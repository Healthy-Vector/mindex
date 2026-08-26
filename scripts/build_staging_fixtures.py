"""합성 계약 PDF를 contract-extraction-worker 형식의 staging fixture로 변환한다.

Ollama나 OCR 모델을 사용하지 않는다. ``C:/mindex/pdf/generated``의 합성 문서는
텍스트 레이어와 정형 문구를 갖고 있으므로 pdfplumber와 언어별 규칙만 사용한다.
결과 JSON은 worker의 ``ExtractionResult.to_dict()``와 같은 네 묶음
(``raw``/``validation``/``normalized``/``compact``)으로 저장한다.

사용 예:

    python scripts/build_staging_fixtures.py
    python scripts/build_staging_fixtures.py --strict
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pdfplumber

SCHEMA_VERSION = "k-rights.contract-extraction.v0.1"
OUTPUT_SCHEMA_VERSION = "mindex.staging-fixture.v0.1"

FIELD_EXPLICIT = "PRESENT_EXPLICIT"
FIELD_DERIVED = "PRESENT_DERIVED"
FIELD_UNRESOLVED = "UNRESOLVED"
FIELD_ABSENT = "ABSENT"

INTRO_PATTERNS = {
    "KO": re.compile(
        r"(?P<mode>구독형주문형영상\(SVOD\)|광고형주문형영상\(AVOD\)|"
        r"건별결제주문형영상\(TVOD\)|선형방송|극장상영|음원스트리밍|"
        r"본문에서특정하지않은이용방식)"
        r"이용을위한본개별이용허락의권리대상은[‘'](?P<title>[^’']+)[’']"
    ),
    "EN": re.compile(
        r"Forexploitationby(?P<mode>.+?),theLicensedSubjectMatterforthisgrant"
        r"islimitedto[“\"](?P<title>[^”\"]+)[”\"]",
        re.I,
    ),
    "JP": re.compile(
        r"(?P<mode>定額制動画配信（SVOD）|広告型動画配信（AVOD）|"
        r"都度課金型動画配信（TVOD）|リニア放送|劇場上映|音楽ストリーミング|"
        r"オンデマンド動画配信|本書で特定されていない利用方法)"
        r"による利用のための本個別許諾の権利対象は「(?P<title>[^」]+)」"
    ),
}

MODE_MAP = {
    "SVOD": "SVOD",
    "AVOD": "AVOD",
    "TVOD": "TVOD",
    "구독형주문형영상": "SVOD",
    "광고형주문형영상": "AVOD",
    "건별결제주문형영상": "TVOD",
    "선형방송": "TV_LINEAR",
    "극장상영": "THEATRICAL",
    "음원스트리밍": "MUSIC_STREAMING",
    "본문에서특정하지않은이용방식": "DIGITAL_DISTRIBUTION_UNSPECIFIED",
    "subscriptionvideo-on-demand": "SVOD",
    "advertising-supportedvideo-on-demand": "AVOD",
    "transactionalvideo-on-demand": "TVOD",
    "lineartelevision": "TV_LINEAR",
    "theatricalexhibition": "THEATRICAL",
    "musicstreaming": "MUSIC_STREAMING",
    "on-demandaudiovisualservices": "ON_DEMAND_AUDIOVISUAL",
    "anexploitationmodenotspecifiedinthisdocument": "DIGITAL_DISTRIBUTION_UNSPECIFIED",
    "定額制動画配信": "SVOD",
    "広告型動画配信": "AVOD",
    "都度課金型動画配信": "TVOD",
    "リニア放送": "TV_LINEAR",
    "劇場上映": "THEATRICAL",
    "音楽ストリーミング": "MUSIC_STREAMING",
    "オンデマンド動画配信": "ON_DEMAND_AUDIOVISUAL",
    "本書で特定されていない利用方法": "DIGITAL_DISTRIBUTION_UNSPECIFIED",
}

COUNTRY_TERMS = {
    "KR": ("대한민국", "한국", "southkorea", "republicofkorea", "韓国", "大韓民国"),
    "JP": ("일본", "japan", "日本"),
    "US": ("미국", "unitedstates", "u.s.", "米国", "アメリカ"),
    "SG": ("싱가포르", "singapore", "シンガポール"),
    "TW": ("대만", "taiwan", "台湾"),
}

GROUP_TERMS = {
    "WORLDWIDE": ("전세계", "전 세계", "worldwide", "全世界"),
    "APAC": ("아시아·태평양", "아시아태평양", "asia-pacific", "apac", "アジア太平洋"),
    "ASIA": ("아시아", "asia", "アジア"),
}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00ad\n", "\n").replace("\u00ad", "-")
    return text.replace("\x00", "")


def clean_page_text(text: str) -> str:
    """합성 문서의 반복 워터마크/쪽번호만 제거하고 본문 형식은 보존한다."""
    clean_lines = []
    for line in normalize_text(text).splitlines():
        if "K-RIGHTS SYNTHETIC REVIEW COPY - NOT FOR EXECUTION" in line:
            continue
        if re.fullmatch(r"\s*\d+\s*/\s*\d+\s*", line):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text(text))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def field(value: Any, raw: str | None, *, derived: bool = False) -> dict[str, Any]:
    if value is None or value == []:
        status = FIELD_UNRESOLVED if raw else FIELD_ABSENT
    else:
        status = FIELD_DERIVED if derived else FIELD_EXPLICIT
    return {"field_status": status, "value": value, "raw_expression": raw}


def values_field(values: list[str], raw: str | None) -> dict[str, Any]:
    status = FIELD_EXPLICIT if values else (FIELD_UNRESOLVED if raw else FIELD_ABSENT)
    return {"field_status": status, "values": values, "raw_expression": raw}


def parse_date_token(token: str) -> str | None:
    token = normalize_text(token)
    match = re.search(r"(20\d{2})[-年年년./]\s*(\d{1,2})[-月월./]\s*(\d{1,2})日?일?", token)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def extract_tables(pdf: pdfplumber.PDF) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            clean_table = []
            for row in table:
                clean_table.append([normalize_text(cell or "").strip() for cell in row])
            tables.append(clean_table)
    return tables


def first_table_value(tables: list[list[list[str]]], labels: tuple[str, ...]) -> str | None:
    for table in tables:
        for row in table:
            if not row:
                continue
            for cell in row:
                key = compact(cell).lower()
                if any(compact(label).lower() in key for label in labels):
                    lines = [part.strip() for part in cell.splitlines() if part.strip()]
                    if len(lines) >= 2:
                        return lines[-1]
    return None


def extract_parties(tables: list[list[list[str]]], lang: str) -> list[dict[str, Any]]:
    row_labels = {
        "KO": ("계약 당사자",),
        "EN": ("Parties",),
        "JP": ("契約当事者",),
    }[lang]
    for table in tables:
        for row in table:
            if len(row) < 3 or compact(row[0]).lower() not in {
                compact(label).lower() for label in row_labels
            }:
                continue
            return [
                {
                    "role": "GRANTOR",
                    "name": row[1].replace("\n", " ").strip() or None,
                    "field_status": FIELD_EXPLICIT,
                    "raw_expression": row[1].strip() or None,
                },
                {
                    "role": "GRANTEE",
                    "name": row[2].replace("\n", " ").strip() or None,
                    "field_status": FIELD_EXPLICIT,
                    "raw_expression": row[2].strip() or None,
                },
            ]
    return []


def extract_main_title(text: str, lang: str) -> tuple[str | None, str | None]:
    front = text[:800]
    first_line = next((line.strip() for line in front.splitlines() if line.strip()), None)
    pattern = r"『([^』]+)』" if lang in {"KO", "JP"} else r"[“\"]([^”\"]+)[”\"]"
    match = re.search(pattern, front)
    if not match:
        return None, first_line
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return title, first_line


def pretty_subject(captured: str, main_title: str | None) -> str:
    if main_title and compact(captured).casefold() == compact(main_title).casefold():
        return main_title
    if main_title and compact(captured).casefold().startswith(compact(main_title).casefold()):
        suffix = captured[len(compact(main_title)):]
        suffix = suffix.replace("OST마스터", "OST 마스터").replace("OSTMaster", "OST Master")
        return f"{main_title} {suffix}".strip()
    return captured


def mode_code(raw_mode: str) -> str | None:
    key = compact(raw_mode).casefold()
    for term, code in MODE_MAP.items():
        if compact(term).casefold() in key:
            return code
    return None


def legal_rights(block: str, mode: str | None) -> tuple[list[str], str | None]:
    checks = [
        (
            ("二次的著作物作成権", "2차적저작물작성권", "derivativework", "derivative-work"),
            "DERIVATIVE_WORK_CREATION",
        ),
        (("複製権", "복제권", "reproductionright"), "REPRODUCTION"),
        (("頒布権", "배포권", "distributionright"), "DISTRIBUTION"),
        (("放送権", "방송권", "broadcastright"), "BROADCASTING"),
        (("上演権", "上映権", "공연권", "상영권", "publicperformance", "exhibitionright"), "PERFORMANCE"),
        (("自動公衆送信権", "送信可能化", "전송권", "interactivetransmission", "making-available"), "INTERACTIVE_TRANSMISSION"),
    ]
    found: list[str] = []
    matched_spans: list[tuple[int, int]] = []
    folded = block.casefold()
    for terms, code in checks:
        for term in terms:
            needle = compact(term).casefold()
            position = folded.find(needle)
            if position >= 0:
                if code not in found:
                    found.append(code)
                matched_spans.append((position, position + len(needle)))
                break
    if not matched_spans:
        unresolved_terms = (
            "본서에서범위가확정되지않은권리",
            "범위가확정되지않은권리",
            "rightscopenotspecifiedinthisdocument",
            "rightscopenotdeterminedinthisdocument",
            "本書で範囲が確定していない権利",
        )
        for term in unresolved_terms:
            needle = compact(term).casefold()
            position = folded.find(needle)
            if position >= 0:
                matched_spans.append((position, position + len(needle)))
                break
    if not found and mode == "THEATRICAL":
        found = ["PERFORMANCE", "EXHIBITION"]
    if "PERFORMANCE" in found and mode == "THEATRICAL" and "EXHIBITION" not in found:
        found.append("EXHIBITION")
    raw = None
    if matched_spans:
        raw = block[min(start for start, _ in matched_spans):max(end for _, end in matched_spans)]
    return found, raw


def territory_values(raw: str | None) -> tuple[list[str], list[str]]:
    if not raw:
        return [], []
    folded = compact(raw).casefold()
    values: list[str] = []
    for code, terms in COUNTRY_TERMS.items():
        if any(compact(term).casefold() in folded for term in terms):
            values.append(code)
    for code, terms in GROUP_TERMS.items():
        if any(compact(term).casefold() in folded for term in terms):
            values.append(code)
            break
    return list(dict.fromkeys(values)), []


def territory_raw(block: str, lang: str) -> str | None:
    patterns = {
        "KO": r"이용지역은(.+?)이고,이용기간은",
        "EN": r"Territoryis(.+?)andtheLicensePeriodis",
        "JP": r"利用する地域は(.+?)とし、利用期間は",
    }
    match = re.search(patterns[lang], block, re.I)
    return match.group(1) if match else None


def period_values(block: str) -> tuple[str | None, str | None, str | None]:
    matches = list(
        re.finditer(r"20\d{2}(?:-|年|年|년)\d{1,2}(?:-|月|월)\d{1,2}(?:日|일)?", block)
    )
    if len(matches) < 2:
        unresolved_patterns = (
            r"이용기간은(.+?)(?:이며|이다|독점성은)",
            r"LicensePeriodis(.+?)Exclusivityapplies",
            r"利用期間は(.+?)(?:とする|独占性は)",
        )
        for pattern in unresolved_patterns:
            unresolved = re.search(pattern, block, re.I)
            if unresolved:
                return None, None, unresolved.group(1)
        return None, None, None
    raw = block[matches[0].start():matches[1].end()]
    return parse_date_token(matches[0].group()), parse_date_token(matches[1].group()), raw


def exclusivity_value(block: str) -> tuple[str | None, str | None]:
    lower = block.casefold()
    for token in ("비독점", "非独占", "non-exclusive"):
        if compact(token).casefold() in lower:
            return "NON_EXCLUSIVE", compact(token)
    for token in ("독점", "独占", "exclusive"):
        if compact(token).casefold() in lower:
            return "EXCLUSIVE", compact(token)
    return None, None


def content_scope(title: str) -> tuple[str, str]:
    key = compact(title).casefold()
    if "ost" in key or "음원마스터" in key or "サウンドトラック" in key:
        return "RELATED_ASSET", "OST_MASTER"
    if any(term in key for term in ("시즌", "season", "シーズン")):
        return "CONTENT", "SEASON"
    if any(term in key for term in ("에피소드", "episode", "話")):
        return "CONTENT", "EPISODE"
    if any(term in key for term in ("감독판", "director'scut", "編集版")):
        return "CONTENT", "EDIT"
    return "CONTENT", "SERIES"


def page_for_quote(page_compacts: list[str], quote: str | None) -> int | None:
    if not quote:
        return None
    needle = compact(quote).casefold()
    for index, page in enumerate(page_compacts, start=1):
        if needle and needle in page.casefold():
            return index
    return None


def evidence_entry(
    number: int,
    grant_ref: str,
    field_name: str,
    label: str,
    quote: str,
    page: int | None,
    section: str,
) -> dict[str, Any]:
    return {
        "evidence_ref": f"evidence-{number}",
        "labels": [label],
        "targets": [
            {
                "target_type": "RIGHTS_GRANT_FIELD",
                "target_ref": grant_ref,
                "field": field_name,
            }
        ],
        "text": quote,
        "section": section,
        "page_start": page,
        "page_end": page,
        "start_char": None,
        "end_char": None,
    }


def parse_grants(
    text: str,
    page_compacts: list[str],
    lang: str,
    main_title: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    joined = compact(text)
    matches = list(INTRO_PATTERNS[lang].finditer(joined))
    grants: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []
    section = {"KO": "제3조/별지 1", "EN": "Article 3/Schedule 1", "JP": "第3条/別紙1"}[lang]

    for index, match in enumerate(matches, start=1):
        end = matches[index].start() if index < len(matches) else min(len(joined), match.start() + 2600)
        block = joined[match.start():end]
        grant_ref = f"grant-{index}"
        raw_mode = match.group("mode")
        mode = mode_code(raw_mode)
        title = pretty_subject(match.group("title"), main_title)
        right_values, right_raw = legal_rights(block, mode)
        terr_raw = territory_raw(block, lang)
        terr_values, excluded_values = territory_values(terr_raw)
        start, finish, period_raw = period_values(block)
        exclusive, exclusive_raw = exclusivity_value(block)
        subject_type, scope_type = content_scope(title)

        missing = []
        for name, value in (
            ("legal_right", right_values),
            ("exploitation_mode", mode),
            ("territory", terr_values),
            ("license_period.start", start),
            ("license_period.end", finish),
            ("exclusivity", exclusive),
        ):
            if not value:
                missing.append(name)
        if missing:
            warnings.append(f"{grant_ref}: 미해결 필드 {', '.join(missing)}")

        grant = {
            "grant_ref": grant_ref,
            "content": {
                "field_status": FIELD_EXPLICIT,
                "subjects": [
                    {
                        "subject_type": subject_type,
                        "title": title,
                        "scope_type": scope_type,
                        "relationship_type": None,
                    }
                ],
                "raw_expression": match.group("title"),
            },
            "legal_right": {
                "field_status": FIELD_EXPLICIT if right_values else FIELD_UNRESOLVED,
                "values": right_values,
                "raw_expression": right_raw,
            },
            "exploitation_mode": {
                "field_status": FIELD_EXPLICIT if mode else FIELD_UNRESOLVED,
                "values": [mode] if mode else [],
                "raw_expression": raw_mode,
            },
            "territory": {
                "field_status": FIELD_EXPLICIT if terr_values else FIELD_UNRESOLVED,
                "values": terr_values,
                "excluded_values": excluded_values,
                "definitions": [],
                "raw_expression": terr_raw,
            },
            "license_period": {
                "field_status": FIELD_EXPLICIT if start and finish else FIELD_UNRESOLVED,
                "start": start,
                "end": finish,
                "raw_expression": period_raw,
            },
            "exclusivity": {
                "field_status": FIELD_EXPLICIT if exclusive else FIELD_UNRESOLVED,
                "value": exclusive,
                "raw_expression": exclusive_raw,
            },
            "authority_constraints": {
                "field_status": FIELD_ABSENT,
                "may_sublicense": None,
                "allowed_recipient_types": [],
                "target_recipient_type": None,
                "raw_expression": None,
            },
            "scope_modifiers": [],
        }
        grants.append(grant)

        evidence_specs = (
            ("legal_right", "LEGAL_RIGHT", right_raw),
            ("exploitation_mode", "EXPLOITATION_MODE", raw_mode),
            ("territory", "TERRITORY", terr_raw),
            ("license_period", "PERIOD", period_raw),
            ("exclusivity", "EXCLUSIVITY", exclusive_raw),
        )
        for field_name, label, quote in evidence_specs:
            if not quote:
                continue
            evidence.append(
                evidence_entry(
                    len(evidence) + 1,
                    grant_ref,
                    field_name,
                    label,
                    quote,
                    page_for_quote(page_compacts, quote),
                    section,
                )
            )

    if not matches:
        warnings.append("권리부여 시작 문구를 찾지 못함")
    return grants, evidence, warnings


def extract_payment(joined: str, lang: str) -> list[dict[str, Any]]:
    compacted = compact(joined)
    patterns = {
        "KO": r"(?:총계약대가는|이계약의이용대가는|총계약대가)([0-9,.]+)([A-Z]{3})",
        "EN": r"considerationis([0-9,.]+)([A-Z]{3})",
        "JP": r"契約対価の総額は([0-9,.]+)([A-Z]{3})",
    }
    match = re.search(patterns[lang], compacted, re.I)
    if not match:
        return []
    amount = match.group(1).replace(",", "")
    return [{"payment_ref": "payment-1", "amount": amount, "currency": match.group(2)}]


def territory_effective(territory: dict[str, Any]) -> list[str]:
    values = territory.get("values") or []
    excluded = set(territory.get("excluded_values") or [])
    definitions = {item["term"]: item.get("members", []) for item in territory.get("definitions") or []}
    expanded: list[str] = []
    for value in values:
        expanded.extend(definitions.get(value, [value]))
    return [value for value in dict.fromkeys(expanded) if value not in excluded]


def normalize_contract(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(raw)
    for grant in normalized["contract"]["rights_grants"]:
        effective = territory_effective(grant["territory"])
        grant["_territory_effective"] = {"effective": effective, "warnings": []}
        grant["_territory_scopes"] = [
            {"term": value, "members": [value]} for value in effective
        ]
        grant["_date_problems"] = []
    normalized["contract"]["_agreement_date_problems"] = []
    return normalized


def project(normalized: dict[str, Any], file_hash: str) -> dict[str, Any]:
    contract = normalized["contract"]
    projected_grants = []
    for grant in contract["rights_grants"]:
        projected_grants.append(
            {
                "subjects": grant["content"]["subjects"],
                "legal_rights": grant["legal_right"]["values"],
                "exploitation_modes": grant["exploitation_mode"]["values"],
                "territory_scopes": grant["_territory_scopes"],
                "license_period": {
                    "start": grant["license_period"]["start"],
                    "end": grant["license_period"]["end"],
                },
                "exclusivity": grant["exclusivity"]["value"],
                "authority": None,
            }
        )
    return {
        "request_id": f"fixture-{file_hash[:12]}",
        "source_document_ref": file_hash,
        "payload": {
            "schema_version": "k-rights.db-contract-projection.v0.1",
            "document_language": normalized["document"]["language"],
            "contract": {
                "title": contract["contract_title"]["value"],
                "agreement_type": contract["agreement_type"]["value"],
                "agreement_date": contract["agreement_date"]["value"],
                "parties": [
                    {"role": party["role"], "name": party["name"]}
                    for party in contract["parties"]
                ],
                "rights_grants": projected_grants,
                "payments": contract["payments"],
            },
        },
    }


def iter_field_results(contract: dict[str, Any]):
    for key in ("contract_title", "agreement_type", "agreement_date"):
        yield key, contract[key]
    for index, party in enumerate(contract["parties"]):
        yield f"parties[{index}]", party
    for grant_index, grant in enumerate(contract["rights_grants"]):
        for key in (
            "content",
            "legal_right",
            "exploitation_mode",
            "territory",
            "license_period",
            "exclusivity",
            "authority_constraints",
        ):
            yield f"rights_grants[{grant_index}].{key}", grant[key]
        for modifier_index, modifier in enumerate(grant["scope_modifiers"]):
            yield f"rights_grants[{grant_index}].scope_modifiers[{modifier_index}]", modifier


def validate_fixture(raw: dict[str, Any], source_text: str) -> dict[str, Any]:
    """worker validator와 같은 근거 일치·참조·날짜 검사를 적용한다."""
    contract = raw["contract"]
    normalized_source = compact(source_text).casefold()
    checks: list[tuple[bool, str]] = []
    dropped_fields: list[str] = []
    for path, item in iter_field_results(contract):
        if item["field_status"] in {FIELD_ABSENT, "EXTERNAL_REFERENCE"}:
            checks.append((True, path))
            continue
        raw_expression = item.get("raw_expression")
        ok = bool(raw_expression and compact(raw_expression).casefold() in normalized_source)
        checks.append((ok, path))
        if not ok:
            dropped_fields.append(path)

    for evidence in contract["evidence"]:
        quote = evidence.get("text")
        checks.append((bool(quote and compact(quote).casefold() in normalized_source), evidence["evidence_ref"]))

    grant_refs = {grant["grant_ref"] for grant in contract["rights_grants"]}
    payment_refs = {payment["payment_ref"] for payment in contract["payments"]}
    ref_problems = []
    for evidence_index, evidence in enumerate(contract["evidence"]):
        for target_index, target in enumerate(evidence["targets"]):
            target_type = target["target_type"]
            target_ref = target["target_ref"]
            if target_type == "RIGHTS_GRANT_FIELD" and target_ref not in grant_refs:
                ref_problems.append(f"evidence[{evidence_index}].targets[{target_index}]: grant_ref 불일치")
            if target_type == "PAYMENT" and target_ref not in payment_refs:
                ref_problems.append(f"evidence[{evidence_index}].targets[{target_index}]: payment_ref 불일치")

    logic_problems = []
    for grant_index, grant in enumerate(contract["rights_grants"]):
        start = grant["license_period"].get("start")
        finish = grant["license_period"].get("end")
        if start and finish and date.fromisoformat(start) >= date.fromisoformat(finish):
            logic_problems.append(f"rights_grants[{grant_index}].license_period: start >= end")

    schema_ok = bool(contract["rights_grants"]) and not ref_problems
    logic_ok = not logic_problems
    checked = len(checks)
    passed = sum(ok for ok, _ in checks)
    ev_rate = passed / checked if checked else 0.0
    confidence = round(0.6 * ev_rate + 0.2 * schema_ok + 0.2 * logic_ok, 3)
    if confidence < 0.70:
        route, level = "폐기·재처리", "RED"
    elif confidence < 0.85:
        route, level = "인간 검수 큐", "YELLOW"
    else:
        route, level = "자동 통과", "GREEN"
    return {
        "confidence": confidence,
        "route": route,
        "route_level": level,
        "ev_rate": round(ev_rate, 3),
        "checked": checked,
        "passed": passed,
        "schema_ok": schema_ok,
        "logic_ok": logic_ok,
        "ref_problems": ref_problems,
        "logic_problems": logic_problems,
        "dropped_fields": dropped_fields,
    }


def parse_pdf(path: Path, input_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data = path.read_bytes()
    file_hash = sha256_bytes(data)
    with pdfplumber.open(path) as pdf:
        page_texts = [clean_page_text(page.extract_text() or "") for page in pdf.pages]
        tables = extract_tables(pdf)
    text = "\n".join(page_texts)
    page_compacts = [compact(page) for page in page_texts]
    relative = path.relative_to(input_root)
    lang = relative.parts[0]
    agreement_type = relative.parts[2]
    main_title, contract_title_raw = extract_main_title(text, lang)
    parties = extract_parties(tables, lang)

    date_labels = {
        "KO": ("계약 체결일",),
        "EN": ("Agreement Date",),
        "JP": ("契約締結日",),
    }[lang]
    agreement_date_raw = first_table_value(tables, date_labels)
    agreement_date = parse_date_token(agreement_date_raw or "")
    grants, evidence, warnings = parse_grants(text, page_compacts, lang, main_title)
    if not parties:
        warnings.append("계약 당사자 표를 찾지 못함")
    if not agreement_date:
        warnings.append("계약 체결일을 찾지 못함")

    raw = {
        "schema_version": SCHEMA_VERSION,
        "document": {"language": lang},
        "contract": {
            "contract_title": field(contract_title_raw, contract_title_raw),
            "agreement_type": field(agreement_type, contract_title_raw, derived=True),
            "agreement_date": field(agreement_date, agreement_date_raw),
            "parties": parties,
            "rights_grants": grants,
            "payments": extract_payment(text, lang),
            "evidence": evidence,
        },
    }
    normalized = normalize_contract(raw)
    validation = validate_fixture(raw, text)
    payload = {
        "raw": raw,
        "validation": validation,
        "normalized": normalized,
        "compact": project(normalized, file_hash),
    }
    manifest = {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "sourcePath": relative.as_posix(),
        "fileName": path.name,
        "fileHash": file_hash,
        "byteSize": len(data),
        "pageCount": len(page_texts),
        "language": lang,
        "templateFamily": relative.parts[1],
        "agreementType": agreement_type,
        "grantCount": len(grants),
        "confidence": validation["confidence"],
        "routeLevel": validation["route_level"],
        "warnings": warnings,
    }
    return payload, manifest


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    default_input = repo_root.parent / "pdf" / "generated"
    default_output = repo_root / "data" / "generated" / "staging-fixtures"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=default_input)
    parser.add_argument("--output", type=Path, default=default_output)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    pdfs = sorted(args.input.rglob("*.pdf"))
    if args.limit is not None:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        raise SystemExit(f"PDF가 없습니다: {args.input}")

    manifests = []
    for pdf_path in pdfs:
        payload, manifest = parse_pdf(pdf_path, args.input)
        relative_json = Path(manifest["sourcePath"]).with_suffix(".json")
        write_json(args.output / relative_json, payload)
        manifests.append(manifest)
        print(
            f"{manifest['fileName']}: grants={manifest['grantCount']} "
            f"confidence={manifest['confidence']:.3f} warnings={len(manifest['warnings'])}"
        )

    summary = {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "sourceRoot": str(args.input.resolve()),
        "outputRoot": str(args.output.resolve()),
        "documentCount": len(manifests),
        "grantCount": sum(item["grantCount"] for item in manifests),
        "pageCount": sum(item["pageCount"] for item in manifests),
        "routeLevels": dict(Counter(item["routeLevel"] for item in manifests)),
        "warningCount": sum(len(item["warnings"]) for item in manifests),
        "documents": manifests,
    }
    write_json(args.output / "_manifest.json", summary)
    print(json.dumps({key: summary[key] for key in (
        "documentCount", "grantCount", "pageCount", "routeLevels", "warningCount"
    )}, ensure_ascii=False))

    if args.strict and (summary["warningCount"] or summary["routeLevels"].get("RED", 0)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
