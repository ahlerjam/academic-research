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

- **Tabellen nicht immer strukturerhaltend extrahieren.** Das Backend `pdfplumber` ist ein
  optionales Extra (`uv sync --extra tables`, siehe `pyproject.toml`). Fehlt es, liefert
  `vault.extract_tables` den Status `backend-missing` statt Zahlen —
  `academic_vault/tables.py`. Die `meta-analysis`-Pipeline übernimmt Effektstärken (`yi`,
  `vi`) ohnehin nur aus einem vom Nutzer bestätigten Eingabe-JSON, nie automatisch aus
  einer erkannten Tabelle — `scripts/meta_analysis.py`.
- **Kein unbegrenztes Kontextfenster beim Embedding.** Das Vektor-Modell
  `intfloat/multilingual-e5-small` schneidet Eingaben über seinem harten Limit
  stillschweigend ab. Bei deutscher Fachprosa (≈2,47 Tokens/Wort) liegt die nutzbare
  Chunkgröße bei rund 180 Wörtern — `academic_vault/chunking.py` (`TARGET_TOKENS`).
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
  belegt, dass ein Zitat aus deinem Vault stammt — nicht, dass Wortlaut, Seitenzahl,
  Autorenname und Jahr korrekt aus dem Original übernommen wurden. Jedes Zitat vor der
  Abgabe im Original gegenprüfen.
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
