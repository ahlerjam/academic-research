# Grenzen — was das Plugin nicht kann, nicht darf und nicht prüft

[← Doku-Übersicht](../README.md)

Ein Werkzeug für wissenschaftliches Arbeiten, das seine Grenzen verschweigt, ist gefährlich
— nicht unangenehm. Diese Seite trennt drei Arten von Grenzen: was technisch **nicht geht**,
was aus rechtlichen oder wissenschaftlichen Redlichkeitsgründen **nicht erlaubt** ist, und
wo ein Ergebnis **ungeprüft nicht verwendbar** ist. Jede Zeile trägt einen Beleg — Code,
Issue oder Doku, nicht nur eine Behauptung. Lies diese Seite vor der Installation, nicht
danach: [Erste Schritte](getting-started.md) verlinkt hierher genau deshalb schon vor
Schritt 1.

## Was das Plugin nicht kann

- **Tabellen nicht bei jedem PDF sicher strukturerhaltend extrahieren.** Das Backend
  `pdfplumber` ist seit Issue #723 Pflicht-Dependency (`pyproject.toml`), läuft also nach
  jedem Setup ohne Zusatzschritt mit. Seit Issue #847 trägt jede erkannte Tabelle ein
  eigenes `confidence`/`detection`-Signal (`high`/`lines` für den Linien-Pfad,
  `low`/`text-strategy` für den Fallback über Textausrichtung bei gitterlinienlosen
  Tabellen) statt eines einzigen PDF-weiten Status — `vault.extract_tables` meldet
  zusätzlich `low_confidence_tables`, damit unsichere Treffer erkennbar sind, ohne jede
  Tabelle einzeln zu prüfen. Die verbleibende Grenze ist strukturell, nicht
  paketierungsbedingt: eine über zwei Spalten laufende Kopfzelle liefert weiterhin keinen
  erratenen Wert für die geschluckte Position (dafür jetzt ein explizites
  `merged_into`-Signal statt eines stummen Gaps), und der Text-Strategie-Fallback ist eine
  Schwellenwert-Heuristik ohne Anspruch auf allgemeine Gültigkeit — `docs/reference/vault.md`,
  Abschnitt „Tabellenextraktion". Fehlt das Paket in einer realen Installation dennoch,
  liefert `vault.extract_tables` den Status `backend-missing` statt Zahlen —
  `academic_vault/tables.py`. Die `meta-analysis`-Pipeline übernimmt Effektstärken (`yi`,
  `vi`) ohnehin nur aus einem vom Nutzer bestätigten Eingabe-JSON, nie automatisch aus einer
  erkannten Tabelle — `scripts/meta_analysis.py`.
- **Kein unbegrenztes Kontextfenster beim Embedding.** Das Chunking-Fenster ist mit 512
  Tokens fest verdrahtet (`academic_vault/chunking.py`, `MODEL_MAX_TOKENS`) — bewusst
  unabhängig davon, wie groß das Kontextfenster des konfigurierten Modells tatsächlich ist
  (`BAAI/bge-m3`, Default seit #732, trägt nativ 8192 Tokens; das wird absichtlich nicht
  ausgenutzt, siehe Modul-Docstring). `SentenceTransformer.encode` schneidet Eingaben über
  dem tatsächlichen Modell-Limit stillschweigend ab. Bei deutscher Fachprosa liegt die
  nutzbare Chunkgröße je nach Tokenizer bei rund 180–220 Wörtern (≈2,47 Tokens/Wort bei
  `intfloat/multilingual-e5-small`, dem Default vor #732; ≈2,0 Tokens/Wort bei `BAAI/bge-m3`,
  Stichprobenmessung 2026-08-08) — `academic_vault/chunking.py` (`TARGET_TOKENS`).
