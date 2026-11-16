"use strict";

const view = document.getElementById("view");
const modal = document.getElementById("modal");
let meta = null;
let pollTimer = null;

/* ---------- utilities ---------- */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtScore = (n) => (n == null ? "–" : Number(n).toFixed(n % 1 ? 1 : 0));
const LIVE = new Set(["starting", "running"]);
const STATUS_LABEL = {
  starting: "Starting", running: "Running", completed: "Completed", completed_with_errors: "Completed with errors",
  cancelled: "Cancelled", building: "Building", built: "Built", revising: "Revising", passed: "Meets target",
  below_target: "Below target", out_of_rounds: "Out of rounds", build_failed: "Build failed",
};
const pill = (status) => `<span class="pill ${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>`;

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function timeAgo(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
function duration(from, to) {
  const s = Math.round((to || Date.now() / 1000) - from);
  const m = Math.floor(s / 60);
  return m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const latest = (v) => (v.rounds && v.rounds.length ? v.rounds[v.rounds.length - 1] : null);

/* ---------- theme ---------- */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("pagesmith-theme", t); } catch (_) { /* storage unavailable */ }
}
(function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("pagesmith-theme"); } catch (_) { /* ignore */ }
  applyTheme(saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  document.getElementById("theme-toggle").addEventListener("click", () =>
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
})();

/* ---------- modal ---------- */
function openModal(title, html, href) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = html;
  const open = document.getElementById("modal-open");
  open.hidden = !href;
  if (href) open.href = href;
  modal.hidden = false;
  document.body.style.overflow = "hidden";
}
function closeModal() {
  modal.hidden = true;
  document.getElementById("modal-body").innerHTML = "";
  document.body.style.overflow = "";
}
modal.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeModal(); });

/* ---------- router ---------- */
function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
}
async function route() {
  clearTimeout(pollTimer);
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/runs\/([\w-]+)/);
  if (!meta) meta = await api("/api/meta").catch(() => ({ builders: [], briefs: [] }));
  if (m) { setNav("runs"); return renderRun(m[1], true); }
  if (hash.startsWith("#/new")) { setNav("new"); return renderNew(); }
  setNav("runs");
  return renderRuns();
}
window.addEventListener("hashchange", route);

