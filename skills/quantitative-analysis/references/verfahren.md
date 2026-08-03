# Verfahrenswahl, Voraussetzungen, Berichtsform

Referenz zum Skill `quantitative-analysis`. Die Tabellen hier sind der
Nachschlageteil; die SKILL.md bleibt schlank.

## 1. Entscheidungstabelle: Fragestellung × Skalenniveau × Design

| Fragestellung | abhängige Variable | Design | Verfahren (`verfahren`-Wert im Plan) |
| --- | --- | --- | --- |
| Verteilung beschreiben | beliebig | — | `deskriptiv` |
| Unterschied, 2 Gruppen | metrisch, normalverteilt, gleiche Varianzen | unabhängig | `t_test_unabhaengig` |
| Unterschied, 2 Gruppen | metrisch, normalverteilt, ungleiche Varianzen | unabhängig | `welch_test` |
| Unterschied, 2 Gruppen | ordinal oder metrisch ohne Normalverteilung | unabhängig | `mann_whitney_u` |
| Unterschied, 2 Messzeitpunkte | metrisch, Differenzen normalverteilt | verbunden | `t_test_gepaart` |
| Unterschied, 2 Messzeitpunkte | ordinal oder schiefe Differenzen | verbunden | `wilcoxon` |
| Unterschied, ≥ 3 Gruppen | metrisch, normalverteilt, gleiche Varianzen | unabhängig | `anova_einfaktoriell` |
| Unterschied, ≥ 3 Gruppen | ordinal oder ohne Normalverteilung | unabhängig | `kruskal_wallis` |
| Zusammenhang | beide nominal | — | `chi_quadrat_unabhaengigkeit` |
| Zusammenhang | beide metrisch, linear | — | `pearson_r` |
| Zusammenhang | ordinal oder monoton, nicht linear | — | `spearman_rho` |

Die Zeile wird von links nach rechts gelesen: Erst steht die Frage fest, dann
das Skalenniveau, dann das Design. Wer beim Verfahren anfängt und rückwärts
begründet, hat das Ergebnis schon gewählt.

## 2. Voraussetzungen je Verfahren

| Verfahren | geprüft wird | Prüfung im Skript | Alternative bei Verletzung |
| --- | --- | --- | --- |
| `t_test_unabhaengig` | Normalverteilung je Gruppe, Varianzhomogenität | Shapiro-Wilk je Gruppe, Levene-Test (Median-zentriert) | Mann-Whitney-U bzw. Welch-Test |
| `welch_test` | Normalverteilung je Gruppe | Shapiro-Wilk je Gruppe | Mann-Whitney-U |
| `t_test_gepaart` | Normalverteilung der **Differenzen** | Shapiro-Wilk auf den Differenzen | Wilcoxon-Vorzeichen-Rang-Test |
| `mann_whitney_u` | Mindestfallzahl, vergleichbare Verteilungsform | n je Gruppe, Schiefedifferenz als Anhaltspunkt | exakte Berechnung; Lageaussage einschränken |
| `wilcoxon` | auswertbare Paare, Symmetrie der Differenzen | n ohne Nulldifferenzen, Schiefe | Vorzeichentest |
| `anova_einfaktoriell` | Normalverteilung je Gruppe, Varianzhomogenität | Shapiro-Wilk je Gruppe, Levene-Test | Kruskal-Wallis-Test |
| `kruskal_wallis` | Mindestfallzahl je Gruppe | n je Gruppe | exakte Berechnung |
| `chi_quadrat_unabhaengigkeit` | erwartete Zellhäufigkeit ≥ 5, unabhängige Fälle | Minimum der erwarteten Häufigkeiten | exakter Test nach Fisher (2×2), Kategorien zusammenfassen |
| `pearson_r` | Normalverteilung beider Merkmale, Linearität | Shapiro-Wilk je Merkmal; Linearität nur im Streudiagramm | Spearman-Rangkorrelation |
| `spearman_rho` | Mindestfallzahl, monotoner Zusammenhang | n, Beurteilung im Streudiagramm | exakte Permutationsverteilung |

Zwei Dinge stehen hier absichtlich nicht: Linearität und Unabhängigkeit der
Beobachtungen. Beides ist kein Testergebnis, sondern eine Sache des Designs und
des Streudiagramms — das Skript weist darauf hin, statt eine Prüfung
vorzutäuschen.

Shapiro-Wilk reagiert bei großen Stichproben auf jede kleine Abweichung. Ein
signifikanter Test bei n = 300 ist deshalb kein Grund, das Verfahren zu
wechseln; hier zählt der Blick auf Schiefe und Histogramm. Umgekehrt gilt bei
n < 30 das Gegenteil: Der Test findet auch grobe Abweichungen oft nicht.

## 3. Effektstärken und ihre Intervalle

