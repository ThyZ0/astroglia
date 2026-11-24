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
// Relation types are told apart by line pattern, not colour (colour already encodes node families).
const EDGE_STYLE = { belongs_to: { dash: [1, 4], alpha: 0.06, label: "belongs to" }, similar_to: { dash: [6, 4], alpha: 0.22, label: "similar to" },
  related_to: { dash: [], alpha: 0.16, label: "related to" }, used_in: { dash: [], alpha: 0.32, label: "used in" } };
const edgeStyle = (t) => EDGE_STYLE[t] || { dash: [], alpha: 0.18, label: t.replace(/_/g, " ") };
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

// ---------- Atlas view: the brain as an anatomical plate drawn like a star chart ----------
// Each region holds what its real counterpart does: frontal = what Claude can do (skills, commands, agents),
// temporal = what it learned (memory), parietal = projects, occipital = senses (MCP servers), cerebellum =
// reflexes (hooks), brainstem = Astroglia's core. Stars are stored entries; lines are stored relations.
const W0 = 1000, H0 = 720;  // world units of the plate
const BRAIN = {
  cerebrum: "M150 430 C110 360 115 250 175 185 C235 115 345 70 465 62 C590 54 710 80 790 140 C860 192 900 262 898 340 " +
    "C896 395 872 440 830 462 C790 482 745 486 705 478 C660 470 615 482 580 500 C520 532 440 545 380 530 " +
    "C320 515 285 480 270 445 C250 455 205 462 150 430 Z",
  cerebellum: "M632 505 C676 474 800 476 848 506 C884 528 878 590 826 606 C770 624 690 618 646 596 C612 578 606 525 632 505 Z",
  stem: "M566 506 C586 548 592 602 597 690 C608 697 630 697 641 690 C641 628 647 572 670 520 C642 506 598 500 566 506 Z",
  // sulci (drawn as ink hairlines, also used to split the cerebrum into lobes)
  sylvian: [[285, 455], [360, 420], [470, 382], [610, 345]],
  central: [[478, 63], [470, 150], [450, 262], [432, 395]],
  parieto: [[738, 108], [760, 180], [770, 252], [762, 330], [742, 410], [722, 478]],
  folds: ["M210 300 C260 270 300 280 330 250", "M190 380 C240 360 290 370 330 340", "M260 190 C300 170 340 180 380 150",
    "M350 300 C380 270 410 280 430 250", "M540 120 C560 170 600 190 640 170", "M560 250 C600 230 640 250 680 220",
    "M520 330 C560 310 600 320 640 300", "M800 220 C830 250 840 290 860 320", "M420 470 C470 455 520 460 560 440",
    "M380 500 C430 492 480 498 520 480", "M652 512 C712 500 788 504 840 520", "M640 540 C708 530 790 536 852 548",
    "M642 566 C710 560 790 566 850 574", "M656 590 C716 588 784 592 832 594"],
};
const REGION = {
  frontal: { label: "Lobus frontalis", what: "what Claude can do", at: [235, 250] },
  parietal: { label: "Lobus parietalis", what: "projects", at: [600, 160] },
  occipital: { label: "Lobus occipitalis", what: "senses: MCP servers", at: [842, 300] },
  temporal: { label: "Lobus temporalis", what: "what Claude learned", at: [430, 455] },
  cerebellum: { label: "Cerebellum", what: "reflexes: hooks", at: [745, 545] },
};
const CORE = [612, 640];

function regionOf(n) {
  if (n.kind === "project" || (MEMORY.has(n.kind) && String(n.source || "").startsWith("provider:"))) return "parietal";
  if (MEMORY.has(n.kind)) return "temporal";
  if (n.kind === "mcp_server") return "occipital";
  if (n.kind === "hook") return "cerebellum";
  return "frontal";
}
const atlasCluster = (n) => {
  const r = regionOf(n);
  return r === "parietal" || r === "temporal" ? `${r}:${n.project || "general"}` : `${r}:${n.origin || "user"}`;
};
const xAt = (poly, y) => {  // x of a polyline at height y (linear interpolation, clamped)
  for (let i = 1; i < poly.length; i++) {
    const [x1, y1] = poly[i - 1], [x2, y2] = poly[i];
    if ((y - y1) * (y - y2) <= 0 && y1 !== y2) return x1 + (x2 - x1) * (y - y1) / (y2 - y1);
  }
  return y < poly[0][1] ? poly[0][0] : poly[poly.length - 1][0];
};
const yAt = (poly, x) => xAt(poly.map(([a, b]) => [b, a]), x);

