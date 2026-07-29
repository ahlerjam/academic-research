# Per-Uni-Profile

[← zurück zur README](../../README.md)

## Per-Uni-Profile

Profile liegen unter `config/library-profiles/<uni>.yaml` und konfigurieren die
Bibliotheks-Authentifizierung für den `book-fetcher` und die Browser-Suchmodule
(HAN, Shibboleth, EZproxy, lizenzierte Sites).

**Ohne Profil funktioniert das Plugin vollständig** — nur die lizenzpflichtigen
Bibliothekszugänge stehen dann nicht zur Verfügung. Open-Access-Quellen, alle API-Module
und der komplette Schreib-Workflow sind davon unberührt.

**Mitgelieferte Profile:** 5 Uni-Profile

| Profil | Hochschule | Auth-Typ |
|--------|-----------|----------|
| `eth-zurich.yaml` | ETH Zürich | Shibboleth |
| `fu-berlin.yaml` | Freie Universität Berlin | Shibboleth |
| `tum.yaml` | TU München | Shibboleth |
| `uni-hamburg.yaml` | Universität Hamburg | Shibboleth |
| `uni-wien.yaml` | Universität Wien | Shibboleth |

Das Schema für eigene Profile steht in `config/library-profiles/_schema.json`.

## Eigenes Profil anlegen

```bash
# Vorhandenes Profil als Ausgangsbasis kopieren und anpassen
cp config/library-profiles/tum.yaml \
   ~/.academic-research/library-profiles/meine-uni.yaml
# → uni, auth_url, credentials_keys, licensed_sites eintragen

# Als aktives Profil setzen
/academic-research:setup --uni meine-uni
```

Alternativ hilft das Helferskript `hooks/onboard-project-uni-prompt.sh` bei der Auswahl:

```bash
./hooks/onboard-project-uni-prompt.sh --profile tum
```

Das aktive Profil landet in `~/.academic-research/library-profiles/active.yaml`. Dort
steht auch das `scihub_optin`-Flag (Default `false`, siehe README-Hinweis zum
SciHub-Tier).

**Zugangsdaten:** `credentials_keys` nennt zwei weitere Feldnamen in derselben YAML,
deren Werte der `auth-helper`-Subagent zur Laufzeit ausliest. Details, Ist-Zustand des
Codes und Abgrenzung zu den beiden anderen Zugangsdaten-Wegen (Such-API-Keys,
HAN-Zugangsdaten-Datei) stehen gesammelt unter
[Zugangsdaten](../guide/installation.md#zugangsdaten).
