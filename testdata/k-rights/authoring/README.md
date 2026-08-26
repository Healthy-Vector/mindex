# Authoring metadata

이 디렉터리는 서비스의 직접 입력이 아니라 합성데이터 관계 복원과 내부 평가를 위한
metadata를 보관한다.

- `scenario_master.yaml`: 72개 Scenario의 규칙·결과·범위 기대값
- `contract_graph.yaml`: Target/Existing/Upstream 관계와 86개 Contract 재사용 구조
- `content_registry.yaml`: Content/IP/related asset 식별과 계층
- `contract_generation.yaml`: 합성 당사자, 체결일, 문서 구조 및 commercial terms

서비스 전달 payload는 `docs/synthetic_data/interfaces/`의 projection 문서를 기준으로 별도로
생성해야 하며, 이 파일들을 그대로 운영 DB schema로 사용하지 않는다.
