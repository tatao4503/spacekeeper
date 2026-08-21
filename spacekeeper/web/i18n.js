"use strict";
/**
 * Spacekeeper 다국어 (한국어 원본 → 영어 치환).
 *
 * 한국어를 소스로 두고, 언어가 en 일 때만 DOM 텍스트를 사전으로 바꾼다.
 * 영어 문자열은 한국어 키에 다시 걸리지 않으므로 여러 번 실행해도 안전하며,
 * MutationObserver 로 동적으로 그려지는 목록·토스트까지 자동 반영한다.
 */

const SK_LANG_KEY = "sk_lang";

const EN = {
  // 사이드바 · 내비게이션
  "Mac 공간 관리자": "Mac storage manager",
  "공간 요약": "Overview",
  "중복 파일": "Duplicates",
  "앱과 관련 파일": "Apps & leftovers",
  "격리함": "Quarantine",
  "환경 진단": "Diagnostics",
  "바로 삭제하지 않습니다": "Nothing is deleted",
  "선택한 항목만 격리함에 보관합니다.": "Selected items are moved to Quarantine.",

  // 대시보드 헤더 · 스캔
  "내 Mac의 여유 공간": "Free space on this Mac",
  "정리 후보를 찾아 드립니다. 확인한 항목만 안전하게 격리하세요.":
    "We find cleanup candidates. You quarantine only what you approve.",
  "이 Mac에서만 분석": "Analyzed on this Mac only",
  // 시스템 데이터 해부
  "시스템 데이터": "System Data",
  "macOS가 '시스템 데이터'로 뭉뚱그린 덩어리가 실제로 어떤 폴더인지 분해합니다. 홈 폴더 밖까지 살펴보며, 여기서는 아무것도 옮기거나 지우지 않습니다.":
    "Breaks down the blob macOS lumps together as \"System Data\" into the actual folders behind it. It looks outside your home folder too, and nothing here is moved or deleted.",
  "시스템 데이터 분석": "Analyze system data",
  "시스템 데이터를 살펴보는 중… 홈 폴더 밖까지 훑기 때문에 시간이 걸립니다.":
    "Examining system data… this takes a while because it walks outside your home folder.",
  "시스템 데이터로 잡히는 용량": "Counted as system data",
  "홈 폴더 밖": "Outside home folder",
  "이 앱에서 정리 가능": "Cleanable in this app",
  "디스크 여유": "Disk free",
  "측정은 실제 할당 블록 기준입니다. macOS 저장공간 설정이 보여주는 '시스템 데이터' 숫자와는 분류 기준이 달라 정확히 일치하지 않을 수 있습니다.":
    "Sizes are measured from actual allocated blocks. macOS System Settings groups things differently, so its \"System Data\" figure may not match exactly.",
  "측정된 시스템 데이터 영역이 없습니다.": "No system data areas were measured.",
  "앱에서 정리 가능": "Cleanable here",
  "직접 정리": "Clean it yourself",
  "macOS가 관리": "Managed by macOS",
  "왜 쌓이나": "Why it grows",
  "명령 복사": "Copy command",
  "명령을 복사했습니다. 터미널에 붙여넣어 실행하세요.":
    "Command copied. Paste it into Terminal to run it.",
  "복사하지 못했습니다. 명령을 직접 선택해 복사하세요.":
    "Couldn't copy. Select the command and copy it manually.",
  "시스템 데이터를 분석하지 못했습니다": "Could not analyze system data",

  // 시스템 데이터 — 영역 이름
  "iOS 시뮬레이터 런타임": "iOS Simulator runtimes",
  "시뮬레이터 캐시": "Simulator caches",
  "시뮬레이터 기기 데이터": "Simulator device data",
  "Xcode 빌드 산출물 (DerivedData)": "Xcode build output (DerivedData)",
  "iOS 기기 디버깅 심볼": "iOS device debug symbols",
  "Xcode 아카이브": "Xcode archives",
  "앱이 저장한 사용자 데이터": "App-stored user data",
  "앱 샌드박스 컨테이너": "App sandbox containers",
  "앱 그룹 데이터": "App group data",
  "시스템 전역 앱 지원 파일": "System-wide app support files",
  "Command Line Tools": "Command Line Tools",
  "시스템 임시 파일": "System temporary files",
  "가상 메모리 (스왑)": "Virtual memory (swap)",
  "시스템 로그": "System logs",
  "iPhone·iPad 백업": "iPhone / iPad backups",

  // 시스템 데이터 — 설명
  "Xcode 시뮬레이터가 쓰는 iOS·watchOS 런타임 디스크 이미지입니다.":
    "Disk images of the iOS and watchOS runtimes the Xcode Simulator uses.",
  "Xcode를 설치하거나 새 iOS 버전으로 시뮬레이터를 돌릴 때마다 런타임이 하나씩 쌓입니다. 옛 버전도 지우기 전까지 그대로 남습니다.":
    "Each Xcode install or new iOS version you simulate adds another runtime, and older ones stay until you remove them.",
  "위 명령으로 설치된 런타임을 확인한 뒤, 더 안 쓰는 것만 `xcrun simctl runtime delete <식별자>`로 지웁니다. Xcode → Settings → Platforms에서 눌러서 지워도 됩니다.":
    "List the installed runtimes with the command above, then delete only the ones you no longer use with `xcrun simctl runtime delete <id>`. You can also remove them in Xcode → Settings → Platforms.",
  "시뮬레이터가 런타임을 풀어놓고 쓰는 캐시입니다.":
    "Cache the Simulator uses to unpack and run runtimes.",
  "런타임을 받거나 시뮬레이터를 실행할 때 만들어지고, 오래된 것이 남아 있곤 합니다.":
    "Created when runtimes are downloaded or simulators run; stale copies tend to linger.",
  "더 이상 쓸 수 없는 시뮬레이터 기기와 그 데이터를 정리합니다. 필요하면 다시 만들어집니다.":
    "Removes unavailable simulator devices and their data. They're recreated if needed.",
  "시뮬레이터 기기별로 설치된 앱과 그 안의 데이터입니다.":
    "Apps installed on each simulated device, plus their data.",
  "시뮬레이터에서 앱을 돌릴 때마다 기기 폴더가 생기고, 만든 기기를 지우기 전까지 남습니다.":
    "Running an app in the Simulator creates a device folder that stays until you delete the device.",
  "지금 쓰는 기기는 두고 못 쓰는 것만 지웁니다. 특정 기기를 비우려면 `xcrun simctl erase <기기ID>`.":
    "Keeps the devices you use and removes only unavailable ones. To wipe a specific device: `xcrun simctl erase <device-id>`.",
  "Xcode가 빌드하면서 만든 중간 산출물과 인덱스입니다.":
    "Intermediate build output and indexes Xcode created while building.",
  "프로젝트를 빌드할 때마다 쌓이고, Xcode가 스스로 지우지 않습니다.":
    "It accumulates with every build, and Xcode doesn't clear it on its own.",
  "다시 빌드하면 그대로 만들어집니다. 정리 후 첫 빌드만 오래 걸립니다.":
    "It's regenerated on the next build; only the first build after cleaning is slow.",
  "연결했던 iPhone·iPad의 디버깅 심볼 파일입니다.":
    "Debug symbol files for iPhones and iPads you've connected.",
  "새 iOS 버전 기기를 연결할 때마다 그 버전의 심볼을 통째로 받아 둡니다.":
    "Connecting a device on a new iOS version downloads that version's full symbol set.",
  "지금 개발 중인 기기의 iOS 버전 폴더는 남기고, 옛 버전만 골라 지우세요. 지워도 그 기기를 다시 연결하면 재생성되지만 시간이 걸립니다.":
    "Keep the iOS version you're currently developing against and remove only older ones. They're regenerated when you reconnect that device, but it takes time.",
  "앱을 배포용으로 빌드할 때 남은 .xcarchive 파일입니다.":
    ".xcarchive files left from distribution builds.",
  "Archive 빌드를 할 때마다 하나씩 쌓입니다.": "One is added with every Archive build.",
  "이미 출시한 버전의 아카이브에는 크래시 로그를 해석할 심볼이 들어 있습니다. 앱을 배포한 적이 있다면 지우기 전에 꼭 확인하세요.":
    "Archives of shipped versions hold the symbols needed to read crash logs. If you've released the app, check carefully before deleting.",
  "앱들이 각자 저장한 데이터입니다. 설정만 있는 앱도 있고, 대화 기록·모델·캐시를 통째로 넣어 두는 앱도 있습니다.":
    "Data each app stores for itself — some keep only settings, others put entire histories, models, and caches here.",
  "앱을 쓸수록 커집니다. 앱을 지워도 이 폴더는 남는 경우가 많습니다.":
    "It grows as you use apps, and often stays behind even after an app is deleted.",
  "위 명령으로 어느 앱이 큰지 확인하세요. 실행 중인 앱의 데이터를 지우면 그 앱의 기록이 사라질 수 있습니다. '앱과 관련 파일' 화면에서 앱별로 안전하게 볼 수 있습니다.":
    "Use the command above to see which app is large. Deleting data for a running app can wipe its history. The Apps & leftovers screen shows this per app more safely.",
  "샌드박스로 격리된 앱들이 자기 데이터를 넣어 두는 곳입니다.":
    "Where sandboxed apps keep their own data.",
  "App Store 앱과 샌드박스 앱이 쓸수록 커집니다. 앱을 지워도 남기도 합니다.":
    "Grows as App Store and sandboxed apps are used, and can remain after deletion.",
  "앱의 실제 사용자 데이터가 들어 있습니다. 폴더 이름이 앱 번들 ID라 무엇인지 확인한 뒤에만 손대세요.":
    "These hold real user data. Folder names are bundle IDs — identify one before touching it.",
  "여러 앱이 함께 쓰는 데이터(확장 프로그램, 위젯 등)입니다.":
    "Data shared between apps and their extensions or widgets.",
  "앱과 그 확장이 데이터를 주고받으며 쌓입니다.":
    "Builds up as an app and its extensions share data.",
  "컨테이너와 마찬가지로 실제 데이터입니다. 확인 없이 지우지 마세요.":
    "Like containers, this is real data. Don't delete it unchecked.",
  "앱들이 다시 만들 수 있는 데이터를 담아 두는 캐시입니다.":
    "Caches holding data apps can rebuild.",
  "앱을 쓰는 동안 계속 쌓이고, 앱이 스스로 비우지 않는 경우가 많습니다.":
    "It keeps accumulating while you use apps, and many apps never clear it.",
  "'공간 요약'에서 분석하면 이 안의 캐시가 항목별로 잡힙니다.":
    "Running an analysis in Overview surfaces these caches item by item.",
  "모든 사용자용으로 설치된 앱의 지원 파일입니다.":
    "Support files for apps installed for all users.",
  "앱이나 드라이버를 설치할 때 여기에 들어가고, 앱을 지워도 남는 경우가 있습니다.":
    "Installers for apps and drivers write here, and files can remain after removal.",
  "시스템 전역이라 관리자 권한이 필요합니다. 어떤 앱 것인지 확인되지 않으면 두세요. 앱을 제거할 땐 그 앱의 공식 제거 프로그램을 쓰는 게 안전합니다.":
    "It's system-wide, so it needs admin rights. Leave anything you can't attribute to an app. When removing an app, its official uninstaller is the safe route.",
  "git·clang 같은 개발자 명령줄 도구 모음입니다.":
    "The developer command-line tools such as git and clang.",
  "Xcode나 `xcode-select --install`로 설치됩니다.":
    "Installed by Xcode or `xcode-select --install`.",
  "개발에 계속 쓰이는 도구입니다. 지우면 git 같은 명령이 동작하지 않습니다. 그대로 두세요.":
    "These are in constant use for development. Removing them breaks commands like git. Leave them alone.",
  "앱과 시스템이 쓰는 임시 파일·캐시 영역입니다.":
    "Scratch space for temporary files and caches used by apps and the system.",
  "실행 중인 앱들이 계속 만들고, macOS가 시점을 봐서 정리합니다.":
    "Running apps create it constantly, and macOS clears it when appropriate.",
  "macOS가 관리합니다. 직접 지우면 실행 중인 앱이 오작동할 수 있습니다. 재시동하면 상당 부분 정리됩니다.":
    "macOS manages this. Deleting it by hand can break running apps. A restart clears much of it.",
  "메모리가 부족할 때 디스크로 밀어내는 스왑 파일입니다.":
    "Swap files macOS writes to disk when memory runs short.",
  "열어 둔 앱이 많고 메모리가 모자랄수록 커집니다.":
    "The more apps you keep open with limited memory, the larger it gets.",
  "macOS가 필요에 따라 자동으로 늘리고 줄입니다. 지우면 안 됩니다. 줄이고 싶으면 앱을 닫고 재시동하세요.":
    "macOS grows and shrinks this automatically. Don't delete it — close apps and restart if you want it smaller.",
  "macOS와 앱들이 남긴 진단 로그입니다.":
    "Diagnostic logs written by macOS and apps.",
  "문제를 추적할 수 있게 계속 기록되고, 오래된 것은 자동으로 회전됩니다.":
    "They're written continuously for troubleshooting, and old ones rotate out automatically.",
  "macOS가 알아서 오래된 로그를 지웁니다. 그대로 두어도 무한정 커지지 않습니다.":
    "macOS prunes old logs itself, so this won't grow without bound.",
  "Finder로 받은 iOS 기기 백업입니다.": "iOS device backups taken through Finder.",
  "기기를 연결해 백업할 때마다 통째로 저장되고, 옛 백업도 지우기 전까지 남습니다.":
    "Each backup stores the device in full, and older ones stay until removed.",
  "기기를 복구할 때 필요한 실제 백업입니다. 지우기 전에 다른 백업(iCloud 등)이 있는지 꼭 확인하세요. Finder → 기기 → 백업 관리에서 지우는 게 안전합니다.":
    "These are real backups you'd need to restore a device. Confirm another backup (iCloud, etc.) exists first. Deleting via Finder → device → Manage Backups is the safe route.",

  "분석할 위치": "Location to analyze",
  "이 위치를 즐겨찾기에 추가": "Save this location to favorites",
  "즐겨찾는 위치": "Favorite locations",
  "즐겨찾기에서 제거": "Remove from favorites",
  "즐겨찾기에 추가했습니다.": "Added to favorites.",
  "먼저 분석할 경로를 골라주세요.": "Choose a location to analyze first.",
  "다운로드 폴더": "Downloads",
  "홈 폴더 전체": "Entire home folder",
  "데스크탑": "Desktop",
  "경로 직접 입력": "Enter a path",
  "중복 파일도 찾기": "Also find duplicates",
  "파일 내용을 비교해 시간이 더 걸립니다.": "Compares file contents, so it takes longer.",
  "분석 시작": "Start analysis",
  "분석 범위 설정": "Analysis scope",
  "제외할 경로": "Paths to exclude",
  "쉼표로 구분합니다. 격리함과 휴지통은 자동으로 제외됩니다.":
    "Separate with commas. Quarantine and Trash are excluded automatically.",

  // 빈 상태
  "분석 준비 완료": "Ready to analyze",
  "되찾을 수 있는 공간을": "See the space you can",
  "한눈에 확인하세요.": "reclaim, at a glance.",
  "큰 파일 · 오래된 다운로드 · 다시 만들 수 있는 캐시를 한곳에 정리합니다. 자동으로 삭제하지 않으니 직접 확인하고 결정하세요.":
    "Large files, old downloads, and regenerable caches in one place. Nothing is deleted automatically — you decide.",
  "홈 폴더 분석하기": "Analyze home folder",
  "완전한 로컬 분석": "Fully local",
  "항목별 이유 안내": "Reason for every item",
  "격리 후 복원 가능": "Restorable anytime",

  // 진행
  "저장 공간을 분석하는 중…": "Analyzing storage…",
  "파일을 살펴보는 중": "Looking through files",
  "분석할 경로를 준비하는 중": "Preparing the path to analyze",
  "분석 중에는 파일이 변경되지 않습니다.": "No files are changed during analysis.",
  "분석 취소": "Cancel",
  "분석 준비 중…": "Preparing…",
  "분석 결과를 정리하는 중…": "Finishing up…",
  "파일 내용을 비교하는 중…": "Comparing file contents…",
  "분석을 안전하게 멈추는 중…": "Stopping safely…",

  // 결과 · 도구
  "남은 공간": "Free",
  "정리 후보 용량": "Reclaimable",
  "파일명, 경로, 추천 이유 검색": "Search name, path, or reason",
  "모든 위험도": "All risk levels",
  "낮은 위험": "Low risk",
  "확인 필요": "Review",
  "높은 주의": "Caution",
  "크기순": "By size",
  "위험도순": "By risk",
  "이름순": "By name",
  "빠른 정리": "Quick clean",
  "JSON으로 저장": "Export JSON",
  "선택한 항목 없음": "Nothing selected",
  "선택 해제": "Clear",
  "선택 항목 격리": "Quarantine selected",
  "선택 파일 격리": "Quarantine selected files",
  "이 그룹 모두 선택": "Select all in group",
  "Finder에서 보기": "Show in Finder",

  // 카테고리
  "프로젝트 의존성": "Project dependencies",
  "패키지 캐시": "Package caches",
  "빌드 캐시": "Build caches",
  "Rust 빌드 산출물": "Rust build artifacts",
  "Xcode 파생 데이터": "Xcode derived data",
  "앱 캐시": "App caches",
  "사용자 캐시": "User caches",
  "로컬 AI 모델": "Local AI models",
  "테스트 캐시": "Test caches",
  "도구 캐시": "Tool caches",
  "Python 캐시": "Python caches",
  "큰 파일": "Large files",
  "오래된 다운로드": "Old downloads",
  "설치·압축 파일": "Installers & archives",

  // 중복 · 앱
  "내용이 완전히 같은 파일을 묶어서 보여줍니다. 그룹마다 하나는 보관본으로 남겨 둡니다.":
    "Groups files with identical contents. One copy per group is kept by default.",
  "설치된 앱과 Library에 남은 지원·캐시·설정 파일을 함께 보여줍니다.":
    "Shows installed apps together with the support, cache, and preference files they leave in Library.",
  "다시 분석": "Rescan",
  "기본 보관": "Kept",

  // 격리함
  "원래 위치에서 옮겨 둔 항목입니다. 복원하거나, 확인한 항목만 macOS 휴지통으로 보내세요.":
    "Items moved from their original location. Restore them, or send approved ones to the macOS Trash.",
  "새로고침": "Refresh",
  "선택 항목 휴지통으로": "Move selected to Trash",
  "원래 경로 검색": "Search original path",
  "보이는 항목 전체 선택": "Select all shown",
  "격리함이 비어 있습니다": "Quarantine is empty",
  "되돌리기": "Restore",
  "복원": "Restore",

  // 진단
  "보호 폴더 읽기와 격리·복원 기능이 제대로 동작하는지 점검합니다.":
    "Checks that protected folders can be read and that quarantine and restore work.",
  "다시 점검": "Re-check",
  "현재 실행 환경": "Current environment",
  "권한과 앱 상태를 점검하는 중": "Checking permissions and app state",
  "임시 검사 파일은 즉시 정리합니다.": "Temporary probe files are removed immediately.",
  "보호 폴더가 차단되었나요?": "Protected folders blocked?",
  "시스템 설정 열기": "Open System Settings",
  "준비됨": "Ready",
  "조치 필요": "Action needed",
  "보호 폴더 접근": "Protected folder access",
  "안전한 이동 경로": "Safe move paths",
  "앱 실행 환경": "App runtime",
  "현재 실행 환경이 준비됐습니다.": "The current environment is ready.",
  "확인할 항목이 있습니다.": "Some items need your attention.",

  // 온보딩
  "안전 우선": "Safety first",
  "파일을 삭제하지 않습니다": "Nothing gets deleted",
  "정리하기로 고른 항목은 삭제 대신 격리함으로 옮겨집니다. 언제든 원래 자리로 되돌릴 수 있고, 휴지통으로 비우는 것도 직접 확인한 뒤에만 진행됩니다.":
    "Items you choose are moved to Quarantine instead of being deleted. You can restore them at any time, and emptying to Trash only happens after you confirm.",
  "권한 안내": "Permissions",
  "전체 디스크 접근 권한": "Full Disk Access",
  "데스크탑·문서·다운로드는 macOS가 보호하는 폴더입니다. 이 폴더까지 분석하려면 시스템 설정에서 Spacekeeper를 허용해 주세요. 허용하지 않아도 나머지 폴더는 분석할 수 있습니다.":
    "Desktop, Documents, and Downloads are protected by macOS. To analyze them, allow Spacekeeper in System Settings. Other folders work without it.",
  "시작하기": "Get started",
  "분석할 위치를 고르세요": "Choose what to analyze",
  "홈 폴더 전체를 한 번 분석하면 큰 파일, 오래된 다운로드, 다시 만들 수 있는 캐시가 한곳에 정리됩니다. 결과를 보고 직접 고르면 됩니다.":
    "Analyze your whole home folder once and large files, old downloads, and regenerable caches land in one place. You pick from there.",
  "건너뛰기": "Skip",
  "다음": "Next",

  // 토스트 · 메시지
  "원래 위치로 복원했습니다.": "Restored to the original location.",
  "분석 결과를 JSON 파일로 저장했습니다.": "Saved the analysis as a JSON file.",
  "Finder에서 항목 위치를 표시했습니다.": "Revealed the item in Finder.",
  "정리할 낮은 위험 항목이 없습니다.": "There are no low-risk items to clean.",
  "요청을 처리하지 못했습니다": "The request could not be completed",
  "분석을 완료하지 못했습니다.": "The analysis could not be completed.",
  "분석을 취소했습니다. 파일은 변경되지 않았습니다.":
    "Analysis canceled. No files were changed.",
  "내용이 완전히 같은 파일을 찾지 못했습니다.": "No identical files were found.",
  "현재 검색과 필터 조건에 맞는 항목이 없습니다.":
    "No items match the current search and filters.",

  // 내비게이션 그룹 · 항목 (보강)
  "개요": "Overview",
  "정리": "Clean up",
  "앱 · 시스템": "Apps & System",
  "보관 · 관리": "Storage & Care",
  "디스크 지도": "Disk map",
  "대용량 파일": "Large files",
  "비슷한 사진": "Similar photos",
  "결정 도우미": "Decision helper",
  "브라우저·메일": "Browsers & Mail",
  "시작 프로그램": "Login items",
  "자동 정리": "Auto cleanup",
  "바로 삭제하지 않아요": "Nothing is deleted",
  "여유": "Free",

  // 대시보드 · 빈 상태 · 진행 (현재 문구)
  "정리할 만한 파일을 찾아드려요. 직접 확인한 것만 격리됩니다.":
    "We surface files worth clearing. Only what you confirm gets quarantined.",
  "큰 파일, 오래된 다운로드, 다시 만들 수 있는 캐시를 한곳에 모아 드려요. 무엇도 자동으로 지우지 않으니 직접 보고 결정하면 됩니다.":
    "Large files, old downloads, and regenerable caches gathered in one place. Nothing is deleted automatically — you look and decide.",
  "파일을 살펴보는 중이에요.": "Looking through your files.",
  "분석할 경로를 준비하고 있어요.": "Preparing the path to analyze.",
  "분석은 파일을 변경하지 않아요.": "Analysis never changes your files.",
  "분석 경로를 확인하고 있어요.": "Checking the path to analyze.",
  "크기가 같은 파일만 안전하게 비교하고 있어요.":
    "Only files of the same size are being compared, safely.",
  "정리 후보와 주의도를 마지막으로 확인하고 있어요.":
    "Doing a final check of candidates and their risk.",
  "현재 파일 확인을 마치면 바로 중단합니다.":
    "Stops as soon as the current file check finishes.",

  // 결과 도구 · 접근성 라벨
  "낮은 위험 모두 선택": "Select all low-risk",
  "안전 항목 바로 정리": "Clean safe items now",
  "결과 필터 및 작업": "Filter and act on results",
  "결과 검색": "Search results",
  "위험도 필터": "Risk filter",
  "결과 정렬": "Sort results",
  "더 보기": "More",
  "재생성 가능한 낮은 위험 항목을 선택 목록에 추가":
    "Add regenerable low-risk items to the selection",
  "다시 만들 수 있는 낮은 위험 캐시를 한 번에 격리함으로 이동":
    "Move regenerable low-risk caches to Quarantine in one step",
  "선택한 정리 후보 작업": "Actions on selected candidates",
  "실시간 Mac 시스템 리소스 상태": "Live Mac system resource status",
  "저장 공간 분석 진행률": "Storage analysis progress",
  "Spacekeeper 분석 원칙": "Spacekeeper analysis principles",
  "예: ~/Documents/Archive": "e.g. ~/Documents/Archive",
  "예: ~/Movies, ~/Documents/archive": "e.g. ~/Movies, ~/Documents/archive",
  "예: ~/Downloads": "e.g. ~/Downloads",
  "분석할 폴더 경로": "Folder path to analyze",

  // 페이지 헤더 (현재 문구)
  "어떤 폴더가 공간을 많이 쓰는지 크기 블록으로 한눈에 보여줍니다.":
    "Shows which folders use the most space as sized blocks, at a glance.",
  "지도 분석": "Analyze map",
  "내용이 완전히 같은 파일을 묶어서 보여줍니다. 그룹마다 하나는 원본으로 남겨 둡니다.":
    "Groups files with identical contents. One original per group is kept.",
  "선택한 중복 파일 작업": "Actions on selected duplicates",
  "설치된 앱과 그 앱이 남긴 지원·캐시·설정 파일을 함께 보여줍니다.":
    "Shows installed apps together with the support, cache, and preference files they leave behind.",
  "선택한 앱 관련 파일 작업": "Actions on selected app files",
  "정한 크기 이상인 파일을 찾아 종류별로 보여줍니다.":
    "Finds files above a size you set and groups them by type.",
  "최소 크기": "Minimum size",
  "파일 검색": "Find files",
  "브라우저·메일 캐시": "Browser & mail cache",
  "Safari·Chrome·Firefox·Edge·Arc와 메일이 쌓아 둔 캐시를 찾습니다.":
    "Finds caches left by Safari, Chrome, Firefox, Edge, Arc, and Mail.",
  "캐시 분석": "Analyze cache",
  "크기나 화질이 달라도 눈으로 같아 보이는 사진을 묶어 줍니다. 그룹마다 가장 큰 파일은 원본으로 남겨 둡니다.":
    "Groups photos that look identical to the eye even at different sizes or quality. The largest file in each group is kept as the original.",
  "사진 분석": "Analyze photos",
  "로그인할 때 자동으로 켜지는 항목입니다. 끄면 설정 파일을 격리함으로 옮겨 실행을 멈추고, 복원하면 다시 켜집니다.":
    "Items that launch automatically at login. Turning one off moves its config to Quarantine to stop it; restoring turns it back on.",
  "다시 확인": "Recheck",
  "선택 항목 끄기": "Turn off selected",
  "지울지 말지 애매한 큰 파일을 모았습니다. 항목을 펼치면 출처·마지막 사용·복사본 같은 단서가 보여요. 판단은 직접 하시면 됩니다.":
    "A collection of large files that are hard to judge. Expand an item to see clues like source, last used, and copies. The decision is yours.",
  "파일 모으기": "Gather files",
  "원래 자리에서 잠시 옮겨 둔 항목입니다. 되돌리거나, 직접 확인한 것만 휴지통으로 보내세요.":
    "Items moved aside from their original location. Restore them, or send only what you confirm to the Trash.",
  "격리함 검색 및 선택": "Search and select in Quarantine",
  "격리함 경로 검색": "Search Quarantine paths",

  // 자동 정리 (스케줄)
  "기본은 알림만 제공하며, 직접 켜면 재생성 캐시만 격리합니다.":
    "Notifications are the default. If enabled, only rebuildable caches are quarantined.",
  "스케줄 저장": "Save schedule",
  "자동 스캔·정리 켜기": "Enable auto scan & cleanup",
  "정해진 주기에 맞춰 백그라운드에서 조용히 실행됩니다.":
    "Runs quietly in the background at the set interval.",
  "실행 주기": "Interval",
  "매일 (24시간)": "Daily (24 hours)",
  "매주 (168시간)": "Weekly (168 hours)",
  "매월 (30일)": "Monthly (30 days)",
  "재생성 캐시 자동 격리": "Auto-quarantine rebuildable caches",
  "기본은 꺼짐이며, 패키지 다운로드·도구 캐시만 자동으로 격리합니다.":
    "Off by default. Only package-download and tool caches are quarantined automatically.",
  "자동 격리를 켤까요?": "Enable automatic quarantine?",
  "패키지 다운로드와 도구 캐시만 자동으로 격리합니다. 파일은 삭제되지 않으며 격리함에서 복원할 수 있어요.":
    "Only package-download and tool caches are quarantined automatically. Nothing is deleted, and you can restore items from Quarantine.",
  "자동 격리 켜기": "Enable auto-quarantine",
  "다시 만들 수 있는 시스템·개발자 캐시만 격리합니다.":
    "Quarantines only regenerable system and developer caches.",
  "완료 알림 받기": "Notify when done",
  "자동 정리가 끝나면 macOS 알림으로 알려 드립니다.":
    "Sends a macOS notification when auto cleanup finishes.",
  "자동 정리가 꺼져 있어요.": "Auto cleanup is off.",
  "자동 정리를 껐어요.": "Turned off auto cleanup.",
  "자동 정리를 켰어요. 정해진 주기에 백그라운드에서 실행됩니다.":
    "Turned on auto cleanup. It runs in the background at the set interval.",

  // 진단 (현재 문구)
  "보호 폴더 읽기와 격리·복원이 제대로 동작하는지 점검합니다.":
    "Checks that protected folders can be read and that quarantine and restore work.",
  "권한과 앱 상태를 점검하고 있어요.": "Checking permissions and app state.",
  "시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한":
    "System Settings → Privacy & Security → Full Disk Access",
  "에서 Spacekeeper를 허용한 뒤 앱을 다시 실행하세요.":
    ", allow Spacekeeper, then relaunch the app.",
  "※ 이 결과는 macOS의 전체 권한 목록을 추측하지 않고, 현재 프로세스에서 실제 읽기·임시 쓰기를 수행한 결과입니다.":
    "※ These results don't guess macOS's full permission list — they reflect actual reads and temporary writes by the current process.",
  "런타임·Finder·로컬 서버 상태": "Runtime, Finder, and local server status",
  "격리와 휴지통 이동에 필요한 쓰기 권한":
    "Write access needed to quarantine and move to Trash",
  "주요 폴더와 안전 기능을 사용할 수 있습니다.":
    "Key folders and safety features are available.",
  "권한 또는 환경 조치가 필요해요.": "Permissions or environment need attention.",
  "조치 필요 항목을 확인한 뒤 다시 점검해주세요.":
    "Review the items needing action, then re-check.",
  "현재 데스크톱 앱용 런타임을 점검한 결과입니다.":
    "Results from checking the current desktop-app runtime.",
  "현재 앱에 포함된 독립 실행 런타임을 점검한 결과입니다. 별도의 Python 설치가 필요하지 않습니다.":
    "Results from checking the standalone runtime bundled with the app. No separate Python install is required.",
  "개발 서버에서는 터미널·Python 권한이 반영될 수 있어 데스크톱 앱 결과와 다를 수 있습니다.":
    "On the dev server, terminal and Python permissions may apply, so results can differ from the desktop app.",
  "폴더 생성 여부나 실행 환경 안내를 확인해주세요.":
    "Check whether the folder was created and the runtime guidance.",
  "점검하는 중…": "Checking…",
  "시스템 설정을 열었습니다. 개인정보 보호 및 보안을 확인하세요.":
    "Opened System Settings. Check Privacy & Security.",

  // 키보드 단축키
  "키보드 단축키": "Keyboard shortcuts",
  "✕ 닫기": "✕ Close",
  "탭 즉시 이동 (공간 요약 ~ 환경 진단)": "Jump between tabs (Overview – Diagnostics)",
  "검색 및 필터 포커스": "Focus search and filters",
  "단축키 도움말 팝업 열기": "Open the shortcuts help",
  "입력 폼 탈출 및 팝업 닫기": "Exit inputs and close popups",

  // 카테고리 (보강)
  "Android 에뮬레이터": "Android emulators",
  "CocoaPods 캐시": "CocoaPods cache",
  "Docker 캐시/데이터": "Docker cache / data",
  "Go 빌드 캐시": "Go build cache",
  "Homebrew 캐시": "Homebrew cache",
  "Maven 라이브러리 캐시": "Maven library cache",
  "Xcode 시뮬레이터": "Xcode simulators",
  "Xcode 아카이브": "Xcode archives",
  "iOS/watchOS 기기 기호": "iOS/watchOS device symbols",
  "pip 캐시": "pip cache",
  "macOS가 관리하는 주요 사용자 폴더": "Key user folders managed by macOS",

  // 결정 도우미 · 신호 라벨
  "받은 곳": "Source",
  "마지막으로 연 날짜": "Last opened",
  "다른 곳의 복사본": "Copies elsewhere",
  "기록 없음": "No record",
  "열람 기록 없음": "No open history",
  "시각 정보 없음": "No timestamp",
  "찾지 못함": "Not found",
  "알 수 없음": "Unknown",
  "클라우드": "Cloud",
  "사용자": "User",
  "시스템 · 잠김": "System · locked",
  "선택한 경로": "Selected path",
  "홈 폴더": "Home folder",
  "macOS에 이 파일의 열람 기록이 남아 있지 않습니다":
    "macOS has no record of this file being opened",
  "같은 이름의 복사본을 찾지 못했습니다 (이름이 다른 복사본은 확인하지 못합니다)":
    "No same-name copy found (copies with different names aren't checked)",
  "내용까지 대조하지는 않았습니다": "Contents were not compared",
  "다운로드 출처 정보가 없습니다": "No download-source information",
  "이 위치에서 다시 받을 수 있습니다": "Can be downloaded again from here",

  // 토스트 · 진행 · 안내 (보강)
  "선택 항목 끄기 ": "Turn off selected ",
  "안전하게 격리하는 중…": "Quarantining safely…",
  "휴지통으로 보내는 중…": "Moving to Trash…",
  "여는 중…": "Opening…",
  "취소 요청 중…": "Requesting cancel…",
  "격리할 낮은 위험 항목이 없습니다.": "There are no low-risk items to quarantine.",
  "선택할 낮은 위험 항목이 없습니다.": "There are no low-risk items to select.",
  "낮은 위험 항목이 이미 모두 선택되어 있습니다.": "All low-risk items are already selected.",
  "‘공간 요약’에서 ‘중복 파일도 찾기’를 켜고 다시 분석하세요.":
    "Turn on ‘Also find duplicates’ in Overview and analyze again.",
  "Finder에서 휴지통을 비우기 전까지는 복구할 수 있으며, 비운 뒤에야 실제 여유 공간이 늘어납니다.":
    "You can recover items until you empty the Trash in Finder; only after emptying does real free space increase.",
  "원래 위치에서 Spacekeeper 격리함으로 옮겨집니다. ":
    "Will be moved from its original location to Spacekeeper's Quarantine. ",
  "이 단계에서는 저장 공간이 늘지 않으며 언제든 복원할 수 있습니다.":
    "This step doesn't increase free space, and you can restore at any time.",
  "이 Mac에 추가": "Add to this Mac",

  // 빈 상태 · 로딩 (고정 문구)
  "보호 폴더와 안전 기능을 하나씩 확인하고 있어요.":
    "Checking protected folders and safety features one by one.",
  "검색한 경로와 일치하는 항목이 없습니다.": "No items match the searched path.",
  "대용량 파일을 검색하는 중…": "Searching for large files…",
  "먼저 ‘공간 요약’에서 분석을 시작하세요.": "Start an analysis in Overview first.",
  "불러오는 중…": "Loading…",
  "브라우저 및 메일 캐시를 분석하는 중…": "Analyzing browser and mail caches…",
  "비슷한 사진을 찾지 못했습니다.": "No similar photos were found.",
  "사진을 비교하는 중… 장수가 많으면 시간이 걸립니다.":
    "Comparing photos… this can take a while with many images.",
  "설치된 앱과 관련 파일을 분석하는 중…": "Analyzing installed apps and their files…",
  "아직 격리한 항목이 없습니다.": "Nothing has been quarantined yet.",
  "‘공간 요약’에서 정리할 항목을 선택해보세요.":
    "Pick items to clean up in Overview.",
  "자동 실행 항목을 확인하는 중…": "Checking startup items…",
  "자동 실행 항목이 없습니다.": "No startup items found.",
  "정리할 브라우저 또는 메일 캐시가 없습니다.":
    "No browser or mail caches to clean.",
  "파일을 모으는 중…": "Gathering files…",
  "폴더 구조와 용량 비중을 분석하는 중…":
    "Analyzing folder structure and size distribution…",
  "폴더에 포함된 항목이 없거나 접근할 수 없습니다.":
    "The folder is empty or can't be accessed.",
  "표시할 앱이 없습니다.": "No apps to show.",
  "단서를 모으는 중…": "Gathering clues…",
  "기본 보관 · 이 화면에서는 선택할 수 없어요":
    "Kept by default · can't be selected here",
  "내용이 같은 중복본": "Duplicate with identical contents",

  // 진단 세부 (고정 문구)
  "현재 실행 중인 Spacekeeper에서 읽을 수 있습니다.":
    "Readable by the running Spacekeeper.",
  "문서": "Documents",
  "다운로드": "Downloads",
  "Spacekeeper 격리함": "Spacekeeper Quarantine",
  "임시 파일을 쓰고 지우는 검사를 안전하게 마쳤습니다.":
    "The write-and-delete probe completed safely.",
  "macOS 휴지통 연결": "macOS Trash connection",
  "앱 런타임": "App runtime",
  "Finder 연동": "Finder integration",
  "Finder에서 항목 위치를 열 수 있습니다.": "Items can be revealed in Finder.",
  "로컬 전용 서버": "Local-only server",
  "127.0.0.1에서만 대시보드 요청을 받습니다.":
    "Only accepts dashboard requests from 127.0.0.1.",

  // 브라우저·메일 캐시 라벨
  "Service Worker 캐시": "Service Worker cache",
  "메일 캐시": "Mail cache",
  "브라우저 캐시": "Browser cache",

  // 카테고리 설명(이유)
  "Android Studio가 생성한 가상 기기(AVD) 이미지 데이터입니다.":
    "Virtual device (AVD) image data created by Android Studio.",
  "Cargo가 다시 생성할 수 있는 Rust 빌드 결과와 증분 캐시입니다.":
    "Rust build output and incremental cache that Cargo can regenerate.",
  "CocoaPods가 다운로드 및 인덱싱한 팟캐시입니다.":
    "Pod cache CocoaPods downloaded and indexed.",
  "Docker CLI 및 런타임 캐시 데이터입니다.":
    "Docker CLI and runtime cache data.",
  "Docker 데스크탑이 보관 중인 VM 디스크 이미지, 컨테이너 및 빌드 캐시입니다.":
    "VM disk images, containers, and build cache held by Docker Desktop.",
  "Go 컴파일러가 다시 생성할 수 있는 빌드 캐시입니다.":
    "Build cache the Go compiler can regenerate.",
  "Google Updater가 업데이트 패키지를 위해 보관한 캐시입니다.":
    "Cache Google Updater keeps for update packages.",
  "Gradle이 다시 생성하거나 내려받을 수 있는 캐시입니다.":
    "Cache Gradle can regenerate or re-download.",
  "Homebrew 패키지 설치 및 업데이트 시 다운로드된 병목 캐시 파일입니다.":
    "Bottle cache files downloaded when installing or updating Homebrew packages.",
  "Maven/Gradle이 다운로드한 Java 라이브러리 의존성 캐시입니다.":
    "Java library dependency cache downloaded by Maven/Gradle.",
  "Next.js가 다시 생성할 수 있는 빌드 결과와 캐시입니다.":
    "Build output and cache that Next.js can regenerate.",
  "Ollama가 로컬 실행을 위해 내려받은 AI 모델 데이터입니다.":
    "AI model data Ollama downloaded to run locally.",
  "Python이 다시 생성할 수 있는 바이트코드 캐시입니다.":
    "Bytecode cache Python can regenerate.",
  "Ruff가 다시 생성할 수 있는 검사 캐시입니다.":
    "Lint cache Ruff can regenerate.",
  "Turbo가 다시 생성할 수 있는 빌드 캐시입니다.":
    "Build cache Turbo can regenerate.",
  "Xcode 시뮬레이터 가상 기기 데이터와 런타임 저장소입니다.":
    "Xcode Simulator virtual-device data and runtime storage.",
  "Xcode 시뮬레이터 실행 캐시입니다.": "Xcode Simulator runtime cache.",
  "Xcode가 빌드하면서 만든 파생 데이터입니다.":
    "Derived data Xcode created while building.",
  "Xcode가 앱 배포/아카이브 빌드 시 남긴 아카이브(.xcarchive) 파일입니다.":
    "Archive (.xcarchive) files Xcode left from distribution/archive builds.",
  "mypy가 다시 생성할 수 있는 타입 검사 캐시입니다.":
    "Type-check cache mypy can regenerate.",
  "npm이 다시 내려받을 수 있는 패키지 캐시입니다.":
    "Package cache npm can re-download.",
  "pip 패키지 설치 다운로드 캐시입니다.":
    "Download cache from installing pip packages.",
  "pnpm이 패키지를 재사용하기 위해 보관한 저장소입니다.":
    "Store pnpm keeps to reuse packages.",
  "pytest가 다시 생성할 수 있는 테스트 캐시입니다.":
    "Test cache pytest can regenerate.",
  "앱 업데이트나 실행 과정에서 만든 캐시입니다.":
    "Cache created while updating or running the app.",
  "앱과 개발 도구가 다시 만들 수 있는 데이터를 담아 두는 캐시입니다.":
    "A cache holding data that apps and dev tools can rebuild.",
  "앱이 다시 만들거나 내려받을 수 있는 캐시입니다.":
    "Cache the app can rebuild or re-download.",
  "연결했던 iOS 기기의 디버깅 기호(Symbol) 파일입니다.":
    "Debug symbol files for iOS devices you connected.",
  "연결했던 tvOS 기기의 디버깅 기호 파일입니다.":
    "Debug symbol files for tvOS devices you connected.",
  "연결했던 watchOS 기기의 디버깅 기호 파일입니다.":
    "Debug symbol files for watchOS devices you connected.",
  "패키지 명세로 다시 설치할 수 있는 프로젝트 의존성입니다.":
    "Project dependencies reinstallable from the package manifest.",

  // 카테고리 주의(advice)
  "Chrome과 Google 업데이트가 진행 중이지 않을 때만 정리를 검토해야 합니다.":
    "Only clean when Chrome and Google updates aren't in progress.",
  "Docker 데스크탑을 종료 후 정리해야 하며, 로컬 컨테이너와 빌드 레이어가 지워질 수 있습니다.":
    "Quit Docker Desktop first; local containers and build layers may be removed.",
  "package.json과 lock 파일이 온전한지 먼저 확인해야 합니다.":
    "Make sure package.json and the lock file are intact first.",
  "pod install 시 필요 시 다시 다운로드됩니다.":
    "Re-downloaded as needed on the next pod install.",
  "과거 앱 배포 빌드 기록 및 디버깅 기호가 포함되어 있어 필요 여부를 검토해야 합니다.":
    "Contains past distribution build records and debug symbols — review whether you still need them.",
  "관련 앱을 종료한 뒤 정리해야 하며, 일부 데이터가 다시 내려받아질 수 있습니다.":
    "Quit the related app first; some data may be re-downloaded.",
  "구형 iOS 기기 기호 파일은 정리해도 안전하지만 해당 기기 디버깅 시 재추출됩니다.":
    "Old iOS device symbol files are safe to clean but are re-extracted when you debug that device.",
  "내용과 백업 여부를 직접 확인하기 전에는 정리하면 안 됩니다.":
    "Don't clean until you've checked the contents and whether it's backed up.",
  "다시 구하기 어렵거나 아직 필요한 파일인지 확인해야 합니다.":
    "Check whether it's hard to obtain again or still needed.",
  "다음 Python 실행 때 다시 만들어집니다.": "Recreated on the next Python run.",
  "다음 pip install 시 인터넷에서 다시 다운로드합니다.":
    "Re-downloaded from the internet on the next pip install.",
  "다음 검사가 느려질 수 있습니다.": "The next check may be slower.",
  "다음 빌드 시 필요한 의존성을 다시 인터넷에서 다운로드합니다.":
    "The next build re-downloads the needed dependencies from the internet.",
  "다음 빌드가 느려지고 의존성을 다시 내려받을 수 있습니다.":
    "The next build is slower and may re-download dependencies.",
  "다음 빌드가 느려질 수 있습니다.": "The next build may be slower.",
  "다음 설치에서 패키지를 다시 내려받을 수 있습니다.":
    "The next install may re-download packages.",
  "다음 타입 검사가 느려질 수 있습니다.": "The next type check may be slower.",
  "로컬 자격 증명과 빌드 캐시 설정이 초기화될 수 있습니다.":
    "Local credentials and build-cache settings may be reset.",
  "배포 중인 로컬 서버를 먼저 종료해야 합니다.":
    "Stop the running local server first.",
  "삭제하면 해당 모델을 쓸 수 없으며 필요할 때 수 GB를 다시 받아야 합니다.":
    "Deleting it makes the model unusable and requires re-downloading several GB when needed.",
  "설치 파일 또는 압축 파일이라 재다운로드 가능성을 검토할 수 있습니다.":
    "An installer or archive — consider whether it can be re-downloaded.",
  "시뮬레이터에 설치된 임시 앱과 로컬 데이터가 초기화됩니다.":
    "Temporary apps and local data installed in the simulator are reset.",
  "실행 중인 빌드를 멈추고 Cargo.toml과 소스가 온전한지 확인해야 합니다.":
    "Stop any running build and verify Cargo.toml and sources are intact.",
  "앱을 종료한 뒤 정리해야 하며, 다음 실행이 느려질 수 있습니다.":
    "Quit the app first; the next launch may be slower.",
  "오프라인 설치에 필요할 수 있으며 재다운로드 시간이 생깁니다.":
    "May be needed for offline installs, and re-downloading takes time.",
  "원본이 유일한 백업이 아닌지, 다시 받을 수 있는지 확인해야 합니다.":
    "Check that the original isn't your only backup and can be re-obtained.",
  "정리 후 첫 빌드가 오래 걸리고 인덱스를 다시 만들 수 있습니다.":
    "The first build after cleaning takes longer and may rebuild the index.",
  "정리 후 필요 시 다시 인터넷에서 다운로드합니다.":
    "Re-downloaded from the internet as needed after cleaning.",
  "첫 go build가 느려질 수 있습니다.": "The first go build may be slower.",
  "테스트 실행 기록 일부가 초기화됩니다.":
    "Part of the test-run history is reset.",
  "필요 시 시뮬레이터 실행 때 자동 재생성됩니다.":
    "Regenerated automatically when the simulator runs, as needed.",
  "필요할 때 다시 생성되지만 첫 실행이나 재다운로드에 시간이 걸릴 수 있습니다.":
    "Regenerated when needed, but the first run or re-download can take time.",
  "해당 가상 디바이스 및 내부 저장 데이터가 초기화되므로 확인이 필요합니다.":
    "The virtual device and its internal data are reset, so confirm first.",
  "해당 기기 연결 디버깅 시 재추출됩니다.":
    "Re-extracted when you debug that device.",
  "사용자가 분석을 중단했습니다.": "Analysis was stopped by the user.",
  "잔여 파일": "Leftover file",

  // 확인 모달
  "취소": "Cancel",
  "선택 항목을 격리할까요?": "Quarantine the selected items?",
  "원래 위치에서 Spacekeeper 격리함으로 옮겨집니다. 저장 공간은 아직 늘지 않으며 언제든 복원할 수 있어요.":
    "They move from their original location to Spacekeeper's Quarantine. Free space doesn't increase yet, and you can restore anytime.",
  "격리하기": "Quarantine",
  "휴지통으로 보낼까요?": "Move to Trash?",
  "휴지통으로 보내기": "Move to Trash",

  // 기록 (추이 + 활동 로그)
  "기록": "History",
  "스캔과 정리 활동을 이 Mac 안에만 남깁니다. 시간에 따라 무엇이 얼마나 쌓이고 정리됐는지 보세요.":
    "Scan and cleanup activity is kept only on this Mac. See what piles up and gets cleared over time.",
  "활동 로그": "Activity log",
  "기록을 불러오는 중…": "Loading history…",
  "스캔": "Scan",
  "격리": "Quarantine",
  "복원": "Restore",
  "휴지통으로": "To Trash",
};

