"""ML 실행 환경 진단.

    python scripts/check_ml_env.py

설치가 성공했다는 것과 이 GPU에서 실제로 돈다는 것은 다르다. 개발 GPU가
RTX 5050(Blackwell, sm_120)이라 커널이 빠진 CUDA 빌드를 깔면 import 와
`torch.cuda.is_available()` 까지는 멀쩡히 통과하고 첫 연산에서 죽는다.
그래서 여기서는 임포트가 아니라 **실제 연산**까지 시켜 본다.
"""

from __future__ import annotations

import importlib.metadata as md
import sys

OK, BAD, WARN = "[OK]", "[!!]", "[--]"
failures: list[str] = []


def ver(pkg: str) -> str | None:
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return None


def head(title: str) -> None:
    print(f"\n=== {title} ===")


def check_python() -> None:
    head("Python")
    major, minor = sys.version_info[:2]
    mark = OK if (major, minor) == (3, 12) else WARN
    print(f"{mark} {sys.version.split()[0]}  (CI/Dockerfile 기준: 3.12)")


def check_torch() -> None:
    head("torch / CUDA")
    v = ver("torch")
    if v is None:
        print(f"{BAD} torch 미설치")
        failures.append("torch 미설치")
        return
    import torch

    print(f"{OK} torch {v}  (빌드 CUDA {torch.version.cuda})")

    if not torch.cuda.is_available():
        print(f"{WARN} CUDA 사용 불가 — CPU로 돌게 된다. 임베딩이 크게 느려진다.")
        failures.append("CUDA 사용 불가")
        return

    name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    sm = f"sm_{cap[0]}{cap[1]}"
    total = torch.cuda.get_device_properties(0).total_memory / 2**30
    print(f"{OK} {name}  {sm}  VRAM {total:.1f}GB")

    # 빌드에 이 아키텍처 커널이 실제로 들어 있는지.
    arch = torch.cuda.get_arch_list()
    print(f"     빌드 포함 아키텍처: {' '.join(arch)}")
    if sm not in arch:
        print(f"{BAD} 이 빌드에는 {sm} 커널이 없다. CUDA 라인을 올려야 한다.")
        failures.append(f"{sm} 커널 없음")

    # 실행이 진짜 증거다.
    try:
        a = torch.randn(512, 512, device="cuda")
        r = float((a @ a).sum())
        assert r == r  # NaN 방어
        torch.cuda.synchronize()
        print(f"{OK} GPU 행렬곱 실행 성공")
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} GPU 연산 실패: {type(e).__name__}: {e}")
        failures.append("GPU 연산 실패")


def check_embedding() -> None:
    head("임베딩 (multilingual-e5-large)")
    v = ver("sentence-transformers")
    if v is None:
        print(f"{BAD} sentence-transformers 미설치")
        failures.append("sentence-transformers 미설치")
        return
    print(f"{OK} sentence-transformers {v}  /  transformers {ver('transformers')}")

    from sentence_transformers import SentenceTransformer

    try:
        m = SentenceTransformer("intfloat/multilingual-e5-large")
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} 모델 로딩 실패: {type(e).__name__}: {e}")
        failures.append("e5-large 로딩 실패")
        return

    dev = str(m.device)
    print(f"{OK} 모델 로딩  device={dev}  max_seq_length={m.max_seq_length}")
    if dev.startswith("cpu"):
        print(f"{WARN} CPU에 올라갔다. GPU를 기대했다면 위 CUDA 항목을 먼저 본다.")

    # e5는 접두어를 요구한다. 접두어를 빼면 품질이 눈에 띄게 떨어진다.
    vecs = m.encode(
        ["passage: 이용지역은 대한민국으로 한다.", "query: 이용지역"],
        normalize_embeddings=True,
    )
    dim = len(vecs[0])
    mark = OK if dim == 1024 else BAD
    print(f"{mark} 출력 차원 {dim}  (pgvector 컬럼 기준 1024)")
    if dim != 1024:
        failures.append(f"임베딩 차원 {dim}")

    norm = float(sum(x * x for x in vecs[0])) ** 0.5
    print(f"{OK} L2 정규화 확인  ||v|| = {norm:.4f}")


