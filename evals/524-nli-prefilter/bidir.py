"""Bidirektionales NLI gegen weggelassene Bedingungen.

Heute wird nur gefragt: folgt die Behauptung aus der Quelle? Eine Behauptung,
die eine Einschraenkung weglaesst, besteht diesen Test -- sie ist allgemeiner,
aber kein Widerspruch.

Die Gegenrichtung entlarvt sie: Aus einer allgemeinen Behauptung folgt die
spezifische Quellaussage NICHT. Nur bei echter Bedeutungsgleichheit gilt
Entailment in beide Richtungen.

  vorwaerts  = p(entailment | Praemisse=Quelle,      Hypothese=Behauptung)
  rueckwaerts= p(entailment | Praemisse=Behauptung,  Hypothese=Quellsatz)
"""

import json
import time
from pathlib import Path

S = Path(__file__).resolve().parent
MODEL = "MoritzLaurer/bge-m3-zeroshot-v2.0"

cases = {}
for f in ("set_med.json", "set_soz.json"):
    for c in json.loads((S / f).read_text(encoding="utf-8"))["cases"]:
        cases[c["id"]] = c
picks = json.loads((S / "picks.json").read_text(encoding="utf-8"))
flat = [pk for p in picks for pk in p["picks"]]
res = json.loads((S / "big_results.json").read_text(encoding="utf-8"))

import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(MODEL)
model.eval()
id2label = {int(k): v for k, v in model.config.id2label.items()}
ENT = next((i for i, lab in id2label.items() if lab.lower().startswith("entail")), 0)


def ent_prob(premise, hypothesis):
    inp = tok(premise, hypothesis, truncation=True, max_length=512, return_tensors="pt")
    with torch.no_grad():
        logits = model(**inp).logits[0]
    return float(torch.softmax(logits, dim=-1)[ENT])


rows = [r for r in res["bge-m3-zeroshot"]["rows"] if r["set"] == "neu"]
out, t0 = [], time.monotonic()
for k, r in enumerate(rows):
    c = cases[r["id"]]
    pk = flat[c["pick"] - 1]
    premise = " ".join(
        x.strip() for x in (pk["context_before"], pk["sentence"], pk["context_after"]) if x.strip()
    )
    back = ent_prob(c["claim"], pk["sentence"])  # Behauptung -> Quellsatz
    out.append({**r, "fwd": r["ent"], "bwd": back})
    if (k + 1) % 60 == 0:
        print(f"  {k + 1}/{len(rows)}", flush=True)
print(f"fertig in {time.monotonic() - t0:.0f}s\n")
(S / "bidir_results.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

FWD = 0.90


def evaluate(bwd_th):
    """faithful nur wenn BEIDE Richtungen halten."""
    tp = fp = fn = tn = 0
    cs_caught = cs_total = 0
    for r in out:
        ok = r["is_ent_argmax"] and r["fwd"] >= FWD and (bwd_th is None or r["bwd"] >= bwd_th)
        if r["label"] == "faithful":
            tp, fn = (tp + 1, fn) if ok else (tp, fn + 1)
        else:
            fp, tn = (fp + 1, tn) if ok else (fp, tn + 1)
            if r["type"] == "condition-stripped":
                cs_total += 1
                cs_caught += 0 if ok else 1
    return tp, fp, fn, tn, cs_caught, cs_total


print("Nur vorwaerts (heutiges Verfahren, Schwelle 0.90):")
tp, fp, fn, tn, csc, cst = evaluate(None)
print(f"  FP={fp}  FN={fn}  |  condition-stripped erkannt: {csc}/{cst}\n")
print("Mit Rueckwaerts-Bedingung:")
print("  bwd-Schw. | FP  FN  | condition-stripped erkannt")
for bth in (0.10, 0.20, 0.30, 0.50, 0.70):
    tp, fp, fn, tn, csc, cst = evaluate(bth)
    print(f"     {bth:.2f}   | {fp:2d}  {fn:2d}  |        {csc}/{cst}")
