import { useEffect, useState } from "react";
import { api } from "../api/client.js";

// GET /refs(API 명세서 #16) 결과를 페이지 간에 공유하는 모듈 스코프 캐시 — 값이 자주
// 바뀌지 않아 페이지마다 다시 받을 필요가 없다(명세서 "구현 시 주의"와 같은 이유).
let cache = null;
let pending = null;

const EMPTY = {
  territoryLabel: {},
  territoryOptions: [],
  territoryGroupLabel: {},
  territoryGroupMembers: {},
  ipKindLabel: {},
  ipKindOptions: [],
  scopeTypeLabel: {},
  scopeTypeOptions: [],
  relationTypeLabel: {},
  legalRightLabel: {},
  legalRightOptions: [],
  exploitationModeLabel: {},
  exploitationModeOptions: [],
};

function toLabelMap(list) {
  return Object.fromEntries((list ?? []).map((r) => [r.code, r.label]));
}

function toOptions(list) {
  return (list ?? []).map((item) => ({ value: item.code, label: item.label }));
}

function deriveRefs(raw) {
  return {
    territoryLabel: toLabelMap(raw.country),
    territoryOptions: toOptions(raw.country),
    territoryGroupLabel: toLabelMap(raw.territoryGroup),
    territoryGroupMembers: Object.fromEntries((raw.territoryGroup ?? []).map((g) => [g.code, g.countries])),
    ipKindLabel: toLabelMap(raw.ipKind),
    ipKindOptions: toOptions(raw.ipKind),
    scopeTypeLabel: toLabelMap(raw.scopeType),
    scopeTypeOptions: toOptions(raw.scopeType),
    relationTypeLabel: toLabelMap(raw.relationType),
    legalRightLabel: toLabelMap(raw.legalRight),
    legalRightOptions: toOptions(raw.legalRight),
    exploitationModeLabel: toLabelMap(raw.exploitationMode),
    exploitationModeOptions: toOptions(raw.exploitationMode),
  };
}

// 국가/지역그룹/IP유형/범위유형/관계유형 라벨을 GET /refs에서 받아온 형태로 돌려준다.
// 로딩 중엔 빈 맵/배열을 돌려주므로 호출부는 별도 loading 분기 없이 그대로 렌더해도 된다
// (라벨이 잠깐 코드값 그대로 보이다가 채워지는 정도 — 값이 캐시되면 이후 페이지 이동에선
// 즉시 채워진다).
export function useRefs() {
  const [refs, setRefs] = useState(cache ? deriveRefs(cache) : EMPTY);
  useEffect(() => {
    if (cache) return;
    let cancelled = false;
    if (!pending) {
      pending = api
        .getRefs()
        .then((data) => {
          cache = data;
          return data;
        })
        .catch(() => null)
        .finally(() => {
          if (!cache) pending = null;
        });
    }
    pending.then((data) => {
      if (!cancelled && data) setRefs(deriveRefs(data));
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return refs;
}
