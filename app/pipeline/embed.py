"""임베딩 — intfloat/multilingual-e5-large (1024차원).

RFP SFR-005에서 확정된 모델이다. **로컬 구동**이 요건인데, 계약서에는 당사자
실명·법인등록번호·계약대가가 들어 있어서 외부 API로 보내려면 마스킹 파이프라인이
따로 필요하기 때문이다.

## 지연 import

`sentence_transformers`와 `torch`는 `requirements-ml.txt`에만 있다.
CI(ubuntu-latest)와 Dockerfile(python:3.12-slim)은 `requirements.txt`만 설치하므로
**이 모듈을 import하는 것만으로 실패하면 안 된다.** 그래서 무거운 import는 전부
함수 안에 둔다. 파이프라인은 임베딩 없이(어휘 회수만) 동작할 수 있어야 하고,
그래야 나머지 단계가 CI에서 검증된다.

## 모델 로딩 비용

실측 13.7초. 요청마다 로딩하면 처리시간의 대부분이 로딩이 된다.
프로세스당 1회 로딩하는 싱글턴으로 잡고, K8s에서는 readiness probe에 여유를 준다.

## fp16

실측(RTX 5050, 232청크): fp32 batch=32에서 29 chunk/s, fp16 batch=32에서 80 chunk/s.
**2.8배 빠르고 VRAM peak 3.5GB로 8GB 안에 들어간다.** CPU에서는 fp16이 오히려
느리거나 미지원이므로 CUDA일 때만 쓴다.
"""

from __future__ import annotations

import importlib.util
import logging
import threading

logger = logging.getLogger(__name__)

MODEL_NAME = "intfloat/multilingual-e5-large"
EMBEDDING_DIM = 1024
#: 실측상 이 크기에서 가장 빨랐다. 더 키우면 패딩 낭비로 오히려 느려진다.
DEFAULT_BATCH_SIZE = 32

_model = None
_lock = threading.Lock()


def is_available() -> bool:
    """임베딩을 쓸 수 있는 환경인가. 모듈을 실제로 import하지 않고 확인한다."""
    return importlib.util.find_spec("sentence_transformers") is not None


def get_model():
    """프로세스당 1회 로딩되는 싱글턴. 스레드 안전."""
    global _model
    if _model is not None:
        return _model

    with _lock:
        if _model is not None:  # 락 대기 중 다른 스레드가 채웠을 수 있다
            return _model

        import torch
        from sentence_transformers import SentenceTransformer

        # 실측 처리량 (232청크 / 80청크 기준)
        #   CUDA fp16   80 chunk/s   RTX 5050 Laptop, VRAM peak 3.5GB
        #   CUDA fp32   29 chunk/s
        #   CPU fp32    2.8 chunk/s  Intel Core Ultra 7 255H, 16 threads
        #
        # CPU가 CUDA fp16 대비 29배 느리다. 86건 전량(색인청크 1804개)이면
        # GPU 23초 vs CPU 11분이다. 배치 작업은 감당되지만 요청당 대기로는
        # 못 쓴다.
        kwargs: dict = {}
        if torch.cuda.is_available():
            # fp16은 CUDA에서만 쓴다. CPU에서는 오히려 느리거나 미지원이고,
            # MPS도 fp16 커널 지원이 연산마다 들쭉날쭉하다.
            kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
            device = f"CUDA fp16 ({torch.cuda.get_device_name(0)})"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            # Apple Silicon. sentence-transformers가 알아서 고르지만, 어디서
            # 도는지 로그로 남겨야 "왜 이렇게 느리지"를 추적할 수 있다.
            kwargs["device"] = "mps"
            device = "MPS fp32 (Apple Silicon)"
        else:
            device = f"CPU fp32 ({torch.get_num_threads()} threads)"

        logger.info("임베딩 모델 로딩: %s / %s", MODEL_NAME, device)
        if not torch.cuda.is_available():
            logger.warning(
                "가속기 없이 도는 경로다(%s). 실측 CPU 2.8 chunk/s — "
                "CUDA fp16 대비 약 29배 느리다.",
                device,
            )

        _model = SentenceTransformer(MODEL_NAME, **kwargs)
        return _model


def _encode(texts: list[str], prefix: str, batch_size: int) -> list[list[float]]:
    if not texts:
        return []
    model = get_model()
    vecs = model.encode(
        [f"{prefix}{t}" for t in texts],
        batch_size=batch_size,
        normalize_embeddings=True,
    )
    return [[round(float(x), 6) for x in v] for v in vecs]


def embed_passages(
    texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE
) -> list[list[float]]:
    """문서 쪽 임베딩.

    e5 계열은 `passage: ` 접두어를 요구한다. 빼면 학습된 벡터 공간과 어긋나
    검색 품질이 떨어진다. 질의 쪽은 `query: `를 쓴다.
    """
    return _encode(texts, "passage: ", batch_size)


def embed_queries(
    texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE
) -> list[list[float]]:
    return _encode(texts, "query: ", batch_size)


def attach_embeddings(chunks, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """청크에 벡터를 채운다. 색인 대상만 처리하고 채운 개수를 반환한다.

    색인 제외 청크(별지 제목 등)를 건너뛰는 이유는 비용이 아니라 품질이다.
    내용 없는 조각은 e5 벡터 공간에서 어떤 질의와도 어중간하게 가까워서
    상위를 차지하고 정답을 밀어낸다.
    """
    targets = [c for c in chunks if c.indexable]
    if not targets:
        return 0
    for chunk, vec in zip(
        targets, embed_passages([c.text for c in targets], batch_size), strict=True
    ):
        chunk.embedding = vec
    return len(targets)
