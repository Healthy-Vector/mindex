"""M1: 초기 스키마 — master/staging + 참조 어휘 + EXCLUDE 제약

지시서 §3 기준. 스키마를 명시 DDL 로 관리한다(autogenerate 미사용).

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-24
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 확장 (지시서 §1.3) ---
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.execute("CREATE SCHEMA IF NOT EXISTS master;")
    op.execute("CREATE SCHEMA IF NOT EXISTS staging;")
    # 프런트 필터 전용 IP 활성/비활성 (P2-DB ip_activity_kind 정렬)
    op.execute("CREATE TYPE master.ip_activity_kind AS ENUM ('active', 'deactive');")

    # --- 참조 어휘 (코드=PK, 라벨=(code,lang) 별도 테이블; 지시서 §3.1) ---
    op.execute(
        """
        CREATE TABLE master.country (
          code  char(2) PRIMARY KEY,           -- ISO 3166-1 alpha-2
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE master.country_label (
          code  char(2) NOT NULL REFERENCES master.country(code),
          lang  char(2) NOT NULL,
          label text    NOT NULL,
          PRIMARY KEY (code, lang)
        );

        CREATE TABLE master.territory_group (
          code text PRIMARY KEY                 -- 'APAC','WORLDWIDE',...
        );
        CREATE TABLE master.territory_group_label (
          code  text NOT NULL REFERENCES master.territory_group(code),
          lang  char(2) NOT NULL,
          label text NOT NULL,
          PRIMARY KEY (code, lang)
        );
        CREATE TABLE master.territory_group_country (
          group_code   text    NOT NULL REFERENCES master.territory_group(code),
          country_code char(2) NOT NULL REFERENCES master.country(code),
          PRIMARY KEY (group_code, country_code)
        );

        CREATE TABLE master.rights_type_ref (
          code text PRIMARY KEY                 -- 'SVOD','AVOD','THEATRICAL',...
        );
        CREATE TABLE master.rights_type_label (
          code  text NOT NULL REFERENCES master.rights_type_ref(code),
          lang  char(2) NOT NULL,
          label text NOT NULL,
          PRIMARY KEY (code, lang)
        );

        CREATE TABLE master.conflict_code (
          code     text PRIMARY KEY,            -- 'EXCLUSIVE_VS_EXCLUSIVE',...
          severity text NOT NULL
        );
        CREATE TABLE master.conflict_code_template (
          code     text NOT NULL REFERENCES master.conflict_code(code),
          lang     char(2) NOT NULL,
          template text NOT NULL,
          PRIMARY KEY (code, lang)
        );
        """
    )

    # --- master 핵심 (지시서 §3.1) ---
    op.execute(
        """
        CREATE TABLE master.team (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          name        text NOT NULL,
          pin_hash    text NOT NULL,
          created_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE master.ip (
          id          bigserial PRIMARY KEY,
          team_id     uuid NOT NULL REFERENCES master.team(id),
          title       text NOT NULL,
          kind        text NOT NULL,
          activity    master.ip_activity_kind NOT NULL DEFAULT 'active',
          created_at  timestamptz NOT NULL DEFAULT now(),
          updated_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE master.ip_alias (
          id          bigserial PRIMARY KEY,
          team_id     uuid NOT NULL REFERENCES master.team(id),
          ip_id       bigint NOT NULL REFERENCES master.ip(id) ON DELETE CASCADE,
          alias_text  text NOT NULL,
          lang        char(2) NOT NULL,
          alias_type  text NOT NULL,
          created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_ip_alias_norm ON master.ip_alias (lower(alias_text));

        CREATE TABLE master.content_asset (
          id            bigserial PRIMARY KEY,
          team_id       uuid NOT NULL REFERENCES master.team(id),
          ip_id         bigint NOT NULL REFERENCES master.ip(id),
          parent_id     bigint REFERENCES master.content_asset(id),
          scope_type    text NOT NULL,
          season_no     int,
          episode_no    int,
          edition_code  text,
          title         text
        );

        CREATE TABLE master.ip_relation (
          source_ip_id   bigint NOT NULL REFERENCES master.ip(id),
          derived_ip_id  bigint NOT NULL REFERENCES master.ip(id),
          relation_type  text   NOT NULL,
          PRIMARY KEY (source_ip_id, derived_ip_id, relation_type)
        );

        CREATE TABLE master.contract (
          id                  bigserial PRIMARY KEY,
          team_id             uuid NOT NULL REFERENCES master.team(id),
          title               text NOT NULL,
          contract_type       text,
          counterparty        text NOT NULL,
          signed_date         date,
          lang                char(2),
          amount              numeric,
          currency            char(3),
          current_history_id  bigint,
          source_tmpid        uuid UNIQUE,
          status              text NOT NULL DEFAULT 'draft',
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE master.contract_history (
          id            bigserial PRIMARY KEY,
          team_id       uuid NOT NULL REFERENCES master.team(id),
          contract_id   bigint NOT NULL REFERENCES master.contract(id),
          version       text NOT NULL,
          status        text NOT NULL,
          conflict_report jsonb,
          file_path     text,
          raw_text      text,
          title         text,
          counterparty  text,
          signed_date   date,
          lang          char(2),
          amount        numeric,
          currency      char(3),
          parsed_at     timestamptz,
          created_at    timestamptz NOT NULL DEFAULT now(),
          UNIQUE (contract_id, version)
        );
        ALTER TABLE master.contract
          ADD CONSTRAINT fk_contract_current_history
          FOREIGN KEY (current_history_id) REFERENCES master.contract_history(id);

        CREATE TABLE master.contract_chunk (
          id                   bigserial PRIMARY KEY,
          team_id              uuid NOT NULL REFERENCES master.team(id),
          contract_history_id  bigint NOT NULL REFERENCES master.contract_history(id) ON DELETE CASCADE,
          clause_no            text,
          chunk_text           text NOT NULL,
          lang                 char(2),
          page                 int,
          embedding            vector(1024),
          created_at           timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_chunk_hnsw ON master.contract_chunk
          USING hnsw (embedding vector_cosine_ops);
        """
    )

    # --- rights_grant + EXCLUDE (지시서 §3.1 §3.2) ---
    op.execute(
        """
        CREATE TABLE master.rights_grant (
          id                   bigserial PRIMARY KEY,
          team_id              uuid NOT NULL REFERENCES master.team(id),
          contract_id          bigint NOT NULL REFERENCES master.contract(id),
          contract_history_id  bigint NOT NULL REFERENCES master.contract_history(id),
          content_asset_id     bigint NOT NULL REFERENCES master.content_asset(id),
          territory            char(2) NOT NULL REFERENCES master.country(code),
          rights_type          text    NOT NULL REFERENCES master.rights_type_ref(code),
          period               daterange NOT NULL,
          exclusivity          text NOT NULL,
          status               text NOT NULL,
          lineage_id           bigint,
          conditions_raw       jsonb,
          confidence           numeric(3,2),
          evidence             jsonb,
          created_at           timestamptz NOT NULL DEFAULT now(),
          terminated_at        timestamptz,
          terminated_reason    text
        );
        CREATE INDEX ix_rg_lineage  ON master.rights_grant (lineage_id, created_at);
        CREATE INDEX ix_rg_contract ON master.rights_grant (contract_id, status);

        ALTER TABLE master.rights_grant
        ADD CONSTRAINT no_exclusive_overlap
        EXCLUDE USING gist (
          contract_id      WITH <>,
          content_asset_id WITH =,
          territory        WITH =,
          rights_type      WITH =,
          period           WITH &&
        )
        WHERE (exclusivity <> 'non_exclusive' AND status = 'active');
        """
    )

    # --- staging (지시서 §3.3; P1 소유이나 P4 가 읽음) ---
    op.execute(
        """
        CREATE TABLE staging.pdf_blob (
          tmpid       uuid PRIMARY KEY,
          data        bytea NOT NULL,
          filename    text,
          byte_size   int,
          created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE staging.extract_job (
          tmpid        uuid PRIMARY KEY REFERENCES staging.pdf_blob(tmpid) ON DELETE CASCADE,
          status       text NOT NULL,
          stage        text,
          lease_until  timestamptz,
          attempts     int NOT NULL DEFAULT 0,
          reason       text,
          created_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_job_queue ON staging.extract_job (status, created_at);
        CREATE TABLE staging.extract_result (
          tmpid       uuid PRIMARY KEY REFERENCES staging.pdf_blob(tmpid) ON DELETE CASCADE,
          payload     jsonb NOT NULL,
          confidence  numeric(4,3),
          created_at  timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS staging CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS master CASCADE;")
