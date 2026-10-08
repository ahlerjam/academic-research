"""make gates-selftest: every gate must turn red on its fixture and stay green on the good twin."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from typing import List, NamedTuple, Optional

from . import catalog, drift, gitx, manifest, roles, tools

ID_IN_OUTPUT = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")
TOOL_DIRS = (".venv", "node_modules", ".gradle", "build")


class Result(NamedTuple):
    """Outcome of one probe: name, status (pass, fail, not-exercised) and detail."""

    name: str
    status: str
    detail: str


def sandbox(tree: str) -> str:
    """Copy the control files, gates and docs into a fresh git tree; symlink tool directories."""
    root = tempfile.mkdtemp(prefix="gates-selftest-")
    files = set(manifest.control_files(tree)) | set(gitx.ls(tree, ["gates/**", ".gitignore", "decisions/**",
                                                                    "*/package.json", "*/pyproject.toml",
                                                                    "*/.python-version", "*/.node-version"]))
    files = {f for f in files if not f.startswith("gates/fixtures/")}
    for rel in sorted(files):
        dest = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(tree, rel), dest)
    cfg = roles.load(tree)
    for comp in cfg["components"]:
        base = roles.component_dir(cfg, comp)
        for name in TOOL_DIRS:
            src = os.path.join(tree, base, name)
            dest = os.path.join(root, base, name)
            if os.path.isdir(src) and not os.path.exists(dest):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.symlink(src, dest)
    gitx.run(["git", "init", "-q"], cwd=root)
    return root


def synth_path(cfg: dict, entry: dict, ext: str) -> Optional[str]:
    """Derive a path that the entry's first role claims, e.g. backend/app/selftest/core.py."""
    component = entry.get("component", "*")
    comps = [component] if component != "*" else sorted(cfg["components"])
    for comp in comps:
        for role in catalog.roles_of(entry):
            role = role if role != "*" else next(iter(cfg["components"][comp]["roles"]))
            for glob in roles.patterns(cfg, comp, role):
                parts = [p.replace("*", "selftest") for p in glob.split("/") if p != "**"]
                last = parts[-1]
                if "." not in last:
                    parts[-1] = f"{last}.{ext}"
                elif not last.endswith("." + ext):
                    continue
                return "/".join(parts)
    return None


def _gate(root: str, args: List[str], payload: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run the sandbox's gate.py."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, GATES_NESTED="1")
    return subprocess.run([sys.executable, "-I", os.path.join(root, "gates", "gate.py")] + args, cwd=root,
                          input=json.dumps(payload) if payload is not None else None, capture_output=True,
                          text=True, env=env, timeout=300)


def _ids(text: str) -> set:
    """Return every [RULE-ID] in output."""
    return set(ID_IN_OUTPUT.findall(text))


def _overlay(fixture: str, side: str, root: str) -> None:
    """Copy fixture/<side>/ into the sandbox."""
    src = os.path.join(fixture, side)
    for base, _, names in os.walk(src):
        for name in names:
            rel = os.path.relpath(os.path.join(base, name), src)
            dest = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(base, name), dest)


def _offline_skip(out: str) -> bool:
    """Return whether output says a carrier was not exercised offline."""
    return tools.offline() and "Not exercised (offline)" in out


def _infra_line(out: str) -> str:
    """Return the first infrastructure message of a probe, so a missing tool is not read as a template defect."""
    line = next((ln for ln in out.splitlines() if "GATES-INFRA" in ln or "infrastructure:" in ln), "")
    return f" (infrastructure, not a template defect: {line.strip()[:160]})" if line else ""


def probe_file(tree: str, entry: dict) -> Result:
    """File fixture: bad must report exactly this id through hook post-edit, good must pass."""
    fixture = os.path.join(tree, entry["fixture"])
    bad = next((f for f in sorted(os.listdir(fixture)) if f.startswith("bad.")), None)
    good = next((f for f in sorted(os.listdir(fixture)) if f.startswith("good.")), None)
    if not bad or not good:
        return Result(entry["id"], "fail", "fixture needs bad.<ext> and good.<ext>")
    meta = os.path.join(fixture, "fixture.json")
    cfg = roles.load(tree)
    rel = json.load(open(meta, encoding="utf-8"))["path"] if os.path.isfile(meta) else synth_path(cfg, entry, bad.split(".", 1)[1])
    if rel is None:
        return Result(entry["id"], "fail", "no role path for the fixture")
    known = set(catalog.by_id(catalog.load(tree)))
    for side, name in (("bad", bad), ("good", good)):
        root = sandbox(tree)
        try:
            dest = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(fixture, name), dest)
            payload = {"tool_name": "Write", "tool_input": {"file_path": dest}, "cwd": root}
            proc = _gate(root, ["hook", "post-edit"], payload)
            out = proc.stdout + proc.stderr
            if entry["id"] not in _ids(out):
                extra = _gate(root, ["check-file", "--tier", "s1", rel])
                out += extra.stdout + extra.stderr
            ids = _ids(out)
            if side == "bad":
                if entry["id"] not in ids:
                    if _offline_skip(out):
                        return Result(entry["id"], "not-exercised", out.strip().splitlines()[-1])
                    return Result(entry["id"], "fail", f"bad fixture not reported as {entry['id']}: {out.strip()[:300]}")
                others = sorted((ids & known) - {entry["id"]})
                if others or "GATES-INFRA" in ids:
                    return Result(entry["id"], "fail", f"bad fixture also reports {others or ['GATES-INFRA']}"
                                                       + _infra_line(out))
            elif ids & (known | {"GATES-INFRA"}) or proc.returncode not in (0,):
                if _offline_skip(out) and not ids:
                    continue
                return Result(entry["id"], "fail", f"good fixture not green{_infra_line(out)}: {out.strip()[:300]}")
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return Result(entry["id"], "pass", rel)