def check_tokenizer_fit() -> None:
    """실제 청크가 모델 입력 한계를 넘는지. 넘으면 조용히 잘린다."""
    head("청크 길이 vs 모델 입력 한계")
    import glob
    import json
    from pathlib import Path

    files = sorted(glob.glob("docs/handoff/samples/*.parse.json"))
    if not files:
        print(f"{WARN} 샘플 parse.json 이 없어 건너뛴다.")
        return
    if ver("transformers") is None:
        print(f"{WARN} transformers 미설치로 건너뛴다.")
        return

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained("intfloat/multilingual-e5-large")
    limit = 512
    over: list[tuple[str, str, int, int]] = []
    total = 0
    for f in files:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for c in d["chunks"]:
            total += 1
            n = len(tok.encode(f"passage: {c['chunk_text']}"))
            if n > limit:
                over.append((d["document"]["file_name"], c["chunk_id"], len(c["chunk_text"]), n))

    if not over:
        print(f"{OK} 청크 {total}개 모두 {limit} 토큰 이내")
        return
    print(f"{BAD} 청크 {total}개 중 {len(over)}개가 {limit} 토큰 초과 — 조용히 잘린다")
    for fn, cid, chars, n in sorted(over, key=lambda x: -x[3])[:8]:
        print(f"     {fn}  {cid}  {chars}자 -> {n}토큰")
    failures.append(f"{len(over)}개 청크가 입력 한계 초과")


