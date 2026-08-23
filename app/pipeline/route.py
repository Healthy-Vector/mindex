"""페이지별 경로 판정 — 텍스트 레이어를 쓸지 OCR로 보낼지.

사용자는 디지털 PDF와 스캔본을 구분하지 않고 올린다. 파일 확장자로는 알 수 없고
한 문서 안에서 섞이기도 한다(본문은 디지털인데 서명 페이지만 스캔). 그래서
**문서가 아니라 페이지 단위로** 판정한다.

pdfplumber에 의존하지 않는다. 신호(숫자)만 받아서 판정하므로 단위 테스트가 쉽고
CI에서 그대로 돈다. 신호 계산은 extract.py가 맡는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# 판정 임계값 — 합성데이터 86건 446페이지(전부 digital-born) 문자밀도 실측으로 정했다.
#
#   정상 최소 0.152 (JP) / 중앙 2.327 / 최대 7.583   래스터화한 스캔본 0.000
#   임계 0.30 -> 정상 오탐 27개(6.1%) / 0.20 -> 10개(2.2%) / 0.10 -> 0개
#
# CJK는 같은 내용을 적은 문자로 쓰고 표가 많은 페이지는 텍스트가 짧게 나오므로
# 밀도만으로 판정하면 짧은 정상 페이지를 스캔으로 오탐한다.
# 밀도는 낮게 잡고 이미지 덮개율을 주 신호로 쓴다.
MIN_CHARS_PER_KPX = 0.10
MIN_CHARS_ABS = 30
MAX_IMAGE_COVERAGE = 0.6
# 이미지가 페이지를 덮으면서 텍스트도 어느 정도 있으면
# "스캔 + 품질 나쁜 OCR 레이어"를 의심한다.
SUSPECT_DENSITY_UNDER_IMAGE = 0.5


class TextSource(StrEnum):
    TEXT_LAYER = "TEXT_LAYER"
    OCR = "OCR"
    VERIFY = "VERIFY"


@dataclass(frozen=True)
class PageSignals:
    """경로 판정에 쓰는 페이지 신호. 전부 pdfplumber에서 뽑은 순수 숫자다."""

    char_count: int
    chars_per_kpx: float
    image_coverage: float
    image_count: int
    bad_char_count: int

    def as_dict(self) -> dict:
        return {
            "char_count": self.char_count,
            "chars_per_kpx": round(self.chars_per_kpx, 3),
            "image_coverage": round(self.image_coverage, 3),
            "image_count": self.image_count,
            "bad_char_count": self.bad_char_count,
        }


def route(sig: PageSignals) -> TextSource:
    """TEXT_LAYER / OCR / VERIFY 3-way 분기.

    VERIFY는 "둘 다 해보고 대조하라"는 뜻이다. 애매한 페이지를 한쪽으로
    단정하면 조용히 틀리므로, 판정을 유보하고 비용을 더 쓰는 쪽을 택한다.
    """
    # 텍스트 레이어가 사실상 없음 -> 순수 스캔
    if sig.chars_per_kpx < MIN_CHARS_PER_KPX or sig.char_count < MIN_CHARS_ABS:
        return TextSource.OCR

    # 페이지를 이미지가 덮었는데 텍스트가 빈약함 -> 스캔 + 나쁜 OCR 레이어
    if (
        sig.image_coverage > MAX_IMAGE_COVERAGE
        and sig.chars_per_kpx < SUSPECT_DENSITY_UNDER_IMAGE
    ):
        return TextSource.OCR

    # 깨진 문자가 섞였거나 이미지가 덮고 있으면 교차검증
    if sig.bad_char_count > 0 or sig.image_coverage > MAX_IMAGE_COVERAGE:
        return TextSource.VERIFY

    return TextSource.TEXT_LAYER
