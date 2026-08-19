"""
02. OCR 후보 비교 — PaddleOCR vs Tesseract
실행 위치: [맥]

가짜 스캔본을 두 OCR에 넣고, 원문(ground_truth.txt)과 대조해
문자 정확도(CER: Character Error Rate)를 계산한다.
설치 안 된 엔진은 자동으로 건너뛴다.
"""

import re
import time
import difflib
from pathlib import Path

OUT = Path(__file__).parent / "out"
truth = (OUT / "ground_truth.txt").read_text(encoding="utf-8")
scans = sorted(OUT.glob("contract_scan_p*.png"))
if not scans:
    raise SystemExit("스캔본이 없습니다. 먼저 01_make_samples.py 를 실행하세요.")


def normalize(s: str) -> str:
    """공백·개행 차이는 OCR 품질과 무관하므로 제거 후 비교"""
    return re.sub(r"\s+", "", s)


def cer(ref: str, hyp: str) -> float:
    """문자 단위 오류율 (낮을수록 좋음). difflib 기반 근사."""
    ref, hyp = normalize(ref), normalize(hyp)
    matched = sum(b.size for b in difflib.SequenceMatcher(None, ref, hyp).get_matching_blocks())
    return 1 - matched / max(len(ref), 1)


# ── CORE 필드 보존율 — 이 프로젝트의 실질 지표 ─────────────────
# CER은 제목·장식 문자의 오류까지 똑같이 세지만, 충돌 판정에 쓰이는 것은
# 아래 필드들뿐이다. 제목이 깨져도 이 값들이 살아있으면 판정은 정상 동작한다.
CORE_FIELDS = {
    "content(콘텐츠)":   ["겨울의신호"],
    "territory(지역)":   ["일본"],
    "mode(이용형태)":     ["SVOD", "구독형주문형비디오"],   # 둘 중 하나만 살아도 정규화 가능
    "exclusivity(독점)":  ["독점"],
    "start(시작일)":      ["2026년1월1일"],
    "end(종료일)":        ["2027년12월31일"],
    "amount(금액)":       ["300,000,000", "삼억원"],
    "sublicense(재허락)": ["재허락"],
}


def field_score(hyp: str):
    """CORE 필드 보존율. 대안 표현 중 하나라도 잡히면 성공으로 본다."""
    h = normalize(hyp)
    detail = {k: any(normalize(v) in h for v in alts) for k, alts in CORE_FIELDS.items()}
    return sum(detail.values()) / len(detail), detail


results = {}

# ── PaddleOCR ──────────────────────────────────────────────
try:
    from paddleocr import PaddleOCR
    t0 = time.time()
    # 버전마다 생성자 인자가 달라 단계적으로 시도 (3.x 에서 show_log 제거됨)
    for kwargs in ({"lang": "korean"}, {"lang": "korean", "show_log": False}, {}):
        try:
            ocr = PaddleOCR(**kwargs)
            break
        except (TypeError, ValueError):
            continue
    texts = []
    for p in scans:
        if hasattr(ocr, "predict"):        # 3.x
            for r in ocr.predict(str(p)):
                texts += list(r["rec_texts"])
        else:                               # 2.x
            res = ocr.ocr(str(p), cls=False)
            texts += [line[1][0] for block in res if block for line in block]
    hyp = "\n".join(texts)
    results["PaddleOCR"] = {"cer": cer(truth, hyp), "sec": time.time() - t0, "text": hyp}
except ImportError:
    print("PaddleOCR 미설치 — 건너뜀  (pip install paddlepaddle paddleocr)")
except Exception as e:
    print(f"PaddleOCR 실패: {e}")

# ── Tesseract ──────────────────────────────────────────────
try:
    import pytesseract
    from PIL import Image
    t0 = time.time()
    hyp = "\n".join(
        pytesseract.image_to_string(Image.open(p), lang="kor+eng") for p in scans
    )
    results["Tesseract"] = {"cer": cer(truth, hyp), "sec": time.time() - t0, "text": hyp}
except ImportError:
    print("pytesseract 미설치 — 건너뜀  (brew install tesseract tesseract-lang && pip install pytesseract)")
except Exception as e:
    print(f"Tesseract 실패: {e}")

# ── 리포트 ─────────────────────────────────────────────────
if not results:
    raise SystemExit("실행된 OCR 엔진이 없습니다.")

for r in results.values():
    r["field"], r["detail"] = field_score(r["text"])

report = [
    "# OCR 비교 결과",
    "",
    "> **선택 기준은 CORE 필드 보존율입니다.** CER은 제목·장식 문자의 오류까지 동일하게 세므로",
    "> 계약서 판정 관점에서는 과소평가됩니다. 충돌 판정에 실제로 쓰이는 값이 살아남는지가 기준입니다.",
    "",
    "| 엔진 | **CORE 필드 보존율** | 문자 정확도 | CER | 소요(초) |",
    "|---|---|---|---|---|",
]
for name, r in sorted(results.items(), key=lambda x: -x[1]["field"]):
    report.append(
        f"| {name} | **{r['field']*100:.0f}%** | {(1-r['cer'])*100:.1f}% | {r['cer']:.4f} | {r['sec']:.1f} |"
    )
    (OUT / f"ocr_output_{name}.txt").write_text(r["text"], encoding="utf-8")

report += ["", "## CORE 필드 상세", "", "| 필드 | " + " | ".join(results) + " |",
           "|---" * (len(results) + 1) + "|"]
for f in CORE_FIELDS:
    report.append("| " + f + " | " + " | ".join("✅" if results[n]["detail"][f] else "❌" for n in results) + " |")

report += [
    "",
    "## 판정 기준",
    "",
    "| CORE 보존율 | 조치 |",
    "|---|---|",
    "| 100% | 그대로 사용 |",
    "| 87.5% (7/8) | 실패 필드가 정규화로 복구 가능한지 확인 (예: SVOD ↔ 구독형 주문형 비디오) |",
    "| 75% 이하 | 전처리 추가(해상도 상향·이진화) 또는 엔진 교체 |",
]

report_md = "\n".join(report)
(OUT / "ocr_report.md").write_text(report_md, encoding="utf-8")
print("\n" + report_md)
print(f"\n상세 출력: out/ocr_output_*.txt / 리포트: out/ocr_report.md")
print("다음: python3 03_embed_load.py")
