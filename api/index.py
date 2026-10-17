"""Flask API for CineGraph (Vercel serverless entry point and local dev server).

Local:   python api/index.py      -> http://localhost:5000
Vercel:  vercel.json rewrites /api/* to this file; static UI is served from public/.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Minimal .env loader for local runs (Vercel injects env vars itself)
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

from core import llm  # noqa: E402
from core.evaluation import run_eval  # noqa: E402
from core.graph import get_store, store_error  # noqa: E402
from core.rag import answer  # noqa: E402
from core.templates import TEMPLATES  # noqa: E402

app = Flask(__name__, static_folder=str(ROOT / "public"), static_url_path="")


class VercelPathFix:
    """Vercel's rewrite (/api/(.*) -> /api/index.py?__route=$1) hands Flask the
    internal path. Restore the original /api/<route> so the normal Flask routes
    match. Requests that already carry the real path pass through unchanged."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        from urllib.parse import parse_qsl, urlencode
        qs = parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        route = next((v for k, v in qs if k == "__route"), None)
        if route is not None:
            environ["PATH_INFO"] = "/api/" + route.lstrip("/")
            environ["QUERY_STRING"] = urlencode([(k, v) for k, v in qs if k != "__route"])
        return self.wsgi_app(environ, start_response)


app.wsgi_app = VercelPathFix(app.wsgi_app)
_EVAL_CACHE = {}


@app.get("/api/status")
def status():
    store = get_store()
    cfg = llm.config()
    return jsonify({
        "graph_backend": store.backend,
        "graph_label": store.label,
        "graph_error": store_error(),
        "llm_enabled": cfg["enabled"],
        "llm_model": cfg["model"] if cfg["enabled"] else None,
        "schema": store.schema(),
    })


@app.post("/api/ask")
def ask():
    body = request.get_json(silent=True) or {}
    q = (body.get("question") or "").strip()
    if not q:
        return jsonify({"error": "Empty question"}), 400
    if len(q) > 500:
        return jsonify({"error": "Question too long (max 500 characters)"}), 400
    try:
        return jsonify(answer(q, body.get("context") or {}, use_llm=body.get("use_llm", True)))
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/templates")
def templates():
    return jsonify([{"id": k, **v} for k, v in TEMPLATES.items()])


@app.get("/api/eval")
def evaluate():
    use_llm = request.args.get("llm", "0") == "1"
    if use_llm not in _EVAL_CACHE:
        _EVAL_CACHE[use_llm] = run_eval(use_llm=use_llm)
    return jsonify(_EVAL_CACHE[use_llm])


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
