"""Waehlt je Paper die zitierfaehigen Ergebnissaetze aus dem Abstract.

Kriterium: Satz enthaelt eine pruefbare Aussage -- Zahl/Prozent, Quantor,
Bedingung oder eine Ergebnisformulierung. Genau solche Saetze lassen sich
regelhaft verzerren (Quantor verstaerken, Bedingung streichen, Zahl aufblasen).
"""

import json
import re
import sys

SRC, DEST = sys.argv[1], sys.argv[2]
MAX_PER_PAPER = 2

SIGNAL = re.compile(
    r"\b(\d+(\.\d+)?\s*%|\d+(\.\d+)?\s*(percent|percentage points)|"
    r"significant|significantly|associated with|correlat|increase[ds]?|decrease[ds]?|"
    r"reduc(ed|tion)|improv(ed|ement)|higher|lower|we found|results show|findings (show|suggest|indicate)|"
    r"only|among those|for (patients|participants|students|firms|respondents)|"
    r"in the (intervention|treatment|control) group)\b",
    re.I,
)
HEDGE = re.compile(
    r"\b(may|might|could|suggest|appear|likely|however|although|whereas|while)\b", re.I
)
SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

papers = json.load(open(SRC, encoding="utf-8"))
out = []
for p in papers:
    sents = [s.strip() for s in SPLIT.split(p["abstract"]) if 80 <= len(s.strip()) <= 400]
    scored = []
    for i, s in enumerate(sents):
        hits = len(SIGNAL.findall(s))
        if hits == 0:
            continue
        scored.append((hits + (1 if HEDGE.search(s) else 0), i, s))
    scored.sort(reverse=True)
    picks = []
    for _, i, s in scored[:MAX_PER_PAPER]:
        picks.append(
            {
                "sentence": s,
                "context_before": sents[i - 1] if i > 0 else "",
                "context_after": sents[i + 1] if i + 1 < len(sents) else "",
            }
        )
    if picks:
        out.append({**{k: p[k] for k in ("field", "doi", "year", "title")}, "picks": picks})

json.dump(out, open(DEST, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"{len(out)} Paper mit {sum(len(o['picks']) for o in out)} Kandidatensaetzen -> {DEST}")
for o in out:
    print(f"\n--- [{o['field']}] {o['title'][:95]}")
    for pk in o["picks"]:
        print(f"    > {pk['sentence'][:260]}")
