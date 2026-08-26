# 한글 폰트 설치

`01_make_samples.py` 가 합성 계약서 PDF 를 만들 때 한글 폰트가 필요하다.

## 왜 시스템 폰트를 쓰지 않나

맥의 `AppleGothic` · `AppleSDGothicNeo` 는 **Apple 독점 폰트**다.

- 저장소에 넣을 수 없다 (재배포 금지)
- 심사위원이 리눅스·윈도우에서 돌리면 **실행 자체가 실패**한다
- 오픈소스 대회 제출물에 비오픈소스 자산이 섞인다

## 설치 — 둘 중 하나

### 방법 1. Noto Sans KR (권장)

[Google Fonts — Noto Sans KR](https://fonts.google.com/noto/specimen/Noto+Sans+KR) 에서 내려받아
압축을 풀고 `NotoSansKR-Regular.ttf` 를 **이 폴더에** 넣는다.

```
ocr_embedding_test/fonts/NotoSansKR-Regular.ttf
```

라이선스: **SIL Open Font License 1.1** — 재배포·수정·상업적 이용 모두 허용.
같이 받은 `OFL.txt` 도 이 폴더에 함께 넣어둔다 (라이선스 고지 의무).

### 방법 2. 나눔고딕 (Homebrew)

```bash
brew install --cask font-nanum-gothic
```

설치되면 `/Library/Fonts/NanumGothic.ttf` 에 들어가고 스크립트가 자동으로 찾는다.
라이선스: **SIL Open Font License 1.1**

## 확인

```bash
python3 01_make_samples.py
```

첫 줄에 이렇게 나오면 정상이다.

```
[폰트] NotoSansKR-Regular.ttf  (OFL-1.1)
```

아래가 나오면 아직 시스템 폰트를 쓰고 있다.

```
[폰트] AppleGothic.ttf  (Apple 독점)
  ⚠️ 이 폰트는 재배포할 수 없습니다. 제출 전 OFL 폰트로 교체하세요.
```

## .gitignore 주의

폰트 파일(`.ttf`)은 저장소에 **커밋해야 한다.** OFL 폰트는 재배포가 허용되고,
없으면 다른 사람이 스크립트를 돌릴 수 없다.

`.gitignore` 에 `*.ttf` 같은 규칙이 있으면 예외 처리한다.

```gitignore
*.ttf
!ocr_embedding_test/fonts/*.ttf
```
