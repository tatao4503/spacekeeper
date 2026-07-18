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
const RISK_LABEL = { low: "낮은 위험", medium: "확인 필요", high: "높은 주의" };

let lastScan = null;
let lastApps = null;
let lastQuarantine = [];
let visibleDashboardIds = new Set();
const selDash = new Set();
const selDup = new Set();
const selApps = new Set();
const selQ = new Set();

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
function finderRevealButton(
  actionId,
  label,
  scope = "visible",
  instanceToken = "",
) {
  const tokenAttribute = instanceToken
    ? ` data-reveal-token="${escapeHtml(instanceToken)}"`
    : "";
  return `
    <button class="entry-reveal" type="button"
      data-reveal="${escapeHtml(actionId)}"
      data-reveal-scope="${scope}"${tokenAttribute}
      title="Finder에서 보기: ${escapeHtml(label)}"
      aria-label="Finder에서 보기: ${escapeHtml(label)}">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h6l1.5 2H20v9.5H4z" /><path d="M4 7.5V5h6l1.5 2H20v2.5" /></svg>
      <span>Finder에서 보기</span>
    </button>`;
}
function wireRevealButtons(root) {
  root.querySelectorAll("[data-reveal]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.classList.add("busy");
      try {
        const body = {
          action_id: button.dataset.reveal,
          scope: button.dataset.revealScope,
        };
        if (button.dataset.revealToken) {
          body.instance_token = button.dataset.revealToken;
        }
        await api("/api/reveal", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        toast("Finder에서 항목 위치를 표시했습니다.", "ok");
      } catch (e) {
        toast(e.message, "err");
      } finally {
        button.disabled = false;
        button.classList.remove("busy");
      }
    });
  });
}
function exportLastScan() {
  if (!lastScan) return;
  const now = new Date();
  const stamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
    "-",
    String(now.getHours()).padStart(2, "0"),
    String(now.getMinutes()).padStart(2, "0"),
    String(now.getSeconds()).padStart(2, "0"),
  ].join("");
  const payload = {
    ...lastScan,
    schema_version: 1,
    exported_at: now.toISOString(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `spacekeeper-scan-${stamp}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  toast("분석 결과를 JSON 파일로 저장했습니다.", "ok");
}
async function reclaimIds(ids, btn, label, selectedBytes = 0) {
  if (!ids.length) return null;
  const sizeText = selectedBytes ? ` (${fmtBytes(selectedBytes)})` : "";
  if (!confirm(
    `선택한 ${ids.length}개 항목${sizeText}을 격리할까요?\n\n` +
    "원래 위치에서 Spacekeeper 격리함으로 옮겨집니다. " +
    "이 단계에서는 저장공간이 늘지 않으며 언제든 복원할 수 있습니다."
  )) return null;
  if (btn) { btn.disabled = true; btn.textContent = "안전하게 격리하는 중…"; }
  try {
    const out = await api("/api/reclaim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_ids: ids, confirmed: true }),
    });
    let msg = `${out.moved_count}개 항목을 격리했습니다 · ` +
      `${fmtBytes(out.quarantined_bytes)} 보관 중`;
    if (out.skipped_count) msg += ` · ${out.skipped_count}개는 제외했습니다`;
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

function scanTargetLabel() {
  const preset = document.getElementById("preset").value;
  if (preset === "downloads") return "다운로드 폴더";
  if (preset === "home") return "홈 폴더";
  if (preset === "desktop") return "데스크탑";
  return document.getElementById("path-input").value.trim() || "선택한 경로";
}

function updateScanCta() {
  document.getElementById("scan-btn-2").textContent = `${scanTargetLabel()} 분석하기`;
}

async function runScan() {
  const path = resolvePath();
  const dup = document.getElementById("opt-duplicates").checked ? "1" : "0";
  const excluded = document.getElementById("exclude-input").value
    .split(/[\n,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
  document.getElementById("empty-state").hidden = true;
  document.getElementById("results").hidden = true;
  document.getElementById("scanning").hidden = false;
  document.getElementById("scanning-text").textContent = `${scanTargetLabel()}의 저장공간을 분석하는 중…`;

  const params = new URLSearchParams({ paths: path, duplicates: dup });
  for (const excludedPath of excluded) params.append("exclude", excludedPath);
  try {
    const data = await api("/api/scan?" + params.toString());
    lastScan = data;
    selDash.clear();
    selDup.clear();
    document.getElementById("result-search").value = "";
    document.getElementById("risk-filter").value = "all";
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
  const excludedMeta = data.skipped?.excluded_paths
    ? `<span class="sep">·</span><span>제외 경로 ${data.skipped.excluded_paths}건</span>`
    : "";
  document.getElementById("hero-meta").innerHTML =
    ["low", "medium", "high"].map((r) =>
      `<span><span class="dot ${r}"></span>${RISK_LABEL[r]} ${fmtBytes(risk[r])}</span>`).join("") +
    `<span class="sep">·</span><span>파일 ${data.scanned_files.toLocaleString()}개 · ${data.duration.toFixed(1)}초</span>` +
    excludedMeta;

  renderFilteredResults();
}

function renderFilteredResults() {
  if (!lastScan) return;
  const query = document.getElementById("result-search").value.trim().toLocaleLowerCase("ko-KR");
  const riskFilter = document.getElementById("risk-filter").value;
  const filtered = lastScan.entries.filter((entry) => {
    if (riskFilter !== "all" && entry.risk !== riskFilter) return false;
    if (!query) return true;
    return `${entry.path}\n${entry.reason}\n${catMeta(entry.category).label}`
      .toLocaleLowerCase("ko-KR")
      .includes(query);
  });

  const groups = {};
  for (const entry of filtered) (groups[entry.category] ||= []).push(entry);
  const order = Object.keys(groups).sort((a, b) => sumBytes(groups[b]) - sumBytes(groups[a]));

  const list = document.getElementById("category-list");
  list.innerHTML = "";
  visibleDashboardIds = new Set(filtered.map((entry) => entry.action_id));
  const hiddenSelected = [...selDash].filter(
    (actionId) => !visibleDashboardIds.has(actionId),
  ).length;
  let filterSummary = `전체 ${lastScan.entries.length}개 중 ${filtered.length}개 표시`;
  if (lastScan.omitted_entries) {
    filterSummary += ` · 분석 한도 밖 ${lastScan.omitted_entries}개`;
  }
  if (hiddenSelected) filterSummary += ` · 숨겨진 선택 ${hiddenSelected}개`;
  document.getElementById("result-filter-summary").textContent = filterSummary;
  if (!filtered.length) {
    list.innerHTML = `<div class="q-empty">현재 검색과 필터 조건에 맞는 항목이 없습니다.</div>`;
  }
  for (const cat of order) list.appendChild(renderCategory(cat, groups[cat]));
  updateDashSelection();
}

function renderCategory(cat, entries) {
  const meta = catMeta(cat);
  const risk = entries[0].risk;
  const el = document.createElement("div");
  el.className = "card";
  const rows = entries.map((e) => `
    <div class="entry">
      <label class="entry-select">
        <input type="checkbox" data-id="${e.action_id}" ${selDash.has(e.action_id) ? "checked" : ""} />
        <span class="entry-main">
          <span class="entry-path" title="${escapeHtml(e.path)}">${escapeHtml(e.path)}</span>
          <span class="entry-reason">${escapeHtml(e.reason)}</span>
        </span>
      </label>
      ${finderRevealButton(e.action_id, e.name || e.path)}
      <span class="entry-size">${e.allocated_human}</span>
    </div>`).join("");
  el.innerHTML = `
    <div class="cat-head">
      <span class="cat-icon">${meta.icon}</span>
      <div><div class="cat-title">${meta.label}</div><div class="cat-sub">${entries.length}개 항목을 확인하세요</div></div>
      <div class="cat-size"><b>${fmtBytes(sumBytes(entries))}</b><span class="badge ${risk}">${RISK_LABEL[risk]}</span><span class="cat-caret">›</span></div>
    </div>
    <div class="cat-body">
      <div class="cat-selectall"><label class="chk"><input type="checkbox" class="cat-all" /> 이 그룹 모두 선택</label></div>
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
  wireRevealButtons(el);
  return el;
}

function updateDashSelection() {
  if (!lastScan) return;
  const chosen = lastScan.entries.filter((e) => selDash.has(e.action_id));
  const hidden = chosen.filter((entry) => !visibleDashboardIds.has(entry.action_id));
  document.getElementById("actions-bar").hidden = chosen.length === 0;
  document.getElementById("selection-summary").textContent =
    `${chosen.length}개 · ${fmtBytes(sumBytes(chosen))} 선택` +
    (hidden.length ? ` · 현재 숨겨진 항목 ${hidden.length}개 포함` : "");
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
    list.innerHTML = `<div class="q-empty">먼저 ‘공간 요약’에서 분석을 시작하세요.</div>`;
    summary.textContent = "";
    document.getElementById("dup-actions").hidden = true;
    return;
  }
  const dups = lastScan.duplicates || [];
  if (!dups.length) {
    const hint = document.getElementById("opt-duplicates").checked
      ? "내용이 완전히 같은 파일을 찾지 못했습니다."
      : "‘공간 요약’에서 ‘중복 파일도 찾기’를 켜고 다시 분석하세요.";
    list.innerHTML = `<div class="q-empty">${hint}</div>`;
    summary.textContent = "";
    document.getElementById("dup-actions").hidden = true;
    return;
  }
  summary.textContent = `${dups.length}개 그룹 · 최대 ${lastScan.duplicate_reclaimable_bytes ? fmtBytes(lastScan.duplicate_reclaimable_bytes) : "–"} 정리 가능`;
  for (const group of dups) {
    const el = document.createElement("div");
    el.className = "card dup-group";
    const rows = group.files.map((f) => `
      <div class="entry">
        <label class="entry-select">
          <input type="checkbox" data-id="${f.action_id}" ${f.keep ? "" : "checked"} />
          <span class="entry-main">
            <span class="entry-path" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</span>
            ${f.keep ? `<span class="entry-reason dup-keep">기본 보관</span>` : ""}
          </span>
        </label>
        ${finderRevealButton(f.action_id, f.name || f.path)}
      </div>`).join("");
    el.innerHTML = `
      <div class="dup-group-head"><b>${group.each_human}</b> 파일 ${group.files.length}개 · ${group.reclaimable_human} 정리 가능</div>
      ${rows}`;
    el.querySelectorAll("input[data-id]").forEach((cb) => {
      if (cb.checked) selDup.add(cb.dataset.id);
      cb.addEventListener("change", () => {
        cb.checked ? selDup.add(cb.dataset.id) : selDup.delete(cb.dataset.id);
        updateDupSelection();
      });
    });
    wireRevealButtons(el);
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
  list.innerHTML = `<div class="q-empty">설치된 앱과 관련 파일을 분석하는 중…</div>`;
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
    list.innerHTML = `<div class="q-empty">표시할 앱이 없습니다.</div>`;
    return;
  }
  for (const app of data.apps) {
    const el = document.createElement("div");
    el.className = "card";
    const initial = escapeHtml(app.name.slice(0, 1).toUpperCase());
    const leftoverRows = app.leftovers.map((f) => `
      <div class="entry">
        <label class="entry-select">
          <input type="checkbox" data-id="${f.action_id}" data-app="${app.app_action_id}" />
          <span class="entry-main"><span class="entry-path" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</span>
            <span class="entry-reason">잔여 파일</span></span>
        </label>
        ${finderRevealButton(f.action_id, f.name || f.path)}
        <span class="entry-size">${f.allocated_human}</span>
      </div>`).join("");
    el.innerHTML = `
      <div class="app-head">
        <div class="app-icon">${initial}</div>
        <div><div class="app-name">${escapeHtml(app.name)}</div>
          <div class="app-sub">앱 ${app.app_human} · 잔여 ${app.leftover_human} · ${app.leftovers.length}개 파일</div></div>
        <div class="cat-size"><b>${app.total_human}</b><span class="cat-caret">›</span></div>
      </div>
      <div class="cat-body">
        <div class="cat-selectall"><label class="chk"><input type="checkbox" class="app-all" data-app="${app.app_action_id}" /> 앱과 잔여 파일 모두 선택</label></div>
        <div class="entry">
          <label class="entry-select">
            <input type="checkbox" data-id="${app.app_action_id}" data-app="${app.app_action_id}" />
            <span class="entry-main"><span class="entry-path">${escapeHtml(app.path)}</span>
              <span class="entry-reason">응용 프로그램 본체</span></span>
          </label>
          ${finderRevealButton(app.app_action_id, app.name)}
          <span class="entry-size">${app.app_human}</span>
        </div>
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
    wireRevealButtons(el);
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

function bytesForIds(ids) {
  const wanted = new Set(ids);
  const sizes = new Map();
  for (const entry of lastScan?.entries || []) {
    sizes.set(entry.action_id, entry.allocated_bytes || 0);
  }
  for (const group of lastScan?.duplicates || []) {
    for (const file of group.files) sizes.set(file.action_id, group.each_bytes || 0);
  }
  for (const app of lastApps?.apps || []) {
    sizes.set(app.app_action_id, app.app_bytes || 0);
    for (const file of app.leftovers) {
      sizes.set(file.action_id, file.allocated_bytes || 0);
    }
  }
  return [...wanted].reduce((total, id) => total + (sizes.get(id) || 0), 0);
}

/* ---------- quarantine ---------- */
function formatQuarantinedAt(timestamp) {
  if (!timestamp) return "시각 정보 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestamp * 1000));
}

function filteredQuarantineItems() {
  const query = document.getElementById("q-search").value.trim().toLocaleLowerCase("ko-KR");
  if (!query) return lastQuarantine;
  return lastQuarantine.filter((item) =>
    item.original_path.toLocaleLowerCase("ko-KR").includes(query));
}

function renderQuarantine() {
  const list = document.getElementById("quarantine-list");
  const tools = document.getElementById("q-tools");
  const totalBytes = lastQuarantine.reduce(
    (total, item) => total + item.allocated_bytes,
    0,
  );
  document.getElementById("q-summary").textContent = lastQuarantine.length
    ? `${lastQuarantine.length}개 항목 · ${fmtBytes(totalBytes)} 보관 중`
    : "격리함이 비어 있습니다";
  tools.hidden = lastQuarantine.length === 0;

  if (!lastQuarantine.length) {
    list.innerHTML = `<div class="q-empty">아직 격리한 항목이 없습니다.<br />‘공간 요약’에서 정리할 항목을 선택해보세요.</div>`;
    updateQSelection();
    return;
  }

  const filtered = filteredQuarantineItems();
  if (!filtered.length) {
    list.innerHTML = `<div class="q-empty">검색한 경로와 일치하는 항목이 없습니다.</div>`;
    updateQSelection();
    return;
  }

  list.innerHTML = "";
  for (const item of filtered) {
    const el = document.createElement("div");
    el.className = "q-item";
    const actionId = escapeHtml(item.action_id);
    el.innerHTML = `
      <input class="q-check" type="checkbox" data-q-id="${actionId}"
        ${selQ.has(item.action_id) ? "checked" : ""} />
      <span class="cat-icon">↩</span>
      <span class="entry-main">
        <span class="entry-path" title="${escapeHtml(item.original_path)}">${escapeHtml(item.original_path)}</span>
        <span class="entry-reason">${fmtBytes(item.allocated_bytes)} · ${formatQuarantinedAt(item.quarantined_at)}</span>
      </span>
      ${finderRevealButton(
        item.action_id,
        item.original_path,
        "quarantine",
        item.instance_token,
      )}
      <button class="btn ghost small" data-restore="${actionId}">원래 위치로</button>`;
    el.querySelector("[data-q-id]").addEventListener("change", (event) => {
      event.target.checked ? selQ.add(item.action_id) : selQ.delete(item.action_id);
      updateQSelection();
    });
    el.querySelector("[data-restore]").addEventListener("click", async (event) => {
      event.target.disabled = true;
      try {
        await api("/api/restore", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action_id: item.action_id,
            instance_token: item.instance_token,
          }),
        });
        toast("원래 위치로 복원했습니다.", "ok");
        await loadQuarantine();
      } catch (e) {
        toast(e.message, "err");
        event.target.disabled = false;
      }
    });
    wireRevealButtons(el);
    list.appendChild(el);
  }
  updateQSelection();
}

function updateQSelection() {
  const selected = lastQuarantine.filter((item) => selQ.has(item.action_id));
  const selectedBytes = selected.reduce(
    (total, item) => total + item.allocated_bytes,
    0,
  );
  const visibleIds = new Set(
    filteredQuarantineItems().map((item) => item.action_id),
  );
  const hiddenSelected = selected.filter(
    (item) => !visibleIds.has(item.action_id),
  ).length;
  document.getElementById("q-selection").textContent = selected.length
    ? `${selected.length}개 · ${fmtBytes(selectedBytes)} 선택` +
      (hiddenSelected ? ` · 현재 숨겨진 항목 ${hiddenSelected}개 포함` : "")
    : "선택한 항목 없음";
  document.getElementById("empty-q").disabled = selected.length === 0;

  const visible = filteredQuarantineItems();
  const selectAll = document.getElementById("q-select-all");
  const selectedVisible = visible.filter((item) => selQ.has(item.action_id)).length;
  selectAll.checked = visible.length > 0 && selectedVisible === visible.length;
  selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
}

async function loadQuarantine() {
  const list = document.getElementById("quarantine-list");
  list.innerHTML = `<div class="q-empty">불러오는 중…</div>`;
  try {
    const data = await api("/api/quarantine");
    lastQuarantine = data.items;
    selQ.clear();
    renderQuarantine();
  } catch (e) {
    lastQuarantine = [];
    selQ.clear();
    document.getElementById("q-summary").textContent = "";
    document.getElementById("q-tools").hidden = true;
    updateQSelection();
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

async function emptyQuarantine() {
  const selected = lastQuarantine.filter((item) => selQ.has(item.action_id));
  if (!selected.length) return;
  const selectedBytes = selected.reduce(
    (total, item) => total + item.allocated_bytes,
    0,
  );
  if (!confirm(
    `선택한 ${selected.length}개 항목 (${fmtBytes(selectedBytes)})을 macOS 휴지통으로 보낼까요?\n\n` +
    "Finder에서 휴지통을 비우기 전까지는 복구할 수 있으며, 비운 뒤에야 실제 여유 공간이 늘어납니다."
  )) return;
  const button = document.getElementById("empty-q");
  button.disabled = true;
  button.textContent = "휴지통으로 보내는 중…";
  try {
    const out = await api("/api/empty", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: selected.map((item) => ({
          action_id: item.action_id,
          instance_token: item.instance_token,
        })),
        confirmed: true,
      }),
    });
    toast(`${out.count}개 항목을 휴지통으로 보냈습니다. Finder에서 비우면 공간이 확보됩니다.`, "ok");
    await loadQuarantine();
  } catch (e) {
    toast(e.message, "err");
    await loadQuarantine();
  } finally {
    button.textContent = "선택 항목 휴지통으로";
    updateQSelection();
  }
}

/* ---------- wiring ---------- */
function switchView(view) {
  document.querySelectorAll(".nav-item").forEach((b) => {
    const active = b.dataset.view === view;
    b.classList.toggle("active", active);
    active ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current");
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById("view-" + view).classList.add("active");
  if (view === "quarantine") loadQuarantine();
  if (view === "duplicates") renderDuplicates();
  if (view === "apps" && !lastApps) loadApps();
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("preset").addEventListener("change", (e) => {
    document.getElementById("path-input").disabled = e.target.value !== "custom";
    updateScanCta();
  });
  document.getElementById("path-input").addEventListener("input", updateScanCta);
  document.getElementById("path-input").disabled = true;
  updateScanCta();
  document.getElementById("scan-btn").addEventListener("click", runScan);
  document.getElementById("scan-btn-2").addEventListener("click", runScan);
  document.getElementById("result-search").addEventListener("input", renderFilteredResults);
  document.getElementById("risk-filter").addEventListener("change", renderFilteredResults);
  document.getElementById("export-scan").addEventListener("click", exportLastScan);

  document.getElementById("reclaim-btn").addEventListener("click", async (e) => {
    const ids = [...selDash];
    const out = await reclaimIds(ids, e.target, "선택 항목 격리", bytesForIds(ids));
    if (out) { selDash.clear(); await runScan(); }
  });
  document.getElementById("clear-sel").addEventListener("click", () => {
    selDash.clear();
    renderFilteredResults();
  });

  document.getElementById("dup-reclaim").addEventListener("click", async (e) => {
    const ids = [...selDup];
    const out = await reclaimIds(ids, e.target, "선택 파일 격리", bytesForIds(ids));
    if (out) await runScan();
  });

  document.getElementById("apps-scan").addEventListener("click", loadApps);
  document.getElementById("apps-reclaim").addEventListener("click", async (e) => {
    const ids = [...selApps];
    const out = await reclaimIds(ids, e.target, "선택 항목 격리", bytesForIds(ids));
    if (out) await loadApps();
  });

  document.getElementById("refresh-q").addEventListener("click", loadQuarantine);
  document.getElementById("empty-q").addEventListener("click", emptyQuarantine);
  document.getElementById("q-search").addEventListener("input", renderQuarantine);
  document.getElementById("q-select-all").addEventListener("change", (event) => {
    for (const item of filteredQuarantineItems()) {
      event.target.checked ? selQ.add(item.action_id) : selQ.delete(item.action_id);
    }
    renderQuarantine();
  });
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.addEventListener("click", () => switchView(b.dataset.view)));
});
