"""M1: 참조 어휘 시드 (country / territory_group / rights_type / conflict_code)

지시서 §5.4 severity 3종과 §3.1 참조 어휘 구조에 맞춘 최소 실용 시드.
값 목록은 미확정 항목이라 대표 국가·그룹·권리유형만 넣는다(§11 방침: 막지 않는 선에서 진행).

Revision ID: 0002_seed
Revises: 0001_initial
"""
from alembic import op

revision = "0002_seed"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

COUNTRIES = [
    ("KR", "대한민국", "South Korea"),
    ("JP", "일본", "Japan"),
    ("CN", "중국", "China"),
    ("TW", "대만", "Taiwan"),
    ("HK", "홍콩", "Hong Kong"),
    ("SG", "싱가포르", "Singapore"),
    ("TH", "태국", "Thailand"),
    ("VN", "베트남", "Vietnam"),
    ("ID", "인도네시아", "Indonesia"),
    ("MY", "말레이시아", "Malaysia"),
    ("PH", "필리핀", "Philippines"),
    ("IN", "인도", "India"),
    ("US", "미국", "United States"),
    ("CA", "캐나다", "Canada"),
    ("GB", "영국", "United Kingdom"),
    ("FR", "프랑스", "France"),
    ("DE", "독일", "Germany"),
    ("AU", "호주", "Australia"),
]

APAC = ["KR", "JP", "CN", "TW", "HK", "SG", "TH", "VN", "ID", "MY", "PH", "IN", "AU"]

RIGHTS_TYPES = [
    ("SVOD", "구독형 스트리밍", "Subscription VOD"),
    ("AVOD", "광고형 스트리밍", "Ad-supported VOD"),
    ("TVOD", "건별 결제 스트리밍", "Transactional VOD"),
    ("THEATRICAL", "극장 상영", "Theatrical"),
    ("BROADCAST", "방송", "Broadcast"),
    ("MERCHANDISING", "상품화", "Merchandising"),
    ("PUBLISHING", "출판", "Publishing"),
    ("REMAKE", "리메이크", "Remake"),
]

CONFLICT_CODES = [
    ("EXCLUSIVE_VS_EXCLUSIVE", "EXCLUSIVE_VS_EXCLUSIVE",
     "독점 권리끼리 같은 대상·지역·기간에서 충돌합니다."),
    ("EXCLUSIVE_VS_SOLE", "EXCLUSIVE_VS_SOLE",
     "독점 권리와 단독(sole) 권리가 충돌합니다."),
    ("SOLE_VS_SOLE", "SOLE_VS_SOLE",
     "단독(sole) 권리끼리 충돌합니다."),
]


def _q(s: str) -> str:
    return s.replace("'", "''")


def upgrade() -> None:
    for code, ko, en in COUNTRIES:
        op.execute(f"INSERT INTO master.country(code) VALUES ('{code}') ON CONFLICT DO NOTHING;")
        op.execute(
            f"INSERT INTO master.country_label(code,lang,label) VALUES "
            f"('{code}','ko','{_q(ko)}'),('{code}','en','{_q(en)}') ON CONFLICT DO NOTHING;"
        )

    op.execute("INSERT INTO master.territory_group(code) VALUES ('APAC'),('WORLDWIDE') ON CONFLICT DO NOTHING;")
    op.execute(
        "INSERT INTO master.territory_group_label(code,lang,label) VALUES "
        "('APAC','ko','아시아·태평양'),('APAC','en','Asia-Pacific'),"
        "('WORLDWIDE','ko','전세계'),('WORLDWIDE','en','Worldwide') ON CONFLICT DO NOTHING;"
    )
    for cc in APAC:
        op.execute(
            f"INSERT INTO master.territory_group_country(group_code,country_code) "
            f"VALUES ('APAC','{cc}') ON CONFLICT DO NOTHING;"
        )
    # WORLDWIDE = 시드된 전체 국가
    for code, _ko, _en in COUNTRIES:
        op.execute(
            f"INSERT INTO master.territory_group_country(group_code,country_code) "
            f"VALUES ('WORLDWIDE','{code}') ON CONFLICT DO NOTHING;"
        )

    for code, ko, en in RIGHTS_TYPES:
        op.execute(f"INSERT INTO master.rights_type_ref(code) VALUES ('{code}') ON CONFLICT DO NOTHING;")
        op.execute(
            f"INSERT INTO master.rights_type_label(code,lang,label) VALUES "
            f"('{code}','ko','{_q(ko)}'),('{code}','en','{_q(en)}') ON CONFLICT DO NOTHING;"
        )

    for code, severity, ko_tmpl in CONFLICT_CODES:
        op.execute(
            f"INSERT INTO master.conflict_code(code,severity) VALUES "
            f"('{code}','{severity}') ON CONFLICT DO NOTHING;"
        )
        op.execute(
            f"INSERT INTO master.conflict_code_template(code,lang,template) VALUES "
            f"('{code}','ko','{_q(ko_tmpl)}') ON CONFLICT DO NOTHING;"
        )


def downgrade() -> None:
    for t in [
        "conflict_code_template", "conflict_code",
        "rights_type_label", "rights_type_ref",
        "territory_group_country", "territory_group_label", "territory_group",
        "country_label", "country",
    ]:
        op.execute(f"DELETE FROM master.{t};")
