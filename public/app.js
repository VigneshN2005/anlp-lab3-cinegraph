const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const SUGGESTIONS = [
  "Who directed The Matrix?",
  "Who acted in Apollo 13?",
  "Who played Neo?",
  "Which movies did Tom Hanks act in?",
  "Recommend movies like Top Gun",
  "How is Kevin Bacon connected to Keanu Reeves?",
  "Movies released in the 1990s",
  "Reviews for The Replacements",
  "Which movies have Tom Hanks and Meg Ryan done together?",
  "Top rated movies",
];

let context = {};
let status = null;

/* ---------------- tabs ---------------- */
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
    if (b.dataset.tab === "templates") loadTemplates();
  })
);
const goTab = (name) => document.querySelector(`.tab[data-tab="${name}"]`).click();

/* ---------------- status ---------------- */
async function loadStatus() {
  try {
    status = await (await fetch("/api/status")).json();
    const g = status.graph_backend === "neo4j";
    $("#status").innerHTML =
      `<span class="chip" title="${esc(status.graph_error || status.graph_label)}"><i class="dot ${g ? "on" : "off"}"></i>Graph: <b>${g ? "Neo4j" : "Local replica"}</b></span>` +
      `<span class="chip"><i class="dot ${status.llm_enabled ? "on" : "off"}"></i>LLM: <b>${status.llm_enabled ? esc(status.llm_model) : "template mode"}</b></span>`;
    $("#llmToggleWrap").hidden = !status.llm_enabled;
    $("#evalLlmWrap").hidden = !status.llm_enabled;
    const s = status.schema;
    $("#schemaStats").innerHTML = [
      ...Object.entries(s.nodes).map(([k, v]) => `<div class="stat"><b>${v}</b><span>:${esc(k)} nodes</span></div>`),
      ...Object.entries(s.relationships).map(([k, v]) => `<div class="stat"><b>${v}</b><span>:${esc(k)}</span></div>`),
    ].join("");
  } catch (e) {
    $("#status").innerHTML = `<span class="chip"><i class="dot"></i>API offline</span>`;
  }
}

/* ---------------- chat ---------------- */
function addMsg(role, html, wide = false) {
  const d = document.createElement("div");
  d.className = `msg ${role}`;
  d.innerHTML = `<div class="bubble ${wide ? "wide" : ""}">${html}</div>`;
  $("#chat").appendChild(d);
  d.scrollIntoView({ behavior: "smooth", block: "end" });
  return d;
}

function highlightCypher(c) {
  return esc(c)
    .replace(/\b(MATCH|OPTIONAL|WHERE|RETURN|ORDER BY|LIMIT|AND|OR|NOT|IN|AS|WITH|DESC|IS NULL|DISTINCT|count|collect|avg|any|shortestPath|type|toLower|CONTAINS|coalesce|nodes|relationships|length)\b/g, '<span class="kw">$1</span>')
    .replace(/(\$\w+)/g, '<span class="pm">$1</span>');
}

function rowsTable(rows) {
  if (!rows.length) return '<p class="muted small">No records returned.</p>';
  const cols = Object.keys(rows[0]);
  const fmt = (v) => {
    if (Array.isArray(v)) return v.map((x) => (typeof x === "object" && x ? `${x.name}${x.roles ? " (" + (x.roles || []).join("/") + ")" : ""}` : x)).join(", ");
    if (typeof v === "number" && !Number.isInteger(v)) return v.toFixed(1);
    return v ?? "—";
  };
  return `<div class="table-wrap"><table><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows
    .slice(0, 40)
    .map((r) => `<tr>${cols.map((c) => `<td>${esc(fmt(r[c]))}</td>`).join("")}</tr>`)
    .join("")}</tbody></table></div>`;
}

function drawGraph(el, g) {
  if (!window.drawForceGraph || !g.nodes.length) { el.remove(); return; }
  drawForceGraph(el, g);
  el.insertAdjacentHTML("afterend", '<div class="legend"><span><i style="background:var(--movie)"></i>Movie</span><span><i style="background:var(--person);border-radius:50%"></i>Person</span></div>');
}

