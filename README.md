# CineGraph: RAG over the Neo4j Movies Knowledge Graph

**AML23702 Advanced NLP · Lab Exercise 3**
Vignesh N · 1GA23AI056 · Dept. of AI & ML, Global Academy of Technology

A small Retrieval-Augmented Generation (RAG) application. It uses the **Neo4j Movies dataset** as a knowledge-graph backend, converts user questions into **Cypher queries**, retrieves the relevant movie, actor and director records, and uses an **LLM** to write grounded natural-language answers. It also supports movie recommendations and multi-turn follow-ups ("who directed it?").

```
question ─► entity linking + intent ─► Cypher template ─► Neo4j ─► records ─► LLM (grounded) ─► answer
              (dialogue context)        (17 templates)     (or local replica)     (or template NLG)
```

## Features
- **17 parameterised, read-only Cypher templates**: cast, crew, filmography, roles, co-actors, reviews, top rated, recommendations, shortest path ("degrees of separation"), movies by year, and more.
- **Entity linking** with typo tolerance ("keanu reves"), partial names ("Nicholson") and titles without the leading article ("matrix").
- **Dialogue state:** pronouns ("it", "she") resolve to the previous turn's movie or person.
- **Grounded generation:** the LLM only sees the retrieved records. A template generator is used when no API key is set.
- **Text-to-Cypher fallback:** for open questions, the LLM writes Cypher, which is checked to be read-only before it runs (live Neo4j only).
- **Transparent UI:** every answer can be expanded to show the intent, the Cypher and its parameters, the retrieved rows, and an evidence subgraph.
- **Built-in evaluation:** 38 labelled questions, scored on intent accuracy, entity linking, retrieval recall, answer accuracy and hallucination rate.
- **Runs without credentials:** if Neo4j is not configured, an identical in-memory replica of the Movies graph (`data/movies.json`, generated from the official Cypher script) is used.

## Project structure
```
api/index.py                 Flask API (Vercel serverless entry + local server)
core/templates.py            Cypher query templates
core/graph.py                Neo4jStore (driver) + LocalGraphStore (offline replica)
core/nlu.py                  entity linking, coreference, intent rules -> query plan
core/llm.py                  OpenAI-compatible LLM client (answer generation, text-to-Cypher)
core/answers.py              template-based answer generation (fallback)
core/rag.py                  end-to-end pipeline + evidence subgraph
core/evaluation.py           evaluation metrics
data/movies.cypher           official Neo4j Movies dataset (neo4j-graph-examples/movies)
data/movies.json             JSON replica (scripts/cypher_to_json.py)
data/eval_questions.json     labelled evaluation questions
scripts/load_movies_to_neo4j.py   loads the dataset into your Neo4j / AuraDB
public/                      frontend (HTML/CSS/JS, no build step, self-hosted fonts)
```

## Run locally
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python api/index.py              # open http://localhost:5000
```
This works immediately in offline mode (local graph replica + template answers).

Run the evaluation from the command line:
```bash
python -m core.evaluation
```

## Connect Neo4j AuraDB (the knowledge-graph backend)
1. Create a free instance at <https://console.neo4j.io> (AuraDB Free) and save the generated password.
2. Copy `.env.example` to `.env` and fill in `NEO4J_URI`, `NEO4J_USERNAME` and `NEO4J_PASSWORD`.
3. Load the dataset with `python scripts/load_movies_to_neo4j.py`. It should report 38 movies, 133 people and 253 relationships. Alternatively, run `:play movies` in Neo4j Browser.
4. Restart the app. The header chip will show **Graph: Neo4j**.

## Connect an LLM
Set `LLM_API_KEY` in `.env`. The default is **Groq** (free key at <https://console.groq.com>) with `llama-3.3-70b-versatile`. Any OpenAI-compatible endpoint works by setting `LLM_BASE_URL` and `LLM_MODEL`:

| Provider | LLM_BASE_URL | example LLM_MODEL |
|---|---|---|
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.0-flash` |
| OpenRouter | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.3-70b-instruct` |

## Deploy on Vercel
1. Push this folder to a GitHub repository.
2. On <https://vercel.com>, choose **Add New → Project**, import the repo, and keep Framework Preset = **Other**. No build command is needed.
3. Under **Settings → Environment Variables**, add `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `LLM_API_KEY` (plus `LLM_MODEL` if needed), then redeploy.
4. Open the `*.vercel.app` URL on any phone or laptop.

`vercel.json` routes `/api/*` to the Flask function, and `public/` is served as static files.

## API
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/status` | graph backend, LLM status, schema counts |
| POST | `/api/ask` | `{question, context, use_llm}` → `{answer, trace, graph, context}` |
| GET | `/api/templates` | all Cypher templates |
| GET | `/api/eval?llm=0\|1` | run the evaluation set |

## Dataset credit
Neo4j Movies example graph: <https://github.com/neo4j-graph-examples/movies> (Apache-2.0).
