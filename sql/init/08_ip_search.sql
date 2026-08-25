-- OCR 추출 제목 기반 IP 유사도 검색.
-- pg_trgm은 PostgreSQL supplied extension이며 Tmax OpenSQL의 PostgreSQL
-- Extension Framework에서도 사용한다. 운영 설치 전 pg_available_extensions에서
-- 패키지 포함 여부를 확인해야 한다.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 현재 feat/api-v1의 로컬 스키마 초안에는 P2 ip 테이블이 없으므로 조건부 생성한다.
-- 최신 P2 스키마와 통합되면 두 인덱스가 생성되어 LIKE/유사도 후보 검색을 가속한다.
DO $$
BEGIN
    IF to_regclass('public.ip') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_ip_title_trgm '
                'ON public.ip USING gin (lower(title) gin_trgm_ops)';
    END IF;
    IF to_regclass('public.ip_alias') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_ip_alias_text_trgm '
                'ON public.ip_alias USING gin (lower(alias_text) gin_trgm_ops)';
    END IF;
END
$$;
