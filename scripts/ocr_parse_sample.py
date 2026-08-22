"""OCR/파싱 1차 결과 → LLM 정규화 task 인계용 2차 가공 샘플 생성기.

담당 P3. 화면에서 업로드된 PDF를 파싱해 조항 단위로 분해하고,
LLM 추출·정규화 task가 그대로 받아쓸 수 있는 payload를 만든다.

    python scripts/ocr_parse_sample.py <pdf...> -o docs/handoff/samples

이 스크립트는 파이프라인 본구현이 아니라 **인계 규격을 고정하기 위한 샘플 생성기**다.
본구현은 app/pipeline/ 에 들어간다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import pdfplumber

SCHEMA_VERSION = "mindex.ocr-parse.v0.1"

# 페이지 경로 판정 임계값.
#
# 합성데이터 86건 446페이지(전부 digital-born)의 문자밀도 실측 분포로 정했다.
#   정상 최소 0.152 (JP) / 중앙 2.327 / 최대 7.583, 래스터화한 스캔본은 0.000
#   임계 0.30 -> 정상 오탐 27개(6.1%) / 0.20 -> 10개(2.2%) / 0.10 -> 0개
# CJK는 같은 내용을 적은 문자로 쓰고 표가 많은 페이지는 텍스트가 짧게 나오므로
# 밀도만으로 판정하면 짧은 정상 페이지를 스캔으로 오탐한다. 밀도는 낮게 잡고
# 이미지 덮개율을 주 신호로 쓴다.
MIN_CHARS_PER_KPX = 0.10
MIN_CHARS_ABS = 30
MAX_IMAGE_COVERAGE = 0.6
# 이미지가 페이지를 덮으면서 텍스트도 어느 정도 있으면 "스캔 + 품질 나쁜 OCR 레이어"를 의심한다.
SUSPECT_DENSITY_UNDER_IMAGE = 0.5

# 본문 조항 머리 패턴. 언어 판별에도 쓴다.
CLAUSE_PATTERNS = {
    "ko": re.compile(r"^\s*제\s*(\d+)\s*조\s*[(（]?\s*([^)）]*)[)）]?\s*$"),
    "ja": re.compile(r"^\s*第\s*(\d+)\s*条\s*[(（]?\s*([^)）]*)[)）]?\s*$"),
    "en": re.compile(r"^\s*(?:Article|Clause|Section)\s+(\d+)\s*[(（]?\s*([^)）]*)[)）]?\s*$"),
}

# 별지 머리. 별지에 실제 권리부여 명세(작품·권리·지역·기간·독점성·금액)가 들어가므로
# 본문 조항과 동급의 분해 단위로 다뤄야 한다. 직전 조항에 흡수되면 추출이 통째로 어긋난다.
SCHEDULE_PATTERNS = {
    "ko": re.compile(r"^\s*(별지)\s*(\d+)\s*[—\-–:]?\s*(.*)$"),
    "ja": re.compile(r"^\s*(別紙)\s*(\d+)\s*[—\-–:]?\s*(.*)$"),
    "en": re.compile(r"^\s*(Schedule|Exhibit|Appendix|Annex)\s+(\d+)\s*[—\-–:]?\s*(.*)$"),
}

# 별지 안에서 개별 권리부여를 나누는 머리.
GRANT_ITEM_PATTERNS = {
    "ko": re.compile(r"^\s*(개별\s*이용허락)\s*(\d+)\s*$"),
    "ja": re.compile(r"^\s*(個別(?:利用)?許諾)\s*(\d+)\s*$"),
    "en": re.compile(r"^\s*(Individual\s+Lic[e|s]nce|Individual\s+License|Grant)\s+(\d+)\s*$"),
}

# 머리말/꼬리말 — 조항 텍스트에서 제거한다.
NOISE_PATTERNS = [
    re.compile(r"NOT FOR EXECUTION", re.I),
    re.compile(r"^\s*\|?\s*\d+\s*/\s*\d+\s*$"),
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def page_signals(page) -> dict:
    """텍스트 레이어를 쓸지 OCR로 갈지 판정할 신호."""
    text = page.extract_text() or ""
    area = (page.width or 1) * (page.height or 1)
    image_area = sum(
        max(0.0, i.get("x1", 0) - i.get("x0", 0)) * max(0.0, i.get("bottom", 0) - i.get("top", 0))
        for i in (page.images or [])
    )
    bad = text.count("�") + text.count("\x00")
    return {
        "char_count": len(text),
        "chars_per_kpx": round(len(text) / (area / 1000), 3),
        "image_coverage": round(image_area / area, 3) if area else 0.0,
        "image_count": len(page.images or []),
        "bad_char_count": bad,
    }


def route(sig: dict) -> str:
    """TEXT_LAYER / OCR / VERIFY 3-way 분기."""
    # 텍스트 레이어가 사실상 없음 -> 순수 스캔
    if sig["chars_per_kpx"] < MIN_CHARS_PER_KPX or sig["char_count"] < MIN_CHARS_ABS:
        return "OCR"
    # 페이지를 이미지가 덮었는데 텍스트가 빈약함 -> 스캔 + 나쁜 OCR 레이어
    if (
        sig["image_coverage"] > MAX_IMAGE_COVERAGE
        and sig["chars_per_kpx"] < SUSPECT_DENSITY_UNDER_IMAGE
    ):
        return "OCR"
    # 깨진 문자가 섞였거나 이미지가 덮고 있으면 교차검증
    if sig["bad_char_count"] > 0 or sig["image_coverage"] > MAX_IMAGE_COVERAGE:
        return "VERIFY"
    return "TEXT_LAYER"


def strip_noise(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    for pat in NOISE_PATTERNS:
        if pat.search(stripped):
            return None
    return line


def detect_language(lines: list[str]) -> str:
    hits = {lang: sum(1 for ln in lines if pat.match(ln)) for lang, pat in CLAUSE_PATTERNS.items()}
    best = max(hits, key=lambda k: hits[k])
    return best if hits[best] else "unknown"


def extract_pages(pdf_path: Path) -> list[dict]:
    """1차 파싱 — 페이지 단위 원문과 경로 판정."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            sig = page_signals(page)
            text = page.extract_text() or ""
            tables = [
                [[(c or "").strip() for c in row] for row in tbl]
                for tbl in (page.extract_tables() or [])
            ]
            pages.append(
                {
                    "page": idx,
                    "text_source": route(sig),
                    "signals": sig,
                    "text": text,
                    "tables": tables,
                }
            )
    return pages


