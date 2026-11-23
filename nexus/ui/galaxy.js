"use strict";
// Brain-galaxy views (Galaxy, Neural, Clusters, Voids). Every star is a stored entry and every
// line a stored relation; animations are triggered only by events read from the store's log.
// Uses helpers from app.js: h, fill, api, setView, tip, toast, short, kindChip, status, showNode, loading, errorBox.

// Categorical colours: 3 families, validated with the dataviz validator (--pairs all, dark, #070b14).
const FAMILY = { capability: "#3987e5", memory: "#c98500", project: "#d55181" };
const FAMILY_LABEL = { capability: "What it can do (skills, tools, plugins)", memory: "What it learned (experiences, decisions, knowledge)", project: "Projects" };
const MEMORY = new Set(["experience", "decision", "knowledge"]);
const familyOf = (k) => (k === "project" ? "project" : MEMORY.has(k) ? "memory" : "capability");
const clusterKey = (n) => familyOf(n.kind) === "capability" ? `cap:${n.origin || "user"}` : `proj:${n.project || "general"}`;
const clusterName = (key) => key.replace(/^cap:/, "").replace(/^proj:/, "") + (key.startsWith("cap:") ? " · capabilities" : "");
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const params = () => Object.fromEntries(new URLSearchParams((location.hash.split("?")[1] || "")));