- **Keine eigene Datenerhebung und keine Statistik-Suite.** Interviews, Fragebögen,
  Laborwerte, Signifikanztests und Regressionsmodelle liegen außerhalb des Plugins.
  `scripts/meta_analysis.py` rechnet eine DerSimonian-Laird-Meta-Analyse auf bereits
  publizierten Effektstärken, es erhebt keine.
- **Office-Formate nur mit externem Plugin.** Excel-, Word- und PowerPoint-Export hängen am
  Marketplace-Plugin `document-skills`, deklariert in `.claude-plugin/plugin.json`. Fehlt
  es, melden die betroffenen Commands den Nachinstallations-Weg statt ein Dokument zu
  erzeugen.
- **Auf deutschsprachige Hochschulen zugeschnitten.** Zitierstile, Formalia-Prüfung
  (`skills/submission-checker/SKILL.md`) und der Anti-KI-Pass folgen den Konventionen
  deutschsprachiger Prüfungsordnungen. Für andere Systeme sind sie Ausgangspunkt, kein
  Maßstab.

## Was das Plugin nicht darf

- **Keinen Zugang beschaffen, den du nicht hast.** Paywalls werden nicht umgangen. Der
  optionale SciHub-Tier (F18, per Default deaktiviert) ist rechtlich umstritten und liegt
  vollständig in deiner Verantwortung — Details und Opt-in-Ablauf stehen im
  [SciHub-Hinweis der README](../../README.md), hier bewusst nur verlinkt, nicht
  wiederholt.
- **Kein Werkzeug für Prüfungsbetrug sein.** Eine vollständig generierte und unverstandene
  Arbeit einzureichen, ist an praktisch jeder Hochschule ein Täuschungsversuch — auch mit
  dem Anti-KI-Pass (`skills/humanizer-de/SKILL.md`), der Stilmerkmale glättet, aber keine
  Redlichkeitsprüfung deiner Hochschule ersetzt. Was hier steht, ist keine Rechtsberatung,
  sondern eine Warnung: Was am Ende erlaubt ist, entscheidet deine Prüfungsordnung, nicht
  dieses Dokument.
- **Nicht als Plagiatsdienst gelten.** `skills/plagiarism-check/SKILL.md` misst
  N-Gramm-Überlappung ausschließlich gegen die Quellen *in deinem Vault*. Gegen alles, was
  dort nicht liegt, prüft der Skill nichts — die offizielle Prüfung deiner Hochschule
  ersetzt er nicht.

## Was das Plugin nicht prüft

