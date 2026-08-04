# OSF-Registration-Templates — Feldlisten

**Quelle:** Open-Science-Framework-Registrierungs-API, `GET
https://api.osf.io/v2/schemas/registrations/{id}/` (öffentlich, unauthentifiziert).
Abgerufen 2026-08-04. Jede Sektion nennt Template-Name, interne OSF-Schema-ID und
Schema-Version — beides identifiziert die Vorlage eindeutig gegenüber künftigen
Änderungen. Das Center for Open Science pflegt insgesamt mehr als zehn Vorlagen;
hier sind nur die drei für diesen Skill relevanten erfasst (Scope-Grenze aus dem
Issue: keine Vorlagen-Volltexte, nur Feldnamen + Kurzeinordnung).

Kein Feld unten ist im OSF-Schema selbst als `required` markiert (anders als bei
PROSPERO) — OSF überlässt die Vollständigkeit den Autor:innen. Der Skill füllt
unbeantwortete Felder trotzdem mit dem festen Platzhalter statt sie wegzulassen
(AC4), damit die Lücke sichtbar bleibt.

## general — „OSF Preregistration"

Schema-ID `697b72f611a8e98484c6139b`, Version 4. Passend für quantitative
Hypothesentests ohne spezielleres Template.

### Overview
- Research questions or hypotheses
- Foreknowledge of data or evidence
- Explanation of foreknowledge and managing unintended influences

### Research Design
- Study type
- Intention for causal interpretation
- Blinding of experimental treatments
- Additional blinding during research or analysis
- Study design
- Randomization

### Sampling
- Data collection procedures
- Sample size
- Sample size rationale
- Starting and stopping rules

### Variables
- Manipulated variables
- Measured variables
- Indices

### Analysis Plan
- Statistical models
- Transformations
- Inference criteria
- Data inclusion and exclusion
- Missing data
- Other planned analysis

### Other
- Context and additional information

## secondary-data — „Secondary Data Preregistration"

Schema-ID `64775783798e08000a70407e`, Version 3. Für Analysen an bereits
existierenden Datensätzen (Sekundärdatenanalyse) — unterscheidet sich vom
`general`-Template vor allem in der Sektion „Data Description" (Zugriff,
Datums-/Herkunftsangaben) und „Knowledge of Data" (was war vor der Analyse
schon bekannt).

### Study Information
- Research questions
- Hypotheses

### Data Description
- Datasets used
- Data availability
- Data access
- Data identifiers
- Access date
- Data collection procedures
- Codebook

### Variables
- Manipulated variables
- Measured variables
- Missing data
- Unit of analysis
- Statistical outliers
- Sampling weights

### Knowledge of Data
- Prior Publication/Dissemination
- Prior knowledge

### Analyses
- Statistical models
- Effect size
- Statistical power
- Inference criteria
- Assumption Violation/Model Non-Convergence
- Reliability and Robustness Testing
- Exploratory analysis

## qualitative — „Qualitative Preregistration"

Schema-ID `5fa0ac510a7f38001c8ae854`, Version 1. Bewusst kein Analyseplan im
quantitativen Sinn — fragt Design, Fallauswahl und Glaubwürdigkeitsstrategien
statt Hypothesen und Teststatistik ab. Für qualitative oder Mixed-Methods-Vorhaben
ist dieses Template zu wählen, nicht `general` (AC1).

### Study Information
- Research Aims
- Research question(s)
- Anticipated Duration

### Design Plan
- Study design
- Sampling and case selection strategy

### Data Collection
- Data source(s) and data type(s)
- Data collection methods
- Data collection tools, instruments or plans
- Stopping criteria

### Analysis Plan
- Data analysis approach
- Data analysis process
- Credibility strategies

### Miscellaneous
- Reflection on your positionality (optional)
