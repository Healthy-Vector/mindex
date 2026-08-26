# scripts/ocr_pipeline

Task1(OCR → 임베딩 → 회수) 파이프라인을 만들면서 쓴 스크립트들. 담당 **P3**.

본구현은 [`app/pipeline/`](../../app/pipeline/) 에 있다. 여기 있는 건 그걸
**진단·평가·산출물 생성**하는 도구다. 서비스 런타임에는 들어가지 않는다.

**전부 저장소 루트에서 실행한다.** 안에 있는 경로가 전부 루트 기준 상대경로다.

```bash
cd <repo root>
PYTHONPATH=. .venv/Scripts/python scripts/ocr_pipeline/<script>.py
```

---

## 무엇이 있나

| 스크립트 | 하는 일 | 언제 쓰나 |
|---|---|---|
| `check_ml_env.py` | 실행 환경 진단 | **새 PC 세팅 직후 제일 먼저** |
| `run_e2e.py` | **전건 end-to-end 실행** | **PR 전 · 파이프라인을 건드린 뒤** |
| `build_goldset.py` | **회수** 정답지 생성 (Task1) | 원본 Evidence가 바뀌었을 때 |
| `build_extraction_goldset.py` | **추출** 정답지 생성 (Task2) | `ground_truth.json` 이 바뀌었을 때 |
| `paraphrase.py` | held-out 집합 생성 | `eval_retrieval.py` 가 내부에서 호출 |
| `eval_retrieval.py` | 회수 품질 측정 | 청킹·스코어러를 건드린 뒤 |
| `make_handoff_samples.py` | Task2 인계 샘플 생성 | 규격이 바뀌었을 때 |

`run_e2e.py` 와 `eval_retrieval.py` 는 목적이 다르다. 전자는 **끝까지 도는가**
(규격 위반·예외·성능), 후자는 **얼마나 잘 찾는가**(정답지 대조)를 본다.

---

## 1. `check_ml_env.py` — 환경 진단

**import 통과를 성공으로 치지 않는다.** 실제로 GPU 커널이 도는지, 임베딩이
1024차원으로 정규화돼 나오는지까지 확인한다.

```bash
python scripts/ocr_pipeline/check_ml_env.py
```

보는 것:

- `torch.cuda.get_arch_list()` 에 `sm_120` 이 있는지 — RTX 5050(Blackwell)은
  cu128 이상 빌드가 아니면 설치는 되고 실행만 죽는다
- 실제 GPU 행렬곱
- 임베딩 차원 1024 · L2 정규화
- 샘플 청크가 512 토큰을 넘는지 (넘으면 **조용히** 잘린다)
- PyMuPDF 혼입 여부 — AGPL이라 들어오면 안 된다
- OCR: `paddlepaddle-gpu` 가 깔려 있으면 거부한다(torch와 cuDNN DLL 충돌).
  torch를 먼저 import해 실제 서비스와 같은 순서를 흉내 낸 뒤,
  **mkldnn을 켜서 먼저 시도하고 실패하면 꺼서 재시도**해 어느 쪽이 되는지 알려준다

> [!tip] 다른 PC에서 세팅한다면
> **x86 PC라면** `MINDEX_OCR_MKLDNN=1` 로 켜고 이 스크립트를 먼저 돌려 볼 것.
> mkldnn 버그는 개발 PC(Intel Core Ultra 7 255H) 한 대에서만 재현됐다.
> 안 나는 환경이면 켜 두는 게 맞다 — CPU OCR이 유의미하게 빨라진다.
>
> **Apple Silicon이면 켜지 말 것.** oneDNN은 AVX 계열 x86 확장용이라
> arm64에서는 의미가 없다.

## 2. `run_e2e.py` — 전건 end-to-end

