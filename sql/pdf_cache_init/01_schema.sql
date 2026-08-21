CREATE TABLE pdf_cache (
    id         bigserial PRIMARY KEY,
    file_path  text NOT NULL,   -- 로컬 파일시스템 경로
    raw_text   text,            -- PDF 파싱 원문
    created_at timestamptz NOT NULL DEFAULT now()
);
