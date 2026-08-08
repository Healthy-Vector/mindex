"""DAR-002 합성 계약서 생성 스크립트 — 담당 P3, 검수 분담 P4.

목표 500건 구성 (RFP DAR-002):

    정상 계약           350   오탐률 0% 검증
    충돌 케이스          50   핵심 시연
    만료 임박            30   알림 기능
    인젝션 공격 문서      20   보안 테스트 (SER-001)
    스캔본 이미지         30   OCR
    다국어(영문 등)       20   크로스링구얼 테스트 (TER-004)

조항 언어는 공개 소스에서 가져온다 — 문체부 표준계약서, 저작권위원회 표준계약서,
CUAD(HuggingFace). 회사명·금액·날짜만 합성한다. 실데이터는 사용하지 않는다 (DAR-003).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

COMPOSITION = {
    "normal": 350,
    "conflict": 50,
    "expiring_soon": 30,
    "injection": 20,
    "scanned_ocr": 30,
    "multilingual": 20,
}


@dataclass
class GenerationPlan:
    category: str
    count: int


def build_plan() -> list[GenerationPlan]:
    return [GenerationPlan(category=k, count=v) for k, v in COMPOSITION.items()]


def main() -> None:
    parser = argparse.ArgumentParser(description="합성 계약서 생성")
    parser.add_argument("--out", default="data/generated", help="출력 디렉터리")
    parser.add_argument(
        "--dry-run", action="store_true", help="생성 없이 계획만 출력"
    )
    args = parser.parse_args()

    plan = build_plan()
    total = sum(p.count for p in plan)
    print(f"합성 계약서 생성 계획 — 총 {total}건 → {args.out}")
    for p in plan:
        print(f"  {p.category:15s} {p.count:4d}건")

    if args.dry_run:
        return

    # TODO: 카테고리별 생성 로직 구현
    # - normal / conflict: 표준계약서 조항 템플릿 + 합성 회사명·금액·날짜
    # - conflict: rights_grant의 EXCLUDE 제약을 실제로 위반하도록 기간·지역 의도적으로 겹치게 생성
    # - injection: 프롬프트 인젝션 문구 삽입 (SER-001 4중 방어 테스트용)
    # - scanned_ocr: PDF를 이미지로 변환해 OCR 경로 테스트
    # - multilingual: 영문 등 비한국어 계약서
    raise NotImplementedError("카테고리별 생성 로직을 구현하세요")


if __name__ == "__main__":
    main()