function atlasLayout(nodes) {
  const probe = document.createElement("canvas").getContext("2d");
  const paths = { cerebrum: new Path2D(BRAIN.cerebrum), cerebellum: new Path2D(BRAIN.cerebellum) };
  const inside = (p, x, y) => probe.isPointInPath(paths[p], x, y);
  const regionAt = (x, y) => {
    if (inside("cerebellum", x, y)) return "cerebellum";
    if (!inside("cerebrum", x, y)) return null;
    if (y > yAt(BRAIN.sylvian, x) && x > 270 && x < 700) return "temporal";
    if (x < xAt(BRAIN.central, y)) return "frontal";
    if (x > xAt(BRAIN.parieto, y)) return "occipital";
    return "parietal";
  };
  const nearTitle = (x, y) => Object.values(REGION).some((r) => Math.abs(x - r.at[0]) < 62 && y > r.at[1] - 16 && y < r.at[1] + 18);
  const deep = (reg, x, y, m) => [[0, 0], [m, 0], [-m, 0], [0, m], [0, -m]].every(([dx, dy]) => regionAt(x + dx, y + dy) === reg);
  const groups = new Map();
  for (const n of nodes) { const k = atlasCluster(n); (groups.get(k) || groups.set(k, []).get(k)).push(n); }
  const pos = new Map(), centers = new Map(), placed = [];
  const keys = [...groups.keys()].sort((a, b) => groups.get(b).length - groups.get(a).length);
  for (const key of keys) {
    const reg = key.split(":")[0], members = groups.get(key), r = rng(hash(key));
    const spread = Math.min(70, 10 + Math.sqrt(members.length) * 9);
    let best = null, bestD = -1;  // best-candidate sampling: clusters spread evenly over their lobe
    for (let i = 0; i < 400 && !(best && i > 60); i++) {
      const x = 100 + r() * 820, y = 40 + r() * 600;
      if (!deep(reg, x, y, Math.max(24, Math.min(spread * 0.8, 36))) || nearTitle(x, y)) continue;  // keep constellations off the lobe boundaries
      const d = Math.min(1e9, ...[...centers.entries()].filter(([k]) => k.startsWith(reg)).map(([, c]) => Math.hypot(c[0] - x, c[1] - y)));
      if (d > bestD) { best = [x, y]; bestD = d; }
    }
    best = best || REGION[reg].at;
    centers.set(key, best);
    const hub = members.find((m) => m.kind === "plugin" || m.kind === "project");
    for (const m of members) {
      if (m === hub) { pos.set(m.id, best); placed.push(best); continue; }
      const q = rng(hash(m.id));
      let p = null, pd = -1;
      for (let i = 0; i < 30; i++) {
        const a = q() * Math.PI * 2, rad = 8 + Math.sqrt(q()) * spread;
        const x = best[0] + Math.cos(a) * rad, y = best[1] + Math.sin(a) * rad;
        if (regionAt(x, y) !== reg || nearTitle(x, y)) continue;
        const d = Math.min(1e9, ...placed.slice(-400).map((s) => Math.hypot(s[0] - x, s[1] - y)));
        if (d > pd) { p = [x, y]; pd = d; }
      }
      p = p || [best[0] + (q() - 0.5) * 20, best[1] + (q() - 0.5) * 20];
      pos.set(m.id, p); placed.push(p);
    }
  }
  return { pos, centers, groups };
}

