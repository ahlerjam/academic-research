"""Nachvollzug des Live-Belegs zu AC1 (Issue #450) gegen das echte Netz.

Dieser Lauf ist **opt-in**: ohne ``RUN_LIVE_FREE_ARCHIVE_FETCH=1`` skippt jeder
Test. CI faehrt ihn nicht — ein Ausfall bei HathiTrust, dem Internet Archive
oder der Bayerischen Staatsbibliothek darf diese Pipeline nicht rot faerben
(dieselbe Begruendung, mit der ``docs/evals/STRATEGY.md``
``free-archive-fetchers`` als ``structural`` fuehrt).

Warum es ihn trotzdem gibt: ``evals/free-archive-fetchers/live-verification.json``
behauptet, dass am 2026-07-31 zwei der drei Archive real ein PDF ohne Login
herausgegeben haben und HathiTrust den Download-Endpunkt gesperrt hat. **Eine
Behauptung, die niemand nachfahren kann, ist kein Beleg** — genau daran ist die
erste Fassung von PR #557 gescheitert ("Realer Live-Lauf bleibt Operator-Sache").
Dies ist der Nachfahrweg::

    RUN_LIVE_FREE_ARCHIVE_FETCH=1 uv run pytest tests/test_issue_450_live_fetch.py -v

Was hart und was weich geprueft wird, ist nicht Geschmack, sondern gemessen:

* **Internet Archive** — voll hart. Zwei vollstaendige Abrufe lieferten byteweise
  dieselbe Datei; das Digitalisat traegt keinen abruf-abhaengigen Stempel. Hier
  wird ``sha256`` verglichen.
* **MDZ** — der rohe ``sha256`` scheidet aus, weil MDZ das PDF pro Anfrage neu
  zusammenstellt und dabei das ``/ID``-Array im Trailer neu vergibt. Das ist kein
  Grund, auf eine Pruefsumme zu verzichten: der Unterschied betraf gemessen
  **ausschliesslich** diese 58 Bytes, also wird gegen den normalisierten Wert
  verglichen. Zusaetzlich wird die Pflicht-Bestaetigung des Rechtehinweises
  gefahren — ohne sie gibt es kein PDF.
* **HathiTrust** — geprueft werden Status 403 und die stabilen Textmarker der
  Sperrseite. Client-IP und Cloudflare Ray ID werden ausdruecklich **nicht**
  verglichen; sie sind pro Request neu. ``test_hathitrust_ray_id_rotates`` fuehrt
  genau das vor, statt es nur zu behaupten.

Der Abruf des MDZ-Gesamtwerks (rund 148 MiB) haengt an einem zweiten Schalter,
``RUN_LIVE_FREE_ARCHIVE_FETCH_WHOLE_WORK=1`` — der Standardweg prueft denselben
Endpunkt mit einem Seitenbereich und laeuft in Sekunden.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pypdf import PdfReader

REPO_ROOT = Path(__file__).parent.parent
RECORD_PATH = REPO_ROOT / "evals" / "free-archive-fetchers" / "live-verification.json"

RUN_LIVE = os.environ.get("RUN_LIVE_FREE_ARCHIVE_FETCH") == "1"
RUN_WHOLE_WORK = os.environ.get("RUN_LIVE_FREE_ARCHIVE_FETCH_WHOLE_WORK") == "1"
TIMEOUT_SECONDS = 900
USER_AGENT = "academic-research/free-archive-fetchers (Issue #450 live verification)"

#: Ersetzt das pro Zusammenstellung neu vergebene ``/ID``-Array im PDF-Trailer.
PDF_TRAILER_ID_RE = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]")

#: Speicherknoten, auf den archive.org die Download-URL umleitet. archive.org
#: vergibt Knoten unter mehr als einem Praefix ("dn" und "ia" beide real
#: beobachtet -- Issue #612 Fix-Runde, 2026-08-03: derselbe stabile
#: Einstiegspunkt fa-02 leitete einmal auf 'ia800108.us.archive.org' und in
#: einem zweiten, unabhaengigen Netz auf 'dn720200.ca.archive.org' um). Die
#: urspruengliche Annahme (nur "dn") war zu eng und machte diesen Live-Test
#: flaky ueber ein Detail, das kein Fetcher-Fehler ist -- siehe
#: tests/test_issue_450_fetcher_evidence.py::test_ia_node_host_pattern_accepts_both_observed_node_prefixes.
IA_NODE_HOST_RE = re.compile(r"^(?:ia|dn)\d+\.[a-z]{2}\.archive\.org$")

#: Dateiname des von MDZ zusammengestellten PDF, inklusive Job-Praefix.
MDZ_RESULT_RE = re.compile(r"/pdf/(\d+)(bsb\d+\.pdf)")

CF_RAY_RE = re.compile(r"^[0-9a-f]{16}-[A-Z]{3}$")

pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="Live-Lauf gegen fremde Archivseiten — nur mit RUN_LIVE_FREE_ARCHIVE_FETCH=1",
)


def _record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def _run(eval_case: str) -> dict:
    return next(run for run in _record()["runs"] if run["eval_case"] == eval_case)


def _fetch(url: str) -> tuple[int, str, bytes, dict]:
    """Holt ``url`` anonym. Gibt (status, content_type, body, headers) zurueck.

    Ein HTTP-Fehler ist hier ein Ergebnis, kein Abbruch — der HathiTrust-Fall
    *erwartet* 403 und der Gegenprobe-Fall *erwartet* 401.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return (
                response.status,
                response.headers.get_content_type(),
                response.read(),
                dict(response.headers),
            )
    except urllib.error.HTTPError as error:  # 401/403 sind auswertbare Antworten
        return error.code, error.headers.get_content_type(), error.read(), dict(error.headers)


