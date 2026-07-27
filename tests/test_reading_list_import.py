"""Tests fuer reading-list-import Skill (TDD).

Testet parse_list.py:
- LLM-Parser (gemockt) extrahiert strukturierte Eintraege aus Plaintext
- DOI/ISBN-Resolution via gemockte Crossref-API
- Vault.add_paper wird fuer jedes resolved Item aufgerufen
- Ambigue Items triggern AskUserQuestion
- >=90% der 30 Sample-Eintraege werden korrekt verarbeitet
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Sicherstellen dass scripts im Pfad ist
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "skills" / "reading-list-import" / "scripts")
)

SAMPLE_TXT = Path(__file__).resolve().parent / "fixtures" / "reading_list" / "sample.txt"

# 1:1 von api.crossref.org aufgezeichnete Works-Antworten (nur `reference`/`abstract`
# u. ae. Grossfelder entfernt). Sie sind die einzige verlaessliche Quelle dafuer, in
# welchem Feld Crossref eine Retraktion tatsaechlich meldet — siehe Issue #383.
CROSSREF_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crossref"


def load_crossref_fixture(name: str) -> dict:
    """Laedt eine aufgezeichnete Crossref-Works-Antwort (vollstaendige Payload)."""
    return json.loads((CROSSREF_FIXTURES / name).read_text(encoding="utf-8"))


def crossref_response(payload: dict, status_code: int = 200) -> MagicMock:
    """Baut ein requests-Response-Double fuer eine Crossref-Payload."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


# ---------------------------------------------------------------------------
# Deterministisches Mock-JSON vom LLM-Parser (30 Eintraege)
# ---------------------------------------------------------------------------