views.galaxy = async () => {
  setView(loading());
  const g = await loadGraph(true);
  $view.classList.add("bleed");
  const canvas = h("canvas.galaxy.atlas", { role: "img", tabindex: 0, "aria-label":
    `Atlas of ${g.nodes.length} entries and ${g.edges.length} relations, drawn as a brain. Arrow keys pan, plus and minus zoom. ` +
    "The same entries are listed as text in Capabilities, Memory, Projects and Health." });
  const search = h("input", { type: "search", placeholder: "Find a star", "aria-label": "Highlight entries by name" });
  const voidSel = h("select", { "aria-label": "Highlight weak zones" }, h("option", { value: "" }, "Weak zones: off"));
  const fitBtn = h("button.btn.ghost.small", { type: "button", title: "Show the whole plate" }, "Fit");
  const side = h("aside.galaxy-side", { hidden: true });
  const ticker = h("div.ticker", { "aria-live": "polite" }, "Live: waiting for Astroglia operations…");
  const hidden = new Set();
  const legendOpen = !localStorage.getItem("astroglia-legend-closed");
  const legend = h("div.legend.atlas-legend", { hidden: !legendOpen },
    h("div.legend-title", {}, "Key (click to show or hide)"),
    Object.entries(FAMILY).map(([f, c]) => {
      const dot = h("span.swatch"); dot.style.background = c;
      const b = h("button.legend-item", { type: "button", "aria-pressed": "true", onclick: () => {
        hidden.has(f) ? hidden.delete(f) : hidden.add(f); b.setAttribute("aria-pressed", String(!hidden.has(f))); redraw(); } }, dot, FAMILY_LABEL[f]);
      return b;
    }),
    h("div.small.muted", {}, "◯ plugin or project · ◇ MCP server · · other · dashed ring = stale"),
    h("div.small.muted", {}, "Lines are stored relations. Select a star to see their type and direction; shift+click a second star for the path."));
  const legendBtn = h("button.btn.ghost.small.legend-toggle", { type: "button", "aria-expanded": String(legendOpen), onclick: () => {
    const open = legend.hidden; legend.hidden = !open; legendBtn.setAttribute("aria-expanded", String(open));
    open ? localStorage.removeItem("astroglia-legend-closed") : localStorage.setItem("astroglia-legend-closed", "1"); } }, "Key");
  const onboard = h("div.onboard", { role: "dialog", "aria-label": "How to read the atlas", hidden: !!localStorage.getItem("astroglia-atlas-onboarded") },
    h("h2", {}, "How to read the atlas"),
    h("ul", {}, h("li", {}, "The plate is a brain. Each region holds what its real counterpart does: the frontal lobe what Claude can do, the temporal lobe what it learned, the parietal lobe your projects, the occipital lobe its senses (MCP servers), the cerebellum its reflexes (hooks)."),
      h("li", {}, "Each star is a stored entry; constellations are a plugin with its skills, or a project with what is known about it. Lines are stored relations only."),
      h("li", {}, "Pulses leave the brainstem only when Astroglia actually serves something: the strip at the bottom names the event."),
      h("li", {}, "Drag to move, scroll or +/− to zoom, click a star for its relations, shift+click a second star for the path, Esc to clear.")),
    h("button.btn.primary", { type: "button", onclick: () => { localStorage.setItem("astroglia-atlas-onboarded", "1"); onboard.hidden = true; } }, "Got it"));
  setView(h("div.galaxy-wrap.atlas-wrap", {}, canvas,
    h("div.galaxy-top", {}, h("div", {}, h("h1.atlas-title", {}, "Atlas"),
      h("p.muted.small", {}, `${g.nodes.length} entries · ${g.edges.length} relations · plate drawn from the local store`)),
      h("div.row", {}, search, voidSel, fitBtn, h("button.btn.ghost.small", { type: "button", "aria-label": "How to read the atlas", onclick: () => { onboard.hidden = false; } }, "?"))),
    legendBtn, legend, side, ticker, onboard));
  api("/api/voids").then((vs) => { for (const v of vs) if (v.items.length) voidSel.append(h("option", { value: v.key }, `${v.label} (${v.items.length})`));
    voidSel.voids = vs; if (params().voids) { voidSel.value = params().voids; voidSel.dispatchEvent(new Event("input")); } });

  const ctx = canvas.getContext("2d");
  let L = atlasLayout(g.nodes), W = 0, H = 0, dpr = 1;
  const view = { x: 0, y: 0, k: 1 };
  let hover = null, selected = null, highlight = null, focusSet = null, path = null, active = null, proj = [];
  const births = new Map(), flares = new Map(), pulses = [], ringsAt = [];
  const now = () => performance.now();
  const visible = (n) => n && !hidden.has(familyOf(n.kind));
  const ekey = (a, b) => (a < b ? a + "|" + b : b + "|" + a);
  const fit = () => { view.k = Math.min(W / (W0 + 60), H / (H0 + 120)); view.x = (W - W0 * view.k) / 2; view.y = (H - H0 * view.k) / 2 + 20; };
  const S = ([x, y]) => [view.x + x * view.k, view.y + y * view.k];
  const resize = () => {
    dpr = devicePixelRatio || 1; const first = !W; W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr; if (first) fit(); redraw();
  };
  const P = { cerebrum: new Path2D(BRAIN.cerebrum), cerebellum: new Path2D(BRAIN.cerebellum), stem: new Path2D(BRAIN.stem),
    folds: BRAIN.folds.map((d) => new Path2D(d)) };
  const poly = (pts) => { const p = new Path2D(); pts.forEach(([x, y], i) => (i ? p.lineTo(x, y) : p.moveTo(x, y))); return p; };
  const sulci = [poly(BRAIN.sylvian), poly(BRAIN.central), poly(BRAIN.parieto)];
  const INK = "rgba(196, 210, 236,", GOLD = "#e8c46a";

  let titleBoxes = [];
  function plate() {  // graticule, frame, anatomy: drawn in world units
    ctx.save(); ctx.setTransform(dpr * view.k, 0, 0, dpr * view.k, dpr * view.x, dpr * view.y);
    const lw = 1 / view.k;
    ctx.lineWidth = lw; ctx.strokeStyle = INK + "0.045)";
    for (let x = 0; x <= W0; x += 50) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H0); ctx.stroke(); }
    for (let y = 0; y <= H0; y += 50) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W0, y); ctx.stroke(); }
    ctx.strokeStyle = INK + "0.22)"; ctx.strokeRect(0, 0, W0, H0); ctx.strokeRect(-8, -8, W0 + 16, H0 + 16);
    ctx.fillStyle = INK + "0.35)"; ctx.font = `${9}px Georgia, "Times New Roman", serif`; ctx.textAlign = "center";
    for (let x = 100; x < W0; x += 100) { ctx.fillText(String(x / 10), x, -12); ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 6); ctx.stroke(); }
    ctx.textAlign = "right";
    for (let y = 100; y < H0; y += 100) { ctx.fillText(String(y / 10), -12, y + 3); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(6, y); ctx.stroke(); }
    // anatomy: very faint fill, ink outline, hairline folds
    const fill = ctx.createLinearGradient(0, 60, 0, 690);
    fill.addColorStop(0, "rgba(120, 150, 210, 0.055)"); fill.addColorStop(1, "rgba(120, 150, 210, 0.02)");
    for (const p of [P.cerebrum, P.cerebellum, P.stem]) { ctx.fillStyle = fill; ctx.fill(p); }
    ctx.strokeStyle = INK + "0.5)"; ctx.lineWidth = 1.3 * lw;
    for (const p of [P.cerebrum, P.cerebellum, P.stem]) ctx.stroke(p);
    ctx.strokeStyle = INK + "0.28)"; ctx.lineWidth = 1.1 * lw; sulci.forEach((p) => ctx.stroke(p));
    ctx.strokeStyle = INK + "0.1)"; ctx.lineWidth = lw; P.folds.forEach((p) => ctx.stroke(p));
    ctx.textAlign = "right"; ctx.font = `italic ${10}px Georgia, serif`; ctx.fillStyle = INK + "0.3)";
    ctx.fillText("Tabula I. — Encephalon Claudii, sectio lateralis", W0 - 10, H0 - 12);
    ctx.restore();
    // region names, like an anatomical plate: fixed size on screen, fading out when zoomed in
    const zoom = view.k / Math.min(W / (W0 + 60), H / (H0 + 120)), fade = Math.max(0, Math.min(1, (3.2 - zoom) / 1.4));
    titleBoxes = [];
    if (!fade) return;
    ctx.textAlign = "center";
    for (const [key, r] of [...Object.entries(REGION), ["stem", { label: "Truncus", what: "Astroglia", at: [CORE[0], CORE[1] + 40] }]]) {
      const dim = active && key !== "stem" && ![...active].some((id) => g.byId.get(id) && regionOf(g.byId.get(id)) === key);
      const [x, y] = S(r.at);
      titleBoxes.push([x - 70, y - 14, x + 70, y + 18]);  // star names keep clear of region titles
      ctx.globalAlpha = fade;
      ctx.fillStyle = INK + (dim ? "0.13)" : "0.48)");
      ctx.font = `italic 16px Georgia, "Times New Roman", serif`; ctx.fillText(r.label, x, y);
      ctx.font = `600 8.5px "Segoe UI", system-ui, sans-serif`; ctx.fillStyle = INK + (dim ? "0.1)" : "0.34)");
      ctx.fillText(r.what.toUpperCase().split("").join(" "), x, y + 14);
      ctx.globalAlpha = 1;
    }
  }

  function curve(a, b, bend) {  // a gentle arc between two screen points, like a route on a chart
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
    return [mx - dy / len * len * bend, my + dx / len * len * bend];
  }

  function draw(t) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    plate();
    const focus = selected || hover;
    active = path ? path.nodes : selected ? focusSet : highlight;
    const SP = new Map(g.nodes.map((n) => [n.id, S(L.pos.get(n.id))]));
    const labels = [], zoom = view.k / Math.min(W / (W0 + 60), H / (H0 + 120));
    // relations: constellation lines (short, within a cluster) always; others only around the selection
    for (const e of g.edges) {
      const na = g.byId.get(e.src), nb = g.byId.get(e.dst);
      if (!visible(na) || !visible(nb)) continue;
      const a = SP.get(e.src), b = SP.get(e.dst); if (!a || !b) continue;
      const onPath = path && path.edges.has(ekey(e.src, e.dst));
      const on = !path && focus && (e.src === focus.id || e.dst === focus.id);
      const local = atlasCluster(na) === atlasCluster(nb);
      if (!onPath && !on && !local) continue;
      const dim = active && !onPath && !on && !(active.has(e.src) && active.has(e.dst));
      const st = edgeStyle(e.type);
      ctx.setLineDash(on || onPath ? [] : st.dash.map((d) => d * 0.8));
      ctx.strokeStyle = onPath ? GOLD : on ? "rgba(232, 196, 106, 0.85)" : INK + (dim ? "0.04)" : "0.2)");
      ctx.lineWidth = onPath ? 2 : on ? 1.3 : 0.8;
      const c = local ? null : curve(a, b, 0.12);
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); c ? ctx.quadraticCurveTo(c[0], c[1], b[0], b[1]) : ctx.lineTo(b[0], b[1]); ctx.stroke();
      if (on || onPath) {
        const tx = c ? c[0] * 0.25 + b[0] * 0.75 : b[0], ty = c ? c[1] * 0.25 + b[1] * 0.75 : b[1];
        const ang = Math.atan2(b[1] - ty, b[0] - tx) || Math.atan2(b[1] - a[1], b[0] - a[0]);
        const hx = b[0] - Math.cos(ang) * 7, hy = b[1] - Math.sin(ang) * 7;
        ctx.setLineDash([]); ctx.fillStyle = ctx.strokeStyle; ctx.beginPath();
        ctx.moveTo(hx, hy); ctx.lineTo(hx - Math.cos(ang - 0.5) * 6, hy - Math.sin(ang - 0.5) * 6);
        ctx.lineTo(hx - Math.cos(ang + 0.5) * 6, hy - Math.sin(ang + 0.5) * 6); ctx.closePath(); ctx.fill();
        if (labels.length < 40) labels.push(c ? [(a[0] + 2 * c[0] + b[0]) / 4, (a[1] + 2 * c[1] + b[1]) / 4, st.label] : [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, st.label]);
      }
    }
    ctx.setLineDash([]);
    // core and its real-event rings
    const core = S(CORE);
    ctx.strokeStyle = INK + "0.6)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(core[0], core[1], 5, 0, 7); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(core[0] - 9, core[1]); ctx.lineTo(core[0] + 9, core[1]); ctx.moveTo(core[0], core[1] - 9); ctx.lineTo(core[0], core[1] + 9); ctx.stroke();
    for (let i = ringsAt.length - 1; i >= 0; i--) {
      const k = (t - ringsAt[i]) / 1600; if (k > 1) { ringsAt.splice(i, 1); continue; }
      ctx.strokeStyle = `rgba(232, 196, 106, ${0.7 * (1 - k)})`; ctx.beginPath(); ctx.arc(core[0], core[1], 6 + k * 40, 0, 7); ctx.stroke();
    }
    // stars: crisp symbols, size by kind and use, colour by family
    proj = [];
    for (const n of g.nodes) {
      if (!visible(n)) continue;
      const p = SP.get(n.id); proj.push([n, p]);
      if (p[0] < -20 || p[1] < -20 || p[0] > W + 20 || p[1] > H + 20) continue;
      const color = FAMILY[familyOf(n.kind)];
      const born = births.get(n.id), grow = born ? Math.min(1, (t - born) / 1400) : 1;
      const fl = flares.get(n.id), flare = fl ? Math.max(0, 1 - (t - fl) / 2200) : 0;
      const hub = n.kind === "plugin" || n.kind === "project";
      let r = (hub ? 3.6 : MEMORY.has(n.kind) ? 2.6 : 2.1) * (1 + Math.log1p(n.uses) * 0.25) * Math.min(1.8, Math.max(0.8, Math.sqrt(zoom)));
      r *= grow;
      const dim = active && !active.has(n.id);
      ctx.globalAlpha = dim ? 0.18 : 1;
      if (flare > 0) { ctx.strokeStyle = `rgba(232, 196, 106, ${flare})`; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(p[0], p[1], r + 4 + (1 - flare) * 10, 0, 7); ctx.stroke(); }
      ctx.fillStyle = color; ctx.strokeStyle = color; ctx.lineWidth = 1.2;
      if (hub) {
        ctx.beginPath(); ctx.arc(p[0], p[1], r + 2.2, 0, 7); ctx.stroke();
        ctx.beginPath(); ctx.arc(p[0], p[1], 1.7, 0, 7); ctx.fill();
      } else if (n.kind === "mcp_server") {
        ctx.beginPath(); ctx.moveTo(p[0], p[1] - r - 1.5); ctx.lineTo(p[0] + r + 1.5, p[1]); ctx.lineTo(p[0], p[1] + r + 1.5); ctx.lineTo(p[0] - r - 1.5, p[1]); ctx.closePath(); ctx.fill();
      } else {
        ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 7); ctx.fill();
      }
      if (n.status === "stale") { ctx.setLineDash([2, 2]); ctx.strokeStyle = "#fbbf24"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(p[0], p[1], r + 4, 0, 7); ctx.stroke(); ctx.setLineDash([]); }
      if (focus && n.id === focus.id) { ctx.strokeStyle = GOLD; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(p[0], p[1], r + 7, 0, 7); ctx.stroke(); }
      ctx.globalAlpha = 1;
    }
    // labels: relation pills first, then names (hubs when zoomed out, every star when zoomed in), never overlapping
    const boxes = [...titleBoxes], overlaps = (b) => boxes.some((o) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1]);
    ctx.font = "10.5px 'Segoe UI', system-ui, sans-serif"; ctx.textAlign = "center";
    for (const [x, y, text] of labels) {
      const w = ctx.measureText(text).width + 10, box = [x - w / 2, y - 8, x + w / 2, y + 7];
      if (overlaps(box)) continue; boxes.push(box);
      ctx.fillStyle = "rgba(9, 14, 26, 0.92)"; ctx.fillRect(box[0], box[1], w, 15); ctx.fillStyle = "#d9c38f"; ctx.fillText(text, x, y + 3);
    }
    const named = proj.filter(([n]) => (focus && n.id === focus.id) || (path && path.nodes.has(n.id)) || (selected && focusSet.has(n.id))
      || (!active && ((n.kind === "plugin" || n.kind === "project") || zoom > 1.9)) || (highlight && highlight.has(n.id) && zoom > 1.2));
    named.sort(([a], [b]) => (focus && b.id === focus.id) - (focus && a.id === focus.id) || (b.kind === "project" || b.kind === "plugin") - (a.kind === "project" || a.kind === "plugin"));
    for (const [n, p] of named) {
      const hub = n.kind === "plugin" || n.kind === "project";
      ctx.font = hub ? "italic 12px Georgia, 'Times New Roman', serif" : "11px 'Segoe UI', system-ui, sans-serif";
      const text = n.title.length > 30 ? n.title.slice(0, 29) + "…" : n.title, w = ctx.measureText(text).width, y = p[1] - (hub ? 12 : 8);
      const box = [p[0] - w / 2 - 3, y - 11, p[0] + w / 2 + 3, y + 3];
      if (overlaps(box)) continue; boxes.push(box);
      ctx.fillStyle = focus && n.id === focus.id ? "#f3ead2" : hub ? INK + "0.85)" : INK + "0.7)";
      ctx.fillText(text, p[0], y);
    }
    // pulses: from the brainstem to what was actually served
    for (let i = pulses.length - 1; i >= 0; i--) {
      const pu = pulses[i], k = (t - pu.t0) / 1300;
      if (k > 1) { flares.set(pu.id, t); pulses.splice(i, 1); continue; }
      if (k < 0) continue;
      const b = SP.get(pu.id); if (!b) { pulses.splice(i, 1); continue; }
      const c = curve(core, b, 0.18), e = 1 - Math.pow(1 - k, 3), u = 1 - e;
      const x = u * u * core[0] + 2 * u * e * c[0] + e * e * b[0], y = u * u * core[1] + 2 * u * e * c[1] + e * e * b[1];
      ctx.strokeStyle = "rgba(232, 196, 106, 0.35)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(core[0], core[1]); ctx.quadraticCurveTo(c[0], c[1], b[0], b[1]); ctx.stroke();
      ctx.fillStyle = GOLD; ctx.beginPath(); ctx.arc(x, y, 2.6, 0, 7); ctx.fill();
    }
  }

  let raf = 0, needs = true;
  const redraw = () => { needs = true; };
  const busy = () => pulses.length || ringsAt.length || [...flares.values()].some((f) => now() - f < 2200) || [...births.values()].some((b) => now() - b < 1400);
  const loop = (t) => { if (needs || busy()) { draw(t); needs = false; } raf = requestAnimationFrame(loop); };

  // interaction: pan, zoom at cursor, select, path
  let drag = null;
  const zoomAt = (mx, my, f) => { const k = Math.max(0.3, Math.min(8, view.k * f)); view.x = mx - (mx - view.x) * k / view.k; view.y = my - (my - view.y) * k / view.k; view.k = k; redraw(); };
  canvas.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY, view.x, view.y, false]; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    if (drag) {
      const dx = e.clientX - drag[0], dy = e.clientY - drag[1];
      if (Math.abs(dx) + Math.abs(dy) > 3) drag[4] = true;
      if (drag[4]) { view.x = drag[2] + dx; view.y = drag[3] + dy; redraw(); }
      return;
    }
    let best = null, bd = 100;
    for (const [n, p] of proj) { const d = (p[0] - mx) ** 2 + (p[1] - my) ** 2; if (d < bd) { bd = d; best = n; } }
    if (best !== hover) { hover = best; redraw(); }
    canvas.style.cursor = best ? "pointer" : "grab";
    if (best) {
      $tip.hidden = false;
      fill($tip, h("div", {}, best.title), h("div.muted", {}, `${best.kind.replace("_", " ")} · ${REGION[regionOf(best)].label.toLowerCase()} · ${best.status}${best.project ? " · " + best.project : ""}`));
      $tip.style.left = e.clientX + 14 + "px"; $tip.style.top = e.clientY + 14 + "px";
    } else $tip.hidden = true;
  });
  canvas.addEventListener("pointerleave", () => { hover = null; $tip.hidden = true; redraw(); });
  canvas.addEventListener("pointerup", (e) => {
    if (drag && !drag[4]) (e.shiftKey && selected && hover && hover.id !== selected.id) ? trace(selected, hover) : select(hover);
    drag = null;
  });
  canvas.addEventListener("dblclick", () => hover && (location.hash = `#/neural?id=${encodeURIComponent(hover.id)}`));
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); const r = canvas.getBoundingClientRect(); zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015)); }, { passive: false });
  canvas.addEventListener("keydown", (e) => {
    const step = 60, m = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
    if (e.key === "Escape") { path = null; select(null); return; }
    if (m) { view.x += m[0]; view.y += m[1]; redraw(); e.preventDefault(); }
    else if (e.key === "+" || e.key === "=") { zoomAt(W / 2, H / 2, 1.2); e.preventDefault(); }
    else if (e.key === "-") { zoomAt(W / 2, H / 2, 1 / 1.2); e.preventDefault(); }
  });
  fitBtn.addEventListener("click", () => { fit(); redraw(); });
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    highlight = q ? new Set(g.nodes.filter((n) => (n.title + " " + n.id).toLowerCase().includes(q)).map((n) => n.id)) : null;
    voidSel.value = ""; redraw();
  });
  voidSel.addEventListener("input", () => {
    const v = (voidSel.voids || []).find((x) => x.key === voidSel.value);
    highlight = v ? new Set(v.items.map((i) => i.id)) : null; search.value = "";
    if (v) ticker.textContent = `Weak zone: ${v.label}: ${v.rule}`;
    redraw();
  });
  function trace(from, to) {
    const prev = new Map([[from.id, null]]), queue = [from.id];
    while (queue.length && !prev.has(to.id)) { const cur = queue.shift(); for (const [o] of g.adj.get(cur) || []) if (!prev.has(o)) { prev.set(o, cur); queue.push(o); } }
    if (!prev.has(to.id)) { path = null; ticker.textContent = `No path between “${from.title}” and “${to.title}”: they are not connected.`; redraw(); return; }
    const ids = []; for (let x = to.id; x; x = prev.get(x)) ids.unshift(x);
    path = { nodes: new Set(ids), edges: new Set(ids.slice(1).map((x, i) => ekey(ids[i], x))) };
    ticker.textContent = `Path (${ids.length - 1} step${ids.length > 2 ? "s" : ""}): ` + ids.map((x) => g.byId.get(x).title).join(" → ");
    redraw();
  }
  function select(n) {
    selected = n || null; path = null;
    if (!n) { side.hidden = true; focusSet = null; redraw(); return; }
    focusSet = new Set([n.id, ...(g.adj.get(n.id) || []).map(([o]) => o)]);
    side.hidden = false;
    const panel = h("div", {});
    const expand = h("button.btn.ghost.small", { type: "button", onclick: () => {
      for (const id of [...focusSet]) for (const [o] of g.adj.get(id) || []) focusSet.add(o);
      expand.disabled = true; expand.textContent = `${focusSet.size - 1} within 2 steps`; redraw(); } }, "Expand to 2 steps");
    fill(side, h("div.row.between", {}, h("strong", {}, `${focusSet.size - 1} direct relation(s)`), h("button.btn.ghost.small", { type: "button", onclick: () => select(null) }, "Close")),
      h("div.row", {}, h("a.btn.small", { href: `#/neural?id=${encodeURIComponent(n.id)}` }, "Explore relations"), expand,
        h("button.btn.ghost.small", { type: "button", onclick: () => api("/api/reveal", { id: n.id }).then(() => toast("Opened in your file manager."), (err) => toast(err.message, true)) }, "Show source")),
      h("p.small.muted", {}, "Shift+click another star to trace the path between them."), panel);
    showNode(panel, n.id);
    const [sx, sy] = S(L.pos.get(n.id)), room = W - Math.min(440, W * 0.42) - 60;
    if (sx > room) view.x -= sx - room * 0.6;
    if (sy < 90 || sy > H - 80) view.y += H / 2 - sy;
    redraw();
  }

  // live: tail the event log; animate only what actually happened
  let lastEvent = g.last_event, stop = false;
  const describe = (e) => e.kind === "route" ? `Routing “${e.payload.task}” → ${(e.payload.selected || []).length} selected`
    : e.kind.startsWith("memory.") ? `Memory ${e.kind.split(".")[1]}: ${e.payload.title || e.payload.id || ""}`
    : e.kind === "wake" ? `Session wake-up (${e.payload.elapsed_ms} ms)` : e.kind === "feedback" ? `Feedback: ${e.payload.useful ? "useful" : "not useful"}`
    : e.kind === "served" && e.payload.kind === "anchor" ? `Claude ${e.payload.via === "edit" ? "edited" : "opened"} ${e.payload.file}: ${e.payload.count} remembered entr${e.payload.count > 1 ? "ies" : "y"} served`
    : e.kind === "served" && e.payload.kind === "dejavu" ? "Déjà vu: a command failed with an error already solved"
    : e.kind === "served" && e.payload.kind === "brief" ? "Project brief served at session start" : e.kind;
  async function poll() {
    if (stop) return;
    try {
      const evs = await api(`/api/events?after=${lastEvent}&limit=50`);
      let refresh = false;
      for (const e of evs) {
        lastEvent = Math.max(lastEvent, e.id);
        ticker.textContent = `Live · ${new Date(e.ts).toLocaleTimeString()} · ${describe(e)}`;
        const t = now();
        if (e.kind === "route") { ringsAt.push(t); (e.payload.selected || []).forEach((id, i) => pulses.push({ id, t0: t + i * 180 })); }
        else if (e.kind === "wake") ringsAt.push(t);
        else if (e.kind === "feedback") (e.payload.ids || []).forEach((id) => flares.set(id, t));
        else if (e.kind === "served" && e.payload.id && g.byId.has(e.payload.id)) { ringsAt.push(t); pulses.push({ id: e.payload.id, t0: t }); }
        if (e.kind.startsWith("memory.") || e.kind.startsWith("sync")) refresh = true;
      }
      if (refresh) {
        const before = new Set(g.nodes.map((n) => n.id));
        Object.assign(g, await loadGraph(true)); L = atlasLayout(g.nodes);
        const t = now(); for (const n of g.nodes) if (!before.has(n.id)) births.set(n.id, t);
      }
      if (evs.length) redraw();
    } catch { ticker.textContent = "Live updates paused: Astroglia UI server not reachable."; }
    if (!stop) setTimeout(poll, 2500);
  }
  if (params().ids) {
    const ids = params().ids.split(",").filter((i) => g.byId.has(i));
    highlight = new Set(ids);
    setTimeout(() => { const t = now(); ringsAt.push(t); ids.forEach((id, i) => pulses.push({ id, t0: t + i * 180 })); }, 400);
    ticker.textContent = `Replaying a routing: ${ids.length} resource(s) selected · ` + ids.map((i) => g.byId.get(i).title).join(", ");
  }
  addEventListener("resize", resize); resize();
  raf = requestAnimationFrame(loop);
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
    h("div.grid.two", {}, h("div.card", {}, svg, ring1.length ? null : h("p.empty", {}, "No relations yet. Link it from the Memory page or with link.")), panel));
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

