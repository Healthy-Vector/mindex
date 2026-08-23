"""추출 텍스트 정규화.

Evidence Anchoring이 문자 offset으로 원문을 되짚으므로, 여기서 문자열이 한 번
어긋나면 뒤의 모든 인용이 어긋난다. 그래서 이 모듈은 **길이를 보존하거나,
보존하지 않는 경우 그 이유가 명확한 변환만** 수행한다.

의존성 없음 — torch/pdfplumber 없이 동작하므로 CI에서 그대로 검증된다.
"""

from __future__ import annotations

import unicodedata

# 일본어 PDF가 정규 한자 대신 내보내는 CJK 호환한자 범위.
CJK_COMPAT_START, CJK_COMPAT_END = 0xF900, 0xFAFF

SOFT_HYPHEN = "­"


def normalize_text(text: str) -> str:
    """NFC 정규화 + 소프트하이픈 처리.

    ## NFC를 쓰는 이유

    일본어 PDF가 정규 한자 대신 CJK 호환한자(U+F900~U+FAFF)를 내보낸다.
    실측: JP 28건 전부에서 4,865자 출현. 예) 利(U+5229)가 U+F9DD로 나온다.
    이대로 두면 정규식·LLM 추출·임베딩·Evidence 문자열 대조가 모두 어긋난다.
    정답지인 canonical Markdown은 정규형(호환한자 0자)이라 NFC를 적용해야 일치한다.

    NFKC가 아니라 NFC인 이유는 길이 보존이다. 이 범위의 호환한자는 canonical
    decomposition을 가지므로 NFC로 정규화되고, 실측상 446페이지 전부 길이가
    보존됐다. NFKC는 전각/반각·합자까지 바꿔 길이가 달라지고 offset이 깨진다.

    ## 소프트하이픈

    영문 PDF가 눈에 보이는 하이픈 자리에 U+00AD를 쓴다. 예) 날짜 "2026-01-01"이
    실제로는 U+00AD를 낀 형태로 나온다. 실측 샘플 10건에서 119자 중 117자가
    문장 내부(실제 하이픈), 2자가 줄끝 하이프네이션이었다.
    그래서 줄끝이면 지우고, 그 밖에는 일반 하이픈으로 바꾼다.

    줄끝 제거는 길이를 줄이는 유일한 변환이다. 정규화 이전 offset을 들고
    있으면 안 되는 이유가 이것이다. 파이프라인은 **정규화된 텍스트를 기준**으로
    offset을 계산한다.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace(SOFT_HYPHEN + "\n", "\n")
    return text.replace(SOFT_HYPHEN, "-")


def count_cjk_compatibility(text: str) -> int:
    """호환한자가 남아 있는지 세는 진단용. 정규화 후에는 0이어야 한다."""
    return sum(1 for ch in text if CJK_COMPAT_START <= ord(ch) <= CJK_COMPAT_END)