def check_ocr() -> None:
    """OCR(PaddleOCR)은 의도적으로 CPU 전용이다.

    처음엔 paddlepaddle-gpu로 시도했다. sm_120(Blackwell) 자체는 문제없었다
    — get_device_capability()가 (12, 0)을 정확히 보고했고 GPU 행렬곱도
    성공했다. 문제는 torch와 **같은 프로세스**에 있을 때였다. 두 프레임워크가
    각자 cuDNN 9.x를 따로 번들해서 같은 이름의 DLL을 갖는데, Windows는 먼저
    로드된 쪽을 재사용하려다 심볼을 못 찾고 죽는다. 실제로 양방향 다
    재현했다(torch->paddle, paddle->torch 순서 모두 실패).

    임베딩(torch)이 모든 청크를 타는 핫패스라 GPU를 지켰다. OCR은 스캔
    페이지에만 도는 드문 경로라 CPU로 내려서 충돌을 없앴다. 그래서 여기서는
    paddle의 GPU 여부를 확인하지 않는다 — CPU인 게 의도된 상태다.
    """
    head("OCR (PaddleOCR — 의도적으로 CPU 전용, 아래 함수 docstring 참조)")
    pv = ver("paddlepaddle")
    if ver("paddlepaddle-gpu"):
        print(
            f"{BAD} paddlepaddle-gpu가 설치돼 있다 — torch와 한 프로세스에서 "
            f"cuDNN 심볼 충돌로 죽는다(실측 확인됨). paddlepaddle(CPU)로 교체할 것."
        )
        failures.append("paddlepaddle-gpu 설치됨 (torch와 충돌)")
        return
    if pv is None:
        print(f"{WARN} paddlepaddle 미설치 — 스캔본 경로는 아직 못 돈다.")
        return
    print(f"{OK} paddlepaddle {pv} (CPU)  /  paddleocr {ver('paddleocr')}")

    # torch를 먼저 로드해서 실제 서비스 프로세스 순서를 흉내낸다. 여기서
    # paddle import가 죽으면 GPU 빌드가 다시 섞여 들어왔다는 신호다.
    if ver("torch"):
        import torch  # noqa: F401
    import paddle

    print(f"     compiled with CUDA: {paddle.device.is_compiled_with_cuda()}")
    if paddle.device.is_compiled_with_cuda():
        print(f"{WARN} CUDA 포함 빌드다 — CPU 전용(paddlepaddle)이어야 한다.")

    if ver("paddleocr") is None:
        print(f"{WARN} paddleocr 미설치 — paddlepaddle만으로는 OCR을 못 돌린다.")
        return

    # 실제 텍스트 인식까지 — 합성 이미지 한 장으로 검증한다.
    #
    # mkldnn(oneDNN CPU 가속)을 켠 쪽을 먼저 시도한다. 이게 정상 경로다.
    # 개발 PC(Intel Core Ultra 7 255H)에서는 이걸 켜면 paddle 3.3.1의 PIR
    # 컴파일러가 특정 연산자 속성 변환을 못 다뤄 예외가 났다. oneDNN은 CPU
    # 명령어 세트(AVX2/AVX-512/AVX-VNNI 등)별로 다른 코드 경로를 타므로,
    # 이 버그가 그 CPU 세대에만 있고 다른 CPU에서는 없을 가능성이 있다 —
    # 그래서 여기서 실제로 먼저 켜서 확인하고, 안 되면 꺼서 재시도한다.
    # 결과가 "켜짐"이면 app/pipeline/ocr.py를 쓸 때
    # `MINDEX_OCR_MKLDNN=1`을 환경변수로 켜 두면 이 환경에서 더 빠르게 돈다.
    import numpy as np
    from paddleocr import PaddleOCR
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 100), "white")
    ImageDraw.Draw(img).text((10, 30), "HELLO 123", fill="black")

    def _try_ocr(mkldnn: bool) -> list[str] | None:
        engine = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=mkldnn,
        )
        result = engine.predict(np.array(img))
        return result[0].get("rec_texts", []) if result else []

    try:
        texts = _try_ocr(mkldnn=True)
        print(f"{OK} mkldnn 켜짐(최적화) — OCR 인식 성공: {texts}")
        print(
            "     이 환경에서는 켜도 된다. app/pipeline/ocr.py 사용 시 "
            "MINDEX_OCR_MKLDNN=1 을 환경변수로 설정할 것."
        )
    except Exception as e:  # noqa: BLE001
        print(f"{WARN} mkldnn 켜면 실패: {type(e).__name__}: {e}")
        print("     개발 PC(Intel Core Ultra 7 255H)와 같은 버그로 보인다. 꺼서 재시도한다.")
        try:
            texts = _try_ocr(mkldnn=False)
            if texts:
                print(f"{OK} mkldnn 끄면 OCR 인식 성공: {texts}")
            else:
                print(f"{WARN} mkldnn을 꺼도 아무 텍스트도 인식하지 못했다")
        except Exception as e2:  # noqa: BLE001
            print(f"{BAD} mkldnn을 꺼도 OCR 실행 실패: {type(e2).__name__}: {e2}")
            failures.append("paddleocr 실행 실패 (mkldnn on/off 둘 다)")


def check_pdf() -> None:
    head("PDF (설치 완료 상태여야 함)")
    for pkg in ("pdfplumber", "pypdfium2", "pillow", "numpy"):
        v = ver(pkg)
        print(f"{OK if v else BAD} {pkg} {v or '미설치'}")
        if not v:
            failures.append(f"{pkg} 미설치")
    if ver("pymupdf") or ver("fitz"):
        print(f"{BAD} PyMuPDF 발견 — AGPL이라 이 프로젝트에서 금지다.")
        failures.append("PyMuPDF 설치됨(AGPL)")


def main() -> int:
    check_python()
    check_pdf()
    check_torch()
    check_embedding()
    check_tokenizer_fit()
    check_ocr()

    head("결과")
    if failures:
        print(f"{BAD} 문제 {len(failures)}건")
        for f in failures:
            print(f"     - {f}")
        return 1
    print(f"{OK} 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
