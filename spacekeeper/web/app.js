"use strict";

const CATEGORY_META = {
  project_dependency: { icon: "📦", label: "프로젝트 의존성" },
  package_cache: { icon: "🗃️", label: "패키지 캐시" },
  build_cache: { icon: "🏗️", label: "빌드 캐시" },
  rust_build: { icon: "🦀", label: "Rust 빌드 산출물" },
  xcode_derived_data: { icon: "🔨", label: "Xcode 파생 데이터" },
  app_cache: { icon: "💾", label: "앱 캐시" },
  user_cache: { icon: "📁", label: "사용자 캐시" },
  local_ai_model: { icon: "🧠", label: "로컬 AI 모델" },
  test_cache: { icon: "🧪", label: "테스트 캐시" },
  tool_cache: { icon: "🛠️", label: "도구 캐시" },
  python_cache: { icon: "🐍", label: "Python 캐시" },
  large_file: { icon: "🗂️", label: "큰 파일" },
  old_download: { icon: "⬇️", label: "오래된 다운로드" },
  installer_or_archive: { icon: "🧰", label: "설치·압축 파일" },
};
const RISK_LABEL = { low: "안전", medium: "확인 권장", high: "주의" };

let lastScan = null;
let lastApps = null;
const selDash = new Set();
const selDup = new Set();
const selApps = new Set();

