"""Deterministic state of the autonomous build, read from GitHub only; the lead follows its output and never orders work itself.

Usage (read-only, prints JSON):
    python3 -I ops/conductor/state.py                 # full state
    python3 -I ops/conductor/state.py --status-body   # markdown body for the status issue

Inputs, all through `gh api` GET: unit issues (label `unit`, hidden header `<!-- unit: {...} -->`), open and
recently merged pull requests into main with their check runs, the status issue, every issue open or closed
with the kill switch `conductor:pause`, legacy `needs-operator` tickets, the dispatched proof.yml and release.yml
runs on main (read the same way release.yml reads them: newest completed run per run name), the head of main,
`docs/autonomy/progress.json` on the state branch (lease, units the lease holder reports alive, usage-limit
stops), CHANGELOG, the release verdict, the merged `claude/release-<version>` pull request and the release tag.
A `state:building` unit without a PR whose workflow the live lease holder has not reported within
`orphan_after_s` is an orphan: the next step resumes it. The repository is public: a unit issue, or a
dependency read by number, whose author_association is not OWNER, MEMBER or COLLABORATOR is never scheduled
(blocked with why `untrusted author`). The verdict counts only when its single `commit: <sha>` line names the
commit the merged release PR was merged onto, that merge is the head of main and the PR changed only the
verdict file and CHANGELOG. Pure decisions sit at the top, the GitHub reads below.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import github

UNIT_TAG = "<!-- unit:"
PASS_CONCLUSIONS = ("success",)
FAIL_CONCLUSIONS = ("failure", "timed_out", "action_required", "startup_failure", "stale")
INFRA_CONCLUSIONS = ("cancelled",)
BLOCKING_LABELS = ("needs-operator", "state:parked", "state:stuck")
ANTHROPIC_KEEP_LABEL = "op:external"
PAUSE_LABEL = "conductor:pause"
FUTURE_SLACK_S = 300.0
TRUSTED_AUTHORS = ("OWNER", "MEMBER", "COLLABORATOR")
SHA_RX = re.compile(r"[0-9a-f]{40}")


# ---------------------------------------------------------------- pure decisions


def load_config(path: Optional[str] = None) -> dict:
    """Read ops/conductor/config.json (or the given file)."""
    with open(path or os.path.join(HERE, "config.json"), encoding="utf-8") as handle:
        return json.load(handle)


def _epoch(value: object) -> Optional[float]:
    """Return a number of epoch seconds, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def lease_future(progress: dict, now: float) -> bool:
    """Return whether the lease names a beat further ahead than the clock slack; such a lease never expires (corrupt)."""
    lease = progress.get("lease") if isinstance(progress.get("lease"), dict) else {}
    beat = _epoch(lease.get("beat_at"))
    return bool(lease.get("holder")) and beat is not None and beat > now + FUTURE_SLACK_S


def lease_age(progress: dict, now: float) -> Optional[float]:
    """Return the age of the lease in seconds, or None without a valid lease (missing, or a beat in the future)."""
    lease = progress.get("lease") if isinstance(progress.get("lease"), dict) else {}
    beat = _epoch(lease.get("beat_at"))
    if not lease.get("holder") or beat is None or lease_future(progress, now):
        return None
    return max(0.0, now - beat)


def live_units(progress: dict, now: float, lease_max_age_s: float, orphan_after_s: float) -> List[int]:
    """Return the units whose workflow the live lease holder reported alive within orphan_after_s."""
    age = lease_age(progress, now)
    if age is None or age > lease_max_age_s:
        return []
    holder = progress["lease"]["holder"]
    units = progress.get("units") if isinstance(progress.get("units"), dict) else {}
    out = []
    for key, rec in units.items():
        beat = _epoch(rec.get("beat_at")) if isinstance(rec, dict) else None
        if (beat is not None and str(key).isdigit() and rec.get("holder") == holder
                and -FUTURE_SLACK_S <= now - beat <= orphan_after_s):
            out.append(int(key))
    return sorted(out)


def glob_regex(glob: str) -> "re.Pattern[str]":
    """Compile a path glob: `**/` spans directories, `*` and `?` stop at `/`."""
    out: List[str] = []
    i = 0
    while i < len(glob):
        at_segment = i == 0 or glob[i - 1] == "/"
        if at_segment and glob.startswith("**/", i):
            out.append("(?:[^/]*/)*")
            i += 3
        elif at_segment and glob.startswith("**", i) and i + 2 == len(glob):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _literal_prefix(glob: str) -> str:
    """Return the part of a glob before its first wildcard."""
    cut = len(glob)
    for ch in "*?[":
        pos = glob.find(ch)
        if pos != -1:
            cut = min(cut, pos)
    return glob[:cut]