/**
 * 숫자·용량이 끼어드는 동적 문자열은 전체 일치로는 못 바꾼다.
 * 렌더된 한국어 텍스트를 정규식으로 잡아 영어로 재구성한다.
 * (숫자·용량·시간 값은 그대로 두고 단위/문구만 영어로 바꾼다.)
 */
const EN_PATTERNS = [
  // 목록 요약
  [/^(.+?)개 파일 · 총 (.+?) \(최소 크기 (.+?)\)$/,
    (m) => `${m[1]} files · ${m[2]} total (min ${m[3]})`],
  [/^(.+?)개 파일 · 총 (.+?) · 항목을 펼쳐 단서를 확인하세요$/,
    (m) => `${m[1]} files · ${m[2]} total · expand an item for clues`],
  [/^(.+?)개 항목 · 총 (.+?) 정리 가능$/,
    (m) => `${m[1]} items · ${m[2]} reclaimable`],
  [/^(.+?)개 그룹 · 최대 (.+?) 정리 가능$/,
    (m) => `${m[1]} groups · up to ${m[2]} reclaimable`],
  [/^전체 (.+?)개 중 (.+?)개 표시$/,
    (m) => `Showing ${m[2]} of ${m[1]}`],
  [/^전체 (.+?)개 파일$/, (m) => `${m[1]} files total`],
  [/^사용자 (.+?)개 · 시스템 (.+?)개$/,
    (m) => `${m[1]} user · ${m[2]} system`],
  // 선택 상태
  [/^(.+?)개 · (.+?) 선택$/, (m) => `${m[1]} selected · ${m[2]}`],
  [/^(.+?)개 선택$/, (m) => `${m[1]} selected`],
  // 보관 상태
  [/^(.+?)개 항목 · (.+?) 보관 중$/, (m) => `${m[1]} items · ${m[2]} held`],
  [/^(.+?) 보관 중$/, (m) => `${m[1]} held`],
  // 진단 카운트
  [/^준비됨 (.+?)개$/, (m) => `${m[1]} ready`],
  [/^확인 (.+?)개$/, (m) => `${m[1]} to review`],
  [/^조치 (.+?)개$/, (m) => `${m[1]} to act`],
  // 자동 정리 상태
  [/^자동 정리가 켜져 있어요 · (.+?)시간마다 실행됩니다\.$/,
    (m) => `Auto cleanup is on · runs every ${m[1]} hours.`],
  // 대용량/결정 빈 상태(최소 크기 삽입)
  [/^(.+?) 이상의 대용량 파일을 찾지 못했습니다\.$/,
    (m) => `No large files found at or above ${m[1]}.`],
  [/^(.+?) 이상의 파일이 없습니다\.$/,
    (m) => `No files at or above ${m[1]}.`],
  // 백엔드 이유(숫자 삽입)
  [/^다운로드 폴더에서 (.+?)일 동안 수정되지 않았습니다\.$/,
    (m) => `Not modified in the Downloads folder for ${m[1]} days.`],
  [/^큰 파일 기준을 넘었습니다 \((.+?) bytes\)\.$/,
    (m) => `Exceeds the large-file threshold (${m[1]} bytes).`],
  [/^기타 항목 \((.+?)개\)$/, (m) => `Other items (${m[1]})`],
  [/^수정: (.+)$/, (m) => `Modified: ${m[1]}`],
  // 신호 단서(개수 삽입)
  [/^Finder에서 보기: (.+)$/, (m) => `Show in Finder: ${m[1]}`],
  [/^(.+?)개 \(내용 동일\)$/, (m) => `${m[1]} (identical contents)`],
  [/^이름·크기가 같은 파일 (.+?)개$/,
    (m) => `${m[1]} files with the same name and size`],
  // 위험도 막대(라벨 + 용량)
  [/^낮은 위험 (.+)$/, (m) => `Low risk ${m[1]}`],
  [/^확인 필요 (.+)$/, (m) => `Review ${m[1]}`],
  [/^높은 주의 (.+)$/, (m) => `Caution ${m[1]}`],
  // 스캔 진행/요약
  [/^(.+?)개 파일 · (.+?) 확인 · 후보 (.+?)개$/,
    (m) => `${m[1]} files · ${m[2]} checked · ${m[3]} candidates`],
  [/^파일 (.+?)개 · (.+?)초$/, (m) => `${m[1]} files · ${m[2]}s`],
  [/^후보 (.+?)개$/, (m) => `${m[1]} candidates`],
  // 카테고리 소제목 · 스캔 버튼 라벨
  [/^(.+?)개 항목을 확인하세요$/, (m) => `Review ${m[1]} item(s)`],
  [/^(.+?) 분석하기$/, (m) => `Analyze ${EN[m[1]] || m[1]}`],
  [/^(.+?) 저장 공간을 분석하는 중…$/, (m) => `Analyzing ${EN[m[1]] || m[1]}…`],
  // 카테고리 헤더(라벨 · 개수 · 용량 · 위험도) — 위험도 라벨은 별도 노드가 아닐 때
  [/^(.+?) · (.+?)개 · (.+?) · (낮은 위험|확인 필요|높은 주의)$/,
    (m) => {
      const risk = { "낮은 위험": "Low risk", "확인 필요": "Review", "높은 주의": "Caution" }[m[4]];
      return `${EN[m[1]] || m[1]} · ${m[2]} · ${m[3]} · ${risk}`;
    }],
];

