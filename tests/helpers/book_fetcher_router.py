"""
BookFetcherRouter -- testbarer Python-Spiegel der Routing-Logik aus agents/book-fetcher.md.

Dieser Modul implementiert dieselbe Routing-Logik, die der Agent-Prompt beschreibt,
damit wir sie mit unittest.mock testen koennen ohne echte Subagenten aufzurufen.
"""

import datetime
import re

GUIDE_DIR = "config/browser_guides"

# Subagent-Reihenfolgen (aus L0-Notes und Spec G.md)
# Issue #450: hathitrust/internetarchive/mdz stehen am Ende der OA-Liste
# (lizenzfrei, daher weiterhin vor allen Verlags-Subagenten).
# Issue #840: die sechs Sites ohne dedizierten Agenten laufen ueber den
# parametrisierten generic-fetcher ("Ultimate Fetcher") mit `site_config`.
# Die REIHENFOLGE bleibt unveraendert -- sie traegt die #450-AC3-Invariante.
OA_SITES = [
    {"site": "doab", "site_config": f"{GUIDE_DIR}/doab.md"},
    {"site": "oapen", "site_config": f"{GUIDE_DIR}/oapen.md"},
    {"site": "tib", "subagent": "tib-fetcher"},
    {"site": "kvk", "site_config": f"{GUIDE_DIR}/kvk.md"},
    {"site": "hathitrust", "site_config": f"{GUIDE_DIR}/hathitrust.md"},
    {"site": "internetarchive", "site_config": f"{GUIDE_DIR}/internetarchive.md"},
    {"site": "mdz", "site_config": f"{GUIDE_DIR}/mdz.md"},
]

PUBLISHER_DOMAIN_MAP = {
    "link.springer.com": {"site": "springer", "subagent": "springer-book"},
    "degruyter.com": {"site": "degruyter", "subagent": "degruyter"},
    "nationallizenzen.de": {
        "site": "nationallizenzen",
        "site_config": f"{GUIDE_DIR}/nationallizenzen.md",
    },
    "ebookcentral.proquest.com": {
        "site": "ebook-central",
        "site_config": f"{GUIDE_DIR}/ebook-central.md",
    },
    "cambridge.org": {"site": "cambridge", "subagent": "cambridge-core"},
    "academic.oup.com": {"site": "oxford", "subagent": "oxford-academic"},
    "jstor.org": {"site": "jstor", "subagent": "jstor"},
}


def subagent_for(entry: dict) -> str:
    """Der Agent, den book-fetcher fuer diesen Site-Eintrag aufruft."""
    return entry.get("subagent", "generic-fetcher")


def is_free_tier_call(subagent: str, payload: dict) -> bool:
    """True, wenn dieser Dispatch zur freien Stufe (Schritt 3) gehoert.

    Seit #840 reicht der Agent-Name dafuer nicht mehr: `generic-fetcher` wird
    sowohl fuer sechs freie Sites (je mit eigener `site_config`) als auch als
    guide-freier Fallback in Schritt 5 aufgerufen. Unterscheidungsmerkmal ist
    die `site_config` im Payload.
    """
    for entry in OA_SITES:
        if subagent_for(entry) != subagent:
            continue
        if "site_config" not in entry:
            return True
        if payload.get("site_config") == entry["site_config"]:
            return True
    return False