```bash
python scripts/ocr_pipeline/run_e2e.py               # 86건, 임베딩 포함
python scripts/ocr_pipeline/run_e2e.py --no-embed    # ML 없이 (CI 경로)
python scripts/ocr_pipeline/run_e2e.py --limit 10    # 앞 10건만
python scripts/ocr_pipeline/run_e2e.py --json out.json
```

건별 규격 검증은 `retrieve_contract_chunks` 가 pydantic 모델을 돌려주는 시점에
이미 끝나 있다. 이 스크립트는 그 위에 **코퍼스 전체에 걸친 불변조건**을 얹는다
— 한 건씩 보면 안 보이고 86건을 모아야 드러나는 것들이다.

| 검사 | 왜 |
|---|---|
| `chunk_id` 충돌 | 문서해시 앞 12자 + 순번이다. 겹치면 `contract_chunk` 조인 키가 깨진다 |
| `file_hash` 중복 | 같은 PDF가 두 번 들어 있으면 평가 수치가 부풀려진다 |
| `UNSEGMENTED` | 조항을 하나도 못 찾은 문서. 회수가 사실상 불가능하다 |
| 빈 회수 | 어떤 필드도 못 건진 계약. 추출이 시작을 못 한다 |

모델 로딩(20.6초)은 첫 계약 처리 시간에서 떼어 낸다. 안 그러면 1건이 90초대,
나머지가 0.6초대로 찍혀 평균이 무의미해진다. 실제 워커도 상주 싱글턴으로 한 번만
로딩하므로 이렇게 재는 쪽이 현실에 가깝다.

**2026-08-25 실측 (v0.4)**

```
성공 86/86건   처리 62.9초 (건당 평균 0.73초, 모델 로딩 20.6초 별도)
페이지 446   조항 1825   청크 1827(색인 1804, 회수 1127)
텍스트 경로  {'TEXT_LAYER': 446}
코퍼스 불변조건 통과
```

합성데이터가 전부 digital-born 이라 **OCR 경로는 한 번도 안 탄다.**
스캔본 검증은 `tests/test_ocr.py` 가 담당한다.

## 3. `build_goldset.py` — 회수 정답지

`testdata/k-rights/annotations/` 의 Evidence 781건에서 회수 정답 556건을 뽑아
`eval/retrieval_goldset.json` 에 쓴다.

```bash
python scripts/ocr_pipeline/build_goldset.py
```

**정답을 `chunk_id` 가 아니라 Evidence 텍스트에 건다.** `chunk_id` 는 청킹
방식을 바꾸는 순간 전부 썩어서 정답지 구실을 못 한다.

`parties` 는 정답 라벨이 0건이라 **측정 불가**로 명시해 둔다. 조용히 0%로
집계되면 결함처럼 보인다.

## 3-1. `build_extraction_goldset.py` — 추출 정답지 (Task2용)

```bash
python scripts/ocr_pipeline/build_extraction_goldset.py
```

`ground_truth.json` 에서 **필드 추출 채점에 필요한 것만** 추려
`eval/extraction_goldset.json` 으로 편다. 충돌 판정(scenarios·findings)과
Evidence 위치는 뺀다.

| | 무엇을 채점하나 |
|---|---|
| `retrieval_goldset.json` | "이 필드의 근거가 **어느 조항**인가" — Task1 |
| `extraction_goldset.json` | "그 조항에서 **어떤 값**을 뽑아야 하나" — Task2 |

**`field_status` 를 그대로 남긴다.** `ABSENT`·`UNRESOLVED` 는 오답이 아니라
정답이기 때문이다. `UNRESOLVED` 인 기간에 날짜를 지어내면 **오답이자 위험한
오답**이다 — 없는 권리기간을 만들어내는 것이다. 그래서 채점이 두 축이다.

    ① status 를 맞혔는가   확정 가능/불가를 옳게 판단했는가
    ② values 를 맞혔는가   status 가 PRESENT_* 일 때만 의미가 있다

