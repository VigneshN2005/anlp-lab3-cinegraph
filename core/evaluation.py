"""Evaluation of the RAG pipeline on data/eval_questions.json.

Metrics
* Intent accuracy           - predicted intent == gold intent
* Entity-linking accuracy   - set of linked entities == gold entities
* Retrieval recall          - share of gold answer strings found in the retrieved rows
* Answer accuracy           - question counts as correct if retrieval recall == 1
                              (out-of-graph questions are correct if nothing is retrieved)
* Answer coverage           - share of gold strings mentioned in the generated answer
* Hallucination rate        - share of answers that mention a graph entity that was
                              neither in the question nor in the retrieved records
"""
from __future__ import annotations

import json
import pathlib

from .rag import answer, linker

EVAL = pathlib.Path(__file__).resolve().parent.parent / "data" / "eval_questions.json"


def flat(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str).lower()


def run_eval(use_llm: bool = True) -> dict:
    items = json.loads(EVAL.read_text(encoding="utf-8"))
    L = linker()
    results = []
    for it in items:
        out = answer(it["q"], it.get("context"), use_llm=use_llm)
        tr = out["trace"]
        retrieved = flat(tr["rows"])
        gold = it["gold"]
        rec = sum(g.lower() in retrieved for g in gold) / len(gold) if gold else (1.0 if not tr["rows"] else 0.0)
        cov = sum(g.lower() in out["answer"].lower() for g in gold) / len(gold) if gold else 1.0
        linked = sorted({e["value"] for e in tr["entities"]})
        pred_intent = tr["intent"]
        gold_intent = it["intent"]
        intent_ok = pred_intent == gold_intent or (gold_intent == "unknown_entity" and not tr["rows"])
        allowed = L.mentions(it["q"]) | L.mentions(json.dumps(tr["rows"], default=str)) | set(linked)
        extra = sorted(L.mentions(out["answer"]) - allowed)
        results.append({
            "question": it["q"], "tag": it.get("tag", ""), "gold_intent": gold_intent,
            "pred_intent": pred_intent, "intent_ok": intent_ok,
            "entities_ok": linked == sorted(it["entities"]),
            "retrieval_recall": round(rec, 3), "correct": rec == 1.0,
            "answer_coverage": round(cov, 3), "hallucinated": extra,
            "answer": out["answer"], "generator": tr["generator"],
        })
    n = len(results)
    mean = lambda k: round(sum(float(r[k]) for r in results) / n, 3)
    summary = {
        "questions": n,
        "intent_accuracy": mean("intent_ok"),
        "entity_linking_accuracy": mean("entities_ok"),
        "retrieval_recall": mean("retrieval_recall"),
        "answer_accuracy": mean("correct"),
        "answer_coverage": mean("answer_coverage"),
        "hallucination_rate": round(sum(bool(r["hallucinated"]) for r in results) / n, 3),
        "generator": results[0]["generator"] if results else "",
    }
    return {"summary": summary, "results": results}


if __name__ == "__main__":
    rep = run_eval()
    print(json.dumps(rep["summary"], indent=2))
    for r in rep["results"]:
        flag = "OK " if r["correct"] and r["intent_ok"] else "XX "
        print(flag, r["question"], "|", r["pred_intent"], "| recall", r["retrieval_recall"], "| cov", r["answer_coverage"], r["hallucinated"] or "")
