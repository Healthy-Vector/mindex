"""스캔본 페이지 OCR — PaddleOCR.

## 과거 크래시 (해결됨, 2026-08-24)

`rasterize_page()` 가 `np.asarray()` 로 pdfium 네이티브 버퍼의 뷰를 반환하면서
반환 직전에 그 버퍼를 해제하고 있었다. 호출자가 해제된 메모리를 PaddleOCR에
넘겨 프로세스가 죽었다. `np.array()` 복사로 고쳤다(같은 함수의 주석 참조).

네이티브 크래시가 비결정적으로 보이면 환경보다 **자기 코드의 메모리 소유권**을
먼저 볼 것 — `np.asarray`(뷰)와 `np.array`(복사)의 차이가 이런 결과를 만든다.

## 지연 import

`paddleocr`·`paddlepaddle`는 `requirements-ml.txt`에만 있다. CI에는 없으므로
이 모듈을 import하는 것만으로 실패하면 안 된다. `app.pipeline.embed`와 같은
패턴 — 무거운 import는 함수 안에 두고, `is_available()`로 존재 여부만 싸게
확인한다.

## 왜 GPU가 아니라 CPU인가 — torch와 한 프로세스에서 못 산다

처음엔 `paddlepaddle-gpu`(cu130)로 시작했다. sm_120(Blackwell) 자체는 문제가
없었다 — `paddle.device.cuda.get_device_capability(0)`이 `(12, 0)`을 정확히
보고했고 GPU 행렬곱도 성공했다. 문제는 그 다음이었다.

**torch를 먼저 import하고 paddle을 import하면(또는 그 반대 순서로) 나중에
import되는 쪽이 죽는다.** 실제로 두 방향 다 재현해서 확인했다.

    import torch  →  import paddle   : paddle import 시점에 실패
    import paddle →  import torch    : torch import 시점에 실패

    OSError: [WinError 127] The specified procedure could not be found.
    Error loading ".../nvidia/cudnn/bin/cudnn_cnn64_9.dll" or one of its
    dependencies.

원인은 두 프레임워크가 **각자 cuDNN 9.x를 별도로 번들**한다는 것이다. torch는
`torch/lib/`에, paddle은 pip 패키지 `nvidia-cudnn-cu13`을 통해
`site-packages/nvidia/cudnn/bin/`에 각각 `cudnn64_9.dll` 등 같은 이름의
DLL을 갖고 있다. Windows는 같은 파일명의 DLL이 프로세스에 이미 로드돼
있으면 새로 로드하지 않고 기존 것을 재사용하는데, 두 회사가 빌드한 cuDNN
9.x는 이름은 같아도 내부 구현이 달라 서로의 의존 심볼을 못 찾는다.

**임베딩(torch)이 모든 청크를 타는 핫패스이므로 GPU를 유지해야 한다.**
반면 **OCR(paddle)은 스캔 페이지에만 도는 드문 경로**다 — 이 프로젝트
합성데이터 446페이지 전부가 digital-born이라 실사용에서도 소수 경로일
가능성이 높다. 그래서 paddle을 CPU 전용(`paddlepaddle`, `-gpu` 아님)으로
바꿔 충돌 자체를 없앴다. CPU 빌드는 cuDNN을 전혀 안 건드리므로 torch와
같은 프로세스에서 아무 순서로 import해도 문제없다(실제로 재검증함).

## CPU에서 mkldnn을 껐다 — 단, 이 CPU에서만 그럴 수 있다

CPU로 바꾼 뒤 처음 돌렸을 때 이번엔 다른 오류가 났다.

    NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute
    not support [pir::ArrayAttribute<pir::DoubleAttribute>]

paddle 3.3.1의 새 PIR(Program Intermediate Representation) 컴파일러가
oneDNN(MKL-DNN) 가속 경로의 특정 연산자 속성 변환을 못 다루는 것으로
보인다. `enable_mkldnn=False`로 끄면 정상 동작한다 — 합성 이미지로 실제
텍스트 인식까지 확인했다.

**이 버그를 재현한 CPU는 Intel Core Ultra 7 255H(2026년 기준 최신 세대,
Arrow Lake) 하나뿐이다.** oneDNN은 CPU가 지원하는 명령어 세트(AVX2·
AVX-512·AVX-VNNI 등)에 따라 서로 다른 커널 코드 경로를 타므로, **이
PIR-변환 버그가 이 CPU 세대의 특정 코드 경로에서만 발생하고 더 오래된
CPU에서는 안 날 가능성이 있다.** 다른 팀원 PC에서 재현되는지 아직
확인하지 못했다.

mkldnn은 커봤을 때 CPU 추론이 유의미하게 빨라지는 최적화라서, 꺼진 채로
그냥 두면 안 그래도 느린 CPU OCR이 필요 이상으로 느려진다. 그래서 끄는
쪽을 코드에 박아 넣지 않고 **환경변수로 재시도할 수 있게** 했다 —
`MINDEX_OCR_MKLDNN=1`로 켜고 `scripts/check_ml_env.py`를 돌려서 이
환경에서도 같은 오류가 나는지 먼저 확인해 보기 바란다. 안 나면 그 값을
기본으로 켜 두는 게 맞다.

## 언어 모델을 둘만 둔다

PaddleOCR 3.x 기본 모델(PP-OCRv6, `lang` 미지정)은 **영어·일본어·중국어를
포함한 50개 언어를 한 모델로 처리한다.** 반면 **한국어는 이 통합 모델에
없고** 별도 `lang="korean"` 모델(`korean_PP-OCRv5_mobile_rec`)이 필요하다.

그래서 이 프로젝트가 다루는 세 언어(ko/ja/en)에 모델이 두 개만 있으면 된다.

    한국어  -> PaddleOCR(lang="korean")
    일본어·영어 -> PaddleOCR()  (기본, lang 지정 안 함)

## 언어를 모를 때 — 신뢰도가 아니라 회수한 글자 수로 판정한다

스캔 페이지에는 텍스트 레이어가 없어 어떤 언어인지 알 방법이 없다. 문서 안에
디지털 페이지가 하나라도 있으면 거기서 언어를 판정해 넘겨주면 되지만(``lang``
인자), **문서 전체가 스캔본이면 사전 정보가 없다.**

처음엔 평균 신뢰도(`rec_scores`)가 낮으면 재시도하는 방식을 시도했는데,
실제 한국어 스캔본으로 검증하다가 이게 틀렸다는 걸 확인했다.

    기본 모델(en/ja/zh)  score 0.71  "Status\nKO-2025-001-002\n2025 \n..."
    한국어 모델          score 0.97  "겨울의 신호... 루미나 픽처스 주식회사..."

기본 모델이 한글 영역을 거의 인식하지 못했는데도(숫자·영단어 몇 개만 건짐)
신뢰도는 0.71로 임계값(0.5)을 넘겼다. **신뢰도는 "인식한 것에 대한 확신"이지
"얼마나 많이 인식했는지"가 아니다.** 잘못된 언어 모델도 몇 글자만 건지면
그 몇 글자에는 확신을 가질 수 있다.

그래서 **언어 힌트가 없으면 두 모델을 항상 둘 다 돌리고, 회수한 글자
수(공백 제외)가 더 많은 쪽을 취한다.** 신뢰도 임계값을 추측하는 대신
직접적인 완전성 지표로 바꿨다. 비용은 2배지만, 언어 힌트가 없는 경우
자체가 이미 드문 경로(문서 전체가 스캔본) 안의 드문 경우(문서 전체가
스캔본**이면서** 힌트를 못 구함)라 감수할 만하다.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading

# numpy는 requirements-ml.txt가 아니라 requirements.txt의 pgvector가 끌어온다
# (pgvector 0.3.* -> numpy). CI에도 항상 있으므로 최상위 import로 둬도 된다 —
# paddleocr 쪽만 지연 import하면 이 모듈 자체는 CI에서 문제없이 import된다.
import numpy as np

logger = logging.getLogger(__name__)

#: mkldnn(oneDNN CPU 가속)을 켤지. 기본은 끔(Intel Core Ultra 7 255H에서
#: 재현된 버그 회피, 위 모듈 docstring 참조). 다른 CPU에서는 문제없을 수
#: 있으니 `MINDEX_OCR_MKLDNN=1`로 켜서 `scripts/check_ml_env.py`로 먼저
#: 확인해 보고, 안 나면 이 값을 기본으로 바꾸는 걸 권한다.
_ENABLE_MKLDNN = os.environ.get("MINDEX_OCR_MKLDNN", "0") == "1"

#: 래스터화 결과의 긴 변 상한(픽셀). 이보다 커지면 dpi를 낮춰서 맞춘다.
#:
#: 사용자가 올리는 PDF의 종이 크기는 우리가 정하지 않는다. A0 도면이나,
#: 이미지를 dpi 정보 없이 감싼 PDF(뷰어가 72dpi로 가정해 종이가 몇 배로
#: 커진다)가 들어오면 200dpi 렌더링이 수천~수만 픽셀이 되어 메모리와 처리
#: 시간이 급증한다. PaddleOCR도 검출 단계에서 어차피 4000으로 리사이즈하므로
#: 그보다 큰 이미지를 만들어 넘길 이유가 없다.
#:
#: 이 값은 **크래시 회피용이 아니다.** use-after-free 를 고친 뒤 A4 기준
#: 200/240/260/280/300dpi(1653x2339 ~ 2480x3509)를 각 2회씩 돌려 10/10 통과를
#: 확인했다. 이미지 크기와 안정성 사이에 상관이 없다는 뜻이므로, 여기서는
#: 메모리·시간만 보고 정하면 된다.
MAX_RASTER_SIDE = 4000

_engines: dict[str, object] = {}
_lock = threading.Lock()


def is_available() -> bool:
    """OCR을 쓸 수 있는 환경인가. 모듈을 실제로 import하지 않고 확인한다."""
    return importlib.util.find_spec("paddleocr") is not None


def _get_engine(lang: str):
    """언어별 PaddleOCR 싱글턴. `lang`은 `"korean"` 또는 `"default"`."""
    if lang in _engines:
        return _engines[lang]

    with _lock:
        if lang in _engines:
            return _engines[lang]

        from paddleocr import PaddleOCR

        kwargs = {} if lang == "default" else {"lang": lang}
        engine = PaddleOCR(
            # 문서 방향·기울기 보정 모델은 끈다. 계약서는 정자세로 스캔되는
            # 표준 문서라 대부분 불필요하고, 켜면 모델 로딩이 하나 더 늘어난다.
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            # 기본 꺼짐 — 위 _ENABLE_MKLDNN 참조. MINDEX_OCR_MKLDNN=1로 켜서
            # 이 환경에서도 PIR 변환 오류가 나는지 재시도해 볼 수 있다.
            enable_mkldnn=_ENABLE_MKLDNN,
            **kwargs,
        )
        _engines[lang] = engine
        logger.info("PaddleOCR 엔진 로딩: lang=%s", lang)
        return engine


def _reading_order(boxes: np.ndarray) -> list[int]:
    """검출 박스를 자연스러운 읽기 순서(위->아래, 좌->우)로 정렬한 인덱스.

    계약서는 단일 컬럼 산문이라 이 단순한 라인 밴드 방식으로 충분하다.
    y 범위가 겹치는 박스를 같은 줄로 묶고, 줄은 위에서 아래로, 줄 안에서는
    왼쪽에서 오른쪽으로 정렬한다.
    """
    if len(boxes) == 0:
        return []

    # [x_min, y_min, x_max, y_max]
    heights = boxes[:, 3] - boxes[:, 1]
    order_by_y = np.argsort(boxes[:, 1])

    lines: list[list[int]] = []
    for i in order_by_y:
        y0, y1 = boxes[i, 1], boxes[i, 3]
        placed = False
        for line in lines:
            ly0, ly1 = boxes[line[0], 1], boxes[line[0], 3]
            overlap = min(y1, ly1) - max(y0, ly0)
            if overlap > 0.5 * min(y1 - y0, ly1 - ly0, heights[i]):
                line.append(i)
                placed = True
                break
        if not placed:
            lines.append([i])

    lines.sort(key=lambda line: min(boxes[i, 1] for i in line))
    order: list[int] = []
    for line in lines:
        order.extend(sorted(line, key=lambda i: boxes[i, 0]))
    return order


def _run_once(image: np.ndarray, lang: str) -> tuple[str, float]:
    """엔진 하나로 OCR. (읽기순서로 이어붙인 텍스트, 평균 신뢰도)."""
    engine = _get_engine(lang)
    results = engine.predict(image)
    if not results:
        return "", 0.0

    res = results[0]
    texts = res.get("rec_texts", [])
    scores = res.get("rec_scores", [])
    boxes = res.get("rec_boxes")

    if not texts:
        return "", 0.0

    if boxes is not None and len(boxes) == len(texts):
        order = _reading_order(np.asarray(boxes))
    else:
        order = list(range(len(texts)))

    text = "\n".join(texts[i] for i in order if texts[i].strip())
    mean_score = float(np.mean(scores)) if len(scores) else 0.0
    return text, mean_score


def rasterize_page(pdf_bytes: bytes, page_index: int, *, dpi: int = 200) -> np.ndarray:
    """PDF의 한 페이지를 RGB ndarray로 렌더링한다.

    파일 경로를 쓰지 않는다. 프로젝트 경로에 한글이 섞여 있어도
    (`d:/오픈소스 대회 자료/...`) 영향을 받지 않는다.

    200dpi로 고정한 이유는 실측 근거가 아니라 업계 통상값이다 — 문서 스캐너
    기본값이 대개 200~300dpi다. 실제 이 프로젝트의 합성데이터는 전부
    digital-born이라 적정 DPI를 실측할 스캔 표본이 없다.

    긴 변은 `MAX_RASTER_SIDE`로 제한한다 — A4는 여유가 있지만 사용자가 올리는
    종이 크기는 우리가 정하지 않는다. 근거는 그 상수의 주석 참조.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        page = pdf[page_index]
        try:
            scale = dpi / 72
            # 종이가 크면 scale 을 낮춰 픽셀 상한을 지킨다. dpi 를 깎는
            # 셈이라 인식률이 조금 떨어지지만, PaddleOCR 이 어차피 검출 단계에서
            # 4000 으로 리사이즈하므로 실질 손해는 크지 않다.
            longest = max(page.get_width(), page.get_height()) * scale
            if longest > MAX_RASTER_SIDE:
                scale *= MAX_RASTER_SIDE / longest
                logger.warning(
                    "페이지가 너무 큽니다(%.0fpx). %ddpi -> %ddpi 로 낮춰 렌더링합니다.",
                    longest,
                    dpi,
                    int(scale * 72),
                )
            bitmap = page.render(scale=scale)
            # np.array(...) 로 **반드시 복사**한다. np.asarray 는 pdfium 이
            # 할당한 네이티브 버퍼를 가리키는 뷰(OWNDATA=False)를 돌려주는데,
            # 이 함수는 바로 아래에서 page.close()/pdf.close() 로 그 버퍼를
            # 해제한다. 뷰를 반환하면 호출자가 해제된 메모리를 읽게 되고,
            # PaddleOCR 이 그걸 만지는 순간 프로세스가 죽는다(실제로 겪었다).
            return np.array(bitmap.to_pil().convert("RGB"))
        finally:
            page.close()
    finally:
        pdf.close()


