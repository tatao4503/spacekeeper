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

1. https://appleid.apple.com → 로그인 → `앱 암호` → 새로 생성 (이름: `notarytool`)
2. 키체인에 저장 (이렇게 하면 비밀번호가 스크립트에 노출되지 않습니다):
   ```bash
   xcrun notarytool store-credentials "spacekeeper-notary" \
     --apple-id "본인_애플_아이디" \
     --team-id "팀ID" \
     --password "생성한_앱_암호"
   ```

### 4단계 — 빌드 설정 변경 (여기서부터는 대신 해줄 수 있음)

`desktop/src-tauri/tauri.conf.json` 의 서명 설정을 바꿉니다.

```json
"macOS": {
  "signingIdentity": "Developer ID Application: 이름 (팀ID)",
  "minimumSystemVersion": "12.0",
  "entitlements": "entitlements.plist"
}
```

`hardenedRuntime`이 필요하고, 이 앱은 자체 포함 파이썬 런타임(sidecar)을 실행하므로
다음 entitlement가 필요할 가능성이 높습니다.

```xml
<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
<key>com.apple.security.cs.disable-library-validation</key><true/>
```

> ⚠️ PyInstaller로 만든 sidecar는 공증에서 가장 자주 막히는 지점입니다.
> `.app` 안의 **모든** 실행 파일과 `.dylib`가 각각 서명돼야 합니다.
> 첫 시도에서 실패하는 게 정상이고, 아래 로그 확인이 핵심입니다.

### 5단계 — 서명·공증·스테이플 (대신 해줄 수 있음)

```bash
# 1) 빌드
cd desktop && npm run build

# 2) DMG 공증 제출 (5~15분 소요)
xcrun notarytool submit \
  src-tauri/target/release/bundle/dmg/Spacekeeper_0.2.0_aarch64.dmg \
  --keychain-profile "spacekeeper-notary" --wait

# 3) 실패하면 이유 확인 (여기가 제일 중요)
xcrun notarytool log <제출ID> --keychain-profile "spacekeeper-notary"

# 4) 성공하면 티켓을 DMG에 박아 넣기 (오프라인에서도 통과)
xcrun stapler staple src-tauri/target/release/bundle/dmg/Spacekeeper_0.2.0_aarch64.dmg

# 5) 최종 확인 — 받는 사람 입장에서 통과하는지
spctl -a -vvv -t install src-tauri/target/release/bundle/dmg/Spacekeeper_0.2.0_aarch64.dmg
```

`spctl` 결과가 `accepted` + `source=Notarized Developer ID` 면 끝입니다.

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
