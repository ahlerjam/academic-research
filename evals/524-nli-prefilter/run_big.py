"""A/B auf dem erweiterten Set: mDeBERTa vs. bge-m3-zeroshot.

Praemissen sind echte OpenAlex-Abstract-Ausschnitte (picks.json), die Faelle
referenzieren sie ueber 'pick'. Zusaetzlich laufen die beiden Bestandssets
aus #524 mit, damit die Gesamtzahl vergleichbar bleibt.
"""

import json
import time
from pathlib import Path

S = Path(__file__).resolve().parent
REPO = S.parent.parent
MODELS = {
    "mdeberta-xnli": "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
    "bge-m3-zeroshot": "MoritzLaurer/bge-m3-zeroshot-v2.0",
}

picks = json.loads((S / "picks.json").read_text(encoding="utf-8"))
flat = []
for p in picks:
    for pk in p["picks"]:
        flat.append({**pk, "field": p["field"], "title": p["title"]})


def premise_for(idx):
    pk = flat[idx - 1]
    parts = [pk["context_before"], pk["sentence"], pk["context_after"]]
    return " ".join(x.strip() for x in parts if x and x.strip())


items = []
for fname in ("set_med.json", "set_soz.json"):
    for c in json.loads((S / fname).read_text(encoding="utf-8"))["cases"]:
        items.append(
            {
                "id": c["id"],
                "set": "neu",
                "field": flat[c["pick"] - 1]["field"],
                "premise": premise_for(c["pick"]),
                "claim": c["claim"],
                "label": c["label"],
                "type": c["type"],
            }
        )

for fname, tag in (("cases.json", "alt-konstruiert"), ("real-cases.json", "alt-real")):
    for c in json.loads((REPO / "evals/524-nli-prefilter" / fname).read_text(encoding="utf-8"))[
        "cases"
    ]:
        prem = " ".join(
            x.strip()
            for x in [c.get("context_before") or "", c["verbatim"], c.get("context_after") or ""]
            if x and x.strip()
        )
        items.append(
            {
                "id": c["id"],
                "set": tag,
                "field": "ml-nlp",
                "premise": prem,
                "claim": c["chapter_claim"],
                "label": c["label"],
                "type": c.get("verzerrend_type"),
            }
        )

assert all(i["label"] in ("faithful", "verzerrend") for i in items), "Ungueltiges Label"
print(
    f"{len(items)} Faelle | neu={sum(1 for i in items if i['set'] == 'neu')} "
    f"| faithful={sum(1 for i in items if i['label'] == 'faithful')} "
    f"| verzerrend={sum(1 for i in items if i['label'] == 'verzerrend')}",
    flush=True,
)


class Scorer:
    def __init__(self, model_id):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_id)
        self.model.eval()
        self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}
        self.ent_idx = next(
            (i for i, lab in self.id2label.items() if lab.lower().startswith("entail")), 0
        )

    def score(self, premise, hypothesis):
        import torch

        inp = self.tok(premise, hypothesis, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            logits = self.model(**inp).logits[0]
        probs = torch.softmax(logits, dim=-1).tolist()
        return float(probs[self.ent_idx]), max(range(len(probs)), key=lambda i: probs[i])


results = {}
for name, mid in MODELS.items():
    print(f"\n### {name}", flush=True)
    sc = Scorer(mid)
    print(f"  id2label={sc.id2label} ent_idx={sc.ent_idx}", flush=True)
    rows, t0 = [], time.monotonic()
    for k, it in enumerate(items):
        ent, argmax = sc.score(it["premise"], it["claim"])
        rows.append(
            {
                **{x: it[x] for x in ("id", "set", "field", "label", "type")},
                "ent": ent,
                "is_ent_argmax": argmax == sc.ent_idx,
            }
        )
        if (k + 1) % 60 == 0:
            print(f"  {k + 1}/{len(items)}", flush=True)
    total_s = time.monotonic() - t0
    results[name] = {"rows": rows, "total_s": total_s}
    print(
        f"  fertig in {total_s:.0f}s ({total_s / len(items) * 1000:.0f} ms/Fall)",
        flush=True,
    )

(S / "big_results.json").write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
print("\nRohdaten: big_results.json")
