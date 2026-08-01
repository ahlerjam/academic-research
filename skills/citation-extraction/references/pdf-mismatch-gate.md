# PDF-Mismatch-Gate — Hintergrund und Optionen

Der `quote-extractor`-Agent meldet `possible_pdf_mismatch: true`, wenn der
gelesene PDF-Inhalt nicht zum erwarteten Paper zu passen scheint (Titel,
Autoren oder Thema weichen ab). Typische Ursachen: falsch zugeordnete Datei
beim Import, ein Sammelband statt des Einzelbeitrags, oder ein Download, der
eine Fehlerseite statt des Volltexts geliefert hat.

## Warum ein Gate und kein Flag

Ein reines Flaggen für späteres Review hilft nicht: Die Zitate landen dann
bereits im Vault, `hooks/verbatim-guard.mjs` betrachtet sie beim Kapitel-Write
als belegt, und sie laufen unbemerkt in Text und Bibliographie ein. Wird der
Mismatch später bemerkt, ist unklar, welche Kapitelstellen betroffen sind.
Deshalb blockiert `possible_pdf_mismatch: true` die Persistierung, bis der
User entschieden hat.

## Die drei Optionen

**Fortfahren — Zitate trotz Mismatch übernehmen.** Der Agent wird mit
`mismatch_override: true` erneut aufgerufen und persistiert selbst. Sinnvoll,
wenn der Mismatch erklärbar ist (etwa ein Preprint mit abweichendem Titel).
Der Skill ruft `vault.add_quote()` nicht zusätzlich auf — sonst entstünden
doppelte Zitate mit verschiedenen `quote_id`s.

**Paper überspringen.** Das Paper wird sessionlokal als „Ausgelassen"
geführt und taucht im Report als eigene Gruppe auf. Bewusst **kein**
Vault-Schreibzugriff, insbesondere **kein** `vault.add_excluded_source()`:
Das Register `excluded_sources` beschreibt methodische Ausschlüsse aus dem
Korpus. Es wird von `reading-list-import` beim Re-Import geprüft und von
`prisma-flow` als PRISMA-2020-Eligibility-Grund ausgewertet, und es gibt in
`academic_vault/` keine Operation, die einen Eintrag wieder entfernt. Ein
transienter Technikfehler — eine falsch zugeordnete Datei — würde ein
zitierfähiges Paper damit dauerhaft aus der Arbeit entfernen.

**PDF-Zuordnung prüfen.** Der Vorgang pausiert ohne Persistenz, der User
klärt die Zuordnung (etwa via `vault.update_pdf_path`) und startet die
Extraktion danach neu.

Ohne Freigabe aus diesem Gate wird kein Zitat des betroffenen Papers
gespeichert.
