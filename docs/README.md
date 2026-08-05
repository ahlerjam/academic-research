# Dokumentation — Übersicht

[← zurück zur Projekt-README](../README.md)

Alles, was zu diesem Plugin geschrieben ist, hängt an dieser Seite. Such dir unten den
Lesepfad, der zu deiner Lage passt — jede Unterseite ist von hier aus mit höchstens zwei
Klicks erreichbar. Wenn du nur nachschlagen willst, spring direkt in die Referenz.

Jede Seite ist gleich aufgebaut: Titel, Rückweg auf diese Übersicht, ein Absatz, der sagt
worum es geht, danach die Abschnitte. Seiten, die einen alten Stand festhalten, tragen
ganz oben einen Hinweis und stehen unten im eigenen Abschnitt.

## Ich fange gerade an

Weißt du schon, was du schreibst — systematische Übersichtsarbeit, empirische
Qualifikationsarbeit mit eigener Erhebung, Literaturarbeit, Zeitschriftenbeitrag?
[Einstieg nach Vorhaben](guide/project-paths.md) zeigt dir direkt die passende
Skill-Reihenfolge dafür. Weißt du es noch nicht, geht es unten Schritt für Schritt.

1. [Erste Schritte](guide/getting-started.md) — von der Installation bis zum ersten
   verifizierten Zitat, in einem Zug und ohne Sprung auf andere Seiten.
2. [Grenzen](guide/limits.md) — was das Plugin nicht kann, nicht darf und nicht prüft,
   mit Beleg. Lies das, bevor du installierst.
3. [Installation und Migration](guide/installation.md) — Voraussetzungen im Detail, was
   das Setup wirklich tut, Umstieg von v5.
4. [Walkthrough](guide/walkthrough.md) — jeder Arbeitsschritt in der realen Reihenfolge,
   mit Beispielformulierung und erwartetem Ergebnis.
5. [Troubleshooting](guide/troubleshooting.md) — wenn etwas klemmt.
6. [Quickstart-Protokoll](quickstart-protocol.md) — ein realer Durchlauf mit allen
   Ausgaben, zum Abgleich mit deiner eigenen Installation.

Der Praxis-Leitfaden geht darüber hinaus:

- [Modellwahl](guide/model-choice.md) — welches Modell für welchen Arbeitsschritt, und wie
  du umschaltest.
- [Token-Budget](guide/token-budget.md) — welche Schritte teuer sind, wie du sie
  eingrenzt, wie du Zwischenstände sicherst.
- [Bewährtes Vorgehen](guide/best-practices.md) — was funktioniert und was regelmäßig
  schiefgeht.

Neue Begriffe schlägst du unterwegs im [Glossar](reference/glossary.md) nach.

## Ich arbeite schon damit

- [Commands](reference/commands.md) — jeder Slash-Command mit Syntax und Beispielen.
- [Skills](reference/skills.md) — welcher Skill wann von selbst anspringt.
- [Agents](reference/agents.md) — die Subagents und wer sie startet.
- [Vault-MCP-Server](reference/vault.md) — Datenmodell, Volltext- und Vektorindex, alle
  MCP-Tools.
- [Suchquellen, Scoring, Cluster](reference/search.md) — woher die Literatur kommt und
  wie sie bewertet wird.
- [Hooks-Stack](reference/hooks.md) — was wann eingreift und was protokolliert wird.
- [Per-Uni-Profile](reference/uni-profiles.md) — Hochschulzugänge einrichten.
- [NotebookLM-Bundle](skills/notebook-bundle.md) — Triage-Bundle bauen, und warum es kein
  Zitat-Pfad ist.
- [literature_state.md — Schema](literature-state-schema.md) — Aufbau des
  Snapshot-Exports aus dem Vault.

## Ich will beitragen

- [Schreibregeln und Glossar-Pflicht](style-guide.md) — Ton, Zielgruppe und der
  Fachbegriffs-Guard für den Einstiegspfad, bevor du neue Doku schreibst.
- [Entwicklung, Tests und Evals](development.md) — Setup, lokale Gates, Konventionen und
  die versionierten `.claude/`-Dateien.
- [Skip-Reasons](SKIP_REASONS.md) — welche Tests bewusst übersprungen werden und warum.
- [Eval-Strategie und Reports](evals/README.md) — Status jeder Eval-Komponente, Budget,
  vorhandene Berichte.
- [AGENTS.md](../AGENTS.md) — verbindliche Konventionen und rote Linien, auch für
  menschliche Beitragende.
- [CHANGELOG.md](../CHANGELOG.md) — was sich wann geändert hat.

## Historisches und Momentaufnahmen

Diese Seiten halten einen vergangenen Stand fest. Sie werden nicht nachgepflegt und sind
kein Sollzustand — sie stehen hier, damit alte Entscheidungen nachvollziehbar bleiben.

- [Planungs- und Spec-Archiv](superpowers/README.md) — Planungsdokumente früherer
  Entwicklungswellen.
- [Issue-Board-Audit 2026-06-03](audit/2026-06-03-board-audit.md) — Momentaufnahme des
  Boards.
- [AC3+AC4 Live-Verifikationsbeleg (Issue #389)](audit/2026-07-27-issue-389-ac3-vulture-live-verification.md)
  — Belegnachweis für die vulture-Dead-Code-Integration.
- [Evals-Summary v5.2.0](evals/2026-04-23-summary.md) — Momentaufnahme der
  Eval-Infrastruktur.
- [Recall@10-Goldset und Modell-A/B](evals/recall-at-k-model-ab-375.md) — Momentaufnahme
  eines Messlaufs.
- [Auto-Download-Tier-Pipeline v6.2](evals/v6.2-tier-eval.md) — Momentaufnahme einer
  Tier-Prüfung.
