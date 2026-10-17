"""End-to-end RAG pipeline:

question -> NLU (entities, intent, dialogue context) -> Cypher template
         -> graph retrieval (Neo4j or local replica) -> LLM / template generation
         -> answer + full trace (for the UI and the report).
"""
from __future__ import annotations

import time

from . import llm
from .answers import template_answer
from .graph import get_store
from .nlu import EntityLinker, Plan, plan_question
from .templates import TEMPLATES

_LINKER = None


def linker():
    global _LINKER
    if _LINKER is None:
        movies, people = get_store().entity_names()
        _LINKER = EntityLinker(movies, people)
    return _LINKER


def subgraph(plan: Plan, rows: list[dict]):
    """Nodes/edges to draw the retrieved evidence as a small graph."""
    nodes, edges = {}, []

    def node(name, kind):
        if name:
            nodes.setdefault(name, {"id": name, "kind": kind})

    def edge(a, b, label):
        if a and b:
            edges.append({"from": a, "to": b, "label": label})

    i, p = plan.intent, plan.params
    for r in rows[:25]:
        if i == "movie_info":
            node(r["title"], "movie")
            for c in r.get("cast", []):
                node(c["name"], "person"); edge(c["name"], r["title"], "ACTED_IN")
            for key, rel in (("directors", "DIRECTED"), ("writers", "WROTE"), ("producers", "PRODUCED")):
                for n in r.get(key, []):
                    node(n, "person"); edge(n, r["title"], rel)
        elif i == "movie_cast":
            node(p["title"], "movie"); node(r["actor"], "person"); edge(r["actor"], p["title"], "ACTED_IN")
        elif plan.template == "movie_crew":
            node(p["title"], "movie"); node(r["person"], "person"); edge(r["person"], p["title"], r["relation"])
        elif plan.template == "person_filmography":
            node(p["name"], "person"); node(r["title"], "movie"); edge(p["name"], r["title"], r["relation"])
        elif i == "person_info":
            node(r["name"], "person")
            for key, rel in (("acted_in", "ACTED_IN"), ("directed", "DIRECTED"), ("wrote", "WROTE"), ("produced", "PRODUCED")):
                for t in r.get(key, []):
                    node(t, "movie"); edge(r["name"], t, rel)
        elif i == "co_actors":
            node(p["name"], "person"); node(r["coactor"], "person")
            edge(p["name"], r["coactor"], f"{r['shared']} shared")
        elif i in ("who_played_role", "person_role_in_movie"):
            node(r["actor"], "person"); node(r["title"], "movie"); edge(r["actor"], r["title"], "/".join(r["roles"] or []))
        elif i == "reviews":
            node(p["title"], "movie"); node(r["reviewer"], "person"); edge(r["reviewer"], p["title"], f"REVIEWED {r['rating']}")
        elif i == "recommend":
            seed = p.get("title") or p.get("name")
            node(seed, "movie" if p.get("title") else "person"); node(r["title"], "movie")
            for v in r["via"][:4]:
                node(v, "person"); edge(v, r["title"], ""); edge(v, seed, "")
        elif i == "connection":
            titles = set(linker().movies)
            for n in r["chain"]:
                node(n, "movie" if n in titles else "person")
            for k, rel in enumerate(r["rels"]):
                edge(r["chain"][k], r["chain"][k + 1], rel)
        elif i == "shared_movies":
            node(p["a"], "person"); node(p["b"], "person"); node(r["title"], "movie")
            edge(p["a"], r["title"], r["a_relation"]); edge(p["b"], r["title"], r["b_relation"])
        elif "title" in r:
            node(r["title"], "movie")
        elif "name" in r:
            node(r["name"], "person")
    # de-duplicate edges
    seen, uniq = set(), []
    for e in edges:
        k = (e["from"], e["to"], e["label"])
        if k not in seen:
            seen.add(k); uniq.append(e)
    return {"nodes": list(nodes.values()), "edges": uniq}


def next_context(plan: Plan, rows, context):
    ctx = dict(context or {})
    for e in plan.entities:
        ctx[e.kind] = e.value
    # If every retrieved row points to the same person / movie, it becomes the
    # new focus, so "Who played Neo?" -> "when was he born?" resolves to that actor.
    for col, kind in (("actor", "person"), ("person", "person"), ("coactor", "person"), ("title", "movie")):
        vals = {r.get(col) for r in rows if r.get(col)}
        if len(vals) == 1 and not any(e.kind == kind for e in plan.entities):
            ctx[kind] = vals.pop()
    return ctx


def answer(question: str, context: dict | None = None, use_llm: bool = True) -> dict:
    t0 = time.perf_counter()
    store = get_store()
    plan = plan_question(question, linker(), context)
    trace = {"intent": plan.intent, "template": plan.template, "params": plan.params,
             "entities": [e.__dict__ for e in plan.entities], "note": plan.note,
             "backend": store.backend, "cypher": None, "rows": [], "generator": "template"}
    rows: list[dict] = []
    t_retrieve = time.perf_counter()
    if plan.template:
        trace["cypher"] = TEMPLATES[plan.template]["cypher"]
        rows = store.run(plan.template, plan.params)
    # Open-ended question: let the LLM write Cypher (only against a live Neo4j)
    cfg = llm.config()
    if store.backend == "neo4j" and cfg["enabled"] and plan.intent in ("unknown", "keyword_search") and not rows:
        try:
            cy = llm.text_to_cypher(question)
            rows = store.query(cy)
            plan = Plan("text2cypher", None, {}, plan.entities, "LLM-generated Cypher (read-only checked)")
            trace.update(intent="text2cypher", template="llm_generated", cypher=cy, note=plan.note)
        except Exception as e:  # noqa: BLE001
            trace["note"] = f"Text-to-Cypher failed: {e}"
    retrieve_ms = (time.perf_counter() - t_retrieve) * 1000
    trace["rows"] = rows[:50]

    text = template_answer(plan, rows)
    if use_llm and cfg["enabled"] and (plan.template is not None or plan.intent == "text2cypher"):
        try:
            text = llm.generate_answer(question, plan.intent, rows)
            trace["generator"] = f"llm:{cfg['model']}"
        except Exception as e:  # noqa: BLE001
            trace["note"] = (trace["note"] + " | " if trace["note"] else "") + f"LLM unavailable, used template ({type(e).__name__})"
    trace["timing_ms"] = {"retrieval": round(retrieve_ms, 1), "total": round((time.perf_counter() - t0) * 1000, 1)}
    return {"answer": text, "trace": trace, "graph": subgraph(plan, rows),
            "context": next_context(plan, rows, context)}
