# ruff: noqa: E402 — 벤치마크 스크립트다. 실행 단계를 나누어 보여주려고
# 무거운 import를 해당 단계 위치에 둔다. 이건 의도된 배치다.
"""
01. 샘플 생성 — 합성 계약서 PDF + 가짜 스캔본
실행 위치: [맥]

시나리오 KO-N01 기반: C001(겨울의 신호) 일본 SVOD 독점, 2026.01~2027.12

3가지를 만든다:
  1) 디지털 PDF        — 텍스트 레이어 있음 (실무 계약서 대부분)
  2) 스캔본 PNG        — 깨끗한 인쇄물을 200dpi 로 스캔한 수준
  3) 텍스트 레이어 추출 — OCR 우회 경로가 동작하는지 확인

원문(ground_truth.txt)을 알고 있으므로 OCR 정확도를 정량 측정할 수 있다.
"""

import random
from pathlib import Path

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

# ── 계약서 원문 (Ground Truth) ─────────────────────────────
# KO-N01: 제작사 → Bridge Contents, C001 일본 SVOD 독점
CONTRACT_TEXT = """콘텐츠 이용허락 계약서

한빛스튜디오 주식회사(이하 "갑"이라 한다)와 Bridge Contents(이하 "을"이라 한다)는
드라마 「겨울의 신호」(이하 "본 콘텐츠"라 한다)의 이용허락에 관하여
다음과 같이 계약을 체결한다.

제1조 (계약의 목적)
본 계약은 갑이 보유한 본 콘텐츠의 전송권을 을에게 이용허락함에 있어
필요한 제반 사항을 정함을 목적으로 한다.

제2조 (이용허락의 범위)
1. 대상 콘텐츠: 겨울의 신호 시즌1 전 회차
2. 허락 지역: 일본
3. 이용 형태: 구독형 주문형 비디오(SVOD) 서비스
4. 독점 여부: 독점

제3조 (계약 기간)
본 계약에 따른 이용허락 기간은 2026년 1월 1일부터
2027년 12월 31일까지로 한다.

제4조 (이용료)
을은 갑에게 이용료로 금 삼억원(₩300,000,000)을 지급한다.

제5조 (재허락의 금지)
을은 갑의 사전 서면 동의 없이 본 계약상 권리를
제3자에게 재허락할 수 없다.

제6조 (준거법)
본 계약은 대한민국 법률에 따라 해석된다.

2025년 12월 15일

갑: 한빛스튜디오 주식회사
을: Bridge Contents"""

(OUT / "ground_truth.txt").write_text(CONTRACT_TEXT, encoding="utf-8")

# ── 1) 디지털 PDF 생성 (reportlab, BSD 라이선스) ─────────────
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ── 한글 폰트 ─────────────────────────────────────────────────
# ⚠️ 오픈소스 대회 제출물이므로 폰트도 재배포 가능한 것을 써야 한다.
#    AppleGothic·AppleSDGothicNeo 는 Apple 시스템 폰트라 재배포 불가 →
#    저장소에 넣을 수 없고, 심사위원이 리눅스에서 돌리면 실행조차 안 된다.
#
#    권장: Noto Sans KR (SIL Open Font License 1.1) 을 fonts/ 에 넣는다.
#          설치 방법은 fonts/README.md 참조.
BUNDLED = Path(__file__).parent / "fonts"
FONT_CANDIDATES = [
    # ① 저장소에 포함된 OFL 폰트 (권장)
    (BUNDLED / "NotoSansKR-Regular.ttf", "OFL-1.1", True),
    (BUNDLED / "NanumGothic.ttf",         "OFL-1.1", True),
    # ② 시스템에 설치된 OFL 폰트
    (Path("/Library/Fonts/NanumGothic.ttf"),                     "OFL-1.1", True),
    (Path("/opt/homebrew/share/fonts/NotoSansKR-Regular.ttf"),   "OFL-1.1", True),
    (Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),    "OFL-1.1", True),
    # ③ 최후 수단 — 동작은 하지만 재배포 불가
    (Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"), "Apple 독점", False),
]

