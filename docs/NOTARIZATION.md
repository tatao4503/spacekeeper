# 공증(notarization) 준비

지금 Spacekeeper는 **직접 서명(ad-hoc)** 상태라, 받는 사람이 첫 실행에서
"확인되지 않은 개발자" 경고를 만나고 우클릭 → 열기를 해야 합니다.
공증을 받으면 그냥 더블클릭으로 열립니다.

**필요한 것: Apple Developer Program, 연 $99(약 13만원).**
이 비용 때문에 지금은 미뤄둔 상태이고, 그 판단은 합리적입니다 —
아직 이 앱을 받아 간 사람이 없으니까요. 관심이 생긴 뒤에 해도 늦지 않습니다.

---

## 언제 하면 되나

이 중 하나라도 해당되면 그때 하세요.

- 남에게 링크를 보내야 할 일이 생겼다
- "우클릭으로 여세요"를 설명하기 번거로워졌다
- 이슈나 별이 붙기 시작했다

그전까지는 README에 한계를 적어두는 것으로 충분합니다. (이미 적혀 있습니다.)

---

## 순서

### 1단계 — 계정 (사용자가 직접, ~30분 + 승인 대기)

1. https://developer.apple.com/programs/enroll/ 에서 등록
2. 개인(Individual)으로 등록하면 법인 서류가 필요 없습니다
3. 결제 후 승인까지 보통 24~48시간

> 이 단계는 결제와 본인 확인이라 대신 해줄 수 없습니다.

### 2단계 — 인증서 (사용자가 직접, ~10분)

1. Xcode → Settings → Accounts → Apple ID 추가
2. `Manage Certificates` → `+` → **Developer ID Application** 생성
3. 확인:
   ```bash
   security find-identity -v -p codesigning | grep "Developer ID Application"
   ```
   여기 나오는 `Developer ID Application: 이름 (팀ID)` 문자열이 다음 단계에 필요합니다.

### 3단계 — 앱 암호 (사용자가 직접, ~5분)

https://appleid.apple.com → 로그인 → `앱 암호` → 새로 생성 (이름: `notarytool`)

### 4단계 — 서명·공증·스테이플: `desktop/notarize.sh`

이 과정은 **이미 스크립트로 있습니다.** DMG에서 앱을 꺼내 Developer ID로 서명하고
(`--options runtime` = hardened runtime), DMG를 다시 만들어 공증을 받고, 티켓을
스테이플합니다.

스크립트는 네 개의 환경변수를 요구합니다. **파일에 적거나 커밋하지 말고** 실행하는
터미널에서만 설정합니다.

```bash
export APPLE_DEV_ID="Developer ID Application: 이름 (팀ID)"   # 2단계에서 확인한 문자열
export APPLE_TEAM_ID="팀ID"                                    # 10자리
export APPLE_ID="본인_애플_아이디"
export APPLE_APP_PASSWORD="3단계에서_만든_앱_암호"

cd desktop
npm run build        # 먼저 일반 DMG를 만든다
./notarize.sh        # 최신 DMG를 찾아 서명·공증·스테이플 (5~15분)
```

끝나면 받는 사람 입장에서 통과하는지 확인합니다.

```bash
spctl -a -vvv -t install src-tauri/target/release/bundle/dmg/Spacekeeper_<버전>_aarch64.dmg
```

`accepted` + `source=Notarized Developer ID` 면 끝입니다.

### 5단계 — 실패했을 때

첫 시도에서 실패하는 게 정상입니다. 이유는 공증 로그에 나옵니다.

```bash
xcrun notarytool history --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD"
xcrun notarytool log <제출ID> --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD"
```

> ⚠️ **가장 가능성 높은 원인: PyInstaller sidecar.**
> 이 앱은 자체 포함 파이썬 런타임을 실행하는데, 지금 `notarize.sh`는 서명할 때
> **entitlements를 넘기지 않습니다.** hardened runtime 아래에서 파이썬 런타임이
> 막히면 다음 entitlement가 필요할 가능성이 높습니다.
>
> ```xml
> <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
> <key>com.apple.security.cs.disable-library-validation</key><true/>
> ```
>
> 이걸 `desktop/entitlements.plist`로 만들고, `notarize.sh`의 `codesign` 줄에
> `--entitlements entitlements.plist`를 더합니다. `--deep` 서명이 sidecar 안의
> `.dylib`까지 빠짐없이 잡는지도 로그에서 확인합니다.

### 알아둘 것 — 스크립트가 DMG를 바꾸는 방식

`notarize.sh`는 서명한 앱만 넣어 **DMG를 새로 만들고, 원래 DMG를 덮어씁니다.**
그래서 지금 배포 DMG에 있는 `/Applications` 드래그 바로가기와 볼륨 아이콘이 빠집니다.
공증된 DMG에도 그게 필요하면, 덮어쓰기 전에 원본을 따로 보관하거나 스크립트의
`hdiutil create` 단계를 `finalize-macos-release.sh` 방식으로 바꿔야 합니다.

### 6단계 — 릴리스 교체

공증된 DMG로 릴리스 자산을 교체하고, README와 릴리스 노트에서
"우클릭 → 열기" 안내를 지웁니다. 그때는 그 문장이 더 이상 사실이 아니게 되니까요.

---

## 하고 나면 바뀌는 것

| | 지금 | 공증 후 |
|---|---|---|
| 첫 실행 | 우클릭 → 열기 (2단계) | 더블클릭 |
| 경고 문구 | "확인되지 않은 개발자" | 없음 |
| 신뢰 | 받는 사람이 판단 | Apple이 검사했음 |
| 비용 | 0원 | 연 $99 |

기능은 하나도 달라지지 않습니다. **배포 마찰만 사라집니다.**
