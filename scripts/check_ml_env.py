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
    head("OCR (선택 — 아직 설치 전이어도 정상)")
    pv = ver("paddlepaddle-gpu") or ver("paddlepaddle")
    if pv is None:
        print(f"{WARN} paddlepaddle 미설치 — 스캔본 경로는 아직 못 돈다.")
        return
    print(f"{OK} paddlepaddle {pv}  /  paddleocr {ver('paddleocr')}")
    try:
        import paddle

        paddle.utils.run_check()
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} paddle GPU 점검 실패: {type(e).__name__}: {e}")
        failures.append("paddle GPU 점검 실패")


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