def _text_len(text: str) -> int:
    """공백을 뺀 글자 수. 완전성 지표로 쓴다 — 신뢰도보다 이게 낫다는 근거는
    모듈 docstring의 실측 사례를 참조."""
    return len("".join(text.split()))


def run_ocr(image: np.ndarray, *, lang_hint: str | None = None) -> tuple[str, str]:
    """이미지 한 장을 OCR한다. (텍스트, 실제 사용한 언어) 를 반환한다.

    `lang_hint`가 `"ko"`면 한국어 모델만 쓴다. 그 밖의 값이면 기본 모델
    (en/ja/zh 통합)만 쓴다 — 이 프로젝트 언어 셋에서 ko만 별도 모델이
    필요하기 때문이다.

    `lang_hint`가 없으면(문서 전체가 스캔본이라 언어를 알 길이 없는 경우)
    **두 모델을 모두 돌려 회수한 글자 수가 더 많은 쪽을 취한다.**
    """
    if lang_hint == "ko":
        text, _ = _run_once(image, "korean")
        return text, "ko"
    if lang_hint is not None:
        text, _ = _run_once(image, "default")
        return text, "auto"

    default_text, _ = _run_once(image, "default")
    korean_text, _ = _run_once(image, "korean")
    if _text_len(korean_text) > _text_len(default_text):
        logger.info(
            "OCR 언어 판정: default(%d자) < korean(%d자) — korean 채택",
            _text_len(default_text),
            _text_len(korean_text),
        )
        return korean_text, "ko"
    return default_text, "auto"