**작품은 제목으로 대조한다.** GT 는 `C007` 같은 dataset ID 로 가리키는데 이
ID 는 DB payload 에 넣지 않기로 규격이 정했다. `content_registry.yaml` 에서
계약서 언어의 제목을 끌어와 `titles` 에 넣어 둔다.

**payment 는 측정 불가**다. 86건 전부 `NOT_YET_PROJECTED` 라 정답 값이 없다.
조용히 0% 로 집계되면 결함처럼 보이므로 정답지에 명시해 뒀다.

## 4. `paraphrase.py` — held-out 집합

정답지의 질의를 **라벨 표현만 바꿔** 다시 쓴다 (`이용지역` → `서비스 대상 권역`).
날짜·국가·금액 같은 내용어는 건드리지 않는다.

단독 실행할 일은 거의 없다. `eval_retrieval.py --paraphrase` 가 호출한다.

> [!note] 왜 이게 필요했나
> 원본 코퍼스로는 hybrid 가중치를 정할 수 없었다. 어휘 패턴을 그 코퍼스를
> **보면서** 썼기 때문에 어휘 단독으로 @5 556건을 다 맞힌다.
> 표현을 바꾸자 80.0%까지 떨어지면서 비로소 의미 검색의 기여가 보였다.

문자 사이마다 `\s*` 를 넣어 매칭한다. PDF가 단어 중간에서 줄을 바꾸기 때문이다
— CJK도 예외가 아니다 (`利用\n方法`).

## 5. `eval_retrieval.py` — 회수 품질 측정

```bash
python scripts/ocr_pipeline/eval_retrieval.py              # 원본 코퍼스
python scripts/ocr_pipeline/eval_retrieval.py --paraphrase # held-out
```

**실패를 네 갈래로 나눈다.** 이게 이 하네스의 핵심이다.

| 결과 | 뜻 | 고칠 곳 |
|---|---|---|
| `hit` | 정답 | — |
| `rank_miss` | 청크에는 있는데 순위에서 밀림 | 스코어러 |
| `chunk_miss` | 어느 청크에도 안 담김 | **청킹** |
| `extract_miss` | 텍스트 자체가 안 뽑힘 | 추출·OCR |

"Recall이 낮다" 로는 어디를 고쳐야 할지 알 수 없다. 실제로 이 분류 덕에
페이지 분할 결함(`chunk_miss` 55건)을 찾았다.

현재 수치:

| | @1 | @3 | @5 |
|---|---:|---:|---:|
| 원본 | 89.0% | 100.0% | 100.0% |
| **held-out** | **77.5%** | **96.8%** | **99.8%** |

GPU + `requirements-ml.txt` 가 필요하다. CI에서는 안 돈다.

## 6. `make_handoff_samples.py` — Task2 인계 샘플

```bash
PYTHONPATH=. python scripts/ocr_pipeline/make_handoff_samples.py
```

`docs/handoff/samples/*.retrieval.json` 10건을 만든다. 언어 × 템플릿 ×
계약유형이 골고루 덮이도록 고른 것이다.

**실제 파이프라인(`retrieve_contract_chunks`)을 그대로 호출한다.** 샘플 전용
경로를 따로 두면 규격과 구현이 갈라진다.

---

## 여기 없는 것

| | |
|---|---|
| `scripts/generate_synthetic_contracts.py` | 합성 계약서 생성. 파이프라인이 아니라 **테스트 데이터** 쪽이라 루트에 둔다 |
| `scripts/ocr_parse_sample.py` | **폐기 대상.** `*.parse.json` 생성기인데 그 산출물이 v0.3에서 없어졌다 |
| `scripts/build_retrieval_bundle.py` | **폐기 대상.** `*.parse.json` 을 먹고 `lexical-v0` 로 점수를 냈다. 둘 다 현재 규격이 아니다 |

폐기 대상 2개는 저장소 어디에서도 참조되지 않는다. `make_handoff_samples.py`
가 실제 파이프라인을 호출하는 방식으로 대체했다.
