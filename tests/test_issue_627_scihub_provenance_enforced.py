"""Regressionstest fuer Issue #627: Sci-Hub-Provenance an der Schreibstelle durchsetzen.

Bisher trug ausschliesslich der Prompt in agents/scihub-fetcher.md die
Verantwortung, `provenance="scihub"` zu setzen -- ein Prompt ist keine
Durchsetzung. Dieser Test belegt, dass `VaultDB.add_paper()` selbst erzwingt:
liegt neben einem uebergebenen `pdf_path` der Sidecar-Marker
`<pdf_path>.provenance-scihub`, wird `provenance` unabhaengig vom
uebergebenen Wert (auch _UNSET oder ein abweichender String) auf "scihub"
gesetzt.
"""

import json
import os
import tempfile

from academic_vault.db import SCIHUB_PROVENANCE_SIDECAR_SUFFIX, VaultDB


class TestScihubProvenanceEnforced:
    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.db = VaultDB(self.db_path)
        self.db.init_schema()

        self.pdf_dir = tempfile.mkdtemp()
        self.pdf_path = os.path.join(self.pdf_dir, "paper.pdf")
        with open(self.pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 fake content")

    def teardown_method(self):
        os.unlink(self.db_path)

    def _write_sidecar(self):
        with open(self.pdf_path + SCIHUB_PROVENANCE_SIDECAR_SUFFIX, "w", encoding="utf-8") as f:
            f.write("scihub")

    def test_sidecar_marker_forces_provenance_without_explicit_param(self):
        """Sidecar vorhanden, provenance nicht uebergeben -> DB traegt trotzdem 'scihub'."""
        self._write_sidecar()
        self.db.add_paper(
            paper_id="scihub-enforced-1",
            csl_json=json.dumps({"type": "article-journal", "title": "T"}),
            pdf_path=self.pdf_path,
        )
        paper = self.db.get_paper("scihub-enforced-1")
        assert paper is not None
        assert paper["provenance"] == "scihub"

    def test_sidecar_marker_overrides_explicit_conflicting_value(self):
        """Sidecar vorhanden, provenance explizit auf abweichenden Wert gesetzt ->
        wird dennoch auf 'scihub' korrigiert (beweist: faellt nicht unbemerkt durch)."""
        self._write_sidecar()
        self.db.add_paper(
            paper_id="scihub-enforced-2",
            csl_json=json.dumps({"type": "article-journal", "title": "T"}),
            pdf_path=self.pdf_path,
            provenance="oa",
        )
        paper = self.db.get_paper("scihub-enforced-2")
        assert paper is not None
        assert paper["provenance"] == "scihub"

    def test_no_sidecar_leaves_provenance_untouched(self):
        """Ohne Sidecar-Marker greift die Erzwingung nicht -- Negativabgrenzung,
        kein Overreach in andere Beschaffungswege."""
        self.db.add_paper(
            paper_id="no-sidecar-1",
            csl_json=json.dumps({"type": "article-journal", "title": "T"}),
            pdf_path=self.pdf_path,
        )
        paper = self.db.get_paper("no-sidecar-1")
        assert paper is not None
        assert paper["provenance"] is None

    def test_no_sidecar_explicit_value_still_respected(self):
        """Ohne Sidecar-Marker bleibt ein explizit uebergebener provenance-Wert
        unangetastet (z.B. 'oa' aus einem anderen Beschaffungsweg)."""
        self.db.add_paper(
            paper_id="no-sidecar-2",
            csl_json=json.dumps({"type": "article-journal", "title": "T"}),
            pdf_path=self.pdf_path,
            provenance="oa",
        )
        paper = self.db.get_paper("no-sidecar-2")
        assert paper is not None
        assert paper["provenance"] == "oa"

    def test_no_pdf_path_does_not_probe_filesystem(self):
        """Ohne uebergebenen pdf_path gibt es nichts zu pruefen -- provenance
        verhaelt sich wie vor #627 (Bestandswert bleibt unangetastet)."""
        self.db.add_paper(
            paper_id="no-pdf-path",
            csl_json=json.dumps({"type": "article-journal", "title": "T"}),
            provenance="oa",
        )
        paper = self.db.get_paper("no-pdf-path")
        assert paper is not None
        assert paper["provenance"] == "oa"
