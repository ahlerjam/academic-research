# Reale Treffermenge vom 12.08.2026 (Issue #890, AC3)

AC3 von #890 verlangt woertlich: „Auf der Treffermenge vom 12.08.2026 findet die
neue Fassung dieselben Zusammenfuehrungen wie die alte." Ihre Rohdatei entsteht
dort, wo `commands/search.md` sie schreibt: im Sitzungsverzeichnis des Laufs auf
der Maschine des Operators, `~/.academic-research/sessions/2026-08-12T10-25-52Z/`
— nicht im Repository. Dieses Verzeichnis enthaelt sie hier als eingecheckten
Auszug, damit die Pruefung reproduzierbar ist.

## Herkunft

| Datei im Sitzungsverzeichnis | Treffer | Rolle im Issue |
|---|---|---|
| `all_raw.json` | 1957 | zweite Messung („1957 Titel liefen ueber 5 Minuten ohne Ergebnis") |
| `prefiltered.json` | 1603 | erste Messung („1603 Titel brauchten 1:56 min") |

`prefiltered.json` ist eine echte Teilmenge von `all_raw.json` (geprueft: kein
Titel aus `prefiltered.json` fehlt in `all_raw.json`). Eingecheckt ist deshalb
die groessere Menge, die die kleinere enthaelt.

Dass es sich um genau den Lauf handelt, den Epic #883 und Issue #891 beschreiben,
laesst sich am Inhalt ablesen: der dort namentlich genannte Nicht-Beitrag
„Table 9: Comparison of multi-agent (M-A) and single-agent (S-A) model
performance across markets." (`10.7717/peerj-cs.2690/table-9`) ist der erste
Datensatz der Rohdatei.

## Was eingecheckt ist

- `hitset_2026-08-12.json.gz` — die 1957 realen Treffer, reduziert auf die
  Felder, die `deduplicate()`/`merge_group()` lesen:
  `title`, `doi`, `url`, `year`, `source_module`, `citations`.
  Nicht uebernommen: `abstract` und `authors` (Umfang bzw. Fremd-/Personendaten)
  sowie `venue`, `oa_url`, `open_access_pdf`, `is_retracted`,
  `citations_normalized`, `run`, `query_block` (fliessen nur in Ausgabefelder,
  nicht in die Gruppierung). Die Reduktion trifft beide verglichenen Fassungen
  gleich und kann die Aequivalenzaussage deshalb nicht verzerren.
  `url` bleibt drin, weil `_normalize_pmid()`/`_normalize_openalex_id()` die
  Kennungen aus der Treffer-URL ziehen — ohne sie faellt Stufe 1 teilweise aus.
- `golden_pre_890_output.json.gz` — das Ergebnis, das die Fassung **vor** #890
  (`d141b09:scripts/dedup.py`, der #707-Stand aus PR #758) auf dieser Datei
  liefert: 1957 Treffer → 1390 Gruppen. Das ist die „alte Fassung" aus AC3,
  geladen direkt aus der Git-Historie statt nachgebaut.

  Eine Kanonisierung steckt drin: `source_modules` ist sortiert. `merge_group()`
  baut dieses Feld als `list({...})` aus einem String-Set, und die
  Iterationsreihenfolge eines String-Sets haengt am `PYTHONHASHSEED`, ist also
  zwischen zwei Prozessen verschieden (`PYTHONHASHSEED=7 python3 -c
  'print(list({"dblp","arxiv"}))'` gegen `PYTHONHASHSEED=12 …`). Das ist keine
  Folge von #890 — dieselbe Zeile steht schon in `d141b09` — und betrifft keine
  Gruppenzugehoerigkeit, sondern nur die Reihenfolge innerhalb dieses einen
  Ausgabefeldes (auf dieser Menge: 47 der 1390 Gruppen). Ohne die Sortierung
  waere der eingefrorene Vergleich zufaellig rot.

## Messergebnis (Stand des PR zu #890)

| Eingabe | vor #890 (`d141b09`) | mit Blocking (#890) | Ergebnis |
|---|---|---|---|
| Fixture, feldreduziert (1957) | 1390 Gruppen, 143,8 s | 1390 Gruppen, 5,6 s | identisch |
| `all_raw.json`, unreduziert (1957) | 1390 Gruppen, 145,2 s | 1390 Gruppen, 5,8 s | identisch |
| `prefiltered.json`, unreduziert (1603) | 1100 Gruppen, 101,2 s | 1100 Gruppen, 4,4 s | identisch |

Zeile 2 ist die Gegenprobe zur Feldreduktion: auf den vollstaendigen
Rohdatensaetzen (mit Abstracts, Autoren, Venue …) faellt dieselbe Gruppierung
wie auf der reduzierten Fixture. Zeile 3 deckt die erste Messung des Issues ab —
und stimmt mit dem Lauf selbst ueberein: die `deduped.json` desselben
Sitzungsverzeichnisses enthaelt genau 1100 Datensaetze. Verglichen wird jeweils
im selben Prozess und ohne jede Kanonisierung (`compare --live`).

Die Laufzeit ist die reale Entsprechung zu AC1: dieselbe Menge, die am
12.08.2026 „ueber 5 Minuten ohne Ergebnis" lief, ist hier in Sekunden
dedupliziert.

## Erzeugen und pruefen

```sh
# Fixture aus der Rohdatei des Laufs ziehen (nur mit Zugriff auf das
# Sitzungsverzeichnis; die Rohdatei selbst ist nicht Teil des Repos):
uv run python scripts/dev/verify_dedup_890_hitset.py extract \
    --source ~/.academic-research/sessions/2026-08-12T10-25-52Z/all_raw.json

# Golden neu rechnen (laedt d141b09 per `git show`, dauert Minuten):
uv run python scripts/dev/verify_dedup_890_hitset.py golden

# Aktuelle Fassung gegen die eingefrorene alte vergleichen (Sekunden):
uv run python scripts/dev/verify_dedup_890_hitset.py compare

# … oder gegen einen frischen Lauf der alten Fassung (Minuten):
uv run python scripts/dev/verify_dedup_890_hitset.py compare --live

# … oder gegen die unreduzierten Rohdatensaetze desselben Laufs:
uv run python scripts/dev/verify_dedup_890_hitset.py compare --live \
    --papers ~/.academic-research/sessions/2026-08-12T10-25-52Z/all_raw.json
```

Der Dauertest in der Suite ist
`tests/test_dedup.py::test_dedup_real_hitset_2026_08_12_matches_pre_890_output`.
Er vergleicht gegen die eingefrorene Golden-Datei und laeuft in Sekunden.
`test_dedup_real_hitset_golden_reproduces_from_pre_890_implementation`
rechnet die Golden-Datei aus der Historie neu und laeuft nur mit
`DEDUP_890_LIVE_REFERENCE=1` (Minuten, braucht Git-Historie bis `d141b09`).
