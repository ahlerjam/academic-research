---
name: ai-disclosure
description: >
  Verwende diesen Skill, wenn der User eine Offenlegungserklärung zur
  KI-Nutzung für Abgabe oder Zeitschrifteneinreichung braucht. Trigger-Phrasen:
  "KI-Nutzung offenlegen", "Offenlegungserklärung erstellen",
  "Erklärung zur KI-Nutzung / Erklaerung zur KI-Nutzung",
  "AI disclosure statement", "AI usage disclosure for submission". Erzeugt
  eine zweiteilige Erklärung (Danksagung + Methodenteil, je DE/EN) nach der
  ICMJE-Aufteilung vom Januar 2026 (Section V). Legt vorhandene Vault-Spuren
  (`extraction_method`, `provenance`, `stance`, Codings) als Vorschlag vor
  statt sie zu unterstellen, markiert unbelegte Angaben als Nutzeraussage.
  Für die eidesstattliche Erklärung → `submission-checker`. Für den
  fertigen Export → `word-export`.
license: MIT
allowed-tools:
  - Read
  - AskUserQuestion
---

# KI-Nutzungs-Offenlegung

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Erzeugt eine Offenlegungserklärung zur KI-Nutzung, zweigeteilt nach der
ICMJE-Aufteilung nach Verwendungsart (Fundstelle:
`${CLAUDE_PLUGIN_ROOT}/skills/ai-disclosure/references/icmje-2026.md`):
Sprachpolitur/Übersetzung/Textaufbereitung gehören in die **Danksagung**,
Datenerhebung/Analyse/Klassifikation/Abbildungserzeugung in den
**Methodenteil**. Reiner Text-Generator — keine Schreiboperation auf
Kapiteldateien, kein neues Aktivitätsprotokoll im Vault (der Vault führt mit
`add_decision` nur ein Log fachlicher Nutzer-Entscheidungen, kein
KI-Aktivitätsprotokoll — siehe `skills/academic-context/SKILL.md`).

## Abgrenzung

Erzeugt die KI-Offenlegungserklärung (Danksagung + Methodenteil, DE/EN).
Für die eidesstattliche Erklärung eigenständiger Arbeit → `submission-checker`
(Abschnitt 6) — dieser Skill dupliziert sie nicht, sondern ergänzt sie um die
KI-spezifische Erklärung. Für den fertigen `.docx`/PDF-Export →
`word-export`. Kein automatisches Einfügen in den Kapiteltext — der Nutzer
kopiert die Ausgabe selbst in Danksagung/Methodik. Keine Bewertung, ob die
offengelegte Nutzung zulässig ist — das entscheiden Fakultät und Zeitschrift.
Keine fakultäts- oder zeitschriftenspezifischen Vorlagen (siehe
`references/icmje-2026.md`, Abschnitt "Warum keine Vorlage").

## Vault-Tools (read-only, Belegquellen)

| Kategorie | Tool | Belegfeld |
|-----------|------|-----------|
| Quellen-Beschaffung | `vault.list_papers_by_provenance(provenance)` | `papers.provenance` (z. B. `scihub`, `zotero`) |
| Zitat-Extraktion | `vault.find_quotes(paper_id)` | `quotes.extraction_method` (`citations-api`/`manual`/`local-verbatim`) |
| Kodierung/Klassifikation | `vault.list_codings(paper_id=None, category=None)` | `codings.category_origin` (`induktiv`/`deduktiv`); ergänzend `quotes.stance`, wo per Fidelity-Auditor gesetzt |
| Bias-Assessment | `vault.list_risk_of_bias(paper_id=None)` | vorhandene RoB-Einträge |
| Methodik-Einordnung (optional) | `vault.list_decisions(category=None, active_only=True)` | fachliche Entscheidungen, die die Erklärung einordnen helfen |

Diese Tools sind read-only und schreiben nichts — sie liefern ausschließlich
den Befund, ob für eine Kategorie eine Spur existiert.

## Workflow

### 1. Fundstelle laden

Lies `${CLAUDE_PLUGIN_ROOT}/skills/ai-disclosure/references/icmje-2026.md`.
Die dort zitierte Fundstelle (ICMJE, Januar 2026, Section V *Use of
Artificial Intelligence in Publishing*) erscheint am Ende jeder erzeugten
Erklärung — der Nutzer prüft sie gegen sein eigenes Merkblatt.

### 2. Kategorien-Scan (Methodenteil)

Für jede der vier Belegkategorien aus der Tabelle oben:

1. Passendes Vault-Tool aufrufen.
2. Kommt ein Treffer zurück: als **Vorschlag** vorlegen ("Der Vault zeigt
   `extraction_method=local-verbatim` für 12 Zitate — soll ich das als
   KI-gestützte Extraktion aufnehmen?"), nie stillschweigend übernehmen.
3. Kein Treffer: die Kategorie strukturiert per `AskUserQuestion` erfragen
   ("Wurde [Kategorie] mit KI-Unterstützung durchgeführt?" — Optionen Ja/Nein/
   Teilweise). Ein Nein-Treffer heißt: Kategorie taucht nicht auf, ein
   Ja-Treffer ohne Vault-Spur wird als **Nutzeraussage, kein Vault-Beleg**
   markiert.

### 3. Bestätigungs-Schritt (AC5)

Jeder Vault-Vorschlag aus Schritt 2 geht als Frage an den Nutzer, nie als
fertige Aussage in den Output:

- Bestätigt der Nutzer → Zeile mit **Vault-Beleg**-Markierung in den Output.
- Widerspricht der Nutzer (z. B. "das war nur ein Testlauf, nicht die
  finale Extraktion") → die **Korrektur** geht in den Output, nie die
  Rohspur aus dem Vault.
- Nennt der Nutzer eine zusätzliche Kategorie ohne jede Vault-Spur → sie
  taucht im Output auf, markiert als **Nutzeraussage, kein Vault-Beleg**.

Der Skill behauptet nie eine Nutzung, die der Nutzer nicht bestätigt hat, und
lässt keine bestätigte Nutzung weg.

### 4. Danksagung erfragen

Sprachpolitur, Übersetzung und Textaufbereitung hinterlassen in diesem Vault
keine Spur (kein Aktivitätsprotokoll, siehe Übersicht) — diese Kategorie
deshalb **immer** per `AskUserQuestion` erfragen, nie aus Vault-Daten
herleiten. Jede bestätigte Angabe ist zwangsläufig als **Nutzeraussage, kein
Vault-Beleg** markiert.

### 5. Output erzeugen

Vier Blöcke, jede Angabe mit Herkunftsmarkierung und, wo vorhanden, dem
konkreten Vault-Feld als Beleg:

```
## Danksagung (Deutsch)

[Formulierung je bestätigter Danksagungs-Angabe]
(Nutzerangabe, kein Vault-Beleg)

## Methodenteil (Deutsch)

[Formulierung je bestätigter Methodenteil-Angabe]
(Vault-Beleg: quotes.extraction_method=local-verbatim, 12 Zitate)
(Nutzerangabe, kein Vault-Beleg)

## Acknowledgement (English)

[gleicher Inhalt wie Danksagung, englische Fassung]

## Methods (English)

[gleicher Inhalt wie Methodenteil, englische Fassung]

---
Grundlage: ICMJE Recommendations, Fassung Januar 2026, Section V
"Use of Artificial Intelligence in Publishing" (Fundstelle:
${CLAUDE_PLUGIN_ROOT}/skills/ai-disclosure/references/icmje-2026.md). Gegen
die eigene Fakultäts- oder Zeitschriftvorgabe prüfen — dieser Text ist der
allgemeine Stand, keine institutsspezifische Vorlage.
```

Jede Zeile im Danksagungs- und Methodenteil-Block trägt genau eine der beiden
Markierungen: `(Vault-Beleg: <Feld>=<Wert>)` oder `(Nutzerangabe, kein
Vault-Beleg)`. Eine Zeile ohne Markierung ist ein Fehler — nie ausgeben.

## Wichtige Regeln

- Nie eine Nutzung behaupten, die weder Vault-Beleg noch Nutzerbestätigung hat.
- Vault-Spuren sind Vorschläge, keine Behauptungen — erst nach Bestätigung
  (oder Korrektur) in den Output.
- Sprachpolitur/Übersetzung/Textaufbereitung → Danksagung, nie Methodenteil.
- Datenerhebung/Analyse/Klassifikation/Abbildungserzeugung → Methodenteil,
  nie Danksagung.
- Kein neues Aktivitätsprotokoll im Vault anlegen — die vier Tools aus der
  Tabelle sind ausschließlich lesend.
- Die Fundstelle (ICMJE Januar 2026, Section V) steht am Ende jeder Ausgabe,
  damit der Nutzer sie gegen seine eigene Vorgabe prüfen kann.

## Few-Shot-Beispiele

**Schlecht** (Grund: Vault-Spur wird stillschweigend als geprüfte Tatsache
ausgegeben, ohne Bestätigung):

> "Methodenteil: KI-gestützte Zitatextraktion wurde verwendet."

**Gut** (Grund: Vault-Vorschlag wird als Frage vorgelegt, nicht behauptet):

> "Der Vault zeigt für 12 Zitate `extraction_method=local-verbatim` —
> soll ich das im Methodenteil als KI-gestützte Extraktion aufnehmen?"

**Schlecht** (Grund: unbelegte Angabe ohne Markierung im Output):

> "Danksagung: Ein Sprachmodell hat die Übersetzung unterstützt."

**Gut** (Grund: gleiche Angabe, aber mit Herkunftsmarkierung):

> "Danksagung: Ein Sprachmodell hat die Übersetzung unterstützt.
> (Nutzerangabe, kein Vault-Beleg)"