def globs_overlap(a: str, b: str) -> bool:
    """Return whether two path globs may name a common file; unsure means overlap."""
    pa, pb = _literal_prefix(a), _literal_prefix(b)
    if pa.startswith(pb) or pb.startswith(pa):
        return True
    return bool(glob_regex(a).match(b) or glob_regex(b).match(a))


def paths_overlap(a: Sequence[str], b: Sequence[str]) -> bool:
    """Return whether two units' declared paths may collide; a unit without paths collides with every unit."""
    if not a or not b:
        return True
    return any(globs_overlap(x, y) for x in a for y in b)


def collides(a: dict, b: dict) -> bool:
    """Return whether two units may not run together; issue-only kinds (writes None) collide with nothing."""
    if a.get("writes") is None or b.get("writes") is None:
        return False
    return paths_overlap(a["writes"], b["writes"])


def parse_unit_header(body: str) -> Optional[dict]:
    """Return the first `<!-- unit: {...} -->` object of an issue body, or None."""
    text = body or ""
    start = 0
    while True:
        pos = text.find(UNIT_TAG, start)
        if pos == -1:
            return None
        end = text.find("-->", pos)
        if end == -1:
            return None
        try:
            obj = json.loads(text[pos + len(UNIT_TAG):end].strip())
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            return obj
        start = end + 3


def label_names(issue: dict) -> List[str]:
    """Return the label names of an issue or pull request."""
    return [lab["name"] if isinstance(lab, dict) else str(lab) for lab in issue.get("labels", [])]


def label_value(labels: Iterable[str], prefix: str) -> Optional[str]:
    """Return the value of the first `prefix:value` label, or None."""
    for name in labels:
        if name.startswith(prefix + ":"):
            return name[len(prefix) + 1:]
    return None


def trusted(issue: dict) -> bool:
    """Return whether an issue was written by the repository owner, a member or a collaborator."""
    return issue.get("author_association") in TRUSTED_AUTHORS


def make_unit(issue: dict, cfg: dict) -> dict:
    """Turn one unit issue into a unit record; labels win over the header for kind, slice and risk."""
    labels = label_names(issue)
    header = parse_unit_header(issue.get("body") or "")
    head = header or {}
    kind = label_value(labels, "kind") or str(head.get("kind") or "build")
    tags = [str(t) for t in head.get("tags", [])]
    paths = [str(p) for p in head.get("paths", []) if str(p).strip()]
    workflow = cfg["workflows"].get(kind)
    if workflow == cfg["workflows"].get("build") and cfg["team_tag"] in tags:
        workflow = cfg["team_workflow"]
    return {
        "number": int(issue["number"]),
        "title": issue.get("title", ""),
        "open": issue.get("state") == "open",
        "done": issue.get("state") == "closed" and issue.get("state_reason") != "not_planned",
        "trusted": trusted(issue),
        "labels": labels,
        "header_ok": header is not None,
        "kind": kind,
        "workflow": workflow,
        "slice": label_value(labels, "slice") or str(head.get("slice") or ""),
        "risk": "high" if ("risk:high" in labels or head.get("risk") == "high") else "low",
        "deps": sorted({int(d) for d in head.get("deps", []) if str(d).isdigit()}),
        "paths": paths,
        "writes": None if kind in cfg["issue_only_kinds"] else paths,
        "proof": [str(p) for p in head.get("proof", [])],
        "tags": tags,
    }


def dep_status(number: int, issues: Dict[int, dict]) -> str:
    """Return done, open, dropped, untrusted (author not OWNER, MEMBER or COLLABORATOR) or missing for one dependency."""
    issue = issues.get(number)
    if issue is None:
        return "missing"
    if not trusted(issue):
        return "untrusted"
    if issue.get("state") == "open":
        return "open"
    return "dropped" if issue.get("state_reason") == "not_planned" else "done"


def find_cycles(units: Sequence[dict]) -> List[List[int]]:
    """Return each dependency cycle among units once, as a sorted list of issue numbers."""
    graph = {u["number"]: list(u["deps"]) for u in units}
    cycles: List[List[int]] = []
    seen_sets: List[frozenset] = []
    for start in sorted(graph):
        stack: List[Tuple[int, List[int]]] = [(start, [start])]
        while stack:
            node, path = stack.pop()
            for nxt in graph.get(node, []):
                if nxt == start:
                    members = frozenset(path)
                    if members not in seen_sets:
                        seen_sets.append(members)
                        cycles.append(sorted(members))
                elif nxt in graph and nxt not in path:
                    stack.append((nxt, path + [nxt]))
    return cycles


