"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const CAT_LABEL = { acts: "Acts", judgments: "Court Judgments", pov: "POV", tax: "Tax Documents" };
const ICON = (id, cls = "icon") => `<svg class="${cls}"><use href="#${id}"/></svg>`;

// ---------- Lottie loaders (graceful CSS fallback if the lib fails) ----------
const LOTTIE_PATH = "/static/assets/Search.json";
const anims = {};
const msgTimers = {};
const LOAD_MSGS = {
  ask: ["Searching the corpus…", "Running hybrid retrieval — vector + keyword…",
        "Fusing and ranking the top passages…", "Generating a grounded answer with Gemini…",
        "Validating every citation…"],
  sum: ["Loading the document…", "Reading its key provisions…", "Writing a faithful summary…"],
  graph: ["Resolving the reference…", "Traversing the citation graph…", "Collecting citing documents…"],
};
function cycleMsgs(key) {
  const cap = $(key + "-loader").querySelector(".cap");
  const msgs = LOAD_MSGS[key] || ["Working…"];
  let i = 0; cap.textContent = msgs[0]; cap.style.opacity = 1;
  clearInterval(msgTimers[key]);
  msgTimers[key] = setInterval(() => {
    cap.style.opacity = 0;
    setTimeout(() => { i = (i + 1) % msgs.length; cap.textContent = msgs[i]; cap.style.opacity = 1; }, 230);
  }, 2100);
}
function showLoader(key) {
  const loader = $(key + "-loader");
  loader.classList.remove("hidden");
  const scan = loader.querySelector(".scan");
  if (window.lottie) {
    if (!anims[key]) {
      try {
        anims[key] = lottie.loadAnimation({
          container: $(key + "-lottie"), renderer: "svg", loop: true, autoplay: true, path: LOTTIE_PATH,
        });
        scan.classList.add("has-lottie");
      } catch (e) { /* keep the CSS fallback */ }
    } else { anims[key].play(); }
  }
  cycleMsgs(key);
}
function hideLoader(key) {
  $(key + "-loader").classList.add("hidden");
  if (anims[key]) anims[key].stop();
  clearInterval(msgTimers[key]);
}

// ---------- accessible tabs ----------
const tabs = Array.from(document.querySelectorAll(".tab"));
function switchTab(name) {
  tabs.forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  $("tab-" + name).classList.add("active");
}
tabs.forEach((btn, i) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  btn.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
      next.focus(); switchTab(next.dataset.tab);
    }
  });
});

// ---------- health (handles both the main and the serverless backend) ----------
async function loadHealth() {
  try {
    const h = await (await fetch("/health")).json();
    $("model-tag").textContent = "Model: " + (h.model || "—");
    let html;
    if (h.vectors !== undefined) {
      const gemOk = !!h.gemini_configured;
      html =
        `<span class="s hide"><b>${h.vectors.toLocaleString()}</b> vectors</span>` +
        `<span class="s hide"><b>${(h.graph_nodes || 0).toLocaleString()}</b> graph nodes</span>` +
        `<span class="s"><span class="dot ${gemOk ? "" : "bad"}"></span>Gemini <b>${gemOk ? "ready" : "key not set"}</b></span>`;
    } else {
      const up = (v) => String(v).startsWith("ok");
      html =
        `<span class="s"><span class="dot ${up(h.qdrant) ? "" : "bad"}"></span>Vector DB <b>${up(h.qdrant) ? "up" : "down"}</b>` +
        `${h.qdrant_points ? ` · ${h.qdrant_points.toLocaleString()} chunks` : ""}</span>` +
        `<span class="s hide">Keyword <b>${up(h.elasticsearch) ? "up" : "down"}</b></span>`;
    }
    $("health").innerHTML = html;
  } catch {
    $("health").innerHTML = `<span class="s"><span class="dot bad"></span>backend unreachable</span>`;
  }
}

// ---------- rendering ----------
// escape (safe) -> **bold** -> *italic* (e.g. case names) -> newlines.
// Bold runs first (consumes doubles); italic only matches a tight *word* pair
// (no surrounding space, no inner * or newline) so stray asterisks don't match.
function fmtText(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/\n/g, "<br>");
}