PARSED_ENTRIES = [
    {
        "author": "Smith, J.; Jones, A.",
        "title": "Deep Learning for Natural Language Processing",
        "year": "2020",
        "isbn": "9780262043724",
        "doi": None,
    },
    {
        "author": "Doe, J.",
        "title": "Attention Mechanisms in Neural Networks",
        "year": "2019",
        "doi": "10.5555/3305381.3305382",
        "isbn": None,
    },
    {
        "author": "Brown, T.",
        "title": "Language Models are Few-Shot Learners",
        "year": "2020",
        "doi": "10.48550/arXiv.2005.14165",
        "isbn": None,
    },
    {
        "author": "LeCun, Y.; Bengio, Y.; Hinton, G.",
        "title": "Deep learning",
        "year": "2015",
        "doi": "10.1038/nature14539",
        "isbn": None,
    },
    {
        "author": "Vaswani, A.",
        "title": "Attention Is All You Need",
        "year": "2017",
        "doi": "10.48550/arXiv.1706.03762",
        "isbn": None,
    },
    {
        "author": "Goodfellow, I.; Bengio, Y.; Courville, A.",
        "title": "Deep Learning",
        "year": "2016",
        "isbn": "9780262035613",
        "doi": None,
    },
    {
        "author": "Devlin, J.",
        "title": "BERT: Pre-training of Deep Bidirectional Transformers",
        "year": "2019",
        "doi": "10.18653/v1/N19-1423",
        "isbn": None,
    },
    {
        "author": "Hochreiter, S.; Schmidhuber, J.",
        "title": "Long Short-Term Memory",
        "year": "1997",
        "doi": "10.1162/neco.1997.9.8.1735",
        "isbn": None,
    },
    {
        "author": "Sutskever, I.",
        "title": "Sequence to Sequence Learning with Neural Networks",
        "year": "2014",
        "doi": "10.48550/arXiv.1409.3215",
        "isbn": None,
    },
    {
        "author": "Mikolov, T.",
        "title": "Efficient Estimation of Word Representations in Vector Space",
        "year": "2013",
        "doi": "10.48550/arXiv.1301.3781",
        "isbn": None,
    },
    {
        "author": "Radford, A.; Wu, J.; Child, R.; Luan, D.",
        "title": "Language Models are Unsupervised Multitask Learners",
        "year": "2019",
        "doi": None,
        "isbn": None,
    },
    {
        "author": "He, K.",
        "title": "Deep Residual Learning for Image Recognition",
        "year": "2016",
        "doi": "10.1109/CVPR.2016.90",
        "isbn": None,
    },
    {
        "author": "Pennington, J.; Socher, R.; Manning, C.",
        "title": "GloVe: Global Vectors for Word Representation",
        "year": "2014",
        "doi": "10.3115/v1/D14-1162",
        "isbn": None,
    },
    {
        "author": "Kingma, D.P.; Ba, J.",
        "title": "Adam: A Method for Stochastic Optimization",
        "year": "2015",
        "doi": None,
        "isbn": None,
    },
    {
        "author": "Srivastava, N.",
        "title": "Dropout: A Simple Way to Prevent Neural Networks from Overfitting",
        "year": "2014",
        "doi": None,
        "isbn": None,
    },
    {
        "author": "Hochreiter, S.",
        "title": "The Vanishing Gradient Problem During Learning Recurrent Neural Nets",
        "year": "1998",
        "doi": None,
        "isbn": None,
    },
    {
        "author": "Bengio, Y.",
        "title": "Learning Long-Term Dependencies with Gradient Descent is Difficult",
        "year": "1994",
        "doi": "10.1109/72.279181",
        "isbn": None,
    },
    {
        "author": "Rumelhart, D.E.",
        "title": "Learning representations by back-propagating errors",
        "year": "1986",
        "doi": "10.1038/323533a0",
        "isbn": None,
    },
    {
        "author": "Minsky, M.; Papert, S.",
        "title": "Perceptrons: An Introduction to Computational Geometry",
        "year": "1969",
        "isbn": "9780262630221",
        "doi": None,
    },
    {
        "author": "Rosenblatt, F.",
        "title": "The Perceptron: A Probabilistic Model",
        "year": "1958",
        "doi": None,
        "isbn": None,
    },
    {
        "author": "McCulloch, W.S.; Pitts, W.",
        "title": "A Logical Calculus of the Ideas Immanent in Nervous Activity",
        "year": "1943",
        "doi": None,
        "isbn": None,
    },
    {
        "author": "Bahdanau, D.",
        "title": "Neural Machine Translation by Jointly Learning to Align and Translate",
        "year": "2015",
        "doi": "10.48550/arXiv.1409.0473",
        "isbn": None,
    },
    {
        "author": "Cho, K.",
        "title": "Learning Phrase Representations using RNN Encoder-Decoder",
        "year": "2014",
        "doi": "10.3115/v1/D14-1179",
        "isbn": None,
    },
    {
        "author": "Krizhevsky, A.",
        "title": "ImageNet Classification with Deep Convolutional Neural Networks",
        "year": "2012",
        "doi": "10.1145/3065386",
        "isbn": None,
    },
    {
        "author": "Zeiler, M.D.",
        "title": "Visualizing and Understanding Convolutional Networks",
        "year": "2014",
        "doi": "10.1007/978-3-319-10590-1_53",
        "isbn": None,
    },
    {
        "author": "Simonyan, K.; Zisserman, A.",
        "title": "Very Deep Convolutional Networks",
        "year": "2015",
        "doi": None,
        "isbn": None,
    },
    {
        "author": "Schmidhuber, J.",
        "title": "Deep Learning in Neural Networks: An Overview",
        "year": "2015",
        "doi": "10.1016/j.neunet.2014.09.003",
        "isbn": None,
    },
    {
        "author": "Graves, A.",
        "title": "Speech Recognition with Deep Recurrent Neural Networks",
        "year": "2013",
        "doi": "10.1109/ICASSP.2013.6638947",
        "isbn": None,
    },
    {
        "author": "Collobert, R.",
        "title": "Natural Language Processing (Almost) from Scratch",
        "year": "2011",
        "doi": None,
        "isbn": None,
    },
    {
        "author": "Ioffe, S.; Szegedy, C.",
        "title": "Batch Normalization",
        "year": "2015",
        "doi": "10.48550/arXiv.1502.03167",
        "isbn": None,
    },
]