class BookFetcherRouter:
    """
    Simuliert die Routing-Logik des book-fetcher Master-Agenten.

    dispatch_subagent() kann in Tests gepatch werden, um echte Subagenten-
    Aufrufe zu simulieren.
    """

    def __init__(self, profile: dict):
        """
        Args:
            profile: Geparste active.yaml (dict mit licensed_sites, bib_pickup_url etc.)
        """
        self.profile = profile
        self.licensed_sites = set(profile.get("licensed_sites", []))
        self.bib_pickup_url = profile.get("bib_pickup_url", "")

    # ------------------------------------------------------------------
    # Input Parsing
    # ------------------------------------------------------------------

    def parse_input(self, raw: str) -> tuple:
        """
        Erkennt den Eingabe-Typ und gibt (typ, normalisierter_wert) zurueck.

        Typen: 'isbn', 'doi', 'url', 'title'
        """
        text = raw.strip()

        # Explizites 'isbn:'-Prefix
        if text.lower().startswith("isbn:"):
            val = text[5:].strip()
            return ("isbn", val)

        # URL
        if text.startswith("http://") or text.startswith("https://"):
            return ("url", text)

        # DOI (beginnt mit 10.)
        if re.match(r"10\.\d{4,}/", text):
            return ("doi", text)

        # ISBN-13: 13 Ziffern (mit oder ohne Bindestriche/Leerzeichen), beginnt mit 978 oder 979
        digits_only = re.sub(r"[- ]", "", text)
        if re.match(r"^97[89]\d{10}$", digits_only):
            return ("isbn", text)

        # ISBN-10: 10 Ziffern (letztes Zeichen darf X sein), mit oder ohne Bindestriche
        if re.match(r"^\d{9}[\dX]$", digits_only):
            return ("isbn", text)

        # Freitext / Titel
        return ("title", text)

    # ------------------------------------------------------------------
    # Subagent Dispatch (real implementation uses Agent(...) tool)
    # ------------------------------------------------------------------

    def dispatch_subagent(self, subagent_name: str, payload: dict) -> dict:
        """
        Wird in Tests durch unittest.mock.patch.object ersetzt.
        In Produktion wuerde der Agent-Prompt hier Agent(...) aufrufen.
        """
        raise NotImplementedError(
            "dispatch_subagent must be patched in tests or overridden for production"
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _ts(self) -> str:
        return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

    def _try_entry(self, subagent: str, status: str, site: str | None = None) -> dict:
        entry = {"subagent": subagent, "status": status, "ts": self._ts()}
        if site is not None:
            # Issue #840: mehrere tries-Eintraege lauten `generic-fetcher` --
            # erst `site` macht die Kette wieder eindeutig diagnostizierbar.
            entry["site"] = site
        return entry

    @staticmethod
    def _site_payload(payload_base: dict, entry: dict) -> dict:
        """Payload je Site: dedizierte Agenten unveraendert, der Ultimate
        Fetcher zusaetzlich mit `site_config`."""
        payload = dict(payload_base)
        if "site_config" in entry:
            payload["site_config"] = entry["site_config"]
        return payload

    @staticmethod
    def _site_of(entry: dict) -> str | None:
        """`site` nur fuer generic-fetcher-Dispatches; dedizierte Agenten
        tragen ihren Namen bereits im `subagent`-Feld."""
        return entry["site"] if "site_config" in entry else None

    def fetch(self, identifier_raw: str, output_path: str) -> dict:
        """
        Haupt-Routing-Funktion. Gibt das Master-Output-Schema zurueck.

        Args:
            identifier_raw: Rohe Eingabe (ISBN, DOI, URL oder Titel)
            output_path: Zielpfad fuer die heruntergeladene PDF-Datei

        Returns:
            dict mit Keys: status, source, file_path?, reason?, tries, pickup_hint?
        """
        id_type, id_value = self.parse_input(identifier_raw)
        payload_base = {
            "output_path": output_path,
            id_type: id_value,
        }
        tries = []
        best_metadata_url = None  # Beste bekannte URL aus metadata_only-Responses

        # ----------------------------------------------------------
        # Schritt 1: OA-Subagenten
        # ----------------------------------------------------------
        oa_any_metadata_only = False
        for entry in OA_SITES:
            subagent = subagent_for(entry)
            site = self._site_of(entry)
            resp = self.dispatch_subagent(subagent, self._site_payload(payload_base, entry))
            status = resp.get("status", "no_match")
            tries.append(self._try_entry(subagent, status, site))

            if status == "success":
                result = {
                    "status": "success",
                    "source": subagent,
                    "file_path": self._pdf_path(resp),
                    "tries": tries,
                }
                if site is not None:
                    result["site"] = site
                if resp.get("edition"):
                    # Issue #450 AC4: unveraendert durchreichen, nie selbst erzeugen.
                    result["edition"] = resp["edition"]
                return result

            if status == "captcha":
                return {
                    "status": "captcha",
                    "source": subagent,
                    "reason": resp.get("reason", "CAPTCHA erkannt"),
                    "tries": tries,
                }

            if status == "metadata_only":
                oa_any_metadata_only = True
                if resp.get("url") and not best_metadata_url:
                    best_metadata_url = resp["url"]

        # ----------------------------------------------------------
        # Schritt 2: Verlags-Subagenten (nur wenn OA metadata_only und lizenziert)
        # ----------------------------------------------------------
        if oa_any_metadata_only:
            for entry in self._get_licensed_publisher_subagents():
                result = self._try_publisher(entry, payload_base, tries)
                if result is not None:
                    return result

        # ----------------------------------------------------------
        # Schritt 3: Fallback generic-fetcher
        # ----------------------------------------------------------
        generic_payload = dict(payload_base)
        if best_metadata_url:
            generic_payload["url"] = best_metadata_url

        resp = self._try_generic(generic_payload, tries)
        status = resp.get("status", "no_match")

        if status == "success":
            return {
                "status": "success",
                "source": "generic-fetcher",
                "file_path": self._pdf_path(resp),
                "tries": tries,
            }

        if status == "captcha":
            return {
                "status": "captcha",
                "source": "generic-fetcher",
                "reason": resp.get("reason", "CAPTCHA erkannt"),
                "tries": tries,
            }

        pickup_result = {
            "status": "pickup_required",
            "source": "generic-fetcher",
            "reason": resp.get("reason", "Keine downloadbare Quelle gefunden"),
            "tries": tries,
            "pickup_hint": {
                "bib_pickup_url": self.bib_pickup_url,
                "identifier": id_value,
                "identifier_type": id_type,
            },
        }

        # ----------------------------------------------------------
        # Schritt 4: SciHub-Last-Resort (Issue #459)
        # ----------------------------------------------------------
        # Ausschliesslich ueber das Flag gesteuert -- kein weiterer Laufzeit-
        # Dialog. Fehlt der Key oder ist er falsy, wird scihub-fetcher NIE
        # dispatcht (Safety-Default).
        if self.profile.get("scihub_optin", False):
            scihub_result = self._try_scihub(id_type, id_value, output_path, tries)
            if scihub_result is not None:
                return scihub_result

        # pickup_required oder no_match -- immer pickup_required mit Hinweis
        return pickup_result

    @staticmethod
    def _pdf_path(resp: dict):
        """Der Agent-Prompt nennt das Feld `file_path`; Altfixtures nutzen `pdf_path`."""
        return resp.get("file_path") or resp.get("pdf_path")

    def _publisher_success(self, pub_subagent: str, site, resp: dict, tries: list) -> dict:
        result = {
            "status": "success",
            "source": pub_subagent,
            "file_path": self._pdf_path(resp),
            "tries": tries,
        }
        if site is not None:
            result["site"] = site
        if resp.get("edition"):
            result["edition"] = resp["edition"]
        return result

    def _try_generic(self, payload: dict, tries: list) -> dict:
        """Ruft generic-fetcher auf und loest `auth_required` mit genau EINEM Retry auf.

        `auth_required` ist ein reiner Innen-Status (Issue #448): der Master
        reicht ihn an `auth-helper` weiter und wiederholt den Aufruf einmalig mit
        dem `session_context` -- nach aussen bleibt das Enum aus commands/fetch.md.
        """
        resp = self.dispatch_subagent("generic-fetcher", payload)
        status = resp.get("status", "no_match")
        tries.append(self._try_entry("generic-fetcher", status))

        if status != "auth_required":
            return resp

        auth_resp = self.dispatch_subagent(
            "auth-helper",
            {
                "target_url": resp.get("url", ""),
                "profile_path": "~/.academic-research/library-profiles/active.yaml",
            },
        )
        auth_status = auth_resp.get("status", "auth_failed")
        tries.append(self._try_entry("auth-helper", auth_status))

        if auth_status == "captcha":
            return {"status": "captcha", "reason": "CAPTCHA beim Login"}

        if auth_status != "authenticated":
            return {
                "status": "pickup_required",
                "reason": resp.get("reason", "Authentifizierung fehlgeschlagen"),
            }

        retry_payload = dict(payload)
        retry_payload["session_context"] = auth_resp.get("session_context")
        retry_resp = self.dispatch_subagent("generic-fetcher", retry_payload)
        tries.append(self._try_entry("generic-fetcher", retry_resp.get("status", "no_match")))
        return retry_resp

    def _try_scihub(self, id_type: str, id_value: str, output_path: str, tries: list):
        """Last-Resort-Dispatch an scihub-fetcher (Issue #459).

        Wird nur aufgerufen, wenn `scihub_optin: true` gesetzt ist (Aufrufer
        prueft das Flag). Kein zusaetzlicher Bestaetigungs-Call davor -- die
        Aktivierungsentscheidung ist bereits durch das Flag getroffen.

        Gibt das finale Ergebnis zurueck bei success/captcha, sonst None
        (Aufrufer faellt auf das bestehende pickup_required zurueck).
        """
        payload = {"output_path": output_path}
        if id_type == "doi":
            payload["doi"] = id_value
        else:
            payload["title"] = id_value

        resp = self.dispatch_subagent("scihub-fetcher", payload)
        status = resp.get("status", "no_match")
        tries.append(self._try_entry("scihub-fetcher", status))

        if status == "success":
            return {
                "status": "success",
                "source": "scihub-fetcher",
                "file_path": resp.get("file_path"),
                "tries": tries,
            }

        if status == "captcha":
            return {
                "status": "captcha",
                "source": "scihub-fetcher",
                "reason": resp.get("reason", "CAPTCHA erkannt"),
                "tries": tries,
            }

        # no_match / opted_out / error -- kein Sonderfall, Aufrufer faellt
        # auf das bereits vorhandene pickup_required zurueck.
        return None

    def _get_licensed_publisher_subagents(self) -> list:
        """Gibt die Verlags-Eintraege zurueck, deren Host in licensed_sites ist."""
        return [
            entry for domain, entry in PUBLISHER_DOMAIN_MAP.items() if domain in self.licensed_sites
        ]

    def _try_publisher(self, entry: dict, payload_base: dict, tries: list):
        """
        Versucht einen Verlags-Subagenten. Handhabt auth_required mit auth-helper-Retry.

        Gibt das finale Ergebnis zurueck wenn erfolgreich/captcha, sonst None.
        """
        pub_subagent = subagent_for(entry)
        site = self._site_of(entry)
        payload = self._site_payload(payload_base, entry)
        resp = self.dispatch_subagent(pub_subagent, payload)
        status = resp.get("status", "no_match")
        tries.append(self._try_entry(pub_subagent, status, site))

        if status == "success":
            return self._publisher_success(pub_subagent, site, resp, tries)

        if status == "captcha":
            return {
                "status": "captcha",
                "source": pub_subagent,
                "reason": resp.get("reason", "CAPTCHA erkannt"),
                "tries": tries,
            }

        if status == "auth_required":
            # Auth-Helper aufrufen
            target_url = resp.get("url", "")
            auth_resp = self.dispatch_subagent(
                "auth-helper",
                {
                    "target_url": target_url,
                    "profile_path": "~/.academic-research/library-profiles/active.yaml",
                },
            )
            auth_status = auth_resp.get("status", "auth_failed")
            tries.append(self._try_entry("auth-helper", auth_status))

            if auth_status == "captcha":
                return {
                    "status": "captcha",
                    "source": "auth-helper",
                    "reason": "CAPTCHA beim Login",
                    "tries": tries,
                }

            if auth_status == "authenticated":
                # Einmaliger Retry
                retry_resp = self.dispatch_subagent(pub_subagent, payload)
                retry_status = retry_resp.get("status", "no_match")
                tries.append(self._try_entry(pub_subagent, retry_status, site))

                if retry_status == "success":
                    return self._publisher_success(pub_subagent, site, retry_resp, tries)

                if retry_status == "captcha":
                    return {
                        "status": "captcha",
                        "source": pub_subagent,
                        "reason": "CAPTCHA nach Auth-Retry",
                        "tries": tries,
                    }

            return None

        return None