def probe_repo(tree: str, entry: dict) -> Result:
    """Repo fixture: overlay bad/ must report the id through check-repo, good/ must not."""
    fixture = os.path.join(tree, entry["fixture"])
    for side in ("bad", "good"):
        root = sandbox(tree)
        try:
            _overlay(fixture, side, root)
            proc = _gate(root, ["check-repo", "--only", entry["id"]])
            ids = _ids(proc.stdout + proc.stderr)
            if side == "bad" and entry["id"] not in ids:
                return Result(entry["id"], "fail", f"bad overlay not reported: {(proc.stdout + proc.stderr)[:300]}")
            if side == "good" and (entry["id"] in ids or "GATES-INFRA" in ids):
                return Result(entry["id"], "fail", f"good overlay reported: {(proc.stdout + proc.stderr)[:300]}")
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return Result(entry["id"], "pass", "repo overlay")


def probe_command(tree: str, entry: dict) -> Result:
    """External carrier: overlay bad/ makes the carrier command fail with the expected text, good/ passes."""
    fixture = os.path.join(tree, entry["fixture"])
    spec = entry["selftest"]
    cfg = roles.load(tree)
    comp_dir = roles.component_dir(cfg, entry["component"]) if entry.get("component", "*") != "*" else "."
    for side in ("bad", "good"):
        root = sandbox(tree)
        try:
            for rel in gitx.ls(tree, spec.get("copy", [])):
                dest = os.path.join(root, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(os.path.join(tree, rel), dest)
            _overlay(fixture, side, root)
            absent = [r for r in spec.get("requires", []) if not os.path.exists(os.path.join(root, r))]
            if absent:
                if tools.offline():
                    return Result(entry["id"], "not-exercised", f"{absent[0]} missing (offline)")
                return Result(entry["id"], "fail", f"infrastructure: {absent[0]} missing; run make setup")
            exe = tools.resolve(root, comp_dir, spec["cmd"][0])
            if exe is None:
                if tools.offline():
                    return Result(entry["id"], "not-exercised", f"tool {spec['cmd'][0]} missing (offline)")
                return Result(entry["id"], "fail", f"infrastructure: tool {spec['cmd'][0]} missing; run make setup")
            cwd = os.path.join(root, comp_dir) if spec.get("cwd") == "component" else root
            proc = subprocess.run([exe] + spec["cmd"][1:], cwd=cwd, capture_output=True, text=True, timeout=600)
            out = proc.stdout + proc.stderr
            if side == "bad" and (proc.returncode == 0 or not re.search(spec.get("expect", "."), out)):
                return Result(entry["id"], "fail", f"bad overlay passed {spec['cmd'][0]}: {out[:300]}")
            if side == "good" and proc.returncode != 0:
                return Result(entry["id"], "fail", f"good overlay failed {spec['cmd'][0]}: {out[:300]}")
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return Result(entry["id"], "pass", " ".join(spec["cmd"]))


def probe_bash_corpus(tree: str) -> List[Result]:
    """Run gates/tests/guard-bash.cases.tsv through hook pre-bash."""
    path = os.path.join(tree, "gates", "tests", "guard-bash.cases.tsv")
    out = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip() or line.startswith("command\t"):
                continue
            command, expected = line.rstrip("\n").rsplit("\t", 1)
            proc = _gate(tree, ["hook", "pre-bash"], {"tool_input": {"command": command}, "cwd": tree})
            got = "block" if proc.returncode == 2 else "allow"
            out.append(Result(f"bash:{number}", "pass" if got == expected else "fail", f"{command!r} -> {got}"))
    return out


def unit_tests(tree: str) -> Result:
    """Run gates/tests with unittest in-process."""
    suite = unittest.defaultTestLoader.discover(os.path.join(tree, "gates", "tests"), top_level_dir=os.path.join(tree, "gates"))
    result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    ok = result.wasSuccessful()
    detail = f"{result.testsRun} tests" + ("" if ok else f", {len(result.failures)} failures, {len(result.errors)} errors: "
                                           + "; ".join(str(t[0]) for t in (result.failures + result.errors)[:5]))
    return Result("unit-tests", "pass" if ok else "fail", detail)


def run(tree: str) -> int:
    """Run every probe, print a table and the carriers that were not exercised."""
    started = time.time()
    results: List[Result] = []
    rule_tests = drift.d5(tree)
    results.append(Result("ast-grep-test", "fail" if rule_tests else "pass", "; ".join(f.what for f in rule_tests)))
    for entry in catalog.load(tree):
        mode = entry.get("fixture_mode", "file")
        if mode == "test":
            continue
        probe = {"file": probe_file, "repo": probe_repo, "command": probe_command}.get(mode)
        results.append(probe(tree, entry) if probe else Result(entry["id"], "fail", f"unknown fixture_mode {mode}"))
    results += probe_bash_corpus(tree)
    results.append(unit_tests(tree))
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{r.name.ljust(width)}  {r.status.upper():<13} {r.detail[:160]}")
    failed = [r for r in results if r.status == "fail"]
    skipped = [r.name for r in results if r.status == "not-exercised"]
    if skipped:
        print(f"NOT EXERCISED (offline, not proven here): {', '.join(skipped)}")
    verdict = "FAIL" if failed else "PASS"
    print(f"RESULT: {verdict} gates-selftest {int(time.time() - started)}s "
          f"({len(results) - len(failed) - len(skipped)} pass, {len(failed)} fail, {len(skipped)} not exercised)")
    return 1 if failed else 0