def descendants(units: Iterable[dict]) -> Dict[int, int]:
    """Count the open units that transitively depend on each unit (its remaining path weight)."""
    items = list(units)
    children: Dict[int, List[int]] = {}
    for u in items:
        for d in u["deps"]:
            children.setdefault(int(d), []).append(int(u["number"]))
    out: Dict[int, int] = {}
    for u in items:
        seen, stack = set(), list(children.get(int(u["number"]), []))
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack += children.get(n, [])
        out[int(u["number"])] = len(seen)
    return out


def slice_rank(name: str, order: Sequence[str]) -> int:
    """Return the milestone order of a slice; unknown slices sort last."""
    return list(order).index(name) if name in order else len(order)


def priority_key(unit: dict, desc: Dict[int, int], order: Sequence[str]) -> tuple:
    """Order ready units: fix-main, critic S1/S2, longest remaining path, spikes, milestone order, age."""
    tags, labels = unit["tags"], unit["labels"]
    if "main" in tags or "revert" in tags:
        cls = 0
    elif "critic" in labels and ("sev:S1" in labels or "sev:S2" in labels):
        cls = 1
    else:
        cls = 2
    spike = 0 if unit["kind"] == "spike" else 1
    return (cls, -desc.get(unit["number"], 0), spike, slice_rank(unit["slice"], order), unit["number"])


def unit_of_branch(ref: str, prefix: str) -> Optional[int]:
    """Return the unit number of a branch named `<prefix><n>-<slug>`, or None."""
    m = re.match(re.escape(prefix) + r"([1-9][0-9]*)(?:-|$)", ref or "")
    return int(m.group(1)) if m else None


def check_verdict(runs: Sequence[dict], statuses: Sequence[dict], required: Sequence[str]) -> Tuple[str, Dict[str, str]]:
    """Reduce check runs and commit statuses to green, red, infra or pending, plus each required check's state."""
    rows: Dict[str, str] = {}
    for run in runs:
        name = str(run.get("name", ""))
        if run.get("status") != "completed":
            state = "pending"
        elif run.get("conclusion") in PASS_CONCLUSIONS:
            state = "pass"
        elif run.get("conclusion") in FAIL_CONCLUSIONS:
            state = "fail"
        elif run.get("conclusion") in INFRA_CONCLUSIONS:
            state = "infra"
        else:
            state = "other"
        if rows.get(name) != "fail":
            rows[name] = state
    for status in statuses:
        name = str(status.get("context", ""))
        state = {"success": "pass", "failure": "fail", "error": "fail"}.get(str(status.get("state")), "pending")
        if rows.get(name) != "fail":
            rows[name] = state
    req = {name: rows.get(name, "missing") for name in required}
    if "fail" in rows.values():
        return "red", req
    if "infra" in rows.values():
        return "infra", req
    if all(v == "pass" for v in req.values()):
        return "green", req
    return "pending", req


def infra_run_ids(runs: Sequence[dict]) -> List[str]:
    """Return the Actions run ids behind cancelled check runs."""
    out: List[str] = []
    for run in runs:
        if run.get("conclusion") in INFRA_CONCLUSIONS:
            m = re.search(r"/actions/runs/(\d+)", str(run.get("details_url") or run.get("html_url") or ""))
            if m and m.group(1) not in out:
                out.append(m.group(1))
    return out


def pr_action(pr: dict) -> str:
    """Decide the lead's next step for one open unit PR."""
    if pr["verdict"] == "red":
        return "fix"
    if pr["verdict"] == "infra":
        return "rerun"
    if pr["mergeable"] is False or pr["mergeable_state"] == "dirty":
        return "conflict"
    if not pr["auto_merge"]:
        return "enable-auto-merge"
    return "wait"


def select_ready(ready: Sequence[dict], in_flight: Sequence[dict], slots: int, all_open: Sequence[dict],
                 order: Sequence[str]) -> Tuple[List[dict], List[int]]:
    """Pick at most `slots` ready units by priority, never two with overlapping paths; also return the deferred ones."""
    desc = descendants(all_open)
    chosen: List[dict] = []
    deferred: List[int] = []
    for unit in sorted(ready, key=lambda u: priority_key(u, desc, order)):
        if any(collides(unit, other) for other in list(in_flight) + chosen):
            deferred.append(unit["number"])
            continue
        if len(chosen) < slots:
            chosen.append(unit)
    return chosen, deferred


def proof_prefix(stage: str) -> str:
    """Return the proof contract id prefix of a stage (stage 2a -> S2A-)."""
    return "S" + stage.upper() + "-"