def segment_clauses(pages: list[dict], lang: str) -> tuple[str, list[dict]]:
    """2차 가공 — 페이지를 이어붙여 조항으로 분해한다.

    조항은 페이지를 넘어갈 수 있으므로 전체 텍스트에서 분해하되,
    각 줄이 몇 페이지에서 왔는지를 함께 들고 다닌다.
    """
    pattern = CLAUSE_PATTERNS.get(lang)
    numbered: list[tuple[str, int]] = []
    for pg in pages:
        for raw in pg["text"].split("\n"):
            line = strip_noise(raw)
            if line is not None:
                numbered.append((line, pg["page"]))

    full_text = "\n".join(ln for ln, _ in numbered)

    # 각 줄의 시작 offset
    offsets, cursor = [], 0
    for line, _ in numbered:
        offsets.append(cursor)
        cursor += len(line) + 1

    # 분해 지점 수집 — 본문 조항 / 별지 / 별지 내 개별 권리부여
    sched_pat = SCHEDULE_PATTERNS.get(lang)
    item_pat = GRANT_ITEM_PATTERNS.get(lang)
    heads: list[tuple[int, str, str, str]] = []  # (line_idx, kind, label, title)

    for i, (line, _page) in enumerate(numbered):
        if pattern and (m := pattern.match(line)):
            label = {"ko": f"제{m.group(1)}조", "ja": f"第{m.group(1)}条"}.get(
                lang, f"Article {m.group(1)}"
            )
            heads.append((i, "ARTICLE", label, (m.group(2) or "").strip()))
        elif sched_pat and (m := sched_pat.match(line)):
            heads.append((i, "SCHEDULE", f"{m.group(1)} {m.group(2)}", (m.group(3) or "").strip()))
        elif item_pat and (m := item_pat.match(line)):
            heads.append((i, "GRANT_ITEM", f"{m.group(1)} {m.group(2)}", ""))

    clauses: list[dict] = []

    def add(clause_no, title, start_i, end_i, kind="ARTICLE"):
        if start_i >= end_i:
            return
        seg = numbered[start_i:end_i]
        body = "\n".join(ln for ln, _ in seg)
        if not body.strip():
            return

        # 페이지 경계로 조각을 나눈다. contract_chunk.page 가 단일 INT 이므로
        # 청크는 한 페이지에만 속해야 한다.
        parts: list[dict] = []
        for i in range(start_i, end_i):
            line, page = numbered[i]
            if parts and parts[-1]["page"] == page:
                parts[-1]["lines"].append(line)
                parts[-1]["char_end"] = offsets[i] + len(line)
            else:
                parts.append(
                    {
                        "page": page,
                        "lines": [line],
                        "char_start": offsets[i],
                        "char_end": offsets[i] + len(line),
                    }
                )
        for part in parts:
            part["text"] = "\n".join(part.pop("lines"))

        clauses.append(
            {
                "clause_no": clause_no,
                "kind": kind,
                "title": title,
                "page_start": seg[0][1],
                "page_end": seg[-1][1],
                "char_start": offsets[start_i],
                "char_end": offsets[end_i - 1] + len(seg[-1][0]),
                "text": body,
                "pages": sorted({p for _, p in seg}),
                "page_parts": parts,
            }
        )

    if heads:
        add("__FRONT_MATTER__", "표제·당사자·전문", 0, heads[0][0], kind="FRONT_MATTER")
        for n, (i, kind, label, title) in enumerate(heads):
            end = heads[n + 1][0] if n + 1 < len(heads) else len(numbered)
            add(label, title, i, end, kind=kind)
    else:
        add("__UNSEGMENTED__", "", 0, len(numbered), kind="UNSEGMENTED")

    return full_text, clauses


