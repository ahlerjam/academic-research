# 0001 — Modellzugang beim Ingest ohne eigenen Schlüssel

[← Doku-Übersicht](../README.md) · [Entscheidungsvermerke](README.md)

Entwurf zu Issue #735. Beantwortet die eine offene Frage des zugehörigen Epics: Auf
welchem Weg bekommt der Vault-Ingest ein Modell, das inhaltliche Kontextsätze
schreibt, ohne dass der Nutzer einen eigenen API-Schlüssel stellt? Ergebnis ist ein
Entscheidungsdokument, kein Feature — Umsetzung folgt als eigenes Issue.

## Ausgangslage im Code

Der Ingest läuft heute synchron und deterministisch innerhalb von `vault.add_paper()`:

```
server.py:1591  add_paper()
  → server.py:1205  _maybe_ingest_embeddings()
    → ingest.py:80   ingest_paper_embeddings()
      → chunking.py:365  chunk_pages(context_provider=...)
```

Entscheidend: Das läuft im **Python-MCP-Serverprozess**, nicht in einem
Claude-Code-Agent-Turn. Der Serverprozess hat keinen Modellzugang — weder OAuth-Sitzung
noch API-Schlüssel.[^1] `_maybe_ingest_embeddings()` fängt zudem jede Ausnahme außer
`EmbeddingDimensionMismatchError` ab und loggt nur (server.py:1223): ein kaputter oder
fehlender Kontextsatz-Weg darf `add_paper()` nicht scheitern lassen.

Der Einhängepunkt existiert bereits: `chunk_pages()` nimmt einen injizierbaren
`context_provider: ContextProvider | None` (chunking.py:260, 527). Ohne ihn greift
`default_context_sentence()` (chunking.py:368) — deterministisch, offline, seit #632
der einzige Weg. Seit #701 trägt er bereits Titel, Erstautor(en) und Jahr aus den
Ingest-Metadaten, nicht nur Sektion/Seite/Chunk-Index.

Die Randbedingung aus #632: Kein Plugin-Pfad darf einen eigenen Anthropic-API-Schlüssel
voraussetzen. `files_api.py` und `batch_api.py` wurden deswegen entfernt,
`embeddings.py`s `generate_context_sentence()`/`_get_anthropic_client()` ebenso — nur
die eigene OAuth-Sitzung von Claude Code zählt als zulässiger Modellzugang, kein
zweites Abrechnungsverhältnis.

## Die drei Wege

### Weg A — Ingest-Agent in der Claude-Code-Session

Ein Agent in der laufenden Sitzung erzeugt den Kontextsatz und schreibt ihn über MCP
zurück.

- **Kosten/Paper:** Sitzungskontingent (Turns/Tokens), kein separates Budget — analog
  zur #632-Entscheidung, das Batch-Relevanz-Scoring durch `agents/relevance-scorer.md` in
  der Sitzung zu ersetzen.
- **Verhalten ohne Modell:** Läuft `add_paper()` ohne aktiven Agent-Turn — z. B. aus
  einem Skript, einem Backfill oder einer Cron-Aufgabe, die den Vault direkt
  anspricht — gibt es keinen Aufrufer für den `context_provider`. Braucht zwingend den
  `default_context_sentence()`-Fallback.
- **#632-Konformität:** Ja. Nutzt ausschließlich die ohnehin vorhandene OAuth-Sitzung,
  keinen zusätzlichen Schlüssel.
- **Ablauf-Auswirkung:** Am größten von allen dreien in reiner Form. Der Agent kann
  nicht direkt als `context_provider` in `chunk_pages()` eingehängt werden — der
  Serverprozess, der diesen Aufruf synchron ausführt, hat keinen Zugriff auf die
  Sitzung. Reine Umsetzung von Weg A verlangt daher zwingend dieselbe Entkopplung wie
  Weg C (siehe dort); als eigenständiger, unentkoppelter Weg ist er nicht umsetzbar,
  ohne `add_paper()` selbst in den Agent-Turn zu verlagern — was der bestehenden
  Best-effort-Philosophie von `_maybe_ingest_embeddings()` widerspricht (Schreiben soll
  gerade *nicht* von einem Modell abhängen).