# Deliberat ambige Eintraege fuer AskUserQuestion-Test (Item-Index 11 und 14)
AMBIGUOUS_ENTRY = {
    "author": "Radford, A.",
    "title": "Language Models",
    "year": "2019",
    "doi": None,
    "isbn": None,
    "_ambiguous": True,
    "_candidates": [
        {"title": "Language Models are Few-Shot Learners", "doi": "10.48550/arXiv.2005.14165"},
        {"title": "Language Models are Unsupervised Multitask Learners", "doi": None},
    ],
}


def _make_csl(entry: dict) -> str:
    """Erstellt minimales CSL-JSON aus einem geparsten Eintrag."""
    csl = {
        "type": "article-journal" if entry.get("doi") else "book",
        "title": entry["title"],
        "author": [{"literal": entry["author"]}],
        "issued": {"date-parts": [[int(entry["year"])]]},
    }
    return json.dumps(csl, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseText:
    """Unit-Tests fuer extract_text() und llm_parse()."""

    def test_extract_text_from_txt(self, tmp_path):
        """extract_text liest .txt-Datei korrekt."""
        from parse_list import extract_text

        sample = tmp_path / "refs.txt"
        sample.write_text("Line one\nLine two\n", encoding="utf-8")
        result = extract_text(str(sample))
        assert "Line one" in result
        assert "Line two" in result

    def test_extract_text_from_md(self, tmp_path):
        """extract_text liest .md-Datei korrekt."""
        from parse_list import extract_text

        sample = tmp_path / "refs.md"
        sample.write_text("# Refs\n\n- Author (2020). Title.\n", encoding="utf-8")
        result = extract_text(str(sample))
        assert "Author" in result

    def test_llm_parse_returns_list(self):
        """llm_parse() gibt Liste von Dicts zurueck."""
        from parse_list import llm_parse

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps(PARSED_ENTRIES[:3]))]
        )
        result = llm_parse("some text", client=mock_client)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["title"] == PARSED_ENTRIES[0]["title"]

    def test_llm_parse_handles_json_in_markdown(self):
        """llm_parse() kann JSON aus Markdown-Code-Block extrahieren."""
        from parse_list import llm_parse

        wrapped = f"```json\n{json.dumps(PARSED_ENTRIES[:2])}\n```"
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text=wrapped)])
        result = llm_parse("some text", client=mock_client)
        assert len(result) == 2

    def test_llm_parse_invalid_json_raises(self):
        """llm_parse() wirft ValueError bei nicht-parse-barem JSON."""
        from parse_list import llm_parse

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Das ist kein JSON")]
        )
        with pytest.raises(ValueError, match="LLM-Parser"):
            llm_parse("some text", client=mock_client)


class TestResolveEntry:
    """Unit-Tests fuer resolve_doi() und resolve_isbn()."""

    def test_resolve_doi_success(self):
        """resolve_doi() gibt CSL-JSON bei bekanntem DOI zurueck."""
        from parse_list import resolve_doi

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "title": ["Deep learning"],
                "author": [{"given": "Yann", "family": "LeCun"}],
                "published": {"date-parts": [[2015]]},
                "DOI": "10.1038/nature14539",
                "type": "journal-article",
            }
        }
        with patch("requests.get", return_value=mock_resp):
            csl = resolve_doi("10.1038/nature14539")
        assert csl is not None
        data = json.loads(csl)
        assert data["title"] == "Deep learning"
        assert data["DOI"] == "10.1038/nature14539"

    def test_resolve_doi_not_found(self):
        """resolve_doi() gibt None bei HTTP 404 zurueck."""
        from parse_list import resolve_doi

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("requests.get", return_value=mock_resp):
            result = resolve_doi("10.9999/nonexistent")
        assert result is None

    def test_resolve_doi_normalizes_url(self):
        """resolve_doi() normalisiert doi.org-URL zu nacktem DOI."""
        from parse_list import resolve_doi

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "title": ["Test"],
                "author": [],
                "published": {"date-parts": [[2020]]},
                "DOI": "10.1234/test",
                "type": "journal-article",
            }
        }
        with patch("requests.get", return_value=mock_resp) as mock_get:
            resolve_doi("https://doi.org/10.1234/test")
        # Stellt sicher dass requests.get mit normalisiertem DOI (ohne doi.org-Praefix) aufgerufen wurde
        called_url = mock_get.call_args[0][0]
        assert "10.1234/test" in called_url
        # doi.org-Praefix wurde entfernt (Crossref-API benoetigt nackten DOI)
        assert "https://api.crossref.org/works/10.1234/test" == called_url

    def test_resolve_isbn_delegates_to_book_resolve(self):
        """resolve_isbn() delegiert an book_resolve-Helper."""
        from parse_list import resolve_isbn

        fake_csl = json.dumps({"type": "book", "title": "Deep Learning", "isbn": "9780262035613"})
        with patch("parse_list.book_resolve_isbn", return_value=fake_csl):
            result = resolve_isbn("9780262035613")
        assert result is not None
        data = json.loads(result)
        assert data["title"] == "Deep Learning"


