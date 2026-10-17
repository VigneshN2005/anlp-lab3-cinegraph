"""LLM generation layer (OpenAI-compatible chat completions API).

Works with Groq (default), Google Gemini's OpenAI endpoint, OpenRouter, OpenAI
or a local Ollama server - set LLM_BASE_URL / LLM_MODEL / LLM_API_KEY.
If no key is configured, the pipeline uses deterministic template answers.
"""
from __future__ import annotations

import json
import os
import re

import requests

DEFAULT_BASE = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"

SYSTEM_ANSWER = """You are CineGraph, a movie assistant that answers ONLY from the
knowledge-graph records provided (retrieved from a Neo4j movie graph).
Rules:
- Use only facts present in the records. Never add outside knowledge.
- If the records are empty, say you could not find that in the movie graph.
- Mention movie titles and people exactly as written in the records.
- Be concise: 1-4 sentences, or a short bulleted list for long lists.
- For recommendations, briefly say why (shared cast/crew listed in `via`)."""

SYSTEM_CYPHER = """You translate questions into a single READ-ONLY Cypher query for this
Neo4j graph schema:
(:Person {name, born})-[:ACTED_IN {roles: [string]}]->(:Movie {title, released, tagline})
(:Person)-[:DIRECTED|WROTE|PRODUCED]->(:Movie)
(:Person)-[:REVIEWED {rating: int, summary}]->(:Movie)
(:Person)-[:FOLLOWS]->(:Person)
Return only the Cypher query, no explanation, no code fences. Always add LIMIT 25.
Never use CREATE, MERGE, DELETE, SET, REMOVE, DROP, LOAD CSV or CALL."""

WRITE_OPS = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|CALL|FOREACH)\b", re.I)


def config():
    key = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY")
    return {
        "key": key,
        "base": os.getenv("LLM_BASE_URL", DEFAULT_BASE).rstrip("/"),
        "model": os.getenv("LLM_MODEL", DEFAULT_MODEL),
        "enabled": bool(key),
    }


def chat(system: str, user: str, temperature: float = 0.2, max_tokens: int = 400) -> str:
    cfg = config()
    r = requests.post(
        f"{cfg['base']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
        json={"model": cfg["model"], "temperature": temperature, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        timeout=25,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def generate_answer(question: str, intent: str, rows: list[dict]) -> str:
    context = json.dumps(rows[:25], ensure_ascii=False, default=str)
    user = f"Question: {question}\nDetected intent: {intent}\nRetrieved records (JSON):\n{context}\n\nAnswer:"
    text = chat(SYSTEM_ANSWER, user)
    # The UI shows plain text, so drop markdown emphasis the model may add
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def text_to_cypher(question: str) -> str:
    q = chat(SYSTEM_CYPHER, question, temperature=0, max_tokens=300)
    q = re.sub(r"^```(?:cypher)?|```$", "", q.strip(), flags=re.M).strip()
    if WRITE_OPS.search(q):
        raise ValueError("Generated Cypher was not read-only; refused.")
    if not re.search(r"\bLIMIT\b", q, re.I):
        q += "\nLIMIT 25"
    return q
