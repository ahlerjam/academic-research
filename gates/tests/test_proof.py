"""Proof contract: the stage files quote NORTHSTAR, proof-verify needs a passed spec, an artefact and a rejected negative case."""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import shutil
import unittest
from typing import Dict, List, Optional
from unittest import mock

import gate
from lib import migrations, proofs
from tests import support

ARTEFACT_BYTES = {
    "pdf": b"%PDF-1.7\n1 0 obj\n",
    "zip": b"PK\x03\x04proof",
    "docx": b"PK\x03\x04proof",
    "png": b"\x89PNG\r\n\x1a\nproof",
    "json": b'{"ok": true}\n',
    "tex": b"\\section{Proof}\n",
    "text": b"proof\n",
}
SUFFIX = {"pdf": "pdf", "zip": "zip", "docx": "docx", "png": "png", "json": "json", "tex": "tex", "text": "html"}


def contract(stage: str) -> dict:
    """Return the stage contract of the source tree."""
    with open(os.path.join(support.SOURCE, proofs.contract_path(stage)), encoding="utf-8") as handle:
        return json.load(handle)


def spec(title: str, statuses: Optional[List[str]] = None, ok: bool = True, expected: str = "passed") -> dict:
    """Return one Playwright JSON report spec with one test and the given result statuses."""
    results = [{"status": s} for s in (statuses or ["passed"])]
    return {"title": title, "ok": ok, "tests": [{"expectedStatus": expected, "results": results}]}


def write_bytes(root: str, rel: str, data: bytes) -> None:
    """Write bytes below root."""
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def evidence(root: str, stage: str, specs: Optional[List[dict]] = None, value: float = 0.9) -> Dict[str, dict]:
    """Write a complete runner report and an evidence record with one artefact per e2e id; return the records."""
    shutil.rmtree(os.path.join(root, proofs.OUT), ignore_errors=True)
    records = {}
    titles = []
    for entry in contract(stage)["contracts"]:
        if entry["evidence"] != "e2e":
            continue
        cid, kind = entry["id"], entry["artefact"]
        titles += [spec(f"{cid} exercises the stage sentence"), spec(f"{cid} negative: wrong input is rejected")]
        artefact = f"{cid}/artefact.{SUFFIX[kind]}"
        write_bytes(root, f"{proofs.OUT}/{artefact}", ARTEFACT_BYTES[kind])
        record = {"id": cid, "artefacts": [artefact],
                  "negative": {"case": entry["negative"], "input": "a deliberately wrong input",
                               "reason": "rejected with code proof-negative"}}
        if entry.get("threshold"):
            record["measurement"] = {"metric": entry["threshold"]["metric"], "value": value}
        records[cid] = record
        write_record(root, cid, record)
    report = {"suites": [{"title": f"stage-{stage}.spec.ts", "specs": titles if specs is None else specs, "suites": []}]}
    support.write(root, proofs.report_path(stage), json.dumps(report))
    return records


def write_record(root: str, cid: str, record: dict) -> None:
    """Write the evidence record of one contract id."""
    support.write(root, proofs.record_path(cid), json.dumps(record))


class ContractFiles(unittest.TestCase):
    """The six stage files are well formed, quote NORTHSTAR verbatim and keep their ids unique."""

    def test_every_stage_contract_is_valid(self) -> None:
        for stage in proofs.STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(proofs.contract_violations(support.SOURCE, stage, contract(stage)), [])

    def test_ids_are_unique_across_stages_and_every_stage_has_an_e2e_id(self) -> None:
        ids: List[str] = []
        for stage in proofs.STAGES:
            entries = contract(stage)["contracts"]
            ids += [e["id"] for e in entries]
            self.assertTrue([e for e in entries if e["evidence"] == "e2e"], stage)
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_quote_not_in_northstar_and_a_missing_negative_are_red(self) -> None:
        data = contract("1")
        data["contracts"][0] = dict(data["contracts"][0], northstar="a sentence the north star never says")
        data["contracts"][1] = {k: v for k, v in data["contracts"][1].items() if k != "negative"}
        data["contracts"].append(dict(data["contracts"][2]))
        what = " ".join(f.what for f in proofs.contract_violations(support.SOURCE, "1", data))
        self.assertIn("verbatim quote of NORTHSTAR.md", what)
        self.assertIn("mandatory 'negative'", what)
        self.assertIn("duplicate id", what)

    def test_a_wrong_prefix_and_an_unknown_evidence_kind_are_red(self) -> None:
        data = contract("2a")
        data["contracts"][0] = dict(data["contracts"][0], id="S1-WRONG-STAGE", evidence="self-report")
        what = " ".join(f.what for f in proofs.contract_violations(support.SOURCE, "2a", data))
        self.assertIn("must match S2A-", what)
        self.assertIn("'evidence' must be one of", what)