| Verfahren | Effektstärke | Intervall |
| --- | --- | --- |
| `t_test_unabhaengig`, `welch_test` | Hedges' g (Cohen's d mit Kleinstichprobenkorrektur) | Perzentil-Bootstrap |
| `t_test_gepaart` | Cohen's d_z | Perzentil-Bootstrap |
| `mann_whitney_u` | rangbiseriale Korrelation r | Perzentil-Bootstrap |
| `wilcoxon` | rangbiseriale Korrelation r (matched pairs) | Perzentil-Bootstrap |
| `anova_einfaktoriell` | η² | Perzentil-Bootstrap |
| `kruskal_wallis` | ε² | Perzentil-Bootstrap |
| `chi_quadrat_unabhaengigkeit` | Cramérs V | Perzentil-Bootstrap |
| `pearson_r` | Pearson r | analytisch, Fisher-z-Transformation |
| `spearman_rho` | Spearman ρ | Perzentil-Bootstrap |

Der Bootstrap zieht bei unabhängigen Stichproben innerhalb jeder Gruppe, bei
verbundenen Daten und Zusammenhangsmaßen über gemeinsame Fallindizes — Paare
bleiben Paare. Der Seed steht im Analyseplan und im Protokoll; zwei Läufe mit
demselben Seed liefern dasselbe Intervall.

Zusätzlich berichten die drei t-Test-Varianten die Mittelwertdifferenz mit
analytischem Intervall. Sie ist die Größe in der Einheit der Messung und
gehört in den Ergebnisteil, weil g allein nichts über die Praxisbedeutung sagt.

Für die Einordnung von g gilt die übliche Faustregel (0.2 / 0.5 / 0.8) nur als
Notbehelf. Wo das Fach eigene Vergleichswerte hat, sind die vorzuziehen — und
zu zitieren.

## 4. Berichtsvorlagen

**Gruppenvergleich (t-Test):**

> Die Gruppen unterschieden sich im Score (M_A = 51.2, SD = 7.8, n = 29;
> M_B = 57.6, SD = 8.1, n = 30), t(57) = −3.09, p = .003, Hedges' g = −0.80,
> 95-%-KI [−1.31, −0.29]. Die Mittelwertdifferenz betrug −6.4 Punkte,
> 95-%-KI [−10.5, −2.3]. Shapiro-Wilk (p = .41 / p = .27) und Levene-Test
> (p = .88) sprachen nicht gegen die Voraussetzungen.

**Varianzanalyse (Omnibus):**

> Der Score unterschied sich zwischen den drei Standorten,
> F(2, 56) = 5.41, p = .007, η² = .16, 95-%-KI [.03, .32]. Paarweise
> Vergleiche wurden nicht gerechnet.

**Zusammenhang (χ²):**

> Entscheidung und Geschlecht hingen zusammen, χ²(1, N = 60) = 6.24,
> p = .013, Cramérs V = .32, 95-%-KI [.07, .54]. Die kleinste erwartete
> Häufigkeit betrug 12.8.

**Verletzte Voraussetzung:**

> Die Dauer war in beiden Gruppen deutlich rechtsschief (Shapiro-Wilk
> p < .001). Gerechnet wurde dennoch der geplante t-Test; als Alternative
> käme der Mann-Whitney-U-Test in Betracht. Die Entscheidung ist im
> Analyseplan dokumentiert.

Was in keiner Vorlage steht: eine Aussage darüber, was das Ergebnis für die
Fragestellung heißt. Die schreibt die Autorin.

## 5. Aufbau des Analyseplans

```json
{
  "version": 1,
  "alpha": 0.05,
  "konfidenzniveau": 0.95,
  "bootstrap": { "replikationen": 2000, "seed": 610 },
  "fehlende_werte": ["", "NA", "-99"],
  "variablen": { "score": "metrisch", "gruppe": "nominal" },
  "analysen": [
    { "id": "d1", "verfahren": "deskriptiv", "variablen": ["score", "gruppe"] },
    { "id": "t1", "verfahren": "t_test_unabhaengig",
      "messwert": "score", "gruppierung": "gruppe" }
  ]
}
```

Feldnamen je Verfahrensgruppe:

- Gruppenvergleiche (`t_test_unabhaengig`, `welch_test`, `mann_whitney_u`,
  `anova_einfaktoriell`, `kruskal_wallis`): `messwert`, `gruppierung`.
- Messwiederholung (`t_test_gepaart`, `wilcoxon`): `messwert_vorher`,
  `messwert_nachher`.
- Zusammenhang (`chi_quadrat_unabhaengigkeit`, `pearson_r`, `spearman_rho`):
  `merkmale` als Zweierliste.
- `deskriptiv`: `variablen` als Liste.

Fehlende Werte werden fallweise ausgeschlossen und je Analyse ausgewiesen. Wer
Imputation braucht, ist hier falsch — dieser Skill deckt sie nicht ab.