function hash(s) { let x = 2166136261; for (const c of s) x = Math.imul(x ^ c.charCodeAt(0), 16777619); return x >>> 0; }
function rng(seed) { return () => { seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const gauss = (r) => Math.sqrt(-2 * Math.log(r() + 1e-9)) * Math.cos(2 * Math.PI * r());

let graphCache = null;
async function loadGraph(force) {
  if (!graphCache || force) {
    const g = await api("/api/graph");
    const adj = new Map(g.nodes.map((n) => [n.id, []]));
    for (const e of g.edges) { adj.get(e.src)?.push([e.dst, e, "out"]); adj.get(e.dst)?.push([e.src, e, "in"]); }
    graphCache = { ...g, byId: new Map(g.nodes.map((n) => [n.id, n])), adj };
  }
  return graphCache;
}

// ---------- layout: two hemispheres, clusters on the cortex, members around their cluster ----------
const HEMI = { r: [0.46, 0.58, 0.86], gap: 0.52 };
function layout(nodes) {
  const groups = new Map();
  for (const n of nodes) { const k = clusterKey(n); (groups.get(k) || groups.set(k, []).get(k)).push(n); }
  const pos = new Map(), centers = new Map();
  for (const [key, members] of groups) {
    const side = key.startsWith("cap:") ? -1 : 1, r = rng(hash(key));
    let d = [Math.abs(gauss(r)) + 0.6, gauss(r) * 0.9, gauss(r) * 1.1];
    const len = Math.hypot(...d); d = d.map((v) => v / len);
    const c = [side * (HEMI.gap + d[0] * HEMI.r[0] * 0.8), d[1] * HEMI.r[1] * 0.8, d[2] * HEMI.r[2] * 0.8];
    centers.set(key, c);
    const spread = Math.min(0.2, 0.035 + Math.sqrt(members.length) * 0.022);
    for (const n of members) {
      if (n.kind === "project" || n.kind === "plugin") { pos.set(n.id, c); continue; }  // hub sits at the centre
      const q = rng(hash(n.id));
      pos.set(n.id, [c[0] + gauss(q) * spread * 0.7, c[1] + gauss(q) * spread, c[2] + gauss(q) * spread]);
    }
  }
  return { pos, centers, groups };
}

// one glow sprite per colour, drawn once
const sprites = new Map();
function sprite(color) {
  if (sprites.has(color)) return sprites.get(color);
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"), grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "#ffffff"); grad.addColorStop(0.18, color); grad.addColorStop(0.45, color + "55"); grad.addColorStop(1, color + "00");
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  sprites.set(color, c); return c;
}

// ---------- Galaxy view ----------
views.galaxy = async () => {
  setView(loading());
  const g = await loadGraph(true);
  $view.classList.add("bleed");
  const canvas = h("canvas.galaxy", { role: "img", tabindex: 0, "aria-label":
    `Galaxy of ${g.nodes.length} entries and ${g.edges.length} relations. Arrow keys rotate, plus and minus zoom. ` +
    "The same entries are listed as text in Capabilities, Memory, Projects and Voids." });
  const search = h("input", { type: "search", placeholder: "Find a star", "aria-label": "Highlight entries by name" });
  const rotateBtn = h("button.btn.ghost.small", { type: "button", "aria-pressed": String(!reduceMotion) }, "Rotate");
  const voidSel = h("select", { "aria-label": "Highlight weak zones" }, h("option", { value: "" }, "Weak zones: off"));
  const side = h("aside.galaxy-side", { hidden: true });
  const ticker = h("div.ticker", { "aria-live": "polite" }, "Live: waiting for NEXUS operations…");
  const legend = h("div.legend", {}, Object.entries(FAMILY).map(([f, c]) => {
    const dot = h("span.swatch"); dot.style.background = c;
    return h("div.row", {}, dot, FAMILY_LABEL[f]);
  }), h("div.small.muted", {}, "◯ plugin   ◇ MCP server   ● other   ring = new in last 24 h"));
  setView(h("div.galaxy-wrap", {}, canvas,
    h("div.galaxy-top", {}, h("div", {}, h("h1", {}, "Galaxy"), h("p.muted.small", {},
      `${g.nodes.length} stars · ${g.edges.length} relations · left: abilities, right: knowledge`)),
      h("div.row", {}, search, voidSel, rotateBtn)),
    legend, side, ticker));
  api("/api/voids").then((vs) => { for (const v of vs) if (v.items.length) voidSel.append(h("option", { value: v.key }, `${v.label} (${v.items.length})`));
    voidSel.voids = vs; if (params().voids) { voidSel.value = params().voids; voidSel.dispatchEvent(new Event("input")); } });

  const ctx = canvas.getContext("2d");
  let L = layout(g.nodes), W = 0, H = 0, dpr = 1;
  const cam = { yaw: -0.5, pitch: 0.18, zoom: 1, auto: !reduceMotion };
  let hover = null, selected = null, highlight = null, lastMove = 0, proj = [];
  const births = new Map(), flares = new Map(), pulses = [], ringsAt = [];
  const now = () => performance.now();

  const resize = () => {
    dpr = devicePixelRatio || 1; W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  const project = ([x, y, z]) => {
    const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
    const x1 = x * cy - z * sy, z1 = x * sy + z * cy, y1 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
    const s = 2.8 / (2.8 + z2), k = Math.min(W, H) * 0.36 * cam.zoom;
    return [W / 2 + x1 * s * k, H / 2 - y1 * s * k, z2, s];
  };

  function outline() {  // faint cortex: latitude and meridian rings of each hemisphere
    ctx.lineWidth = 1; ctx.strokeStyle = "rgba(120, 160, 230, 0.11)";
    for (const side of [-1, 1]) {
      const c = [side * HEMI.gap, 0, 0];
      for (let i = 1; i < 6; i++) {
        const lat = -Math.PI / 2 + (i * Math.PI) / 6;
        ctx.beginPath();
        for (let j = 0; j <= 48; j++) {
          const lon = (j / 48) * 2 * Math.PI;
          const p = project([c[0] + HEMI.r[0] * Math.cos(lat) * Math.cos(lon), c[1] + HEMI.r[1] * Math.sin(lat), c[2] + HEMI.r[2] * Math.cos(lat) * Math.sin(lon)]);
          j ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
        }
        ctx.stroke();
      }
      for (let j = 0; j < 6; j++) {
        const lon = (j / 6) * Math.PI; ctx.beginPath();
        for (let i = 0; i <= 32; i++) {
          const lat = -Math.PI / 2 + (i / 32) * Math.PI;
          const p = project([c[0] + HEMI.r[0] * Math.cos(lat) * Math.cos(lon), c[1] + HEMI.r[1] * Math.sin(lat), c[2] + HEMI.r[2] * Math.cos(lat) * Math.sin(lon)]);
          i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
        }
        ctx.stroke();
      }
    }
  }

  function draw(t) {
    ctx.clearRect(0, 0, W, H);
    outline();
    const P = new Map(g.nodes.map((n) => [n.id, project(L.pos.get(n.id))]));
    const focus = selected || hover;
    // relations
    for (const e of g.edges) {
      const a = P.get(e.src), b = P.get(e.dst); if (!a || !b) continue;
      const on = focus && (e.src === focus.id || e.dst === focus.id);
      const dim = highlight && !(highlight.has(e.src) && highlight.has(e.dst));
      ctx.strokeStyle = on ? "rgba(56, 189, 248, 0.75)" : `rgba(170, 190, 230, ${dim ? 0.015 : e.type === "belongs_to" ? 0.05 : 0.14})`;
      ctx.lineWidth = on ? 1.4 : 1;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    }
    // core
    const core = project([0, 0, 0]), cs = 26 * core[3] * cam.zoom;
    ctx.globalAlpha = 0.9; ctx.drawImage(sprite("#7dd3fc"), core[0] - cs, core[1] - cs, cs * 2, cs * 2); ctx.globalAlpha = 1;
    for (let i = ringsAt.length - 1; i >= 0; i--) {  // core ring = a real wake/route event
      const k = (t - ringsAt[i]) / 1600; if (k > 1) { ringsAt.splice(i, 1); continue; }
      ctx.strokeStyle = `rgba(125, 211, 252, ${0.6 * (1 - k)})`; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(core[0], core[1], cs * (0.4 + k * 2.2), 0, 7); ctx.stroke();
    }
    // stars, far to near
    proj = g.nodes.map((n) => [n, P.get(n.id)]).sort((a, b) => b[1][2] - a[1][2]);
    const day = Date.now() - 864e5;
    for (const [n, p] of proj) {
      const fam = familyOf(n.kind), color = FAMILY[fam];
      const born = births.get(n.id), grow = born ? Math.min(1, (t - born) / 1400) : 1;
      const fl = flares.get(n.id), flare = fl ? Math.max(0, 1 - (t - fl) / 2200) : 0;
      let size = (n.kind === "project" || n.kind === "plugin" ? 7 : MEMORY.has(n.kind) ? 5 : 4) * (1 + Math.log1p(n.uses) * 0.3);
      size *= p[3] * cam.zoom * grow * (1 + flare * 1.6);
      const depth = Math.max(0.35, Math.min(1, 1.1 - p[2] * 0.6));
      const dim = highlight && !highlight.has(n.id);
      ctx.globalAlpha = dim ? 0.08 : depth;
      const glow = size * 3.2;
      ctx.drawImage(sprite(color), p[0] - glow, p[1] - glow, glow * 2, glow * 2);
      ctx.globalAlpha = dim ? 0.15 : 1;
      ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1.3;
      if (n.kind === "plugin") { ctx.beginPath(); ctx.arc(p[0], p[1], size, 0, 7); ctx.stroke(); }
      else if (n.kind === "mcp_server") { ctx.beginPath(); ctx.moveTo(p[0], p[1] - size); ctx.lineTo(p[0] + size, p[1]); ctx.lineTo(p[0], p[1] + size); ctx.lineTo(p[0] - size, p[1]); ctx.closePath(); ctx.fill(); }
      else { ctx.beginPath(); ctx.arc(p[0], p[1], Math.max(1.2, size * 0.45), 0, 7); ctx.fill(); }
      if (n.status === "stale") { ctx.setLineDash([2, 2]); ctx.strokeStyle = "#fbbf24"; ctx.beginPath(); ctx.arc(p[0], p[1], size + 3, 0, 7); ctx.stroke(); ctx.setLineDash([]); }
      if (n.created && Date.parse(n.created) > day && !dim) { ctx.strokeStyle = "rgba(255,255,255,0.22)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(p[0], p[1], size + 4, 0, 7); ctx.stroke(); }
      if (focus && n.id === focus.id) { ctx.strokeStyle = "#e8edf7"; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(p[0], p[1], size + 7, 0, 7); ctx.stroke(); }
      ctx.globalAlpha = 1;
    }
    // labels: projects and plugins on the near side, plus the focused star
    ctx.font = "12px Inter, Segoe UI, system-ui, sans-serif"; ctx.textAlign = "center";
    const boxes = [];  // nearest first; a label that would overlap an already placed one is skipped
    const cands = [...proj].reverse().filter(([n, p]) => (focus && n.id === focus.id) || ((n.kind === "project" || n.kind === "plugin") && p[2] < 0.15 && !highlight));
    if (focus) cands.sort(([a], [b]) => (b.id === focus.id) - (a.id === focus.id));
    for (const [n, p] of cands) {
      const text = n.title.length > 34 ? n.title.slice(0, 33) + "…" : n.title, w = ctx.measureText(text).width, y = p[1] - 12 * p[3] * cam.zoom - 6;
      const box = [p[0] - w / 2 - 4, y - 12, p[0] + w / 2 + 4, y + 3];
      if (boxes.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue;
      boxes.push(box);
      ctx.fillStyle = focus && n.id === focus.id ? "#e8edf7" : "rgba(169, 180, 201, 0.85)";
      ctx.fillText(text, p[0], y);
    }
    // pulses: core -> selected entry, one per real routing pick
    for (let i = pulses.length - 1; i >= 0; i--) {
      const pu = pulses[i], k = (t - pu.t0) / 1300;
      if (k > 1) { flares.set(pu.id, t); pulses.splice(i, 1); continue; }
      if (k < 0) continue;
      const b = P.get(pu.id); if (!b) { pulses.splice(i, 1); continue; }
      const e = 1 - Math.pow(1 - k, 3), x = core[0] + (b[0] - core[0]) * e, y = core[1] + (b[1] - core[1]) * e;
      ctx.strokeStyle = "rgba(56, 189, 248, 0.35)"; ctx.beginPath(); ctx.moveTo(core[0], core[1]); ctx.lineTo(x, y); ctx.stroke();
      ctx.drawImage(sprite("#38bdf8"), x - 10, y - 10, 20, 20);
    }
  }

  let raf = 0, last = now();
  const loop = (t) => {
    if (cam.auto && t - lastMove > 2500) cam.yaw += (t - last) * 0.00005;
    last = t; draw(t); raf = requestAnimationFrame(loop);
  };

  // interaction
  let drag = null;
  canvas.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY, cam.yaw, cam.pitch, false]; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    if (drag) {
      const dx = e.clientX - drag[0], dy = e.clientY - drag[1];
      if (Math.abs(dx) + Math.abs(dy) > 3) drag[4] = true;
      cam.yaw = drag[2] + dx * 0.006; cam.pitch = Math.max(-1.2, Math.min(1.2, drag[3] + dy * 0.006)); lastMove = now();
      if (reduceMotion) draw(now());
      return;
    }
    let best = null, bd = 144;
    for (const [n, p] of proj) { const d = (p[0] - mx) ** 2 + (p[1] - my) ** 2; if (d < bd) { bd = d; best = n; } }
    hover = best; canvas.style.cursor = best ? "pointer" : "grab";
    if (best) {
      $tip.hidden = false; fill($tip, h("div", {}, best.title), h("div.muted", {}, `${best.kind.replace("_", " ")} · ${best.status}${best.project ? " · " + best.project : ""}`));
      $tip.style.left = e.clientX + 14 + "px"; $tip.style.top = e.clientY + 14 + "px";
    } else $tip.hidden = true;
    if (reduceMotion) draw(now());
  });
  canvas.addEventListener("pointerleave", () => { hover = null; $tip.hidden = true; });
  canvas.addEventListener("pointerup", () => { if (drag && !drag[4]) select(hover); drag = null; });
  canvas.addEventListener("dblclick", () => hover && (location.hash = `#/neural?id=${encodeURIComponent(hover.id)}`));
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); cam.zoom = Math.max(0.5, Math.min(4, cam.zoom * Math.exp(-e.deltaY * 0.001))); lastMove = now(); if (reduceMotion) draw(now()); }, { passive: false });
  canvas.addEventListener("keydown", (e) => {
    const k = { ArrowLeft: [-0.12, 0, 1], ArrowRight: [0.12, 0, 1], ArrowUp: [0, -0.1, 1], ArrowDown: [0, 0.1, 1], "+": [0, 0, 1.15], "=": [0, 0, 1.15], "-": [0, 0, 1 / 1.15] }[e.key];
    if (e.key === "Escape") return select(null);
    if (!k) return;
    e.preventDefault();
    cam.yaw += k[0]; cam.pitch = Math.max(-1.2, Math.min(1.2, cam.pitch + k[1])); cam.zoom = Math.max(0.5, Math.min(4, cam.zoom * k[2]));
    lastMove = now(); if (reduceMotion) draw(now());
  });
  rotateBtn.addEventListener("click", () => { cam.auto = !cam.auto; rotateBtn.setAttribute("aria-pressed", String(cam.auto)); });
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    highlight = q ? new Set(g.nodes.filter((n) => (n.title + " " + n.id).toLowerCase().includes(q)).map((n) => n.id)) : null;
    voidSel.value = ""; if (reduceMotion) draw(now());
  });
  voidSel.addEventListener("input", () => {
    const v = (voidSel.voids || []).find((x) => x.key === voidSel.value);
    highlight = v ? new Set(v.items.map((i) => i.id)) : null; search.value = "";
    if (v) ticker.textContent = `Weak zone: ${v.label}: ${v.rule}`;
    if (reduceMotion) draw(now());
  });

  function select(n) {
    selected = n || null;
    if (!n) { side.hidden = true; return; }
    side.hidden = false;
    const panel = h("div", {});
    fill(side, h("div.row.between", {}, h("strong", {}, "Selected"), h("button.btn.ghost.small", { type: "button", onclick: () => select(null) }, "Close")),
      h("div.row", {}, h("a.btn.small", { href: `#/neural?id=${encodeURIComponent(n.id)}` }, "Explore relations"),
        h("a.btn.ghost.small", { href: `#/clusters?key=${encodeURIComponent(clusterKey(n))}` }, "Open cluster")), panel);
    showNode(panel, n.id);
    if (reduceMotion) draw(now());
  }

  // live: tail the event log; animate only what actually happened
  let lastEvent = g.last_event, stop = false;
  const describe = (e) => e.kind === "route" ? `Routing “${e.payload.task}” → ${(e.payload.selected || []).length} selected`
    : e.kind.startsWith("memory.") ? `Memory ${e.kind.split(".")[1]}: ${e.payload.title || e.payload.id || ""}`
    : e.kind === "wake" ? `Session wake-up (${e.payload.elapsed_ms} ms)` : e.kind === "feedback" ? `Feedback: ${e.payload.useful ? "useful" : "not useful"}`
    : e.kind;
  async function poll() {
    if (stop) return;
    try {
      const evs = await api(`/api/events?after=${lastEvent}&limit=50`);
      let refresh = false;
      for (const e of evs) {
        lastEvent = Math.max(lastEvent, e.id);
        ticker.textContent = `Live · ${new Date(e.ts).toLocaleTimeString()} · ${describe(e)}`;
        const t = now();
        if (e.kind === "route") {
          ringsAt.push(t);
          (e.payload.selected || []).forEach((id, i) => pulses.push({ id, t0: t + i * 180 }));
          const keys = new Set((e.payload.selected || []).map((id) => g.byId.get(id)).filter(Boolean).map(clusterKey));
          if (keys.size && !search.value && !voidSel.value) {  // the clusters this search used become more visible
            highlight = new Set(g.nodes.filter((n) => keys.has(clusterKey(n))).map((n) => n.id));
            setTimeout(() => { if (!search.value && !voidSel.value) highlight = null; }, 3500);
          }
        } else if (e.kind === "wake") ringsAt.push(t);
        else if (e.kind === "feedback") (e.payload.ids || []).forEach((id) => flares.set(id, t));
        if (e.kind.startsWith("memory.") || e.kind.startsWith("sync")) refresh = true;
      }
      if (refresh) {
        const before = new Set(g.nodes.map((n) => n.id));
        Object.assign(g, await loadGraph(true));
        L = layout(g.nodes);
        const t = now();
        for (const n of g.nodes) if (!before.has(n.id)) births.set(n.id, t);
      }
    } catch { ticker.textContent = "Live updates paused: NEXUS UI server not reachable."; }
    if (!stop) setTimeout(poll, 2500);
  }

  resize(); addEventListener("resize", resize);
  if (reduceMotion) { draw(now()); setInterval(() => !stop && draw(now()), 1000); } else raf = requestAnimationFrame(loop);
  poll();
  viewCleanup = () => { stop = true; cancelAnimationFrame(raf); removeEventListener("resize", resize); $tip.hidden = true; };
};

