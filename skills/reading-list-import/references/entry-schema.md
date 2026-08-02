# Eintrags-Schema für `parse_list.py --entries`

Seit #632 parst dieser Skill die Literaturliste selbst in der laufenden
Sitzung — das Skript hat keinen eigenen Modellzugang mehr. Stufe 1
(`--extract`) liefert den Rohtext, Stufe 2 (`--entries`) nimmt das hier
beschriebene JSON entgegen.

## Format

`entries.json` ist ein JSON-Array. Jedes Element ist ein Objekt:

| Feld | Typ | Bedeutung |
|---|---|---|
| `author` | string | Autoren, getrennt durch `"; "` |
| `title` | string | Titel der Quelle |
| `year` | string | vierstellig |
| `doi` | string \| null | DOI ohne `https://doi.org/`-Präfix |
| `isbn` | string \| null | nur Ziffern, ohne Bindestriche |
| `_ambiguous` | boolean | `true`, wenn mehrere Quellen in Frage kommen |
| `_candidates` | array | `{title, doi}` je Kandidat, nur bei `_ambiguous` |

Nur das Array ausgeben, kein Prosatext davor oder danach. Ein umschließender
` ```json `-Codeblock wird von `load_entries()` toleriert.

## Beispiel

```json
[
  {
    "author": "Vaswani, A.; Shazeer, N.",
    "title": "Attention Is All You Need",
    "year": "2017",
    "doi": "10.48550/arxiv.1706.03762",
    "isbn": null
  },
  {
    "author": "Radford, A.",
    "title": "Language Models",
    "year": "2019",
    "doi": null,
    "isbn": null,
    "_ambiguous": true,
    "_candidates": [
      {"title": "Language Models are Few-Shot Learners", "doi": "10.48550/arxiv.2005.14165"},
      {"title": "Language Models are Unsupervised Multitask Learners", "doi": null}
    ]
  }
]
```

## Nichts erfinden

Felder, die im Rohtext nicht stehen, bleiben `null`. Ein geratener DOI ist
schlimmer als keiner: die Resolution löst ihn stillschweigend auf die falsche
Quelle auf, und der Vault trägt danach eine Fehlzuordnung, die niemand mehr
als solche erkennt. Fehlt die Eindeutigkeit, ist `_ambiguous: true` mit
`_candidates` der richtige Weg — dann fragt der Import beim User nach.
