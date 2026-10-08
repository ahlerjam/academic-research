#!/usr/bin/env python3
"""Single entry point of the gates: hook, check, lint, drift, sync, baseline, anchor, selftest, bench, doctor, adr."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import adr, catalog, doctor, drift, engine, findings, gitx, guard, hooks, manifest  # noqa: E402
from lib import repo, roles, selftest, suppress, sync  # noqa: E402


def _tree() -> str:
    """Return the work tree of the current directory."""
    top = gitx.toplevel(os.getcwd())
    if top is None:
        sys.stderr.write("gates: not inside a git work tree\n")
        sys.exit(2)
    return top


def _finish(tree: str, stage: str, found: list, started: float) -> int:
    """Print findings by the message contract or one PASS line."""
    if found:
        log = findings.write_log(gitx.state_dir(tree), stage, found)
        print(findings.render(found, catalog.by_id(catalog.load(tree)), os.path.relpath(log, tree)))
        print(f"RESULT: FAIL {stage} {int(time.time() - started)}s")
        return 1
    print(f"RESULT: PASS {stage} {int(time.time() - started)}s")
    return 0


def main(argv: list) -> int:
    """Parse the command line and run one command."""
    parser = argparse.ArgumentParser(prog="gate.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook").add_argument("event")
    check_file = sub.add_parser("check-file")
    check_file.add_argument("--tier", default="s0")
    check_file.add_argument("files", nargs="+")
    sub.add_parser("lint").add_argument("--component")
    sub.add_parser("check-repo").add_argument("--only")
    sub.add_parser("drift")
    sync_p = sub.add_parser("sync")
    sync_p.add_argument("--check", action="store_true")
    sync_p.add_argument("--no-settings", action="store_true")
    sync_p.add_argument("--settings-to", help="write the rendered settings.json to this path instead")
    sub.add_parser("baseline")
    sub.add_parser("anchor")
    sup_p = sub.add_parser("suppress-baseline")
    sup_p.add_argument("--reason", required=True)
    sub.add_parser("manifest-check")
    sub.add_parser("guard")
    sub.add_parser("selftest")
    sub.add_parser("bench")
    sub.add_parser("doctor")
    sub.add_parser("mark-setup")
    sub.add_parser("touched")
    adr_p = sub.add_parser("adr")
    adr_p.add_argument("action", choices=["index", "find", "new", "check"])
    adr_p.add_argument("--tag", default="")
    adr_p.add_argument("--query", default="")
    adr_p.add_argument("--title", default="")
    args = parser.parse_args(argv)
    if args.cmd == "hook":
        return hooks.main(args.event)
    tree = _tree()
    started = time.time()
    if args.cmd == "check-file":
        cfg, entries = roles.load(tree), catalog.load(tree)
        found, skipped = [], []
        for rel in args.files:
            outcome = engine.run_tier(tree, rel, args.tier, cfg, entries, do_format=False)
            found += outcome.findings
            skipped += outcome.skipped
        if skipped:
            print(f"Not exercised (offline): {', '.join(sorted(set(skipped)))}")
        return _finish(tree, f"check-file-{args.tier}", found, started)
    if args.cmd == "lint":
        return _finish(tree, f"lint-{args.component or 'all'}", engine.lint(tree, args.component), started)
    if args.cmd == "check-repo":
        return _finish(tree, "check-repo", repo.rules(tree, args.only), started)
    if args.cmd == "drift":
        return _finish(tree, "drift", drift.violations(tree) + sync.check(tree), started)
    if args.cmd == "sync":
        if args.check:
            return _finish(tree, "sync-check", sync.check(tree), started)
        for rel in sync.write(tree, "no-settings" if args.no_settings or args.settings_to else None):
            print(f"sync: wrote {rel}")
        if args.settings_to:
            with open(args.settings_to, "w", encoding="utf-8") as handle:
                handle.write(sync.settings(tree))
        return 0
    if args.cmd == "baseline":
        with open(os.path.join(tree, manifest.MANIFEST), "w", encoding="utf-8") as handle:
            handle.write(manifest.render(tree))
        print(f"wrote {manifest.MANIFEST}; commit it, then `make controls-anchor` without a remote")
        return 0
    if args.cmd == "anchor":
        ref, text = "HEAD", gitx.show(tree, "HEAD", manifest.MANIFEST)
        if text is None or text != manifest.render(tree):
            sys.stderr.write("gates: HEAD does not hold the current manifest; run `make controls-baseline` and commit\n")
            return 2
        gitx.run(["git", "update-ref", gitx.ANCHOR, ref], cwd=tree)
        print(f"{gitx.ANCHOR} -> {gitx.head(tree)}")
        return 0
    if args.cmd == "suppress-baseline":
        if not args.reason.strip():
            sys.stderr.write("gates: suppress-baseline needs REASON=<issue or ADR>\n")
            return 2
        data = dict(suppress.count(tree), reason=args.reason.strip())
        with open(os.path.join(tree, suppress.BASELINE), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
            handle.write("\n")
        print(f"wrote {suppress.BASELINE}; commit it with the reason, then `make controls-baseline`")
        return 0
    if args.cmd == "manifest-check":
        return _finish(tree, "manifest", manifest.violations(tree), started)
    if args.cmd == "guard":
        return _finish(tree, "guard", guard.violations(tree), started)
    if args.cmd == "selftest":
        return selftest.run(tree)
    if args.cmd == "bench":
        return doctor.bench(tree)
    if args.cmd == "doctor":
        return doctor.doctor(tree)
    if args.cmd == "touched":
        from lib import stopgate
        print(" ".join(sorted(stopgate.components_for(tree, gitx.changed_since_base(tree, deleted=True)))))
        return 0
    if args.cmd == "mark-setup":
        with open(os.path.join(gitx.state_dir(tree), "setup.json"), "w", encoding="utf-8") as handle:
            json.dump({"at": time.time()}, handle)
        return 0
    if args.cmd == "adr":
        lang = (adr.project(tree) or {}).get("doc_lang", "en")
        if args.action == "index":
            with open(os.path.join(tree, "decisions", "index.md"), "w", encoding="utf-8") as handle:
                handle.write(adr.index_text(tree))
            return 0
        if args.action == "find":
            print("\n".join(adr.find(tree, args.tag, args.query)) or "no matching ADR")
            return 0
        if args.action == "new":
            if not args.title:
                sys.stderr.write("adr new needs TITLE\n")
                return 2
            print(adr.new(tree, args.title, lang))
            return 0
        rid = next((e["id"] for e in catalog.load(tree) if e.get("carrier_ref") == "adr"), "ADR-FORMAT")
        return _finish(tree, "adr", adr.violations(tree, rid), started)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