function renderAnswer(text) {
  $("answer").innerHTML = fmtText(text).replace(/\[([\d,\s]+)\]/g, (m, grp) =>
    (grp.match(/\d+/g) || []).map((n) => `<a class="m" href="#cite-${n}" data-n="${n}">${n}</a>`).join(""));
  $("answer").querySelectorAll(".m").forEach((a) =>
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const li = $("cite-" + a.dataset.n);
      if (li) { li.scrollIntoView({ behavior: "smooth", block: "center" });
        li.classList.remove("flash"); void li.offsetWidth; li.classList.add("flash");
        setTimeout(() => li.classList.remove("flash"), 1100); }
    }));
}

function renderCitations(citations) {
  const ul = $("citations");
  ul.innerHTML = "";
  if (!citations.length) {
    ul.innerHTML = `<li><div class="cbody cmeta">No citations (the answer was a refusal or had no grounded source).</div></li>`;
    return;
  }
  for (const c of citations) {
    const li = document.createElement("li");
    li.id = "cite-" + c.marker;
    const link = c.url ? ` <a href="${esc(c.url)}" target="_blank" rel="noopener">open source ${ICON("i-ext", "icon icon-sm")}</a>` : "";
    li.innerHTML =
      `<div class="ci">${ICON("i-file", "icon icon-sm")}</div>` +
      `<div class="cbody"><span class="cnum">[${c.marker}]</span><span class="cdoc">${esc(c.doc)}</span>` +
      (c.category ? `<span class="catb">${CAT_LABEL[c.category] || c.category}</span>` : "") +
      `<div class="cmeta">Section: ${esc(c.section || "—")} · Page ${esc(String(c.page))}${link}</div></div>`;
    ul.appendChild(li);
  }
}

function renderRelated(data) {
  const docs = data.related_documents || [], auth = data.shared_authorities || [];
  if (!docs.length && !auth.length) { $("related-section").classList.add("hidden"); return; }
  const dr = $("related-docs"); dr.innerHTML = "";
  for (const d of docs) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "dchip";
    b.innerHTML = `${ICON("i-file", "icon icon-sm")}<span>${esc(d.title)}</span><span class="cc">${CAT_LABEL[d.category] || d.category}</span>`;
    b.title = "Explore this document's citations";
    b.addEventListener("click", () => openGraphFor(d.title));
    dr.appendChild(b);
  }
  const sa = $("shared-auth");
  sa.innerHTML = auth.length ? `<span class="al">Shared authorities:</span>` : "";
  for (const a of auth) {
    const s = document.createElement("span");
    s.className = "auth-chip"; s.textContent = a.id; sa.appendChild(s);
  }
  $("related-section").classList.remove("hidden");
}

function openGraphFor(title) {
  switchTab("graph");
  $("graph-ref").value = title; $("graph-cat").value = "all";
  runGraphQuery(title);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showError(key, msg) {
  const el = $(key + "-status");
  el.className = "status-line error";
  el.innerHTML = `${ICON("i-warn", "icon icon-sm")}${esc(msg)}`;
}

// ---------- ask ----------
async function runAsk(query) {
  $("query").value = query;
  $("ask-btn").disabled = true;
  $("answer-section").classList.add("hidden");
  $("ask-empty").classList.add("hidden");
  $("ask-status").className = "status-line"; $("ask-status").textContent = "";
  showLoader("ask");
  try {
    const r = await fetch("/query", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, category: $("category").value }),
    });
    if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || "request failed"); }
    const data = await r.json();
    renderAnswer(data.answer); renderCitations(data.citations); renderRelated(data);
    const badge = $("grounded-badge");
    badge.className = "pill" + (data.grounded ? "" : " ungrounded");
    badge.innerHTML = data.grounded
      ? `${ICON("i-check", "icon icon-sm")}Grounded in sources`
      : `${ICON("i-warn", "icon icon-sm")}Not fully grounded`;
    $("answer-section").classList.remove("hidden");
  } catch (e) {
    showError("ask", "Error: " + e.message);
    $("ask-empty").classList.add("hidden");
  } finally {
    hideLoader("ask"); $("ask-btn").disabled = false;
  }
}
$("ask-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = $("query").value.trim();
  if (q.length < 3) { showError("ask", "Please enter a longer question."); return; }
  runAsk(q);
});
$("ask-examples").querySelectorAll(".chip").forEach((b) =>
  b.addEventListener("click", () => { $("query").value = b.dataset.q; $("query").focus(); }));
