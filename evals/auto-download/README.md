# Eval-Set: auto-download

**Ticket:** #390 (urspruengliches Material aus der v6.2-Tier-Eval)
**Status:** `metric` — hermetischer Routing-Runner, kein Netz

---

## Lauf

```bash
uv run python evals/auto-download/runner.py     # Report auf stdout
uv run pytest tests/evals/test_auto_download_routing.py -v
```

## Was geprueft wird

Fuer jede der 20 kuratierten Quellen in `sources.yaml` wird genau der in
`expected_tier` genannte Tier auf Treffer gestellt und jeder andere auf
Fehlschlag; `resolve_pdf_url()` aus `scripts/pdf.py` muss dann genau diesen
Tier zurueckmelden. Das faellt auf, sobald

- einer Quelle die Metadaten fehlen, die ihren Tier ueberhaupt erreichbar
  machen (EuropePMC braucht eine DOI, arXiv einen Titel, DOAB ISBN oder Titel),
- oder die Tier-Reihenfolge in `scripts/pdf.py` so umgebaut wird, dass der
  erwartete Tier nicht mehr erreicht wird (z. B. der Buch-Vorrang von DOAB).

Als Negativkontrolle laeuft jede Quelle zusaetzlich mit **keinem** Tier auf
Treffer; das Ergebnis muss `(None, None)` sein. Ohne diese Kontrolle koennte
der Runner den erwarteten Tier auch schlicht zurueckerfinden.

## Was bewusst NICHT geprueft wird

`expected_hit` — ob eine reale API heute ein PDF liefert. Das ist
netzabhaengig, aendert sich ohne Zutun des Repos und wuerde die CI bei fremden
Ausfaellen rot faerben. Ein Live-Abgleich gegen die echten Endpunkte bleibt ein
manueller Operator-Schritt; der historische Report dazu steht in
`docs/evals/v6.2-tier-eval.md`.

## Felder in `sources.yaml`

| Feld | Bedeutung |
|---|---|
| `id` | Eindeutiger Bezeichner (`book-NN`, `biomed-NN`, `general-NN`) |
| `type` | `paper` \| `book` \| `chapter` — steuert den DOAB-Vorrang |
| `doi` / `isbn` / `title` | Metadaten, die die Tier-Erreichbarkeit bestimmen |
| `expected_tier` | Erwarteter Tier oder `null` fuer Kontroll-Quellen |
| `expected_hit` | Nur fuer den manuellen Live-Lauf relevant |
| `domain` / `notes` | Freitext-Kontext |

Neue Tier-Labels muessen zusaetzlich in `TIER_FUNCTIONS` (`runner.py`)
eingetragen werden — `test_expected_tier_vocabulary_is_valid` erzwingt das.
