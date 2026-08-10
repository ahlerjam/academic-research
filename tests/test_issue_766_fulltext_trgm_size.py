"""Tests fuer Issue #766: lohnt ein Trigram-Index ueber ``paper_fulltext.text``
bzw. ``notes.text``?

Die Entscheidungsregel (Issue-Kommentar vom 2026-08-10): der Index kommt nur,
wenn BEIDE Bedingungen gelten -- (1) die Vault-Datei waechst um weniger als
100 % UND (2) es liegt ein Nutzennachweis vor. Reisst Bedingung 1, faellt die
Entscheidung negativ, unabhaengig von Bedingung 2 (#789 zeigt: Bedingung 2 ist
mit dem heutigen #708-Goldset ohnehin nicht pruefbar -- 1/60 ``papers_fts``-,
0/60 ``papers_trgm``-Treffer).

Diese Tests pruefen die MESSMETHODE (Determinismus des Korpusgenerators,
Schwellenauswertung, Trennung der beiden Tabellen) -- nicht die
Marktrealitaet. Die tatsaechlichen Zahlen stehen in
``docs/evals/2026-08-10-fulltext-trgm-size-766.md``.
"""

from __future__ import annotations

from pathlib import Path

from scripts.eval.measure_fulltext_trgm_size_766 import (
    FULLTEXT_MAX_KB,
    FULLTEXT_MIN_KB,
    GROWTH_THRESHOLD_PCT,
    NOTE_MAX_KB,
    NOTE_MIN_KB,
    decide,
    generate_fulltext,
    generate_note,
    measure_fulltext_variant,
    measure_notes_variant,
)

# ---------------------------------------------------------------------------
# Korpusgenerator: deterministisch, im Zielkorridor, nicht-repetitiv
# ---------------------------------------------------------------------------


class TestGenerateFulltext:
    def test_deterministic_fuer_gleichen_seed(self):
        target = 60 * 1024
        assert generate_fulltext(seed=7, target_bytes=target) == generate_fulltext(
            seed=7, target_bytes=target
        )

    def test_unterschiedliche_seeds_liefern_unterschiedlichen_text(self):
        target = 60 * 1024
        assert generate_fulltext(seed=1, target_bytes=target) != generate_fulltext(
            seed=2, target_bytes=target
        )

    def test_trifft_den_zielkorridor(self):
        target = FULLTEXT_MIN_KB * 1024
        text = generate_fulltext(seed=3, target_bytes=target)
        size = len(text.encode("utf-8"))
        # Toleranz: der Generator stoppt satzweise, nicht auf's Byte genau.
        assert target <= size <= target * 1.2

    def test_ist_nicht_repetitiv(self):
        """Guard gegen den im Plan benannten Lorem-Ipsum-Fehler: ein Text, der
        sich staendig wiederholt, druecke den Trigram-Zuwachs kuenstlich
        niedrig -- die Messung waere geschoent. Gemessen an einem kleinen
        Textausschnitt (10 KB), weil bei sehr grossen Texten selbst ein
        breites, kombinatorisches Vokabular irgendwann erschoepft ist --
        das ist normale Sprachstatistik, kein Wiederholungsmuster."""
        target = 10 * 1024
        text = generate_fulltext(seed=4, target_bytes=target)
        words = text.split()
        unique_ratio = len(set(words)) / len(words)
        assert unique_ratio > 0.3, f"Woerterbuch zu klein/repetitiv: ratio={unique_ratio}"

    def test_kein_ganzer_satz_wiederholt_sich_direkt_hintereinander(self):
        """Echtes Lorem-Ipsum-Symptom: derselbe Satz mehrfach in Folge. Auch
        bei grossen Texten darf das nicht vorkommen."""
        target = FULLTEXT_MAX_KB * 1024
        text = generate_fulltext(seed=4, target_bytes=target)
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        consecutive_duplicates = sum(
            1 for a, b in zip(sentences, sentences[1:], strict=False) if a == b
        )
        assert consecutive_duplicates == 0