### Weg B — Lokales Kleinmodell im Vault-Prozess

Ein Modell, das im Serverprozess selbst läuft, ohne Sitzung und ohne Schlüssel.

- **Präzedenz im Stack:** Zwei lokale Modelle laufen bereits genauso —
  `E5SmallEmbedder` (`embedding_model.py`, `intfloat/multilingual-e5-small`,
  ≈ 470 MB Download) und der NLI-Vorfilter (`nli_prefilter.py`,
  `bge-m3-zeroshot-v2.0`, ≈ 1,1 GB), beide über `sentence-transformers`, beide mit
  Lazy-Load und Download-Ankündigung vor dem ersten impliziten Download
  (`_model_prefetchable.py`, #718).
- **Der entscheidende Unterschied:** Beide Präzedenzfälle sind **Encoder bzw.
  Klassifikatoren** — sie liefern einen Vektor oder ein Label, keinen freien Text. Ein
  inhaltlicher Kontextsatz ist generierter Text. Das verlangt ein **generatives**
  Modell (kleines Instruct-LLM), eine Modellklasse, die im heutigen Stack nicht
  existiert — alle drei bisherigen lokalen Modelle (Embedder, Reranker
  `bge-reranker-v2-m3`, ≈ 2,27 GB, NLI-Scorer) sind `sentence-transformers`-Backends
  ohne Generierung. Eine generative Inferenz-Engine (z. B. `llama.cpp`/GGUF) wäre eine
  neue Abhängigkeitsklasse, kein Anschluss an bestehende Infrastruktur.
- **Kosten/Paper:** Einmaliger Download im GB-Bereich (mutmaßlich größer als die
  bisherigen Modelle, da Textqualität mehr Parameter braucht als Klassifikation),
  laufende Inferenzzeit und RAM pro Chunk, aber keine laufenden Geldkosten und kein
  Schlüssel.
- **Verhalten ohne Modell:** Analog zu `get_embedder_error()` — Download- oder
  Ladefehler wird geloggt, Fallback auf `default_context_sentence()` bleibt im
  bestehenden `_maybe_ingest_embeddings()`-Fehlerpfad möglich, ohne `add_paper()` zu
  gefährden.
- **#632-Konformität:** Ja. Kein API-Call, kein Schlüssel.
- **Ablauf-Auswirkung:** Keine strukturelle — passt unverändert in den bestehenden
  synchronen `context_provider`-Einhängepunkt. Der Preis dafür ist eine neue,
  ungetestete Modellklasse im Stack mit unklarer erreichbarer Textqualität bei einer
  Größe, die noch als "lokal vertretbar" gilt.

### Weg C — Zweistufiger Ingest mit nachgelagerter Anreicherung

`add_paper()` schreibt wie heute sofort mit `default_context_sentence()`. Ein
Nachlauf holt Chunks mit Platzhalter-Kontextsatz, lässt sie anreichern und schreibt
Kontextsatz + neu berechnetes `embedding_text` + Vektor zurück.

- **Kosten/Paper:** Hängt von der Quelle ab, die den Nachlauf speist (Agent-Sitzung
  oder lokales Kleinmodell) — Weg C selbst ist eine Ablaufentkopplung, keine eigene
  Modellquelle. Zusätzlich: Re-Embedding-Kosten, da sich `embedding_text` mit dem
  Kontextsatz ändert und der Vektor neu berechnet werden muss (Präzedenz für
  Bulk-Vektor-Updates existiert strukturell bereits in `replace_chunk_vectors()`,
  db.py:2693, wenn auch für Modellwechsel statt Kontextsatz-Nachtrag).
- **Verhalten ohne Modell:** Unproblematisch per Konstruktion. Der Ingest hängt nie
  von der Anreicherung ab, der Vault bleibt jederzeit mit dem deterministischen Satz
  durchsuchbar. Anreicherung ist strikt optional und beliebig nachholbar — genau der
  in AC4 verlangte Rückfall, hier nicht als Fehlerpfad, sondern als Normalzustand
  zwischen Ingest und Anreicherung.
- **#632-Konformität:** Ja, unabhängig von der gewählten Quelle — solange diese Quelle
  selbst #632-konform ist (siehe Weg A/B).
- **Ablauf-Auswirkung:** Größte strukturelle Änderung. Neuer Zustand pro Chunk
  ("angereichert oder nicht"), mindestens ein neues Tool zum Abholen ausstehender
  Chunks, eines zum Zurückschreiben, ein Trigger-Mechanismus für den Nachlauf.

## Kosten-/Verhaltens-Matrix

| Weg | Kosten/Paper | Verhalten ohne Modell | #632-konform | Ablauf-Impact |
|---|---|---|---|---|
| A — Ingest-Agent (unentkoppelt) | Sitzungskontingent | Bricht ohne aktiven Agent-Turn (kein Fallback ohne Entkopplung) | Ja | Hoch — als eigenständiger Weg praktisch nicht umsetzbar, ohne `add_paper()`-Synchronität zu brechen |
| B — Lokales Kleinmodell | Einmal-Download (GB) + Inferenzzeit/RAM, $0 laufend | Fallback auf `default_context_sentence()` im bestehenden Fehlerpfad | Ja | Keine — passt in bestehenden Einhängepunkt, aber neue Modellklasse (generativ statt Encoder/Klassifikator) |
| C — Zweistufig (Quelle: Agent-Sitzung) | Sitzungskontingent, nur bei aktivem Anreicherungslauf; + Re-Embedding | Ingest unberührt; Anreicherung strikt optional, `default_context_sentence()` ist der Normalzustand bis zur Anreicherung | Ja | Mittel–Hoch — neue Tools, neuer Zustand pro Chunk, kein Bruch der Ingest-Synchronität |

## Empfehlung

**Weg C, gespeist von Weg A** (Agent in der Sitzung als Modellquelle des
Nachlaufs) — nicht Weg B, nicht Weg A in unentkoppelter Form.

Begründung: `add_paper()` bleibt exakt so synchron und modellunabhängig, wie es heute
ist und wie es die bestehende Best-effort-Philosophie von
`_maybe_ingest_embeddings()` verlangt (jeder Fehler wird geloggt, nie geworfen —
das Schreiben eines Papers darf nie an einem Modell hängen). Die eigentliche
Texterzeugung passiert dort, wo bereits Modellzugang vorhanden ist: in der aktiven
Claude-Code-Sitzung, über die ohnehin vorhandene OAuth-Verbindung, ohne neuen
Schlüssel und ohne neue Abhängigkeitsklasse. Der Rückfall auf
`default_context_sentence()` ist in diesem Weg kein zusätzlicher Fehlerpfad, den man
extra bauen müsste, sondern der bestehende Normalzustand jedes Chunks zwischen
Ingest und (optionaler) Anreicherung — AC4 ist damit strukturell erfüllt, nicht nur
als Ausnahmebehandlung.

**Verworfen: Weg B (lokales generatives Kleinmodell).** Ausschlussgrund: Die
bestehende lokale-Modell-Präzedenz im Stack (Embedder, Reranker, NLI-Scorer) ist
durchgehend nicht-generativ. Ein Kontextsatz-Generator wäre die erste generative
Modellklasse im Projekt — neue Inferenz-Engine, unklare erreichbare Qualität bei
vertretbarer Größe, höchstes Umsetzungsrisiko der drei Wege, ohne dass ein
bestehendes Muster die Kosten absichert.

**Verworfen: Weg A in unentkoppelter Form** (Agent direkt als `context_provider` im
synchronen `add_paper()`-Aufruf). Ausschlussgrund: nicht umsetzbar, ohne entweder
`add_paper()` selbst in einen Agent-Turn zu verlagern (bricht die
Serverprozess-Architektur und macht jeden programmatischen `add_paper()`-Aufruf ohne
Sitzung fehlerhaft) oder auf die Entkopplung von Weg C auszuweichen — womit er de
facto zu Weg C wird.

## Was ein Umsetzungs-Issue leisten müsste

**Datei-Kandidaten:**
- `academic_vault/db.py` — Abfrage für Chunks mit ausstehender Anreicherung
  (Erkennungsmerkmal für "Platzhalter-Kontextsatz" ist selbst eine Spezifikationsfrage
  fürs Umsetzungs-Issue: eigene Spalte vs. Vergleich gegen
  `default_context_sentence()`-Ausgabe) sowie eine Update-Methode analog zu
  `replace_chunk_vectors()` (db.py:2693), die Kontextsatz, `embedding_text` und Vektor
  zusammen aktualisiert.
- `academic_vault/server.py` — zwei neue MCP-Tools: eines zum Abholen ausstehender
  Chunks (Batch-Limit), eines zum Zurückschreiben eines angereicherten Kontextsatzes
  pro Chunk.
- Ein neuer oder erweiterter Agent/Skill, der die Pending-Liste in einer Sitzung
  abarbeitet und die beiden neuen Tools aufruft.
- `academic_vault/ingest.py` — Markierung "ausstehend" beim initialen Ingest, falls
  eine eigene Spalte statt eines Vergleichswerts gewählt wird.
- Tests für: Pending-Query, Update-Pfad (inkl. Re-Embedding), Idempotenz eines
  zweiten Anreicherungslaufs, Nicht-Beeinträchtigung von `add_paper()` bei
  fehlendem/fehlgeschlagenem Anreicherungslauf.

**AC-Kandidaten:**
- Ein neues MCP-Tool liefert Chunks mit ausstehender Anreicherung, batchweise.
- Ein neues MCP-Tool schreibt einen angereicherten Kontextsatz zurück und
  aktualisiert `embedding_text` sowie den Vektor konsistent (kein veralteter Vektor zu
  neuem Kontextsatz).
- `add_paper()` bleibt bei fehlendem oder fehlgeschlagenem Anreicherungslauf
  unverändert lauffähig — bestehendes Verhalten, durch Test abgesichert.
- Ein zweiter Anreicherungslauf über bereits angereicherte Chunks ist idempotent
  (kein Doppel-Update, kein Fehler).

**Out-of-Scope-Grenzen fürs Umsetzungs-Issue:**
- Kein neues lokales generatives Modell (Weg B ist verworfen).
- Keine Änderung an `default_context_sentence()` selbst.
- Keine Pflicht zur Anreicherung — bleibt best-effort und nachholbar, nie
  Voraussetzung für einen erfolgreichen `add_paper()`-Aufruf.
- Keine Messung des Retrieval-Gewinns durch inhaltliche Kontextsätze — das ist ein
  eigenes Folge-Issue nach der Umsetzung, nicht Teil dieses Schritts.
- Kein Trigger-Design (Cron vs. nutzerinitiiert vs. nach N neuen Papers) wird hier
  vorentschieden — das ist Teil der Spezifikation des Umsetzungs-Issues selbst.

---

[^1]: **Nachtrag (#710-Plan-Kommentar, Abschnitt 0):** Die Prämisse „weder
    OAuth-Sitzung noch API-Schlüssel" stimmt seit #734 nicht mehr —
    `query_expansion.expand_query()` ruft im selben Serverprozess bereits
    `claude -p` als Subprozess über die eingeloggte OAuth-Sitzung auf (siehe
    `docs/reference/vault.md`, Abschnitt „Query-Umformung"). Es gäbe damit
    einen Weg D (`claude -p` direkt als synchroner `context_provider` in
    `chunk_pages()`). Er bleibt verworfen — aber aus messbaren Gründen, nicht
    aus der überholten Prämisse: rund 6,8 s je `claude -p`-Aufruf (#733-Messung)
    bei bis zu 64 Chunks/Paper hinge der synchrone `add_paper()`-Ingest an
    einem Subprozess mit 240-s-Timeout, und der Aufruf liefe neben dem
    ohnehin aktiven Session-Agenten als zweite, konkurrierende
    Modellnutzung. Die Empfehlung dieses Vermerks (Weg C, zweistufiger
    Ingest, umgesetzt in #783/#784) bleibt davon unberührt richtig — Weg D
    würde die synchrone `add_paper()`-Architektur genau in der Weise
    verletzen, die Weg C bewusst vermeidet.