// ---------- Health: score, suggestions, overlaps, usage, weak zones ----------
views.voids = async () => {
  setView(h("h1", {}, "Health"), loading());
  const [r, vs] = await Promise.all([api("/api/insights"), api("/api/voids")]);
  const pct = (x) => Math.round(x * 100) + "%";
  const bars = h("div.why", {}, Object.entries(r.parts).flatMap(([k, p]) => {
    const f = h("div.fill"); f.style.width = pct(p.value);
    return [h("span.muted", { title: p.means }, k), h("div.track", { title: p.means }, f), h("span.num", {}, pct(p.value))];
  }));
  const act = (label, fn, cls = "btn.ghost.small") => h(`button.${cls}`, { type: "button", onclick: async (e) => {
    e.target.disabled = true; try { await fn(); views.voids(); } catch (err) { toast(err.message, true); e.target.disabled = false; } } }, label);
  const link = (x) => h("a", { href: `#/neural?id=${encodeURIComponent(x.id)}` }, x.title);
  setView(h("h1", {}, "Health"),
    h("p.lede", {}, "How trustworthy and well organised Astroglia's knowledge is, what to tidy, and what Claude actually reuses. Every item comes from an explicit rule."),
    h("div.grid.two", {},
      h("div.card", {}, h("div.row", {}, h("div.score", { "aria-label": `Health score ${r.score} out of 100` }, String(r.score)),
        h("div", {}, h("h2", {}, "Health score"), h("p.small.muted", {}, "Average of four ratios. Hover a bar for its definition."))), bars),
      h("div.card", {}, h("h2", {}, `Most reused (${r.routings} routings so far)`),
        r.most_served.length ? h("ul.list.stack", {}, r.most_served.map((x) => h("li.row.between", {}, link(x), h("span.small.muted", {}, `${x.times}×  ${x.kind}`))))
          : h("p.empty", {}, "Nothing served yet."))),
    h("div.grid.two", {},
      h("div.card", {}, h("h2", {}, `Suggested relations (${r.missing_relations.length})`),
        r.missing_relations.length ? r.missing_relations.slice(0, 12).map((m) => h("div.pick", {}, h("p.small", {}, m.why),
          h("div.row", {}, act("Link them", () => api("/api/link", { src: m.src.id, dst: m.dst.id, type: m.type }), "btn.small"),
            act("Ignore", () => api("/api/dismiss", { key: m.key }))))) : h("p.empty", {}, "No missing relation found.")),
      h("div.card", {}, h("h2", {}, `Overlapping memory (${r.overlaps.length})`),
        r.overlaps.length ? r.overlaps.slice(0, 10).map((o) => h("div.pick", {}, h("p.small", {}, link(o.a), " ≈ ", link(o.b), h("span.muted", {}, ` (similarity ${o.similarity})`)),
          h("p.small.muted", {}, o.advice),
          h("div.row", {}, act("Merge 2nd into 1st", () => api("/api/merge", { src: o.b.id, dst: o.a.id }), "btn.small"),
            act("Not the same", () => api("/api/dismiss", { key: o.key }))))) : h("p.empty", {}, "No overlapping entries."))),
    h("div.card", {}, h("h2", {}, `Recurring errors (${r.recurring_errors.length})`),
      h("p.small.muted", {}, "The same failure seen in at least two sessions. Those without a remembered fix cost time every time they come back."),
      r.recurring_errors.length ? h("ul.list.stack", {}, r.recurring_errors.map((x) => h("li", {},
        h("div.mono", {}, x.line || "(no error line)"),
        h("div.small.muted", {}, `${x.count}× in ${x.sessions} sessions · last ${new Date(x.last).toLocaleString()}${x.projects.length ? " · " + x.projects.join(", ") : ""} · `,
          x.fix ? h("a", { href: `#/neural?id=${encodeURIComponent(x.fix)}` }, "fix remembered") : h("span.warn", {}, "no fix saved")))))
        : h("p.empty", {}, "No error has come back across sessions yet.")),
    h("div.card", {}, h("h2", {}, "Capabilities never selected"),
      r.unused_note ? h("p.small.muted", {}, r.unused_note) : r.unused_capabilities.length
        ? h("p.small", {}, r.unused_capabilities.map((x) => x.title).join(" · ")) : h("p.empty", {}, "Every capability has been used at least once.")),
    h("h2", {}, "Weak zones"),
    h("div.grid.voids", {}, vs.map((v) => h("div.card", {},
      h("div.row.between", {}, h("h3", {}, v.label), h("span.chip" + (v.items.length ? ".status-stale" : ".status-active"), {}, v.items.length ? `⚠ ${v.items.length}` : "● none")),
      h("p.small.muted", {}, v.rule),
      v.items.length ? h("ul.list", {}, v.items.slice(0, 8).map((i) => h("li", {}, h("a", { href: `#/neural?id=${encodeURIComponent(i.id)}` }, i.title), " ", h("span.small.muted", {}, i.kind.replace("_", " ")))),
        v.items.length > 8 ? h("li.small.muted", {}, `+${v.items.length - 8} more`) : null) : null,
      v.items.length ? h("a.btn.ghost.small", { href: `#/galaxy?voids=${v.key}` }, "Show in galaxy") : null))));
};

