// README 스크린샷. 가짜 홈으로 띄운 서버를 헤드리스 Chrome(CDP)으로 1280×820 @2x로 찍는다.
//
//   ./scripts/screenshots/demo-home.sh
//   HOME=/Users/Shared/demo python3 -m spacekeeper --serve --port 8791   # 다른 창에서
//   SKLANG=ko node scripts/screenshots/shots.mjs docs/screenshots/ko
//   ./scripts/screenshots/demo-home.sh     # 격리함 장면이 홈을 바꾸므로 언어마다 새로
//   SKLANG=en node scripts/screenshots/shots.mjs docs/screenshots/en
//
// 찍은 뒤에는 사용자 경로·이름이 없는지 눈으로 확인한다. 시스템 데이터 화면의 숫자는
// 찍는 Mac의 실제 시스템 폴더 크기다.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const OUT = process.argv[2];
if (!OUT) { console.error("사용법: node shots.mjs <출력 폴더>"); process.exit(1); }
const BASE = process.env.SK_URL || "http://127.0.0.1:8791/";
const LANG = process.env.SKLANG || "ko";
const SCHEME = process.env.SCHEME || "light";
mkdirSync(OUT, { recursive: true });

const PORT = 9333;
const profile = mkdtempSync(join(tmpdir(), "sk-shots-"));
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--hide-scrollbars", "about:blank",
], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const done = (code) => { try { chrome.kill(); } catch {} process.exit(code); };
setTimeout(() => { console.error("전체 시간 초과"); done(2); }, 300000);

let ws, id = 0;
const pending = new Map();
for (let i = 0; i < 50 && !ws; i++) {
  try {
    const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    const page = list.find((t) => t.type === "page");
    if (page) ws = new WebSocket(page.webSocketDebuggerUrl);
  } catch {}
  if (!ws) await sleep(200);
}
await new Promise((r) => ws.addEventListener("open", r));
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id;
  pending.set(i, (m) => (m.error ? rej(new Error(`${method}: ${m.error.message}`)) : res(m.result)));
  ws.send(JSON.stringify({ id: i, method, params }));
});
const evalJs = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true, timeout: 20000 });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || "eval error");
  return r.result.value;
};
const waitFor = async (expr, ms, label) => {
  const t = Date.now();
  while (Date.now() - t < ms) { if (await evalJs(expr)) return; await sleep(300); }
  throw new Error(`기다리다 시간 초과: ${label}`);
};
const shot = async (name) => {
  await sleep(900);
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, "base64"));
  console.log("찍음", name);
};

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 820, deviceScaleFactor: 2, mobile: false });
  await send("Emulation.setEmulatedMedia", { features: [
    { name: "prefers-color-scheme", value: SCHEME },
    { name: "prefers-reduced-motion", value: "reduce" },
  ] });
  await send("Page.navigate", { url: BASE });
  await waitFor("document.readyState === 'complete' && typeof ONBOARD_KEY !== 'undefined'", 20000, "첫 화면");
  await evalJs(`localStorage.setItem(ONBOARD_KEY, '1'); localStorage.setItem('sk_lang', '${LANG}'); location.reload(); true`);
  await sleep(1500);
  await waitFor("document.readyState === 'complete' && typeof switchView === 'function'", 20000, "새로고침");

  // 1) 공간 요약: 홈 전체 + 중복 찾기
  await evalJs(`(() => {
    const s = document.getElementById('preset'); s.value = 'home'; s.dispatchEvent(new Event('change'));
    const d = document.getElementById('opt-duplicates'); d.checked = true; d.dispatchEvent(new Event('change'));
    document.querySelector('#scan-btn, [data-action=scan], button#scan').click(); return true; })()`);
  await waitFor("lastScan && (lastScan.entries || []).length > 0", 120000, "홈 분석");
  await sleep(1500);
  await shot("dashboard");

  // 2) 시스템 데이터
  await evalJs("switchView('systemdata'); document.getElementById('sd-scan').click(); true");
  await sleep(1000);
  await waitFor("!document.getElementById('sd-scan').disabled && document.querySelectorAll('#sd-list > *').length > 1", 180000, "시스템 데이터");
  await sleep(1200);
  await shot("system-data");

  // 3) 격리함: 다시 만들 수 있는 캐시 몇 개를 격리한 뒤
  await evalJs(`(async () => {
    const ids = (lastScan.entries || [])
      .filter((e) => /node_modules|\\.next|Homebrew|pip|gradle/.test(e.path)).map((e) => e.action_id);
    await api('/api/reclaim', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action_ids: ids, confirmed: true }) });
    switchView('quarantine'); return ids.length; })()`);
  await sleep(2000);
  await shot("quarantine");
  done(0);
} catch (err) {
  console.error(String(err));
  done(1);
}