def _normalised_sha256(body: bytes) -> str:
    return hashlib.sha256(PDF_TRAILER_ID_RE.sub(b"/ID [<0><0>]", body)).hexdigest()


def _assert_is_pdf(body: bytes, artifact: dict, label: str) -> None:
    assert body.startswith(b"%PDF-"), (
        f"{label}: Antwort ist kein PDF (beginnt mit {body[:16]!r}) — "
        f"der aufgezeichnete Volltext-Bezug laesst sich so nicht nachfahren."
    )
    assert body[:8].decode("latin-1") == artifact["magic"]
    assert len(body) == artifact["bytes"], (
        f"{label}: {len(body)} Bytes statt der aufgezeichneten {artifact['bytes']}."
    )


def _pages(body: bytes, tmp_path: Path, name: str) -> int:
    path = tmp_path / f"{name}.pdf"
    path.write_bytes(body)
    return len(PdfReader(str(path)).pages)


# ---------------------------------------------------------------------------
# Internet Archive — der Beleg ist byteweise reproduzierbar
# ---------------------------------------------------------------------------


def test_internet_archive_still_serves_the_recorded_pdf(tmp_path: Path):
    run = _run("fa-02")
    artifact = run["artifact"]
    status, content_type, body, _ = _fetch(run["url_chain"][-1])

    assert status == artifact["http_status"]
    assert content_type == artifact["content_type"]
    _assert_is_pdf(body, artifact, "fa-02")

    assert artifact["sha256_stable"] is True
    assert hashlib.sha256(body).hexdigest() == artifact["sha256"], (
        "archive.org liefert andere Bytes als aufgezeichnet. Der Beleg ist damit "
        "nicht mehr byteweise nachfahrbar — live-verification.json anpassen und "
        "'sha256_stable' neu bewerten, statt die Assertion zu lockern."
    )
    assert _pages(body, tmp_path, "fa-02") == artifact["pages"]


def test_internet_archive_pdf_is_bound_to_the_recorded_item(tmp_path: Path):
    """Das Dokument muss sich selbst dem Item zuordnen, das der Lauf nennt."""
    run = _run("fa-02")
    _, _, body, _ = _fetch(run["url_chain"][-1])
    path = tmp_path / "fa-02.pdf"
    path.write_bytes(body)
    metadata = PdfReader(str(path)).metadata or {}

    assert metadata.get("/Title") == run["artifact"]["pdf_title"]
    assert metadata.get("/Author") == run["artifact"]["pdf_author"]
    assert run["item"]["identifier"] in (metadata.get("/Keywords") or ""), (
        "Das PDF nennt die Item-Kennung nicht mehr in seinen Metadaten — dann "
        "gehoert es womoeglich nicht mehr zu diesem Digitalisat."
    )