// ---------- Timeline: what changed, day by day ----------
views.timeline = async () => {
  setView(h("h1", {}, "Timeline"), loading());
  const ev = await api("/api/timeline?days=60");
  const LABEL = { "memory.created": ["✚", "Learned"], "memory.updated": ["✎", "Changed"], "memory.stale": ["⚠", "Went stale"],
    "memory.revalidated": ["✓", "Re-validated"], "memory.merged": ["⇢", "Merged"], "consolidate.asked": ["◷", "Asked to save"],
    "feedback": ["★", "Feedback"], "sync.capabilities": ["◇", "Capabilities changed"], "sync.providers": ["◎", "Projects changed"] };
  const text = (e) => {
    const p = e.payload;
    if (e.kind.startsWith("memory.")) return p.title || p.id || p.src || "";
    if (e.kind === "sync.capabilities") return [p.new_ids?.length ? `new: ${p.new_ids.map(short).join(", ")}` : "", p.missing ? `${p.missing} gone` : ""].filter(Boolean).join(" · ");
    if (e.kind === "sync.providers") return [(p.new || []).length ? `new: ${p.new.map(short).join(", ")}` : "", (p.briefs_built || []).length ? `briefs rebuilt: ${p.briefs_built.map(short).join(", ")}` : "", (p.missing || []).length ? `gone: ${p.missing.map(short).join(", ")}` : ""].filter(Boolean).join(" · ");
    if (e.kind === "feedback") return `${p.useful ? "useful" : "not useful"}: ${(p.ids || []).map(short).join(", ")}`;
    if (e.kind === "consolidate.asked") return `${p.files} files edited in the session`;
    return "";
  };
  const days = new Map();
  for (const e of ev) { const d = e.ts.slice(0, 10); (days.get(d) || days.set(d, []).get(d)).push(e); }
  setView(h("h1", {}, "Timeline"),
    h("p.lede", {}, "How Astroglia's knowledge evolved: what was learned, what changed, what went stale and what was re-validated. Answers “what changed since last time?”."),
    days.size ? [...days].map(([d, es]) => h("div.card", {}, h("h2", {}, new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })),
      es.map((e) => { const [icon, label] = LABEL[e.kind] || ["•", e.kind]; const id = e.payload.id || e.payload.dst;
        return h("div.event", {}, h("span.muted", {}, new Date(e.ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })),
          h("span", {}, `${icon} ${label}`), id ? h("a", { href: `#/neural?id=${encodeURIComponent(id)}` }, text(e)) : h("span", {}, text(e))); })))
      : h("p.empty", {}, "Nothing changed in the last 60 days."));
};
