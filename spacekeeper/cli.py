from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import ScanOptions
from .planning import VALID_RISKS, build_cleanup_plan, render_cleanup_plan
from .report import render_text
from .scanner import scan


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("0보다 큰 정수가 필요합니다.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spacekeeper",
        description="삭제 없이 맥 저장공간의 정리 후보를 설명합니다.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="스캔할 폴더. 생략하면 ~/Downloads만 확인합니다.",
    )
    parser.add_argument(
        "--large-mb",
        type=_positive_int,
        default=500,
        help="큰 파일 기준(MB, 기본 500)",
    )
    parser.add_argument(
        "--old-days",
        type=_positive_int,
        default=180,
        help="오래된 다운로드 기준 일수(기본 180)",
    )
    parser.add_argument(
        "--top",
        type=_positive_int,
        default=20,
        help="분류별 최대 표시 개수(기본 20)",
    )
    parser.add_argument(
        "--duplicates",
        action="store_true",
        help="10MB 이상 파일의 SHA-256을 계산해 완전 동일 파일을 찾습니다.",
    )
    parser.add_argument(
        "--duplicate-min-mb",
        type=_positive_int,
        default=10,
        help="중복 검사 최소 크기(MB, 기본 10)",
    )
    parser.add_argument(
        "--include-cloud",
        action="store_true",
        help="iCloud Drive와 CloudStorage 루트도 포함합니다. 기본값은 제외입니다.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="스캔 보고서 대신 ID가 붙은 읽기 전용 정리 미리보기를 만듭니다.",
    )
    parser.add_argument(
        "--risk",
        choices=[*VALID_RISKS, "all"],
        default="low",
        help="미리보기에 포함할 위험도(기본 low, --plan에서 사용)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="사람용 보고서 대신 JSON을 출력합니다.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="터미널 대신 로컬 웹 대시보드를 실행합니다.",
    )
    parser.add_argument(
        "--port",
        type=_positive_int,
        default=8765,
        help="대시보드 포트(기본 8765, --serve에서 사용)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.serve:
        from .server import serve

        serve(port=args.port)
        return 0

    roots = tuple(args.paths) if args.paths else (Path.home() / "Downloads",)
    scan_result_limit = max(args.top, 100_000) if args.plan else args.top
    options = ScanOptions(
        roots=roots,
        large_bytes=args.large_mb * 1024 * 1024,
        old_days=args.old_days,
        top=scan_result_limit,
        find_duplicates=args.duplicates,
        duplicate_min_bytes=args.duplicate_min_mb * 1024 * 1024,
        include_cloud_storage=args.include_cloud,
    )
    try:
        result = scan(options)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        parser.exit(2, f"spacekeeper: {exc}\n")

    if args.plan:
        risks = set(VALID_RISKS) if args.risk == "all" else {args.risk}
        plan = build_cleanup_plan(result, risks=risks, limit=args.top)
        payload = plan.to_dict()
        rendered = render_cleanup_plan(plan)
    else:
        payload = result.to_dict()
        rendered = render_text(result)

    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(rendered)
    return 0