class TestCheckRetraction:
    """Unit-Tests fuer check_retraction() (Crossref update-type:retraction, Issue #383).

    Crossref-Semantik (gegen die Live-API verifiziert, Fixtures in fixtures/crossref/):
    - Der zurueckgezogene ARTIKEL traegt `message.updated-by` mit `type == "retraction"`
      und hat gar kein `update-to`-Feld.
    - `message.update-to` traegt umgekehrt die RETRACTION-NOTIZ; sie zeigt auf den
      zurueckgezogenen Artikel und ist selbst nicht zurueckgezogen.
    check_retraction() bekommt den DOI des Papers — also ist `updated-by` das
    richtige Feld. Auf `update-to` zu pruefen dreht die Relation um und liefert
    fuer jedes real zurueckgezogene Paper False.
    """

    def test_true_for_real_retracted_article_payload(self):
        """Reale Crossref-Payload eines zurueckgezogenen Artikels wird als Retraction erkannt."""
        from parse_list import check_retraction

        payload = load_crossref_fixture("retracted_article.json")
        message = payload["message"]

        # Beweist, warum die Pruefung auf `update-to` in Produktion nie greifen kann:
        # das Feld existiert auf dem zurueckgezogenen Artikel schlicht nicht.
        assert "update-to" not in message
        assert any(entry["type"] == "retraction" for entry in message["updated-by"])

        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction(message["DOI"])
        assert result is True

    def test_false_for_real_retraction_notice_payload(self):
        """Die Retraction-NOTIZ selbst ist nicht zurueckgezogen (nur ihr `update-to`-Ziel)."""
        from parse_list import check_retraction

        payload = load_crossref_fixture("retraction_notice.json")
        message = payload["message"]

        # Die Notiz traegt genau das Feld, das die alte Implementierung ausgewertet hat.
        assert any(entry["type"] == "retraction" for entry in message["update-to"])
        assert "updated-by" not in message

        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction(message["DOI"])
        assert result is False

    def test_false_for_real_regular_article_payload(self):
        """Reale Crossref-Payload eines regulaeren Artikels loest keine Retraction aus."""
        from parse_list import check_retraction

        payload = load_crossref_fixture("regular_article.json")
        message = payload["message"]
        assert "updated-by" not in message

        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction(message["DOI"])
        assert result is False

    def test_true_when_updated_by_contains_retraction(self):
        """check_retraction() gibt True zurueck wenn message.updated-by eine Retraction enthaelt."""
        from parse_list import check_retraction

        payload = {
            "message": {
                "DOI": "10.1234/retracted",
                "updated-by": [
                    {
                        "type": "retraction",
                        "DOI": "10.1234/retraction-notice",
                        "label": "Retraction",
                        "source": "retraction-watch",
                    }
                ],
            }
        }
        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction("10.1234/retracted")
        assert result is True

    def test_false_when_no_update_field(self):
        """check_retraction() gibt False zurueck bei regulaerem Paper ohne updated-by."""
        from parse_list import check_retraction

        payload = {
            "message": {
                "DOI": "10.1234/regular",
                "title": ["A Regular Paper"],
            }
        }
        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction("10.1234/regular")
        assert result is False

    def test_false_when_updated_by_has_other_type(self):
        """check_retraction() gibt False zurueck wenn updated-by nur Korrekturen enthaelt."""
        from parse_list import check_retraction

        payload = {
            "message": {
                "DOI": "10.1234/corrected",
                "updated-by": [{"type": "correction", "DOI": "10.1234/correction-notice"}],
            }
        }
        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction("10.1234/corrected")
        assert result is False

    def test_false_when_updated_by_is_json_null(self):
        """Ein explizites JSON-null in updated-by darf keinen TypeError ausloesen."""
        from parse_list import check_retraction

        payload = {"message": {"DOI": "10.1234/null-field", "updated-by": None}}
        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction("10.1234/null-field")
        assert result is False

    def test_false_on_404(self):
        """check_retraction() gibt False zurueck bei HTTP 404 (fail-safe)."""
        from parse_list import check_retraction

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("requests.get", return_value=mock_resp):
            result = check_retraction("10.9999/nonexistent")
        assert result is False

    def test_false_on_network_exception(self):
        """check_retraction() gibt False zurueck bei Netzwerk-Fehler (fail-safe, AC3)."""
        from parse_list import check_retraction

        with patch("requests.get", side_effect=ConnectionError("network down")):
            result = check_retraction("10.1234/whatever")
        assert result is False

    def test_false_on_empty_doi(self):
        """check_retraction() gibt False zurueck bei leerem DOI, ohne Netzwerk-Call."""
        from parse_list import check_retraction

        with patch("requests.get") as mock_get:
            result = check_retraction("")
        assert result is False
        mock_get.assert_not_called()


