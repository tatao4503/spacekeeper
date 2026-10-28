# Spacekeeper

> 📖 [사용설명서 (USER_GUIDE.html)](USER_GUIDE.html) — 화면별 안내·실행법·안전 요약


Spacekeeper는 맥북 저장공간을 **바로 삭제하지 않고 먼저 설명하는** 로컬 에이전트입니다.
파일명과 크기 같은 스캔 정보는 네트워크로 전송하지 않습니다. 선택한 항목은 먼저
복원 가능한 격리함으로 옮기며, 사용자가 다시 확인한 항목만 macOS 휴지통으로 보냅니다.

## 현재 가능한 것

- 큰 파일, 오래된 다운로드, 설치 파일과 압축 파일 찾기
- `node_modules`, `.next`, Xcode (`DerivedData`/시뮬레이터/DeviceSupport/아카이브), Docker VM/캐시, Homebrew/CocoaPods/pip/Go/Maven 패키지 캐시, Android AVD 등 재생성 가능한 후보 묶기
- 선택적으로 SHA-256 기반 완전 동일 파일 찾기
- 사람이 읽는 한국어 보고서 또는 JSON 보고서 출력
- 사용자 지정 경로 제외, Spacekeeper 격리함과 macOS 휴지통 자동 제외
- 심볼릭 링크를 따라가지 않고, 권한이 없는 폴더는 건너뛰기
- 희소 파일과 클라우드 자리표시자로 부풀지 않도록 실제 할당 블록 기준 계산
- 경로 기반 고정 ID가 붙은 위험도별 정리 미리보기
- 격리 전 후보와 격리된 항목을 Finder에서 바로 확인
- 선택 항목 격리, 원래 위치 복원, 확인한 항목만 macOS 휴지통으로 이동

> 후보는 자동 삭제 승인이 아닙니다. 특히 `검토 필요`와 `높은 주의` 항목은 내용을 직접 확인해야 합니다.

## 앱으로 실행

**네이티브 앱 (Tauri)** — 메뉴바에 상주하는 데스크탑 앱입니다.
파이썬 서버를 자동으로 켜고, 준비되면 대시보드를 자체 창에 띄웁니다. 창을 닫아도
메뉴바에 남아 있다가 트레이의 "종료"를 누르면 서버까지 함께 정리합니다.

```bash
cd desktop
npm install               # 최초 1회
npm run tauri dev         # 개발 실행
npm run build             # 검증된 배포용 .app / .dmg 빌드 (src-tauri/target/*/bundle/)
```

`tauri dev`와 `npm run build`는 PyInstaller 빌드를 먼저 실행해 Python 인터프리터와
Spacekeeper 서버를 앱에 포함합니다. 최종 사용자는 Python이나 별도 패키지를 설치할
필요가 없습니다. 배포 빌드는 전체 앱 번들의 확장 속성을 정리하고 ad-hoc 서명과 DMG
무결성까지 확인합니다. 최초 개발 빌드에서만 `desktop/.venv-sidecar`에 빌드 도구가 준비됩니다.

### 배포본