def build_chunks(clauses: list[dict], lang: str, max_chars: int, overlap: int) -> list[dict]:
    """조항 × 페이지 단위로 청크를 만든다.

    contract_chunk.page 가 단일 INT 이므로 한 청크는 한 페이지에만 속해야 한다.
    조항이 페이지를 넘으면 페이지 경계에서 자른다. 그래도 긴 조각은 슬라이딩으로 쪼갠다.
    """
    chunks: list[dict] = []
    for clause in clauses:
        for part in clause["page_parts"]:
            body = part["text"]
            start = 0
            while start < len(body):
                piece = body[start : start + max_chars]
                if piece.strip():
                    chunks.append(
                        {
                            "chunk_index": len(chunks),
                            "clause_no": clause["clause_no"],
                            "clause_title": clause["title"],
                            "page": part["page"],
                            "lang": lang,
                            "chunk_text": piece,
                            "char_start": part["char_start"] + start,
                            "char_end": part["char_start"] + start + len(piece),
                            "clause_page_span": [clause["page_start"], clause["page_end"]],
                        }
                    )
                if start + max_chars >= len(body):
                    break
                start += max_chars - overlap
    return chunks


def build_payload(pdf_path: Path, max_chars: int, overlap: int) -> dict:
    pages = extract_pages(pdf_path)
    lang = detect_language([ln for pg in pages for ln in pg["text"].split("\n")])
    full_text, clauses = segment_clauses(pages, lang)
    chunks = build_chunks(clauses, lang, max_chars, overlap)

    routes: dict[str, int] = {}
    for pg in pages:
        routes[pg["text_source"]] = routes.get(pg["text_source"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "document": {
            "file_name": pdf_path.name,
            "file_hash": sha256_of(pdf_path),
            "mime_type": "application/pdf",
            "page_count": len(pages),
            "language": lang,
            "text_source_summary": routes,
        },
        "pages": [
            {
                "page": pg["page"],
                "text_source": pg["text_source"],
                "signals": pg["signals"],
                "tables": pg["tables"],
                "text": pg["text"],
            }
            for pg in pages
        ],
        "clauses": clauses,
        "chunks": chunks,
        "full_text": full_text,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--max-chars", type=int, default=1200, help="청크 최대 길이")
    ap.add_argument("--overlap", type=int, default=150, help="청크 겹침 길이")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for pdf in args.pdfs:
        if not pdf.exists():
            print(f"건너뜀 (없음): {pdf}", file=sys.stderr)
            continue
        payload = build_payload(pdf, args.max_chars, args.overlap)
        dest = args.out / f"{pdf.stem}.parse.json"
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        doc = payload["document"]
        print(
            f"{pdf.name}: lang={doc['language']} pages={doc['page_count']} "
            f"clauses={len(payload['clauses'])} chunks={len(payload['chunks'])} "
            f"routes={doc['text_source_summary']} -> {dest}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
