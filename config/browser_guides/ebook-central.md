# Ebook Central (ProQuest) — Browser-Guide (Buch-Download)

**URL:** https://ebookcentral.proquest.com
**Auth:** Shibboleth / HAN / IP-basiert (Institutionszugang)
**Anti-Scraping:** niedrig (lizenzierter Zugriff), aber Session-Timeout nach Inaktivität.

## Login-Flow

1. `browser-use open https://ebookcentral.proquest.com`
2. "Sign in" oben rechts klicken.
3. `browser-use state` → "Sign in through your institution" suchen, klicken.
4. Hochschule im Suchfeld eingeben oder aus Liste wählen.
5. Shibboleth-Login: Hochschul-Credentials eingeben (aus Uni-Profil).
6. Auf Weiterleitung zurück zu Ebook Central warten.

Alternativ via HAN-Proxy: `han_login.md` zuerst ausführen, dann
`https://han.<uni-domain>/ebookcentral` aufrufen.

## Discovery-Pfad

1. Suchfeld im Header: Titel, Autor, ISBN eingeben.
2. `browser-use state` → Suchergebnisse prüfen.
3. Filter im linken Panel: "Subject", "Publication Date", "Language".
4. Trefferdetailseite öffnen → Lizenz- und Download-Optionen prüfen.
5. Alternativ über OPAC-Link: OPAC-Eintrag enthält oft Direktlink zu Ebook Central.

## Volltext-Lokation

- Auf Detailseite: "Full Book Download" suchen (wenn Lizenz vorhanden).
- `browser-use state` → Button-Index identifizieren, klicken.
- Falls "Full Book Download" fehlt: "Download Chapter" für kapitelweisen Download.
- Online-Reader ("Read Online") ist kein Download-Äquivalent — nicht verwenden.
- DRM-Hinweis prüfen: "Adobe DRM" bedeutet verschlüsseltes PDF.

## Lizenz-Prüfung (ZUERST, vor jeder Navigation)

`~/.academic-research/library-profiles/active.yaml` lesen und prüfen, ob
`ebookcentral.proquest.com` in `licensed_sites` steht.

Steht es **nicht** drin: sofort stoppen mit
`{"status": "metadata_only", "url": "https://ebookcentral.proquest.com"}`.

**Sonderfall HAN:** Manche Institutionen haben Ebook Central nur über HAN
eingerichtet. Ist `proxy_pattern` gesetzt und `auth_type: HAN`, läuft der
Zugang über den HAN-Flow (via `auth-helper`), nicht über den Direktaufruf.

## Auth-Delegation

Ebook Central verlangt **immer** einen Login. Auth-Trigger: "Sign in"-Button
ohne eingeloggten Zustand, "Sign in through your institution", Login-Wall nach
einem Navigationsversuch ohne Session, oder eine HAN-Proxy-URL aus
`proxy_pattern`.

Der Login wird **vollständig an `auth-helper` delegiert** (`target_url:
https://ebookcentral.proquest.com`, `profile_path` = aktives Uni-Profil) —
hier werden nie selbst Credentials verarbeitet. Auth-Methode ist Shibboleth
ODER HAN, abhängig von `auth_type` im Profil.

Antworten des `auth-helper`:

- `authenticated` → weiter zur Discovery.
- `not_required` (`auth_type: oa-only`) → weiter zur Discovery (unerwarteter
  OA-Zustand; wie `authenticated` behandeln).
- `auth_failed` → `pickup_required` mit `reason: "auth_failed: <grund>"`.
- `captcha` → `captcha`.

## Download-Prüfung vor dem Klick

- **DRM:** "Adobe DRM" / "Adobe Digital Editions" sichtbar → das PDF ist
  verschlüsselt und nicht archivierbar → `pickup_required` mit
  `reason: "DRM-PDF (Adobe Digital Editions) — nicht archivierbar"`.
  Nicht herunterladen.
- **Download-Limit:** "You have reached the maximum number of checkouts" →
  `pickup_required` mit `reason: "Download-Limit erreicht"`.
- Sonst "Full Book Download" klicken und die Datei verifizieren.
- Fehlt "Full Book Download", ist aber "Download Chapter" vorhanden:
  kapitelweiser Fallback, Ergebnis `success` mit `"chapter_only": true`.

## Status-Vokabular

| Beobachtung | Status | Feld |
|---|---|---|
| "Full Book Download" geglückt und verifiziert | `success` | `file_path`, `url` = Detailseite |
| Kapitelweiser Fallback | `success` | zusätzlich `"chapter_only": true` |
| `ebookcentral.proquest.com` fehlt in `licensed_sites` | `metadata_only` | `url` |
| DRM-PDF, Download-Limit, Session-Timeout, kein Download-Button nach Auth, nur Online-Reader | `pickup_required` | `url`, `reason` |
| CAPTCHA sichtbar | `captcha` | `reason` |
| ISBN nicht im Katalog | `no_match` | `reason` |

## Verbote (site-spezifisch)

- **"Read Online" ist kein Download** — der Online-Reader wird nie als
  PDF-Ersatz verwendet, weder per Screenshot noch seitenweise.
- Keine eigene Credential-Verarbeitung — Auth geht ausschließlich über
  `auth-helper`.

## Bekannte Fallstricke

- DRM-PDFs (Adobe Digital Editions) sind technisch downloadbar, aber nicht
  ohne Adobe-Software lesbar und nicht langfristig archivierbar — als
  `pickup_required` behandeln.
- Download-Limit pro User/Tag variiert je Lizenzvertrag (meist 20–50 Seiten
  oder 1 Kapitel/Tag bei Pay-per-Use).
- Session-Timeout nach ~15 Minuten Inaktivität → neu anmelden.
- "Full Book Download" nur bei Institutional-Ownership-Lizenzen — bei
  Short-Term-Loan-Lizenzen nur kapitelweise.
- Einige Institutionen haben Ebook Central nur über HAN eingerichtet, nicht
  direkt — HAN-Flow dann pflichtmäßig.
