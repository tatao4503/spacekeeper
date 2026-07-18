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

## 실행

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
