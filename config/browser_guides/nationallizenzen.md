# Nationallizenzen DFG — Browser-Guide (Buch-Download)

**URL:** https://www.nationallizenzen.de
**Auth:** DFN-AAI / Shibboleth mit Hochschulkonto (mehrstufig)
**Anti-Scraping:** niedrig auf Nationallizenzen-Portal; mittel beim Ziel-Verlag.

## Login-Flow

Nationallizenzen selbst sind kein Download-Portal — sie ermöglichen Zugang zu
Verlags-Plattformen via Shibboleth.

1. Ziel-Verlagsseite öffnen (z. B. Springer, Wiley — aus Discovery-Ergebnis).
2. Auf der Verlagsseite: "Sign in via institution" oder "Institutional login" klicken.
3. DFN-AAI-Seite öffnet: Hochschule im Suchfeld eingeben oder aus Liste wählen.
4. Hochschul-IdP-Login-Seite: Credentials eingeben (Credentials aus Uni-Profil).
5. Auf Weiterleitung zurück zum Verlag warten.
6. Zugang geprüft → Volltext-Lokation.

## Discovery-Pfad

1. `browser-use open https://www.nationallizenzen.de`
2. Suche im Nationallizenzen-Katalog: Titel, ISBN, DOI oder Verlag.
3. `browser-use state` → Treffer prüfen; Verlags-Link in Trefferdetails notieren.
4. Auf Verlags-Link klicken → Verlagsseite öffnet (Springer, Wiley, etc.).
5. Auf der Verlagsseite weiter im verlagsspezifischen Guide verfahren
   (`springer.md`, etc.).

Alternativ: DOI-Direktlink verwenden — falls Nationallizenz gilt, wird Zugang
nach Shibboleth-Auth gewährt.

## Volltext-Lokation

- Volltext liegt beim jeweiligen Verlag, nicht bei Nationallizenzen.
- Nach erfolgreicher Shibboleth-Auth: Download-Button auf Verlagsseite erscheint.
- Verlagsspezifische Guides für die Volltext-Lokation verwenden:
  - Springer → `springer.md` (Buch-Download-Block)
  - De Gruyter → `degruyter.md`
  - Wiley → verlagseigene URL-Muster

## Lizenz-Prüfung (ZUERST, vor jeder Navigation)

`~/.academic-research/library-profiles/active.yaml` lesen und prüfen, ob
`nationallizenzen.de` in `licensed_sites` steht.

Steht es **nicht** drin: sofort stoppen mit
`{"status": "metadata_only", "url": "https://www.nationallizenzen.de"}`.
Der Master entscheidet über den Fallback — hier wird nichts anonym versucht.

## Auth-Delegation

Auf der Ziel-Verlagsseite gilt als **Auth-Trigger**: "Sign in via institution" /
"Institutional login" sichtbar, Auth-Wall bzw. "Access options" statt
Download-Button, kein PDF-Download trotz Nationallizenzen-Referenz, oder eine
Login-Wall nach der Weiterleitung vom Portal.

Der Auth-Flow wird **vollständig an `auth-helper` delegiert** (`target_url` =
aktuelle Verlagsseiten-URL, `profile_path` = aktives Uni-Profil) — hier werden
nie selbst Credentials verarbeitet. Auth-Methode ist ausschließlich
DFN-AAI/Shibboleth; die konkrete Variante steht als `auth_type` im Profil.

Antworten des `auth-helper`:

- `authenticated` → weiter zum Download.
- `not_required` (`auth_type: oa-only`) → weiter zum Download (OA-Zugang ohne Login).
- `auth_failed` → `pickup_required` mit `reason: "auth_failed: <grund>"`.
- `captcha` → `captcha`.

## Status-Vokabular

| Beobachtung | Status | Feld |
|---|---|---|
| Download nach Auth geglückt und verifiziert | `success` | `file_path`, `url` = Verlagsseite |
| `nationallizenzen.de` fehlt in `licensed_sites` | `metadata_only` | `url` |
| Hochschule nicht in dieser Nationallizenz enthalten | `metadata_only` | fehlende Lizenz im `reason` nennen |
| Titel nicht im Nationallizenzen-Katalog / Neuerscheinung außerhalb des Zeitraums | `no_match` | `reason` |
| Shibboleth-Flow scheitert, Verlag verweigert trotz Auth, kein Download-Button nach Auth | `pickup_required` | `url`, `reason` |
| Verlag zeigt CAPTCHA | `captcha` | `reason` |

## Bekannte Fallstricke

- Nationallizenzen gelten nur für bestimmte Erscheinungsjahre — häufig bis 2007–2015
  je nach Verlagsvertrag. Neuerscheinungen sind nicht enthalten.
- Auth-Redirect ist mehrstufig: Verlag → Nationallizenzen-Redirect → DFN-AAI →
  Hochschul-IdP → zurück — vollständigen Flow abwarten (kann 10–15 Sekunden dauern).
- Nicht jede Hochschule hat alle Nationallizenzen aktiviert — Uni-Profil prüfen.
- Einige Verlage erfordern zusätzlich Cookie-Akzeptanz vor dem Auth-Flow.