function renderAnswer(res) {
  const t = res.trace;
  const ents = t.entities.map((e) => `<span class="tag ${e.kind}" title="${esc(e.method)}">${esc(e.value)}${e.method !== "exact" ? " · " + esc(e.method) : ""}</span>`).join("");
  const params = Object.entries(t.params || {}).map(([k, v]) => `$${k} = ${JSON.stringify(v)}`).join("\n");
  const id = "g" + Math.random().toString(36).slice(2);
  const html = `
    <p class="answer">${esc(res.answer)}</p>
    <div class="meta"><span class="tag intent">${esc(t.intent)}</span>${ents}${t.template ? `<span class="tag">${t.rows.length} record${t.rows.length === 1 ? "" : "s"}</span>` : ""}<span class="tag">${esc(t.generator)}</span></div>
    ${t.template || t.cypher ? `<button class="trace-btn" type="button">Show pipeline ▾</button>
    <div class="trace" hidden>
      <div class="step"><h4><span>1</span>Understand</h4>
        <p class="small">Intent <code>${esc(t.intent)}</code> → template <code>${esc(t.template)}</code>${t.note ? ` · <span class="muted">${esc(t.note)}</span>` : ""}</p></div>
      <div class="step"><h4><span>2</span>Retrieve · ${t.backend === "neo4j" ? "Neo4j" : "local graph replica"} · ${t.timing_ms.retrieval} ms</h4>
        <pre class="cypher">${highlightCypher(t.cypher || "")}${params ? "\n\n// params\n" + esc(params) : ""}</pre></div>
      <div class="step">${rowsTable(t.rows)}</div>
      ${res.graph.nodes.length ? `<div class="step"><h4><span>3</span>Evidence subgraph</h4><div class="graph" id="${id}"></div></div>` : ""}
      <div class="step"><h4><span>4</span>Generate</h4><p class="small">${t.generator.startsWith("llm") ? `LLM <code>${esc(t.generator.slice(4))}</code> wrote the answer from the retrieved records only.` : "Template generator wrote the answer from the retrieved records (no LLM key configured)."} Total ${t.timing_ms.total} ms.</p></div>
    </div>` : ""}`;
  const msg = addMsg("bot", html, true);
  const btn = $(".trace-btn", msg);
  if (btn) {
    let drawn = false;
    btn.addEventListener("click", () => {
      const tr = $(".trace", msg);
      tr.hidden = !tr.hidden;
      btn.textContent = tr.hidden ? "Show pipeline ▾" : "Hide pipeline ▴";
      if (!tr.hidden && !drawn && res.graph.nodes.length) { drawGraph(document.getElementById(id), res.graph); drawn = true; }
    });
  }
}

async function ask(q) {
  if (!q.trim()) return;
  addMsg("user", esc(q));
  $("#q").value = "";
  $("#send").disabled = true;
  const wait = addMsg("bot", '<span class="typing"><i></i><i></i><i></i></span>');
  try {
    const r = await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, context, use_llm: $("#useLlm").checked }),
    });
    const res = await r.json();
    wait.remove();
    if (res.error) { addMsg("bot", `<p class="bad">${esc(res.error)}</p>`); return; }
    context = res.context || {};
    renderAnswer(res);
  } catch (e) {
    wait.remove();
    addMsg("bot", `<p class="bad">Network error: ${esc(e.message)}</p>`);
  } finally {
    $("#send").disabled = false;
  }
}

$("#ask").addEventListener("submit", (e) => { e.preventDefault(); ask($("#q").value); });
$("#reset").addEventListener("click", () => {
  context = {};
  document.querySelectorAll("#chat .msg:not(.intro)").forEach((m) => m.remove());
});
$("#suggest").innerHTML = SUGGESTIONS.map((s) => `<button type="button">${esc(s)}</button>`).join("");
$("#suggest").addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") ask(e.target.textContent); });

/* ---------------- templates ---------------- */
let tplLoaded = false;
async function loadTemplates() {
  if (tplLoaded) return;
  const list = await (await fetch("/api/templates")).json();
  tplLoaded = true;
  $("#tplList").innerHTML = list.map((t) => `
    <article class="tpl">
      <header><b>${esc(t.id)}</b><button type="button" data-q="${esc(t.example)}">Try: “${esc(t.example)}”</button></header>
      <p>${esc(t.description)}</p>
      <pre class="cypher">${highlightCypher(t.cypher)}</pre>
    </article>`).join("");
  $("#tplList").addEventListener("click", (e) => {
    const q = e.target.dataset?.q;
    if (q) { goTab("ask"); ask(q); }
  });
}

/* ---------------- evaluation ---------------- */
$("#runEval").addEventListener("click", async () => {
  const btn = $("#runEval");
  btn.disabled = true; btn.textContent = "Running…";
  try {
    const rep = await (await fetch("/api/eval?llm=" + ($("#evalLlm").checked ? 1 : 0))).json();
    const s = rep.summary;
    const pct = (x) => (x * 100).toFixed(1) + "%";
    $("#evalSummary").innerHTML = [
      ["Intent accuracy", pct(s.intent_accuracy)], ["Entity linking", pct(s.entity_linking_accuracy)],
      ["Retrieval recall", pct(s.retrieval_recall)], ["Answer accuracy", pct(s.answer_accuracy)],
      ["Answer coverage", pct(s.answer_coverage)], ["Hallucination rate", pct(s.hallucination_rate)],
    ].map(([k, v]) => `<div class="metric"><b>${v}</b><span>${k}</span></div>`).join("") +
      `<p class="muted small" style="grid-column:1/-1;margin:4px 0 0">${s.questions} questions · generator: ${esc(s.generator)}</p>`;
    $("#evalTable").innerHTML = `<div class="card"><div class="table-wrap" style="max-height:none"><table><thead><tr><th>#</th><th>Question</th><th>Type</th><th>Gold intent</th><th>Predicted</th><th>Recall</th><th>Result</th></tr></thead><tbody>${rep.results
      .map((r, i) => `<tr><td>${i + 1}</td><td>${esc(r.question)}</td><td>${esc(r.tag || "direct")}</td><td><code>${esc(r.gold_intent)}</code></td><td><code>${esc(r.pred_intent)}</code></td><td>${r.retrieval_recall}</td><td class="${r.correct && r.intent_ok ? "ok" : "bad"}">${r.correct && r.intent_ok ? "✔" : "✘"}</td></tr>`)
      .join("")}</tbody></table></div></div>`;
  } finally {
    btn.disabled = false; btn.textContent = "Run evaluation";
  }
});

loadStatus();