class TestGenerateNote:
    def test_deterministic_fuer_gleichen_seed(self):
        target = int(2 * 1024)
        assert generate_note(seed=11, target_bytes=target) == generate_note(
            seed=11, target_bytes=target
        )

    def test_trifft_den_zielkorridor(self):
        target = int(NOTE_MIN_KB * 1024)
        text = generate_note(seed=5, target_bytes=target)
        size = len(text.encode("utf-8"))
        # Notizen sind kurz, ein Satz kann bereits überschießen; Toleranz breiter als bei Volltexten.
        assert target <= size <= target * 2.0

    def test_notiz_bleibt_klein(self):
        """Notizen sind deutlich kleiner als Volltexte (Issue-Body-Schaetzung)."""
        target = int(NOTE_MAX_KB * 1024)
        text = generate_note(seed=6, target_bytes=target)
        assert len(text.encode("utf-8")) < FULLTEXT_MIN_KB * 1024


# ---------------------------------------------------------------------------
# Entscheidungsregel: harte 100-%-Schwelle
# ---------------------------------------------------------------------------


class TestDecisionRule:
    def test_unter_schwelle_ist_positiv(self):
        assert decide(0.0) is True
        assert decide(50.0) is True
        assert decide(99.99) is True

    def test_ab_schwelle_ist_negativ(self):
        assert decide(100.0) is False
        assert decide(100.01) is False
        assert decide(250.0) is False

    def test_default_schwelle_ist_100_prozent(self):
        assert GROWTH_THRESHOLD_PCT == 100.0

    def test_eigene_schwelle_wird_respektiert(self):
        assert decide(60.0, threshold_pct=50.0) is False
        assert decide(40.0, threshold_pct=50.0) is True


# ---------------------------------------------------------------------------
# Messung: Vorher/Nachher-Bytes fuer BEIDE Tabellen unabhaengig (AC1/AC3)
# ---------------------------------------------------------------------------


class TestMeasureFulltextVariant:
    def test_liefert_vorher_und_nachher_bytes(self, tmp_path: Path):
        result = measure_fulltext_variant(tmp_path, n_papers=3, seed=100)

        assert result["table"] == "paper_fulltext"
        assert result["n_rows"] == 3
        assert result["baseline_bytes"] > 0
        assert result["with_trgm_bytes"] > 0

    def test_growth_pct_ist_aus_den_bytes_berechnet(self, tmp_path: Path):
        result = measure_fulltext_variant(tmp_path, n_papers=3, seed=101)

        expected = round(
            (result["with_trgm_bytes"] - result["baseline_bytes"])
            / result["baseline_bytes"]
            * 100.0,
            2,
        )
        assert result["growth_pct"] == expected

    def test_trigram_index_ueber_volltext_vergroessert_die_datei(self, tmp_path: Path):
        """Ein Trigram-Index legt je Zeichenposition einen Term ab -- die Datei
        MIT Index ist nie kleiner als ohne."""
        result = measure_fulltext_variant(tmp_path, n_papers=3, seed=102)
        assert result["with_trgm_bytes"] >= result["baseline_bytes"]


class TestMeasureNotesVariant:
    def test_liefert_vorher_und_nachher_bytes(self, tmp_path: Path):
        result = measure_notes_variant(tmp_path, n_notes=5, seed=200)

        assert result["table"] == "notes"
        assert result["n_rows"] == 5
        assert result["baseline_bytes"] > 0
        assert result["with_trgm_bytes"] > 0

    def test_growth_pct_ist_aus_den_bytes_berechnet(self, tmp_path: Path):
        result = measure_notes_variant(tmp_path, n_notes=5, seed=201)

        expected = round(
            (result["with_trgm_bytes"] - result["baseline_bytes"])
            / result["baseline_bytes"]
            * 100.0,
            2,
        )
        assert result["growth_pct"] == expected


class TestBeideTabellenUnabhaengig:
    def test_fulltext_und_notes_messung_sind_getrennte_laeufe(self, tmp_path: Path):
        """Die Messung liefert je Tabelle einen EIGENEN Wert, nicht eine
        gemeinsame Zahl fuer beide (AC3-Anforderung: dieselbe Entscheidung
        MUSS fuer notes_fts getrennt begruendet werden koennen)."""
        fulltext_result = measure_fulltext_variant(tmp_path / "ft", n_papers=3, seed=300)
        notes_result = measure_notes_variant(tmp_path / "notes", n_notes=5, seed=301)

        assert fulltext_result["table"] != notes_result["table"]
        assert fulltext_result["baseline_bytes"] != notes_result["baseline_bytes"]
