"""Proof contract: every id of gates/proofs/stage-<s>.json needs a passed spec, an artefact and a rejected negative case."""

from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterator, List, Optional, Tuple

from .findings import Finding

STAGES = ("1", "2a", "2b", "3", "4", "5")
OUT = "proof-out"
RULE = "PROOF-CONTRACT"
EVIDENCE = ("e2e", "operator")
ARTEFACTS: Dict[str, Tuple[Tuple[str, ...], bytes]] = {
    "pdf": ((".pdf",), b"%PDF-"),
    "zip": ((".zip",), b"PK\x03\x04"),
    "docx": ((".docx",), b"PK\x03\x04"),
    "png": ((".png",), b"\x89PNG\r\n\x1a\n"),
    "json": ((".json",), b""),
    "tex": ((".tex",), b""),
    "text": ((".txt", ".log", ".md", ".html", ".csv", ".ris", ".bib"), b""),
}
CONTRACT_ID = re.compile(r"^S(1|2A|2B|3|4|5)-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
TITLE_ID = re.compile(r"(?<![A-Z0-9-])(S(?:1|2A|2B|3|4|5)-[A-Z0-9]+(?:-[A-Z0-9]+)*)(?![A-Z0-9-])")
NEGATIVE = re.compile(r"\bnegative\b", re.IGNORECASE)


def contract_path(stage: str) -> str:
    """Return the repository path of a stage's proof contract."""
    return f"gates/proofs/stage-{stage}.json"


def report_path(stage: str) -> str:
    """Return the path of the Playwright JSON report that `make proof STAGE=<s>` writes."""
    return f"{OUT}/stage-{stage}.report.json"


def record_path(cid: str) -> str:
    """Return the path of the evidence record a proof spec writes for one contract id."""
    return f"{OUT}/{cid}.json"


def load_json(tree: str, rel: str) -> Tuple[Optional[object], str]:
    """Return the parsed JSON file and an empty string, or None and the reason it could not be read."""
    try:
        with open(os.path.join(tree, rel), encoding="utf-8") as handle:
            return json.load(handle), ""
    except OSError as err:
        return None, err.strerror or "unreadable"
    except ValueError as err:
        return None, str(err)


def _flat(text: str) -> str:
    """Collapse every whitespace run to one space, so a quote may cross a line break of NORTHSTAR.md."""
    return " ".join(text.split())


def _text(value: object) -> bool:
    """Return whether value is a non-empty string."""
    return isinstance(value, str) and bool(value.strip())


def _entry_problems(stage: str, entry: object, northstar: str) -> List[str]:
    """Return what is wrong with one contract entry."""
    if not isinstance(entry, dict):
        return ["contract entry is not an object"]
    cid = entry.get("id")
    prefix = f"S{stage.upper()}-"
    problems = []
    if not isinstance(cid, str) or not CONTRACT_ID.match(cid) or not cid.startswith(prefix):
        problems.append(f"id {cid!r} must match {prefix}<NAME>")
    if not _text(entry.get("northstar")) or _flat(entry["northstar"]) not in northstar:
        problems.append(f"{cid}: 'northstar' must be a verbatim quote of NORTHSTAR.md")
    if entry.get("evidence") not in EVIDENCE:
        problems.append(f"{cid}: 'evidence' must be one of {', '.join(EVIDENCE)}")
    if entry.get("evidence") == "e2e":
        if entry.get("artefact") not in ARTEFACTS:
            problems.append(f"{cid}: 'artefact' must be one of {', '.join(sorted(ARTEFACTS))}")
        if not _text(entry.get("negative")):
            problems.append(f"{cid}: an e2e contract needs its mandatory 'negative' case")
        limit = entry.get("threshold")
        if limit is not None and not (isinstance(limit, dict) and _text(limit.get("metric"))
                                      and isinstance(limit.get("min"), (int, float))
                                      and not isinstance(limit.get("min"), bool)):
            problems.append(f"{cid}: 'threshold' needs a 'metric' and a numeric 'min'")
    if entry.get("evidence") == "operator" and not _text(entry.get("operator")):
        problems.append(f"{cid}: an operator contract says in 'operator' what the operator does")
    return problems


def contract_violations(tree: str, stage: str, data: object) -> List[Finding]:
    """Return findings for a contract file that is malformed or does not quote NORTHSTAR.md."""
    rel = contract_path(stage)
    with open(os.path.join(tree, "NORTHSTAR.md"), encoding="utf-8") as handle:
        northstar = _flat(handle.read())
    if not isinstance(data, dict) or not isinstance(data.get("contracts"), list) or not data["contracts"]:
        return [Finding(rel, 1, RULE, "contract needs a non-empty 'contracts' list")]
    problems = [] if data.get("stage") == stage else [f"'stage' must be {stage!r}"]
    for key in ("outcome", "proof"):
        if not _text(data.get(key)) or _flat(data[key]) not in northstar:
            problems.append(f"'{key}' must be a verbatim quote of the NORTHSTAR.md stage row")
    seen = set()
    for entry in data["contracts"]:
        problems += _entry_problems(stage, entry, northstar)
        cid = entry.get("id") if isinstance(entry, dict) else None
        if cid in seen:
            problems.append(f"duplicate id {cid}")
        seen.add(cid)
    return [Finding(rel, 1, RULE, problem) for problem in problems]


def specs(report: dict) -> Iterator[Tuple[str, dict]]:
    # constraint: a root suite is the spec file; an id in the file name must not make every test in it carry the id
    """Yield every spec of a Playwright JSON report with its title joined to its describe titles (not the file name)."""
    stack = [(None, suite) for suite in report.get("suites", [])]
    while stack:
        path, suite = stack.pop()
        if not isinstance(suite, dict):
            continue
        here = [] if path is None else path + [str(suite.get("title", ""))]
        for spec in suite.get("specs", []):
            if isinstance(spec, dict):
                yield " ".join(here + [str(spec.get("title", ""))]), spec
        stack += [(here, child) for child in suite.get("suites", [])]


def passed(spec: dict) -> bool:
    """Return whether every run of every test of a spec passed as expected: not skipped, flaky or expected-to-fail."""
    tests = spec.get("tests")
    if spec.get("ok") is not True or not isinstance(tests, list) or not tests:
        return False
    for test in tests:
        results = test.get("results") if isinstance(test, dict) else None
        if not isinstance(results, list) or not results:
            return False
        if test.get("expectedStatus", "passed") != "passed":
            return False
        if any(not isinstance(r, dict) or r.get("status") != "passed" for r in results):
            return False
    return True


def report_violations(stage: str, contracts: List[dict], report: object) -> Dict[str, List[Finding]]:
    """Return findings per contract id: a passed spec and a passed negative spec are required, nothing else may fail."""
    rel = report_path(stage)
    if not isinstance(report, dict) or not isinstance(report.get("suites"), list):
        return {"": [Finding(rel, 1, RULE, "not a Playwright JSON report (no 'suites' list)")]}
    titled = list(specs(report))
    known = {c["id"] for c in contracts}
    out: Dict[str, List[Finding]] = {"": []}
    for title, _ in titled:
        for cid in TITLE_ID.findall(title):
            if cid.startswith(f"S{stage.upper()}-") and cid not in known:
                out[""].append(Finding(rel, 1, RULE, f"spec '{title}' names {cid}, which is not in {contract_path(stage)}"))
    for contract in contracts:
        if contract["evidence"] != "e2e":
            continue
        cid = contract["id"]
        mine = [(t, s) for t, s in titled if cid in TITLE_ID.findall(t)]
        found = [Finding(rel, 1, RULE, f"spec '{t}' did not pass (failed, skipped, flaky or expected to fail)")
                 for t, s in mine if not passed(s)]
        if not [t for t, _ in mine if not NEGATIVE.search(t)]:
            found.append(Finding(rel, 1, RULE, f"{cid}: no spec titled with the id; the scenario is missing"))
        if not [t for t, _ in mine if NEGATIVE.search(t)]:
            found.append(Finding(rel, 1, RULE, f"{cid}: no spec titled '{cid} negative ...'; the negative case is missing"))
        out[cid] = found
    return out


def _artefact_problem(tree: str, cid: str, rel: object) -> str:
    """Return why one listed artefact does not count, or an empty string."""
    if not isinstance(rel, str) or os.path.isabs(rel) or not rel.startswith(cid + "/") or ".." in rel.split("/"):
        return f"artefact {rel!r} must be a relative path below {OUT}/{cid}/"
    base = os.path.realpath(os.path.join(tree, OUT, cid))
    path = os.path.join(tree, OUT, rel)
    if os.path.islink(path) or not os.path.isfile(path) or not os.path.realpath(path).startswith(base + os.sep):
        return f"artefact {OUT}/{rel} is missing or not a regular file inside {OUT}/{cid}/"
    if os.path.getsize(path) == 0:
        return f"artefact {OUT}/{rel} is empty"
    return ""


def _is_kind(path: str, kind: str) -> bool:
    """Return whether a file has the suffix and the content signature of an artefact kind."""
    suffixes, magic = ARTEFACTS[kind]
    if not path.endswith(suffixes):
        return False
    with open(path, "rb") as handle:
        data = handle.read()
    if not data.startswith(magic):
        return False
    if kind in ("json", "tex", "text"):
        text = data.decode("utf-8", errors="replace")
        if "�" in text or not text.strip():
            return False
        if kind == "json":
            _, err = _parse(text)
            return not err
    return True


def _parse(text: str) -> Tuple[Optional[object], str]:
    """Parse JSON text and return the value and an empty string, or None and the error."""
    try:
        return json.loads(text), ""
    except ValueError as err:
        return None, str(err)


def _negative_problems(contract: dict, negative: object) -> List[str]:
    """Return what is missing from the documented rejection of the contract's negative case."""
    if not isinstance(negative, dict):
        return ["'negative' must document the rejected case with 'case', 'input' and 'reason'"]
    problems = []
    if negative.get("case") != contract["negative"]:
        problems.append("'negative.case' must repeat the contract's negative case verbatim")
    for key in ("input", "reason"):
        if not _text(negative.get(key)):
            problems.append(f"'negative.{key}' must say which wrong input was given and how it was rejected")
    return problems


def _measurement_problem(contract: dict, measured: object) -> str:
    """Return why a measurement misses the contract's threshold, or an empty string."""
    limit = contract["threshold"]
    if not isinstance(measured, dict) or measured.get("metric") != limit["metric"]:
        return f"'measurement' must report metric {limit['metric']!r}"
    value = measured.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "'measurement.value' must be a number"
    if value < limit["min"]:
        return f"{limit['metric']} = {value} is below the contract's minimum {limit['min']}"
    return ""


def record_violations(tree: str, contract: dict) -> List[Finding]:
    """Return findings for the evidence record of one e2e contract id and the artefacts it lists."""
    cid = contract["id"]
    rel = record_path(cid)
    data, err = load_json(tree, rel)
    if not isinstance(data, dict):
        return [Finding(rel, 1, RULE, f"{cid}: evidence record missing or unreadable ({err or 'not an object'})")]
    problems = [] if data.get("id") == cid else [f"'id' must be {cid}"]
    listed = data.get("artefacts")
    if not isinstance(listed, list) or not listed:
        listed = []
        problems.append("'artefacts' must list at least one file")
    kind = contract["artefact"]
    has_kind = False
    for item in listed:
        problem = _artefact_problem(tree, cid, item)
        if problem:
            problems.append(problem)
        elif _is_kind(os.path.join(tree, OUT, item), kind):
            has_kind = True
    if not has_kind:
        problems.append(f"no valid {kind} artefact among {OUT}/{cid}/")
    problems += _negative_problems(contract, data.get("negative"))
    if contract.get("threshold") is not None:
        problems.append(_measurement_problem(contract, data.get("measurement")))
    return [Finding(rel, 1, RULE, f"{cid}: {p}") for p in problems if p]


def verify(tree: str, stage: str) -> Tuple[List[Finding], List[str]]:
    """Check a stage's contract against the runner report and the evidence; return findings and the per-id lines."""
    data, err = load_json(tree, contract_path(stage))
    if data is None:
        return [Finding(contract_path(stage), 1, RULE, f"contract missing or unreadable: {err}")], []
    found = contract_violations(tree, stage, data)
    if found:
        return found, []
    contracts = data["contracts"]
    report, err = load_json(tree, report_path(stage))
    if report is None:
        per_id = {"": [Finding(report_path(stage), 1, RULE,
                               f"runner report missing ({err}); run `make proof STAGE={stage}` first")]}
    else:
        per_id = report_violations(stage, contracts, report)
    found = list(per_id.get("", []))
    lines = []
    for contract in contracts:
        cid = contract["id"]
        if contract["evidence"] == "operator":
            lines.append(f"OPEN (operator) {cid}: {contract['operator']}")
            continue
        mine = per_id.get(cid, []) + record_violations(tree, contract)
        found += mine
        lines.append(f"{'FAIL' if mine or report is None else 'PASS'} {cid}")
    if any(line.startswith("OPEN") for line in lines):
        lines.append(f"Stage {stage} counts as done only when the operator closes the OPEN items; they never pass here.")
    return found, lines