/* ---------- runs list ---------- */
async function renderRuns() {
  const runs = await api("/api/runs").catch(() => []);
  const head = `
    <div class="page-head">
      <div><h1>Runs</h1><p>Every run builds one landing page per audience, scores each page with the audit, and keeps iterating until the target score is reached.</p></div>
      <a class="btn btn-primary" href="#/new">＋ New run</a>
    </div>`;
  if (!runs.length) {
    view.innerHTML = head + document.getElementById("tpl-empty").innerHTML;
    return;
  }
  view.innerHTML = head + `
    <div class="card">
      <table class="runs-table">
        <thead><tr><th>Product</th><th>Status</th><th>Best score</th><th>Variants</th><th>Started</th></tr></thead>
        <tbody>${runs.map((r) => `
          <tr data-run="${esc(r.id)}">
            <td><div class="product">${esc(r.product)}</div><div class="subtle mono">${esc(r.id)}</div></td>
            <td>${pill(r.status)}</td>
            <td class="score-inline">${fmtScore(r.best_score)}<span class="subtle"> / 100</span></td>
            <td>${r.variants}</td>
            <td class="muted">${timeAgo(r.created_at)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
  view.querySelectorAll("[data-run]").forEach((tr) => tr.addEventListener("click", () => { location.hash = `#/runs/${tr.dataset.run}`; }));
  if (runs.some((r) => LIVE.has(r.status))) pollTimer = setTimeout(renderRuns, 4000);
}

/* ---------- run detail ---------- */
function ring(score, colour, target) {
  const r = 30, c = 2 * Math.PI * r, pct = Math.max(0, Math.min(100, score || 0)) / 100;
  const stroke = score >= target ? "var(--good)" : colour;
  return `<div class="ring" aria-label="Score ${fmtScore(score)} out of 100">
    <svg viewBox="0 0 72 72"><circle class="track" cx="36" cy="36" r="${r}" fill="none" stroke-width="7"/>
    <circle class="bar" cx="36" cy="36" r="${r}" fill="none" stroke="${stroke}" stroke-width="7" stroke-linecap="round"
      stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - pct)}"/></svg>
    <div class="num"><div>${fmtScore(score)}<small>/ 100</small></div></div></div>`;
}

function chart(state) {
  const variants = Object.values(state.variants).filter((v) => v.rounds && v.rounds.length);
  const maxRound = Math.max(state.max_rounds, 1);
  const W = 1000, H = 240, L = 36, R = 20, T = 14, B = 28;
  // Zoom the y-axis onto the scores (the interesting movement is usually in the top band).
  const all = variants.flatMap((v) => v.rounds.map((r) => r.score)).concat(state.target);
  const span = Math.min(100, Math.ceil((100 - Math.min(...all) + 2) / 4) * 4);
  const lo = 100 - span, hi = 100;
  const ticks = Array.from({ length: 5 }, (_, i) => Math.round(lo + ((hi - lo) * i) / 4));
  const x = (round) => L + (maxRound === 1 ? (W - L - R) / 2 : ((round - 1) / (maxRound - 1)) * (W - L - R));
  const y = (s) => T + (1 - (s - lo) / (hi - lo)) * (H - T - B);
  const grid = ticks.map((g) => `<line x1="${L}" x2="${W - R}" y1="${y(g)}" y2="${y(g)}"/><text x="${L - 8}" y="${y(g) + 4}" text-anchor="end">${g}</text>`).join("");
  const xs = Array.from({ length: maxRound }, (_, i) => `<text x="${x(i + 1)}" y="${H - 6}" text-anchor="middle">Round ${i + 1}</text>`).join("");
  const lines = variants.map((v) => {
    const pts = v.rounds.map((r) => [x(r.round), y(r.score)]);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    const dots = v.rounds.map((r) => `<circle cx="${x(r.round)}" cy="${y(r.score)}" r="5" fill="var(--surface)" stroke="${v.colour}" stroke-width="2.5"><title>${esc(v.framework)} · round ${r.round}: ${fmtScore(r.score)}</title></circle>`).join("");
    return `<path d="${d}" fill="none" stroke="${v.colour}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>${dots}`;
  }).join("");
  const target = `<line class="target" x1="${L}" x2="${W - R}" y1="${y(state.target)}" y2="${y(state.target)}"/><text class="target-label" x="${W - R}" y="${y(state.target) - 6}" text-anchor="end">Target ${state.target}</text>`;
  const legend = Object.values(state.variants).map((v) => `<span><i class="dot" style="background:${v.colour}"></i>${esc(v.framework)}</span>`).join("");
  return `<div class="card chart-card chart">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Score by round">
      <g class="grid">${grid}</g><g class="axis">${xs}</g>${target}${lines}</svg>
    <div class="legend">${legend || '<span class="subtle">Scores appear after the first audit.</span>'}</div></div>`;
}

function variantCard(state, v, winnerKey) {
  const last = latest(v);
  const score = last ? last.score : null;
  const cats = last ? Object.values(last.categories) : [];
  const history = (v.rounds || []).map((r) => `<span class="step">${fmtScore(r.score)}</span>`).join('<span class="arrow">→</span>');
  const pageUrl = `/runs/${state.id}/pages/${v.key}/`;
  return `<article class="card variant ${v.key === winnerKey ? "winner" : ""}" style="--c:${v.colour}">
    <div class="variant-top">
      <div>
        <div class="name"><i class="dot" style="background:${v.colour}"></i>${esc(v.framework)}</div>
        <div class="aud">${esc(v.audience)}</div>
        <div class="variant-tags">${pill(v.status)}<span class="chip">Round ${v.round || 1} / ${state.max_rounds}</span>${v.key === winnerKey ? '<span class="badge-win">★ Top variant</span>' : ""}</div>
      </div>
      ${ring(score, v.colour, state.target)}
    </div>
    <div class="bars">${cats.map((c) => `
      <div class="bar-row"><span>${esc(c.label)}</span><div class="track"><div class="fill" style="width:${(c.score / c.max) * 100}%"></div></div><span class="val">${fmtScore(c.score)}/${c.max}</span></div>`).join("") || '<div class="subtle">Waiting for the first audit…</div>'}
    </div>
    ${history ? `<div class="history"><span class="subtle">Progress</span>${history}</div>` : ""}
    <div class="variant-actions">
      <button class="btn btn-sm" data-preview="${esc(v.key)}" ${last ? "" : "disabled"}>Preview page</button>
      <button class="btn btn-sm btn-ghost" data-audit="${esc(v.key)}" ${last ? "" : "disabled"}>Audit report</button>
    </div>
    <a hidden href="${pageUrl}"></a>
  </article>`;
}

function boardLanes(state) {
  const goals = state.board.filter((t) => t.parent_id == null);
  return Object.values(state.variants).map((v) => {
    const mine = goals.filter((g) => g.owner === v.key);
    const steps = state.board.filter((t) => t.owner === v.key && t.parent_id != null);
    const done = steps.filter((s) => s.status === "done").length;
    return `<div class="card lane">
      <div class="lane-head"><i class="dot" style="background:${v.colour}"></i>${esc(v.framework)}<span class="count">${done}/${steps.length} steps</span></div>
      ${mine.map((g) => `
        <div class="goal">
          <div class="goal-title"><span>Round ${g.round} · ${g.round === 1 ? "Build" : "Revision"}</span>${pill(g.status === "done" ? "completed" : g.status === "failed" ? "failed" : g.status === "in_progress" ? "running" : "starting")}</div>
          <ul class="steps">${state.board.filter((s) => s.parent_id === g.id).map((s) => `
            <li class="${esc(s.status)}"><span class="ic"></span><span class="txt">${esc(s.task)}</span></li>`).join("") || '<li><span class="ic"></span><span class="txt subtle">Planning…</span></li>'}
          </ul>
          ${g.result ? `<div class="goal-result">${esc(g.result)}</div>` : ""}
        </div>`).join("") || '<div class="subtle">Not started</div>'}
    </div>`;
  }).join("");
}

function stylePanel(st, runId) {
  if (!st) return "";
  const roles = COLOUR_ROLES.filter(([role]) => st[role]);
  return `<dt>Look &amp; feel</dt><dd>
    ${st.reference ? `<a href="/runs/${esc(runId)}/reference" target="_blank" rel="noopener"><img class="ref-thumb" src="/runs/${esc(runId)}/reference" alt="Reference screenshot"></a>` : ""}
    ${roles.length ? `<div class="swatch-chips">${roles.map(([role, label]) => `<span class="chip"><i class="dot" style="background:${esc(st[role])}"></i>${label} <span class="mono">${esc(st[role])}</span></span>`).join("")}</div>` : ""}
    ${st.font ? `<div class="subtle" style="margin-top:6px">Type: ${esc(st.font)}</div>` : ""}
    ${st.notes ? `<div class="subtle" style="margin-top:4px">${esc(st.notes)}</div>` : ""}
  </dd>`;
}

function briefPanel(b, runId) {
  return `<dl class="brief-list">
    <dt>Description</dt><dd>${esc(b.description)}</dd>
    <dt>Keywords</dt><dd class="tags">${b.keywords.map((k) => `<span class="chip">${esc(k)}</span>`).join("")}</dd>
    <dt>Features</dt><dd>${b.features.map(esc).join(" · ")}</dd>
    <dt>Call to action</dt><dd>${esc(b.call_to_action)}</dd>
    ${stylePanel(b.style, runId)}
  </dl>`;
}

async function renderRun(id, first) {
  if (first) view.innerHTML = '<div class="skeleton"></div>';
  let state;
  try {
    state = await api(`/api/runs/${id}`);
  } catch (err) {
    view.innerHTML = `<div class="empty"><h2>Run not found</h2><p>${esc(err.message)}</p><a class="btn" href="#/">Back to runs</a></div>`;
    return;
  }
  const variants = Object.values(state.variants);
  const scored = variants.filter(latest);
  const scores = scored.map((v) => latest(v).score);
  const best = scores.length ? Math.max(...scores) : null;
  const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
  const firstAvg = scored.length ? scored.reduce((a, v) => a + v.rounds[0].score, 0) / scored.length : null;
  const passing = scored.filter((v) => latest(v).score >= state.target).length;
  const steps = state.board.filter((t) => t.parent_id != null);
  const winner = scored.length ? scored.reduce((a, b) => (latest(b).score > latest(a).score ? b : a)) : null;
  const live = LIVE.has(state.status);

  view.innerHTML = `
    <div class="run-head">
      <div>
        <a class="subtle" href="#/" style="text-decoration:none">← All runs</a>
        <h1 style="margin-top:6px">${esc(state.brief.product)} ${pill(state.status)}</h1>
        <p class="tagline">${esc(state.brief.tagline)}</p>
        <div class="meta-row">
          <span class="chip">Target ${state.target}</span>
          <span class="chip">Up to ${state.max_rounds} rounds</span>
          <span class="chip">Lead · ${esc(state.orchestrator_model)}</span>
          <span class="chip">Builders · ${esc(state.builder_model)}</span>
          <span class="chip">${live ? "Running for" : "Took"} ${duration(state.created_at, state.finished_at)}</span>
        </div>
      </div>
    </div>

    <div class="kpis">
      <div class="card kpi"><div class="label">Best score</div><div class="value">${fmtScore(best)}<small>/100</small></div></div>
      <div class="card kpi"><div class="label">Average score</div><div class="value">${avg == null ? "–" : avg.toFixed(1)}</div>${avg != null && avg - firstAvg > 0.05 ? `<div class="delta">▲ ${(avg - firstAvg).toFixed(1)} since round 1</div>` : '<div class="subtle">&nbsp;</div>'}</div>
      <div class="card kpi"><div class="label">Meeting target</div><div class="value">${passing}<small>/ ${variants.length}</small></div></div>
      <div class="card kpi"><div class="label">Rounds run</div><div class="value">${variants.reduce((a, v) => a + (v.rounds || []).length, 0)}</div></div>
      <div class="card kpi"><div class="label">Board steps done</div><div class="value">${steps.filter((s) => s.status === "done").length}<small>/ ${steps.length}</small></div></div>
    </div>

    ${state.summary ? `<div class="card summary"><div><strong>Lead's summary</strong>${esc(state.summary)}</div></div>` : ""}

    <div class="section-title"><h2>Score by round</h2><span>Every point comes from the automated audit</span></div>
    ${chart(state)}

    <div class="section-title"><h2>Variants</h2><span>${variants.length} audiences</span></div>
    <div class="variants">${variants.map((v) => variantCard(state, v, winner && winner.key)).join("") || '<div class="subtle">The lead is assigning audiences…</div>'}</div>

    <div class="section-title"><h2>Task board</h2><span>${live ? "Live" : "Final state"}</span></div>
    <div class="board">${boardLanes(state)}</div>

    <div class="two-col" style="margin-top:32px">
      <div><div class="section-title" style="margin-top:0"><h2>Activity</h2></div>
        <div class="card"><ul class="timeline">${state.log.slice().reverse().map((e) => `
          <li><time>${clock(e.at)}</time><span class="k-${esc(e.kind)}">${esc(e.message)}</span></li>`).join("")}</ul></div></div>
      <div><div class="section-title" style="margin-top:0"><h2>Brief</h2></div><div class="card">${briefPanel(state.brief, state.id)}</div></div>
    </div>`;

  view.querySelectorAll("[data-preview]").forEach((b) => b.addEventListener("click", () => {
    const v = state.variants[b.dataset.preview];
    const url = `/runs/${state.id}/pages/${v.key}/`;
    openModal(`${v.framework} · ${v.audience}`, `<iframe src="${url}" title="Landing page preview"></iframe>`, url);
  }));
  view.querySelectorAll("[data-audit]").forEach((b) => b.addEventListener("click", () => showAudit(state, b.dataset.audit)));

  // Deep links: #/runs/<id>?audit=<key> or ?preview=<key> open straight into a variant.
  if (first) {
    const params = new URLSearchParams((location.hash.split("?")[1]) || "");
    const audit = params.get("audit"), preview = params.get("preview");
    if (audit && state.variants[audit]) showAudit(state, audit);
    else if (preview && state.variants[preview]) view.querySelector(`[data-preview="${CSS.escape(preview)}"]`)?.click();
  }

  if (live) pollTimer = setTimeout(() => renderRun(id, false), 2000);
}

async function showAudit(state, key) {
  const v = state.variants[key];
  openModal(`Audit · ${v.framework}`, '<div class="pad"><div class="skeleton"></div></div>');
  const a = await api(`/api/runs/${state.id}/variants/${key}/audit`);
  const cats = Object.values(a.categories).map((c) => `<div class="card"><div class="subtle">${esc(c.label)}</div><div class="v">${fmtScore(c.score)}<span class="subtle"> / ${c.max}</span></div></div>`).join("");
  const rows = a.checks.slice().sort((x, y) => y.lost - x.lost).map((c) => `
    <tr><td class="${c.lost ? "ko" : "ok"}">${c.lost ? "−" + fmtScore(c.lost) : "✓"}</td>
      <td><strong>${esc(c.label)}</strong><div class="hint">${esc(c.detail)}</div>${c.lost ? `<div class="hint">→ ${esc(c.hint)}</div>` : ""}</td>
      <td class="subtle">${esc(c.category)}</td><td style="text-align:right">${fmtScore(c.earned)} / ${c.points}</td></tr>`).join("");
  document.getElementById("modal-body").innerHTML = `<div class="pad">
    <p style="margin-top:0"><span style="font-size:32px;font-weight:750">${fmtScore(a.score)}</span><span class="subtle"> / 100 · grade ${a.grade}</span></p>
    <div class="audit-cats">${cats}</div>
    <table class="checks"><thead><tr><th></th><th>Check</th><th>Category</th><th style="text-align:right">Points</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

/* ---------- new run ---------- */
const BLANK_BRIEF = {
  product: "", tagline: "", description: "", features: ["", "", ""], pricing: [],
  keywords: [], audiences: [""], call_to_action: "Start free trial", tone: "confident, clear, no hype",
};
const COLOUR_ROLES = [
  ["primary", "Primary", "Buttons and links"],
  ["accent", "Accent", "Badges and highlights"],
  ["background", "Background", "Page background"],
  ["surface", "Surface", "Cards and bands"],
  ["text", "Text", "Headings and copy"],
];
const PREVIEW_FALLBACK = { primary: "#5b5bd6", accent: "#f59e0b", background: "#ffffff", surface: "#f3f3f7", text: "#1a1a22" };
const HEX = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i;
const normHex = (v) => {
  const m = HEX.exec(String(v || "").trim());
  if (!m) return null;
  const d = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
  return `#${d.toLowerCase()}`;
};
const emptyStyle = () => ({ primary: null, accent: null, background: null, surface: null, text: null, font: "", notes: "" });

function normaliseBrief(b = {}) {
  return {
    ...BLANK_BRIEF, ...b,
    features: [...(b.features || BLANK_BRIEF.features)],
    keywords: [...(b.keywords || [])],
    audiences: [...(b.audiences || BLANK_BRIEF.audiences)],
    pricing: (b.pricing || []).map((t) => ({ name: t.name || "", price: t.price || "", includes: [...(t.includes || [])] })),
    style: { ...emptyStyle(), ...(b.style || {}) },
  };
}

function cleanStyle(st) {
  const out = {};
  COLOUR_ROLES.forEach(([role]) => { const h = normHex(st[role]); if (h) out[role] = h; });
  if (st.font && st.font.trim()) out.font = st.font.trim();
  if (st.notes && st.notes.trim()) out.notes = st.notes.trim();
  return Object.keys(out).length ? out : null;
}

function cleanBrief(d) {
  const list = (xs) => xs.map((x) => String(x).trim()).filter(Boolean);
  return {
    product: d.product.trim(), tagline: d.tagline.trim(), description: d.description.trim(),
    features: list(d.features), keywords: list(d.keywords), audiences: list(d.audiences),
    pricing: d.pricing
      .map((t) => ({ name: t.name.trim(), price: t.price.trim(), includes: list(t.includes) }))
      .filter((t) => t.name || t.price),
    call_to_action: d.call_to_action.trim() || BLANK_BRIEF.call_to_action,
    tone: d.tone.trim() || BLANK_BRIEF.tone,
    ...(cleanStyle(d.style) ? { style: cleanStyle(d.style) } : {}),
  };
}

function briefProblems(b) {
  const out = [];
  if (!b.product) out.push(["f-product", "Give the product a name."]);
  if (!b.tagline) out.push(["f-tagline", "Add a one-line tagline."]);
  if (!b.description) out.push(["f-description", "Describe what the product does."]);
  if (b.features.length < 3) out.push(["list-features", `List at least 3 features (${b.features.length} so far).`]);
  if (!b.audiences.length) out.push(["list-audiences", "Add at least one audience."]);
  if (!b.keywords.length) out.push(["tags-keywords", "Add at least one search keyword."]);
  b.pricing.forEach((t, i) => { if (!t.name || !t.price) out.push([`tier-${i}`, `Pricing plan ${i + 1} needs a name and a price.`]); });
  return out;
}

function colourProblems(st) {
  const out = [];
  COLOUR_ROLES.forEach(([role, label]) => {
    if (st[role] && !normHex(st[role])) out.push([`hex-${role}`, `${label} colour "${st[role]}" is not a hex colour like #56cfe1.`]);
  });
  return out;
}

const getPath = (obj, path) => path.split(".").reduce((o, k) => o[k], obj);

function textInput(id, key, value, placeholder) {
  return `<input type="text" id="${id}" data-key="${key}" value="${esc(value)}" placeholder="${esc(placeholder)}">`;
}

function listRows(name, items, placeholder, addLabel) {
  const rows = items.map((v, i) => `
    <div class="list-row">
      <span class="list-num">${i + 1}</span>
      <input type="text" data-list="${name}" data-index="${i}" value="${esc(v)}" placeholder="${esc(placeholder)}">
      <button type="button" class="icon-x" data-remove="${name}" data-index="${i}" aria-label="Remove">×</button>
    </div>`).join("");
  return `<div class="list-rows" id="list-${name}">${rows}</div>
    <button type="button" class="link-btn" data-add="${name}">+ ${esc(addLabel)}</button>`;
}

function tagBox(path, tags, placeholder, id = "") {
  const chips = tags.map((t, i) => `
    <span class="tag${i === 0 && path === "keywords" ? " primary" : ""}">${esc(t)}<button type="button" data-tag-remove="${path}" data-index="${i}" aria-label="Remove ${esc(t)}">×</button></span>`).join("");
  return `<div class="tag-box"${id ? ` id="${id}"` : ""}>${chips}<input type="text" data-tags="${path}" placeholder="${esc(tags.length ? "Add another…" : placeholder)}"></div>`;
}

function tierCard(t, i) {
  return `
    <div class="tier" id="tier-${i}">
      <div class="tier-head">
        <input type="text" data-tier="${i}" data-tier-key="name" value="${esc(t.name)}" placeholder="Plan name, e.g. Growth">
        <input type="text" data-tier="${i}" data-tier-key="price" value="${esc(t.price)}" placeholder="Price, e.g. $19/month">
        <button type="button" class="icon-x" data-remove-tier="${i}" aria-label="Remove plan">×</button>
      </div>
      ${tagBox(`pricing.${i}.includes`, t.includes, "What's included? Type and press Enter")}
    </div>`;
}

function swatchRow(st) {
  return COLOUR_ROLES.map(([role, label, hint]) => {
    const v = normHex(st[role]);
    return `
      <div class="swatch-field">
        <label class="swatch${v ? "" : " unset"}" style="--c:${v || "transparent"}" title="Pick the ${label.toLowerCase()} colour">
          <input type="color" data-colour="${role}" value="${v || "#ffffff"}" aria-label="${label} colour">
        </label>
        <div class="swatch-text">
          <span class="swatch-name">${label}</span>
          <input type="text" id="hex-${role}" data-hex="${role}" value="${esc(st[role] || "")}" placeholder="not set" maxlength="7" spellcheck="false" aria-label="${label} hex value">
          <span class="swatch-hint">${hint}</span>
        </div>
      </div>`;
  }).join("");
}

function stylePreview(st) {
  const c = (role) => normHex(st[role]) || PREVIEW_FALLBACK[role];
  return `<div class="style-preview" id="style-preview" style="--p:${c("primary")};--a:${c("accent")};--bg:${c("background")};--s:${c("surface")};--t:${c("text")}" aria-hidden="true">
    <div class="sp-band"><div class="sp-card">
      <span class="sp-badge">New</span>
      <div class="sp-h">Your headline here</div>
      <div class="sp-line"></div><div class="sp-line short"></div>
      <span class="sp-btn">Start free trial</span>
    </div></div>
  </div>`;
}

function dropzone(ref, status) {
  if (!ref) {
    return `<label class="dropzone" id="dropzone">
      <input type="file" id="ref-file" accept="image/png,image/jpeg,image/webp" hidden>
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/></svg>
      <strong>Drop a screenshot of a page you like</strong>
      <span>or click to choose one, or paste it with Ctrl/⌘ + V. Its colours and style are read automatically.</span>
    </label>`;
  }
  return `<div class="dropzone has-image" id="dropzone">
    <img src="${ref}" alt="Reference screenshot">
    <div class="ref-side">
      <div class="ref-status ${status?.kind || ""}">${status?.html || "This screenshot will be saved with the run."}</div>
      <div class="ref-actions">
        <button type="button" class="btn btn-sm" data-ref-read>Read colours again</button>
        <button type="button" class="btn btn-sm btn-ghost" data-ref-remove>Remove</button>
      </div>
    </div>
  </div>`;
}

function briefEditor(d, ref, refStatus) {
  return `
    <section class="form-section">
      <h3>Product</h3>
      <div class="field"><label for="f-product">Product name</label>${textInput("f-product", "product", d.product, "e.g. Ledgerly")}</div>
      <div class="field"><label for="f-tagline">Tagline</label>${textInput("f-tagline", "tagline", d.tagline, "e.g. Invoices that chase themselves.")}</div>
      <div class="field"><label for="f-description">Description</label>
        <textarea id="f-description" data-key="description" rows="4" placeholder="What it is, who it's for, and why it's better. Two or three sentences.">${esc(d.description)}</textarea></div>
      <div class="row-2">
        <div class="field"><label for="f-cta">Call to action</label>${textInput("f-cta", "call_to_action", d.call_to_action, "Start free trial")}</div>
        <div class="field"><label for="f-tone">Tone of voice</label>${textInput("f-tone", "tone", d.tone, "friendly, confident, plain English")}</div>
      </div>
    </section>
    <section class="form-section">
      <div class="section-row"><h3>Look &amp; feel</h3><span class="count">Optional</span></div>
      <p class="help">Show a page you like, or set the colours yourself. Builders follow them and the audit checks every colour is used.</p>
      <div id="ref-slot">${dropzone(ref, refStatus)}</div>
      <div class="style-grid">
        <div class="swatches">${swatchRow(d.style)}</div>
        ${stylePreview(d.style)}
      </div>
      <div class="row-2" style="margin-top:14px">
        <div class="field"><label for="f-font">Font feel</label>
          <input type="text" id="f-font" data-style="font" value="${esc(d.style.font)}" placeholder="e.g. rounded geometric sans, like Poppins">
          <span class="help">Pages use system fonts only, so builders pick the closest match.</span></div>
        <div class="field"><label for="f-notes">Design notes</label>
          <textarea id="f-notes" data-style="notes" rows="3" placeholder="e.g. centred white card on a mint band, square inputs, wide flat cyan button">${esc(d.style.notes)}</textarea></div>
      </div>
    </section>
    <section class="form-section">
      <div class="section-row"><h3>Features</h3><span class="count">${d.features.filter((x) => x.trim()).length} added · 3 minimum</span></div>
      <p class="help">What the product does, one per line. Builders turn these into the features section.</p>
      ${listRows("features", d.features, "e.g. Automatic payment reminders", "Add feature")}
    </section>
    <section class="form-section">
      <div class="section-row"><h3>Audiences</h3><span class="count" id="aud-count"></span></div>
      <p class="help">Who you're selling to. Each audience gets its own page from a different builder.</p>
      ${listRows("audiences", d.audiences, "e.g. Freelance designers and developers", "Add audience")}
    </section>
    <section class="form-section">
      <div class="section-row"><h3>Search keywords</h3><span class="count">${d.keywords.length ? "First one is the primary keyword" : ""}</span></div>
      <p class="help">Phrases people search for. Type one and press Enter. Every page is checked for them.</p>
      ${tagBox("keywords", d.keywords, "e.g. online invoicing software", "tags-keywords")}
    </section>
    <section class="form-section">
      <div class="section-row"><h3>Pricing</h3><span class="count">Optional</span></div>
      <p class="help">Plans shown in the pricing section. Leave empty and builders will skip prices.</p>
      <div class="tiers">${d.pricing.map(tierCard).join("")}</div>
      <button type="button" class="link-btn" data-add-tier>+ Add plan</button>
    </section>`;
}

async function renderNew() {
  const briefs = meta.briefs || [];
  view.innerHTML = `
    <div class="page-head"><div><h1>New run</h1><p>Describe the product once. Each builder takes a different audience, and the lead keeps sending pages back until they reach the target score.</p></div></div>
    <form class="form-grid" id="new-run" novalidate>
      <div class="card card-pad">
        <div class="brief-toolbar">
          <div class="field" style="margin:0;flex:1">
            <label for="sample">Start from</label>
            <select id="sample"><option value="">Blank brief</option>${briefs.map((b) => `<option value="${esc(b)}">Sample: ${esc(b)}</option>`).join("")}</select>
          </div>
          <div class="segmented" role="tablist" aria-label="Editor mode">
            <button type="button" class="active" data-mode="form">Form</button>
            <button type="button" data-mode="json">JSON</button>
          </div>
        </div>
        <div id="brief-editor"></div>
        <div id="brief-json-wrap" hidden>
          <textarea id="brief-json" spellcheck="false" aria-label="Product brief as JSON"></textarea>
          <span class="help">Paste a brief you already have. Switch back to Form to keep editing it there.</span>
        </div>
      </div>
      <div class="card card-pad sticky-card">
        <div id="form-error"></div>
        <div class="field">
          <label for="target">Target score <span class="range-value" id="target-val">${meta.target}</span></label>
          <input type="range" id="target" min="70" max="100" value="${meta.target}">
          <span class="help">Every page has to reach this on the 100-point audit.</span>
        </div>
        <div class="field">
          <label for="rounds">Rounds per builder</label>
          <input type="number" id="rounds" min="1" max="5" value="${meta.rounds}">
          <span class="help">The first build plus revisions, in total.</span>
        </div>
        <div class="field">
          <label>Builders</label>
          <div class="check-list">${meta.builders.map((b) => `
            <label class="check-item"><input type="checkbox" name="builder" value="${esc(b.key)}" checked><i class="dot" style="background:${b.colour}"></i>${esc(b.name)}</label>`).join("")}</div>
          <span class="help" id="variant-note"></span>
        </div>
        ${meta.token_required ? `<div class="field"><label for="token">Access token</label><input type="password" id="token" autocomplete="off"><span class="help">This deployment requires a token to start runs.</span></div>` : ""}
        <button class="btn btn-primary" type="submit" style="width:100%;justify-content:center">Start run</button>
      </div>
    </form>`;

  let draft = normaliseBrief(BLANK_BRIEF);
  let mode = "form";
  let ref = null;        // reference screenshot as a data URL
  let refStatus = null;  // { kind, html } shown next to it
  const editor = document.getElementById("brief-editor");
  const jsonWrap = document.getElementById("brief-json-wrap");
  const jsonBox = document.getElementById("brief-json");
  const error = document.getElementById("form-error");

  const updateNotes = () => {
    const audiences = draft.audiences.filter((a) => a.trim()).length;
    const builders = document.querySelectorAll("input[name=builder]:checked").length;
    const pages = Math.min(audiences, builders);
    const count = document.getElementById("aud-count");
    if (count) count.textContent = `${audiences} ${audiences === 1 ? "audience" : "audiences"}`;
    const note = document.getElementById("variant-note");
    if (!pages) note.textContent = builders ? "Add an audience to build a page." : "Pick at least one builder.";
    else if (audiences > builders) note.textContent = `${pages} pages: the first ${builders} ${builders === 1 ? "audience" : "audiences"} get a builder each.`;
    else note.textContent = `${pages} ${pages === 1 ? "page" : "pages"}, one per audience.`;
  };

  const render = (focus) => {
    editor.innerHTML = briefEditor(draft, ref, refStatus);
    updateNotes();
    if (focus) editor.querySelector(focus)?.focus();
  };

  // Colour changes repaint the swatch and preview in place, so pickers keep focus.
  const paintColour = (role) => {
    const v = normHex(draft.style[role]);
    const swatch = editor.querySelector(`[data-colour="${role}"]`)?.parentElement;
    if (swatch) { swatch.style.setProperty("--c", v || "transparent"); swatch.classList.toggle("unset", !v); }
    const preview = document.getElementById("style-preview");
    if (preview) preview.outerHTML = stylePreview(draft.style);
  };

  const renderRef = () => { document.getElementById("ref-slot").innerHTML = dropzone(ref, refStatus); };

  // Screenshots are scaled to at most 1600px wide before upload: plenty for colours and layout.
  const toDataUrl = (file) => new Promise((resolve, reject) => {
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) { reject(new Error("Use a PNG, JPG or WebP screenshot.")); return; }
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1600 / img.width, 6000 / img.height);
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      let url = canvas.toDataURL("image/png");
      if (url.length > 9_000_000) url = canvas.toDataURL("image/jpeg", 0.92);
      URL.revokeObjectURL(img.src);
      resolve(url);
    };
    img.onerror = () => reject(new Error("That file could not be opened as an image."));
    img.src = URL.createObjectURL(file);
  });

  const readReference = async () => {
    refStatus = { kind: "busy", html: '<span class="spinner"></span> Reading colours and style…' };
    renderRef();
    try {
      const token = document.getElementById("token");
      const res = await api("/api/style", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { "X-Access-Token": token.value } : {}) },
        body: JSON.stringify({ image: ref }),
      });
      draft.style = { ...emptyStyle(), ...res.style };
      refStatus = {
        kind: "ok",
        html: res.source === "model"
          ? "Colours, font feel and design notes read from your screenshot. Adjust anything below."
          : "Colours picked from the screenshot's pixels (the model could not describe it). Adjust anything below.",
      };
    } catch (err) {
      refStatus = { kind: "error", html: `Couldn't read it: ${esc(err.message)}. You can still set colours by hand.` };
    }
    render();
  };

  const useFile = async (file) => {
    if (!file) return;
    try { ref = await toDataUrl(file); } catch (err) {
      refStatus = { kind: "error", html: esc(err.message) };
      ref = null;
      renderRef();
      return;
    }
    await readReference();
  };

  editor.addEventListener("change", (e) => {
    if (e.target.id === "ref-file") useFile(e.target.files[0]);
  });
  editor.addEventListener("dragover", (e) => {
    const zone = e.target.closest(".dropzone");
    if (zone) { e.preventDefault(); zone.classList.add("drag"); }
  });
  editor.addEventListener("dragleave", (e) => e.target.closest(".dropzone")?.classList.remove("drag"));
  editor.addEventListener("drop", (e) => {
    const zone = e.target.closest(".dropzone");
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove("drag");
    useFile(e.dataTransfer.files[0]);
  });
  document.onpaste = (e) => {
    if (!document.getElementById("ref-slot") || mode !== "form") return;
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); useFile(item.getAsFile()); }
  };

  const addTag = (input) => {
    const value = input.value.trim().replace(/,$/, "").trim();
    if (!value) return false;
    const tags = getPath(draft, input.dataset.tags);
    if (!tags.includes(value)) tags.push(value);
    input.value = "";
    render(`[data-tags="${input.dataset.tags}"]`);
    return true;
  };

  editor.addEventListener("input", (e) => {
    const t = e.target;
    t.closest(".invalid")?.classList.remove("invalid");
    t.classList.remove("invalid");
    if (t.dataset.key) draft[t.dataset.key] = t.value;
    else if (t.dataset.style) draft.style[t.dataset.style] = t.value;
    else if (t.dataset.colour) {
      draft.style[t.dataset.colour] = t.value;
      const hex = editor.querySelector(`[data-hex="${t.dataset.colour}"]`);
      if (hex) hex.value = t.value;
      paintColour(t.dataset.colour);
    } else if (t.dataset.hex) {
      draft.style[t.dataset.hex] = t.value.trim() || null;
      const v = normHex(t.value);
      const picker = editor.querySelector(`[data-colour="${t.dataset.hex}"]`);
      if (v && picker) picker.value = v;
      paintColour(t.dataset.hex);
    }
    else if (t.dataset.list) { draft[t.dataset.list][Number(t.dataset.index)] = t.value; updateNotes(); }
    else if (t.dataset.tier) draft.pricing[Number(t.dataset.tier)][t.dataset.tierKey] = t.value;
    else if (t.dataset.tags && t.value.includes(",")) addTag(t);
  });

  editor.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t.dataset.tags) {
      if (e.key === "Enter") { e.preventDefault(); addTag(t); }
      else if (e.key === "Backspace" && !t.value) {
        const tags = getPath(draft, t.dataset.tags);
        if (tags.length) { tags.pop(); render(`[data-tags="${t.dataset.tags}"]`); }
      }
    } else if (t.dataset.list && e.key === "Enter") {
      e.preventDefault();
      const list = draft[t.dataset.list];
      const i = Number(t.dataset.index);
      list.splice(i + 1, 0, "");
      render(`[data-list="${t.dataset.list}"][data-index="${i + 1}"]`);
    } else if (t.tagName === "INPUT" && e.key === "Enter") {
      e.preventDefault();
    }
  });

  editor.addEventListener("focusout", (e) => {
    const t = e.target;
    if (t.dataset.tags && t.value.trim() && !editor.contains(e.relatedTarget)) addTag(t);
  });

  editor.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) {
      const d = b.dataset;
      if (d.add) { draft[d.add].push(""); render(`[data-list="${d.add}"][data-index="${draft[d.add].length - 1}"]`); }
      else if (d.remove) { draft[d.remove].splice(Number(d.index), 1); render(); }
      else if (d.tagRemove) { getPath(draft, d.tagRemove).splice(Number(d.index), 1); render(`[data-tags="${d.tagRemove}"]`); }
      else if ("addTier" in d) { draft.pricing.push({ name: "", price: "", includes: [] }); render(`[data-tier="${draft.pricing.length - 1}"]`); }
      else if (d.removeTier) { draft.pricing.splice(Number(d.removeTier), 1); render(); }
      else if ("refRead" in d) readReference();
      else if ("refRemove" in d) { ref = null; refStatus = null; renderRef(); }
      return;
    }
    const box = e.target.closest(".tag-box");
    if (box) box.querySelector("input").focus();
  });

  const setMode = (next) => {
    error.innerHTML = "";
    if (next === mode) return true;
    if (next === "json") {
      jsonBox.value = JSON.stringify(cleanBrief(draft), null, 2);
    } else {
      try { draft = normaliseBrief(JSON.parse(jsonBox.value)); } catch (err) {
        error.innerHTML = `<div class="alert">The JSON has a mistake, so it can't be shown as a form yet: ${esc(err.message)}</div>`;
        return false;
      }
      render();
    }
    mode = next;
    editor.hidden = mode !== "form";
    jsonWrap.hidden = mode !== "json";
    document.querySelectorAll(".segmented button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    return true;
  };
  document.querySelectorAll(".segmented button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

  const sample = document.getElementById("sample");
  const loadSample = async () => {
    draft = normaliseBrief(sample.value ? await api(`/api/briefs/${sample.value}`) : BLANK_BRIEF);
    error.innerHTML = "";
    render();
    if (mode === "json") jsonBox.value = JSON.stringify(cleanBrief(draft), null, 2);
  };
  sample.addEventListener("change", loadSample);
  if (briefs.length) sample.value = briefs[0];
  await loadSample();

  const target = document.getElementById("target");
  target.addEventListener("input", () => { document.getElementById("target-val").textContent = target.value; });
  document.querySelectorAll("input[name=builder]").forEach((i) => i.addEventListener("change", updateNotes));

  document.getElementById("new-run").addEventListener("submit", async (e) => {
    e.preventDefault();
    error.innerHTML = "";
    editor.querySelectorAll(".invalid").forEach((el) => el.classList.remove("invalid"));
    if (mode === "json" && !setMode("form")) return;
    const brief = cleanBrief(draft);
    const problems = [...briefProblems(brief), ...colourProblems(draft.style)];
    if (problems.length) {
      problems.forEach(([id]) => document.getElementById(id)?.classList.add("invalid"));
      error.innerHTML = `<div class="alert"><strong>A few things are missing</strong><ul>${problems.map(([, m]) => `<li>${esc(m)}</li>`).join("")}</ul></div>`;
      document.getElementById(problems[0][0])?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    const builders = [...document.querySelectorAll("input[name=builder]:checked")].map((i) => i.value);
    if (!builders.length) { error.innerHTML = `<div class="alert">Pick at least one builder.</div>`; return; }

    const button = e.target.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "Starting…";
    try {
      const token = document.getElementById("token");
      const res = await api("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { "X-Access-Token": token.value } : {}) },
        body: JSON.stringify({
          brief, builders, reference_image: ref,
          target: Number(target.value), rounds: Number(document.getElementById("rounds").value),
        }),
      });
      location.hash = `#/runs/${res.id}`;
    } catch (err) {
      error.innerHTML = `<div class="alert">${esc(err.message)}</div>`;
      button.disabled = false;
      button.textContent = "Start run";
    }
  });
}

route();
