"use strict";

const CATEGORY_META = {
  project_dependency: { icon: "📦", label: "프로젝트 의존성" },
  package_cache: { icon: "🗃️", label: "패키지 캐시" },
  build_cache: { icon: "🏗️", label: "빌드 캐시" },
  rust_build: { icon: "🦀", label: "Rust 빌드 산출물" },
  xcode_derived_data: { icon: "🔨", label: "Xcode 파생 데이터" },
  xcode_simulator: { icon: "📱", label: "Xcode 시뮬레이터" },
  xcode_device_support: { icon: "📲", label: "iOS/watchOS 기기 기호" },
  xcode_archives: { icon: "📦", label: "Xcode 아카이브" },
  docker_data: { icon: "🐳", label: "Docker 캐시/데이터" },
  homebrew_cache: { icon: "🍺", label: "Homebrew 캐시" },
  cocoapods_cache: { icon: "🍫", label: "CocoaPods 캐시" },
  pip_cache: { icon: "🐍", label: "pip 캐시" },
  go_cache: { icon: "🦫", label: "Go 빌드 캐시" },
  maven_cache: { icon: "☕", label: "Maven 라이브러리 캐시" },
  android_emulator: { icon: "🤖", label: "Android 에뮬레이터" },
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
const DIAGNOSTIC_STATUS = {
  ready: { label: "준비됨" },
  attention: { label: "확인 필요" },
  blocked: { label: "조치 필요" },
};
const DIAGNOSTIC_GROUPS = [
  ["protected", "보호 폴더 접근", "macOS가 관리하는 주요 사용자 폴더"],
  ["safety", "안전한 이동 경로", "격리와 휴지통 이동에 필요한 쓰기 권한"],
  ["environment", "앱 실행 환경", "런타임·Finder·로컬 서버 상태"],
];
const API_TOKEN =
  document.querySelector('meta[name="spacekeeper-api-token"]')?.content || "";

let lastScan = null;
let lastApps = null;
let lastQuarantine = [];
let activeScanJobId = null;
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
  el.setAttribute("role", kind === "err" ? "alert" : "status");
  el.setAttribute("aria-live", kind === "err" ? "assertive" : "polite");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), 3600);
}

function syncGroupCheckbox(root, allSelector, itemSelector = "input[data-id]") {
  const all = root.querySelector(allSelector);
  const boxes = [...root.querySelectorAll(itemSelector)].filter((box) => !box.disabled);
  if (!all || !boxes.length) return;
  const checked = boxes.filter((box) => box.checked).length;
  all.checked = checked === boxes.length;
  all.indeterminate = checked > 0 && checked < boxes.length;
}