def newest_runs(rows: Sequence[dict], title: str) -> Tuple[Optional[dict], bool]:
    """Return the newest completed run with exactly this run name, and whether one with that name is still running."""
    named = [r for r in rows if str(r.get("display_title") or "") == title]
    done = sorted((r for r in named if r.get("status") == "completed"), key=lambda r: str(r.get("created_at") or ""),
                  reverse=True)
    return (done[0] if done else None), any(r.get("status") != "completed" for r in named)


def stage_status(stage: str, run: Optional[dict], workflow: str, base: str) -> dict:
    """Judge a run: green only for a successful workflow_dispatch run of the workflow on main."""
    if run is None:
        return {"stage": stage, "green": False, "why": "no completed run"}
    path = str(run.get("path") or "")
    title = str(run.get("display_title") or "")
    named = re.search(r"\bstage\s+([0-9][a-z]?)\b", title, re.I)
    problems = []
    if not path.endswith("/" + workflow) and path != workflow:
        problems.append(f"run is not {workflow}")
    if run.get("head_branch") != base:
        problems.append(f"run is not on {base}")
    if run.get("event") != "workflow_dispatch":
        problems.append("run was not dispatched")
    if named and named.group(1).lower() != stage.lower():
        problems.append(f"run names stage {named.group(1)}")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        problems.append(f"run is {run.get('status')}/{run.get('conclusion')}")
    return {"stage": stage, "green": not problems, "run": run.get("html_url") or run.get("id"),
            "why": "; ".join(problems) or "green"}


def dry_run_green(rows: Sequence[dict], version: str, main_sha: Optional[str], workflow: str, base: str) -> bool:
    """Return whether a successful dry run `release <version> dry_run=true` exists for the current head of main."""
    title = f"release {version} dry_run=true"
    for run in rows:
        if (str(run.get("display_title") or "") == title and main_sha and run.get("head_sha") == main_sha
                and stage_status("dry-run", run, workflow, base)["green"]):
            return True
    return False


def changelog_has(text: str, version: str) -> bool:
    """Return whether a CHANGELOG has the heading release.yml demands: `## <version>` or `## [<version>]`, v allowed."""
    return bool(re.search(r"^## \[?v?" + re.escape(version) + r"\]?(\s|$)", text or "", re.M))


def verdict_is_release(text: str) -> bool:
    """Return whether a judge verdict file has exactly one line starting with `verdict:` and it is `verdict: release`."""
    return [line for line in (text or "").splitlines() if line.startswith("verdict:")] == ["verdict: release"]


def verdict_commit(text: str) -> Optional[str]:
    """Return the sha of the only line starting with `commit:` when it is exactly `commit: <40 hex>`, else None."""
    lines = [line for line in (text or "").splitlines() if line.startswith("commit:")]
    if len(lines) != 1 or not re.fullmatch(r"commit: [0-9a-f]{40}", lines[0]):
        return None
    return lines[0][len("commit: "):]


def release_pr_of(rows: Sequence[dict], version: str, repo: str) -> Optional[dict]:
    """Return the newest merged pull request from this repository's branch `claude/release-<version>`, or None."""
    mine = [p for p in rows if isinstance(p, dict) and p.get("merged_at")
            and (p.get("head") or {}).get("ref") == f"claude/release-{version}"
            and ((p.get("head") or {}).get("repo") or {}).get("full_name") == repo]
    return max(mine, key=lambda p: str(p.get("merged_at")), default=None)


def verdict_bound(judged: Optional[str], pr: Optional[dict], merge: Optional[dict], files: Sequence[str],
                  main_sha: Optional[str], allowed: Sequence[str]) -> bool:
    """Return whether the verdict is bound to the release merge: that merge is main's head, its other parent is
    the judged commit, and the release PR changed only the allowed files (the verdict and CHANGELOG)."""
    if not judged or not isinstance(pr, dict) or not isinstance(merge, dict) or not main_sha:
        return False
    parents = [str(p.get("sha")) for p in merge.get("parents", []) if isinstance(p, dict)]
    head_sha = (pr.get("head") or {}).get("sha")
    return (pr.get("merge_commit_sha") == main_sha and merge.get("sha") == main_sha and len(parents) == 2
            and judged in parents and judged != head_sha and head_sha in parents
            and bool(files) and all(f in allowed for f in files))


def release_checks(stages: Sequence[dict], changelog: Optional[str], verdict: Optional[str], bound: bool,
                   dry_ok: bool, released: bool) -> dict:
    """Return every release condition with its state; release_ready is their AND (and false once released)."""
    checks = {
        "proofs_green": bool(stages) and all(s["green"] for s in stages),
        "changelog_entry": changelog_has(changelog or "", version_of(stages)),
        "judge_verdict": verdict_is_release(verdict or ""),
        "verdict_bound": bound,
        "dry_run_green": dry_ok,
        "not_yet_released": not released,
    }
    return {"checks": checks, "release_ready": all(checks.values())}