class TestImportPipeline:
    """Integrationstests fuer import_reading_list() — 90%-Kriterium."""

    def _run_import(self, entries, mock_vault_add, mock_ask=None, crossref_fixture=None):
        """Hilfsmethode: fuehrt Import mit gemocktem LLM und Vault aus.

        `check_retraction()` wird bewusst NICHT gemockt — gemockt wird nur die
        HTTP-Grenze (`requests.get`), sodass die echte Retraction-Auswertung gegen
        eine reale Crossref-Payload laeuft. Default ist ein regulaerer Artikel.
        """
        from parse_list import import_reading_list

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps(entries))]
        )

        # Alle DOIs/ISBNs erfolgreich resolven
        def fake_resolve_doi(doi):
            if doi:
                csl = {"type": "article-journal", "title": "Resolved", "DOI": doi}
                return json.dumps(csl)
            return None

        def fake_resolve_isbn(isbn):
            if isbn:
                csl = {"type": "book", "title": "Resolved Book", "isbn": isbn}
                return json.dumps(csl)
            return None

        crossref_payload = load_crossref_fixture(crossref_fixture or "regular_article.json")

        with (
            patch("parse_list.resolve_doi", side_effect=fake_resolve_doi),
            patch("parse_list.resolve_isbn", side_effect=fake_resolve_isbn),
            patch("parse_list.vault_add_paper", mock_vault_add),
            patch("requests.get", return_value=crossref_response(crossref_payload)),
            patch("parse_list.vault_add_excluded_source") as mock_excluded,
        ):
            self._last_mock_excluded = mock_excluded
            if mock_ask:
                with patch("parse_list.ask_user_question", mock_ask):
                    return import_reading_list(
                        str(SAMPLE_TXT),
                        db_path=":memory:",
                        llm_client=mock_client,
                    )
            else:
                return import_reading_list(
                    str(SAMPLE_TXT),
                    db_path=":memory:",
                    llm_client=mock_client,
                )

    def test_90_percent_imported(self):
        """>=28 von 30 Eintraegen werden erfolgreich via vault.add_paper importiert."""
        mock_vault_add = MagicMock()

        result = self._run_import(PARSED_ENTRIES, mock_vault_add)

        imported = mock_vault_add.call_count
        assert imported >= 28, (
            f"Nur {imported}/30 Eintraege importiert — Mindestquote 28 (90%) nicht erreicht"
        )
        assert result["imported"] >= 28
        assert result["total"] == 30

    def test_vault_add_paper_called_with_correct_args(self):
        """vault.add_paper wird mit paper_id, csl_json, doi/isbn aufgerufen."""
        mock_vault_add = MagicMock()

        self._run_import(PARSED_ENTRIES[:3], mock_vault_add)

        assert mock_vault_add.call_count >= 2  # mindestens die mit DOI/ISBN
        # Pruefe dass call-args das korrekte Schema haben
        for c in mock_vault_add.call_args_list:
            kwargs = c[1] if c[1] else {}
            args = c[0] if c[0] else ()
            # paper_id muss ein nicht-leerer String sein
            paper_id = kwargs.get("paper_id") or (args[0] if args else None)
            assert paper_id, "paper_id darf nicht leer sein"
            # csl_json muss valides JSON sein
            csl_json = kwargs.get("csl_json") or (args[1] if len(args) > 1 else None)
            assert csl_json, "csl_json darf nicht leer sein"
            json.loads(csl_json)  # wirft bei ungueltigem JSON

    def test_ambiguous_entry_triggers_ask_user_question(self):
        """Bei Mehrdeutigkeit wird AskUserQuestion aufgerufen."""
        mock_vault_add = MagicMock()
        mock_ask = MagicMock(return_value=0)  # User waehlt ersten Kandidaten

        ambiguous_entries = [PARSED_ENTRIES[0], AMBIGUOUS_ENTRY]

        self._run_import(ambiguous_entries, mock_vault_add, mock_ask=mock_ask)

        mock_ask.assert_called_once()
        call_kwargs = mock_ask.call_args[1] if mock_ask.call_args[1] else {}
        call_args = mock_ask.call_args[0] if mock_ask.call_args[0] else ()
        # Frage oder options muss die Kandidaten enthalten
        question_text = str(call_args) + str(call_kwargs)
        assert "Language Models" in question_text or len(call_args) > 0 or len(call_kwargs) > 0

    def test_result_dict_structure(self):
        """import_reading_list() gibt Dict mit imported/skipped/total zurueck."""
        mock_vault_add = MagicMock()
        result = self._run_import(PARSED_ENTRIES[:5], mock_vault_add)

        assert "imported" in result
        assert "skipped" in result
        assert "total" in result
        assert result["total"] == 5

    def test_entries_without_doi_or_isbn_still_imported(self):
        """Eintraege ohne DOI/ISBN werden trotzdem per Fallback importiert."""
        mock_vault_add = MagicMock()
        no_id_entries = [
            {
                "author": "Rosenblatt, F.",
                "title": "The Perceptron",
                "year": "1958",
                "doi": None,
                "isbn": None,
            },
            {
                "author": "McCulloch, W.S.",
                "title": "Logical Calculus",
                "year": "1943",
                "doi": None,
                "isbn": None,
            },
        ]
        result = self._run_import(no_id_entries, mock_vault_add)
        # Auch ohne DOI/ISBN soll vault.add_paper aufgerufen werden
        assert mock_vault_add.call_count >= 2
        assert result["imported"] >= 2

    def test_skipped_count_on_resolve_failure(self):
        """Eintraege die nicht resolvet werden koennen, werden als 'skipped' gezaehlt."""
        from parse_list import import_reading_list

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps(PARSED_ENTRIES[:3]))]
        )
        mock_vault_add = MagicMock()

        # Resolve schlaegt immer fehl
        def always_fail_doi(doi):
            return None

        def always_fail_isbn(isbn):
            return None

        with (
            patch("parse_list.resolve_doi", side_effect=always_fail_doi),
            patch("parse_list.resolve_isbn", side_effect=always_fail_isbn),
            patch("parse_list.vault_add_paper", mock_vault_add),
        ):
            result = import_reading_list(
                str(SAMPLE_TXT),
                db_path=":memory:",
                llm_client=mock_client,
            )

        # Eintraege ohne DOI/ISBN-Resolution: Fallback-Pfad oder skipped
        assert result["total"] == 3

    def test_retracted_paper_marked_as_excluded_source(self):
        """AC1: Ein als retracted erkanntes Paper wird automatisch excluded_source.

        Laeuft ueber die echte check_retraction()-Auswertung einer realen
        Crossref-Payload — nur `requests.get` ist gemockt.
        """
        mock_vault_add = MagicMock()
        entry = dict(PARSED_ENTRIES[1])  # hat DOI

        self._run_import([entry], mock_vault_add, crossref_fixture="retracted_article.json")

        mock_excluded = self._last_mock_excluded
        mock_excluded.assert_called_once()
        call_kwargs = mock_excluded.call_args[1] if mock_excluded.call_args[1] else {}
        call_args = mock_excluded.call_args[0] if mock_excluded.call_args[0] else ()
        paper_id = call_kwargs.get("paper_id") or (call_args[1] if len(call_args) > 1 else None)
        assert paper_id, "paper_id darf bei vault_add_excluded_source nicht leer sein"

    def test_regular_paper_not_marked_as_excluded_source(self):
        """AC2: Ein reguläres, nicht zurückgezogenes Paper löst keine Markierung aus."""
        mock_vault_add = MagicMock()
        entry = dict(PARSED_ENTRIES[1])  # hat DOI

        result = self._run_import([entry], mock_vault_add, crossref_fixture="regular_article.json")

        mock_excluded = self._last_mock_excluded
        mock_excluded.assert_not_called()
        assert result["imported"] == 1

    def test_retraction_notice_not_marked_as_excluded_source(self):
        """AC2: Die Retraction-NOTIZ selbst ist kein zurueckgezogenes Paper.

        Die alte Implementierung (Pruefung auf `update-to`) haette hier als
        einzigem Fall True geliefert — genau falsch herum.
        """
        mock_vault_add = MagicMock()
        entry = dict(PARSED_ENTRIES[1])  # hat DOI

        result = self._run_import(
            [entry], mock_vault_add, crossref_fixture="retraction_notice.json"
        )

        self._last_mock_excluded.assert_not_called()
        assert result["imported"] == 1

    def test_crossref_outage_does_not_block_import(self):
        """AC3: Ein echter Crossref-Ausfall blockiert den Ingest nicht.

        Gemockt wird nur `requests.get` — die Fail-safe-Logik in check_retraction()
        laeuft dabei wirklich durch.
        """
        from parse_list import import_reading_list

        mock_client = MagicMock()
        entry = dict(PARSED_ENTRIES[1])  # hat DOI
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps([entry]))]
        )
        mock_vault_add = MagicMock()

        def fake_resolve_doi(doi):
            return json.dumps({"type": "article-journal", "title": "Resolved", "DOI": doi})

        with (
            patch("parse_list.resolve_doi", side_effect=fake_resolve_doi),
            patch("parse_list.vault_add_paper", mock_vault_add),
            patch("requests.get", side_effect=ConnectionError("Crossref down")),
            patch("parse_list.vault_add_excluded_source") as mock_excluded,
        ):
            result = import_reading_list(
                str(SAMPLE_TXT),
                db_path=":memory:",
                llm_client=mock_client,
            )

        assert result["imported"] == 1
        assert result["errors"] == []
        mock_vault_add.assert_called_once()
        mock_excluded.assert_not_called()

    def test_retraction_check_failure_does_not_block_import(self):
        """AC3, zweite Verteidigungslinie: wirft check_retraction() wider Erwarten
        doch eine Exception, faengt der try/except am Call-Standort sie ab."""
        from parse_list import import_reading_list

        mock_client = MagicMock()
        entry = dict(PARSED_ENTRIES[1])  # hat DOI
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps([entry]))]
        )
        mock_vault_add = MagicMock()

        def fake_resolve_doi(doi):
            return json.dumps({"type": "article-journal", "title": "Resolved", "DOI": doi})

        with (
            patch("parse_list.resolve_doi", side_effect=fake_resolve_doi),
            patch("parse_list.vault_add_paper", mock_vault_add),
            patch("parse_list.check_retraction", side_effect=Exception("Crossref down")),
            patch("parse_list.vault_add_excluded_source") as mock_excluded,
        ):
            result = import_reading_list(
                str(SAMPLE_TXT),
                db_path=":memory:",
                llm_client=mock_client,
            )

        assert result["imported"] == 1
        mock_vault_add.assert_called_once()
        mock_excluded.assert_not_called()

    def test_excluded_source_write_failure_is_surfaced(self):
        """Schlaegt vault_add_excluded_source() nach erkannter Retraction fehl,
        darf das nicht spurlos verschluckt werden (except Exception: pass).

        Die erkannte Retraktion ginge sonst ohne jedes Signal verloren:
        kein Eintrag in errors, kein Log, kein Test - Regression zu PR #419.
        """
        from parse_list import import_reading_list

        mock_client = MagicMock()
        entry = dict(PARSED_ENTRIES[1])  # hat DOI
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps([entry]))]
        )
        mock_vault_add = MagicMock()

        def fake_resolve_doi(doi):
            return json.dumps({"type": "article-journal", "title": "Resolved", "DOI": doi})

        retracted = load_crossref_fixture("retracted_article.json")

        with (
            patch("parse_list.resolve_doi", side_effect=fake_resolve_doi),
            patch("parse_list.vault_add_paper", mock_vault_add),
            patch("requests.get", return_value=crossref_response(retracted)),
            patch(
                "parse_list.vault_add_excluded_source",
                side_effect=RuntimeError("vault locked"),
            ) as mock_excluded,
        ):
            result = import_reading_list(
                str(SAMPLE_TXT),
                db_path=":memory:",
                llm_client=mock_client,
            )

        # Der Ingest selbst bleibt unberuehrt (fail-safe fuer den regulaeren Import) ...
        mock_vault_add.assert_called_once()
        assert result["imported"] == 1

        # ... aber der Fehlschlag beim Markieren als excluded_source muss sichtbar sein.
        mock_excluded.assert_called_once()
        assert result["errors"], (
            "Eine erkannte Retraktion, die nicht in den Vault geschrieben werden konnte, "
            "muss in result['errors'] auftauchen statt spurlos zu verschwinden"
        )
        assert any("vault locked" in e or "excluded_source" in e for e in result["errors"])