// ---------- Neural view: one entry and its neighbourhood ----------
views.neural = async () => {
  const g = await loadGraph(true);
  const id = params().id || g.nodes.find((n) => n.kind === "project")?.id || g.nodes[0]?.id;
  const n = g.byId.get(id);
  if (!n) return setView(h("h1", {}, "Neural view"), h("p.empty", {}, "Pick a star in the Galaxy, or an entry anywhere, to explore its relations."));
  const ring1 = [...new Map(g.adj.get(id).map(([o, e, dir]) => [o, [o, e, dir]])).values()].slice(0, 28);
  const r1 = new Set(ring1.map(([o]) => o));
  const ring2 = [...new Set(ring1.flatMap(([o]) => g.adj.get(o).map(([x]) => x)))].filter((x) => x !== id && !r1.has(x)).slice(0, 48);
  const W = 760, H = 560, cx = W / 2, cy = H / 2;
  const at = (i, count, r, off = 0) => [cx + r * Math.cos(off + (2 * Math.PI * i) / Math.max(count, 1)), cy + r * Math.sin(off + (2 * Math.PI * i) / Math.max(count, 1))];
  const P = new Map([[id, [cx, cy]]]);
  ring1.forEach(([o], i) => P.set(o, at(i, ring1.length, 165)));
  ring2.forEach((o, i) => P.set(o, at(i, ring2.length, 255, 0.3)));
  const svg = h("svg.neural", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${n.title} and its ${ring1.length} direct relations` });
  for (const o of ring2) for (const [x, e] of g.adj.get(o)) if (r1.has(x)) {
    const a = P.get(o), b = P.get(x); svg.append(h("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: "edge far" }));
  }
  for (const [o, e, dir] of ring1) {
    const a = P.get(id), b = P.get(o), mx = a[0] + (b[0] - a[0]) * 0.64, my = a[1] + (b[1] - a[1]) * 0.64;  // toward the neighbour: opposite labels never meet
    svg.append(h("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: "edge" }),
      h("text", { x: mx, y: my - 4, class: "edge-label", "text-anchor": "middle" }, `${dir === "out" ? "" : "← "}${e.type}${dir === "out" ? " →" : ""}`));
  }
  const node = (x, r, cls) => {
    const m = g.byId.get(x), [px, py] = P.get(x);
    const el = h("g", { class: `nnode ${cls}`, tabindex: 0, role: "link", "aria-label": `${m.title} (${m.kind})`,
      onclick: () => (location.hash = `#/neural?id=${encodeURIComponent(x)}`), onkeydown: (ev) => ev.key === "Enter" && (location.hash = `#/neural?id=${encodeURIComponent(x)}`) });
    const c = h("circle", { cx: px, cy: py, r }); c.style.fill = FAMILY[familyOf(m.kind)];
    el.append(c, cls !== "far" ? h("text", { x: px, y: py + r + 14, "text-anchor": "middle" }, m.title.length > 26 ? m.title.slice(0, 25) + "…" : m.title) : "");
    tip(el, [m.title, `${m.kind.replace("_", " ")} · ${m.status}`]);
    return el;
  };
  ring2.forEach((o) => svg.append(node(o, 4, "far")));
  ring1.forEach(([o]) => svg.append(node(o, 8, "near")));
  svg.append(node(id, 16, "center"));
  const panel = h("div.card.detail", {});
  setView(h("h1", {}, "Neural view"),
    h("p.lede", {}, `${n.title}: ${ring1.length} direct relation(s)${ring2.length ? `, ${ring2.length} at two steps` : ""}. Click a node to move to it.`),
    h("div.grid.two", {}, h("div.card", {}, svg, ring1.length ? null : h("p.empty", {}, "No relations yet. Link it from the Memory page or with nexus_link.")), panel));
  showNode(panel, id, { editable: MEMORY.has(n.kind) });
};

