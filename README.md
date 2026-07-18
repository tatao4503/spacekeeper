# Spacekeeper

Spacekeeper는 맥북 저장공간을 **삭제하지 않고 먼저 설명하는** 로컬 에이전트입니다.
파일명과 크기 같은 스캔 정보는 네트워크로 전송하지 않으며, 현재 버전에는 삭제 기능이 없습니다.

## 현재 가능한 것

- 큰 파일, 오래된 다운로드, 설치 파일과 압축 파일 찾기
- `node_modules`, `.next`, Xcode `DerivedData`, 일반 앱 캐시 등 재생성 가능한 후보 묶기
- 선택적으로 SHA-256 기반 완전 동일 파일 찾기
- 사람이 읽는 한국어 보고서 또는 JSON 보고서 출력
- 심볼릭 링크를 따라가지 않고, 권한이 없는 폴더는 건너뛰기
- 희소 파일과 클라우드 자리표시자로 부풀지 않도록 실제 할당 블록 기준 계산
- 경로 기반 고정 ID가 붙은 위험도별 정리 미리보기

> 후보는 자동 삭제 승인이 아닙니다. 특히 `검토 필요`와 `높은 주의` 항목은 내용을 직접 확인해야 합니다.

## 앱으로 실행

두 가지 방법이 있습니다.

**1) 네이티브 앱 (Tauri, 권장)** — 메뉴바에 상주하는 진짜 데스크탑 앱입니다.
파이썬 서버를 자동으로 켜고, 준비되면 대시보드를 자체 창에 띄웁니다. 창을 닫아도
메뉴바에 남아 있다가 트레이의 "종료"를 누르면 서버까지 함께 정리합니다.

```bash
cd desktop
npm install               # 최초 1회
./stage-runtime.sh        # 파이썬 런타임을 ~/.spacekeeper/runtime 로 복사
npm run tauri dev         # 개발 실행
npm run tauri build       # 배포용 .app / .dmg 빌드 (src-tauri/target/*/bundle/)
```

> **런타임 스테이징이 필요한 이유:** 저장소가 `~/Desktop`처럼 macOS가 보호하는
> 폴더에 있으면, 서명 없는 앱이 스폰한 파이썬이 시작할 때 그 경로를 훑다가
> 권한 프롬프트에 막힙니다. 그래서 파이썬 런타임은 보호되지 않는
> `~/.spacekeeper/runtime`에 두고 실행합니다. 파이썬 소스를 바꾸면
> `./stage-runtime.sh`를 다시 실행하세요.

> **전체 디스크 접근:** 앱이 `~/Desktop`·`~/Documents`·`~/Downloads` 등 보호
> 폴더를 스캔하려면 **시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한**에
> Spacekeeper를 추가해야 합니다. 없으면 해당 폴더는 건너뛰고(권한 제한으로 기록)
> 나머지만 스캔합니다.

**2) 런처 앱** — `Spacekeeper.app`을 더블클릭하면 서버를 켜고 대시보드를
Chrome 앱 창(또는 기본 브라우저)으로 엽니다. 빌드가 필요 없습니다.

## 웹 대시보드 (Cleaner One Pro 스타일)

디스크 도넛, 카테고리별 카드, 원클릭 정리를 갖춘 로컬 대시보드입니다.
127.0.0.1에만 바인딩하는 단일 사용자용이며, 정리 요청은 **직전에 표시한
항목**에 대해서만 처리합니다.

```bash
cd /Users/yuntaeung/Desktop/코딩/spacekeeper
python3 -m spacekeeper --serve            # http://127.0.0.1:8765
python3 -m spacekeeper --serve --port 9000
```

화면은 네 가지입니다.

- **대시보드** — 디스크 사용량 도넛과 정리 가능한 용량, 카테고리별 후보. 안전(재생성 가능) 항목만 기본 선택됩니다.
- **중복 파일** — `중복 검사`를 켜고 스캔하면 완전히 같은 파일을 그룹으로 묶어 보여줍니다. 그룹마다 하나는 기본 보관합니다.
- **응용 프로그램** — 앱과, 그 앱이 `~/Library`에 남긴 지원·캐시·설정 파일을 묶어서 보여줍니다.
- **격리함** — 이동한 항목을 원래 자리로 **되돌리거나** macOS 휴지통으로 **비웁니다**.

"정리"는 파일을 삭제하지 않고 `~/.spacekeeper/quarantine/`로 **이동**하며, manifest에
원래 위치를 기록해 언제든 복구할 수 있습니다. 이동 대상은 홈 폴더와 `/Applications`
안으로 제한하고, 시스템·보호 경로(`/System`, `/Library`, `~/.ssh`, Keychains 등)는
절대 건드리지 않습니다.

## CLI 실행

Python 3.11 이상만 필요하며 외부 패키지는 없습니다.

```bash
cd /Users/yuntaeung/Desktop/코딩/spacekeeper
python3 -m spacekeeper
```

경로를 생략하면 `~/Downloads`만 스캔합니다. 다른 폴더는 명시적으로 지정합니다.

```bash
python3 -m spacekeeper ~/Desktop ~/Documents
python3 -m spacekeeper ~ --large-mb 1000 --old-days 365
python3 -m spacekeeper ~/Downloads --duplicates
python3 -m spacekeeper ~/Downloads --json > report.json
python3 -m spacekeeper ~ --include-cloud
python3 -m spacekeeper ~ --plan --risk low --top 20
python3 -m spacekeeper ~ --plan --risk all --json > cleanup-plan.json
```

`--duplicates`는 파일 내용을 읽어 해시를 계산하므로 큰 폴더에서는 오래 걸릴 수 있습니다. 그래도 파일을 수정하거나 외부로 전송하지는 않습니다.

홈 폴더 전체를 스캔할 때는 오프라인 파일 다운로드와 공급자 지연을 피하도록 iCloud Drive와 `~/Library/CloudStorage`를 기본 제외합니다. 경로를 직접 지정하거나 `--include-cloud`를 쓸 때만 포함합니다.

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
5. 향후 정리 기능도 먼저 휴지통 또는 격리함을 사용