/* ---------- helpers ---------- */
function fmtBytes(v) {
  if (v == null) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = v;
  for (let i = 0; i < units.length; i++) {
    if (n < 1024 || i === units.length - 1) {
      return i === 0 ? `${n} B` : `${n.toFixed(1)} ${units[i]}`;
    }
    n /= 1024;
  }
}
function catMeta(cat) { return CATEGORY_META[cat] || { icon: "📄", label: cat }; }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function toast(msg, kind) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (kind ? " " + kind : "");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), 3600);
}
async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "요청에 실패했어요");
  return data;
}
async function reclaimIds(ids, btn, label) {
  if (!ids.length) return null;
  if (btn) { btn.disabled = true; btn.textContent = "이동하는 중…"; }
  try {
    const out = await api("/api/reclaim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_ids: ids }),
    });
    let msg = `${out.moved_count}개 항목을 격리함으로 옮겼어요 · ${fmtBytes(out.freed_bytes)} 확보`;
    if (out.skipped_count) msg += ` · ${out.skipped_count}개 건너뜀`;
    toast(msg, "ok");
    return out;
  } catch (e) {
    toast(e.message, "err");
    return null;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

/* ---------- dashboard scan ---------- */
function resolvePath() {
  const preset = document.getElementById("preset").value;
  if (preset === "downloads") return "~/Downloads";
  if (preset === "home") return "~";
  if (preset === "desktop") return "~/Desktop";
  return document.getElementById("path-input").value.trim() || "~";
}

async function runScan() {
  const path = resolvePath();
  const dup = document.getElementById("opt-duplicates").checked ? "1" : "0";
  document.getElementById("empty-state").hidden = true;
  document.getElementById("results").hidden = true;
  document.getElementById("scanning").hidden = false;
  document.getElementById("scanning-text").textContent = `${path} 살펴보는 중…`;

  const params = new URLSearchParams({ paths: path, duplicates: dup });
  try {
    const data = await api("/api/scan?" + params.toString());
    lastScan = data;
    selDash.clear();
    selDup.clear();
    renderResults(data);
    renderDuplicates();
  } catch (e) {
    toast(e.message, "err");
    document.getElementById("empty-state").hidden = false;
  } finally {
    document.getElementById("scanning").hidden = true;
  }
}

function sumBytes(entries) { return entries.reduce((s, e) => s + e.allocated_bytes, 0); }

function renderResults(data) {
  document.getElementById("results").hidden = false;

  const usedRatio = data.disk.total ? data.disk.used / data.disk.total : 0;
  const circ = 2 * Math.PI * 52;
  const used = document.getElementById("donut-used");
  used.style.strokeDasharray = circ;
  used.style.strokeDashoffset = circ * (1 - usedRatio);
  document.getElementById("donut-free").textContent = fmtBytes(data.disk.free);
  document.getElementById("reclaimable-total").textContent = fmtBytes(data.review_bytes);

  const risk = data.by_risk;
  const total = (risk.low + risk.medium + risk.high) || 1;
  const bars = document.getElementById("risk-bars");
  bars.innerHTML = "";
  for (const r of ["low", "medium", "high"]) {
    if (!risk[r]) continue;
    const seg = document.createElement("div");
    seg.className = "risk-seg " + r;
    seg.style.width = (risk[r] / total * 100) + "%";
    bars.appendChild(seg);
  }
  document.getElementById("hero-meta").innerHTML =
    ["low", "medium", "high"].map((r) =>
      `<span><span class="dot ${r}"></span>${RISK_LABEL[r]} ${fmtBytes(risk[r])}</span>`).join("") +
    `<span class="sep">·</span><span>파일 ${data.scanned_files.toLocaleString()}개 · ${data.duration.toFixed(1)}초</span>`;

  const groups = {};
  for (const e of data.entries) (groups[e.category] ||= []).push(e);
  const order = Object.keys(groups).sort((a, b) => sumBytes(groups[b]) - sumBytes(groups[a]));

  const list = document.getElementById("category-list");
  list.innerHTML = "";
  if (!data.entries.length) list.innerHTML = `<div class="q-empty">정리할 항목이 없어요. 깔끔하네요.</div>`;
  for (const cat of order) list.appendChild(renderCategory(cat, groups[cat]));
  updateDashSelection();
}

function renderCategory(cat, entries) {
  const meta = catMeta(cat);
  const risk = entries[0].risk;
  const el = document.createElement("div");
  el.className = "card";
  const rows = entries.map((e) => `
    <label class="entry">
      <input type="checkbox" data-id="${e.action_id}" ${e.risk === "low" ? "checked" : ""} />
      <span class="entry-main">
        <span class="entry-path" title="${escapeHtml(e.path)}">${escapeHtml(e.path)}</span>
        <span class="entry-reason">${escapeHtml(e.reason)}</span>
      </span>
      <span class="entry-size">${e.allocated_human}</span>
    </label>`).join("");
  el.innerHTML = `
    <div class="cat-head">
      <span class="cat-icon">${meta.icon}</span>
      <div><div class="cat-title">${meta.label}</div><div class="cat-sub">${entries.length}개 항목</div></div>
      <div class="cat-size"><b>${fmtBytes(sumBytes(entries))}</b><span class="badge ${risk}">${RISK_LABEL[risk]}</span><span class="cat-caret">›</span></div>
    </div>
    <div class="cat-body">
      <div class="cat-selectall"><label class="chk"><input type="checkbox" class="cat-all" /> 이 그룹 전체 선택</label></div>
      ${rows}
    </div>`;
  if (risk === "low") el.classList.add("open");
  el.querySelector(".cat-head").addEventListener("click", (ev) => {
    if (ev.target.closest("input")) return;
    el.classList.toggle("open");
  });
  el.querySelectorAll("input[data-id]").forEach((cb) => {
    if (cb.checked) selDash.add(cb.dataset.id);
    cb.addEventListener("change", () => {
      cb.checked ? selDash.add(cb.dataset.id) : selDash.delete(cb.dataset.id);
      updateDashSelection();
    });
  });
  const all = el.querySelector(".cat-all");
  all.checked = entries.every((e) => selDash.has(e.action_id));
  all.addEventListener("change", () => {
    el.querySelectorAll("input[data-id]").forEach((cb) => {
      cb.checked = all.checked;
      cb.checked ? selDash.add(cb.dataset.id) : selDash.delete(cb.dataset.id);
    });
    updateDashSelection();
  });
  return el;
}

function updateDashSelection() {
  if (!lastScan) return;
  const chosen = lastScan.entries.filter((e) => selDash.has(e.action_id));
  document.getElementById("actions-bar").hidden = chosen.length === 0;
  document.getElementById("selection-summary").textContent =
    `${chosen.length}개 선택 · ${fmtBytes(sumBytes(chosen))}`;
  document.querySelectorAll("#category-list .card").forEach((card) => {
    const boxes = card.querySelectorAll("input[data-id]");
    const all = card.querySelector(".cat-all");
    if (all && boxes.length) all.checked = [...boxes].every((b) => b.checked);
  });
}

/* ---------- duplicates ---------- */
function renderDuplicates() {
  const list = document.getElementById("dup-list");
  const summary = document.getElementById("dup-summary");
  list.innerHTML = "";
  selDup.clear();
  if (!lastScan) {
    list.innerHTML = `<div class="q-empty">먼저 대시보드에서 스캔을 실행하세요.</div>`;
    summary.textContent = "";
    document.getElementById("dup-actions").hidden = true;
    return;
  }
  const dups = lastScan.duplicates || [];
  if (!dups.length) {
    const hint = document.getElementById("opt-duplicates").checked
      ? "완전히 같은 파일을 찾지 못했어요."
      : "대시보드에서 ‘중복 검사’를 켜고 다시 스캔하면 여기에 표시돼요.";
    list.innerHTML = `<div class="q-empty">${hint}</div>`;
    summary.textContent = "";
    document.getElementById("dup-actions").hidden = true;
    return;
  }
  summary.textContent = `${dups.length}개 그룹 · 최대 ${lastScan.duplicate_reclaimable_bytes ? fmtBytes(lastScan.duplicate_reclaimable_bytes) : "–"} 확보`;
  for (const group of dups) {
    const el = document.createElement("div");
    el.className = "card dup-group";
    const rows = group.files.map((f) => `
      <label class="entry">
        <input type="checkbox" data-id="${f.action_id}" ${f.keep ? "" : "checked"} />
        <span class="entry-main">
          <span class="entry-path" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</span>
          ${f.keep ? `<span class="entry-reason dup-keep">기본 보관</span>` : ""}
        </span>
      </label>`).join("");
    el.innerHTML = `
      <div class="dup-group-head"><b>${group.each_human}</b> 파일 ${group.files.length}개 · ${group.reclaimable_human} 확보 가능</div>
      ${rows}`;
    el.querySelectorAll("input[data-id]").forEach((cb) => {
      if (cb.checked) selDup.add(cb.dataset.id);
      cb.addEventListener("change", () => {
        cb.checked ? selDup.add(cb.dataset.id) : selDup.delete(cb.dataset.id);
        updateDupSelection();
      });
    });
    list.appendChild(el);
  }
  updateDupSelection();
}

function updateDupSelection() {
  document.getElementById("dup-actions").hidden = selDup.size === 0;
  document.getElementById("dup-selection").textContent = `${selDup.size}개 선택`;
}

/* ---------- apps ---------- */
async function loadApps() {
  const list = document.getElementById("apps-list");
  list.innerHTML = `<div class="q-empty">응용 프로그램을 살펴보는 중…</div>`;
  try {
    const data = await api("/api/apps");
    lastApps = data;
    selApps.clear();
    renderApps(data);
  } catch (e) {
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

function renderApps(data) {
  const list = document.getElementById("apps-list");
  list.innerHTML = "";
  if (!data.apps.length) {
    list.innerHTML = `<div class="q-empty">표시할 응용 프로그램이 없어요.</div>`;
    return;
  }
  for (const app of data.apps) {
    const el = document.createElement("div");
    el.className = "card";
    const initial = escapeHtml(app.name.slice(0, 1).toUpperCase());
    const leftoverRows = app.leftovers.map((f) => `
      <label class="entry">
        <input type="checkbox" data-id="${f.action_id}" data-app="${app.app_action_id}" />
        <span class="entry-main"><span class="entry-path" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</span>
          <span class="entry-reason">잔여 파일</span></span>
        <span class="entry-size">${f.allocated_human}</span>
      </label>`).join("");
    el.innerHTML = `
      <div class="app-head">
        <div class="app-icon">${initial}</div>
        <div><div class="app-name">${escapeHtml(app.name)}</div>
          <div class="app-sub">앱 ${app.app_human} · 잔여 ${app.leftover_human} · ${app.leftovers.length}개 파일</div></div>
        <div class="cat-size"><b>${app.total_human}</b><span class="cat-caret">›</span></div>
      </div>
      <div class="cat-body">
        <div class="cat-selectall"><label class="chk"><input type="checkbox" class="app-all" data-app="${app.app_action_id}" /> 앱과 잔여 파일 모두 선택</label></div>
        <label class="entry">
          <input type="checkbox" data-id="${app.app_action_id}" data-app="${app.app_action_id}" />
          <span class="entry-main"><span class="entry-path">${escapeHtml(app.path)}</span>
            <span class="entry-reason">응용 프로그램 본체</span></span>
          <span class="entry-size">${app.app_human}</span>
        </label>
        ${leftoverRows}
      </div>`;
    el.querySelector(".app-head").addEventListener("click", (ev) => {
      if (ev.target.closest("input")) return;
      el.classList.toggle("open");
    });
    el.querySelectorAll("input[data-id]").forEach((cb) => {
      cb.addEventListener("change", () => {
        cb.checked ? selApps.add(cb.dataset.id) : selApps.delete(cb.dataset.id);
        syncAppAll(el);
        updateAppsSelection();
      });
    });
    const appAll = el.querySelector(".app-all");
    appAll.addEventListener("change", () => {
      el.querySelectorAll("input[data-id]").forEach((cb) => {
        cb.checked = appAll.checked;
        cb.checked ? selApps.add(cb.dataset.id) : selApps.delete(cb.dataset.id);
      });
      updateAppsSelection();
    });
    list.appendChild(el);
  }
  updateAppsSelection();
}

function syncAppAll(card) {
  const boxes = card.querySelectorAll("input[data-id]");
  const all = card.querySelector(".app-all");
  if (all && boxes.length) all.checked = [...boxes].every((b) => b.checked);
}

function updateAppsSelection() {
  document.getElementById("apps-actions").hidden = selApps.size === 0;
  document.getElementById("apps-selection").textContent = `${selApps.size}개 항목 선택`;
}

/* ---------- quarantine ---------- */
async function loadQuarantine() {
  const list = document.getElementById("quarantine-list");
  list.innerHTML = `<div class="q-empty">불러오는 중…</div>`;
  try {
    const data = await api("/api/quarantine");
    if (!data.items.length) {
      list.innerHTML = `<div class="q-empty">격리된 항목이 없어요.</div>`;
      return;
    }
    list.innerHTML = "";
    for (const item of data.items) {
      const el = document.createElement("div");
      el.className = "q-item";
      el.innerHTML = `
        <span class="cat-icon">↩</span>
        <span class="entry-main">
          <span class="entry-path" title="${escapeHtml(item.original_path)}">${escapeHtml(item.original_path)}</span>
          <span class="entry-reason">${fmtBytes(item.allocated_bytes)}</span>
        </span>
        <button class="btn ghost small" data-restore="${item.action_id}">되돌리기</button>`;
      el.querySelector("[data-restore]").addEventListener("click", async (ev) => {
        ev.target.disabled = true;
        try {
          await api("/api/restore", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action_id: item.action_id }),
          });
          toast("원래 자리로 되돌렸어요.", "ok");
          loadQuarantine();
        } catch (e) { toast(e.message, "err"); ev.target.disabled = false; }
      });
      list.appendChild(el);
    }
  } catch (e) {
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

async function emptyQuarantine() {
  if (!confirm("격리된 항목을 macOS 휴지통으로 옮길게요. 계속할까요?")) return;
  try {
    const out = await api("/api/empty", { method: "POST" });
    toast(`${out.count}개를 휴지통으로 옮겼어요.`, "ok");
    loadQuarantine();
  } catch (e) { toast(e.message, "err"); }
}

/* ---------- wiring ---------- */
function switchView(view) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById("view-" + view).classList.add("active");
  if (view === "quarantine") loadQuarantine();
  if (view === "duplicates") renderDuplicates();
  if (view === "apps" && !lastApps) loadApps();
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("preset").addEventListener("change", (e) => {
    document.getElementById("path-input").disabled = e.target.value !== "custom";
  });
  document.getElementById("path-input").disabled = true;
  document.getElementById("scan-btn").addEventListener("click", runScan);
  document.getElementById("scan-btn-2").addEventListener("click", runScan);

  document.getElementById("reclaim-btn").addEventListener("click", async (e) => {
    const out = await reclaimIds([...selDash], e.target, "격리함으로 이동");
    if (out) { selDash.clear(); await runScan(); }
  });
  document.getElementById("clear-sel").addEventListener("click", () => {
    selDash.clear();
    document.querySelectorAll("#category-list input").forEach((b) => (b.checked = false));
    updateDashSelection();
  });

  document.getElementById("dup-reclaim").addEventListener("click", async (e) => {
    const out = await reclaimIds([...selDup], e.target, "격리함으로 이동");
    if (out) await runScan();
  });

  document.getElementById("apps-scan").addEventListener("click", loadApps);
  document.getElementById("apps-reclaim").addEventListener("click", async (e) => {
    const out = await reclaimIds([...selApps], e.target, "격리함으로 이동");
    if (out) await loadApps();
  });

  document.getElementById("refresh-q").addEventListener("click", loadQuarantine);
  document.getElementById("empty-q").addEventListener("click", emptyQuarantine);
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.addEventListener("click", () => switchView(b.dataset.view)));
});
