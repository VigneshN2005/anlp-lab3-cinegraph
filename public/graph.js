/* Tiny dependency-free force-directed graph renderer (SVG).
   drawForceGraph(container, {nodes:[{id,kind}], edges:[{from,to,label}]}) */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };

  function layout(nodes, edges, W, H) {
    const n = nodes.length;
    const idx = new Map(nodes.map((d, i) => [d.id, i]));
    // deterministic start on a circle
    nodes.forEach((d, i) => {
      const a = (2 * Math.PI * i) / n;
      d.x = W / 2 + (W / 3) * Math.cos(a);
      d.y = H / 2 + (H / 3) * Math.sin(a);
    });
    const links = edges.map((e) => [idx.get(e.from), idx.get(e.to)]).filter(([a, b]) => a != null && b != null);
    const k = Math.sqrt((W * H) / Math.max(n, 1)) * 0.75;
    let temp = W / 6;
    for (let it = 0; it < 300; it++) {
      const dx = new Float64Array(n), dy = new Float64Array(n);
      for (let i = 0; i < n; i++)
        for (let j = i + 1; j < n; j++) {
          let x = nodes[i].x - nodes[j].x, y = nodes[i].y - nodes[j].y;
          let d = Math.hypot(x, y) || 0.01;
          const f = (k * k) / d;
          dx[i] += (x / d) * f; dy[i] += (y / d) * f;
          dx[j] -= (x / d) * f; dy[j] -= (y / d) * f;
        }
      for (const [a, b] of links) {
        let x = nodes[a].x - nodes[b].x, y = nodes[a].y - nodes[b].y;
        let d = Math.hypot(x, y) || 0.01;
        const f = (d * d) / k;
        dx[a] -= (x / d) * f; dy[a] -= (y / d) * f;
        dx[b] += (x / d) * f; dy[b] += (y / d) * f;
      }
      for (let i = 0; i < n; i++) {
        // gravity to centre keeps disconnected pieces on screen
        dx[i] += (W / 2 - nodes[i].x) * 0.02 * k / 10;
        dy[i] += (H / 2 - nodes[i].y) * 0.02 * k / 10;
        const d = Math.hypot(dx[i], dy[i]) || 0.01;
        nodes[i].x += (dx[i] / d) * Math.min(d, temp);
        nodes[i].y += (dy[i] / d) * Math.min(d, temp);
      }
      temp *= 0.985;
    }
    return links;
  }

  window.drawForceGraph = function (container, g) {
    const W = 640, H = 380;
    const nodes = g.nodes.map((d) => ({ ...d }));
    const edges = g.edges;
    layout(nodes, edges, W, H);
    // fit to viewBox with padding for labels
    const xs = nodes.map((d) => d.x), ys = nodes.map((d) => d.y);
    const pad = 70;
    const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
    const minY = Math.min(...ys) - 30, maxY = Math.max(...ys) + 30;
    const svg = el("svg", { viewBox: `${minX} ${minY} ${maxX - minX} ${maxY - minY}`, class: "fg", role: "img",
      "aria-label": "Retrieved evidence subgraph" });
    const defs = el("defs", {}, svg);
    const m = el("marker", { id: "fgArrow" + Math.random().toString(36).slice(2, 7), viewBox: "0 0 10 10", refX: "10", refY: "5",
      markerWidth: "6", markerHeight: "6", orient: "auto" }, defs);
    el("path", { d: "M0 0 10 5 0 10z", class: "fg-arrow" }, m);
    const byId = new Map(nodes.map((d) => [d.id, d]));
    const gE = el("g", {}, svg), gL = el("g", {}, svg), gN = el("g", {}, svg);
    for (const e of edges) {
      const a = byId.get(e.from), b = byId.get(e.to);
      if (!a || !b) continue;
      // shorten line so the arrow stops at the node edge
      const d = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const r = b.kind === "movie" ? 20 : 11;
      const x2 = b.x - ((b.x - a.x) / d) * r, y2 = b.y - ((b.y - a.y) / d) * r;
      const attrs = { x1: a.x, y1: a.y, x2, y2, class: "fg-edge" };
      if (e.label && !/shared/.test(e.label)) attrs["marker-end"] = `url(#${m.id})`;
      el("line", attrs, gE);
      if (e.label) {
        const t = el("text", { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 3, class: "fg-elabel" }, gL);
        t.textContent = e.label.length > 22 ? e.label.slice(0, 21) + "…" : e.label;
      }
    }
    for (const d of nodes) {
      const grp = el("g", { transform: `translate(${d.x},${d.y})` }, gN);
      const label = d.id.length > 26 ? d.id.slice(0, 25) + "…" : d.id;
      if (d.kind === "movie") {
        const w = Math.max(60, label.length * 6.6 + 18);
        el("rect", { x: -w / 2, y: -13, width: w, height: 26, rx: 7, class: "fg-movie" }, grp);
        const t = el("text", { y: 4, class: "fg-mlabel" }, grp);
        t.textContent = label;
      } else {
        el("circle", { r: 9, class: "fg-person" }, grp);
        const t = el("text", { y: 24, class: "fg-plabel" }, grp);
        t.textContent = label;
      }
      const title = el("title", {}, grp);
      title.textContent = `${d.kind}: ${d.id}`;
    }
    container.innerHTML = "";
    container.appendChild(svg);
  };
})();
