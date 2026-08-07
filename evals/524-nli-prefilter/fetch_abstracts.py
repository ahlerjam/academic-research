"""Holt echte Open-Access-Abstracts aus OpenAlex, breit ueber Faecher gestreut.

Kein API-Key noetig. Der Abstract kommt als inverted index und wird hier
rekonstruiert. Ausgabe: JSON mit doi/title/abstract/field je Paper.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

# Breite Faecherstreuung -- der #524-Report nennt die Beschraenkung auf
# ML/NLP-Paper ausdruecklich als offene Luecke.
QUERIES = {
    "wirtschaft": "digital transformation small medium enterprises governance",
    "medizin": "randomized controlled trial patient outcome intervention",
    "psychologie": "cognitive behavioral intervention adolescents wellbeing",
    "soziologie": "social inequality labour market participation",
    "paedagogik": "classroom instruction student achievement intervention",
    "umwelt": "climate adaptation policy municipal implementation",
    "informatik": "distributed systems fault tolerance consistency",
    "public-health": "vaccination uptake determinants population survey",
}
PER_FIELD = int(sys.argv[2]) if len(sys.argv) > 2 else 6
MAILTO = "jam@ahler.org"  # OpenAlex bittet um eine Kontaktadresse (polite pool)


def reconstruct(inv):
    if not inv:
        return ""
    positions = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


out = []
for field, q in QUERIES.items():
    params = urllib.parse.urlencode(
        {
            "search": q,
            "filter": "is_oa:true,has_abstract:true,type:article,language:en",
            "per-page": str(PER_FIELD * 3),
            "select": "id,doi,title,abstract_inverted_index,publication_year",
            "mailto": MAILTO,
        }
    )
    url = f"https://api.openalex.org/works?{params}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = json.load(r)
    except Exception as exc:
        print(f"{field}: FEHLER {exc}", file=sys.stderr)
        continue
    taken = 0
    for w in data.get("results", []):
        abstract = reconstruct(w.get("abstract_inverted_index"))
        # Nur brauchbar lange Abstracts mit klaren Aussagesaetzen.
        if len(abstract) < 600 or len(abstract) > 2500:
            continue
        out.append(
            {
                "field": field,
                "doi": w.get("doi"),
                "year": w.get("publication_year"),
                "title": (w.get("title") or "").strip(),
                "abstract": abstract,
            }
        )
        taken += 1
        if taken >= PER_FIELD:
            break
    print(f"{field}: {taken} Paper", file=sys.stderr)
    time.sleep(0.3)

dest = sys.argv[1]
with open(dest, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
print(f"\n{len(out)} Paper -> {dest}", file=sys.stderr)