// ---------- Clusters: a plugin's capabilities, or a project's knowledge ----------
views.clusters = async () => {
  const g = await loadGraph(true);
  const { groups } = layout(g.nodes);
  const keys = [...groups.keys()].sort((a, b) => groups.get(b).length - groups.get(a).length);
  const key = params().key && groups.has(params().key) ? params().key : keys[0];
  const members = groups.get(key) || [];
  const ids = new Set(members.map((m) => m.id));
  const inner = g.edges.filter((e) => ids.has(e.src) && ids.has(e.dst));
  const outer = g.edges.filter((e) => ids.has(e.src) !== ids.has(e.dst));
  const byKind = members.reduce((m, x) => (m[x.kind] = (m[x.kind] || 0) + 1, m), {});
  const W = 700, H = 520, cx = W / 2, cy = H / 2;
  const hub = members.find((m) => m.kind === "project" || m.kind === "plugin");
  const rest = members.filter((m) => m !== hub);
  const P = new Map(hub ? [[hub.id, [cx, cy]]] : []);
  rest.forEach((m, i) => { const a = (2 * Math.PI * i) / Math.max(rest.length, 1), r = rest.length > 18 && i % 2 ? 230 : 175; P.set(m.id, [cx + r * Math.cos(a), cy + r * Math.sin(a)]); });
  const svg = h("svg.neural", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Cluster ${clusterName(key)}: ${members.length} entries` });
  for (const e of inner) { const a = P.get(e.src), b = P.get(e.dst); svg.append(h("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: e.type === "belongs_to" ? "edge far" : "edge" })); }
  for (const m of members) {
    const [x, y] = P.get(m.id), el = h("g", { class: "nnode near", tabindex: 0, role: "link", "aria-label": m.title,
      onclick: () => (location.hash = `#/neural?id=${encodeURIComponent(m.id)}`), onkeydown: (ev) => ev.key === "Enter" && (location.hash = `#/neural?id=${encodeURIComponent(m.id)}`) });
    const c = h("circle", { cx: x, cy: y, r: m === hub ? 14 : 7 }); c.style.fill = FAMILY[familyOf(m.kind)];
    el.append(c, h("text", { x, y: y + (m === hub ? 30 : 19), "text-anchor": "middle" }, m.title.length > 22 ? m.title.slice(0, 21) + "…" : m.title));
    tip(el, [m.title, `${m.kind.replace("_", " ")} · ${m.status}`]);
    svg.append(el);
  }
  setView(h("h1", {}, "Clusters"),
    h("p.lede", {}, "Each star system of the galaxy: a plugin with its capabilities, or a project with what is known about it."),
    h("div.grid.cluster-layout", {},
      h("div.card", {}, h("ul.list.scroll", { "aria-label": "Clusters" }, keys.map((k) => h("li.item", { "aria-selected": String(k === key), tabindex: 0,
        onclick: () => (location.hash = `#/clusters?key=${encodeURIComponent(k)}`), onkeydown: (ev) => ev.key === "Enter" && (location.hash = `#/clusters?key=${encodeURIComponent(k)}`) },
        h("div.title", {}, h("span", {}, clusterName(k)), h("span.chip", {}, String(groups.get(k).length))))))),
      h("div.card", {}, h("h3", {}, clusterName(key)),
        h("p.small.muted", {}, Object.entries(byKind).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · "),
          ` · ${inner.length} internal relation(s) · ${outer.length} to other clusters`,
          members.some((m) => m.status === "stale") ? ` · ${members.filter((m) => m.status === "stale").length} stale` : ""),
        svg)));
};