def version_of(stages: Sequence[dict]) -> str:
    """Return the release version the stage records carry (set by compute)."""
    return str(stages[0].get("version", "")) if stages else ""


def forecast(merged_at: Sequence[float], now: float, window_days: int, remaining_next: int,
             remaining_total: int, limit_stops: int) -> dict:
    """Return merge rate per day over the window and the days left to the next milestone and to v0.1."""
    start = now - window_days * 86400
    recent = [t for t in merged_at if t >= start]
    rate = round(len(recent) / float(window_days), 2) if window_days > 0 else 0.0

    def days(n: int) -> Optional[float]:
        """Return the days for n units at the current rate, or None without a rate."""
        return round(n / rate, 1) if rate > 0 else None

    return {"merged_in_window": len(recent), "window_days": window_days, "units_per_day": rate,
            "remaining_next_milestone": remaining_next, "remaining_total": remaining_total,
            "days_to_next_milestone": days(remaining_next), "days_to_v0_1": days(remaining_total),
            "limit_stops": limit_stops}


def legacy_operator(issues: Sequence[dict]) -> List[dict]:
    """List open non-unit needs-operator tickets: clear the label, except the Anthropic request (op:external)."""
    out = []
    for issue in issues:
        labels = label_names(issue)
        if "needs-operator" not in labels or "unit" in labels or issue.get("state") != "open":
            continue
        out.append({"number": int(issue["number"]), "title": issue.get("title", ""),
                    "action": "keep" if ANTHROPIC_KEEP_LABEL in labels else "clear"})
    return out


def next_steps(s: dict) -> List[dict]:
    """Order the lead's next actions; the lead takes the first one it can do and re-runs state.py afterwards."""
    if s["paused"]:
        return [{"do": "pause", "why": "label conductor:pause on an issue"}]
    if s["goal_met"]:
        return [{"do": "stop", "why": "v" + s["release"]["version"] + " released and every milestone proof green"}]
    steps: List[dict] = []
    for pr in s["prs"]:
        if pr["action"] == "rerun":
            steps.append({"do": "rerun", "pr": pr["number"], "unit": pr["unit"], "runs": pr["infra_runs"]})
        elif pr["action"] != "wait":
            steps.append({"do": pr["action"], "pr": pr["number"], "unit": pr["unit"]})
    for number in s["orphans"]:
        steps.append({"do": "resume-unit", "unit": number,
                      "why": "state:building without a PR and without a live workflow of the lease holder"})
    idle = not s["ready"] and not s["in_flight"] and not s["prs"] and not s["orphans"]
    rel = s["release"]
    if rel["release_ready"] and not rel["running"]:
        steps.append({"do": "dispatch-release", "dry_run": False, "version": rel["version"]})
    elif rel["checks"]["proofs_green"] and not rel["release_ready"] and not rel["running"] and idle:
        prep = {"do": "release-prep", "missing": [k for k, v in rel["checks"].items() if not v]}
        if rel["dry_run_red"]:
            prep["dry_run_red"] = rel["dry_run_red"]
        steps.append(prep)
    for st in s["milestones"]:
        if not st["green"] and not st["running"] and st["done_units"] > 0 and st["open_units"] == 0:
            steps.append({"do": "dispatch-proof", "stage": st["stage"]})
    clear = [x["number"] for x in s["legacy_operator"] if x["action"] == "clear"]
    if clear:
        steps.append({"do": "clear-needs-operator", "issues": clear})
    for unit in s["pick"]:
        steps.append({"do": "start-unit", "unit": unit["number"], "kind": unit["kind"], "workflow": unit["workflow"]})
    if idle and not rel["checks"]["proofs_green"]:
        steps.append({"do": "plan", "why": "no ready, running or open unit"})
    if not steps:
        steps.append({"do": "wait", "why": "release.yml is running" if rel["running"]
                      else "units in flight, PRs or proof runs waiting for checks"})
    return steps


# ---------------------------------------------------------------- GitHub reads


def iso_epoch(text: Optional[str]) -> float:
    """Parse a GitHub ISO timestamp to epoch seconds (0 for none)."""
    if not text:
        return 0.0
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()


def decode_content(data: object) -> Optional[str]:
    """Decode a contents API answer to text, or None."""
    if not isinstance(data, dict) or data.get("encoding") != "base64":
        return None
    return base64.b64decode(data.get("content") or "").decode("utf-8", errors="replace")


