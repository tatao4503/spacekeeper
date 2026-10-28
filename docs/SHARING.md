# 공유용 문구 모음

복사해서 그대로 쓰라고 만든 문서입니다. 상황별로 길이가 다릅니다.

---

## 1. 친구에게 (카톡/메시지) — 검증 부탁

> 맥 저장공간 정리하는 거 하나 만들었는데, 내 맥에서만 돌려봐서 다른 데서도 되는지 몰라.
> 혹시 30분만 봐줄 수 있어?
>
> 받는 곳: https://github.com/tatao4503/spacekeeper/releases/latest
> (`.dmg` 받아서 응용프로그램에 넣고, **처음엔 우클릭 → 열기**. 그냥 더블클릭하면 안 열려)
>
> 뭘 봐주면 되는지: https://github.com/tatao4503/spacekeeper/blob/main/docs/TESTING_ON_ANOTHER_MAC.md
>
> 아무것도 안 지우는 앱이라 그냥 화면만 봐줘도 돼. 잘 되면 "다 됐다" 한마디면 충분하고.
> 아 그리고 M1 이후 맥만 돼.

---

## 2. 짧은 소개 (한 줄)

> 지우지 않고 격리하는 macOS 저장공간 정리 도구. 왜 후보인지 설명하고, 언제든 되돌립니다.

**영어:**
> A macOS storage cleaner that never deletes — it quarantines, explains why, and lets you restore.

---

## 3. 커뮤니티 글 (개발자 대상)

> **Spacekeeper — 아무것도 지우지 않는 macOS 정리 도구**
>
> macOS 저장공간 설정이 '시스템 데이터'로 뭉뚱그린 100GB가 뭔지 알고 싶어서 만들었습니다.
>
> - **삭제 대신 격리** — `~/.spacekeeper/quarantine/`로 옮기고 원래 위치를 기록. 복원은 한 번의 클릭.
> - **항목마다 이유** — "Cargo가 다시 만들 수 있음" 같은 근거·주의·위험도가 붙습니다. "정크 12.4GB" 같은 불투명한 덩어리가 없습니다.
> - **시스템 데이터 해부** — macOS가 안 알려주는 그 덩어리를 실제 폴더로 분해합니다. `/Library`나 `/private/var` 같은 시스템 위치까지 재는 유일한 화면이고, 읽기 전용입니다. 시뮬레이터 런타임처럼 앱이 안전하게 못 지우는 건 **공식 명령을 보여주기만 하고 실행하지 않습니다.**
> - **정직한 숫자** — 논리 크기가 아니라 실제 할당 블록(`st_blocks`) 기준. APFS 복제 때문에 실제 확보량이 더 적을 수 있다는 것도 화면에서 먼저 밝힙니다.
> - **완전 로컬** — 네트워크·계정·텔레메트리 없음. 대시보드는 루프백에서만 받고 실행마다 새 토큰으로 인증합니다.
>
> 파이썬 표준 라이브러리 + Tauri. 테스트 159개.
>
> 한계도 적어둡니다: **Apple Silicon 전용**, **공증 안 됨**(첫 실행 우클릭→열기), **제 맥 한 대에서만 검증**.
> 마지막 항목 때문에 다른 환경 결과가 제일 반갑습니다.
>
> https://github.com/tatao4503/spacekeeper

---

## 4. 영어 커뮤니티 (Show HN / Reddit 등)

> **Spacekeeper — a macOS cleaner that never deletes anything**
>
> I built this because macOS System Settings kept telling me "System Data: 100+ GB"
> and gave me no way to look inside.
>
> - **Quarantine, not delete.** Cleaning moves files to `~/.spacekeeper/quarantine/`
>   and records where they came from. Restore is one click. Emptying goes to the
>   Trash, so even that is reversible.
> - **Every item explains itself** — a reason, a caution, a risk level. No opaque
>   "Junk: 12.4 GB" bucket.
> - **System Data breakdown** — the only screen that measures system locations like
>   `/Library/Developer` and `/private/var`, and it's strictly read-only. Things it can't remove safely (simulator runtimes,
>   `/private/var`) are *explained with the official command to copy* — it never
>   runs them. Quarantine can't undo a broken system, so it doesn't pretend to.
> - **Honest numbers** — allocated blocks, not logical size, and the UI says up
>   front that APFS clones may make the real gain smaller.
> - **Local only** — no network, no account, no telemetry. The dashboard binds to
>   loopback and authenticates with a fresh token per launch.
>
> Python stdlib + Tauri, 159 tests.
>
> Known limits, stated plainly: **Apple Silicon only**, **not notarized** (first
> launch needs right-click → Open), and **tested on exactly one Mac** — that last
> one is why reports from other machines would be the most useful thing anyone
> could send.
>
> https://github.com/tatao4503/spacekeeper

---

## 쓰지 말아야 할 표현

- "N GB를 확보해드립니다" — 확보량은 기기마다 다르고, 격리 단계에서는 공간이 늘지 않습니다.
- "안전하게 삭제" — 이 앱은 삭제하지 않습니다. 표현이 어긋납니다.
- "시스템 데이터를 정리해드립니다" — 홈 밖은 **설명만** 합니다. 정리는 사용자가 합니다.
- 검증되지 않은 호환성 주장 — 지금은 한 대에서만 확인됐습니다.