$("copy-btn").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("answer").innerText);
    $("copy-btn").innerHTML = `${ICON("i-check", "icon icon-sm")}Copied`;
    setTimeout(() => ($("copy-btn").innerHTML = `${ICON("i-copy", "icon icon-sm")}Copy`), 1500);
  } catch { /* ignore */ }
});

// ---------- summarize ----------
async function loadDocuments() {
  try {
    const docs = await (await fetch("/documents")).json();
    docs.sort((a, b) => a.category.localeCompare(b.category) || a.title.localeCompare(b.title));
    const sel = $("doc-select");
    sel.innerHTML = `<option value="">Select a document to summarize…</option>`;
    for (const d of docs) {
      const o = document.createElement("option");
      o.value = d.doc_id; o.textContent = `${CAT_LABEL[d.category] || d.category} — ${d.title}`;
      sel.appendChild(o);
    }
  } catch { $("doc-select").innerHTML = `<option value="">(couldn't load documents)</option>`; }
}
$("summarize-btn").addEventListener("click", async () => {
  const id = $("doc-select").value;
  if (!id) { showError("sum", "Pick a document first."); return; }
  $("summarize-btn").disabled = true;
  $("summary-section").classList.add("hidden"); $("sum-empty").classList.add("hidden");
  $("sum-status").className = "status-line"; $("sum-status").textContent = "";
  showLoader("sum");
  try {
    const r = await fetch("/summarize", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ doc_id: id }),
    });
    if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || "request failed"); }
    const d = await r.json();
    $("summary-title").textContent = d.title;
    $("summary-cat").textContent = CAT_LABEL[d.category] || d.category;
    $("summary").innerHTML = fmtText(d.summary);
    $("summary-section").classList.remove("hidden");
  } catch (e) { showError("sum", "Error: " + e.message); }
  finally { hideLoader("sum"); $("summarize-btn").disabled = false; }
});

// ---------- graph ----------
async function runGraphQuery(reference) {
  $("graph-section").classList.add("hidden"); $("graph-empty").classList.add("hidden");
  $("graph-status").className = "status-line"; $("graph-status").textContent = "";
  $("graph-btn").disabled = true;
  showLoader("graph");
  try {
    const r = await fetch("/graph/citing", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference, category: $("graph-cat").value }),
    });
    if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || "request failed"); }
    const data = await r.json();
    $("graph-ref-label").textContent = data.reference;
    const docs = data.citing_documents || [];
    $("graph-count").textContent = `${docs.length} found`;
    const wrap = $("graph-results"); wrap.innerHTML = "";
    if (!docs.length) {
      wrap.innerHTML = `<p class="hint">No corpus documents cite that reference. Try a different Act/authority name (see the examples above).</p>`;
    } else {
      const byCat = {};
      for (const d of docs) (byCat[d.category] = byCat[d.category] || []).push(d);
      for (const cat of Object.keys(byCat).sort()) {
        const g = document.createElement("div");
        g.innerHTML = `<div class="ghead">${CAT_LABEL[cat] || cat}<span class="gcount">${byCat[cat].length}</span></div>`;
        const ul = document.createElement("ul"); ul.className = "cites";
        for (const d of byCat[cat]) {
          const li = document.createElement("li");
          li.innerHTML = `<div class="ci">${ICON("i-file", "icon icon-sm")}</div>` +
            `<div class="cbody"><span class="cdoc">${esc(d.title)}</span>` +
            `<div class="cmeta">references “${esc(data.reference)}”</div></div>`;
          ul.appendChild(li);
        }
        g.appendChild(ul); wrap.appendChild(g);
      }
    }
    $("graph-section").classList.remove("hidden");
  } catch (e) { showError("graph", "Error: " + e.message); }
  finally { hideLoader("graph"); $("graph-btn").disabled = false; }
}
$("graph-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const ref = $("graph-ref").value.trim();
  if (ref.length < 2) { showError("graph", "Enter an Act, statute, or case name."); return; }
  runGraphQuery(ref);
});
document.querySelectorAll(".ex-graph").forEach((b) =>
  b.addEventListener("click", () => { $("graph-ref").value = b.dataset.q; $("graph-ref").focus(); }));

// ---------- init ----------
loadHealth();
loadDocuments();