class TestFileFormats:
    """Tests fuer verschiedene Input-Formate."""

    def test_detect_format_txt(self, tmp_path):
        """detect_format erkennt .txt-Dateien."""
        from parse_list import detect_format

        f = tmp_path / "refs.txt"
        f.write_text("text")
        assert detect_format(str(f)) == "txt"

    def test_detect_format_md(self, tmp_path):
        """detect_format erkennt .md-Dateien."""
        from parse_list import detect_format

        f = tmp_path / "refs.md"
        f.write_text("text")
        assert detect_format(str(f)) == "md"

    def test_detect_format_pdf(self, tmp_path):
        """detect_format erkennt .pdf-Dateien."""
        from parse_list import detect_format

        f = tmp_path / "refs.pdf"
        f.write_bytes(b"%PDF-1.4")
        assert detect_format(str(f)) == "pdf"

    def test_detect_format_unknown_raises(self, tmp_path):
        """detect_format wirft ValueError bei unbekanntem Format."""
        from parse_list import detect_format

        f = tmp_path / "refs.xyz"
        f.write_text("text")
        with pytest.raises(ValueError, match="Unbekanntes"):
            detect_format(str(f))

    def test_extract_text_sample_fixture(self):
        """extract_text liest das reale Sample-Fixture ein."""
        from parse_list import extract_text

        text = extract_text(str(SAMPLE_TXT))
        assert len(text) > 500
        assert "LeCun" in text
        assert "Vaswani" in text


class TestSkillSizeBaseline:
    """Sicherstellt dass reading-list-import in skill_sizes.json eingetragen ist."""

    def test_reading_list_import_in_baseline(self):
        """skills/reading-list-import/SKILL.md existiert und ist in Baseline eingetragen."""
        baseline_path = Path(__file__).resolve().parent / "baselines" / "skill_sizes.json"
        with open(baseline_path) as f:
            baselines = json.load(f)
        assert "reading-list-import" in baselines, (
            "reading-list-import fehlt in tests/baselines/skill_sizes.json"
        )
        assert baselines["reading-list-import"] > 0

    def test_skill_md_exists(self):
        """skills/reading-list-import/SKILL.md ist vorhanden."""
        skill_path = (
            Path(__file__).resolve().parent.parent / "skills" / "reading-list-import" / "SKILL.md"
        )
        assert skill_path.exists(), f"SKILL.md nicht gefunden: {skill_path}"