function applyPatterns(value) {
  const key = value.trim();
  for (const [re, fn] of EN_PATTERNS) {
    const m = key.match(re);
    if (m) return value.replace(key, fn(m));
  }
  return null;
}

function currentLang() {
  const saved = localStorage.getItem(SK_LANG_KEY);
  if (saved === "ko" || saved === "en") return saved;
  return (navigator.language || "ko").toLowerCase().startsWith("ko") ? "ko" : "en";
}

/** 한국어 원문을 현재 언어로 옮긴다(사전에 없으면 원문 그대로). */
function t(korean) {
  return currentLang() === "en" ? EN[korean] || korean : korean;
}

function translateText(textNode) {
  const key = textNode.nodeValue.trim();
  if (!key) return;
  if (EN[key]) {
    textNode.nodeValue = textNode.nodeValue.replace(key, EN[key]);
    return;
  }
  const patterned = applyPatterns(textNode.nodeValue);
  if (patterned !== null) textNode.nodeValue = patterned;
}

function translateNode(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    translateText(node);
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;

  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const text of texts) translateText(text);

  const attrs = ["placeholder", "title", "aria-label"];
  const scope = [node, ...node.querySelectorAll("[placeholder],[title],[aria-label]")];
  for (const el of scope) {
    if (!el.getAttribute) continue;
    for (const attr of attrs) {
      const value = el.getAttribute(attr);
      if (!value) continue;
      const key = value.trim();
      if (EN[key]) {
        el.setAttribute(attr, EN[key]);
      } else {
        const patterned = applyPatterns(value);
        if (patterned !== null) el.setAttribute(attr, patterned);
      }
    }
  }
}

function translateAll() {
  translateNode(document.body);
}

function setLang(lang) {
  localStorage.setItem(SK_LANG_KEY, lang);
  location.reload(); // 한국어가 원본이므로 되돌릴 때는 다시 그리는 편이 안전하다.
}

function initI18n() {
  if (currentLang() !== "en") return;
  document.documentElement.lang = "en";
  translateAll();
  // 동적으로 그려지는 목록·토스트도 따라오게 한다.
  new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === "characterData") translateNode(record.target);
      else record.addedNodes.forEach(translateNode);
    }
  }).observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
}

window.SKI18N = { t, currentLang, setLang, translateAll, EN };
window.t = t;

document.addEventListener("DOMContentLoaded", initI18n);