- **Zitate ohne Gegenprüfung.** Der `verbatim-guard`-Hook (`hooks/verbatim-guard.mjs`)
  belegt, dass ein Zitat aus deinem Vault stammt. Autorenname, Jahr und (seit Issue #724)
  auch die Seitenzahl von Klammer-Belegen werden gegen den Vault geprüft
  (`papers.csl_json` bzw. `quotes.printed_page`/`papers.page_first`/`page_last`).
  **Seit Issue #846 wird auch der Wortlaut selbst geprüft:** weicht ein wörtliches Zitat
  vom hinterlegten Vault-Snapshot ab, blockiert der Hook mit Fundstelle
  (`Datei:Zeile:Spalte`), beiden Wortlauten und den abweichenden Wörtern. Reine
  Darstellungsunterschiede lösen dabei keinen Alarm aus — typografische
  Anführungszeichen und Apostrophe, kollabierter Whitespace und Zeilenumbrüche,
  Ligaturen, Trennstriche am Zeilenende und `[…]`-Auslassungen gelten als
  gleichbedeutend, ein reiner Groß-/Kleinschreibungsunterschied als Hinweis statt
  als Block.
  Was der Wortlaut-Abgleich **nicht** leistet: Es gilt eine **Mindestlänge** von 40
  normalisierten Zeichen (`MIN_FUZZY_CANDIDATE_LEN` in
  `academic_vault/quote_match.py`); kürzere Zitate werden nur auf Vorkommen geprüft, nicht auf
  Abweichung — kurze Fragmente erreichen in langem Text zufällig hohe
  Ähnlichkeitswerte und ergäben Falschbefunde. Passen zwei Vault-Zitate praktisch
  gleich gut, meldet der Hook „nicht im Vault" statt einen Wortlaut-Vorwurf gegen das
  womöglich falsche Zitat zu erheben. Geprüft wird immer gegen den **Vault-Snapshot**,
  nicht gegen das PDF — ist der Snapshot selbst falsch erfasst, ist es die Prüfung auch
  (dafür `vault.verify_verbatim` gegen den PDF-Volltext nutzen). Paraphrasen bleiben
  Sache des separaten NLI-Zitatscans (`hooks/nli-quote-scan.mjs`), seitenübergreifende
  Zitate und Zitate aus Quellen außerhalb des Vaults bleiben ungeprüft. Jedes Zitat vor
  der Abgabe trotzdem im Original gegenprüfen.
  **Geprüft** werden ausschließlich APA-artige Belege: die klammer­förmige Form
  (`(Müller 2021, S. 45)`, Co-Autoren, `vgl.`/`zit. nach`), die narrative Form
  außerhalb von Klammern (`Müller (2021, S. 45) zeigt …`, `Müller et al. (2021)
  belegen …`, `vgl. Schmidt 2019`) und Sekundärbelege (`Schmidt, 2015, zitiert nach
  Müller, 2021`, beide Werke einzeln). **Nicht geprüft** — und seit Issue #740
  wenigstens *gemeldet*, statt stillschweigend zu passieren — sind LaTeX-Fußnoten
  (`\footnote{Vgl. Müller 2021.}`), Markdown-Fußnoten (`[^1]`, `[^1]: Vgl. …`) und
  numerische Verweise im IEEE-Stil (`[12]`); wer ausschließlich so zitiert, sieht
  dazu einen nicht-blockierenden Hinweis auf stderr (abstellbar über
  `ACADEMIC_CITATION_UNCHECKED_NOTICE=off`, siehe
  [docs/reference/hooks.md](../reference/hooks.md#klammer-zitat-validierung)). Ganz
  ungeprüft und ungemeldet bleiben die deutsche Zitierweise mit Fußnoten ohne
  Autor/Jahr im Fließtext sowie Körperschaftsautoren.
- **Fachliches Urteil.** Die [5D-Bewertung](../reference/search.md#5d-scoring) sortiert
  Treffer, sie entscheidet nicht, was methodisch tragfähig oder für deine Forschungsfrage
  relevant ist. Scores sind Sortierhilfen, keine Wahrheit.
- **Die Eingaben der Meta-Analyse.** `scripts/meta_analysis.py` übernimmt Effektgröße
  (`yi`) und Varianz (`vi`) so, wie sie im Eingabe-JSON stehen — ein falscher Wert ergibt
  eine falsche gepoolte Effektstärke, ohne dass das Skript das erkennen könnte.

## Pflicht zur Offenlegung der KI-Nutzung

Praktisch jede Prüfungsordnung verlangt inzwischen, KI-Einsatz offenzulegen. Der
`ai-disclosure`-Skill (`skills/ai-disclosure/SKILL.md`) erzeugt dafür eine zweiteilige
Erklärung nach der ICMJE-Aufteilung (Danksagung für Sprachpolitur/Textaufbereitung,
Methodenteil für Datenerhebung/Analyse) — als Textvorschlag auf Basis vorhandener
Vault-Spuren, nie als unterstellte Tatsache. Die eidesstattliche Erklärung selbst prüft
`skills/submission-checker/SKILL.md`. Ob und wie du offenlegst, entscheidet am Ende deine
Hochschule, nicht dieses Plugin.

Was gut funktioniert und was regelmäßig schiefgeht, steht in
[Claude Code bedienen](working-with-claude-code.md); der ganze Ablauf im
[Walkthrough](walkthrough.md).
