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
  "분석할 위치": "Location to analyze",
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
};

function currentLang() {
  const saved = localStorage.getItem(SK_LANG_KEY);
  if (saved === "ko" || saved === "en") return saved;
  return (navigator.language || "ko").toLowerCase().startsWith("ko") ? "ko" : "en";
}

/** 한국어 원문을 현재 언어로 옮긴다(사전에 없으면 원문 그대로). */
function t(korean) {
  return currentLang() === "en" ? EN[korean] || korean : korean;
}

function translateNode(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    const key = node.nodeValue.trim();
    if (key && EN[key]) node.nodeValue = node.nodeValue.replace(key, EN[key]);
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;

  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const text of texts) {
    const key = text.nodeValue.trim();
    if (key && EN[key]) text.nodeValue = text.nodeValue.replace(key, EN[key]);
  }

  const attrs = ["placeholder", "title", "aria-label"];
  const scope = [node, ...node.querySelectorAll("[placeholder],[title],[aria-label]")];
  for (const el of scope) {
    if (!el.getAttribute) continue;
    for (const attr of attrs) {
      const value = el.getAttribute(attr);
      if (value && EN[value.trim()]) el.setAttribute(attr, EN[value.trim()]);
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
