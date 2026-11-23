"use strict";
// NEXUS UI. Every value shown comes from the local API; text from the store is untrusted,
// so it is only ever inserted with textContent (never innerHTML).

const token = (() => {
  const m = location.hash.match(/token=([\w-]+)/);
  // keep any view in the link ("#/memory&token=…"), drop the token from the address bar
  if (m) { sessionStorage.setItem("nexus-token", m[1]); history.replaceState(null, "", location.hash.replace(/[#&]?token=[\w-]+/, "") || "#/dashboard"); }
  return sessionStorage.getItem("nexus-token") || "";
})();

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "X-Nexus-Token": token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// h("div.card", {onclick}, child, "text", ...) -> element. Strings become text nodes.
function h(tag, attrs, ...kids) {
  const [name, ...classes] = tag.split(".");
  const el = name === "svg" || SVG_TAGS.has(name)
    ? document.createElementNS("http://www.w3.org/2000/svg", name) : document.createElement(name || "div");
  if (classes.length) el.setAttribute("class", classes.join(" "));
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
  return el;
}
// DOM replaceChildren() would print null/false as text: filter them out first.
const fill = (el, ...nodes) => el.replaceChildren(...nodes.flat(Infinity).filter((x) => x != null && x !== false));
const SVG_TAGS = new Set(["rect", "path", "line", "text", "g", "circle"]);
const $view = document.getElementById("view");
const toast = (msg, err) => {
  const t = h("div.t" + (err ? ".err" : ""), {}, msg);
  document.getElementById("toast").append(t);
  setTimeout(() => t.remove(), err ? 7000 : 3500);
};
const fmtDate = (iso) => iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never";
const short = (id) => id.split(":").slice(-1)[0];
const STATUS_ICON = { active: "●", stale: "⚠", missing: "✕", disabled: "○", archived: "○" };
const status = (s) => h(`span.chip.status-${s}`, { title: `status: ${s}` }, `${STATUS_ICON[s] || "•"} ${s}`);
const kindChip = (k) => h("span.chip.kind", {}, k.replace("_", " "));
const loading = () => h("div.card", {}, h("div.skeleton"), h("div.skeleton", {}), h("div.skeleton"));
const errorBox = (e) => h("div.error-box", { role: "alert" }, `Could not load: ${e.message}. Is \`nexus ui\` still running?`);
function setView(...nodes) { fill($view, ...nodes); $view.focus({ preventScroll: true }); }

// ---------- tooltip ----------
const $tip = document.getElementById("tooltip");
function tip(el, lines) {
  const show = (e) => {
    fill($tip, ...lines.map((l, i) => h(i ? "div.muted" : "div", {}, l)));
    $tip.hidden = false;
    $tip.style.left = Math.min(e.clientX + 14, innerWidth - $tip.offsetWidth - 8) + "px";
    $tip.style.top = (e.clientY + 14) + "px";
  };
  el.addEventListener("mousemove", show);
  el.addEventListener("focus", (e) => { const r = el.getBoundingClientRect(); show({ clientX: r.right, clientY: r.top }); });
  el.addEventListener("mouseleave", () => { $tip.hidden = true; });
  el.addEventListener("blur", () => { $tip.hidden = true; });
}

// ---------- charts (single series: no legend, title names it; hover + table view) ----------
function columnChart(rows, { label = "events" } = {}) {
  const W = 640, H = 180, pad = { l: 34, r: 8, t: 10, b: 24 };
  const max = Math.max(1, ...rows.map((r) => r[1]));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1];
  const slot = (W - pad.l - pad.r) / Math.max(rows.length, 1);
  const bw = Math.min(24, slot * 0.68);
  const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - v / top);
  const svg = h("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${label} per day, last ${rows.length} days` });
  for (const t of ticks) {
    svg.append(h("line.grid-line", { x1: pad.l, x2: W - pad.r, y1: y(t), y2: y(t) }),
      h("text.axis-label", { x: pad.l - 6, y: y(t) + 4, "text-anchor": "end" }, String(t)));
  }
  rows.forEach(([day, v], i) => {
    const x = pad.l + i * slot + (slot - bw) / 2, yt = y(v), base = y(0), r = Math.min(4, (base - yt) / 2);
    const g = h("g", { tabindex: 0, "aria-label": `${day}: ${v} ${label}` });
    // 4px rounded data-end, square at the baseline
    const d = v ? `M${x},${base}V${yt + r}Q${x},${yt} ${x + r},${yt}H${x + bw - r}Q${x + bw},${yt} ${x + bw},${yt + r}V${base}Z` : "";
    g.append(h("rect.hit", { x: pad.l + i * slot, y: pad.t, width: slot, height: H - pad.t - pad.b }), h("path.mark", { d }));
    tip(g, [`${v} ${label}`, day]);
    svg.append(g);
  });
  const first = rows[0]?.[0], last = rows[rows.length - 1]?.[0];
  if (first) svg.append(h("text.axis-label", { x: pad.l, y: H - 6 }, first),
    h("text.axis-label", { x: W - pad.r, y: H - 6, "text-anchor": "end" }, last));
  return withTable(h("div.chart", {}, svg), ["Day", label], rows);
}

function barList(rows, unit) {
  const W = 400, row = 26, H = rows.length * row, lw = 110, max = Math.max(1, ...rows.map((r) => r[1]));
  const svg = h("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `count by ${unit}` });
  rows.forEach(([k, v], i) => {
    const w = Math.max(2, (W - lw - 44) * v / max), yy = i * row + 7, r = Math.min(4, w / 2);
    const g = h("g", { tabindex: 0, "aria-label": `${k}: ${v}` });
    g.append(h("text.axis-label", { x: lw - 10, y: yy + 10, "text-anchor": "end" }, k.replace("_", " ")),
      h("path.mark", { d: `M${lw},${yy}H${lw + w - r}Q${lw + w},${yy} ${lw + w},${yy + r}V${yy + 12 - r}Q${lw + w},${yy + 12} ${lw + w - r},${yy + 12}H${lw}Z` }),
      h("text.value-label", { x: lw + w + 6, y: yy + 10 }, String(v)));
    tip(g, [`${v}`, k]);
    svg.append(g);
  });
  return withTable(h("div.chart", {}, svg), [unit, "Count"], rows);
}

function withTable(chart, head, rows) {
  const table = h("table.data", { hidden: true },
    h("thead", {}, h("tr", {}, h("th", {}, head[0]), h("th.num", {}, head[1]))),
    h("tbody", {}, rows.map(([a, b]) => h("tr", {}, h("td", {}, a), h("td.num", {}, String(b))))));
  const btn = h("button.btn.ghost.small", { type: "button", "aria-pressed": "false", onclick: () => {
    const on = table.hidden; table.hidden = !on; chart.hidden = on;
    btn.setAttribute("aria-pressed", String(on)); btn.textContent = on ? "Chart" : "Table";
  } }, "Table");
  return h("div", {}, h("div.row.between", {}, h("span"), btn), chart, table);
}

function niceTicks(max) {
  const step = Math.pow(10, Math.floor(Math.log10(max))) * ([1, 2, 5, 10].find((m) => max / (Math.pow(10, Math.floor(Math.log10(max))) * m) <= 4) || 10);
  const out = [];
  for (let v = 0; v <= max + step - 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

// ---------- views ----------
const views = {};

views.dashboard = async () => {
  setView(h("h1", {}, "Dashboard"), loading());
  const [o, events] = await Promise.all([api("/api/overview"), api("/api/events?limit=12")]);
  const k = o.nodes_by_kind, s = o.nodes_by_status, sum = (...ks) => ks.reduce((a, x) => a + (k[x] || 0), 0);
  const caps = sum("plugin", "skill", "command", "agent", "mcp_server", "hook");
  const edges = Object.values(o.edges_by_type).reduce((a, b) => a + b, 0);
  const kpi = (value, label, sub) => h("div.card.kpi", {}, h("div.value", {}, String(value)), h("div.label", {}, label), sub ? h("div.sub", {}, sub) : null);
  const activity = fillDays(o.activity, 30);
  setView(
    h("h1", {}, "Dashboard"),
    h("p.lede", {}, `Health of this NEXUS store (v${o.version}). Every number is counted from the local database.`),
    h("div.grid.kpis", {},
      kpi(caps, "Capabilities", `${k.skill || 0} skills · ${k.mcp_server || 0} MCP servers`),
      kpi(k.project || 0, "Projects"),
      kpi(sum("experience", "decision", "knowledge"), "Memory entries", `${k.experience || 0} exp · ${k.decision || 0} dec · ${k.knowledge || 0} know`),
      kpi(edges, "Relations"),
      kpi(s.stale || 0, "Stale entries", s.stale ? "sources changed since recorded" : "all sources unchanged"),
      kpi(o.routes, "Routings", o.avg_selected != null ? `avg ${o.avg_selected} picks · ~${o.avg_est_tokens} tokens (est.)` : "none yet")),
    h("div.grid.two", {},
      h("div.card", {}, h("h2", {}, "Activity per day, last 30 days"), columnChart(activity)),
      h("div.card", {}, h("h2", {}, "Entries by kind"),
        barList(Object.entries(k).sort((a, b) => b[1] - a[1]), "Kind"))),
    h("div.grid.two", {},
      h("div.card", {}, h("h2", {}, "Recent operations"),
        events.length ? events.map(eventRow) : h("p.empty", {}, "No operations logged yet.")),
      h("div.card", {}, h("h2", {}, "Sync"),
        h("div", {},
          h("p", {}, "Last capability sync: ", h("strong", {}, fmtDate(o.last_capability_sync))),
          h("p", {}, "Sessions started with NEXUS: ", h("strong", {}, String(o.sessions))),
          h("p", {}, "Logged events: ", h("strong", {}, String(o.events)))),
        Object.entries(s).map(([st, n]) => h("span", {}, status(st), ` ${n} `)))),
  );
};

function fillDays(rows, n) {
  const map = new Map(rows), out = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10);
    out.push([d, map.get(d) || 0]);
  }
  return out;
}

function eventRow(e) {
  const p = e.payload, detail =
    e.kind === "route" ? `“${p.task}” → ${(p.selected || []).map(short).join(", ") || "nothing selected"}` :
    e.kind.startsWith("memory.") ? (p.title || p.id || "") :
    e.kind.startsWith("sync") ? `created ${Array.isArray(p.new) ? p.new.length : p.created ?? 0}, missing ${Array.isArray(p.missing) ? p.missing.length : p.missing ?? 0}` :
    e.kind === "wake" ? `${p.elapsed_ms} ms, ${p.new} new, ${p.stale} stale` :
    e.kind === "feedback" ? `${p.useful ? "useful" : "not useful"}: ${(p.ids || []).map(short).join(", ")}` : JSON.stringify(p).slice(0, 120);
  return h("div.event", {}, h("span.muted", {}, fmtDate(e.ts)), h("span", {}, e.kind), h("span", {}, detail));
}

// ---------- context monitor ----------
views.context = async () => {
  const input = h("input", { type: "search", placeholder: "Describe a task, e.g. “review my code before merging”", "aria-label": "Task" });
  const out = h("div", {});
  const run = async (ev) => {
    ev?.preventDefault();
    if (!input.value.trim()) return;
    fill(out, loading());
    try { fill(out, routeResult(await api("/api/route", { task: input.value }))); fill(history_, ...(await routeHistory())); }
    catch (e) { fill(out, errorBox(e)); }
  };
  const history_ = h("div", {}, loading());
  setView(
    h("h1", {}, "Context Monitor"),
    h("p.lede", {}, "What the router selected or rejected for each task, and why. These are NEXUS's own operations, not Claude's reasoning."),
    h("form.card.row", { onsubmit: run }, input, h("button.btn.primary", { type: "submit" }, "Route")),
    h("div", {}, out),
    h("div.card", {}, h("h2", {}, "Recent routings"), history_));
  fill(history_, ...(await routeHistory()));
};

function routeResult(r) {
  const picks = r.selected.map((s) => h("div.pick", {},
    h("div.row.between", {}, h("div.row", {}, kindChip(s.kind), h("strong", {}, s.title)), h("span.mono", {}, `score ${s.score}`)),
    h("p.desc.small.muted", {}, s.summary),
    s.warnings.map((w) => h("p.warn.small", {}, `⚠ ${w}`)),
    h("div.why", {}, Object.entries(s.why).flatMap(([k, v]) => [
      h("span.muted", {}, k), (() => { const f = h("div.fill"); f.style.width = `${Math.round(v * 100)}%`; return h("div.track", {}, f); })(),
      h("span.num", {}, v.toFixed(2))])),
    h("div.row.between", {}, h("span.mono.muted", {}, s.id),
      h("div.row", {},
        h("button.btn.ghost.small", { type: "button", onclick: (e) => feedback([s.id], true, e.target) }, "Useful"),
        h("button.btn.ghost.small", { type: "button", onclick: (e) => feedback([s.id], false, e.target) }, "Not useful")))));
  return h("div.grid.split", {},
    h("div.stack", {}, h("h2", {}, `Selected (${r.selected.length}) · ~${r.estimated_tokens}/${r.budget} tokens (estimate)`),
      picks.length ? picks : h("p.empty", {}, "Nothing relevant enough. NEXUS returns nothing rather than noise.")),
    h("div.card", {}, h("h2", {}, `Rejected (${r.rejected.length})`),
      r.rejected.length ? r.rejected.map((x) => h("div.reject", {}, h("span", {}, x.title), h("span.mono.muted", {}, String(x.score)),
        h("span.small.muted", {}, x.reason))) : h("p.empty", {}, "No candidates rejected.")));
}

async function feedback(ids, useful, btn) {
  btn.disabled = true;
  try { await api("/api/feedback", { ids, useful }); toast(`Recorded: ${useful ? "useful" : "not useful"}. It adjusts the success signal.`); }
  catch (e) { toast(e.message, true); btn.disabled = false; }
}

async function routeHistory() {
  const ev = await api("/api/events?kind=route&limit=30");
  if (!ev.length) return [h("p.empty", {}, "No routing yet. Claude calls nexus_route, or try one above.")];
  return ev.map((e) => h("details", { class: "event-details" },
    h("summary", {}, h("span.muted", {}, fmtDate(e.ts) + "  "), `“${e.payload.task}”`),
    h("p.small", {}, "Selected: ", (e.payload.selected || []).join(", ") || "none"),
    (e.payload.rejected || []).length ? h("p.small.muted", {}, "Rejected: ",
      e.payload.rejected.slice(0, 8).map((x) => `${short(x.id)} (${x.reason})`).join("; ")) : null));
}

// ---------- capabilities ----------
views.capabilities = async () => {
  setView(h("h1", {}, "Capabilities"), loading());
  const [nodes, edges] = await Promise.all([
    api("/api/nodes?kinds=plugin,skill,command,agent,mcp_server,hook"), api("/api/edges")]);
  const q = h("input", { type: "search", placeholder: "Filter by name or description", "aria-label": "Filter capabilities" });
  const kind = h("select", { "aria-label": "Kind" }, h("option", { value: "" }, "All kinds"),
    [...new Set(nodes.map((n) => n.kind))].sort().map((k) => h("option", { value: k }, k.replace("_", " "))));
  const st = h("select", { "aria-label": "Status" }, ["active", "all", "missing", "disabled"].map((s) => h("option", { value: s }, s === "all" ? "All statuses" : s)));
  const list = h("ul.list.scroll", { role: "listbox", "aria-label": "Capabilities" });
  const detail = h("div.card.detail", {}, h("p.empty", {}, "Select a capability to see what it does, where it comes from and what it relates to."));
  const sims = edges.filter((e) => e.type === "similar_to" || (e.type === "related_to" && e.source === "auto:mention"));
  const draw = () => {
    const t = q.value.toLowerCase();
    const rows = nodes.filter((n) => (!kind.value || n.kind === kind.value) && (st.value === "all" || n.status === st.value)
      && (!t || (n.title + " " + n.summary).toLowerCase().includes(t)));
    const groups = Map.groupBy ? Map.groupBy(rows, (n) => n.origin || "user") : rows.reduce((m, n) => m.set(n.origin || "user", [...(m.get(n.origin || "user") || []), n]), new Map());
    fill(list, ...(rows.length ? [...groups].sort().flatMap(([g, ns]) => [h("li.group-label", { role: "presentation" }, `${g} · ${ns.length}`),
      ...ns.map((n) => h("li.item", { role: "option", tabindex: 0, "aria-selected": "false",
        onclick: (e) => select(e.currentTarget, n), onkeydown: (e) => e.key === "Enter" && select(e.currentTarget, n) },
        h("div.title", {}, h("span", {}, n.title), kindChip(n.kind), n.status !== "active" ? status(n.status) : null),
        h("div.desc", {}, n.summary || "No description on disk.")))]) : [h("li.empty", {}, "No capability matches these filters.")]));
  };
  const select = (li, n) => {
    list.querySelectorAll("[aria-selected=true]").forEach((x) => x.setAttribute("aria-selected", "false"));
    li.setAttribute("aria-selected", "true");
    showNode(detail, n.id);
  };
  [q, kind, st].forEach((c) => c.addEventListener("input", draw));
  draw();
  setView(h("h1", {}, "Capabilities"),
    h("p.lede", {}, `${nodes.filter((n) => n.status === "active").length} active capabilities discovered on disk. Overlaps are measured, not assumed: ${sims.length} relation(s) between skills found automatically.`),
    h("div.filters", {}, q, kind, st),
    h("div.grid.split", {}, h("div.card", {}, list), detail),
    h("div.card", {}, h("h2", {}, "Detected overlaps and mentions"),
      sims.length ? h("table.data", {}, h("thead", {}, h("tr", {}, ["From", "Relation", "To", "Source", "Confidence"].map((x) => h("th", {}, x)))),
        h("tbody", {}, sims.map((e) => h("tr", {}, h("td", {}, short(e.src)), h("td", {}, e.type), h("td", {}, short(e.dst)),
          h("td.muted", {}, e.source), h("td.num", {}, e.confidence.toFixed(2)))))) : h("p.empty", {}, "None detected.")));
};

// ---------- node detail (shared by capabilities & memory) ----------
async function showNode(panel, id, { editable = false } = {}) {
  fill(panel, loading());
  let d;
  try { d = await api(`/api/node?id=${encodeURIComponent(id)}`); } catch (e) { return fill(panel, errorBox(e)); }
  const n = d.node;
  const rel = d.edges.map((e) => {
    const other = e.src === n.id ? e.dst : e.src, dir = e.src === n.id ? "→" : "←";
    return h("li.row.between", {}, h("span", {}, `${dir} ${e.type} `, h("span.mono", {}, other)),
      h("span.row", {}, h("span.small.muted", {}, `${e.source} · ${e.confidence.toFixed(2)}`),
        editable ? h("button.btn.ghost.small.danger", { type: "button", onclick: async () => {
          await api("/api/unlink", e); toast("Relation removed."); showNode(panel, id, { editable });
        } }, "Remove") : null));
  });
  const v = n.validity;
  fill(panel, 
    h("div.row", {}, kindChip(n.kind), status(n.status)),
    h("h3", {}, n.title),
    h("p.muted.mono", {}, n.id),
    v && v.status === "stale" ? h("div.error-box", {}, `Sources changed since this was recorded: ${v.changed.join(", ")}`,
      editable ? h("div", {}, h("button.btn.small", { type: "button", onclick: async () => {
        await api("/api/revalidate", { id }); toast("Marked as still valid with current files."); showNode(panel, id, { editable });
      } }, "Still valid: revalidate")) : null) : null,
    editable ? editor(n, panel) : h("p", {}, n.summary || h("span.muted", {}, "No description.")),
    !editable && n.body ? h("div.body-text", {}, n.body) : null,
    h("dl", {},
      h("dt", {}, "Source"), h("dd", {}, n.source),
      h("dt", {}, "Reference"), h("dd.mono", {}, n.ref || "—"),
      h("dt", {}, "Project"), h("dd", {}, n.project || "—"),
      h("dt", {}, "Confidence"), h("dd", {}, n.confidence.toFixed(2)),
      h("dt", {}, "Used / useful"), h("dd", {}, `${n.uses} / ${n.successes}`),
      h("dt", {}, "Created"), h("dd", {}, fmtDate(n.created)),
      h("dt", {}, "Verified"), h("dd", {}, fmtDate(n.verified)),
      n.fingerprint ? [h("dt", {}, "Depends on"), h("dd.mono", {}, Object.keys(n.fingerprint).join("\n"))] : null,
      Object.keys(n.meta || {}).length ? [h("dt", {}, "Metadata"), h("dd.mono", {}, JSON.stringify(n.meta))] : null),
    h("h2", {}, `Relations (${d.edges.length})`),
    rel.length ? h("ul.list.stack", {}, rel) : h("p.muted.small", {}, "No relations."),
    editable ? linkForm(n, panel) : null,
    h("h2", {}, `History (${d.history.length})`),
    d.history.length ? h("ul.list.stack", {}, d.history.map((x) => h("li.row.between", {},
      h("span.small", {}, `${fmtDate(x.ts)} · ${x.op} · “${(x.snapshot.summary || "").slice(0, 60)}”`),
      editable ? h("button.btn.ghost.small", { type: "button", onclick: async () => {
        await api("/api/restore", { history_id: x.history_id }); toast("Previous version restored (the current one is kept in history)."); showNode(panel, id, { editable });
      } }, "Restore") : null))) : h("p.muted.small", {}, "No previous versions."));
}

function editor(n, panel) {
  const f = (name, el) => h("label", {}, name, el);
  const title = h("input", { value: n.title }), summary = h("textarea", {}), body = h("textarea", {}), tags = h("input", { value: n.tags });
  const conf = h("input", { type: "number", min: 0, max: 1, step: 0.05, value: n.confidence });
  summary.value = n.summary; body.value = n.body || "";
  const save = async (ev) => {
    ev.preventDefault();
    try {
      const r = await api("/api/node", { id: n.id, title: title.value, summary: summary.value, body: body.value, tags: tags.value, confidence: conf.value });
      toast(r.result === "unchanged" ? "No change." : "Saved. The previous version is in history."); showNode(panel, n.id, { editable: true }); refreshList?.();
    } catch (e) { toast(e.message, true); }
  };
  const del = async () => {
    if (!confirm(`Delete “${n.title}”? It stays restorable from history.`)) return;
    await api("/api/delete", { id: n.id }); toast("Deleted (restorable)."); fill(panel, h("p.empty", {}, "Entry deleted.")); refreshList?.();
  };
  return h("form.stack", { onsubmit: save }, f("Title", title), f("Summary", summary), f("Body", body),
    h("div.grid", {}, f("Tags", tags), f("Confidence (0–1)", conf)),
    h("div.row", {}, h("button.btn.primary", { type: "submit" }, "Save"), h("button.btn.danger", { type: "button", onclick: del }, "Delete")));
}

function linkForm(n, panel) {
  const other = h("input", { placeholder: "other entry id", "aria-label": "Other entry id" });
  const type = h("select", { "aria-label": "Relation type" });
  api("/api/edge-types").then((ts) => fill(type, ...ts.map((t) => h("option", { value: t }, t))));
  const merge = h("input", { placeholder: "merge this entry into… (id)", "aria-label": "Merge target id" });
  return h("div.stack", {},
    h("form.row", { onsubmit: async (e) => { e.preventDefault();
      try { await api("/api/link", { src: n.id, dst: other.value.trim(), type: type.value }); toast("Relation added."); showNode(panel, n.id, { editable: true }); }
      catch (err) { toast(err.message, true); } } }, other, type, h("button.btn", { type: "submit" }, "Link")),
    h("form.row", { onsubmit: async (e) => { e.preventDefault();
      if (!confirm(`Merge “${n.title}” into ${merge.value}? This entry is then deleted (restorable).`)) return;
      try { await api("/api/merge", { src: n.id, dst: merge.value.trim() }); toast("Merged."); showNode(panel, merge.value.trim(), { editable: true }); refreshList?.(); }
      catch (err) { toast(err.message, true); } } }, merge, h("button.btn", { type: "submit" }, "Merge")));
}

// ---------- memory inspector ----------
let refreshList = null;
views.memory = async () => {
  setView(h("h1", {}, "Memory"), loading());
  const q = h("input", { type: "search", placeholder: "Filter memory", "aria-label": "Filter memory" });
  const kinds = ["experience", "decision", "knowledge"];
  let active = "all";
  const seg = h("div.seg", { role: "group", "aria-label": "Kind" }, ["all", ...kinds].map((k) =>
    h("button", { type: "button", "aria-pressed": String(k === "all"), onclick: (e) => {
      active = k; seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.target))); draw(); } }, k)));
  const list = h("ul.list.scroll", { role: "listbox", "aria-label": "Memory entries" });
  const detail = h("div.card.detail", {}, h("p.empty", {}, "Select an entry to read, edit, link, merge or restore it."));
  let nodes = [];
  const draw = () => {
    const t = q.value.toLowerCase();
    const rows = nodes.filter((n) => (active === "all" || n.kind === active) && (!t || (n.title + " " + n.summary + " " + n.tags).toLowerCase().includes(t)));
    fill(list, ...(rows.length ? rows.map((n) => h("li.item", { role: "option", tabindex: 0, "aria-selected": "false",
      onclick: (e) => pick(e.currentTarget, n), onkeydown: (e) => e.key === "Enter" && pick(e.currentTarget, n) },
      h("div.title", {}, h("span", {}, n.title), kindChip(n.kind), n.status !== "active" ? status(n.status) : null),
      h("div.desc", {}, n.summary), n.project ? h("div.small.muted", {}, `project: ${n.project}`) : null))
      : [h("li.empty", {}, nodes.length ? "Nothing matches." : "Memory is empty. Claude fills it with nexus_remember, or use `nexus remember` in a terminal.")]));
  };
  const pick = (li, n) => {
    list.querySelectorAll("[aria-selected=true]").forEach((x) => x.setAttribute("aria-selected", "false"));
    li.setAttribute("aria-selected", "true");
    showNode(detail, n.id, { editable: true });
  };
  refreshList = async () => { nodes = await api(`/api/nodes?kinds=${kinds.join(",")}`); draw(); };
  q.addEventListener("input", draw);
  await refreshList();
  setView(h("h1", {}, "Memory"),
    h("p.lede", {}, "What the agent has learned. Edits, deletions and merges are versioned and can be restored. Entries tied to files are flagged stale when those files change."),
    h("div.filters", {}, q, seg), h("div.grid.split", {}, h("div.card", {}, list), detail));
};

// ---------- projects ----------
views.projects = async () => {
  setView(h("h1", {}, "Projects"), loading());
  const nodes = (await api("/api/nodes?kinds=project")).sort((a, b) => a.title.localeCompare(b.title));
  const detail = h("div.card.detail", {}, h("p.empty", {}, "Select a project to see its indexes and what NEXUS can reuse."));
  const open = async (li, n) => {
    document.querySelectorAll("#view .item[aria-selected=true]").forEach((x) => x.setAttribute("aria-selected", "false"));
    li.setAttribute("aria-selected", "true");
    fill(detail, loading());
    try {
      const c = await api(`/api/project?ref=${encodeURIComponent(n.title)}`);
      const g = c.providers.graphify, cx = c.providers.cortex;
      fill(detail, h("h3", {}, c.project.title), h("p.mono.muted", {}, c.project.ref),
        h("p", {}, c.advice),
        h("h2", {}, "Indexes"),
        cx ? h("p", {}, `Cortex: ${cx.files} files, ${cx.symbols} symbols (${cx.languages.join(", ")}). Query with cortex_pack / cortex_ask.`) : h("p.muted", {}, "Not indexed by Cortex."),
        g ? h("div", {}, h("p", {}, `Graphify: ${g.nodes} nodes, ${g.edges} edges. `, g.stale ? h("span.warn", {}, `⚠ stale: built at ${String(g.built_at_commit).slice(0, 8)}, HEAD ${String(g.head).slice(0, 8)}`) : status("active")),
          g.communities.length ? h("p.small.muted", {}, "Communities: " + g.communities.join(" · ")) : null) : h("p.muted", {}, "No Graphify graph."),
        h("h2", {}, `Remembered (${c.entries.active.length} valid · ${c.entries.stale.length} stale)`),
        [...c.entries.stale, ...c.entries.active].map((e) => h("div.pick", {}, h("div.row", {}, kindChip(e.kind), status(e.changed?.length ? "stale" : "active"), h("strong", {}, e.title)),
          h("p.small.muted", {}, e.summary), e.changed?.length ? h("p.small.warn", {}, "Changed: " + e.changed.join(", ")) : null)),
        c.changed_files.length ? h("p.small", {}, `${c.changed_files.length} changed file(s) to re-check.`) : null);
    } catch (e) { fill(detail, errorBox(e)); }
  };
  setView(h("h1", {}, "Projects"),
    h("p.lede", {}, "Projects NEXUS knows, where their understanding already lives (Cortex, Graphify, CLAUDE.md), and whether it is still current."),
    h("div.grid.split", {},
      h("div.card", {}, nodes.length ? h("ul.list", {}, nodes.map((n) => h("li.item", { tabindex: 0, "aria-selected": "false",
        onclick: (e) => open(e.currentTarget, n), onkeydown: (e) => e.key === "Enter" && open(e.currentTarget, n) },
        h("div.title", {}, h("span", {}, n.title), n.status !== "active" ? status(n.status) : null),
        h("div.desc", {}, n.summary)))) : h("p.empty", {}, "No project found. Add folders to project_roots in ~/.nexus/config.toml, then Sync.")),
      detail));
};

// ---------- router & sync ----------
async function route() {
  const name = (location.hash.match(/^#\/(\w+)/) || [, "dashboard"])[1];
  const view = views[name] ? name : "dashboard";
  document.querySelectorAll("nav a").forEach((a) => a.dataset.view === view ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  try { await views[view](); } catch (e) { setView(h("h1", {}, "NEXUS"), errorBox(e)); }
}
document.getElementById("sync").addEventListener("click", async (e) => {
  const b = e.currentTarget, state = document.getElementById("sync-state");
  b.disabled = true; state.textContent = "Syncing…";
  try {
    const r = await api("/api/sync", {});
    const c = r.capabilities, p = r.projects;
    state.textContent = `Capabilities +${c.created} ~${c.updated} −${c.missing} · projects +${p.created} −${p.missing} · ${r.stale.length} stale`;
    route();
  } catch (err) { state.textContent = ""; toast(err.message, true); }
  b.disabled = false;
});
if (!token) setView(h("h1", {}, "NEXUS"), h("div.error-box", {}, "No access token. Open the UI with the link printed by `nexus ui`."));
else { addEventListener("hashchange", route); route(); }