def read_progress(t: github.Transport, cfg: dict) -> dict:
    """Read progress.json from the state branch through the contents API; absent means empty progress."""
    text = decode_content(github.get(t, f"repos/{t.repo}/contents/{cfg['progress_path']}?ref={cfg['state_branch']}"))
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {"corrupt": True}
    return data if isinstance(data, dict) else {"corrupt": True}


def _pr_record(t: github.Transport, pr: dict, cfg: dict) -> dict:
    """Read one open unit PR in full with its checks and reduce it to a record."""
    full = github.get(t, f"repos/{t.repo}/pulls/{pr['number']}") or pr
    sha = full["head"]["sha"]
    runs = github.get_all(t, f"repos/{t.repo}/commits/{sha}/check-runs", key="check_runs")
    status = github.get(t, f"repos/{t.repo}/commits/{sha}/status") or {}
    verdict, required = check_verdict(runs, status.get("statuses", []) if isinstance(status, dict) else [],
                                      cfg["required_checks"])
    rec = {"number": int(full["number"]), "head": full["head"]["ref"], "sha": sha,
           "unit": unit_of_branch(full["head"]["ref"], cfg["unit_branch_prefix"]),
           "draft": bool(full.get("draft")), "mergeable": full.get("mergeable"),
           "mergeable_state": full.get("mergeable_state"), "auto_merge": full.get("auto_merge") is not None,
           "verdict": verdict, "required": required, "infra_runs": infra_run_ids(runs),
           "merge_ready": verdict == "green" and full.get("mergeable") is True
           and full.get("mergeable_state") in ("clean", "has_hooks")}
    rec["action"] = pr_action(rec)
    return rec


def dispatched_runs(t: github.Transport, workflow: str, base: str) -> List[dict]:
    """Read the newest 100 dispatched runs of a workflow on the base branch (an absent workflow means none)."""
    data = github.get(t, f"repos/{t.repo}/actions/workflows/{workflow}/runs?branch={base}&event=workflow_dispatch"
                         "&per_page=100")
    rows = data.get("workflow_runs") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _milestones(rows: Sequence[dict], cfg: dict, units: Sequence[dict]) -> List[dict]:
    """Judge every stage by its newest completed `proof stage <s>` run and count its open and done units."""
    out = []
    for stage in cfg["stages"]:
        run, running = newest_runs(rows, f"proof stage {stage}")
        st = stage_status(stage, run, cfg["proof_workflow"], cfg["base"])
        st["running"] = running
        st["version"] = cfg["release_version"]
        prefix = proof_prefix(stage)
        mine = [u for u in units if any(p.upper().startswith(prefix) for p in u["proof"])]
        st["open_units"] = sum(1 for u in mine if u["open"])
        st["done_units"] = sum(1 for u in mine if u["done"])
        out.append(st)
    return out


def _verdict_bound(t: github.Transport, cfg: dict, verdict: Optional[str], closed: Sequence[dict],
                   main_sha: Optional[str]) -> bool:
    """Read the merged release PR, its merge commit and its files, and judge whether the verdict is bound to them."""
    version = cfg["release_version"]
    judged = verdict_commit(verdict or "")
    found = release_pr_of(closed, version, t.repo)
    pr = github.get(t, f"repos/{t.repo}/pulls/{int(found['number'])}") if judged and found else None
    merge_sha = str(pr.get("merge_commit_sha") or "") if isinstance(pr, dict) else ""
    merge = github.get(t, f"repos/{t.repo}/commits/{merge_sha}") if SHA_RX.fullmatch(merge_sha) else None
    files = ([str(f.get("filename")) for f in github.get_all(t, f"repos/{t.repo}/pulls/{int(found['number'])}/files")]
             if isinstance(merge, dict) and found else [])
    allowed = (cfg["verdict_path"].format(version=version), cfg["changelog_path"])
    return verdict_bound(judged, pr if isinstance(pr, dict) and pr.get("merged_at") else None,
                         merge if isinstance(merge, dict) else None, files, main_sha, allowed)