[최신 릴리스](https://github.com/tatao4503/spacekeeper/releases/latest)에서 DMG를 받을 수 있습니다.
**Apple Silicon(arm64) 전용**이며 앱과 독립 실행 런타임을 함께 포함합니다.

공증(notarization)을 받지 않은 ad-hoc 서명본이라, 처음 실행할 때 macOS가 차단하면
Finder에서 앱을 Control-클릭해 **열기**를 선택하거나 **시스템 설정 → 개인정보 보호 및
보안 → 확인 없이 열기**를 사용합니다. 공증 절차는 [docs/NOTARIZATION.md](docs/NOTARIZATION.md)에
정리돼 있습니다.

릴리스를 올릴 때는 DMG와 함께 SHA-256을 같이 올립니다.

```bash
shasum -a 256 src-tauri/target/release/bundle/dmg/Spacekeeper_<버전>_aarch64.dmg
```

> **전체 디스크 접근:** 앱이 `~/Desktop`·`~/Documents`·`~/Downloads` 등 보호
> 폴더를 스캔하려면 **시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한**에
> Spacekeeper를 추가해야 합니다. 없으면 해당 폴더는 건너뛰고(권한 제한으로 기록)
> 나머지만 스캔합니다.

## 웹 대시보드 (소스에서 실행)

디스크 도넛, 카테고리별 카드, 원클릭 정리를 갖춘 로컬 대시보드입니다.
127.0.0.1에만 바인딩하는 단일 사용자용이며, 정리 요청은 **직전에 표시한
항목**에 대해서만 처리합니다. 앱을 실행할 때마다 임시 포트와 256비트
인증 토큰을 새로 만들고, 로컬 Host·Origin·JSON 요청 형식을 모두 확인합니다.

```bash
python3 -m spacekeeper --serve            # http://127.0.0.1:8765
python3 -m spacekeeper --serve --port 9000
```

주요 화면은 다음과 같습니다. (앱 사이드바 순서)

- **공간 요약** — 디스크 사용량 도넛과 정리 가능한 용량, 카테고리별 후보. 분석 중 확인한 파일·용량·현재 경로를 보여주고 즉시 취소할 수 있습니다. 경로·이유 검색, 위험도 필터, Finder에서 보기, JSON 내보내기도 지원합니다. 항목은 자동 선택하지 않으며 이동 전에 확인을 요청합니다. 자주 보는 폴더는 ★로 즐겨찾기해 한 번에 다시 분석할 수 있습니다.
- **디스크 지도** — 어느 폴더가 공간을 쓰는지 크기에 비례한 블록(트리맵)으로 보여주고, 눌러서 안으로 들어갑니다.
- **시스템 데이터** — macOS가 '시스템 데이터'로 뭉뚱그린 덩어리를 실제 폴더로 분해합니다. `/Library/Developer`(시뮬레이터 런타임)나 `/private/var` 같은 **시스템 위치까지 재는 유일한 화면**이며, 읽기 전용입니다. 항목마다 앱에서 정리 가능 / 직접 정리(공식 명령 안내) / macOS가 관리로 등급을 나눠 보여주고, 이 화면에서 찾은 홈 밖 항목은 절대 격리하지 않습니다.
- **대용량 파일** — 정한 크기(10MB~1GB) 이상 파일을 종류별로 묶어 보여줍니다. 펼치면 출처·마지막 사용 같은 단서가 보입니다.
- **중복 파일** — `중복 검사`를 켜고 스캔하면 완전히 같은 파일을 그룹으로 묶어 보여줍니다. 그룹마다 하나는 기본 보관합니다.
- **비슷한 사진** — 크기·화질이 달라도 눈으로 같아 보이는 사진을 지각 해시(dHash)로 묶습니다. 그룹의 가장 큰 파일을 원본으로 둡니다.
- **결정 도우미** — 지울지 애매한 큰 파일에 대해 출처·마지막 사용·다른 곳의 사본 같은 **단서만** 중립적으로 보여줍니다. 판단은 사용자가 합니다.
- **앱과 관련 파일** — `/Applications`의 앱과, 그 앱이 `~/Library`에 남긴 지원·캐시·설정 파일을 묶어서 보여줍니다.
- **브라우저·메일** — Safari·Chrome·Firefox·Edge·Arc와 메일이 쌓아 둔 캐시만 찾습니다. 메일 본문이나 사이트 데이터는 건드리지 않습니다.
- **시작 프로그램** — 로그인할 때 자동으로 켜지는 항목. 끄면 설정 파일(plist)을 격리함으로 옮겨 실행을 멈추고, 복원하면 다시 켜집니다. `/Library`의 시스템 영역 항목은 읽기 전용으로 보여주기만 합니다.
- **격리함** — 보관 용량과 격리 시각을 확인하고, Finder에서 실제 보관 항목을 열어본 뒤 필요한 항목만 원래 자리로 **되돌리거나** macOS 휴지통으로 **비웁니다**.
- **기록** — 스캔·격리·복원·비우기 활동이 시간순으로 남고, 정리 가능 용량의 추이를 그래프로 보여줍니다. 전부 이 Mac 안에만 저장됩니다.
- **자동 정리** — 기본은 꺼져 있습니다. 직접 켜고 한 번 더 확인하면 백그라운드에서 다시 만들 수 있는 패키지 다운로드·도구 캐시만 정해진 주기로 격리합니다.
- **환경 진단** — 데스크탑·문서·다운로드 읽기, 격리함·휴지통 임시 쓰기, 런타임·Finder·로컬 서버 상태를 실제 실행 기준으로 점검합니다. 권한이 막힌 경우 macOS 시스템 설정을 바로 열 수 있습니다.

"격리"는 파일을 삭제하지 않고 `~/.spacekeeper/quarantine/`로 **이동**하며, manifest에
원래 위치를 기록해 언제든 복구할 수 있습니다. 같은 디스크 안으로 옮기므로 이 단계에서는
실제 여유 공간이 늘지 않습니다. 격리함을 macOS 휴지통으로 비운 뒤 Finder에서 휴지통을 비워야
저장공간이 확보됩니다. 이동 전에 원자적 journal을 기록하며, 이동과 manifest
기록 사이에 종료되어도 다음 실행에서 자동으로 회복합니다. 이동 대상은 홈 폴더와 `/Applications`
안으로 제한하고, 시스템·보호 경로(`/System`, `/Library`, `~/.ssh`, Keychains 등)는
절대 건드리지 않습니다.

## CLI 실행

CLI는 Python 3.11 이상만 필요하며 외부 패키지는 없습니다.

```bash
python3 -m spacekeeper
```

경로를 생략하면 `~/Downloads`만 스캔합니다. 다른 폴더는 명시적으로 지정합니다.

```bash
python3 -m spacekeeper ~/Desktop ~/Documents
python3 -m spacekeeper ~ --large-mb 1000 --old-days 365
python3 -m spacekeeper ~/Downloads --duplicates
python3 -m spacekeeper ~ --exclude ~/Movies --exclude ~/Documents/archive
python3 -m spacekeeper ~/Downloads --json > report.json
python3 -m spacekeeper ~ --include-cloud
python3 -m spacekeeper ~ --plan --risk low --top 20
python3 -m spacekeeper ~ --plan --risk all --json > cleanup-plan.json
```

`--duplicates`는 파일 내용을 읽어 해시를 계산하므로 큰 폴더에서는 오래 걸릴 수 있습니다. 그래도 파일을 수정하거나 외부로 전송하지는 않습니다.

홈 폴더 전체를 스캔할 때는 오프라인 파일 다운로드와 공급자 지연을 피하도록 iCloud Drive와 `~/Library/CloudStorage`를 기본 제외합니다. 경로를 직접 지정하거나 `--include-cloud`를 쓸 때만 포함합니다.

`--exclude PATH`는 지정한 파일이나 폴더 하위를 스캔하지 않습니다. 여러 번 사용할 수 있으며, `~/.spacekeeper`, `~/.Trash`, 외장 볼륨의 `.Trashes`는 안전을 위해 항상 자동 제외됩니다.

`--plan`은 기본적으로 `low` 위험도만 보여주며, 후보에 다음 스캔에서도 같은 고정 ID를 붙입니다. 이 단계는 선택·이동·삭제를 수행하지 않습니다.

## 개발 확인

```bash
python3 -m unittest discover -s tests -v
```

## 안전 원칙

1. 사용자 승인 없는 삭제 금지
2. 시스템·보호 폴더 오류는 우회하고 기록
3. 심볼릭 링크 미추적
4. 후보의 이유와 주의사항을 함께 표시
5. 정리는 삭제가 아니라 격리함으로 이동이며, 비우기도 macOS 휴지통으로 보냄
6. 백그라운드 자동 격리는 기본 꺼짐이며, 명시적으로 켜도 패키지 다운로드·도구 캐시만 대상으로 사용

## 알려진 한계

개인 도구를 공개한 것이라, 그 티가 나는 부분을 숨기지 않고 적어둡니다.

- **Apple Silicon 전용**, macOS 12 이상. Intel 빌드는 없습니다.
- **공증 안 됨.** 처음 실행할 때 Control-클릭 → 열기가 필요합니다. 해결 방법은
  [docs/NOTARIZATION.md](docs/NOTARIZATION.md)에 있습니다. 코드가 아니라 Apple Developer
  계정이 필요한 일입니다.
- **한 대의 Mac에서만 테스트됨.** 다른 기기나 macOS 버전에서 돌려본 사람이 아직 없습니다.
  30분 정도 시간이 된다면 [docs/TESTING_ON_ANOTHER_MAC.md](docs/TESTING_ON_ANOTHER_MAC.md)의
  점검표를 따라 결과를 알려주세요. "다 잘 됐다"는 보고도 버그 리포트만큼 값집니다.

## 라이선스

[MIT](LICENSE)