font_path = license_name = None
redistributable = True
for cand, lic, ok in FONT_CANDIDATES:
    if cand.exists():
        font_path, license_name, redistributable = str(cand), lic, ok
        break

if not font_path:
    raise SystemExit(
        "한글 폰트를 찾지 못했습니다.\n"
        "  → ocr_embedding_test/fonts/README.md 를 보고 Noto Sans KR 을 내려받으세요."
    )

pdfmetrics.registerFont(TTFont("KFont", font_path))
print(f"[폰트] {Path(font_path).name}  ({license_name})")
if not redistributable:
    print("  ⚠️ 이 폰트는 재배포할 수 없습니다. 제출 전 OFL 폰트로 교체하세요.")
    print("     → fonts/README.md 참조")

pdf_path = OUT / "contract_digital.pdf"
c = canvas.Canvas(str(pdf_path), pagesize=A4)
w, h = A4
y = h - 60
for line in CONTRACT_TEXT.split("\n"):
    c.setFont("KFont", 16 if "계약서" in line and y > h - 80 else 11)
    c.drawString(60, y, line)
    y -= 22
    if y < 60:
        c.showPage()
        y = h - 60
c.save()
print(f"[1/2] 디지털 PDF 생성: {pdf_path}")

# ── 2) 스캔본 생성 (pypdfium2 렌더 + 최소 왜곡) ───────────────
#    pypdfium2 는 RFP 확정 스택이라 그대로 사용
#
#    ⚠️ 노이즈 정책 변경 (2026-08-19)
#    계약서는 법적 문서라 흐릿하게 인쇄되지 않는다. 팩스본·복사본이라도
#    원본은 깨끗한 인쇄물이다. 이전 버전의 가우시안 블러 0.6 + 소금·후추
#    노이즈 0.2% 는 현실에 없는 조건이었다.
#
#    현실적 조건만 남긴다:
#      - 200dpi 렌더 (사무실 복합기 기본값)
#      - 흑백화 (스캐너 grayscale 모드)
#      - ±0.5° 기울임 (급지 시 종이가 살짝 틀어지는 것 — 유일한 실제 왜곡)
#
#    → 즉, 이 테스트는 "깨끗한 인쇄물을 스캔한 것" 을 재현한다.
import pypdfium2 as pdfium

pdf = pdfium.PdfDocument(str(pdf_path))
random.seed(42)
for i, page in enumerate(pdf):
    img = page.render(scale=200 / 72).to_pil()   # 200dpi
    img = img.convert("L")                        # 스캐너 grayscale
    img = img.rotate(random.uniform(-0.5, 0.5),   # 급지 기울임
                     expand=False, fillcolor=255)
    out_img = OUT / f"contract_scan_p{i+1}.png"
    img.save(out_img)
    print(f"[2/3] 스캔본 생성: {out_img}")

# ── 3) 텍스트 레이어 추출 (OCR 우회 경로 확인) ─────────────────
#    실무 계약서 PDF 의 상당수는 Word 로 만들어 PDF 로 저장한 것이라
#    텍스트 레이어가 살아 있다. 이 경우 OCR 이 아예 필요 없다.
#    파싱 모듈(P3)은 반드시 이 분기를 먼저 태워야 한다.
textlayer = "\n".join(page.get_textpage().get_text_range() for page in pdf)
(OUT / "textlayer_extracted.txt").write_text(textlayer, encoding="utf-8")
has_layer = len(textlayer.strip()) > 100
print(f"[3/3] 텍스트 레이어: {'있음 → OCR 불필요' if has_layer else '없음 → OCR 필요'}"
      f" ({len(textlayer.strip())}자)")

print("\n완료. 다음: python3 02_ocr_compare.py")
