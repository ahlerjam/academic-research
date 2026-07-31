# Beiträge zu academic-research

Danke für dein Interesse. Dieses Repository ist ein Claude-Code-Plugin für
akademisches Arbeiten und wird von einer einzelnen Person gepflegt. Damit
Beiträge tatsächlich helfen, gelten ein paar klare Regeln.

**English speakers: see [Policy on automated and AI-generated contributions](#policy-on-automated-and-ai-generated-contributions) below — it applies to you before you open a PR.**

## Der übliche Weg

1. **Erst ein Issue, dann Code.** Öffne ein Issue oder kommentiere ein
   bestehendes und warte auf eine Rückmeldung, bevor du anfängst. Ein Issue,
   das offen ist, bedeutet nicht, dass es zur Bearbeitung freigegeben ist.
2. **Ein Thema pro Pull Request.** Kein Mitnehmen von Formatierungen,
   Umbenennungen oder Nebenfixes.
3. **Tests gehören dazu.** `uv run pytest tests/` und `uv run ruff check .`
   müssen lokal grün sein, bevor du den PR aufmachst — siehe `AGENTS.md`
   für die vollständige Befehlsliste.
4. **Sprache.** Prosa, Kommentare und Doku auf Deutsch mit voller
   Orthografie. Code-Identifier und Commit-Messages auf Englisch, mit
   Typ-Präfix und Issue-Nummer (`fix(hooks): … (#516)`).

## Geschützte Bereiche

Änderungen an `vault`, `hooks`, `security` und `ci` (maßgeblich:
`.claude/workflow.config.json`) werden **nicht** ohne vorherige Absprache im
Issue angenommen. Das ist die Sicherheitsschicht des Plugins; ein
funktionierender Patch ist hier kein hinreichender Grund für einen Merge.

## Policy on automated and AI-generated contributions

Agent-assisted work is welcome **when a human is accountable for it and the
change was agreed in an issue first.** Tooling is not the issue; unsolicited
volume is.

**Unsolicited automated pull requests will be closed without review.** A PR is
treated as unsolicited automation when it shows the typical drive-by pattern:
the contributor has no prior interaction with this project, forked the
repository minutes before opening the PR, and is opening comparable PRs across
many unrelated repositories in the same time window.

This applies regardless of whether the patch is correct. Correctness is not the
bar — a maintainer's review time is the scarce resource, and a change to this
project's guard hooks costs more to verify than to write.

**If you contribute with the help of an agent, you must:**

- comment on the issue and wait for a maintainer's go-ahead before writing code;
- have read and understood every line you submit, and be able to answer
  questions about it;
- disclose the tooling in the PR description;
- run the full test suite yourself, not rely on CI to find out.

**Specifically not accepted:** PRs opened to satisfy an external incentive
scheme — contribution-count leaderboards, crypto reward networks that pay for
merged pull requests, résumé or badge farming. If a merge into this repository
earns you something other than a working plugin, the answer is no. Say so
honestly if asked; an undisclosed incentive is a reason for a permanent block.

## Sicherheit

Melde Sicherheitslücken nicht als öffentliches Issue, sondern per E-Mail an
den Maintainer. Fork-Pull-Requests durchlaufen die automatische
Review-Pipeline nur eingeschränkt (keine Secrets im Fork-Kontext) — sie
werden ausschließlich manuell geprüft.