function wireDisclosure(card, selector) {
  const trigger = card.querySelector(selector);
  if (!trigger) return;
  trigger.addEventListener("click", () => {
    card.classList.toggle("open");
    trigger.setAttribute("aria-expanded", String(card.classList.contains("open")));
  });
}
async function api(path, opts = {}) {
  const headers = new Headers(opts.headers || {});
  headers.set("X-Spacekeeper-Token", API_TOKEN);
  const res = await fetch(path, {
    ...opts,
    headers,
    cache: "no-store",
    credentials: "same-origin",
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "요청을 처리하지 못했습니다");
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
function closeToolMenu() {
  const pop = document.getElementById("tool-more-pop");
  const btn = document.getElementById("tool-more");
  if (pop) pop.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function wireToolMenu() {
  const btn = document.getElementById("tool-more");
  const pop = document.getElementById("tool-more-pop");
  if (!btn || !pop) return;
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = pop.hidden;
    pop.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  });
  document.addEventListener("click", (e) => {
    if (!pop.hidden && !pop.contains(e.target) && e.target !== btn) closeToolMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeToolMenu();
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
const TR = (ko) => (window.t ? window.t(ko) : ko);
const isEn = () => Boolean(window.SKI18N && window.SKI18N.currentLang() === "en");
function countLine(n, bytes) {
  return isEn() ? `${n} items · ${fmtBytes(bytes)}` : `${n}개 항목 · ${fmtBytes(bytes)}`;
}

/** OS confirm() 대신 앱 스타일의 확인 모달. boolean으로 resolve. */
function confirmDialog({ title, body, count, confirmLabel, danger }) {
  return new Promise((resolve) => {
    const modal = document.getElementById("confirm-modal");
    if (!modal || typeof modal.showModal !== "function") {
      resolve(confirm(`${TR(title)}\n\n${count ? count + "\n\n" : ""}${TR(body)}`));
      return;
    }
    modal.querySelector(".confirm-title").textContent = TR(title);
    const countEl = modal.querySelector(".confirm-count");
    countEl.textContent = count || "";
    countEl.hidden = !count;
    modal.querySelector(".confirm-body").textContent = TR(body);
    const ok = modal.querySelector(".confirm-ok");
    ok.textContent = TR(confirmLabel);
    ok.classList.toggle("danger", Boolean(danger));
    ok.classList.toggle("primary", !danger);
    const cancel = modal.querySelector(".confirm-cancel");
    let done = false;
    const finish = (val) => {
      if (done) return;
      done = true;
      ok.onclick = cancel.onclick = modal.onclose = null;
      if (modal.open) modal.close();
      resolve(val);
    };
    ok.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
    modal.onclose = () => finish(false);
    modal.showModal();
    cancel.focus();
  });
}

async function reclaimIds(ids, btn, label, selectedBytes = 0) {
  if (!ids.length) return null;
  if (!(await confirmDialog({
    title: "선택 항목을 격리할까요?",
    count: countLine(ids.length, selectedBytes),
    body: "원래 위치에서 Spacekeeper 격리함으로 옮겨집니다. 저장 공간은 아직 늘지 않으며 언제든 복원할 수 있어요.",
    confirmLabel: "격리하기",
  }))) return null;
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

/* ---------- 즐겨찾는 위치 ---------- */
function currentScanPath() {
  const preset = document.getElementById("preset").value;
  if (preset === "downloads") return "~/Downloads";
  if (preset === "home") return "~";
  if (preset === "desktop") return "~/Desktop";
  return document.getElementById("path-input").value.trim();
}

function favLabel(path) {
  const clean = path.replace(/\/+$/, "");
  const name = clean.split("/").pop() || clean;
  return name === "" ? clean : name;
}

async function loadFavorites() {
  try {
    const data = await api("/api/favorites");
    renderFavorites(data.favorites || []);
  } catch (_) {
    renderFavorites([]);
  }
}

function renderFavorites(paths) {
  const list = document.getElementById("fav-list");
  if (!list) return;
  list.innerHTML = "";
  list.hidden = paths.length === 0;
  for (const path of paths) {
    const chip = document.createElement("span");
    chip.className = "fav-chip";
    chip.title = path;
    const open = document.createElement("button");
    open.type = "button";
    open.className = "fav-chip-open";
    open.innerHTML =
      `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6l2.5 5.2 5.7.8-4.1 4 1 5.7L12 17.9l-5.1 2.4 1-5.7-4.1-4 5.7-.8z"/></svg>` +
      `<span>${escapeHtml(favLabel(path))}</span>`;
    open.addEventListener("click", () => {
      const preset = document.getElementById("preset");
      preset.value = "custom";
      preset.dispatchEvent(new Event("change"));
      const input = document.getElementById("path-input");
      input.value = path;
      input.dispatchEvent(new Event("input"));
      runScan();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "fav-chip-remove";
    remove.setAttribute("aria-label", "즐겨찾기에서 제거");
    remove.textContent = "✕";
    remove.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        const data = await api("/api/favorites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "remove", path }),
        });
        renderFavorites(data.favorites || []);
      } catch (err) {
        toast(err.message, "err");
      }
    });
    chip.appendChild(open);
    chip.appendChild(remove);
    list.appendChild(chip);
  }
}

async function addCurrentFavorite() {
  const path = currentScanPath();
  if (!path) {
    toast("먼저 분석할 경로를 골라주세요.", "err");
    return;
  }
  try {
    const data = await api("/api/favorites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "add", path }),
    });
    renderFavorites(data.favorites || []);
    toast("즐겨찾기에 추가했습니다.", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
}

function setScanControlsBusy(busy) {
  document.getElementById("scan-btn").disabled = busy;
  document.getElementById("scan-btn-2").disabled = busy;
  document.getElementById("preset").disabled = busy;
  document.getElementById("opt-duplicates").disabled = busy;
  document.getElementById("exclude-input").disabled = busy;
  document.getElementById("path-input").disabled = busy ||
    document.getElementById("preset").value !== "custom";
}

function resetScanProgress(targetLabel) {
  document.getElementById("scanning-text").textContent =
    `${targetLabel} 저장 공간을 분석하는 중…`;
  document.getElementById("scan-progress-meta").textContent =
    "파일을 살펴보는 중이에요.";
  document.getElementById("scan-current-path").textContent =
    "분석할 경로를 준비하고 있어요.";
  document.getElementById("scan-phase-note").textContent =
    "분석은 파일을 변경하지 않아요.";
  const track = document.getElementById("scan-progress-track");
  track.classList.add("indeterminate");
  track.removeAttribute("aria-valuenow");
  document.getElementById("scan-progress-fill").style.width = "";
  const cancel = document.getElementById("cancel-scan");
  cancel.disabled = true;
  cancel.textContent = "분석 준비 중…";
}

function updateScanProgress(job, targetLabel) {
  const progress = job.progress || {};
  const phase = progress.phase || "scanning";
  const files = Number(progress.scanned_files || 0);
  const bytes = Number(progress.scanned_bytes || 0);
  const candidates = Number(progress.candidates_found || 0);
  const track = document.getElementById("scan-progress-track");
  const fill = document.getElementById("scan-progress-fill");
  const title = document.getElementById("scanning-text");
  const meta = document.getElementById("scan-progress-meta");
  const note = document.getElementById("scan-phase-note");

  if (job.status === "canceling") {
    title.textContent = "분석을 안전하게 멈추는 중…";
    note.textContent = "현재 파일 확인을 마치면 바로 중단합니다.";
  } else if (phase === "duplicates") {
    title.textContent = "파일 내용을 비교하는 중…";
    note.textContent = "크기가 같은 파일만 안전하게 비교하고 있어요.";
  } else if (phase === "finalizing") {
    title.textContent = "분석 결과를 정리하는 중…";
    note.textContent = "정리 후보와 주의도를 마지막으로 확인하고 있어요.";
  } else {
    title.textContent = `${targetLabel} 저장 공간을 분석하는 중…`;
    note.textContent = "분석은 파일을 변경하지 않아요.";
  }

  if (phase === "duplicates" && progress.duplicate_files_total) {
    const done = Number(progress.duplicate_files_done || 0);
    const total = Number(progress.duplicate_files_total);
    const percent = Math.min(100, Math.round(done / total * 100));
    track.classList.remove("indeterminate");
    track.setAttribute("aria-valuenow", String(percent));
    fill.style.width = `${percent}%`;
    meta.textContent = `중복 후보 ${done.toLocaleString()} / ${total.toLocaleString()}개 비교 · ` +
      `전체 ${files.toLocaleString()}개 파일`;
  } else if (phase === "finalizing") {
    track.classList.remove("indeterminate");
    track.setAttribute("aria-valuenow", "100");
    fill.style.width = "100%";
    meta.textContent = `${files.toLocaleString()}개 파일 · ${fmtBytes(bytes)} 확인 · ` +
      `후보 ${candidates.toLocaleString()}개`;
  } else {
    track.classList.add("indeterminate");
    track.removeAttribute("aria-valuenow");
    fill.style.width = "";
    meta.textContent = `${files.toLocaleString()}개 파일 · ${fmtBytes(bytes)} 확인 · ` +
      `후보 ${candidates.toLocaleString()}개`;
  }
  document.getElementById("scan-current-path").textContent =
    progress.current_path || "분석 경로를 확인하고 있어요.";
}

async function waitForScan(jobId, targetLabel) {
  while (activeScanJobId === jobId) {
    const job = await api(`/api/scan/status?job_id=${encodeURIComponent(jobId)}`);
    updateScanProgress(job, targetLabel);
    if (!["running", "canceling"].includes(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 180));
  }
  return null;
}

async function cancelScan() {
  if (!activeScanJobId) return;
  const button = document.getElementById("cancel-scan");
  button.disabled = true;
  button.textContent = "취소 요청 중…";
  try {
    const job = await api("/api/scan/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: activeScanJobId }),
    });
    updateScanProgress(job, scanTargetLabel());
  } catch (e) {
    button.disabled = false;
    button.textContent = "분석 취소";
    toast(e.message, "err");
  }
}

async function runScan() {
  if (activeScanJobId) return;
  const path = resolvePath();
  const duplicates = document.getElementById("opt-duplicates").checked;
  const excluded = document.getElementById("exclude-input").value
    .split(/[\n,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
  const targetLabel = scanTargetLabel();
  document.getElementById("empty-state").hidden = true;
  document.getElementById("results").hidden = true;
  document.getElementById("scanning").hidden = false;
  resetScanProgress(targetLabel);
  setScanControlsBusy(true);

  try {
    const started = await api("/api/scan/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: [path], duplicates, exclude: excluded }),
    });
    activeScanJobId = started.job_id;
    document.getElementById("cancel-scan").disabled = false;
    document.getElementById("cancel-scan").textContent = "분석 취소";
    updateScanProgress(started, targetLabel);
    const finished = await waitForScan(started.job_id, targetLabel);
    if (!finished) return;
    if (finished.status === "cancelled") {
      toast("분석을 취소했습니다. 파일은 변경되지 않았습니다.", "ok");
      return;
    }
    if (finished.status === "failed") {
      throw new Error(finished.error || "분석을 완료하지 못했습니다.");
    }
    const data = finished.result;
    lastScan = data;
    selDash.clear();
    selDup.clear();
    document.getElementById("result-search").value = "";
    document.getElementById("risk-filter").value = "all";
    renderResults(data);
    renderDuplicates();
  } catch (e) {
    toast(e.message, "err");
  } finally {
    activeScanJobId = null;
    setScanControlsBusy(false);
    document.getElementById("scanning").hidden = true;
    document.getElementById("results").hidden = !lastScan;
    document.getElementById("empty-state").hidden = Boolean(lastScan);
  }
}

function sumBytes(entries) { return entries.reduce((s, e) => s + e.allocated_bytes, 0); }

/* 큰 용량 숫자를 도넛 애니메이션과 함께 0→목표로 카운트업 */
function animateBytes(el, target) {
  if (!el) return;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !(target > 0)) { el.textContent = fmtBytes(target || 0); return; }
  const dur = 850;
  const start = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const token = (el.__animToken = (el.__animToken || 0) + 1);
  function frame(now) {
    if (el.__animToken !== token) return; // 새 스캔이 시작되면 이전 애니메이션 취소
    const t = Math.min(1, (now - start) / dur);
    el.textContent = fmtBytes(target * ease(t));
    if (t < 1) requestAnimationFrame(frame);
    else el.textContent = fmtBytes(target);
  }
  requestAnimationFrame(frame);
  // rAF가 스로틀·중단돼도(백그라운드 탭 등) 최종값은 반드시 찍히게 보증
  setTimeout(() => {
    if (el.__animToken === token) el.textContent = fmtBytes(target);
  }, dur + 150);
}

function renderResults(data) {
  document.getElementById("results").hidden = false;

  const usedRatio = data.disk.total ? data.disk.used / data.disk.total : 0;
  const circ = 2 * Math.PI * 52;
  const used = document.getElementById("donut-used");
  used.style.strokeDasharray = circ;
  used.style.strokeDashoffset = circ * (1 - usedRatio);
  document.getElementById("donut-free").textContent = fmtBytes(data.disk.free);
  animateBytes(document.getElementById("reclaimable-total"), data.review_bytes);

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
  const permissionMeta = data.skipped?.permission_denied
    ? `<span class="sep">·</span><button class="meta-link" type="button" data-open-diagnostics>` +
      `권한 제한 ${data.skipped.permission_denied}건 확인</button>`
    : "";
  const heroMeta = document.getElementById("hero-meta");
  heroMeta.innerHTML =
    ["low", "medium", "high"].map((r) =>
      `<span><span class="dot ${r}"></span>${RISK_LABEL[r]} ${fmtBytes(risk[r])}</span>`).join("") +
    `<span class="sep">·</span><span>파일 ${data.scanned_files.toLocaleString()}개 · ${data.duration.toFixed(1)}초</span>` +
    excludedMeta + permissionMeta;
  heroMeta.querySelector("[data-open-diagnostics]")?.addEventListener(
    "click",
    () => switchView("diagnostics"),
  );

  renderFilteredResults();
}

function selectLowRisk() {
  if (!lastScan) return;
  const low = lastScan.entries.filter((e) => e.risk === "low");
  if (!low.length) {
    toast("선택할 낮은 위험 항목이 없습니다.", "err");
    return;
  }
  const added = low.filter((entry) => !selDash.has(entry.action_id));
  for (const entry of low) selDash.add(entry.action_id);
  renderFilteredResults();
  const actions = document.getElementById("actions-bar");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  actions.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
  toast(
    added.length
      ? `낮은 위험 ${added.length}개를 선택했습니다. 목록을 확인한 뒤 격리하세요.`
      : "낮은 위험 항목이 이미 모두 선택되어 있습니다.",
    "ok",
  );
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
  const sortMode = document.getElementById("result-sort")?.value || "size";
  const riskRank = { high: 0, medium: 1, low: 2 };
  const order = Object.keys(groups);
  if (sortMode === "name") {
    order.sort((a, b) => catMeta(a).label.localeCompare(catMeta(b).label, "ko-KR"));
  } else if (sortMode === "risk") {
    order.sort((a, b) =>
      (riskRank[groups[a][0].risk] - riskRank[groups[b][0].risk]) ||
      (sumBytes(groups[b]) - sumBytes(groups[a])));
  } else {
    order.sort((a, b) => sumBytes(groups[b]) - sumBytes(groups[a]));
  }

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
  const maxCat = Math.max(1, ...order.map((cat) => sumBytes(groups[cat])));
  for (const cat of order) list.appendChild(renderCategory(cat, groups[cat], maxCat));
  updateDashSelection();
}

function renderCategory(cat, entries, maxCat = 1) {
  const meta = catMeta(cat);
  const risk = entries[0].risk;
  const catBytes = sumBytes(entries);
  const pct = Math.max(7, Math.round((catBytes / maxCat) * 100));
  const bodyId = `cat-body-${cat.replace(/[^a-z0-9_-]/gi, "-")}`;
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.cat = cat;
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
    <button type="button" class="cat-head" aria-expanded="${risk === "low"}" aria-controls="${bodyId}"
      aria-label="${escapeHtml(meta.label)} · ${entries.length}개 · ${fmtBytes(catBytes)} · ${RISK_LABEL[risk]}">
      <span class="cat-icon" aria-hidden="true">${meta.icon}</span>
      <span class="cat-labels"><span class="cat-title">${meta.label}</span><span class="cat-sub">${entries.length}개 항목을 확인하세요</span></span>
      <span class="cat-track" aria-hidden="true"><span style="width:${pct}%"></span></span>
      <span class="cat-size"><b>${fmtBytes(catBytes)}</b><span class="badge ${risk}">${RISK_LABEL[risk]}</span><span class="cat-caret">›</span></span>
    </button>
    <div class="cat-body" id="${bodyId}">
      <div class="cat-selectall"><label class="chk"><input type="checkbox" class="cat-all" /> 이 그룹 모두 선택</label></div>
      ${rows}
    </div>`;
  if (risk === "low") el.classList.add("open");
  wireDisclosure(el, ".cat-head");
  el.querySelectorAll("input[data-id]").forEach((cb) => {
    if (cb.checked) selDash.add(cb.dataset.id);
    cb.addEventListener("change", () => {
      cb.checked ? selDash.add(cb.dataset.id) : selDash.delete(cb.dataset.id);
      updateDashSelection();
    });
  });
  const all = el.querySelector(".cat-all");
  syncGroupCheckbox(el, ".cat-all");
  all.addEventListener("change", () => {
    all.indeterminate = false;
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
    syncGroupCheckbox(card, ".cat-all");
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
          <input type="checkbox" data-id="${f.action_id}" ${f.keep ? "disabled" : ""} />
          <span class="entry-main">
            <span class="entry-path" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</span>
            ${f.keep ? `<span class="entry-reason dup-keep">기본 보관 · 이 화면에서는 선택할 수 없어요</span>` : `<span class="entry-reason">내용이 같은 중복본</span>`}
          </span>
        </label>
        ${finderRevealButton(f.action_id, f.name || f.path)}
      </div>`).join("");
    el.innerHTML = `
      <div class="dup-group-head">
        <span><b>${group.each_human}</b> 파일 ${group.files.length}개 · ${group.reclaimable_human} 정리 가능</span>
        <label class="chk"><input type="checkbox" class="dup-all" /> 보관본 제외 모두 선택</label>
      </div>
      ${rows}`;
    el.querySelectorAll("input[data-id]").forEach((cb) => {
      cb.addEventListener("change", () => {
        cb.checked ? selDup.add(cb.dataset.id) : selDup.delete(cb.dataset.id);
        syncGroupCheckbox(el, ".dup-all");
        updateDupSelection();
      });
    });
    const dupAll = el.querySelector(".dup-all");
    dupAll.addEventListener("change", () => {
      el.querySelectorAll("input[data-id]:not(:disabled)").forEach((cb) => {
        cb.checked = dupAll.checked;
        cb.checked ? selDup.add(cb.dataset.id) : selDup.delete(cb.dataset.id);
      });
      dupAll.indeterminate = false;
      updateDupSelection();
    });
    wireRevealButtons(el);
    list.appendChild(el);
  }
  updateDupSelection();
}

function updateDupSelection() {
  document.getElementById("dup-actions").hidden = selDup.size === 0;
  document.getElementById("dup-selection").textContent = selDup.size
    ? `${selDup.size}개 · ${fmtBytes(bytesForIds([...selDup]))} 선택`
    : "선택한 항목 없음";
}

/* ---------- apps ---------- */
async function loadApps() {
  const list = document.getElementById("apps-list");
  list.innerHTML = `<div class="q-empty is-loading">설치된 앱과 관련 파일을 분석하는 중…</div>`;
  try {
    const data = await api("/api/apps");
    lastApps = data;
    selApps.clear();
    renderApps(data);
  } catch (e) {
    selApps.clear();
    updateAppsSelection();
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

function renderApps(data) {
  const list = document.getElementById("apps-list");
  list.innerHTML = "";
  if (!data.apps.length) {
    updateAppsSelection();
    list.innerHTML = `<div class="q-empty">표시할 앱이 없습니다.</div>`;
    return;
  }
  for (const app of data.apps) {
    const el = document.createElement("div");
    el.className = "card";
    const initial = escapeHtml(app.name.slice(0, 1).toUpperCase());
    const appBodyId = `app-body-${String(app.app_action_id).replace(/[^a-z0-9_-]/gi, "-")}`;
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
      <button type="button" class="app-head" aria-expanded="false" aria-controls="${appBodyId}"
        aria-label="${escapeHtml(app.name)} · 전체 ${app.total_human} · 관련 파일 ${app.leftovers.length}개">
        <span class="app-icon" aria-hidden="true">${initial}</span>
        <span><span class="app-name">${escapeHtml(app.name)}</span>
          <span class="app-sub">앱 ${app.app_human} · 잔여 ${app.leftover_human} · ${app.leftovers.length}개 파일</span></span>
        <span class="cat-size"><b>${app.total_human}</b><span class="cat-caret">›</span></span>
      </button>
      <div class="cat-body" id="${appBodyId}">
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
    wireDisclosure(el, ".app-head");
    el.querySelectorAll("input[data-id]").forEach((cb) => {
      cb.addEventListener("change", () => {
        cb.checked ? selApps.add(cb.dataset.id) : selApps.delete(cb.dataset.id);
        syncAppAll(el);
        updateAppsSelection();
      });
    });
    const appAll = el.querySelector(".app-all");
    appAll.addEventListener("change", () => {
      appAll.indeterminate = false;
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
  syncGroupCheckbox(card, ".app-all");
}

function updateAppsSelection() {
  document.getElementById("apps-actions").hidden = selApps.size === 0;
  document.getElementById("apps-selection").textContent = selApps.size
    ? `${selApps.size}개 · ${fmtBytes(bytesForIds([...selApps]))} 선택`
    : "선택한 항목 없음";
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
        aria-label="격리 항목 선택: ${escapeHtml(item.original_path)}"
        ${selQ.has(item.action_id) ? "checked" : ""} />
      <span class="cat-icon" aria-hidden="true">↩</span>
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
      <button class="btn ghost small" type="button" data-restore="${actionId}"
        aria-label="원래 위치로 복원: ${escapeHtml(item.original_path)}">원래 위치로</button>`;
    el.querySelector("[data-q-id]").addEventListener("change", (event) => {
      event.currentTarget.checked ? selQ.add(item.action_id) : selQ.delete(item.action_id);
      updateQSelection();
    });
    el.querySelector("[data-restore]").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
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
        button.disabled = false;
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
  list.innerHTML = `<div class="q-empty is-loading">불러오는 중…</div>`;
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
  if (!(await confirmDialog({
    title: "휴지통으로 보낼까요?",
    count: countLine(selected.length, selectedBytes),
    body: "Finder에서 휴지통을 비우기 전까지는 복구할 수 있으며, 비운 뒤에야 실제 여유 공간이 늘어납니다.",
    confirmLabel: "휴지통으로 보내기",
    danger: true,
  }))) return;
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

/* ---------- environment diagnostics ---------- */
function diagnosticCard(check) {
  const status = DIAGNOSTIC_STATUS[check.status] || DIAGNOSTIC_STATUS.attention;
  const path = check.path
    ? `<div class="diag-path" title="${escapeHtml(check.path)}">${escapeHtml(check.path)}</div>`
    : "";
  return `
    <article class="diag-card ${escapeHtml(check.status)}">
      <div class="diag-card-title">
        <i aria-hidden="true"></i>
        <b>${escapeHtml(check.label)}</b>
        <span class="diag-status">${status.label}</span>
      </div>
      <p class="diag-detail">${escapeHtml(check.detail)}</p>
      ${path}
    </article>`;
}

function renderDiagnostics(data) {
  const overview = document.getElementById("diagnostics-overview");
  const overviewCopy = {
    ready: ["현재 실행 환경이 준비됐습니다.", "주요 폴더와 안전 기능을 사용할 수 있습니다."],
    attention: ["확인할 항목이 있습니다.", "폴더 생성 여부나 실행 환경 안내를 확인해주세요."],
    blocked: ["권한 또는 환경 조치가 필요해요.", "조치 필요 항목을 확인한 뒤 다시 점검해주세요."],
  }[data.overall_status];
  const checkedAt = new Date(data.checked_at).toLocaleString("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  overview.className = `diagnostics-overview ${data.overall_status}`;
  overview.setAttribute("aria-busy", "false");
  overview.innerHTML = `
    <div class="diag-overview-icon" aria-hidden="true"></div>
    <div>
      <div class="diag-overview-kicker">현재 실행 환경 · ${escapeHtml(checkedAt)} 점검</div>
      <h2>${overviewCopy[0]}</h2>
      <p>${overviewCopy[1]}</p>
      <div class="diag-counts">
        <span class="diag-count ready"><i></i>준비됨 ${data.counts.ready}개</span>
        <span class="diag-count attention"><i></i>확인 ${data.counts.attention}개</span>
        <span class="diag-count blocked"><i></i>조치 ${data.counts.blocked}개</span>
      </div>
    </div>`;

  document.getElementById("diagnostics-groups").innerHTML =
    DIAGNOSTIC_GROUPS.map(([groupId, title, description]) => {
      const checks = data.checks.filter((check) => check.group === groupId);
      return `
        <section class="diag-section">
          <div class="diag-section-head">
            <h2>${title}</h2>
            <p>${description}</p>
          </div>
          <div class="diag-grid">${checks.map(diagnosticCard).join("")}</div>
        </section>`;
    }).join("");

  document.getElementById("diagnostics-runtime-note").textContent =
    data.runtime.mode === "bundled"
      ? "현재 앱에 포함된 독립 실행 런타임을 점검한 결과입니다. 별도의 Python 설치가 필요하지 않습니다."
      : data.runtime.mode === "staged"
      ? "현재 데스크톱 앱용 런타임을 점검한 결과입니다."
      : "개발 서버에서는 터미널·Python 권한이 반영될 수 있어 데스크톱 앱 결과와 다를 수 있습니다.";
}

async function loadDiagnostics() {
  const refresh = document.getElementById("diagnostics-refresh");
  refresh.disabled = true;
  refresh.textContent = "점검하는 중…";
  const overview = document.getElementById("diagnostics-overview");
  overview.className = "diagnostics-overview loading";
  overview.setAttribute("aria-busy", "true");
  overview.innerHTML = `
    <div class="diag-overview-icon" aria-hidden="true"></div>
    <div>
      <div class="diag-overview-kicker">현재 실행 환경</div>
      <h2>권한과 앱 상태를 점검하고 있어요.</h2>
      <p>임시 검사 파일은 즉시 정리합니다.</p>
    </div>`;
  document.getElementById("diagnostics-groups").innerHTML =
    `<div class="diag-loading">보호 폴더와 안전 기능을 하나씩 확인하고 있어요.</div>`;
  try {
    renderDiagnostics(await api("/api/diagnostics"));
  } catch (e) {
    overview.className = "diagnostics-overview blocked";
    overview.setAttribute("aria-busy", "false");
    overview.innerHTML = `
      <div class="diag-overview-icon" aria-hidden="true"></div>
      <div><div class="diag-overview-kicker">점검 실패</div>
      <h2>환경 상태를 불러오지 못했어요.</h2>
      <p>${escapeHtml(e.message)}</p></div>`;
    document.getElementById("diagnostics-groups").innerHTML = "";
  } finally {
    refresh.disabled = false;
    refresh.textContent = "다시 점검";
  }
}

async function openSystemSettings(trigger) {
  const button = trigger instanceof HTMLElement
    ? trigger
    : document.getElementById("open-privacy-settings");
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "여는 중…";
  try {
    await api("/api/open-system-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    toast("시스템 설정을 열었습니다. 개인정보 보호 및 보안을 확인하세요.", "ok");
  } catch (e) {
    toast(e.message, "err");
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

async function smartClean() {
  selectLowRisk();
  const ids = [...selDash];
  if (!ids.length) {
    toast("격리할 낮은 위험 항목이 없습니다.", "ok");
    return;
  }
  const button = document.getElementById("smart-clean-btn");
  const bytes = bytesForIds(ids);
  const out = await reclaimIds(ids, button, "안전 항목 바로 정리", bytes);
  if (out) {
    selDash.clear();
    await runScan();
  }
}

/* ---------- wiring ---------- */
/* ---------- Live System Monitor ---------- */
async function updateSystemMonitor() {
  try {
    const sys = await api("/api/system-status");
    if (sys.cpu_load && document.getElementById("sys-cpu")) {
      document.getElementById("sys-cpu").textContent = `${sys.cpu_load["1m"]}`;
    }
    if (sys.memory && document.getElementById("sys-ram")) {
      document.getElementById("sys-ram").textContent = sys.memory.used_percent ? `${sys.memory.used_percent}%` : sys.memory.used_human;
    }
    if (sys.disk && document.getElementById("sys-disk")) {
      document.getElementById("sys-disk").textContent = sys.disk.free_human;
    }
  } catch (_) {}
}

function startSystemMonitor() {
  updateSystemMonitor();
  setInterval(updateSystemMonitor, 8000);
}

/* ---------- Space Treemap Visualizer ---------- */
let currentTreePath = "";

async function loadSpaceTree(targetPath) {
  const container = document.getElementById("tree-view-container");
  const bc = document.getElementById("tree-breadcrumb");
  if (!container || !bc) return;
  container.innerHTML = `<div class="q-empty is-loading">폴더 구조와 용량 비중을 분석하는 중…</div>`;
  bc.innerHTML = "";
  try {
    const url = targetPath ? `/api/space-tree?path=${encodeURIComponent(targetPath)}` : "/api/space-tree";
    const data = await api(url);
    currentTreePath = data.path;
    document.getElementById("tree-path-input").value = data.path;
    renderBreadcrumb(data.path);
    renderTreemap(data);
  } catch (e) {
    container.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

function renderBreadcrumb(fullPath) {
  const bc = document.getElementById("tree-breadcrumb");
  if (!bc) return;
  const parts = fullPath.split("/").filter(Boolean);
  let accumulated = "";
  let html = `<span class="tree-bc-item" data-path="/">/ (Root)</span>`;
  for (let i = 0; i < parts.length; i++) {
    accumulated += "/" + parts[i];
    const isLast = i === parts.length - 1;
    if (isLast) {
      html += ` <span aria-hidden="true">/</span> <span class="tree-bc-curr">${escapeHtml(parts[i])}</span>`;
    } else {
      const p = accumulated;
      html += ` <span aria-hidden="true">/</span> <span class="tree-bc-item" data-path="${escapeHtml(p)}">${escapeHtml(parts[i])}</span>`;
    }
  }
  bc.innerHTML = html;
  bc.querySelectorAll(".tree-bc-item").forEach((el) => {
    el.addEventListener("click", () => loadSpaceTree(el.dataset.path));
  });
}

/* Squarified treemap layout (Bruls et al.): block area ∝ size. */
function squarify(areas, x, y, w, h) {
  const out = [];
  const vals = areas.slice();
  let cx = x, cy = y, cw = w, ch = h;
  let row = [];
  const side = () => Math.min(cw, ch);
  const worst = (r, len) => {
    const s = r.reduce((a, b) => a + b, 0);
    if (s <= 0) return Infinity;
    const mx = Math.max(...r), mn = Math.min(...r);
    return Math.max((len * len * mx) / (s * s), (s * s) / (len * len * mn));
  };
  const flush = (r) => {
    const s = r.reduce((a, b) => a + b, 0);
    if (cw >= ch) {
      const colW = s / ch;
      let yy = cy;
      for (const a of r) { const hh = a / colW; out.push({ x: cx, y: yy, w: colW, h: hh }); yy += hh; }
      cx += colW; cw -= colW;
    } else {
      const rowH = s / cw;
      let xx = cx;
      for (const a of r) { const ww = a / rowH; out.push({ x: xx, y: cy, w: ww, h: rowH }); xx += ww; }
      cy += rowH; ch -= rowH;
    }
  };
  while (vals.length) {
    if (!row.length) { row.push(vals.shift()); continue; }
    if (worst(row, side()) >= worst(row.concat(vals[0]), side())) row.push(vals.shift());
    else { flush(row); row = []; }
  }
  if (row.length) flush(row);
  return out;
}

function renderTreemap(treeNode) {
  const container = document.getElementById("tree-view-container");
  if (!container) return;
  const children = (treeNode.children || []).filter((c) => Number(c.allocated_bytes) > 0);
  if (!children.length) {
    container.innerHTML = `<div class="q-empty">폴더에 포함된 항목이 없거나 접근할 수 없습니다.</div>`;
    return;
  }
  container.innerHTML = "";
  const canvas = document.createElement("div");
  canvas.className = "treemap-canvas";
  container.appendChild(canvas);

  const W = Math.max(320, canvas.clientWidth || container.clientWidth || 900);
  const H = 470;
  canvas.style.height = `${H}px`;

  const total = children.reduce((a, c) => a + Number(c.allocated_bytes || 0), 0) || 1;
  const scale = (W * H) / total;
  const areas = children.map((c) => Math.max(1, Number(c.allocated_bytes || 0) * scale));
  const rects = squarify(areas, 0, 0, W, H);

  children.forEach((child, i) => {
    const r = rects[i];
    if (!r) return;
    const pct = Math.max(1, Math.round((Number(child.allocated_bytes || 0) / total) * 100));
    const gap = 2;
    const block = document.createElement(child.kind === "dir" ? "button" : "div");
    block.className = `tm-block kind-${escapeHtml(child.kind)}`;
    block.style.cssText =
      `left:${r.x + gap}px;top:${r.y + gap}px;` +
      `width:${Math.max(0, r.w - gap * 2)}px;height:${Math.max(0, r.h - gap * 2)}px;`;
    // 큰 블록일수록 진하게 (사이즈 히트맵)
    block.style.setProperty("--tm-weight", String(Math.min(1, pct / 40)));
    const roomy = r.w > 64 && r.h > 40;
    const icon = child.kind === "dir" ? "📁" : child.kind === "other" ? "📦" : "📄";
    block.title = `${child.name} · ${child.allocated_human} (${pct}%)`;
    if (roomy) {
      block.innerHTML =
        `<span class="tm-name">${icon} ${escapeHtml(child.name)}</span>` +
        `<span class="tm-size">${escapeHtml(child.allocated_human)} · ${pct}%</span>`;
    } else if (r.w > 26 && r.h > 16) {
      block.innerHTML = `<span class="tm-size tm-mini">${pct}%</span>`;
    }
    if (child.kind === "dir") {
      block.type = "button";
      block.addEventListener("click", () => loadSpaceTree(child.path));
    }
    canvas.appendChild(block);
  });
}

/* ---------- Large Files ---------- */
let lastLargeFiles = null;

async function loadLargeFiles() {
  const list = document.getElementById("lf-list");
  const summary = document.getElementById("lf-summary");
  if (!list) return;
  list.innerHTML = `<div class="q-empty is-loading">대용량 파일을 검색하는 중…</div>`;
  summary.textContent = "";
  try {
    const minMb = document.getElementById("lf-min-mb")?.value || "50";
    const data = await api(`/api/large-files?min_mb=${minMb}`);
    lastLargeFiles = data;
    renderLargeFiles(data);
  } catch (e) {
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

function renderLargeFiles(data) {
  const list = document.getElementById("lf-list");
  const summary = document.getElementById("lf-summary");
  if (!list) return;
  summary.textContent = `${data.count}개 파일 · 총 ${data.total_human} (최소 크기 ${data.min_human})`;
  if (!data.files.length) {
    list.innerHTML = `<div class="q-empty">${data.min_human} 이상의 대용량 파일을 찾지 못했습니다.</div>`;
    return;
  }
  list.innerHTML = "";
  for (const f of data.files) {
    const el = document.createElement("div");
    el.className = "lf-item has-signals";
    el.innerHTML = `
      <button type="button" class="lf-head" aria-expanded="false">
        <span class="lf-icon" aria-hidden="true">${f.kind_icon || "📁"}</span>
        <span class="entry-main">
          <span class="entry-path" title="${escapeHtml(f.path)}">${escapeHtml(f.name)}</span>
          <span class="entry-reason">${escapeHtml(f.path)}</span>
        </span>
        <span class="entry-size">${f.allocated_human}</span>
        <span class="lf-caret" aria-hidden="true">›</span>
      </button>
      <div class="signal-slot" hidden></div>`;
    wireSignalDisclosure(el, f.path);
    list.appendChild(el);
  }
}

/* ---------- 결정 도우미 (전용 탭) ---------- */
let lastDecide = null;

async function loadDecide() {
  const list = document.getElementById("decide-list");
  const summary = document.getElementById("decide-summary");
  const button = document.getElementById("decide-scan");
  const minMb = document.getElementById("decide-min-mb").value;
  list.innerHTML = `<div class="q-empty is-loading">파일을 모으는 중…</div>`;
  summary.textContent = "";
  button.disabled = true;
  try {
    const data = await api(`/api/large-files?min_mb=${minMb}`);
    lastDecide = data;
    renderDecide(data);
  } catch (e) {
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  } finally {
    button.disabled = false;
  }
}

function renderDecide(data) {
  const list = document.getElementById("decide-list");
  const summary = document.getElementById("decide-summary");
  summary.textContent =
    `${data.count}개 파일 · 총 ${data.total_human} · 항목을 펼쳐 단서를 확인하세요`;
  list.innerHTML = "";
  if (!data.files.length) {
    list.innerHTML = `<div class="q-empty">${data.min_human} 이상의 파일이 없습니다.</div>`;
    return;
  }
  for (const f of data.files) {
    const el = document.createElement("div");
    el.className = "lf-item has-signals";
    el.innerHTML = `
      <button type="button" class="lf-head" aria-expanded="false">
        <span class="lf-icon" aria-hidden="true">${f.kind_icon || "📁"}</span>
        <span class="entry-main">
          <span class="entry-path" title="${escapeHtml(f.path)}">${escapeHtml(f.name)}</span>
          <span class="entry-reason">${escapeHtml(f.path)}</span>
        </span>
        <span class="entry-size">${f.allocated_human}</span>
        <span class="lf-caret" aria-hidden="true">›</span>
      </button>
      <div class="signal-slot" hidden></div>`;
    wireSignalDisclosure(el, f.path);
    list.appendChild(el);
  }
}

/* ---------- 결정 단서 카드 (재사용) ---------- */
const signalCache = new Map();

function wireSignalDisclosure(container, path) {
  const head = container.querySelector(".lf-head, .cat-head, .signal-trigger");
  const slot = container.querySelector(".signal-slot");
  if (!head || !slot) return;
  head.addEventListener("click", async () => {
    const open = container.classList.toggle("signals-open");
    head.setAttribute("aria-expanded", String(open));
    slot.hidden = !open;
    if (!open || slot.dataset.loaded) return;
    slot.innerHTML = `<div class="signal-loading">단서를 모으는 중…</div>`;
    try {
      const data = signalCache.get(path)
        || await api(`/api/file-signals?path=${encodeURIComponent(path)}`);
      signalCache.set(path, data);
      slot.innerHTML = renderSignalCard(data);
      slot.dataset.loaded = "1";
    } catch (e) {
      slot.innerHTML = `<div class="signal-loading">${escapeHtml(e.message)}</div>`;
    }
  });
}

function signalHost(url) {
  try {
    if (url.startsWith("blob:")) url = url.slice(5);
    return new URL(url).hostname || url;
  } catch {
    return url;
  }
}

function renderSignalCard(s) {
  const rows = [];
  // 출처
  if (s.sources && s.sources.length) {
    const hosts = [...new Set(s.sources.map(signalHost))].join(", ");
    rows.push(sigRow("⬇︎", "받은 곳", escapeHtml(hosts), "이 위치에서 다시 받을 수 있습니다"));
  } else {
    rows.push(sigRow("⬇︎", "받은 곳", "기록 없음", "다운로드 출처 정보가 없습니다"));
  }
  // 마지막 사용
  if (s.has_open_record) {
    rows.push(sigRow("👁", "마지막으로 연 날짜", escapeHtml(s.last_used_label), ""));
  } else {
    rows.push(sigRow("👁", "마지막으로 연 날짜", "열람 기록 없음", "macOS에 이 파일의 열람 기록이 남아 있지 않습니다"));
  }
  // 추가/수정
  rows.push(sigRow("＋", "이 Mac에 추가", escapeHtml(s.added_label || "알 수 없음"),
    s.modified_label ? `수정: ${escapeHtml(s.modified_label)}` : ""));
  // 로컬 복사본
  if (s.local_copy_count > 0) {
    const list = s.local_copies.map((p) => `<div class="sig-path">${escapeHtml(p)}</div>`).join("");
    rows.push(sigRow("⧉", "다른 곳의 복사본", `${s.local_copy_count}개 (내용 동일)`, list));
  } else {
    rows.push(sigRow("⧉", "다른 곳의 복사본", "찾지 못함",
      "같은 이름의 복사본을 찾지 못했습니다 (이름이 다른 복사본은 확인하지 못합니다)"));
  }
  // 클라우드
  if (s.cloud_match_count > 0) {
    rows.push(sigRow("☁", "클라우드", `이름·크기가 같은 파일 ${s.cloud_match_count}개`,
      "내용까지 대조하지는 않았습니다"));
  }
  return `
    <div class="signal-card">
      <div class="signal-card-note">Spacekeeper는 판단하지 않습니다. 아래 사실만 보고 직접 결정하세요.</div>
      ${rows.join("")}
    </div>`;
}

function sigRow(icon, label, value, detail) {
  return `
    <div class="sig-row">
      <span class="sig-icon" aria-hidden="true">${icon}</span>
      <span class="sig-label">${label}</span>
      <span class="sig-value">${value}</span>
      ${detail ? `<span class="sig-detail">${detail}</span>` : ""}
    </div>`;
}

/* ---------- Browser & Mail Caches ---------- */
let lastBrowserCaches = null;

async function loadBrowserCaches() {
  const list = document.getElementById("bc-list");
  const summary = document.getElementById("bc-summary");
  if (!list) return;
  list.innerHTML = `<div class="q-empty is-loading">브라우저 및 메일 캐시를 분석하는 중…</div>`;
  summary.textContent = "";
  try {
    const data = await api("/api/browser-caches");
    lastBrowserCaches = data;
    renderBrowserCaches(data);
  } catch (e) {
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

function renderBrowserCaches(data) {
  const list = document.getElementById("bc-list");
  const summary = document.getElementById("bc-summary");
  if (!list) return;
  const allItems = [...(data.browsers || []), ...(data.mail || [])];
  summary.textContent = `${allItems.length}개 항목 · 총 ${data.total_human || '0 B'} 정리 가능`;
  if (!allItems.length) {
    list.innerHTML = `<div class="q-empty">정리할 브라우저 또는 메일 캐시가 없습니다.</div>`;
    return;
  }
  list.innerHTML = "";
  for (const item of allItems) {
    const el = document.createElement("div");
    el.className = "bc-item";
    const icon = item.browser === "Safari" ? "🌐" : item.browser === "Google Chrome" ? "🌐" : item.browser === "Mail" ? "✉️" : "🌐";
    el.innerHTML = `
      <span class="bc-icon" aria-hidden="true">${icon}</span>
      <span class="entry-main">
        <span class="entry-path" title="${escapeHtml(item.path)}">${escapeHtml(item.browser || item.category)} - ${escapeHtml(item.category)}</span>
        <span class="entry-reason">${escapeHtml(item.path)}</span>
      </span>
      <span class="entry-size">${item.allocated_human}</span>`;
    list.appendChild(el);
  }
}

/* ---------- Automated Schedule ---------- */
async function loadSchedule() {
  try {
    const data = await api("/api/schedule");
    document.getElementById("sched-enabled").checked = !!data.enabled;
    document.getElementById("sched-interval").value = String(data.interval_hours || 168);
    document.getElementById("sched-auto-clean").checked = !!data.auto_quarantine_low_risk;
    document.getElementById("sched-notify").checked = !!data.notify;
    const status = document.getElementById("sched-status");
    if (status) {
      status.textContent = data.enabled
        ? data.agent_installed
          ? `자동 정리가 켜져 있어요 · ${data.interval_hours}시간마다 실행됩니다.`
          : "설정은 켜져 있지만 백그라운드 실행이 등록되지 않았어요. 다시 저장해주세요."
        : "자동 정리가 꺼져 있어요.";
    }
  } catch (_) {}
}

async function saveSchedule() {
  const btn = document.getElementById("save-schedule-btn");
  if (btn) btn.disabled = true;
  try {
    const payload = {
      enabled: document.getElementById("sched-enabled").checked,
      interval_hours: parseInt(document.getElementById("sched-interval").value, 10),
      auto_quarantine_low_risk: document.getElementById("sched-auto-clean").checked,
      notify: document.getElementById("sched-notify").checked,
    };
    if (
      payload.enabled &&
      payload.auto_quarantine_low_risk &&
      !(await confirmDialog({
        title: "자동 격리를 켤까요?",
        body: "패키지 다운로드와 도구 캐시만 자동으로 격리합니다. 파일은 삭제되지 않으며 격리함에서 복원할 수 있어요.",
        confirmLabel: "자동 격리 켜기",
      }))
    ) return;
    const res = await api("/api/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    toast(res.enabled ? "자동 정리를 켰어요. 정해진 주기에 백그라운드에서 실행됩니다." : "자동 정리를 껐어요.", "ok");
    await loadSchedule();
  } catch (e) {
    toast(e.message, "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function switchView(view) {
  document.querySelectorAll(".nav-item").forEach((b) => {
    const active = b.dataset.view === view;
    b.classList.toggle("active", active);
    active ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current");
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById("view-" + view).classList.add("active");
  if (location.hash.slice(1) !== view) history.replaceState(null, "", "#" + view);
  if (view === "spacetree" && !currentTreePath) loadSpaceTree();
  if (view === "largefiles" && !lastLargeFiles) loadLargeFiles();
  if (view === "browsercache" && !lastBrowserCaches) loadBrowserCaches();
  if (view === "schedule") loadSchedule();
  if (view === "quarantine") loadQuarantine();
  if (view === "duplicates") renderDuplicates();
  if (view === "apps" && !lastApps) loadApps();
  if (view === "diagnostics") loadDiagnostics();
  if (view === "startup") loadStartup();
  if (view === "photos" && !lastPhotos) loadPhotos();
  if (view === "decide" && !lastDecide) loadDecide();
  if (view === "history") loadHistory();
}

/* ---------- 기록 (추이 + 활동 로그) ---------- */
async function loadHistory() {
  const trend = document.getElementById("history-trend");
  const log = document.getElementById("history-log");
  trend.innerHTML = `<div class="q-empty is-loading">기록을 불러오는 중…</div>`;
  log.innerHTML = "";
  try {
    const data = await api("/api/history");
    renderHistory(data.records || []);
  } catch (e) {
    trend.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

function historyTimeLabel(ts) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (sameDay) return isEn() ? `Today ${hm}` : `오늘 ${hm}`;
  const md = isEn()
    ? `${d.getMonth() + 1}/${d.getDate()}`
    : `${d.getMonth() + 1}월 ${d.getDate()}일`;
  return `${md} ${hm}`;
}

function renderTrendChart(scans) {
  if (scans.length < 2) {
    const only = scans.length === 1 ? fmtBytes(scans[0].reclaimable_bytes || 0) : "–";
    return `<div class="trend-empty">${
      isEn()
        ? "Run a couple of scans to see the trend."
        : "스캔을 몇 번 하면 추이가 보여요."
    }${scans.length === 1 ? ` (${TR("정리 후보 용량")}: ${only})` : ""}</div>`;
  }
  const pts = scans.slice(-20);
  const vals = pts.map((s) => s.reclaimable_bytes || 0);
  const max = Math.max(...vals, 1);
  const W = 640, H = 120, pad = 6;
  const step = (W - pad * 2) / (pts.length - 1);
  const y = (v) => H - pad - (v / max) * (H - pad * 2);
  const coords = pts.map((s, i) => [pad + i * step, y(s.reclaimable_bytes || 0)]);
  const line = coords.map(([x, yy], i) => `${i ? "L" : "M"}${x.toFixed(1)},${yy.toFixed(1)}`).join(" ");
  const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${H - pad} L${pad},${H - pad} Z`;
  const dots = coords
    .map(([x, yy]) => `<circle cx="${x.toFixed(1)}" cy="${yy.toFixed(1)}" r="2.5" />`)
    .join("");
  const first = fmtBytes(vals[0]);
  const last = fmtBytes(vals[vals.length - 1]);
  return `
    <div class="trend-head">
      <span class="trend-label">${TR("정리 후보 용량")} ${isEn() ? "trend" : "추이"}</span>
      <span class="trend-range">${first} → <b>${last}</b> · ${isEn() ? `${pts.length} scans` : `${pts.length}회 스캔`}</span>
    </div>
    <svg class="trend-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
      <path class="trend-area" d="${area}" />
      <path class="trend-line" d="${line}" />
      ${dots}
    </svg>`;
}

const HISTORY_META = {
  scan: { icon: "🔍", cls: "scan", label: "스캔" },
  quarantine: { icon: "📦", cls: "quarantine", label: "격리" },
  restore: { icon: "↩︎", cls: "restore", label: "복원" },
  empty: { icon: "🗑️", cls: "empty", label: "휴지통으로" },
};

function renderHistory(records) {
  const trend = document.getElementById("history-trend");
  const log = document.getElementById("history-log");
  if (!records.length) {
    trend.innerHTML = `<div class="q-empty">${
      isEn() ? "No activity yet. Run a scan to get started." : "아직 활동 기록이 없어요. 스캔부터 해보세요."
    }</div>`;
    log.innerHTML = "";
    return;
  }
  const scans = records.filter((r) => r.type === "scan");
  trend.innerHTML = `<div class="trend-card">${renderTrendChart(scans)}</div>`;

  log.innerHTML = "";
  for (const r of records.slice().reverse()) {
    const meta = HISTORY_META[r.type] || { icon: "•", cls: "scan", label: r.type };
    const row = document.createElement("div");
    row.className = `hist-row hist-${meta.cls}`;
    let detail;
    if (r.type === "scan") {
      detail = isEn()
        ? `${fmtBytes(r.reclaimable_bytes || 0)} reclaimable · ${(r.scanned_files || 0).toLocaleString()} files`
        : `정리 후보 ${fmtBytes(r.reclaimable_bytes || 0)} · 파일 ${(r.scanned_files || 0).toLocaleString()}개`;
    } else {
      detail = isEn()
        ? `${r.count || 0} items · ${fmtBytes(r.bytes || 0)}`
        : `${r.count || 0}개 · ${fmtBytes(r.bytes || 0)}`;
    }
    row.innerHTML = `
      <span class="hist-icon" aria-hidden="true">${meta.icon}</span>
      <span class="hist-main">
        <span class="hist-kind">${TR(meta.label)}</span>
        <span class="hist-detail">${detail}</span>
      </span>
      <span class="hist-time">${historyTimeLabel(r.ts || 0)}</span>`;
    log.appendChild(row);
  }
}

/* ---------- 비슷한 사진 ---------- */
const selPhotos = new Set();
let lastPhotos = null;

async function loadPhotos() {
  const list = document.getElementById("photos-list");
  const button = document.getElementById("photos-scan");
  list.innerHTML = `<div class="q-empty is-loading">사진을 비교하는 중… 장수가 많으면 시간이 걸립니다.</div>`;
  button.disabled = true;
  try {
    const data = await api("/api/similar-photos");
    lastPhotos = data;
    selPhotos.clear();
    renderPhotos(data);
  } catch (e) {
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  } finally {
    button.disabled = false;
  }
}

function renderPhotos(data) {
  const list = document.getElementById("photos-list");
  const cappedNote = data.capped
    ? ` · 상한 ${data.max_images.toLocaleString()}장까지만 검사`
    : "";
  document.getElementById("photos-summary").textContent =
    `${data.scanned_images.toLocaleString()}장 검사 · ${data.group_count}개 그룹 · `
    + `${data.reclaimable_human} 정리 가능${cappedNote}`;
  list.innerHTML = "";
  if (!data.group_count) {
    list.innerHTML = `<div class="q-empty">비슷한 사진을 찾지 못했습니다.</div>`;
    updatePhotosSelection();
    return;
  }
  for (const group of data.groups) {
    const card = document.createElement("div");
    card.className = "card dup-group";
    card.innerHTML = `
      <div class="dup-group-head"><b>${group.count}장</b> · ${group.reclaimable_human} 정리 가능</div>
      ${group.files.map((f) => `
        <div class="entry">
          <label class="entry-select">
            <input type="checkbox" data-id="${f.action_id}" ${f.keep ? "disabled" : ""} />
            <span class="entry-main">
              <span class="entry-path" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</span>
              ${f.keep ? `<span class="entry-reason dup-keep">기본 보관</span>` : ""}
            </span>
          </label>
          <span class="entry-size">${f.allocated_human}</span>
        </div>`).join("")}`;
    card.querySelectorAll("input[data-id]").forEach((cb) => {
      cb.addEventListener("change", () => {
        cb.checked ? selPhotos.add(cb.dataset.id) : selPhotos.delete(cb.dataset.id);
        updatePhotosSelection();
      });
    });
    list.appendChild(card);
  }
  updatePhotosSelection();
}

function updatePhotosSelection() {
  document.getElementById("photos-actions").hidden = selPhotos.size === 0;
  document.getElementById("photos-selection").textContent = `${selPhotos.size}개 선택`;
}

/* ---------- 시작 프로그램 ---------- */
const selStartup = new Set();

async function loadStartup() {
  const list = document.getElementById("startup-list");
  list.innerHTML = `<div class="q-empty is-loading">자동 실행 항목을 확인하는 중…</div>`;
  try {
    const data = await api("/api/startup-items");
    selStartup.clear();
    renderStartup(data);
  } catch (e) {
    list.innerHTML = `<div class="q-empty">${escapeHtml(e.message)}</div>`;
  }
}

function renderStartup(data) {
  const list = document.getElementById("startup-list");
  document.getElementById("startup-summary").textContent =
    `사용자 ${data.user_count}개 · 시스템 ${data.system_count}개`;
  list.innerHTML = "";
  if (!data.items.length) {
    list.innerHTML = `<div class="q-empty">자동 실행 항목이 없습니다.</div>`;
    updateStartupSelection();
    return;
  }
  for (const item of data.items) {
    const row = document.createElement("div");
    row.className = "q-item";
    row.innerHTML = `
      <label class="entry-select">
        <input type="checkbox" data-id="${item.action_id || ""}" ${item.manageable ? "" : "disabled"} />
      </label>
      <span class="entry-main">
        <span class="entry-path" title="${escapeHtml(item.path)}">${escapeHtml(item.label)}</span>
        <span class="entry-reason">${escapeHtml(item.program || item.path)}</span>
      </span>
      <span class="badge ${item.manageable ? "low" : "medium"}">${item.manageable ? "사용자" : "시스템 · 잠김"}</span>`;
    const cb = row.querySelector("input[data-id]");
    if (item.manageable) {
      cb.addEventListener("change", () => {
        cb.checked ? selStartup.add(cb.dataset.id) : selStartup.delete(cb.dataset.id);
        updateStartupSelection();
      });
    }
    list.appendChild(row);
  }
  updateStartupSelection();
}

function updateStartupSelection() {
  document.getElementById("startup-actions").hidden = selStartup.size === 0;
  document.getElementById("startup-selection").textContent = `${selStartup.size}개 선택`;
}

/* ---------- 첫 실행 온보딩 ---------- */
const ONBOARD_KEY = "sk_onboarded";
let obStep = 1;

function showOnboardingStep(step) {
  const root = document.getElementById("onboarding");
  root.querySelectorAll(".ob-step").forEach((el) => {
    el.hidden = Number(el.dataset.step) !== step;
  });
  root.querySelectorAll(".ob-dot").forEach((dot, index) => {
    dot.classList.toggle("is-on", index === step - 1);
  });
  const next = document.getElementById("ob-next");
  next.textContent = step === 3 ? t("시작하기") : t("다음");
}

function closeOnboarding() {
  localStorage.setItem(ONBOARD_KEY, "1");
  document.getElementById("onboarding").hidden = true;
}

function initOnboarding() {
  const root = document.getElementById("onboarding");
  if (!root) return;
  document.getElementById("ob-skip").addEventListener("click", closeOnboarding);
  document.getElementById("ob-next").addEventListener("click", () => {
    if (obStep >= 3) {
      closeOnboarding();
      return;
    }
    obStep += 1;
    showOnboardingStep(obStep);
  });
  document.getElementById("ob-open-settings").addEventListener("click", (event) =>
    openSystemSettings(event.currentTarget),
  );
  if (!localStorage.getItem(ONBOARD_KEY)) {
    root.hidden = false;
    showOnboardingStep(1);
  }
}

function initLangSwitch() {
  const current = window.SKI18N ? window.SKI18N.currentLang() : "ko";
  document.querySelectorAll(".lang-btn").forEach((button) => {
    button.classList.toggle("is-on", button.dataset.lang === current);
    button.addEventListener("click", () => {
      if (button.dataset.lang === current) return;
      window.SKI18N.setLang(button.dataset.lang);
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initLangSwitch();
  initOnboarding();
  document.getElementById("decide-scan").addEventListener("click", loadDecide);
  document.getElementById("photos-scan").addEventListener("click", loadPhotos);
  document.getElementById("startup-scan").addEventListener("click", loadStartup);
  document.getElementById("photos-reclaim").addEventListener("click", async (e) => {
    const ids = [...selPhotos];
    const out = await reclaimIds(ids, e.currentTarget, "선택 항목 격리", bytesForIds(ids));
    if (out) await loadPhotos();
  });
  document.getElementById("startup-reclaim").addEventListener("click", async (e) => {
    const ids = [...selStartup];
    const out = await reclaimIds(ids, e.currentTarget, "선택 항목 끄기", 0);
    if (out) await loadStartup();
  });
  startSystemMonitor();
  document.getElementById("preset").addEventListener("change", (e) => {
    document.getElementById("path-input").disabled = e.currentTarget.value !== "custom";
    updateScanCta();
  });
  document.getElementById("path-input").addEventListener("input", updateScanCta);
  document.getElementById("path-input").disabled = true;
  updateScanCta();
  document.getElementById("scan-btn").addEventListener("click", runScan);
  document.getElementById("scan-btn-2").addEventListener("click", runScan);
  document.getElementById("fav-add")?.addEventListener("click", addCurrentFavorite);
  loadFavorites();
  document.getElementById("cancel-scan").addEventListener("click", cancelScan);
  document.getElementById("result-search").addEventListener("input", renderFilteredResults);
  document.getElementById("risk-filter").addEventListener("change", renderFilteredResults);
  document.getElementById("result-sort").addEventListener("change", renderFilteredResults);
  document.getElementById("select-low-risk").addEventListener("click", selectLowRisk);
  document.getElementById("smart-clean-btn")?.addEventListener("click", smartClean);

  document.getElementById("tree-load-btn")?.addEventListener("click", () => {
    const p = document.getElementById("tree-path-input").value.trim();
    loadSpaceTree(p);
  });
  document.getElementById("lf-scan-btn")?.addEventListener("click", loadLargeFiles);
  document.getElementById("bc-scan-btn")?.addEventListener("click", loadBrowserCaches);
  document.getElementById("save-schedule-btn")?.addEventListener("click", saveSchedule);

  const shortcutModal = document.getElementById("shortcut-modal");
  document.getElementById("close-shortcut-modal")?.addEventListener("click", () => shortcutModal?.close());

  const navOrder = ["dashboard", "spacetree", "largefiles", "duplicates", "photos", "decide", "apps", "browsercache", "startup", "quarantine", "history", "schedule", "diagnostics"];
  const fromHash = location.hash.slice(1);
  if (navOrder.includes(fromHash)) switchView(fromHash);

  document.addEventListener("keydown", (e) => {
    const tag = document.activeElement?.tagName;
    if (e.key === "?" || (e.key === "/" && (e.metaKey || e.ctrlKey))) {
      if (tag !== "INPUT" && tag !== "SELECT") {
        e.preventDefault();
        shortcutModal?.showModal();
        return;
      }
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") {
      const activeView = document.querySelector(".view.active")?.id;
      const search = activeView === "view-quarantine"
        ? document.getElementById("q-search")
        : activeView === "view-dashboard" && !document.getElementById("results").hidden
          ? document.getElementById("result-search")
          : null;
      if (search && !search.closest("[hidden]")) {
        e.preventDefault();
        search.focus();
        search.select();
      }
    } else if ((e.metaKey || e.ctrlKey) && navOrder[Number(e.key) - 1]) {
      e.preventDefault();
      switchView(navOrder[Number(e.key) - 1]);
    } else if (e.key === "Escape") {
      if (shortcutModal?.open) {
        shortcutModal.close();
      } else if (tag === "INPUT" || tag === "SELECT") {
        document.activeElement.blur();
      }
    }
  });
  document.getElementById("export-scan").addEventListener("click", (e) => {
    closeToolMenu();
    exportLastScan(e);
  });
  wireToolMenu();
  document.getElementById("history-refresh")?.addEventListener("click", loadHistory);

  document.getElementById("reclaim-btn").addEventListener("click", async (e) => {
    const ids = [...selDash];
    const out = await reclaimIds(ids, e.currentTarget, "선택 항목 격리", bytesForIds(ids));
    if (out) { selDash.clear(); await runScan(); }
  });
  document.getElementById("clear-sel").addEventListener("click", () => {
    selDash.clear();
    renderFilteredResults();
  });

  document.getElementById("dup-reclaim").addEventListener("click", async (e) => {
    const ids = [...selDup];
    const out = await reclaimIds(ids, e.currentTarget, "선택 파일 격리", bytesForIds(ids));
    if (out) await runScan();
  });

  document.getElementById("apps-scan").addEventListener("click", loadApps);
  document.getElementById("apps-reclaim").addEventListener("click", async (e) => {
    const ids = [...selApps];
    const out = await reclaimIds(ids, e.currentTarget, "선택 항목 격리", bytesForIds(ids));
    if (out) await loadApps();
  });

  document.getElementById("refresh-q").addEventListener("click", loadQuarantine);
  document.getElementById("empty-q").addEventListener("click", emptyQuarantine);
  document.getElementById("q-search").addEventListener("input", renderQuarantine);
  document.getElementById("q-select-all").addEventListener("change", (event) => {
    for (const item of filteredQuarantineItems()) {
      event.currentTarget.checked ? selQ.add(item.action_id) : selQ.delete(item.action_id);
    }
    renderQuarantine();
  });
  document.getElementById("diagnostics-refresh").addEventListener("click", loadDiagnostics);
  document.getElementById("open-privacy-settings").addEventListener("click", openSystemSettings);
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.addEventListener("click", () => switchView(b.dataset.view)));
});