def compute(t: github.Transport, cfg: dict, now: float) -> dict:
    """Read GitHub and return the whole state the lead acts on."""
    repo, base = t.repo, cfg["base"]
    progress = read_progress(t, cfg)
    raw_units = [i for i in github.get_all(t, f"repos/{repo}/issues?state=all&labels=unit") if "pull_request" not in i]
    issues = {int(i["number"]): i for i in raw_units}
    every = [make_unit(i, cfg) for i in raw_units]
    units = [u for u in every if u["trusted"]]
    for dep in sorted({d for u in units if u["open"] for d in u["deps"]} - set(issues)):
        found = github.get(t, f"repos/{repo}/issues/{dep}")
        if isinstance(found, dict):
            issues[dep] = found
    prs_raw = [p for p in github.get_all(t, f"repos/{repo}/pulls?state=open&base={base}")
               if str(p.get("head", {}).get("ref", "")).startswith(cfg["head_prefix"])
               and p.get("head", {}).get("repo", {}).get("full_name") == repo]
    prs = [_pr_record(t, p, cfg) for p in prs_raw]
    pr_units = {p["unit"] for p in prs if p["unit"]}
    merged_rows = t.request("GET", f"repos/{repo}/pulls?state=closed&base={base}&sort=updated&direction=desc&per_page=100&page=1")
    closed = [p for p in (merged_rows if isinstance(merged_rows, list) else []) if isinstance(p, dict)]
    merged = [p for p in closed if p.get("merged_at")
              and unit_of_branch(p.get("head", {}).get("ref", ""), cfg["unit_branch_prefix"])]
    status_issues = [i for i in github.get_all(t, f"repos/{repo}/issues?state=open&labels=conductor")
                     if i.get("title") == cfg["status_title"] and "pull_request" not in i]
    paused = bool(github.get_all(t, f"repos/{repo}/issues?state=all&labels={PAUSE_LABEL}"))
    legacy = legacy_operator([i for i in github.get_all(t, f"repos/{repo}/issues?state=open&labels=needs-operator")
                              if "pull_request" not in i])
    alive = set(live_units(progress, now, float(cfg["lease_max_age_s"]), float(cfg["orphan_after_s"])))

    open_units = [u for u in units if u["open"]]
    cycles = find_cycles(open_units)
    in_cycle = {n for c in cycles for n in c}
    in_flight, ready, orphans = [], [], []
    blocked = [dict(u, why="untrusted author", blocked_by=[]) for u in every if u["open"] and not u["trusted"]]
    for u in open_units:
        u["blocked_by"] = [{"issue": d, "status": dep_status(d, issues)} for d in u["deps"]
                           if dep_status(d, issues) != "done"]
        hit = [lab for lab in BLOCKING_LABELS if lab in u["labels"]]
        if u["number"] in pr_units or ("state:building" in u["labels"] and u["number"] in alive):
            in_flight.append(u)
        elif "state:building" in u["labels"]:
            orphans.append(u["number"])
        elif not u["header_ok"]:
            blocked.append(dict(u, why="no unit header"))
        elif u["workflow"] is None:
            blocked.append(dict(u, why="unknown kind " + u["kind"]))
        elif u["number"] in in_cycle:
            blocked.append(dict(u, why="dependency cycle"))
        elif hit:
            blocked.append(dict(u, why="label " + hit[0]))
        elif any(b["status"] == "untrusted" for b in u["blocked_by"]):
            blocked.append(dict(u, why="untrusted author"))
        elif u["blocked_by"]:
            blocked.append(dict(u, why="dependencies"))
        else:
            ready.append(u)
    wip = int(cfg["wip_max"]) if len(merged) >= 3 else int(cfg["wip_start"])
    slots = max(0, wip - len(in_flight))
    pick, deferred = select_ready(ready, in_flight, slots, open_units, cfg["slices"])
    desc = descendants(open_units)

    milestones = _milestones(dispatched_runs(t, cfg["proof_workflow"], base), cfg, units)
    version = cfg["release_version"]
    tag = github.get(t, f"repos/{repo}/releases/tags/v{version}")
    released = isinstance(tag, dict) and not tag.get("draft") and not tag.get("prerelease")
    changelog = decode_content(github.get(t, f"repos/{repo}/contents/{cfg['changelog_path']}?ref={base}"))
    verdict_path = cfg["verdict_path"].format(version=version)
    verdict = decode_content(github.get(t, f"repos/{repo}/contents/{verdict_path}?ref={base}"))
    head = github.get(t, f"repos/{repo}/commits/{base}")
    main_sha = str(head.get("sha")) if isinstance(head, dict) and head.get("sha") else None
    bound = _verdict_bound(t, cfg, verdict, closed, main_sha)
    release_rows = dispatched_runs(t, cfg["release_workflow"], base)
    dry_ok = dry_run_green(release_rows, version, main_sha, cfg["release_workflow"], base)
    release = release_checks(milestones, changelog, verdict, bound, dry_ok, released)
    release["version"] = version
    release["released"] = released
    release["main_sha"] = main_sha
    release["running"] = any(newest_runs(release_rows, f"release {version} dry_run={d}")[1] for d in ("true", "false"))
    head_dry, _ = newest_runs([r for r in release_rows if main_sha and r.get("head_sha") == main_sha],
                              f"release {version} dry_run=true")
    release["dry_run_red"] = (head_dry.get("html_url") or str(head_dry.get("id"))) if head_dry and not dry_ok else None

    next_open = next((m for m in milestones if not m["green"]), None)
    fc = forecast([iso_epoch(p.get("merged_at")) for p in merged], now, int(cfg["forecast_window_days"]),
                  next_open["open_units"] if next_open else 0, len(open_units),
                  int(progress.get("limit_stops") or 0))
    last = max(merged, key=lambda p: iso_epoch(p.get("merged_at")), default=None)
    state = {
        "now": now, "repo": repo, "paused": paused,
        "status_issue": status_issues[0]["number"] if status_issues else None,
        "wip": wip, "slots": slots,
        "in_flight": [{"unit": u["number"], "kind": u["kind"], "paths": u["paths"]} for u in in_flight],
        "orphans": sorted(orphans),
        "ready": [u["number"] for u in sorted(ready, key=lambda u: priority_key(u, desc, cfg["slices"]))],
        "pick": [{"number": u["number"], "title": u["title"], "kind": u["kind"], "workflow": u["workflow"],
                  "slice": u["slice"], "risk": u["risk"], "tags": u["tags"], "paths": u["paths"]} for u in pick],
        "deferred_overlap": deferred,
        "blocked": [{"unit": u["number"], "why": u["why"], "blocked_by": u["blocked_by"]} for u in blocked],
        "cycles": cycles, "prs": prs, "legacy_operator": legacy, "milestones": milestones,
        "next_milestone": next_open["stage"] if next_open else None,
        "release": release, "forecast": fc,
        "last_merged": {"pr": last["number"], "head": last["head"]["ref"], "at": last["merged_at"]} if last else None,
        "progress_corrupt": bool(progress.get("corrupt")) or lease_future(progress, now),
    }
    state["goal_met"] = released and all(m["green"] for m in milestones)
    state["next"] = next_steps(state)
    return state


