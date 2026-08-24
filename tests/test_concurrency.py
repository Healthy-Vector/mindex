"""§8.3 동시성 — 겹치는 두 계약을 동시에 6번으로 확정하면
하나는 applied, 하나는 conflicted 여야 한다(둘 다 applied 면 EXCLUDE 실패)."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from tests.conftest import requires_db, make_verify_body


@requires_db
def test_concurrent_confirm_one_conflicts(client, clean_db):
    def confirm():
        body = make_verify_body(clean_db, source_tmpid=str(uuid.uuid4()))
        return client.post("/api/contracts", json=body).json()

    with ThreadPoolExecutor(max_workers=2) as ex:
        r1, r2 = list(ex.map(lambda _: confirm(), range(2)))

    conflicts = [r1["hasConflict"], r2["hasConflict"]]
    # 정확히 하나만 충돌(하나는 applied)
    assert conflicts.count(True) == 1, conflicts
    assert conflicts.count(False) == 1, conflicts