class ProofVerify(unittest.TestCase):
    """proof-verify turns red for every missing piece of evidence and green only on the complete set."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(os.path.join(support.SOURCE, "NORTHSTAR.md"), encoding="utf-8") as handle:
            cls.root = support.make_tree({"NORTHSTAR.md": handle.read()}, baseline=False)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def verify(self, stage: str = "1") -> tuple:
        result = support.gate(self.root, ["proof-verify", "--stage", stage])
        return result.returncode, result.stdout + result.stderr

    def test_complete_evidence_passes_and_lists_operator_items_as_open(self) -> None:
        evidence(self.root, "1")
        code, out = self.verify()
        self.assertEqual(code, 0, out)
        self.assertIn("PASS S1-QUOTE-EXACT", out)
        self.assertIn("OPEN (operator) S1-T23-REVIEW", out)
        self.assertIn("RESULT: PASS proof-verify-1", out)

    def test_missing_runner_report_is_red(self) -> None:
        evidence(self.root, "1")
        os.remove(os.path.join(self.root, proofs.report_path("1")))
        code, out = self.verify()
        self.assertEqual(code, 1, out)
        self.assertIn("runner report missing", out)
        self.assertNotIn("PASS S1-", out)

    def test_missing_scenario_and_missing_negative_spec_are_red(self) -> None:
        records = evidence(self.root, "1")
        specs = []
        for cid in records:
            if cid != "S1-QUOTE-EXACT":
                specs += [spec(f"{cid} works"), spec(f"{cid} negative case")]
        specs.append(spec("S1-QUOTE-EXACT works"))
        specs.append(spec("S1-HOVER-PAGE negative again"))
        evidence(self.root, "1", specs=[s for s in specs if s["title"] != "S1-TRACE-BLOCKS works"])
        code, out = self.verify()
        self.assertEqual(code, 1, out)
        self.assertIn("S1-QUOTE-EXACT: no spec titled 'S1-QUOTE-EXACT negative", out)
        self.assertIn("S1-TRACE-BLOCKS: no spec titled with the id", out)
        self.assertIn("FAIL S1-QUOTE-EXACT", out)

    def test_skipped_flaky_expected_to_fail_and_failed_specs_are_red(self) -> None:
        cases = {"skipped": spec("S1-IMPORT negative x", ["skipped"]),
                 "flaky": spec("S1-IMPORT negative x", ["failed", "passed"]),
                 "test.fail": spec("S1-IMPORT negative x", ["passed"], expected="failed"),
                 "failed": spec("S1-IMPORT negative x", ["failed"], ok=False)}
        for name, bad in cases.items():
            with self.subTest(case=name):
                records = evidence(self.root, "1")
                specs = [s for cid in records for s in (spec(f"{cid} ok"), spec(f"{cid} negative ok"))
                         if s["title"] != "S1-IMPORT negative ok"]
                evidence(self.root, "1", specs=specs + [bad])
                code, out = self.verify()
                self.assertEqual(code, 1, out)
                self.assertIn("did not pass", out)

    def test_a_spec_naming_an_id_outside_the_contract_is_red(self) -> None:
        records = evidence(self.root, "1")
        specs = [s for cid in records for s in (spec(f"{cid} ok"), spec(f"{cid} negative ok"))]
        evidence(self.root, "1", specs=specs + [spec("S1-QUOTE-EXCAT typo ok")])
        code, out = self.verify()
        self.assertEqual(code, 1, out)
        self.assertIn("names S1-QUOTE-EXCAT, which is not in", out)

    def test_an_id_only_in_the_file_name_does_not_count_but_one_in_a_describe_title_does(self) -> None:
        records = evidence(self.root, "1")
        others = [s for cid in records if cid != "S1-PRINTONLY" for s in (spec(f"{cid} ok"), spec(f"{cid} negative ok"))]
        nested = {"title": "S1-PRINTONLY", "specs": [spec("passes after a logged confirmation"),
                                                     spec("negative: no confirmation blocks")], "suites": []}
        for child, expected in (({"title": "describe", "specs": [spec("ok"), spec("negative ok")], "suites": []}, 1),
                                (nested, 0)):
            report = {"suites": [{"title": "stage-1-S1-PRINTONLY.spec.ts", "specs": others, "suites": [child]}]}
            support.write(self.root, proofs.report_path("1"), json.dumps(report))
            code, out = self.verify()
            self.assertEqual(code, expected, out)

    def test_missing_record_is_red(self) -> None:
        evidence(self.root, "1")
        os.remove(os.path.join(self.root, proofs.record_path("S1-PRINTONLY")))
        code, out = self.verify()
        self.assertEqual(code, 1, out)
        self.assertIn("S1-PRINTONLY: evidence record missing", out)

    def test_missing_empty_fake_and_escaping_artefacts_are_red(self) -> None:
        cases = {"missing": None, "empty": b"", "fake pdf": b"just text"}
        for name, data in cases.items():
            with self.subTest(case=name):
                evidence(self.root, "1")
                path = os.path.join(self.root, proofs.OUT, "S1-NO-AI-MARKER", "artefact.pdf")
                os.remove(path)
                if data is not None:
                    write_bytes(self.root, os.path.relpath(path, self.root), data)
                code, out = self.verify()
                self.assertEqual(code, 1, out)
                self.assertIn("S1-NO-AI-MARKER", out)
        records = evidence(self.root, "1")
        write_bytes(self.root, "elsewhere.pdf", ARTEFACT_BYTES["pdf"])
        write_record(self.root, "S1-NO-AI-MARKER", dict(records["S1-NO-AI-MARKER"], artefacts=["S1-NO-AI-MARKER/../../elsewhere.pdf"]))
        code, out = self.verify()
        self.assertEqual(code, 1, out)
        self.assertIn("must be a relative path below", out)

    def test_a_symlinked_artefact_is_red(self) -> None:
        evidence(self.root, "1")
        write_bytes(self.root, "outside.pdf", ARTEFACT_BYTES["pdf"])
        path = os.path.join(self.root, proofs.OUT, "S1-NO-AI-MARKER", "artefact.pdf")
        os.remove(path)
        os.symlink(os.path.join(self.root, "outside.pdf"), path)
        code, out = self.verify()
        self.assertEqual(code, 1, out)
        self.assertIn("not a regular file", out)

    def test_an_undocumented_or_paraphrased_negative_case_is_red(self) -> None:
        records = evidence(self.root, "1")
        rec = records["S1-TRACE-BLOCKS"]
        write_record(self.root, "S1-TRACE-BLOCKS", dict(rec, negative=dict(rec["negative"], case="something milder")))
        write_record(self.root, "S1-HOVER-PAGE", {k: v for k, v in records["S1-HOVER-PAGE"].items() if k != "negative"})
        write_record(self.root, "S1-IMPORT", dict(records["S1-IMPORT"], negative=dict(records["S1-IMPORT"]["negative"], reason=" ")))
        code, out = self.verify()
        self.assertEqual(code, 1, out)
        self.assertIn("S1-TRACE-BLOCKS: 'negative.case' must repeat", out)
        self.assertIn("S1-HOVER-PAGE: 'negative' must document", out)
        self.assertIn("S1-IMPORT: 'negative.reason'", out)

    def test_measurement_below_the_contract_threshold_is_red(self) -> None:
        evidence(self.root, "2b", value=0.85)
        code, out = self.verify("2b")
        self.assertEqual(code, 0, out)
        evidence(self.root, "2b", value=0.79)
        code, out = self.verify("2b")
        self.assertEqual(code, 1, out)
        self.assertIn("recall@10 = 0.79 is below the contract's minimum 0.8", out)

    def test_a_broken_contract_in_the_tree_is_red(self) -> None:
        evidence(self.root, "3")
        rel = proofs.contract_path("3")
        with open(os.path.join(self.root, rel), encoding="utf-8") as handle:
            original = handle.read()
        try:
            data = json.loads(original)
            data["contracts"][0]["northstar"] = "not a north star sentence"
            support.write(self.root, rel, json.dumps(data))
            code, out = self.verify("3")
            self.assertEqual(code, 1, out)
            self.assertIn("verbatim quote of NORTHSTAR.md", out)
        finally:
            support.write(self.root, rel, original)

    def test_unknown_stage_is_refused(self) -> None:
        code, out = self.verify("9")
        self.assertEqual(code, 2, out)


class MigrationNew(unittest.TestCase):
    """gate.py migration new hands the name to migrations.new and prints the path it returns."""

    def run_gate(self, argv: List[str]) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(gate, "_tree", return_value="/tree"), \
                mock.patch.object(migrations, "new", create=True, return_value="packages/server/migrations/0003_sources.sql") as new, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate.main(argv)
        return code, out.getvalue(), err.getvalue(), new

    def test_name_is_passed_and_the_path_printed(self) -> None:
        code, out, _, new = self.run_gate(["migration", "new", "--name", "sources"])
        self.assertEqual(code, 0)
        new.assert_called_once_with("/tree", "sources")
        self.assertEqual(out.strip(), "packages/server/migrations/0003_sources.sql")

    def test_missing_name_is_refused_without_creating_anything(self) -> None:
        code, _, err, new = self.run_gate(["migration", "new"])
        self.assertEqual(code, 2)
        self.assertIn("NAME", err)
        new.assert_not_called()

    def test_migrations_module_offers_new_with_tree_and_name(self) -> None:
        self.assertTrue(callable(getattr(migrations, "new", None)), "gates/lib/migrations.py lacks new(tree, name)")
        self.assertEqual(len(inspect.signature(migrations.new).parameters), 2)


if __name__ == "__main__":
    unittest.main()