def render_status(s: dict) -> str:
    """Render the status issue body (English) from a computed state."""
    fc = s["forecast"]

    def n_a(value: object) -> str:
        """Render None as n/a."""
        return "n/a" if value is None else str(value)

    last = s["last_merged"]
    lines = [
        "<!-- conductor-status -->",
        "# Conductor status",
        "",
        f"- Paused: {'yes' if s['paused'] else 'no'}; goal met: {'yes' if s['goal_met'] else 'no'}",
        f"- In flight: {', '.join('#' + str(u['unit']) for u in s['in_flight']) or 'none'}; WIP {s['wip']}; "
        f"orphaned: {', '.join('#' + str(n) for n in s['orphans']) or 'none'}",
        f"- Ready: {', '.join('#' + str(n) for n in s['ready']) or 'none'}; blocked: {len(s['blocked'])}",
        f"- Open PRs: {', '.join('#' + str(p['number']) + ' ' + p['verdict'] for p in s['prs']) or 'none'}",
        f"- Last merged: {('#' + str(last['pr']) + ' at ' + last['at']) if last else 'none'}",
        f"- Milestones: {', '.join(m['stage'] + (' green' if m['green'] else ' open') for m in s['milestones'])}",
        f"- Release v{s['release']['version']}: ready {s['release']['release_ready']}, released {s['release']['released']}",
        "",
        "## Forecast",
        "",
        f"- Units merged per day (last {fc['window_days']} days): {fc['units_per_day']}",
        f"- Remaining to the next milestone ({s['next_milestone'] or 'none'}): {fc['remaining_next_milestone']} units, "
        f"about {n_a(fc['days_to_next_milestone'])} days",
        f"- Remaining to v0.1: {fc['remaining_total']} units, about {n_a(fc['days_to_v0_1'])} days",
        f"- Usage-limit stops recorded: {fc['limit_stops']}",
        "",
        f"Next step: {json.dumps(s['next'][0], sort_keys=True)}",
        "",
        "Pause the build by adding the label `conductor:pause` to this issue.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Print the computed state as JSON (or the status body) and exit 0; GitHub errors exit 1."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--status-body", action="store_true", help="print the status issue body instead of JSON")
    parser.add_argument("--now", type=float, default=None, help="epoch seconds (tests only)")
    args = parser.parse_args(argv)
    cfg = load_config()
    try:
        state = compute(github.GhTransport(cfg["repo"]), cfg, args.now if args.now is not None else time.time())
    except (github.GitHubError, github.RouteRefused) as err:
        sys.stderr.write(f"state: {err}\n")
        return 1
    sys.stdout.write(render_status(state) if args.status_body else json.dumps(state, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
