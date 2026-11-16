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

function briefPanel(b) {
  return `<dl class="brief-list">
    <dt>Description</dt><dd>${esc(b.description)}</dd>
    <dt>Keywords</dt><dd class="tags">${b.keywords.map((k) => `<span class="chip">${esc(k)}</span>`).join("")}</dd>
    <dt>Features</dt><dd>${b.features.map(esc).join(" · ")}</dd>
    <dt>Call to action</dt><dd>${esc(b.call_to_action)}</dd>
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
      <div><div class="section-title" style="margin-top:0"><h2>Brief</h2></div><div class="card">${briefPanel(state.brief)}</div></div>
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
async function renderNew() {
  const briefs = meta.briefs || [];
  view.innerHTML = `
    <div class="page-head"><div><h1>New run</h1><p>Describe the product once. Each builder takes a different audience, and the lead keeps sending pages back until they reach the target score.</p></div></div>
    <form class="form-grid" id="new-run">
      <div class="card card-pad">
        <div class="field">
          <label for="sample">Start from a sample brief</label>
          <select id="sample">${briefs.map((b) => `<option value="${esc(b)}">${esc(b)}</option>`).join("")}</select>
        </div>
        <div class="field">
          <label for="brief">Product brief (JSON)</label>
          <textarea id="brief" spellcheck="false"></textarea>
          <span class="help">Required: product, tagline, description, features (3+), keywords, audiences. One variant is built per audience.</span>
        </div>
      </div>
      <div class="card card-pad">
        <div id="form-error"></div>
        <div class="field">
          <label for="target">Target score <span class="range-value" id="target-val">${meta.target}</span></label>
          <input type="range" id="target" min="70" max="100" value="${meta.target}">
        </div>
        <div class="field">
          <label for="rounds">Rounds per builder</label>
          <input type="number" id="rounds" min="1" max="5" value="${meta.rounds}">
          <span class="help">The first build plus up to this many revisions in total.</span>
        </div>
        <div class="field">
          <label>Builders</label>
          <div class="check-list">${meta.builders.map((b) => `
            <label class="check-item"><input type="checkbox" name="builder" value="${esc(b.key)}" checked><i class="dot" style="background:${b.colour}"></i>${esc(b.name)}</label>`).join("")}</div>
        </div>
        ${meta.token_required ? `<div class="field"><label for="token">Access token</label><input type="password" id="token" autocomplete="off"><span class="help">This deployment requires a token to start runs.</span></div>` : ""}
        <button class="btn btn-primary" type="submit" style="width:100%;justify-content:center">Start run</button>
      </div>
    </form>`;

  const sample = document.getElementById("sample");
  const brief = document.getElementById("brief");
  const loadSample = async () => {
    if (!sample.value) return;
    brief.value = JSON.stringify(await api(`/api/briefs/${sample.value}`), null, 2);
  };
  sample.addEventListener("change", loadSample);
  await loadSample();
  const target = document.getElementById("target");
  target.addEventListener("input", () => { document.getElementById("target-val").textContent = target.value; });

  document.getElementById("new-run").addEventListener("submit", async (e) => {
    e.preventDefault();
    const error = document.getElementById("form-error");
    error.innerHTML = "";
    let parsed;
    try { parsed = JSON.parse(brief.value); } catch (err) {
      error.innerHTML = `<div class="alert">The brief is not valid JSON: ${esc(err.message)}</div>`;
      return;
    }
    const button = e.target.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "Starting…";
    try {
      const token = document.getElementById("token");
      const res = await api("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { "X-Access-Token": token.value } : {}) },
        body: JSON.stringify({
          brief: parsed,
          target: Number(target.value),
          rounds: Number(document.getElementById("rounds").value),
          builders: [...document.querySelectorAll("input[name=builder]:checked")].map((i) => i.value),
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