// ---------- Voids: where the brain is weak ----------
views.voids = async () => {
  setView(h("h1", {}, "Voids"), loading());
  const vs = await api("/api/voids");
  const total = vs.reduce((a, v) => a + v.items.length, 0);
  setView(h("h1", {}, "Voids"),
    h("p.lede", {}, `The dark zones of the brain: ${total} finding(s). Each comes from an explicit rule, shown under its title.`),
    h("div.grid.voids", {}, vs.map((v) => h("div.card", {},
      h("div.row.between", {}, h("h3", {}, v.label), h("span.chip" + (v.items.length ? ".status-stale" : ".status-active"), {}, v.items.length ? `⚠ ${v.items.length}` : "● none")),
      h("p.small.muted", {}, v.rule),
      v.items.length ? h("ul.list", {}, v.items.slice(0, 8).map((i) => h("li", {}, h("a", { href: `#/neural?id=${encodeURIComponent(i.id)}` }, i.title), " ", h("span.small.muted", {}, i.kind.replace("_", " ")))),
        v.items.length > 8 ? h("li.small.muted", {}, `+${v.items.length - 8} more`) : null) : null,
      v.items.length ? h("a.btn.ghost.small", { href: `#/galaxy?voids=${v.key}` }, "Show in galaxy") : null))));
};
