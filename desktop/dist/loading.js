// 시작 화면. 서버가 늦거나 끝내 뜨지 않을 때 사용자가 알 수 있게 한다.
// 실패 신호는 네이티브 쪽(main.rs)이 보낸다. 이 파일보다 먼저 올 수도 있어서
// window.__skFailReason 에 남겨 두고, 이 파일이 읽히면 그걸 확인한다.
(() => {
  const hint = document.getElementById("hint");
  setTimeout(() => {
    if (!document.body.classList.contains("failed")) {
      hint.textContent = "평소보다 오래 걸리고 있어요. 조금만 더 기다려 주세요…";
    }
  }, 10000);
  window.__skStartupFailed = () => document.body.classList.add("failed");
  if (window.__skFailReason) window.__skStartupFailed();
})();
