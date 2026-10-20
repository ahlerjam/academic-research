"""The only mutation interface of the cloud lead: a fixed verb set over GitHub REST, every argument validated.

Usage: python3 -I ops/conductor/gh_ops.py <verb> [options]   (prints JSON; exit 0 done, 1 GitHub error, 2 refused)

Verbs: open-pr, enable-auto-merge, label, comment, create-issue, close-issue, clear-needs-operator,
apply-actions, dispatch-release, dispatch-proof, rerun-failed, update-status-issue, ensure-labels. There is no
merge verb, no settings, ruleset or branch-protection verb, no contents or ref write and no workflow-file change;
github.check_route refuses those routes a second time. GitHub merges a unit PR itself once auto-merge is on
and the required checks `gate` and `protect` are green.

apply-actions files what an issue-only workflow (ar-plan, ar-judge, ar-critic, ar-triage, ar-release) returns
in its `actions` list: create-issue, comment, label and close-issue, validated as a whole before anything is
sent, in list order, with `{{ref}}` placeholders replaced by the numbers of issues created earlier in the
same list. Progress is kept next to the action file, so a rerun after an error never files an action twice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from typing import Dict, List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import github
import state

HEAD_RX = re.compile(r"^claude/[A-Za-z0-9_-][A-Za-z0-9._-]*(?:/[A-Za-z0-9_-][A-Za-z0-9._-]*)*$")
VERSION_RX = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA256_RX = re.compile(r"^[0-9a-f]{64}$")
CHARTER = "docs/autonomy/charter.md"
OPERATOR_ONLY_REMOVALS = ("conductor:pause",)
ACTION_VERBS = ("create-issue", "comment", "label", "close-issue")
REF_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
PLACEHOLDER_RX = re.compile(r"\{\{([^{}]*)\}\}")
MAX_ACTIONS = 80
MAX_ACTION_FILE = 2_000_000
INBOX = "inbox"
INBOX_BODY = ("Operator inbox of the autonomous build: kernel patches (`op:kernel`) and the request to Anthropic. "
              "Nothing here blocks the build (docs/autonomy/charter.md section 4).\n")


class Refused(Exception):
    """A verb or argument outside the allowed set; nothing was sent."""


def load_labels() -> Dict[str, dict]:
    """Return the label catalogue of ops/conductor/labels.json by name."""
    with open(os.path.join(HERE, "labels.json"), encoding="utf-8") as handle:
        return {row["name"]: row for row in json.load(handle)}


def valid_head(head: str, cfg: dict) -> bool:
    """Return whether a branch name is an acceptable claude/* PR head (never the state branch)."""
    return (bool(HEAD_RX.match(head or "")) and len(head) <= 100 and ".." not in head
            and not head.endswith(".lock") and not head.endswith(".") and head != cfg["state_branch"])


def _number(value: str, what: str) -> int:
    """Parse a positive issue, PR or run number."""
    if not re.fullmatch(r"[1-9][0-9]{0,19}", value or ""):
        raise Refused(f"{what} must be a positive number, got {value!r}")
    return int(value)


def _title(value: str) -> str:
    """Validate a one-line title of 1 to 256 characters."""
    if not value or len(value) > 256 or "\n" in value or "\r" in value or not value.strip():
        raise Refused("title must be one line of 1 to 256 characters")
    return value.strip()


def _text(text: str, cfg: dict, what: str) -> str:
    """Validate a non-empty body text within the size limit."""
    if not isinstance(text, str) or not text.strip():
        raise Refused(f"{what} is empty")
    if len(text) > int(cfg["body_max_chars"]):
        raise Refused(f"{what} exceeds {cfg['body_max_chars']} characters")
    return text


def _body(path: str, cfg: dict) -> str:
    """Read a non-empty body file within the size limit."""
    if not path or not os.path.isfile(path):
        raise Refused(f"body file {path!r} does not exist")
    with open(path, encoding="utf-8") as handle:
        return _text(handle.read(), cfg, f"body file {path}")


def _labels(names: Sequence[str], catalogue: Dict[str, dict]) -> List[str]:
    """Validate label names against labels.json."""
    unknown = [n for n in names if n not in catalogue]
    if unknown:
        raise Refused(f"labels not in ops/conductor/labels.json: {', '.join(unknown)}")
    return list(dict.fromkeys(names))


def _label_change(add: Sequence[str], remove: Sequence[str], catalogue: Dict[str, dict]) -> tuple:
    """Validate one label change: known labels, something to do, protected labels never removed."""
    add, remove = _labels(add, catalogue), _labels(remove, catalogue)
    if not add and not remove:
        raise Refused("label needs --add or --remove")
    if "needs-operator" in remove:
        raise Refused("needs-operator is removed only by clear-needs-operator, with the charter rule")
    blocked = [n for n in remove if n in OPERATOR_ONLY_REMOVALS]
    if blocked:
        raise Refused(f"only the operator removes {', '.join(blocked)}")
    return add, remove


def _issue(t: github.Transport, number: int) -> dict:
    """Read one issue or refuse when it does not exist."""
    data = github.get(t, f"repos/{t.repo}/issues/{number}")
    if not isinstance(data, dict):
        raise Refused(f"issue #{number} does not exist")
    return data


def _inbox(t: github.Transport, cfg: dict) -> int:
    """Return the number of the open Operator-Inbox issue, creating it (label conductor) when none exists."""
    found = [i for i in github.get_all(t, f"repos/{t.repo}/issues?state=open")
             if i.get("title") == cfg["inbox_title"] and "pull_request" not in i]
    if found:
        return int(sorted(found, key=lambda i: int(i["number"]))[0]["number"])
    issue = t.request("POST", f"repos/{t.repo}/issues", {"title": cfg["inbox_title"], "body": INBOX_BODY,
                                                         "labels": ["conductor"]})
    if not isinstance(issue, dict) or not issue.get("number"):
        raise github.GitHubError(0, "creating the inbox issue returned no number")
    return int(issue["number"])


def _do_label(t: github.Transport, number: int, add: Sequence[str], remove: Sequence[str]) -> dict:
    """Send one validated label change."""
    if add:
        t.request("POST", f"repos/{t.repo}/issues/{number}/labels", {"labels": list(add)})
    removed, absent = [], []
    for name in remove:
        try:
            t.request("DELETE", f"repos/{t.repo}/issues/{number}/labels/{urllib.parse.quote(name, safe='')}")
            removed.append(name)
        except github.GitHubError as err:
            if err.status != 404:
                raise
            absent.append(name)
    return {"issue": number, "added": list(add), "removed": removed, "absent": absent}


def _do_close(t: github.Transport, number: int, reason: str, text: str) -> dict:
    """Close an issue (never a PR) with an explaining comment."""
    issue = _issue(t, number)
    if "pull_request" in issue:
        raise Refused(f"#{number} is a pull request; gh_ops never closes PRs")
    t.request("POST", f"repos/{t.repo}/issues/{number}/comments", {"body": text})
    t.request("PATCH", f"repos/{t.repo}/issues/{number}", {"state": "closed", "state_reason": reason})
    return {"issue": number, "closed": reason}


def _do_create(t: github.Transport, title: str, text: str, labels: Sequence[str]) -> dict:
    """Create one issue and return its number."""
    issue = t.request("POST", f"repos/{t.repo}/issues", {"title": title, "body": text, "labels": list(labels)})
    return {"issue": issue.get("number") if isinstance(issue, dict) else None, "labels": list(labels)}


def open_pr(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Open a PR from a claude/* branch into main, after the evidence log matches its recorded hash."""
    if not valid_head(a.head, cfg):
        raise Refused(f"head must be a claude/* branch, got {a.head!r}")
    title = _title(a.title)
    body = _body(a.body_file, cfg)
    if not SHA256_RX.match(a.evidence_sha256 or ""):
        raise Refused("--evidence-sha256 must be 64 lowercase hex characters")
    if not os.path.isfile(a.evidence_log or ""):
        raise Refused(f"evidence log {a.evidence_log!r} does not exist")
    with open(a.evidence_log, "rb") as handle:
        actual = hashlib.sha256(handle.read()).hexdigest()
    if actual != a.evidence_sha256:
        raise Refused(f"evidence log hash {actual} differs from the recorded {a.evidence_sha256}")
    body = body.rstrip("\n") + f"\n\nEvidence collected by the lead: `{os.path.basename(a.evidence_log)}` sha256 {actual}\n"
    if len(body) > int(cfg["body_max_chars"]):
        raise Refused(f"body exceeds {cfg['body_max_chars']} characters")
    pr = t.request("POST", f"repos/{t.repo}/pulls", {"title": title, "head": a.head, "base": cfg["base"], "body": body})
    return {"pr": pr.get("number"), "url": pr.get("html_url")} if isinstance(pr, dict) else {"pr": None}


def enable_auto_merge(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Turn on auto-merge (merge method merge) for an open claude/* PR into main through the ccr route."""
    number = _number(a.pr, "--pr")
    pr = github.get(t, f"repos/{t.repo}/pulls/{number}")
    if not isinstance(pr, dict):
        raise Refused(f"PR #{number} does not exist")
    head, base = pr.get("head", {}), pr.get("base", {})
    if pr.get("state") != "open":
        raise Refused(f"PR #{number} is not open")
    if not valid_head(str(head.get("ref", "")), cfg):
        raise Refused(f"PR #{number} head {head.get('ref')!r} is not a claude/* branch")
    if base.get("ref") != cfg["base"]:
        raise Refused(f"PR #{number} does not target {cfg['base']}")
    if head.get("repo", {}).get("full_name") != t.repo:
        raise Refused(f"PR #{number} comes from another repository")
    t.request("PUT", f"repos/{t.repo}/pulls/{number}/ccr/auto_merge", {"merge_method": "merge"})
    return {"pr": number, "auto_merge": "merge"}


def label(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Add or remove labels on an issue or PR; needs-operator leaves only through clear-needs-operator."""
    number = _number(a.issue, "--issue")
    add, remove = _label_change(a.add or [], a.remove or [], load_labels())
    return _do_label(t, number, add, remove)


def comment(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Post one comment on an issue or PR; `--issue inbox` names the Operator-Inbox issue."""
    text = _body(a.body_file, cfg)
    number = _inbox(t, cfg) if a.issue == INBOX else _number(a.issue, "--issue")
    t.request("POST", f"repos/{t.repo}/issues/{number}/comments", {"body": text})
    return {"issue": number, "commented": True}


def create_issue(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Create an issue with labels from labels.json."""
    labels = _labels(a.label or [], load_labels())
    return _do_create(t, _title(a.title), _body(a.body_file, cfg), labels)


def close_issue(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Close an issue with a reason and a comment that explains it; PRs are never closed."""
    number = _number(a.issue, "--issue")
    if a.reason not in ("completed", "not_planned"):
        raise Refused("--reason must be completed or not_planned")
    return _do_close(t, number, a.reason, _body(a.comment_file, cfg))


def clear_needs_operator(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Remove needs-operator from a legacy ticket with a comment naming the charter rule; the Anthropic request stays."""
    number = _number(a.issue, "--issue")
    if a.charter_section != "3":
        raise Refused("--charter-section must be 3 (agents decide without asking); section 4 items stay with the operator")
    reason = (a.reason or "").strip()
    if len(reason) < 10 or "\n" in reason or len(reason) > 500:
        raise Refused("--reason must be one line of 10 to 500 characters naming what replaces the operator action")
    issue = _issue(t, number)
    labels = state.label_names(issue)
    if "needs-operator" not in labels:
        raise Refused(f"#{number} has no needs-operator label")
    if state.ANTHROPIC_KEEP_LABEL in labels:
        raise Refused(f"#{number} carries {state.ANTHROPIC_KEEP_LABEL} (the Anthropic request); it stays with the operator")
    body = (f"The lead removes `needs-operator`: {CHARTER} section {a.charter_section} (agents decide without asking) "
            f"replaces the operator action. {reason}")
    t.request("POST", f"repos/{t.repo}/issues/{number}/comments", {"body": body})
    t.request("DELETE", f"repos/{t.repo}/issues/{number}/labels/needs-operator")
    return {"issue": number, "cleared": "needs-operator"}


def _placeholders(text: str, defined: Sequence[str], where: str) -> None:
    """Refuse a `{{ref}}` placeholder that names no issue created earlier in the list."""
    for ref in PLACEHOLDER_RX.findall(text or ""):
        if ref not in defined:
            raise Refused(f"{where}: placeholder {{{{{ref}}}}} names no issue created earlier in this list")


def _target(act: dict, defined: Sequence[str], where: str) -> dict:
    """Validate the target of a non-create action: exactly one of issue, ref or inbox."""
    keys = [k for k in ("issue", "ref", INBOX) if act.get(k) not in (None, False, "")]
    if len(keys) != 1:
        raise Refused(f"{where}: name exactly one target: issue, ref or inbox")
    if keys[0] == "issue":
        value = act["issue"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise Refused(f"{where}: issue must be a positive integer")
        return {"issue": value}
    if keys[0] == "ref":
        if act["ref"] not in defined:
            raise Refused(f"{where}: ref {act['ref']!r} names no issue created earlier in this list")
        return {"ref": act["ref"]}
    if act[INBOX] is not True:
        raise Refused(f"{where}: inbox must be true")
    return {INBOX: True}


def plan_actions(data: object, cfg: dict, catalogue: Dict[str, dict]) -> List[dict]:
    """Validate a whole action list before anything is sent and return it normalised."""
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        raise Refused('the action file must hold {"actions": [...]}')
    actions = data["actions"]
    if not actions or len(actions) > MAX_ACTIONS:
        raise Refused(f"the action list must hold 1 to {MAX_ACTIONS} actions")
    defined: List[str] = []
    out: List[dict] = []
    for i, act in enumerate(actions):
        where = f"action {i}"
        if not isinstance(act, dict) or act.get("verb") not in ACTION_VERBS:
            raise Refused(f"{where}: verb must be one of {', '.join(ACTION_VERBS)}")
        verb = act["verb"]
        optional = verb == "label" and act.get("body") in (None, "")
        body = "" if optional else _text(act.get("body"), cfg, f"{where} body")
        _placeholders(body, defined, where)
        if verb == "create-issue":
            ref = act.get("ref")
            if not isinstance(ref, str) or not REF_RX.match(ref) or ref in defined:
                raise Refused(f"{where}: create-issue needs a new ref of lowercase letters, digits and dashes")
            title = act.get("title")
            _placeholders(title or "", defined, where)
            _title(PLACEHOLDER_RX.sub("1", title or ""))
            labels = act.get("labels") or []
            if not isinstance(labels, list):
                raise Refused(f"{where}: labels must be a list")
            out.append({"verb": verb, "ref": ref, "title": title, "body": body,
                        "labels": _labels([str(x) for x in labels], catalogue)})
            defined.append(ref)
            continue
        rec = dict(_target(act, defined, where), verb=verb, body=body)
        if verb == "label":
            add, remove = act.get("add") or [], act.get("remove") or []
            if not isinstance(add, list) or not isinstance(remove, list):
                raise Refused(f"{where}: add and remove must be lists")
            rec["add"], rec["remove"] = _label_change([str(x) for x in add], [str(x) for x in remove], catalogue)
        elif verb == "close-issue":
            if act.get("reason") not in ("completed", "not_planned"):
                raise Refused(f"{where}: reason must be completed or not_planned")
            rec["reason"] = act["reason"]
        out.append(rec)
    return out


def _fill(text: str, refs: Dict[str, int]) -> str:
    """Replace every `{{ref}}` with the number of the issue created for it."""
    return PLACEHOLDER_RX.sub(lambda m: str(refs[m.group(1)]), text)


def _read_progress(path: str, digest: str) -> dict:
    """Read the progress of an earlier run of the same action file; a changed file is refused."""
    if not os.path.isfile(path):
        return {"digest": digest, "done": 0, "refs": {}, "results": []}
    with open(path, encoding="utf-8") as handle:
        progress = json.load(handle)
    if progress.get("digest") != digest:
        raise Refused(f"the action file changed after a partial run; restore it or remove {path} after checking "
                      "which actions were filed")
    return progress


def _write_progress(path: str, progress: dict) -> None:
    """Store the progress after every filed action."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(progress, handle, sort_keys=True)


def apply_actions(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """File a workflow's action list in order; a rerun continues after the last filed action."""
    if not a.file or not os.path.isfile(a.file):
        raise Refused(f"action file {a.file!r} does not exist")
    if os.path.getsize(a.file) > MAX_ACTION_FILE:
        raise Refused(f"action file {a.file} exceeds {MAX_ACTION_FILE} bytes")
    with open(a.file, "rb") as handle:
        raw = handle.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as err:
        raise Refused(f"action file {a.file} is not JSON: {err}") from err
    actions = plan_actions(data, cfg, load_labels())
    done_path = a.file + ".done.json"
    progress = _read_progress(done_path, hashlib.sha256(raw).hexdigest())
    refs: Dict[str, int] = {k: int(v) for k, v in progress["refs"].items()}
    start = int(progress["done"])
    for i in range(start, len(actions)):
        act = actions[i]
        body = _fill(act["body"], refs)
        if act["verb"] == "create-issue":
            result = _do_create(t, _title(_fill(act["title"], refs)), body, act["labels"])
            if not result["issue"]:
                raise github.GitHubError(0, f"action {i}: creating the issue returned no number")
            refs[act["ref"]] = int(result["issue"])
        else:
            number = refs[act["ref"]] if "ref" in act else _inbox(t, cfg) if INBOX in act else int(act["issue"])
            if act["verb"] == "comment":
                t.request("POST", f"repos/{t.repo}/issues/{number}/comments", {"body": body})
                result = {"issue": number, "commented": True}
            elif act["verb"] == "label":
                result = _do_label(t, number, act["add"], act["remove"])
                if body:
                    t.request("POST", f"repos/{t.repo}/issues/{number}/comments", {"body": body})
            else:
                result = _do_close(t, number, act["reason"], body)
        progress = {"digest": progress["digest"], "done": i + 1, "refs": refs,
                    "results": list(progress["results"]) + [result]}
        _write_progress(done_path, progress)
    return {"applied": len(actions) - start, "skipped_already_filed": start, "refs": refs,
            "progress_file": done_path}


def dispatch_release(t: github.Transport, cfg: dict, a: argparse.Namespace, now: float) -> dict:
    """Dispatch release.yml; dry_run=false only when state.py computes release_ready for exactly this version."""
    if not VERSION_RX.match(a.version or ""):
        raise Refused(f"--version must be X.Y.Z, got {a.version!r}")
    if a.dry_run not in ("true", "false"):
        raise Refused(f"--dry-run must be true or false, got {a.dry_run!r}")
    dry = a.dry_run == "true"
    if not dry:
        if a.version != cfg["release_version"]:
            raise Refused(f"a real release must be version {cfg['release_version']}")
        computed = state.compute(t, cfg, now)
        if not computed["release"]["release_ready"]:
            missing = [k for k, v in computed["release"]["checks"].items() if not v]
            raise Refused(f"release_ready is false ({', '.join(missing)}); dry_run=false refused")
    t.run_workflow(cfg["release_workflow"], cfg["base"], {"dry_run": a.dry_run, "version": a.version})
    return {"workflow": cfg["release_workflow"], "dry_run": dry, "version": a.version}


def dispatch_proof(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Dispatch proof.yml for one milestone stage on main."""
    if a.stage not in cfg["stages"]:
        raise Refused(f"--stage must be one of {', '.join(cfg['stages'])}")
    t.run_workflow(cfg["proof_workflow"], cfg["base"], {"stage": a.stage})
    return {"workflow": cfg["proof_workflow"], "stage": a.stage}


def rerun_failed(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Re-run the failed jobs of a cancelled or failed CI run of a claude/* branch."""
    number = _number(a.run, "--run")
    run = github.get(t, f"repos/{t.repo}/actions/runs/{number}")
    if not isinstance(run, dict):
        raise Refused(f"run {number} does not exist")
    if not valid_head(str(run.get("head_branch") or ""), cfg):
        raise Refused(f"run {number} is not on a claude/* branch")
    if run.get("status") != "completed" or run.get("conclusion") not in ("cancelled", "failure", "timed_out"):
        raise Refused(f"run {number} is {run.get('status')}/{run.get('conclusion')}; nothing to re-run")
    t.request("POST", f"repos/{t.repo}/actions/runs/{number}/rerun-failed-jobs", {})
    return {"run": number, "rerun": True}


def update_status_issue(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Replace the body of the open status issue, creating it (label conductor) when none exists."""
    body = _body(a.body_file, cfg)
    found = [i for i in github.get_all(t, f"repos/{t.repo}/issues?state=open&labels=conductor")
             if i.get("title") == cfg["status_title"] and "pull_request" not in i]
    if found:
        number = int(sorted(found, key=lambda i: int(i["number"]))[0]["number"])
        t.request("PATCH", f"repos/{t.repo}/issues/{number}", {"body": body})
        return {"issue": number, "updated": True}
    issue = t.request("POST", f"repos/{t.repo}/issues", {"title": cfg["status_title"], "body": body, "labels": ["conductor"]})
    return {"issue": issue.get("number") if isinstance(issue, dict) else None, "created": True}


def ensure_labels(t: github.Transport, cfg: dict, a: argparse.Namespace) -> dict:
    """Create the labels of labels.json that the repository lacks; existing labels stay untouched."""
    have = {row.get("name") for row in github.get_all(t, f"repos/{t.repo}/labels")}
    created = []
    for name, row in load_labels().items():
        if name not in have:
            t.request("POST", f"repos/{t.repo}/labels",
                      {"name": name, "color": row["color"], "description": row["description"]})
            created.append(name)
    return {"created": created}


def parser() -> argparse.ArgumentParser:
    """Build the argument parser with the fixed verb set."""
    p = argparse.ArgumentParser(prog="gh_ops.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("open-pr")
    s.add_argument("--head", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--body-file", required=True)
    s.add_argument("--evidence-log", required=True)
    s.add_argument("--evidence-sha256", required=True)
    s = sub.add_parser("enable-auto-merge")
    s.add_argument("--pr", required=True)
    s = sub.add_parser("label")
    s.add_argument("--issue", required=True)
    s.add_argument("--add", action="append")
    s.add_argument("--remove", action="append")
    s = sub.add_parser("comment")
    s.add_argument("--issue", required=True, help="issue or PR number, or `inbox` for the Operator-Inbox issue")
    s.add_argument("--body-file", required=True)
    s = sub.add_parser("create-issue")
    s.add_argument("--title", required=True)
    s.add_argument("--body-file", required=True)
    s.add_argument("--label", action="append")
    s = sub.add_parser("close-issue")
    s.add_argument("--issue", required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--comment-file", required=True)
    s = sub.add_parser("clear-needs-operator")
    s.add_argument("--issue", required=True)
    s.add_argument("--charter-section", required=True)
    s.add_argument("--reason", required=True)
    s = sub.add_parser("apply-actions")
    s.add_argument("--file", required=True, help='JSON file {"actions": [...]} as an issue-only workflow returned it')
    s = sub.add_parser("dispatch-release")
    s.add_argument("--version", required=True)
    s.add_argument("--dry-run", required=True)
    s = sub.add_parser("dispatch-proof")
    s.add_argument("--stage", required=True)
    s = sub.add_parser("rerun-failed")
    s.add_argument("--run", required=True)
    s = sub.add_parser("update-status-issue")
    s.add_argument("--body-file", required=True)
    sub.add_parser("ensure-labels")
    return p


VERBS = {"open-pr": open_pr, "enable-auto-merge": enable_auto_merge, "label": label, "comment": comment,
         "create-issue": create_issue, "close-issue": close_issue, "clear-needs-operator": clear_needs_operator,
         "apply-actions": apply_actions, "dispatch-proof": dispatch_proof, "rerun-failed": rerun_failed,
         "update-status-issue": update_status_issue, "ensure-labels": ensure_labels}


def run(argv: Sequence[str], t: Optional[github.Transport] = None, cfg: Optional[dict] = None,
        now: Optional[float] = None) -> int:
    """Run one verb; return 0 done, 1 GitHub error, 2 refused (nothing sent)."""
    try:
        a = parser().parse_args(list(argv))
    except SystemExit as exc:
        return 2 if exc.code else 0
    cfg = cfg or state.load_config()
    t = t or github.GhTransport(cfg["repo"])
    try:
        if a.verb == "dispatch-release":
            out = dispatch_release(t, cfg, a, now if now is not None else time.time())
        else:
            out = VERBS[a.verb](t, cfg, a)
    except (Refused, github.RouteRefused) as err:
        sys.stderr.write(f"gh_ops: refused: {err}\n")
        return 2
    except github.GitHubError as err:
        sys.stderr.write(f"gh_ops: {err}\n")
        return 1
    sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