def test_internet_archive_redirects_to_an_assigned_node():
    """Zeigt, warum der Ziel-Hostname kein Beleg sein kann.

    Die stabile ``/download/``-URL beantwortet archive.org mit einer Umleitung
    auf einen zugewiesenen Speicherknoten. Geprueft wird die *Form* dieser
    Zuweisung — dass innerhalb weniger Sekunden zwei verschiedene Knoten
    zurueckkommen, sichert archive.org nicht zu und wird darum auch nicht
    behauptet.
    """
    entry = _run("fa-02")["url_chain"][-1]

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(entry, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            pytest.fail(f"Erwartet wurde eine Umleitung, bekommen HTTP {response.status}.")
    except urllib.error.HTTPError as error:
        assert error.code in (301, 302, 307), f"Unerwarteter Status {error.code}."
        target = error.headers["Location"]

    host = urlsplit(target).hostname or ""
    assert host != urlsplit(entry).hostname
    assert IA_NODE_HOST_RE.match(host), (
        f"Das Umleitungsziel {host!r} sieht nicht nach einem zugewiesenen "
        f"Speicherknoten aus. Dann traegt die Begruendung in "
        f"'volatile_fields_excluded' nicht mehr."
    )


def test_internet_archive_restricted_item_is_refused():
    """Die Gegenprobe: bei einem CDL-Titel gibt dieselbe URL-Form kein PDF her.

    Geprueft wird eine Menge zulaessiger Abweisungs-Codes (401, 403), kein
    einzelner fest verdrahteter Wert — archive.org hat den konkreten Code fuer
    denselben CDL-Fehlerpfad zwischen den Aufzeichnungen bereits einmal
    gewechselt (Issue #799). Fuer die Aussage dieses Tests ist gleichgueltig,
    welcher der beiden Codes es im Einzelfall ist: beide belegen eine
    Zugriffskontrolle. Was zaehlt, ist einzig, dass die Anfrage abgewiesen wird
    und kein PDF liefert.
    """
    counter = _run("fa-02")["access_control_counter_example"]
    status, _, body, _ = _fetch(counter["url"])
    allowed = counter["http_status_allowed"]
    assert status in allowed, (
        f"Das gesperrte Item antwortet mit {status}, zulaessig waeren "
        f"{allowed}. Damit waere offen, ob der Erfolg beim freien Item eine "
        f"Eigenschaft dieses Items ist oder nur die Abwesenheit jeder "
        f"Zugriffskontrolle."
    )
    assert not body.startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# MDZ — der Rechtehinweis ist Pflicht, die Pruefsumme wird normalisiert
# ---------------------------------------------------------------------------


def _mdz_assemble(url: str) -> tuple[str, bytes]:
    """Sendet das Download-Formular ab und holt das zusammengestellte PDF."""
    status, _, page, _ = _fetch(url)
    assert status == 200
    match = MDZ_RESULT_RE.search(page.decode("utf-8", errors="replace"))
    assert match, (
        "Die Antwort enthaelt keinen Link auf ein zusammengestelltes PDF. "
        "Entweder wurde der Rechtehinweis nicht akzeptiert oder MDZ hat das "
        "Formular umgebaut."
    )
    job_prefix, filename = match.group(1), match.group(2)
    pdf_status, content_type, body, _ = _fetch(
        f"https://download.digitale-sammlungen.de/pdf/{job_prefix}{filename}"
    )
    assert pdf_status == 200
    assert content_type == "application/pdf"
    return job_prefix, body


def test_mdz_refuses_without_accepting_the_rights_statement():
    """Ohne ``xdfz=2`` gibt es kein PDF — die Kernaussage von ``rights_gate``.

    Das Formularfeld steht auf "Nein" vorbelegt. Wer den Bestaetigungsschritt
    ueberspringt, bekommt HTTP 200 und wieder das Formular. Genau daran waere
    ein Agent gescheitert, der der urspruenglichen Fassung des Browser-Guides
    gefolgt waere ("Download-Icon → PDF-Option waehlen → herunterladen").
    """
    accepted = _run("fa-03")["fast_reproduction"]["url"]
    declined = accepted.replace("xdfz=2", "xdfz=1")
    status, content_type, body, _ = _fetch(declined)

    assert status == 200
    assert content_type == "text/html"
    assert not body.startswith(b"%PDF-")
    assert not MDZ_RESULT_RE.search(body.decode("utf-8", errors="replace")), (
        "MDZ liefert auch ohne Bestaetigung des Rechtehinweises ein PDF. Dann "
        "waere 'rights_gate' in live-verification.json falsch — und die "
        "Pflicht-Bestaetigung gehoerte aus dem Agenten-Flow wieder heraus."
    )


def test_mdz_serves_the_recorded_pdf_after_accepting_the_rights_statement(tmp_path: Path):
    fast = _run("fa-03")["fast_reproduction"]
    _, body = _mdz_assemble(fast["url"])

    assert body.startswith(b"%PDF-")
    assert body[:8].decode("latin-1") == fast["magic"]
    assert len(body) == fast["bytes"]
    assert _pages(body, tmp_path, "fa-03-range") == fast["pages"]
    assert _normalised_sha256(body) == fast["sha256_normalized"], (
        "Der normalisierte sha256 weicht ab. Da die Normalisierung genau das "
        "pro Lauf neu vergebene /ID-Array herausrechnet, ist das eine echte "
        "Aenderung am Digitalisat oder an der Zusammenstellung — nicht das "
        "erwartete Rauschen."
    )


def test_mdz_job_prefix_rotates():
    """Fuehrt vor, warum das Job-Praefix kein Beleg sein kann.

    MDZ legt jede Zusammenstellung unter ``/pdf/<praefix>bsb<id>.pdf`` ab. Zwei
    Anfragen genuegen, um zu zeigen, dass das Praefix pro Lauf neu vergeben wird
    — niemand kann es nachpruefen, auch der Autor nicht.
    """
    url = _run("fa-03")["fast_reproduction"]["url"]
    prefixes = []
    for _ in range(2):
        prefix, _ = _mdz_assemble(url)
        prefixes.append(prefix)
        time.sleep(2)

    assert prefixes[0] != prefixes[1], (
        "Beide Zusammenstellungen liefen unter demselben Job-Praefix. Dann waere "
        "die Annahme hinter 'volatile_fields_excluded' falsch und die Begruendung "
        "in live-verification.json muesste korrigiert werden."
    )


@pytest.mark.skipif(
    not RUN_WHOLE_WORK,
    reason="Gesamtwerk sind rund 148 MiB — nur mit RUN_LIVE_FREE_ARCHIVE_FETCH_WHOLE_WORK=1",
)
def test_mdz_serves_the_whole_work_as_one_pdf(tmp_path: Path):
    """Der eigentliche AC1-Beleg fuer MDZ: das ganze Digitalisat als eine Datei."""
    run = _run("fa-03")
    artifact = run["artifact"]
    _, body = _mdz_assemble(run["url_chain"][-1])

    _assert_is_pdf(body, artifact, "fa-03")
    assert _pages(body, tmp_path, "fa-03-whole") == artifact["pages"]
    assert _normalised_sha256(body) == artifact["sha256_normalized"]


# ---------------------------------------------------------------------------
# HathiTrust — die Sperre ist der Beleg, ihre Kennnummern sind es nicht
# ---------------------------------------------------------------------------


def test_hathitrust_download_endpoint_is_still_blocked():
    run = _run("fa-01")
    artifact = run["artifact"]
    status, content_type, body, _ = _fetch(run["url_chain"][-1])
    html = body.decode("utf-8", errors="replace")

    assert status == artifact["http_status"], (
        f"HathiTrust antwortet mit {status} statt {artifact['http_status']} — die "
        f"aufgezeichnete Begruendung fuer 'blocked_verified' traegt dann nicht "
        f"mehr und AC1 ist fuer diesen Agenten neu zu bewerten."
    )
    assert content_type == artifact["content_type"]
    assert artifact["page_title"] in html
    for marker in artifact["stable_markers"]:
        assert marker in html, f"Stabil-Marker {marker!r} fehlt in der Live-Antwort."


def test_hathitrust_bib_api_stays_open():
    """Der Grund, warum ``metadata_only`` und nicht ``no_match`` richtig ist."""
    also = _run("fa-01")["also_measured"]["bib_api_stays_open"]
    status, content_type, body, _ = _fetch(also["url"])

    assert status == also["http_status"]
    assert content_type == also["content_type"]
    assert json.loads(body.decode("utf-8")), "Bib-API antwortet mit leerem Ergebnis."


def test_hathitrust_ray_id_rotates():
    """Fuehrt vor, warum die Ray ID kein Beleg sein kann.

    Sie steht auf der Sperrseite direkt neben der Client-IP und wirkt wie ein
    harter Fall-Bezeichner. Zwei Abrufe genuegen, um zu zeigen, dass Cloudflare
    sie pro Request neu vergibt.
    """
    url = _run("fa-01")["url_chain"][-1]
    ray_ids = []
    for _ in range(2):
        _, _, _, headers = _fetch(url)
        ray = headers.get("cf-ray") or headers.get("CF-RAY")
        assert ray and CF_RAY_RE.match(ray), f"Keine verwertbare Ray ID im Header: {ray!r}"
        ray_ids.append(ray)
        time.sleep(2)

    assert ray_ids[0] != ray_ids[1], (
        "Beide Abrufe lieferten dieselbe Ray ID. Dann waere die Annahme hinter "
        "'volatile_fields_excluded' falsch."
    )
