# Bewährtes Vorgehen und ehrliche Grenzen

[← Doku-Übersicht](../README.md)

Diese Seite sammelt, was sich im Betrieb bewährt hat, welche Fehler regelmäßig passieren
und — der wichtigste Teil — wofür dieses Plugin nicht taugt. Wer die letzte Liste vor der
Installation liest, spart sich unter Umständen den ganzen Aufwand.

Der Ablauf selbst steht im [Walkthrough](walkthrough.md), der Einstieg in
[Erste Schritte](getting-started.md).

## Wofür das Plugin gut geeignet ist

- **Literaturgetriebene Textarbeit.** Hausarbeit, Bachelor-, Master-, Doktorarbeit: viele
  Quellen, seitengenaue Belege, ein über Wochen wachsender Stand.
- **Systematische Reviews.** Screening mit Ledger, PRISMA-Zähler, Verzerrungsbewertung und
  Extraktionsmatrix hängen an denselben Daten und nicht an getrennten Tabellen.
- **Ein Gedächtnis über Sitzungen hinweg.** Der Vault überlebt jeden Verlauf; Zitate,
  Notizen und Ausschlussentscheidungen bleiben abrufbar.
- **Formalia und Stil am Ende.** Abgabe-Check, Anti-KI-Pass und Exportformate sind auf
  deutschsprachige Prüfungsordnungen zugeschnitten.

## Was sich bewährt hat

- **Kontext zuerst, immer.** Ohne gefüllte `academic_context.md` raten alle folgenden
  Schritte. Fünf Minuten am Anfang sparen jede Nachfrage danach.
- **Erst belegen, dann schreiben.** Zieh die Zitate in den Vault, bevor du ein Kapitel
  anfängst. Umgekehrt schreibst du einen Entwurf, den der `verbatim-guard`-Hook
  anschließend zerlegt.
- **Pro Kapitel eine eigene Sitzung.** Der Vault trägt den Zusammenhang, nicht der
  Verlauf — und das Fenster bleibt schlank (siehe [Token-Budget](token-budget.md)).
- **Notizen anlegen, während du liest.** Der `reading-notes`-Skill kostet pro Quelle eine
  Minute; die Rekonstruktion vier Wochen später kostet eine Stunde.
- **Ausschlüsse begründen und ablegen.** Wer eine Quelle verwirft, notiert warum — sonst
  taucht sie in der nächsten Suchrunde wieder auf und wird erneut geprüft.
- **Modell zum Schritt wählen.** Recherche klein, Kapitelentwurf groß, danach zurück —
  siehe [Modellwahl](model-choice.md).
- **Vor der Abgabe einfrieren.** Material-Passport und Repro-Lock machen den Stand
  nachvollziehbar; danach ändert niemand mehr versehentlich etwas.

## Typische Fehler

- **Das Thema zu spät schärfen.** Eine unscharfe Forschungsfrage produziert eine unscharfe
  Trefferliste, und die trägst du durch die ganze Arbeit. Lieber einen Durchgang mehr:

  ```
  Hilf mir, die Forschungsfrage zu präzisieren.
  ```

- **Jede Suche auf voller Tiefe.** Der teuerste Modus ist selten der nützlichste.
- **Zitate ungeprüft übernehmen.** Der Guard beweist Vault-Herkunft, nicht Korrektheit.
- **Kapitelentwürfe unverändert einreichen.** Ein Entwurf ist Rohmaterial. Die
  Argumentation musst du verantworten — inhaltlich und prüfungsrechtlich.
- **Den Vault als Ablage behandeln.** Er ist nur so gut wie das, was du hineinschreibst;
  ein Vault ohne Notizen und Zitate ist eine PDF-Halde.

Läuft etwas technisch schief, steht die Diagnose in
[Troubleshooting](troubleshooting.md) — hier stehen nur die Fehler, die kein Bug sind.

## Wofür das Plugin nicht geeignet ist

- **Keine Zitat-Garantie ohne Gegenprüfung.** Der `verbatim-guard`-Hook belegt, dass ein
  Zitat aus deinem Vault stammt — nicht, dass Wortlaut, Seitenzahl, Autorenname und Jahr
  korrekt aus dem Original übernommen wurden. Jedes Zitat gegenprüfen, bevor es in die
  Arbeit wandert.
- **Kein Ersatz für einen Plagiatsdienst.** Der `plagiarism-check`-Skill misst
  N-Gramm-Überlappung gegen die Quellen *in deinem Vault*. Gegen alles, was nicht im Vault
  liegt, prüft er nichts. Die offizielle Prüfung deiner Hochschule ersetzt er nicht.
- **Keine eigene Datenerhebung und keine Statistik-Suite.** Interviews, Fragebögen,
  Laborwerte, Signifikanztests und Regressionsmodelle liegen außerhalb. Der
  `meta-analysis`-Agent rechnet auf bereits publizierten Effektstärken, er erhebt nichts.
- **Kein Zugang, den du nicht hast.** Paywalls werden nicht umgangen. Ohne
  Open-Access-Quelle, Hochschullizenz oder Fernleihe gibt es kein PDF. Der SciHub-Tier ist
  per Default aus, rechtlich umstritten und liegt vollständig in deiner Verantwortung.
- **Office-Formate nur mit externem Plugin.** Excel, Word und PowerPoint hängen am
  Marketplace-Plugin `document-skills`. Fehlt es, melden die betroffenen Commands den
  Nachinstallations-Weg, statt ein Dokument zu erzeugen.
- **Auf deutschsprachige Hochschulen ausgelegt.** Zitierstile, Formalia-Prüfung und der
  Anti-KI-Pass folgen den Konventionen deutschsprachiger Prüfungsordnungen. Für andere
  Systeme sind sie Ausgangspunkt, nicht Maßstab.
- **Kein Ersatz für Fachurteil.** Was relevant, methodisch tragfähig und begründet ist,
  entscheidest du. Scores sind Sortierhilfen, keine Wahrheit.
- **Kein Werkzeug für Prüfungsbetrug.** Eine vollständig generierte und unverstandene
  Arbeit einzureichen, ist an praktisch jeder Hochschule ein Täuschungsversuch — mit oder
  ohne Anti-KI-Pass.
