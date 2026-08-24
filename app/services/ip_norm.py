"""IP 정규화 키 (지시서 §6 13번): lower(trim(title)) 에서 공백·구두점 제거."""
from __future__ import annotations

import re
import unicodedata

_STRIP = re.compile(r"[\s\W_]+", re.UNICODE)


def norm_key(title: str) -> str:
    s = unicodedata.normalize("NFKC", title or "").strip().lower()
    return _STRIP.sub("", s)
