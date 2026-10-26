import csv
import io
import json
import os
import re
import time
import html as html_lib
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

import comparison_extras as cx

# ─────────────────────────────────────────────────────────────
# 의약품 허가정보·약가 통합 조회 — Streamlit version
# 기존 Colab 노트북의 API 엔드포인트/필드명/매칭 규칙을 유지합니다.
# ─────────────────────────────────────────────────────────────

MFDS_LIST_URL = "http://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnInq07"
MFDS_DETAIL_URL = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnDtlInq06"
HIRA_PRICE_URL = "https://apis.data.go.kr/B551182/dgamtCrtrInfoService1.2/getDgamtList"

FIELD_BAR_CODE = "BAR_CODE"
LIST_NUM_OF_ROWS = 500
HIRA_CALL_LIMIT = 600
MFDS_CALL_LIMIT = 1000
LIST_CSV_FIELDS = [
    "ITEM_SEQ", "ITEM_NAME", "ENTP_NAME", "CANCEL_NAME", "ITEM_PERMIT_DATE",
    "MAIN_ITEM_INGR", "MAIN_INGR_ENG",
]  # 바코드는 상세 API에서만 확인 가능
BASE_COLUMNS = ["허가제품명", "제약사한글명", "희귀의약품", "약가", "약효분류", "주성분영문명", "성분명", "효능효과", "용법용량"]
HIRA_MEFT_FIELD = "meftDivNo"

# 식약처 상세 응답에서 실제 확인된 직접 필드와 NB_DOC_DATA 문서 섹션입니다.
# 사용자가 체크한 항목만 API 응답/캐시에서 결과로 펼칩니다.
EXTRA_FIELD_SPECS = {
    "희귀의약품": {"label": "희귀의약품", "source": "RARE_DRUG_YN", "transform": "direct"},
    "영문제품명": {"label": "영문 제품명", "source": "ITEM_ENG_NAME", "transform": "direct"},
    "주성분영문명": {"label": "주성분 영문명", "source": "MAIN_INGR_ENG", "transform": "direct"},
    "전문일반구분": {"label": "전문·일반의약품 구분", "source": "ETC_OTC_CODE", "transform": "direct"},
    "ATC코드": {"label": "ATC 코드", "source": "ATC_CODE", "transform": "direct"},
    "원료약품및분량": {"label": "원료약품 및 분량", "source": "MATERIAL_NAME", "transform": "direct"},
    "소아_고령자투여": {"label": "소아·고령자 투여", "source": "NB_DOC_DATA", "keywords": ["소아에 대한 투여", "소아투여", "고령자에 대한 투여", "고령자투여"], "transform": "section"},
    "임부_수유부투여": {"label": "임부 및 수유부 투여", "source": "NB_DOC_DATA", "keywords": ["임부 및 수유부에 대한 투여", "임부, 수유부, 가임여성 및 남성에 대한 투여", "가임여성 및 남성에 대한 투여", "임부에 대한 투여", "수유부에 대한 투여", "임부투여", "수유부투여"], "transform": "section"},
    "금기사항": {"label": "금기사항", "source": "NB_DOC_DATA", "keywords": ["다음 환자에게는 투여하지 말 것", "투여하지 말 것", "금기"], "transform": "section"},
    "신중투여": {"label": "신중히 투여할 환자", "source": "NB_DOC_DATA", "keywords": ["다음 환자에는 신중히 투여할 것", "신중히 투여"], "transform": "section"},
    "일반적주의": {"label": "일반적 주의", "source": "NB_DOC_DATA", "keywords": ["일반적 주의"], "transform": "section"},
    "상호작용": {"label": "상호작용", "source": "NB_DOC_DATA", "keywords": ["상호작용"], "transform": "section"},
    "이상반응": {"label": "이상반응", "source": "NB_DOC_DATA", "keywords": ["이상반응", "이상 반응"], "transform": "section"},
    "과량투여처치": {"label": "과량투여시의 처치", "source": "NB_DOC_DATA", "keywords": ["과량투여시의 처치", "과량투여", "과량 투여"], "transform": "section"},
    "적용상의주의사항": {"label": "적용상의 주의사항", "source": "NB_DOC_DATA", "keywords": ["적용상의 주의", "적용상 주의"], "transform": "section"},
    "기타주의사항": {"label": "기타 사용상 주의사항", "source": "NB_DOC_DATA", "keywords": ["기타"], "transform": "section"},
    "포장단위": {"label": "포장단위", "source": "PACK_UNIT", "transform": "direct"},
    "유효기간": {"label": "유효기간", "source": "VALID_TERM", "transform": "direct"},
    "보관정보": {"label": "보관정보", "source": "STORAGE_METHOD", "transform": "direct"},
    "보관_취급주의사항": {"label": "보관 및 취급상의 주의사항", "source": "NB_DOC_DATA", "keywords": ["보관 및 취급상의 주의사항", "보관 및 취급상의 주의", "보관취급상의주의사항"], "transform": "section"},
    "성상": {"label": "성상", "source": "CHART", "transform": "direct"},
    "변경내용": {"label": "변경내용", "source": "GBN_NAME", "transform": "direct"},
    "변경일자": {"label": "변경일자", "source": "CHANGE_DATE", "transform": "direct"},
}
EXTRA_FIELD_ORDER = [
    "영문제품명", "주성분영문명", "전문일반구분", "ATC코드", "원료약품및분량",
    "소아_고령자투여", "임부_수유부투여",
    "금기사항", "신중투여", "일반적주의",
    "상호작용",
    "이상반응", "과량투여처치",
    "적용상의주의사항", "기타주의사항",
    "포장단위", "유효기간", "보관정보", "보관_취급주의사항", "성상", "변경내용", "변경일자",
]
EXTRA_FIELD_LABELS = {key: EXTRA_FIELD_SPECS[key]["label"] for key in EXTRA_FIELD_ORDER}
EXTRA_FIELD_KEYWORDS = {key: EXTRA_FIELD_SPECS[key]["keywords"] for key in EXTRA_FIELD_ORDER if "keywords" in EXTRA_FIELD_SPECS[key]}
EXTRA_DIRECT_FIELDS = {
    key: spec["source"] for key, spec in EXTRA_FIELD_SPECS.items()
    if spec["transform"] == "direct"
}
NEW_DRUG_PRESET_KEYS = [
    "영문제품명", "ATC코드", "포장단위", "주성분영문명", "원료약품및분량",
    "유효기간", "성상", "전문일반구분", "보관정보", "보관_취급주의사항",
]
ALWAYS_FETCH_DETAIL_KEYS = ["주성분영문명", "희귀의약품"]
RESULT_COLUMN_ORDER = ["구분", "함량", "허가제품명", "원내코드", "제약사한글명", "희귀의약품", "약가", "약효분류", "영문제품명", "주성분영문명", "전문일반구분", "ATC코드", "원료약품및분량", "포장단위", "유효기간", "성상", "보관정보", "성분명", "효능효과", "용법용량"]
HEADING_PATTERN = re.compile(r"^\s*\d+\s*[.\-]")
MAX_RETRY = 5
MFDS_RAW_EXCLUDED_FIELDS = {
    "EE_DOC_DATA", "UD_DOC_DATA", "NB_DOC_DATA", "PN_DOC_DATA", "RARE_DRUG_YN",
}

DUR_CATEGORIES = [
    "병용금기(급여)", "병용금기(비급여)", "임부금기", "연령금기", "효능군중복",
    "수유부주의", "비대면진료처방금지", "비용효과적인함량의약품",
]
DUR_EXTRA_COLUMNS = {
    "임부금기": ["금기등급", "상세정보"],
    "연령금기": ["특정연령", "특정연령단위코드", "연령처리조건", "상세정보"],
    "효능군중복": ["효능군", "Group"],
}
DUR_CODE_COLUMN_PATTERN = re.compile(r"(제품코드|약품코드|품목코드|EDI)", re.IGNORECASE)

DATA_DIR = Path(os.environ.get("DRUG_APP_DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LIST_FILE = DATA_DIR / "허가목록_원본.csv"
TEMP_FILE = DATA_DIR / "허가목록_임시.json"
CACHE_CODE_FILE = DATA_DIR / "cache_약가_코드별.json"
CACHE_NAME_FILE = DATA_DIR / "cache_약가_이름별.json"
CACHE_DETAIL_FILE = DATA_DIR / "cache_상세정보.json"
CACHE_MEFT_FILE = DATA_DIR / "cache_약효분류.json"
LIST_META_FILE = DATA_DIR / "허가목록_메타.json"
KST = timezone(timedelta(hours=9))


def clean_whitespace(text):
    if text is None:
        return ""
    try:
        if pd.isna(text):
            return ""
    except (TypeError, ValueError):
        pass
    return re.sub(r"\s+", " ", str(text)).strip()


def parse_strength(text):
    """제품명에서 대표 함량을 보수적으로 추출합니다. 사용자가 그룹 표에서 수정할 수 있습니다."""
    value = clean_whitespace(text)
    patterns = [
        r"(?i)(\d+(?:\.\d+)?)\s*(마이크로그램|μg|mcg|밀리그램|mg|그램|g)(?:\s*/\s*(\d+(?:\.\d+)?)?\s*(mL|ml|밀리리터|정|캡슐|포|바이알))?",
        r"(?i)(\d+(?:\.\d+)?)\s*(%|IU|U)(?:\s*/\s*(\d+(?:\.\d+)?)?\s*(mL|ml|밀리리터))?",
    ]
    unit_map = {"마이크로그램": "μg", "밀리그램": "mg", "그램": "g", "밀리리터": "mL", "ml": "mL"}
    for pattern in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        groups = match.groups()
        amount = groups[0]
        unit = unit_map.get(groups[1], groups[1])
        if len(groups) >= 4 and groups[3]:
            denominator_amount = groups[2] or "1"
            denominator_unit = unit_map.get(groups[3], groups[3])
            return f"{amount}{unit}/{denominator_amount}{denominator_unit}"
        return f"{amount}{unit}"
    return ""


def group_label(group_id):
    if group_id == "applicant":
        return "신청의약품"
    number = re.sub(r"\D", "", str(group_id)) or "1"
    return f"비교의약품{number}"


def ordered_group_ids(groups):
    comparator_ids = [gid for gid in groups if gid.startswith("comparator_")]
    comparator_ids.sort(key=lambda gid: int(re.sub(r"\D", "", gid) or 0))
    return ["applicant"] + comparator_ids


def ensure_group_state():
    groups = st.session_state.get("groups")
    if not isinstance(groups, dict):
        legacy = [str(seq) for seq in st.session_state.get("selection", []) if str(seq)]
        groups = {
            "applicant": {"label": "신청의약품", "seqs": legacy},
            "comparator_1": {"label": "비교의약품1", "seqs": []},
        }
    groups.setdefault("applicant", {"label": "신청의약품", "seqs": []})
    if not any(gid.startswith("comparator_") for gid in groups):
        groups["comparator_1"] = {"label": "비교의약품1", "seqs": []}
    for gid in ordered_group_ids(groups):
        groups[gid].setdefault("label", group_label(gid))
        groups[gid]["seqs"] = list(dict.fromkeys(str(seq) for seq in groups[gid].get("seqs", []) if str(seq)))
    st.session_state.groups = groups
    st.session_state.setdefault("strength_overrides", {})


def flatten_group_seqs():
    return [seq for gid in ordered_group_ids(st.session_state.groups) for seq in st.session_state.groups[gid]["seqs"]]


def sync_selection_from_groups():
    st.session_state.selection = flatten_group_seqs() if isinstance(st.session_state.get("groups"), dict) else []


def next_comparator_group_id():
    used = [int(re.sub(r"\D", "", gid) or 0) for gid in st.session_state.groups if gid.startswith("comparator_")]
    return f"comparator_{max(used, default=0) + 1}"


def assign_seqs_to_group(target_gid, seqs):
    selected = [str(seq) for seq in seqs if str(seq)]
    for meta in st.session_state.groups.values():
        meta["seqs"] = [seq for seq in meta.get("seqs", []) if seq not in selected]
    target = st.session_state.groups[target_gid]["seqs"]
    target.extend(seq for seq in selected if seq not in target)
    sync_selection_from_groups()


def remove_group_seqs(group_id, seqs):
    removing = {str(seq) for seq in seqs}
    st.session_state.groups[group_id]["seqs"] = [seq for seq in st.session_state.groups[group_id]["seqs"] if seq not in removing]
    for seq in removing:
        st.session_state.strength_overrides.pop(seq, None)
    sync_selection_from_groups()


# ── 콜백 함수 (버튼 on_click용: 콜백은 스크립트 재실행 전에 실행되므로 st.rerun()이 필요 없습니다) ──
def add_to_selection(group_mode, target_gid, seqs):
    """검색 결과에서 선택한 품목을 조회 목록(또는 그룹)에 추가합니다."""
    if group_mode:
        assign_seqs_to_group(target_gid, seqs)
    else:
        selection = st.session_state.selection
        selection.extend(seq for seq in seqs if seq not in selection)


def move_selected_items(delta):
    """'조회할 품목' 표에서 선택(체크)한 행들을 한 칸 위(-1) 또는 아래(+1)로 이동합니다."""
    rendered = st.session_state.get("sel_rendered", [])
    state = st.session_state.get(f"selected_items_table_{st.session_state.get('sel_table_ver', 0)}")
    try:
        rows = list(state["selection"]["rows"]) if state else []
    except (KeyError, TypeError):
        rows = []
    checked = {rendered[i] for i in rows if 0 <= i < len(rendered)}
    selection = st.session_state.selection
    n = len(selection)
    if delta < 0:
        for i in range(1, n):
            if selection[i] in checked and selection[i - 1] not in checked:
                selection[i - 1], selection[i] = selection[i], selection[i - 1]
    else:
        for i in range(n - 2, -1, -1):
            if selection[i] in checked and selection[i + 1] not in checked:
                selection[i + 1], selection[i] = selection[i], selection[i + 1]
    # 순서가 바뀌면 행 번호 기준 선택이 어긋나므로, 표 위젯을 새로 만들어 선택을 초기화합니다.
    st.session_state.sel_table_ver = st.session_state.get("sel_table_ver", 0) + 1


# ── 앱 입력용 파일로 품목 추가 (원내 비교 후보 추출 프로그램에서 만든 파일) ──
APP_INPUT_COLUMNS = ["구분", "약품명", "성분명", "보험코드"]  # 신청번호 열은 있으면 씁니다 (신청의약품별 비교표)
STRENGTH_IN_NAME = re.compile(r"\d+(?:\.\d+)?\s*(?:마이크로그램|밀리그램|그램|밀리리터|mcg|μg|ug|mg|g|ml|mL|%)", re.IGNORECASE)


def normalize_product_name(name):
    """제품명 비교용: 심평원 이름 끝의 '_(규격)'과 띄어쓰기를 빼고 대소문자를 맞춥니다."""
    value = re.sub(r"_\(.*?\)\s*$", "", clean_whitespace(name))
    return re.sub(r"\s+", "", value).casefold()


def product_name_index(rows):
    index = {}
    for row in rows:
        index.setdefault(normalize_product_name(row.get("ITEM_NAME", "")), []).append(row)
    return index


def name_candidates(rows, name, limit=20):
    """자동 연결이 안 될 때 고를 수 있도록, 함량·괄호를 뺀 이름이 들어간 식약처 품목을 보여 줍니다."""
    base = re.sub(r"\(.*?\)|\[.*?\]", "", clean_whitespace(name))
    base = normalize_product_name(STRENGTH_IN_NAME.sub("", base))
    if len(base) < 2:
        return []
    return [row for row in rows if base in normalize_product_name(row.get("ITEM_NAME", ""))][:limit]


# 성분명 비교용: 염·수화물 표기는 뺍니다 (원내 비교 후보 추출 프로그램과 같은 규칙)
SALT_WORDS_KO = [
    "브롬화수소산염", "타르타르산염", "시트르산염", "말레산염", "베실산염", "메실산염", "푸마르산염", "숙신산염",
    "아세트산염", "염산염", "황산염", "인산염", "베실레이트", "삼수화물", "이수화물", "일수화물", "수화물",
    "무수물", "미분화", "나트륨", "칼륨", "칼슘", "마그네슘",
]
SALT_WORDS_EN = [
    "hydrobromide", "hydrochloride", "bitartrate", "tartrate", "citrate", "maleate", "besylate", "besilate",
    "mesylate", "mesilate", "fumarate", "succinate", "phosphate", "acetate", "sulfate", "sulphate", "hcl",
    "monohydrate", "dihydrate", "trihydrate", "hydrate", "anhydrous", "micronized", "micronised",
    "sodium", "potassium", "calcium", "magnesium",
]


def ingredient_keys(text):
    """성분명을 비교용 성분 묶음으로 바꿉니다. 예: '펜타닐시트르산염' → {'펜타닐'}, 'Oxycodone HCl/Naloxone' → {'oxycodone', 'naloxone'}"""
    keys = set()
    for part in re.split(r"[|+/,·;]|\s및\s|\sand\s", clean_ingredient(text or ""), flags=re.IGNORECASE):
        value = re.sub(r"\(.*?\)|\[.*?\]", " ", part).lower()
        value = re.sub(r"^\s*\d+(?:,\d+)*-", "", value)  # 앞의 위치 번호는 뺍니다: '5-fluorouracil' = 'fluorouracil'
        for word in SALT_WORDS_EN:
            value = re.sub(rf"\b{word}\b", " ", value)
        for word in SALT_WORDS_KO:
            value = value.replace(word, " ")
        value = re.sub(r"[^0-9a-z가-힣]", "", value)
        if value:
            keys.add(value)
    return frozenset(keys)


def ingredient_index(rows):
    """성분 묶음 → 식약처 품목 목록. 한글·영문 성분명 둘 다로 찾을 수 있게 만듭니다."""
    index = {}
    for row in rows:
        for keys in {ingredient_keys(row.get("MAIN_ITEM_INGR", "")), ingredient_keys(row.get("MAIN_INGR_ENG", ""))}:
            if keys:
                index.setdefault(keys, []).append(row)
    return index


def ingredient_candidates(index, ingredient, limit=20):
    """이름으로도 못 찾을 때, 성분이 같은 식약처 품목을 후보로 보여 줍니다 (자동 연결은 하지 않음)."""
    return index.get(ingredient_keys(ingredient), [])[:limit]


def link_app_input(frame, rows, mfds_key, hira_key):
    """앱 입력용 파일의 줄마다 식약처 품목을 찾습니다. 비슷한 이름이나 같은 성분만으로는 자동 연결하지 않습니다.

    찾는 순서: EDI(보험)코드 → 한글 약품명 → 성분명
    1) 보험코드 → 심평원 제품명 → 같은 이름의 식약처 품목 → 바코드 4~11번째 = 보험코드 앞 8자리면 자동 연결
    2) 식약처 제품명과 완전히 같으면 자동 연결
    3) 나머지는 후보를 보여 주고 약사가 고름: 보험코드로 찾은 품목 → 이름이 들어간 품목 → 성분이 같은 품목 순
    """
    name_index = product_name_index(rows)
    by_ingredient = None  # 성분으로 찾을 일이 생길 때 한 번만 만듭니다
    cache_detail = load_json_cache(CACHE_DETAIL_FILE)
    call_counter = {"hira": 0, "mfds": 0}
    errors, links = [], []
    for _, row in frame.iterrows():
        edi = next((code for code in (normalize_code_digits(v) for v in str(row.get("보험코드", "")).split()) if code), "")
        name = clean_whitespace(row.get("약품명", ""))
        ingredient = clean_whitespace(row.get("성분명", ""))
        link = {"구분": clean_whitespace(row.get("구분", "")), "입력 약품명": name, "보험코드": edi,
                "seq": "", "연결 품목": "", "방법": "", "후보": [], "후보 근거": ""}
        if edi and hira_key:
            try:
                items = hira_get(hira_key, {"mdsCd": edi})
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"HIRA mdsCd={edi}: {exc}")
                items = []
            for item in (it for it in items if hira_code(it) == edi):
                matches = name_index.get(normalize_product_name(item.get("itmNm", "")), [])
                for match in matches:
                    detail = fetch_detail(match["ITEM_SEQ"], mfds_key, call_counter, cache_detail, [], errors)
                    if any(code[3:11] == edi[:8] for code in split_barcode_values(detail.get("_bar_code", ""))):
                        link.update(seq=match["ITEM_SEQ"], 방법="보험코드 → 심평원 제품명 → 바코드 확인")
                        break
                if link["seq"]:
                    break
                if matches and not link["후보"]:
                    link.update(후보=matches, **{"후보 근거": "보험코드"})
        if not link["seq"]:
            matches = name_index.get(normalize_product_name(name), [])
            if len(matches) == 1:
                link.update(seq=matches[0]["ITEM_SEQ"], 방법="식약처 제품명 완전일치")
            elif not link["후보"]:
                candidates, basis = matches or name_candidates(rows, name), "약품명"
                if not candidates and ingredient:
                    by_ingredient = by_ingredient if by_ingredient is not None else ingredient_index(rows)
                    candidates, basis = ingredient_candidates(by_ingredient, ingredient), "성분명"
                if candidates:
                    link.update(후보=candidates, **{"후보 근거": basis})
        if link["seq"]:
            matched = next(r for r in rows if r.get("ITEM_SEQ") == link["seq"])
            link["연결 품목"] = clean_whitespace(matched.get("ITEM_NAME", ""))
        link["후보"] = [{"ITEM_SEQ": r.get("ITEM_SEQ", ""), "ITEM_NAME": r.get("ITEM_NAME", ""), "ENTP_NAME": r.get("ENTP_NAME", "")}
                       for r in link["후보"]]
        links.append(link)
    save_json_cache(CACHE_DETAIL_FILE, cache_detail)
    return links, errors


def apply_file_links(links, replace):
    """연결된 품목을 신청의약품·비교의약품 그룹에 넣고 그룹 모드를 켭니다. (버튼 on_click용)"""
    if replace:
        st.session_state.groups = {"applicant": {"label": "신청의약품", "seqs": []}}
        st.session_state.strength_overrides = {}
    for index, link in enumerate(links):
        seq = link["seq"]
        if not seq:
            pick = st.session_state.get(f"link_pick_{index}", "")
            seq = pick.rsplit(" · ", 1)[-1] if " · " in pick else ""
        if not seq:
            continue
        if link["구분"] == "신청의약품":
            gid = "applicant"
        else:
            gid = f"comparator_{re.sub(r'[^0-9]', '', link['구분']) or '1'}"
        st.session_state.groups.setdefault(gid, {"label": group_label(gid), "seqs": []})
        assign_seqs_to_group(gid, [seq])
    st.session_state.group_mode = True
    st.session_state.group_mode_previous = True  # 그룹 모드로 바뀔 때 예전 조회 목록이 신청의약품으로 섞이지 않게 합니다.
    st.session_state.file_links = None


def build_group_items(by_seq):
    items = []
    for gid in ordered_group_ids(st.session_state.groups):
        meta = st.session_state.groups[gid]
        for seq in meta["seqs"]:
            row = by_seq.get(seq)
            if not row:
                continue
            parsed = parse_strength(row.get("ITEM_NAME", ""))
            items.append({
                "group_id": gid,
                "group_label": meta["label"],
                "seq": seq,
                "item_name": row.get("ITEM_NAME", ""),
                "entp_name": row.get("ENTP_NAME", ""),
                "parsed_strength": parsed,
                "strength": st.session_state.strength_overrides.get(seq, parsed),
            })
    return items


def apply_all_fields_preset():
    selected = bool(st.session_state.get("preset_all_fields", False))
    for key in EXTRA_FIELD_ORDER:
        st.session_state[f"extra_{key}"] = selected
    st.session_state.preset_new_drug_intro = selected


def apply_new_drug_preset():
    selected = bool(st.session_state.get("preset_new_drug_intro", False))
    for key in NEW_DRUG_PRESET_KEYS:
        st.session_state[f"extra_{key}"] = selected
    st.session_state.preset_all_fields = all(
        st.session_state.get(f"extra_{key}", False) for key in EXTRA_FIELD_ORDER
    )


def sync_field_presets():
    st.session_state.preset_new_drug_intro = all(
        st.session_state.get(f"extra_{key}", False) for key in NEW_DRUG_PRESET_KEYS
    )
    st.session_state.preset_all_fields = all(
        st.session_state.get(f"extra_{key}", False) for key in EXTRA_FIELD_ORDER
    )


def clean_ingredient(text):
    if not text:
        return ""
    return clean_whitespace(re.sub(r"\[[A-Za-z0-9]+\]", "", text))


def sanitize_all_api_fields(fields):
    """전체 조회에서도 원본 XML 문서와 빈값은 제외해 의미 있는 필드만 남깁니다."""
    sanitized = {}
    for key, value in (fields or {}).items():
        key = str(key)
        cleaned = clean_whitespace(value)
        if key in MFDS_RAW_EXCLUDED_FIELDS or key.endswith("_DOC_DATA"):
            continue
        if not cleaned or cleaned.casefold() == "nan":
            continue
        if "</PARAGRAPH>" in cleaned or cleaned.startswith("<DOC "):
            continue
        sanitized[key] = cleaned
    return sanitized


def unescape_html_repeated(text, rounds=3):
    if text is None:
        return ""
    value = str(text)
    for _ in range(max(1, rounds)):
        new_value = html_lib.unescape(value)
        if new_value == value:
            break
        value = new_value
    return value.replace("\xa0", " ").replace("&nbsp;", " ")


def clean_markup(text):
    if not text:
        return ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = unescape_html_repeated(text)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    return clean_whitespace(text)


def parse_nested_doc_xml(xml_str):
    if not xml_str or not xml_str.strip():
        return ""
    try:
        root = ET.fromstring(xml_str.strip())
    except ET.ParseError:
        return clean_markup(xml_str)
    parts = []
    for el in root.iter():
        title = el.get("title")
        if title:
            parts.append(title.strip())
        if el.text and el.text.strip():
            parts.append(el.text.strip())
    return clean_markup(" ".join(parts))


def normalize_section_title(text):
    text = unescape_html_repeated(text)
    text = clean_whitespace(text)
    text = re.sub(r"^\s*\d+\s*[.\-)]\s*", "", text)
    text = re.sub(r"[\s,·ㆍ/()\[\]{}:;]", "", text)
    return text


def parse_doc_sections(xml_str, keywords):
    """중첩 XML에서 title에 특정 키워드가 포함된 상위 항목과 하위 내용 추출."""
    if not xml_str or not xml_str.strip():
        return ""
    try:
        root = ET.fromstring(xml_str.strip())
    except ET.ParseError:
        return ""
    normalized_keywords = [normalize_section_title(keyword) for keyword in keywords if keyword]
    chunks = []
    for el in root.iter():
        title = el.get("title")
        if title and title.strip():
            chunks.append((bool(HEADING_PATTERN.match(title.strip())), title.strip()))
        if el.text and el.text.strip():
            chunks.append((False, el.text.strip()))
    heading_idx = [i for i, (heading, _) in enumerate(chunks) if heading]
    picked = []
    if heading_idx:
        for n, idx in enumerate(heading_idx):
            heading_text = chunks[idx][1]
            normalized_heading = normalize_section_title(heading_text)
            if any(keyword in normalized_heading or normalized_heading in keyword for keyword in normalized_keywords):
                end = heading_idx[n + 1] if n + 1 < len(heading_idx) else len(chunks)
                picked.extend(text for _, text in chunks[idx:end])
    else:
        picked.extend(
            text for _, text in chunks
            if any(keyword in normalize_section_title(text) for keyword in normalized_keywords)
        )
    return clean_markup(" ".join(picked))


def summarize_text(text, max_chars=420, max_sentences=3):
    """의학적 판단을 새로 생성하지 않고, 원문 앞부분과 핵심 문장만 발췌합니다."""
    text = clean_whitespace(text)
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|(?=\d+\.)", text) if part.strip()]
    selected = []
    for sentence in sentences:
        if sentence not in selected:
            selected.append(sentence)
        if len(selected) >= max_sentences:
            break
    summary = " ".join(selected)
    if len(summary) < 80:
        summary = text[:max_chars]
    return summary[:max_chars].rstrip() + ("…" if len(summary) > max_chars else "")


def summarize_usage(text, max_chars=520):
    """용법·용량에서 성인/소아/고령자 등 투여군별 문장을 우선 발췌합니다."""
    text = clean_whitespace(text)
    if not text:
        return ""
    headings = list(re.finditer(r"<[^>]{1,20}>", text))
    if not headings:
        return summarize_text(text, max_chars=max_chars, max_sentences=4)
    parts = []
    for index, match in enumerate(headings):
        start = match.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[start:end].strip()
        if section:
            parts.append(summarize_text(section, max_chars=180, max_sentences=2))
    summary = " ".join(parts)
    return summary[:max_chars].rstrip() + ("…" if len(summary) > max_chars else "")


def make_summary_df(result_df):
    """용법·용량과 효능·효과를 짧게 표시하는 규칙 기반 요약본."""
    summary_df = result_df.copy()
    if "효능효과" in summary_df.columns:
        summary_df["효능효과"] = summary_df["효능효과"].map(lambda value: summarize_text(value))
    if "용법용량" in summary_df.columns:
        summary_df["용법용량"] = summary_df["용법용량"].map(lambda value: summarize_usage(value))
    for column in summary_df.columns:
        # 간단/일반/상세로 바꾼 용법용량 열("용법용량 (일반)" 등)은 이미 요약본이므로 다시 자르지 않습니다.
        if str(column).startswith("용법용량") or column in cx.MANUAL_COLUMNS:
            continue
        if column not in {"효능효과", "용법용량", "허가제품명", "제약사한글명", "약가", "약효분류", "주성분영문명", "영문제품명", "전문일반구분", "ATC코드", "원료약품및분량", "포장단위", "유효기간", "성상", "보관정보"}:
            summary_df[column] = summary_df[column].map(lambda value: summarize_text(value, max_chars=260, max_sentences=2))
    return summary_df


# 효능·효과, 용법·용량 등 긴 문서형 항목은 표시할 때만 줄바꿈을 정리합니다.
# (조회 결과 원본, AI 검토용 JSON에는 원문 그대로 저장되며 단어는 바꾸지 않습니다.)
LAYOUT_COLUMNS = {"효능효과", "용법용량"} | set(EXTRA_FIELD_KEYWORDS)
_KOREAN_ORDER = "가나다라마바사아자차카타파하"


def _sequential_matches(matches, value_of):
    """1, 2, 3… 처럼 순서대로 이어지는 번호만 인정합니다(용량 숫자 등 오탐 방지). 1로 다시 시작하는 것은 허용."""
    accepted, last = [], None
    for match in matches:
        value = value_of(match)
        if value is None:
            continue
        if (last is None and value == 1) or (last is not None and (value == last + 1 or value == 1)):
            accepted.append(match)
            last = value
    return accepted


def layout_long_text(text):
    """번호(1. 2.), 가나다(가. 나.), 원문자(①), 1) 2), <성인>/<소아> 같은 소제목, ※ 앞에서 줄을 나눕니다."""
    value = clean_whitespace(text)
    if not value:
        return ""
    breaks = {}  # 위치 -> 들여쓰기 단계

    for match in re.finditer(r"<[^<>]{1,20}>", value):
        breaks[match.start()] = 0
    for match in re.finditer(r"※", value):
        breaks[match.start()] = 0
    for match in re.finditer(r"[①-⑳]", value):
        breaks.setdefault(match.start(), 2)

    numbered = list(re.finditer(r"(?<![^\s])(\d{1,2})\.(?=\s|[가-힣A-Za-z<(\[])", value))
    for match in _sequential_matches(numbered, lambda m: int(m.group(1))):
        breaks.setdefault(match.start(), 1)

    korean = list(re.finditer(r"(?<![^\s])([가나다라마바사아자차카타파하])\.\s", value))
    for match in _sequential_matches(korean, lambda m: _KOREAN_ORDER.index(m.group(1)) + 1):
        breaks.setdefault(match.start(), 2)

    paren = list(re.finditer(r"(?<![^\s])(\d{1,2})\)\s", value))
    for match in _sequential_matches(paren, lambda m: int(m.group(1))):
        breaks.setdefault(match.start(), 3)

    positions = sorted(breaks)
    if not positions:
        return value
    # 실제로 쓰인 번호 체계 중 가장 바깥 단계를 들여쓰기 없이, 안쪽 단계는 두 칸씩 들여씁니다.
    used_levels = sorted({level for level in breaks.values() if level > 0})
    indent_of = {0: ""}
    indent_of.update({level: "\u00a0\u00a0" * rank for rank, level in enumerate(used_levels)})
    lines, start, level = [], 0, 0
    for position in positions:
        segment = value[start:position].strip()
        if segment:
            lines.append(indent_of[level] + segment)
        start, level = position, breaks[position]
    tail = value[start:].strip()
    if tail:
        lines.append(indent_of[level] + tail)
    return "\n".join(lines)


def apply_text_layout(df):
    """표시용 DataFrame의 긴 문서형 열에만 줄바꿈 정리를 적용합니다."""
    laid_out = df.copy()
    for column in laid_out.columns:
        if column in LAYOUT_COLUMNS:
            laid_out[column] = laid_out[column].map(layout_long_text)
    return laid_out


def format_price(value):
    text = clean_whitespace(value)
    if not text:
        return ""
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return text
    try:
        number = int(digits)
    except ValueError:
        return text
    return f"{number:,}원"


def load_json_cache(path):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                value = json.load(file)
                return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def save_json_cache(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp.replace(path)


def barcode_key8(bar_code):
    if not bar_code:
        return None
    digits = re.sub(r"\D", "", str(bar_code))
    return digits[3:11] if len(digits) >= 11 else None


def mdscd_key8(mds_cd):
    """엑셀에서 숫자로 저장된 코드는 645200020.0 처럼 float로 들어오는데, 그대로
    문자열화하면 소수점의 '0'이 붙어 코드가 틀어지므로 정수로 먼저 변환합니다."""
    if mds_cd is None:
        return None
    if isinstance(mds_cd, float):
        if pd.isna(mds_cd):
            return None
        mds_cd = str(int(mds_cd))
    elif not mds_cd:
        return None
    digits = re.sub(r"\D", "", str(mds_cd))
    return digits[:8] if len(digits) >= 8 else None


def normalize_code_digits(value):
    if value is None:
        return ""
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        value = str(int(value)) if value.is_integer() else str(value)
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return re.sub(r"\D", "", text)


def code_lookup_keys(value):
    digits = normalize_code_digits(value)
    if not digits:
        return []
    keys = [digits]
    key8 = digits[:8] if len(digits) >= 8 else ""
    if key8 and key8 not in keys:
        keys.append(key8)
    return keys


def split_barcode_values(bar_code_text):
    raw = str(bar_code_text or "")
    parts = re.split(r"[,/;\n]+", raw)
    values = []
    for part in parts:
        digits = normalize_code_digits(part)
        if digits:
            values.append(digits)
    return values


def collect_dur_candidate_codes(item_seq, detail):
    candidates = []

    def add_codes(source, raw_value):
        digits = normalize_code_digits(raw_value)
        if not digits:
            return
        for key in code_lookup_keys(digits):
            candidates.append((key, source, digits))

    for barcode in split_barcode_values(detail.get("_bar_code", "")):
        add_codes("바코드", barcode)
    add_codes("EDI코드", detail.get("_edi_code", ""))
    add_codes("품목코드", item_seq)

    deduped = []
    seen = set()
    for item in candidates:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def _excel_engine_for(filename):
    return "pyxlsb" if filename.lower().endswith(".xlsb") else None


def _find_dur_header_row(file_bytes, filename, max_scan=15):
    """제목 행이 위에 몇 줄 더 있는 파일 대응: '코드'가 들어간 열이 나오는 행을 헤더로 판단합니다."""
    engine = _excel_engine_for(filename)
    raw = pd.read_excel(io.BytesIO(file_bytes), header=None, engine=engine, nrows=max_scan)
    for i in range(len(raw)):
        row_vals = [str(v) for v in raw.iloc[i].tolist()]
        if any(DUR_CODE_COLUMN_PATTERN.search(v) for v in row_vals):
            return i
    return 0


def read_dur_excel(file_bytes, filename):
    engine = _excel_engine_for(filename)
    header_row = _find_dur_header_row(file_bytes, filename)
    df = pd.read_excel(io.BytesIO(file_bytes), header=header_row, engine=engine)
    df.columns = [str(c).strip() for c in df.columns]
    return df, header_row


def build_dur_index(df):
    """코드 열이 여러 개인 DUR 파일을 폭넓게 인덱싱합니다.
    - exact digits (예: 073400390)
    - 앞 8자리 key (예: 07340039)
    모두 저장해 바코드/EDI/품목코드 어느 쪽으로도 매칭되기 쉽게 만듭니다.
    """
    code_cols = [c for c in df.columns if DUR_CODE_COLUMN_PATTERN.search(str(c))]
    if not code_cols:
        return {}, code_cols
    idx = {}
    for row_number, (_, row) in enumerate(df.iterrows(), start=1):
        row_dict = row.to_dict()
        for col in code_cols:
            digits = normalize_code_digits(row.get(col))
            if not digits:
                continue
            payload = {
                "row": row_dict,
                "_dur_code_column": str(col),
                "_dur_code_value": digits,
                "_dur_row_number": row_number,
            }
            for key in code_lookup_keys(digits):
                idx.setdefault(key, []).append(payload)
    return idx, code_cols


@st.cache_data(show_spinner="DUR 파일을 읽는 중입니다…")
def parse_dur_excel_cached(file_bytes, filename):
    """파일 내용(바이트)+이름이 그대로면 캐시된 결과를 재사용해, 다른 위젯을 조작할 때마다
    무거운 엑셀을 다시 파싱하지 않도록 합니다."""
    df, header_row = read_dur_excel(file_bytes, filename)
    index, code_columns = build_dur_index(df)
    return df, header_row, index, code_columns


def _items_from_body(body):
    items = body.get("items", []) if isinstance(body, dict) else []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items or []


def _parse_response_items(resp, api_name):
    resp.raise_for_status()
    text = resp.text.strip()
    if text.startswith("<"):
        root = ET.fromstring(text)
        result_code = root.findtext(".//resultCode")
        if result_code and result_code != "00":
            raise ValueError(f"{api_name} API 오류: {root.findtext('.//resultMsg')}")
        return [{child.tag: (child.text or "") for child in item_el} for item_el in root.findall(".//items/item")]
    data = resp.json()
    body = data.get("body", data.get("response", {}).get("body", {}))
    return _items_from_body(body)


def hira_get(service_key, params):
    query = {"serviceKey": service_key, "type": "json"}
    query.update(params)
    return _parse_response_items(requests.get(HIRA_PRICE_URL, params=query, timeout=30), "HIRA")


def parse_hira_date(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError:
        return None


def select_effective_hira_item(items, as_of_date):
    """기준일에 유효한 약가 중 적용 시작일이 가장 최근인 이력을 선택합니다."""
    eligible = []
    for item in items:
        if clean_whitespace(item.get("payTpNm", "")).lower() in {"삭제", "deleted"}:
            continue
        if clean_whitespace(item.get("delYn", "")).lower() == "y":
            continue
        start = parse_hira_date(item.get("adtStaDd"))
        end = parse_hira_date(item.get("sellEptDd"))
        if start is None or start > as_of_date:
            continue
        if end is not None and end < as_of_date:
            continue
        eligible.append((start, item))
    if not eligible:
        return None
    eligible.sort(key=lambda pair: pair[0], reverse=True)
    return eligible[0][1]


def match_price(item_name, bar_code, service_key, call_counter, cache_code, cache_name, errors, as_of_date):
    key8 = barcode_key8(bar_code)
    as_of_key = as_of_date.isoformat()
    if key8:
        cache_key = f"{key8}|{as_of_key}"
        cached = cache_code.get(cache_key)
        if isinstance(cached, dict):
            return cached.get("mxCprc", ""), "bar_code_8자리(기준일 캐시)", cached
        if call_counter["hira"] < HIRA_CALL_LIMIT:
            call_counter["hira"] += 1
            try:
                items = hira_get(service_key, {"mdsCd": key8})
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"HIRA mdsCd={key8}: {exc}")
                items = []
            exact = [it for it in items if mdscd_key8(it.get("mdsCd")) == key8]
            selected = select_effective_hira_item(exact, as_of_date)
            if selected:
                cache_code[cache_key] = selected
                return selected.get("mxCprc", ""), "bar_code_8자리(기준일 직접조회)", selected
    name_key = re.sub(r"_\(.*?\)\s*$", "", item_name or "").strip()
    name_cache_key = f"{name_key}|{as_of_key}"
    if isinstance(cache_name.get(name_cache_key), dict):
        selected = cache_name[name_cache_key]
    else:
        if call_counter["hira"] >= HIRA_CALL_LIMIT:
            return "", "호출한도초과", None
        call_counter["hira"] += 1
        call_ok = True
        try:
            items = hira_get(service_key, {"itmNm": name_key})
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"HIRA itmNm={name_key}: {exc}")
            items, call_ok = [], False
        valid = [it for it in items if it.get("payTpNm") != "삭제"]
        selected = None
        cached = ""
        if key8:
            exact = [it for it in valid if mdscd_key8(it.get("mdsCd")) == key8]
            selected = select_effective_hira_item(exact, as_of_date)
            if selected:
                cache_code[f"{key8}|{as_of_key}"] = selected
        if not selected:
            def norm(name):
                return re.sub(r"_\(.*?\)\s*$", "", name or "").strip()
            exact_name = [it for it in valid if norm(it.get("itmNm")) == name_key]
            selected = select_effective_hira_item(exact_name, as_of_date)
        if call_ok:
            cache_name[name_cache_key] = selected or {}
    if selected:
        return selected.get("mxCprc", ""), "품목명검색(8자리검증 또는 완전일치, 기준일 적용)", selected
    return "", "기준일 유효 약가 매칭없음", None


HIRA_PACK_FIELD_HINTS = ("unit", "pack", "pkg", "spec")


def hira_code(item):
    """심평원 약제 코드(mdsCd, 보통 9자리)를 숫자 문자열로 반환합니다."""
    return normalize_code_digits((item or {}).get("mdsCd"))


def hira_package_hint(item):
    """심평원 응답 필드 중 이름에 unit/pack/pkg/spec이 들어간 값을 포장·규격 힌트로 모읍니다."""
    parts = []
    for key, value in (item or {}).items():
        lowered = str(key).lower()
        if lowered == "mdscd" or not any(hint in lowered for hint in HIRA_PACK_FIELD_HINTS):
            continue
        text = clean_whitespace(value)
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


def effective_items_by_code(items, as_of_date):
    """제품코드(mdsCd)별로 기준일에 유효한 약가 이력 1건씩을 골라 코드순으로 반환합니다."""
    groups = {}
    for item in items:
        code = hira_code(item)
        if code:
            groups.setdefault(code, []).append(item)
    picked = []
    for code in sorted(groups):
        selected = select_effective_hira_item(groups[code], as_of_date)
        if selected:
            picked.append(selected)
    return picked


def match_prices(item_name, bar_code, service_key, call_counter, cache_code, cache_name, errors, as_of_date):
    """식약처 품목 1개에 연결된 심평원 약가를 포장(제품코드)별로 모두 찾습니다.
    반환: (약가 항목 리스트, 매칭근거 문자열). 항목이 1개면 기존과 같은 결과입니다."""
    as_of_key = as_of_date.isoformat()
    keys8, codes9 = [], []
    for barcode in split_barcode_values(bar_code):
        if len(barcode) >= 11 and barcode[3:11] not in keys8:
            keys8.append(barcode[3:11])
        if len(barcode) >= 12 and barcode[3:12] not in codes9:
            codes9.append(barcode[3:12])

    found, all_cached = [], True
    for key8 in keys8:
        cache_key = f"{key8}|{as_of_key}|all"
        cached = cache_code.get(cache_key)
        if isinstance(cached, list):
            found.extend(cached)
            continue
        if call_counter["hira"] >= HIRA_CALL_LIMIT:
            continue
        call_counter["hira"] += 1
        all_cached = False
        try:
            items = hira_get(service_key, {"mdsCd": key8})
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"HIRA mdsCd={key8}: {exc}")
            continue
        exact = [it for it in items if mdscd_key8(it.get("mdsCd")) == key8]
        picked = effective_items_by_code(exact, as_of_date)
        if picked:
            cache_code[cache_key] = picked
        found.extend(picked)

    # 8자리 조회로 하나도 못 찾았을 때만, 바코드에서 얻은 9자리 코드로 정확 조회를 시도합니다.
    if not found:
        for code9 in codes9:
            cache_key = f"{code9}|{as_of_key}|code9"
            cached = cache_code.get(cache_key)
            if isinstance(cached, list):
                found.extend(cached)
                continue
            if call_counter["hira"] >= HIRA_CALL_LIMIT:
                continue
            call_counter["hira"] += 1
            all_cached = False
            try:
                items = hira_get(service_key, {"mdsCd": code9})
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"HIRA mdsCd={code9}: {exc}")
                continue
            exact = [it for it in items if hira_code(it) == code9]
            picked = effective_items_by_code(exact, as_of_date)
            cache_code[cache_key] = picked
            found.extend(picked)

    if found:
        unique = {hira_code(it): it for it in found}
        prices = [unique[code] for code in sorted(unique)]
        method = "bar_code_8자리(기준일 캐시)" if all_cached else "bar_code_8자리(기준일 직접조회)"
        if len(prices) > 1:
            method += f", 포장별 {len(prices)}건"
        return prices, method

    name_key = re.sub(r"_\(.*?\)\s*$", "", item_name or "").strip()
    name_cache_key = f"{name_key}|{as_of_key}|all"
    cached = cache_name.get(name_cache_key)
    if isinstance(cached, list):
        prices = cached
    else:
        if call_counter["hira"] >= HIRA_CALL_LIMIT:
            return [], "호출한도초과"
        call_counter["hira"] += 1
        call_ok = True
        try:
            items = hira_get(service_key, {"itmNm": name_key})
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"HIRA itmNm={name_key}: {exc}")
            items, call_ok = [], False
        valid = [it for it in items if it.get("payTpNm") != "삭제"]
        prices = []
        for key8 in keys8:
            exact = [it for it in valid if mdscd_key8(it.get("mdsCd")) == key8]
            prices = effective_items_by_code(exact, as_of_date)
            if prices:
                break
        if not prices:
            def norm(name):
                return re.sub(r"_\(.*?\)\s*$", "", name or "").strip()
            exact_name = [it for it in valid if norm(it.get("itmNm")) == name_key]
            prices = effective_items_by_code(exact_name, as_of_date)
        if call_ok:
            cache_name[name_cache_key] = prices
    if prices:
        method = "품목명검색(8자리검증 또는 완전일치, 기준일 적용)"
        if len(prices) > 1:
            method += f", 포장별 {len(prices)}건"
        return prices, method
    return [], "기준일 유효 약가 매칭없음"


def price_line_label(item, all_items):
    """약가 한 줄 앞에 붙일 라벨: 제품코드 + (포장·규격 힌트)."""
    code = hira_code(item)
    hint = hira_package_hint(item)
    names = {clean_whitespace(it.get("itmNm", "")) for it in all_items}
    if len(names) > 1:
        name = clean_whitespace(item.get("itmNm", ""))
        suffix = re.search(r"_\((.*?)\)\s*$", name)
        extra = suffix.group(1) if suffix else name
        if extra and extra not in hint:
            hint = f"{hint} {extra}".strip()
    return f"{code} ({hint})" if hint else code


def format_price_cell(price_items):
    """약가 1건이면 기존과 같은 '1,309원', 여러 건이면 포장(제품코드)별로 줄을 나눠 모두 표시합니다."""
    if not price_items:
        return ""
    if len(price_items) == 1:
        return format_price(price_items[0].get("mxCprc", ""))
    return "\n".join(
        f"{price_line_label(item, price_items)}: {format_price(item.get('mxCprc', ''))}"
        for item in price_items
    )


def join_hira_field(price_items, key):
    """약가가 여러 건이면 약가 칸과 같은 순서로 줄바꿈해 이어 붙입니다."""
    return "\n".join(clean_whitespace(item.get(key, "")) for item in price_items)


def get_effect_classification(item_name, bar_code, service_key, call_counter, cache_meft, errors):
    """심평원 응답의 meftDivNo를 항상 조회해 약효분류로 반환합니다."""
    key8 = barcode_key8(bar_code)
    cache_key = f"mdsCd:{key8}" if key8 else f"itmNm:{re.sub(r'_\(.*?\)\s*$', '', item_name or '').strip()}"
    if cache_key in cache_meft:
        return cache_meft[cache_key]
    if call_counter["hira"] >= HIRA_CALL_LIMIT:
        return ""
    call_counter["hira"] += 1
    try:
        params = {"mdsCd": key8} if key8 else {"itmNm": re.sub(r"_\(.*?\)\s*$", "", item_name or "").strip()}
        items = hira_get(service_key, params)
    except (requests.RequestException, ValueError) as exc:
        errors.append(f"HIRA 약효분류 {cache_key}: {exc}")
        return ""
    valid = [item for item in items if item.get("payTpNm") != "삭제"]
    if key8:
        valid = [item for item in valid if mdscd_key8(item.get("mdsCd")) == key8] or valid
    value = clean_whitespace(valid[0].get(HIRA_MEFT_FIELD, "")) if valid else ""
    cache_meft[cache_key] = value
    return value


def fetch_detail(item_seq, service_key, call_counter, cache_detail, wanted_extras, errors, include_all_fields=False):
    cached = cache_detail.get(item_seq, {})
    # 효능효과·용법용량이 비어서 저장된 기록은 완성된 것으로 보지 않고 다시 조회합니다.
    # (식약처가 문서 항목을 비워 보내는 날이 있어, 그 빈 값이 계속 남지 않게 합니다)
    have_base = "성분명" in cached and bool(cached.get("효능효과") or cached.get("용법용량"))
    missing_extras = [key for key in wanted_extras if key not in cached or not clean_whitespace(cached.get(key, ""))]
    have_all_fields = "_all_api_fields" in cached
    if have_base and not missing_extras and (not include_all_fields or have_all_fields):
        return cached
    cached_direct_ready = all(
        key not in EXTRA_DIRECT_FIELDS or ("_raw_" + key) in cached
        for key in missing_extras
    )
    if have_base and "_raw_nb_xml" in cached and cached_direct_ready and (not include_all_fields or have_all_fields):
        for key in missing_extras:
            if key in EXTRA_DIRECT_FIELDS:
                cached[key] = cached.get("_raw_" + key, "")
            else:
                cached[key] = parse_doc_sections(cached["_raw_nb_xml"], EXTRA_FIELD_KEYWORDS[key])
        cache_detail[item_seq] = cached
        return cached
    if call_counter["mfds"] >= MFDS_CALL_LIMIT:
        return cached if cached else {"성분명": "", "효능효과": "", "용법용량": ""}
    call_counter["mfds"] += 1
    params = {"serviceKey": service_key, "item_seq": item_seq, "type": "json"}
    try:
        items = _parse_response_items(requests.get(MFDS_DETAIL_URL, params=params, timeout=30), "MFDS 상세")
        if not items:
            errors.append(f"MFDS 상세 item_seq={item_seq}: items 없음")
            return cached if cached else {"성분명": "", "효능효과": "", "용법용량": ""}
        item = items[0]
    except (requests.RequestException, ValueError, ET.ParseError) as exc:
        errors.append(f"MFDS 상세 item_seq={item_seq}: {exc}")
        return cached if cached else {"성분명": "", "효능효과": "", "용법용량": ""}
    nb_xml = item.get("NB_DOC_DATA", "")
    cached["성분명"] = clean_ingredient(item.get("MAIN_ITEM_INGR", ""))
    cached["효능효과"] = parse_nested_doc_xml(item.get("EE_DOC_DATA", ""))
    cached["용법용량"] = parse_nested_doc_xml(item.get("UD_DOC_DATA", ""))
    # 목록 API(getDrugPrdtPrmsnInq07)에는 바코드 필드가 없으므로, 상세 API 응답에서 받아 캐시합니다.
    cached["_bar_code"] = item.get("BAR_CODE", "")
    cached["_edi_code"] = item.get("EDI_CODE", "")
    cached["_raw_nb_xml"] = nb_xml
    cached["_all_api_fields"] = sanitize_all_api_fields({
        str(key): clean_whitespace(value)
        for key, value in item.items()
        if not isinstance(value, (dict, list))
    })
    for key, field in EXTRA_DIRECT_FIELDS.items():
        cached["_raw_" + key] = clean_whitespace(item.get(field, ""))
    for key in wanted_extras:
        cached[key] = cached.get("_raw_" + key, "") if key in EXTRA_DIRECT_FIELDS else parse_doc_sections(nb_xml, EXTRA_FIELD_KEYWORDS[key])
    cache_detail[item_seq] = cached
    return cached


def _mask_key(text, key):
    """화면에 보여 줄 글에서 인증키를 가립니다."""
    text = str(text)
    for value in {key, requests.utils.quote(key or "", safe="")}:
        if value:
            text = text.replace(value, "****")
    return re.sub(r"(serviceKey=)[^&\s]+", r"\1****", text)


def diagnose_mfds_detail(item_seq, service_key):
    """식약처 상세 API 응답에서 효능효과(EE)·용법용량(UD)·주의사항(NB) 문서가 어떻게 오는지 요약합니다."""
    lines = [f"주소: {MFDS_DETAIL_URL}", f"품목기준코드: {item_seq}"]
    for response_type in ("json", "xml"):
        lines.append(f"\n[type={response_type}]")
        resp = None
        try:
            resp = requests.get(MFDS_DETAIL_URL, params={"serviceKey": service_key, "item_seq": item_seq, "type": response_type}, timeout=30)
            lines.append(f"HTTP {resp.status_code} · {resp.headers.get('Content-Type', '')} · {len(resp.text):,}자")
            items = _parse_response_items(resp, "MFDS 상세")
        except Exception as exc:  # 점검 화면이라 어떤 오류든 그대로 보여 줍니다 (키는 가림).
            lines.append(f"오류: {_mask_key(exc, service_key)}")
            if resp is not None:
                lines.append(f"응답 앞부분: {_mask_key(resp.text[:300], service_key)}")
            continue
        if not items:
            lines.append(f"items 없음. 응답 앞부분: {_mask_key(resp.text[:300], service_key)}")
            continue
        item = items[0]
        lines.append(f"받은 항목 {len(item)}개: {', '.join(list(item)[:40])}")
        for field in ("EE_DOC_DATA", "UD_DOC_DATA", "NB_DOC_DATA"):
            value = item.get(field)
            if value is None:
                lines.append(f"{field}: 항목 자체가 없음")
                continue
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            parsed = parse_nested_doc_xml(text)
            lines.append(f"{field}: 형식 {type(value).__name__}, {len(text):,}자, 읽은 글 {len(parsed):,}자")
            lines.append(f"  앞부분: {text[:200]!r}")
    return "\n".join(lines)


def current_kst_date():
    return datetime.now(KST).date().isoformat()


def list_cache_is_fresh():
    if not LIST_FILE.exists() or not LIST_META_FILE.exists():
        return False
    try:
        with LIST_META_FILE.open("r", encoding="utf-8") as file:
            meta = json.load(file)
        if meta.get("collected_date_kst") != current_kst_date():
            return False
        with LIST_FILE.open("r", encoding="utf-8-sig", newline="") as file:
            cached_fields = set(next(csv.reader(file), []))
        return set(LIST_CSV_FIELDS).issubset(cached_fields)
    except (OSError, json.JSONDecodeError):
        return False


def fetch_list_page(page, mfds_key):
    params = {"serviceKey": mfds_key, "pageNo": page, "numOfRows": LIST_NUM_OF_ROWS, "type": "json"}
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = requests.get(MFDS_LIST_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            body = data.get("body", data.get("response", {}).get("body", {}))
            return body, _items_from_body(body)
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 30))
    raise last_err


# cache_data → cache_resource: cache_data는 호출할 때마다 수만 건 목록을 복사(역직렬화)하지만,
# cache_resource는 같은 객체를 그대로 돌려주므로 매 재실행마다 드는 비용이 거의 없습니다.
# (반환된 목록은 읽기 전용으로만 사용하세요.)
@st.cache_resource(show_spinner=False)
def load_permitted_drugs(mfds_key, data_dir_string, cache_day, force_refresh_token=0):
    list_file = Path(data_dir_string) / "허가목록_원본.csv"
    temp_file = Path(data_dir_string) / "허가목록_임시.json"
    meta_file = Path(data_dir_string) / "허가목록_메타.json"

    cache_is_fresh = list_file.exists() and meta_file.exists()
    if cache_is_fresh:
        try:
            with meta_file.open("r", encoding="utf-8") as file:
                cache_is_fresh = json.load(file).get("collected_date_kst") == cache_day
            if cache_is_fresh:
                with list_file.open("r", encoding="utf-8-sig", newline="") as file:
                    cached_fields = set(next(csv.reader(file), []))
                cache_is_fresh = set(LIST_CSV_FIELDS).issubset(cached_fields)
        except (OSError, json.JSONDecodeError):
            cache_is_fresh = False

    if cache_is_fresh:
        with list_file.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))

    if not mfds_key:
        raise ValueError("오늘 날짜의 허가목록 캐시가 없습니다. 식약처 인증키를 입력해야 허가목록을 갱신할 수 있습니다.")

    if temp_file.exists():
        with temp_file.open("r", encoding="utf-8") as file:
            resume = json.load(file)
        all_rows, page, total_count = resume["rows"], resume["next_page"], resume.get("total_count")
    else:
        all_rows, page, total_count = [], 1, None

    progress = st.progress(0, text="식약처 허가목록을 수집하는 중입니다…")
    while True:
        body, items = fetch_list_page(page, mfds_key)
        if total_count is None:
            total_count = int(body.get("totalCount", 0))
        if not items:
            break
        all_rows.extend(items)
        page += 1
        if total_count:
            progress.progress(min(len(all_rows) / total_count, 1.0), text=f"허가목록 수집 중: {len(all_rows):,}/{total_count:,}")
        if page % 10 == 0 or (total_count and len(all_rows) >= total_count):
            with temp_file.open("w", encoding="utf-8") as file:
                json.dump({"rows": all_rows, "next_page": page, "total_count": total_count}, file, ensure_ascii=False)
        if total_count and len(all_rows) >= total_count:
            break
        time.sleep(0.1)
    progress.empty()

    with list_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LIST_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in LIST_CSV_FIELDS} for row in all_rows)
    if temp_file.exists():
        temp_file.unlink()
    with meta_file.open("w", encoding="utf-8") as file:
        json.dump({"collected_date_kst": cache_day, "updated_at": datetime.now(KST).isoformat()}, file, ensure_ascii=False, indent=2)
    return all_rows


def detail_cache_mtime():
    return CACHE_DETAIL_FILE.stat().st_mtime if CACHE_DETAIL_FILE.exists() else 0


@st.cache_resource(show_spinner=False)
def build_search_index(_normal_rows, cache_day, row_count, detail_mtime):
    """검색용 소문자 문자열과 성분명 경량 캐시를 한 번만 만들어 재사용합니다.
    상세 조회를 하면 캐시 파일 수정시간(detail_mtime)이 바뀌어 인덱스가 한 번 다시 만들어집니다."""
    detail = load_json_cache(CACHE_DETAIL_FILE)
    index, light = [], {}
    for row in _normal_rows:
        seq = str(row.get("ITEM_SEQ", ""))
        d = detail.get(seq, {})
        ingr, ingr_eng = d.get("성분명", ""), d.get("주성분영문명", "")
        blob = " ".join(str(v) for v in [
            row.get("ITEM_NAME", ""), row.get("ENTP_NAME", ""),
            row.get("MAIN_ITEM_INGR", ""), row.get("MAIN_INGR_ENG", ""),
            ingr, ingr_eng,
        ]).casefold()
        index.append((blob, row))
        light[seq] = (ingr, ingr_eng)
    return index, light


def order_result_columns(df):
    """기본 순서대로 열을 정렬하고, 사람이 채우는 행(code open, 처방건수, 비급여)은 맨 끝에 둡니다."""
    def canonical(column):
        return "용법용량" if str(column).startswith("용법용량 (") else column

    by_canonical = {canonical(column): column for column in df.columns}
    tail = [column for column in cx.MANUAL_TAIL_COLUMNS if column in df.columns]
    ordered = [by_canonical[column] for column in RESULT_COLUMN_ORDER if column in by_canonical]
    ordered += [by_canonical[column] for column in EXTRA_FIELD_ORDER if column in by_canonical and by_canonical[column] not in ordered]
    ordered += [column for column in df.columns if column not in ordered and column not in tail]
    return df[ordered + tail]


def apply_dosage_version(df, choice):
    """용법용량 열을 고른 버전(간단/일반/상세)으로 바꾸고 열 이름을 '용법용량 (일반)'처럼 바꿉니다.
    행 순서는 조회 순서와 같아야 하므로, 정렬하기 전의 조회 결과에 적용합니다."""
    summaries = st.session_state.get("last_dosage")
    level = cx.resolve_dosage_choice(choice, summaries)
    if level == "원문" or "용법용량" not in df.columns:
        return df, "원문"
    seqs = st.session_state.get("last_seqs", [])
    applied = df.copy()
    applied["용법용량"] = [
        cx.dosage_cell(
            summaries["items"].get(str(seqs[position])) if position < len(seqs) else None,
            level,
            applied["용법용량"].iloc[position],
        )
        for position in range(len(applied))
    ]
    return applied.rename(columns={"용법용량": f"용법용량 ({level})"}), level


def dosage_products(reference_bundle):
    """용법·용량 요약에 넘길 제품 목록. 원내코드 같은 대외비 값은 넣지 않습니다."""
    return [
        {
            "id": str(product["mfds"]["item_seq"]),
            "name": product["mfds"]["product_name"],
            "dosage_text": product["mfds"]["dosage_text"],
            "indications_text": product["mfds"]["indications_text"],
        }
        for product in reference_bundle.get("products", [])
    ]


def make_display_df(result_df, summary_view=False, transpose_view=False):
    display_df = make_summary_df(result_df) if summary_view else result_df.copy()
    display_df = apply_text_layout(display_df)
    display_df = order_result_columns(display_df)
    if transpose_view:
        display_df = display_df.T
        display_df.index.name = "항목"
    return display_df


def result_column_config(df):
    """긴 텍스트는 넓게 시작하고, Streamlit 표에서 드래그로 폭을 조절합니다."""
    config = {}
    long_columns = {"효능효과", "용법용량", "성분명", "이상반응", "상호작용", "금기사항", "원료약품및분량"}
    for column in df.columns:
        config[column] = st.column_config.TextColumn(
            label=str(column),
            width="large" if column in long_columns else "medium",
            help="헤더 경계를 드래그해 컬럼 너비를 조절할 수 있습니다.",
        )
    return config


def filter_result_dataframe(df, widget_prefix="result_filter"):
    """컬럼별 필터를 적용해 결과 DataFrame을 반환합니다."""
    filtered = df.copy()
    with st.expander("컬럼별 필터", expanded=False):
        st.caption("문자열은 포함 검색, 범주형은 여러 값 선택, 숫자형은 범위 필터를 사용합니다.")
        filter_columns = st.columns(2)
        for index, column in enumerate(df.columns):
            series = df[column].fillna("")
            numeric = pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")
            numeric_ratio = numeric.notna().mean() if len(series) else 0
            with filter_columns[index % 2]:
                if numeric_ratio >= 0.8 and numeric.notna().any():
                    minimum, maximum = float(numeric.min()), float(numeric.max())
                    if minimum < maximum:
                        selected_range = st.slider(
                            str(column), minimum, maximum, (minimum, maximum), key=f"{widget_prefix}_num_{index}"
                        )
                        filtered = filtered[numeric.loc[filtered.index].between(*selected_range)]
                    else:
                        st.caption(f"{column}: {minimum:g}")
                else:
                    values = sorted({str(value) for value in series if str(value).strip()})
                    if 0 < len(values) <= 30:
                        selected_values = st.multiselect(
                            str(column), values, key=f"{widget_prefix}_cat_{index}"
                        )
                        if selected_values:
                            filtered = filtered[filtered[column].astype(str).isin(selected_values)]
                    else:
                        text = st.text_input(f"{column} 포함 검색", key=f"{widget_prefix}_text_{index}")
                        if text.strip():
                            filtered = filtered[filtered[column].astype(str).str.contains(text.strip(), case=False, na=False)]
    return filtered


def render_resizable_wrapped_table(display_df, show_index=False, height=720, table_key="result"):
    """외부 라이브러리 없이 컬럼 드래그 리사이즈와 셀 줄바꿈을 함께 제공합니다."""
    table_df = display_df.reset_index() if show_index else display_df.reset_index(drop=True)
    if show_index:
        table_df = table_df.rename(columns={table_df.columns[0]: str(display_df.index.name or "항목")})

    headers = [str(column) for column in table_df.columns]
    long_columns = {"효능효과", "용법용량", "성분명", "이상반응", "상호작용", "금기사항", "원료약품및분량"}
    narrow_columns = {"약가", "제약사한글명", "약효분류"}

    def cell(value):
        if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
            value = ""
        return html_lib.escape(str(value)).replace("\\n", "<br>").replace("\n", "<br>")

    if show_index:
        # 행/열 전환 보기: 약 하나가 세로줄 하나가 됩니다. 맨 앞(항목명) 열만 고정 폭으로 두고,
        # 나머지 약 컬럼들은 화면 폭에서 그 만큼을 뺀 나머지를 균등하게 나눠 갖도록 %로 지정합니다.
        # 그래서 화면을 늘리면 약별 폭이 넓어지고, 줄이면 좁아지며 전체 약이 한 화면에 들어옵니다.
        index_width_px = 160
        drug_column_count = max(len(headers) - 1, 1)
        col_widths = [f"{index_width_px}px"] + [
            f"calc((100% - {index_width_px}px) / {drug_column_count})"
        ] * drug_column_count
    else:
        def width_for(header):
            if header in narrow_columns:
                return 200
            if header == "허가제품명":
                return 1000
            if header in long_columns:
                return 720
            return 360
        col_widths = [f"{width_for(header)}px" for header in headers]

    colgroup = "".join(
        f'<col data-column="{index}" style="width:{width}">' for index, width in enumerate(col_widths)
    )
    header_html = "".join(f'<th data-column="{index}">{cell(header)}<span class="resize-handle" data-column="{index}"></span></th>' for index, header in enumerate(headers))
    body_html = []
    for row in table_df.itertuples(index=False, name=None):
        body_html.append("<tr>" + "".join(f"<td>{cell(value)}</td>" for value in row) + "</tr>")

    table_width_css = "width:100%;" if show_index else "width:max-content; min-width:100%;"
    markup = f"""
    <style>
      html, body {{ margin:0; padding:0; background:#fff; font-family:Arial, sans-serif; }}
      .table-wrap {{ width:100%; height:calc(100vh - 24px); overflow:auto; border:1px solid #d9dee7; }}
      table {{ border-collapse:collapse; table-layout:fixed; {table_width_css} font-size:13px; }}
      col {{ width:360px; }}
      th, td {{ border:1px solid #d9dee7; padding:8px; vertical-align:top; white-space:normal; overflow-wrap:anywhere; word-break:break-word; line-height:1.45; }}
      th {{ position:sticky; top:0; z-index:2; background:#f3f6fa; font-weight:700; text-align:left; user-select:none; }}
      .resize-handle {{ position:absolute; top:0; right:-4px; width:8px; height:100%; cursor:col-resize; z-index:3; }}
      .resize-handle:hover, .resizing {{ background:#5b8def; opacity:.55; }}
      body.resizing {{ cursor:col-resize; user-select:none; }}
      @media (prefers-color-scheme: dark) {{
        html, body {{ background:#111923; color:#e6edf5; color-scheme:dark; }}
        .table-wrap {{ border-color:#344354; background:#111923; }}
        th, td {{ border-color:#344354; color:#e6edf5; }}
        th {{ background:#1b2a3a; color:#f5f9fd; }}
        tr:nth-child(even) td {{ background:#151f2b; }}
        tr:hover td {{ background:#1b3142; }}
        .resize-handle:hover, .resizing {{ background:#42c7c1; }}
      }}
    </style>
    <div class="table-wrap" id="wrap-{table_key}">
      <table id="table-{table_key}"><colgroup>{colgroup}</colgroup><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_html)}</tbody></table>
    </div>
    <script>
      (() => {{
        const table = document.getElementById('table-{table_key}');
        const cols = table.querySelectorAll('col');
        table.querySelectorAll('.resize-handle').forEach(handle => {{
          handle.addEventListener('mousedown', event => {{
            event.preventDefault();
            const index = Number(handle.dataset.column);
            const startX = event.clientX;
            const startWidth = cols[index].getBoundingClientRect().width;
            document.body.classList.add('resizing');
            handle.classList.add('resizing');
            const move = moveEvent => {{
              const nextWidth = Math.max(120, startWidth + moveEvent.clientX - startX);
              cols[index].style.width = nextWidth + 'px';
            }};
            const stop = () => {{
              document.body.classList.remove('resizing');
              handle.classList.remove('resizing');
              document.removeEventListener('mousemove', move);
              document.removeEventListener('mouseup', stop);
            }};
            document.addEventListener('mousemove', move);
            document.addEventListener('mouseup', stop);
          }});
        }});
      }})();
    </script>
    """
    components.html(markup, height=height, scrolling=False)


def make_comparison_df(result_df):
    """각 품목을 독립된 열로 표시하며 신청의약품은 맨 오른쪽에 배치합니다."""
    comparison, comparison_names = comparison_columns(result_df)
    comparison["_비교용약품명"] = comparison_names
    result = comparison.set_index("_비교용약품명").T
    result.index.name = "조회 항목"
    return result


def comparison_columns(result_df):
    """비교표 열 순서(신청의약품 맨 오른쪽)로 정렬한 표와 각 열 이름을 돌려줍니다.
    정렬된 표의 index는 원래 조회 결과의 행 번호를 그대로 유지합니다."""
    comparison = result_df.copy()
    if "구분" in comparison.columns:
        comparison["_그룹정렬"] = comparison["구분"].map(
            lambda value: 1 if clean_whitespace(value) == "신청의약품" else 0
        )
        comparison = comparison.sort_values("_그룹정렬", kind="stable").drop(columns=["_그룹정렬"])
    comparison_names = []
    seen = {}
    for _, row in comparison.iterrows():
        prefix = " ".join(
            value for value in [clean_whitespace(row.get("구분", "")), clean_whitespace(row.get("함량", ""))]
            if value
        )
        product_name = clean_whitespace(row.get("허가제품명", "품목"))
        name = f"{prefix} | {product_name}" if prefix else product_name
        seen[name] = seen.get(name, 0) + 1
        comparison_names.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return comparison, comparison_names


def dosage_sources(result_df, reference_bundle):
    """Excel '용법용량 원문' 시트에 넣을 내용. 비교표 열 이름으로 이어 두어 나중에 요약을 정확한 칸에 채웁니다."""
    sorted_df, names = comparison_columns(result_df)
    name_by_index = dict(zip(sorted_df.index, names))
    products = (reference_bundle or {}).get("products", [])
    sources = []
    for position, row_index in enumerate(result_df.index):
        mfds = products[position]["mfds"] if position < len(products) else {}
        sources.append({
            "column": name_by_index.get(row_index, ""),
            "id": mfds.get("item_seq", ""),
            "name": mfds.get("product_name", ""),
            "indications_text": mfds.get("indications_text", ""),
            "dosage_text": mfds.get("dosage_text", ""),
        })
    return sources


def lookup_selected(rows, mfds_key, hira_key, wanted_extras, as_of_date, group_lookup=None, include_all_fields=False):
    cache_code = load_json_cache(CACHE_CODE_FILE)
    cache_name = load_json_cache(CACHE_NAME_FILE)
    cache_detail = load_json_cache(CACHE_DETAIL_FILE)
    cache_meft = load_json_cache(CACHE_MEFT_FILE)
    call_counter = {"hira": 0, "mfds": 0}
    errors = []
    columns = BASE_COLUMNS + wanted_extras
    output = []
    reference_items = []
    progress = st.progress(0, text="조회 중입니다…")
    for index, row in enumerate(rows, start=1):
        item_seq = row.get("ITEM_SEQ", "")
        item_name = clean_whitespace(row.get("ITEM_NAME", ""))
        entp_name = clean_whitespace(row.get("ENTP_NAME", ""))
        group_meta = (group_lookup or {}).get(str(item_seq), {})
        # 목록 API에는 바코드가 없으므로, 상세 API(fetch_detail)를 먼저 불러 실제 바코드를 얻습니다.
        fetch_keys = list(dict.fromkeys(ALWAYS_FETCH_DETAIL_KEYS + wanted_extras))
        detail = fetch_detail(
            item_seq, mfds_key, call_counter, cache_detail, fetch_keys, errors,
            include_all_fields=include_all_fields,
        )
        # 상세 조회에 성공하면 바코드 칸이 생기므로, 이 칸이 없으면 조회 실패로 봅니다.
        detail_failed = "_bar_code" not in detail
        bar_code = detail.get("_bar_code", "")
        errors_before_price = len(errors)
        price_items, method = match_prices(
            item_name, bar_code, hira_key, call_counter, cache_code, cache_name, errors, as_of_date
        )
        # 상세 조회가 실패하면 바코드로 약가를 확인할 수 없으므로 약가도 조회 실패로 봅니다.
        price_failed = not price_items and (detail_failed or method == "호출한도초과" or len(errors) > errors_before_price)
        price_item = price_items[0] if price_items else None
        errors_before_meft = len(errors)
        effect_classification = get_effect_classification(item_name, bar_code, hira_key, call_counter, cache_meft, errors)
        meft_failed = not effect_classification and len(errors) > errors_before_meft
        out_row = {"구분": group_meta.get("group_label", ""), "함량": group_meta.get("strength", ""), "허가제품명": item_name, "제약사한글명": entp_name, "희귀의약품": detail.get("희귀의약품", ""), "약가": format_price_cell(price_items), "약가기준일": as_of_date.isoformat(), "약가매칭근거": method, "심평원제품코드": join_hira_field(price_items, "mdsCd"), "약가적용시작일": join_hira_field(price_items, "adtStaDd"), "판매예정종료일": join_hira_field(price_items, "sellEptDd"), "약효분류": effect_classification, "주성분영문명": detail.get("주성분영문명", ""), "성분명": detail.get("성분명", ""), "효능효과": detail.get("효능효과", ""), "용법용량": detail.get("용법용량", "")}
        for key in wanted_extras:
            out_row[key] = detail.get(key, "")
        # 빈 칸은 '조회 실패'와 '자료 없음'으로 나눠 표시합니다. 사람이 채우는 행은 빈칸으로 둡니다.
        for key in ["희귀의약품", "주성분영문명", "성분명", "효능효과", "용법용량"] + list(wanted_extras):
            out_row[key] = cx.mark_missing(out_row.get(key, ""), detail_failed)
        out_row["약가"] = cx.mark_missing(out_row["약가"], price_failed)
        out_row["약효분류"] = cx.mark_missing(out_row["약효분류"], meft_failed)
        out_row.update(cx.manual_values(group_meta.get("group_label", "")))
        if include_all_fields:
            for api_key, api_value in sanitize_all_api_fields(detail.get("_all_api_fields", {})).items():
                out_row.setdefault(f"MFDS_{api_key}", api_value)
        output.append(out_row)
        reference_items.append({
            "group": {
                "id": group_meta.get("group_id", ""),
                "label": group_meta.get("group_label", ""),
                "strength": group_meta.get("strength", ""),
                "parsed_strength": group_meta.get("parsed_strength", ""),
            },
            "mfds": {
                "item_seq": item_seq,
                "product_name": item_name,
                "manufacturer": entp_name,
                "bar_code": clean_whitespace(bar_code),
                "ingredient": detail.get("성분명", ""),
                "rare_drug_yn": detail.get("희귀의약품", ""),
                "indications_text": detail.get("효능효과", ""),
                "dosage_text": detail.get("용법용량", ""),
                "selected_extra_fields": {key: detail.get(key, "") for key in wanted_extras},
                "all_api_fields": sanitize_all_api_fields(detail.get("_all_api_fields", {})) if include_all_fields else None,
            },
            "hira": {
                "reference_date": as_of_date.isoformat(),
                "match_method": method,
                "mds_cd": clean_whitespace((price_item or {}).get("mdsCd", "")),
                "product_name": clean_whitespace((price_item or {}).get("itmNm", "")),
                "manufacturer": clean_whitespace((price_item or {}).get("mnfEntpNm", "")),
                "max_price": (price_item or {}).get("mxCprc"),
                "effective_start": clean_whitespace((price_item or {}).get("adtStaDd", "")),
                "sale_end": clean_whitespace((price_item or {}).get("sellEptDd", "")),
            } if price_item else None,
            "hira_prices": [
                {
                    "mds_cd": clean_whitespace(item.get("mdsCd", "")),
                    "product_name": clean_whitespace(item.get("itmNm", "")),
                    "package_hint": hira_package_hint(item),
                    "max_price": item.get("mxCprc"),
                    "effective_start": clean_whitespace(item.get("adtStaDd", "")),
                    "sale_end": clean_whitespace(item.get("sellEptDd", "")),
                    "raw": item,
                }
                for item in price_items
            ],
        })
        progress.progress(index / len(rows), text=f"조회 중: {index}/{len(rows)}")
    progress.empty()
    save_json_cache(CACHE_CODE_FILE, cache_code)
    save_json_cache(CACHE_NAME_FILE, cache_name)
    save_json_cache(CACHE_DETAIL_FILE, cache_detail)
    save_json_cache(CACHE_MEFT_FILE, cache_meft)
    reference_bundle = {
        "schema_version": "1.2",
        "reference_date": as_of_date.isoformat(),
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "product_count": len(reference_items),
        "products": reference_items,
        "api_warnings": errors,
    }
    return order_result_columns(pd.DataFrame(output)), errors, reference_bundle


def check_dur(rows, mfds_key, dur_indices, cache_detail, call_counter, errors):
    """선택한 품목들이 업로드된 DUR(병용금기 등) 리스트에 포함되는지 확인합니다.
    바코드, EDI코드, 품목코드를 모두 후보로 사용하고, 어떤 코드열에 매칭되었는지 함께 보여줍니다.
    """
    result_rows = []
    seen_extra_cols = []
    seen_matches = set()
    for row in rows:
        item_seq = row.get("ITEM_SEQ", "")
        item_name = clean_whitespace(row.get("ITEM_NAME", ""))
        entp_name = clean_whitespace(row.get("ENTP_NAME", ""))
        detail = fetch_detail(item_seq, mfds_key, call_counter, cache_detail, [], errors)
        candidates = collect_dur_candidate_codes(item_seq, detail)
        if not candidates:
            continue
        for category in DUR_CATEGORIES:
            index = dur_indices.get(category, {})
            for lookup_key, match_source, raw_code in candidates:
                if lookup_key not in index:
                    continue
                for payload in index[lookup_key]:
                    row_dict = payload["row"]
                    dedupe_key = (
                        item_seq,
                        category,
                        payload.get("_dur_code_column", ""),
                        payload.get("_dur_code_value", ""),
                        payload.get("_dur_row_number", 0),
                    )
                    if dedupe_key in seen_matches:
                        continue
                    seen_matches.add(dedupe_key)
                    result_row = {
                        "허가제품명": item_name,
                        "제약사한글명": entp_name,
                        "DUR종류": category,
                        "매칭근거": match_source,
                        "매칭코드": raw_code,
                        "DUR코드열": payload.get("_dur_code_column", ""),
                    }
                    for column in DUR_EXTRA_COLUMNS.get(category, []):
                        value = row_dict.get(column, "")
                        result_row[column] = "" if pd.isna(value) else str(value)
                        if column not in seen_extra_cols:
                            seen_extra_cols.append(column)
                    result_rows.append(result_row)
    columns = ["허가제품명", "제약사한글명", "DUR종류", "매칭근거", "매칭코드", "DUR코드열"] + seen_extra_cols
    return pd.DataFrame(result_rows, columns=columns)


st.set_page_config(
    page_title="의약품 통합 조회",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --ink: #10243e;
        --muted: #617086;
        --line: #dbe4ee;
        --surface: #ffffff;
        --surface-soft: #f5f8fc;
        --brand: #146c94;
        --brand-dark: #0d4f72;
        --accent: #19a7a0;
    }

    .stApp {
        background:
            radial-gradient(circle at 92% 0%, rgba(25, 167, 160, .10), transparent 28rem),
            linear-gradient(180deg, #f8fbfe 0%, #f3f7fb 100%);
        color: var(--ink);
    }
    .block-container {
        max-width: 1440px;
        padding-top: 2.25rem;
        padding-bottom: 4rem;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f3550 0%, #102b42 100%);
        border-right: 0;
    }
    [data-testid="stSidebar"] * { color: #f6fbff; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: #bad0df; }
    [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.14); }
    [data-testid="stSidebar"] .stTextInput input {
        background: rgba(255,255,255,.10);
        border-color: rgba(255,255,255,.22);
        color: #fff;
    }
    .app-hero {
        position: relative;
        overflow: hidden;
        padding: 1.75rem 2rem;
        margin-bottom: 1.5rem;
        border: 1px solid rgba(20,108,148,.13);
        border-radius: 22px;
        background: linear-gradient(135deg, rgba(255,255,255,.98), rgba(235,247,250,.96));
        box-shadow: 0 14px 40px rgba(31, 78, 121, .08);
    }
    .app-hero::after {
        content: "";
        position: absolute;
        width: 210px;
        height: 210px;
        right: -55px;
        top: -95px;
        border-radius: 50%;
        background: linear-gradient(145deg, rgba(20,108,148,.17), rgba(25,167,160,.06));
    }
    .hero-kicker {
        display: inline-flex;
        align-items: center;
        gap: .4rem;
        padding: .3rem .65rem;
        border-radius: 999px;
        color: var(--brand-dark);
        background: #e2f2f5;
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .04em;
    }
    .app-hero h1 {
        margin: .8rem 0 .4rem;
        color: var(--ink);
        font-size: clamp(1.75rem, 3vw, 2.55rem);
        line-height: 1.15;
        letter-spacing: -.035em;
    }
    .app-hero p {
        margin: 0;
        max-width: 760px;
        color: var(--muted);
        font-size: 1rem;
        line-height: 1.65;
    }
    .app-hero .app-credit {
        margin-top: .9rem;
        text-align: right;
        color: var(--muted);
        font-size: .78rem;
        line-height: 1.5;
    }
    .section-title {
        display: flex;
        align-items: center;
        gap: .75rem;
        margin: 2rem 0 .85rem;
        color: var(--ink);
        font-size: 1.18rem;
        font-weight: 750;
    }
    .section-step {
        display: inline-grid;
        place-items: center;
        width: 1.8rem;
        height: 1.8rem;
        border-radius: 10px;
        color: #fff;
        background: linear-gradient(135deg, var(--brand), var(--accent));
        font-size: .82rem;
        box-shadow: 0 5px 14px rgba(20,108,148,.2);
    }
    div[data-testid="stForm"],
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--line);
        border-radius: 16px;
    }
    .stButton > button, .stDownloadButton > button {
        min-height: 2.75rem;
        border-radius: 11px;
        border: 1px solid #c9d7e5;
        font-weight: 700;
        transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        transform: translateY(-1px);
        border-color: var(--brand);
        box-shadow: 0 8px 18px rgba(20,108,148,.12);
    }
    .stButton > button[kind="primary"] {
        border: 0;
        color: #fff;
        background: linear-gradient(135deg, var(--brand-dark), var(--brand));
    }
    .stTextInput input, .stDateInput input, [data-baseweb="select"] > div {
        border-radius: 10px !important;
        border-color: #cfdae6 !important;
        background: rgba(255,255,255,.92);
    }
    [data-testid="stDataFrame"] {
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 14px;
        box-shadow: 0 6px 20px rgba(31,78,121,.05);
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: .35rem;
        padding: .3rem;
        border-radius: 13px;
        background: #eaf0f6;
    }
    .stTabs [data-baseweb="tab"] {
        height: 2.7rem;
        padding: 0 1.05rem;
        border-radius: 9px;
    }
    .stTabs [aria-selected="true"] {
        background: #fff;
        box-shadow: 0 3px 10px rgba(31,78,121,.10);
    }
    [data-testid="stAlert"] { border-radius: 13px; }
    [data-testid="stExpander"] {
        overflow: hidden;
        border-color: var(--line);
        border-radius: 13px;
        background: rgba(255,255,255,.72);
    }
    @media (prefers-color-scheme: dark) {
        :root {
            --ink: #edf4fa;
            --muted: #a9bacb;
            --line: #33475b;
            --surface: #121c27;
            --surface-soft: #172431;
            --brand: #39a9d0;
            --brand-dark: #1889b2;
            --accent: #42c7c1;
            color-scheme: dark;
        }
        .stApp {
            background:
                radial-gradient(circle at 92% 0%, rgba(66, 199, 193, .12), transparent 28rem),
                linear-gradient(180deg, #0d151e 0%, #111b26 100%);
            color: var(--ink);
        }
        .stApp p, .stApp label, .stApp li, .stApp span,
        .stMarkdown, [data-testid="stCaptionContainer"] p {
            color: #dce7f1;
        }
        .app-hero {
            border-color: #2c5268;
            background: linear-gradient(135deg, rgba(22,37,50,.98), rgba(17,49,59,.96));
            box-shadow: 0 16px 44px rgba(0,0,0,.30);
        }
        .app-hero::after {
            background: linear-gradient(145deg, rgba(57,169,208,.22), rgba(66,199,193,.07));
        }
        .hero-kicker {
            color: #d9fbf8 !important;
            background: rgba(66,199,193,.16);
            border: 1px solid rgba(66,199,193,.24);
        }
        .app-hero h1, .section-title, .section-title span { color: #f3f8fc; }
        .app-hero p { color: #b8c8d7; }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0a2233 0%, #0b1b29 100%);
            border-right: 1px solid #233b4d;
        }
        [data-testid="stSidebar"] * { color: #edf7ff; }
        .stTextInput input, .stDateInput input, [data-baseweb="select"] > div,
        [data-baseweb="input"] {
            color: #edf4fa !important;
            caret-color: #67d7d1;
            border-color: #3a5166 !important;
            background: #162330 !important;
        }
        .stTextInput input::placeholder { color: #8194a7; opacity: 1; }
        [data-baseweb="popover"], [role="listbox"] {
            color: #edf4fa;
            background: #182633 !important;
        }
        .stButton > button, .stDownloadButton > button {
            color: #eaf3fa;
            border-color: #3a5268;
            background: #172635;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            color: #ffffff;
            border-color: #4bbbd8;
            background: #1b3041;
            box-shadow: 0 8px 20px rgba(0,0,0,.24);
        }
        .stButton > button[kind="primary"] {
            color: #ffffff;
            background: linear-gradient(135deg, #126f96, #15998f);
        }
        [data-testid="stDataFrame"] {
            border-color: #34475a;
            background: #111b26;
            box-shadow: 0 7px 24px rgba(0,0,0,.20);
        }
        .stTabs [data-baseweb="tab-list"] { background: #172431; }
        .stTabs [data-baseweb="tab"] { color: #b8c7d5; }
        .stTabs [aria-selected="true"] {
            color: #f6fbff;
            background: #24384a;
            box-shadow: 0 4px 12px rgba(0,0,0,.22);
        }
        [data-testid="stExpander"] {
            border-color: #33475b;
            background: rgba(20,32,44,.88);
        }
        [data-testid="stAlert"] {
            border-color: #3c5368;
            color: #edf4fa;
        }
        hr { border-color: #314355; }
        code, pre {
            color: #d9eff7 !important;
            background: #0b141d !important;
        }
    }
    @media (max-width: 720px) {
        .block-container { padding: 1rem .85rem 2.5rem; }
        .app-hero { padding: 1.25rem; border-radius: 17px; }
        .app-hero p { font-size: .92rem; }
        .stTabs [data-baseweb="tab"] { padding: 0 .55rem; }
    }
    </style>
    <div class="app-hero">
      <span class="hero-kicker">OFFICIAL DRUG REFERENCE</span>
      <h1>의약품 허가정보·약가 통합 조회</h1>
      <p>식약처 허가사항과 심평원 급여약가를 한 화면에서 조회하고, 비교표와 AI 검토용 공식 레퍼런스를 생성합니다.</p>
      <div class="app-credit" lang="en">Developed by Chaereen Jeong</div>
    </div>
    """,
    unsafe_allow_html=True,
)


def section_header(step, title):
    st.markdown(
        f'<div class="section-title"><span class="section-step">{step}</span><span>{title}</span></div>',
        unsafe_allow_html=True,
    )

with st.sidebar:
    st.header("환경 설정")
    try:
        secret_mfds = st.secrets.get("MFDS_KEY", "")
        secret_hira = st.secrets.get("HIRA_KEY", "")
    except Exception:
        secret_mfds, secret_hira = "", ""

    if secret_mfds and secret_hira:
        # Streamlit Cloud의 'Settings > Secrets'에 MFDS_KEY / HIRA_KEY가 등록되어 있으면
        # 매번 입력할 필요 없이 자동으로 사용합니다.
        mfds_key = secret_mfds
        hira_key = secret_hira
        st.success("API 키를 Secrets에서 자동으로 불러왔습니다.")
        with st.expander("이번 세션만 다른 키로 임시 사용"):
            override_mfds = st.text_input("식약처 인증키", type="password", key="override_mfds")
            override_hira = st.text_input("심평원 인증키", type="password", key="override_hira")
            if override_mfds:
                mfds_key = override_mfds
            if override_hira:
                hira_key = override_hira
    else:
        st.markdown("API 키는 코드에 저장하지 말고 아래 입력란 또는 Streamlit secrets를 사용하세요.")
        missing = []
        if not secret_mfds:
            missing.append("MFDS_KEY")
        if not secret_hira:
            missing.append("HIRA_KEY")
        st.caption(
            "매번 입력하지 않으려면 앱 설정(점 3개 메뉴) > Secrets에 아래 형식으로 등록하세요:\n\n"
            + "\n".join(f'{name} = "여기에 디코딩된 키"' for name in missing)
        )
        mfds_key = st.text_input("식약처 인증키 (디코딩된 키)", value=secret_mfds, type="password")
        hira_key = st.text_input("심평원 인증키 (디코딩된 키)", value=secret_hira, type="password")

    if st.button("허가목록 캐시 새로고침"):
        st.cache_data.clear()
        st.cache_resource.clear()
        for cache_path in (LIST_FILE, LIST_META_FILE, TEMP_FILE):
            if cache_path.exists():
                cache_path.unlink()
        st.rerun()
    st.caption("허가목록은 KST 기준 하루 1회만 자동 갱신합니다. API 키는 파일에 저장하지 않고 Streamlit Secrets/입력값으로만 재사용합니다.")
    with st.expander("🔧 식약처 상세정보 점검 (효능효과·용법용량이 빈칸일 때)"):
        st.caption("품목기준코드 하나로 식약처 상세 API를 직접 불러, 효능효과·용법용량 문서가 오는지 보여 줍니다. 인증키는 화면에 나오지 않습니다.")
        check_seq = st.text_input("품목기준코드", value="200700547", key="mfds_check_seq")
        if st.button("점검하기", disabled=not mfds_key):
            st.code(diagnose_mfds_detail(check_seq.strip(), mfds_key), language="text")
        if st.button("상세정보 캐시 비우기"):
            if CACHE_DETAIL_FILE.exists():
                CACHE_DETAIL_FILE.unlink()
            st.cache_resource.clear()
            st.success("상세정보 캐시를 비웠습니다. 다음 조회 때 식약처에서 새로 받아옵니다.")
    st.divider()
    st.markdown("**저장 위치**")
    st.code(str(DATA_DIR), language="text")

cache_day = current_kst_date()
cache_fresh = list_cache_is_fresh()
if not cache_fresh and not mfds_key:
    st.warning("오늘 날짜의 허가목록 캐시가 없어 식약처 인증키가 필요합니다. 심평원 인증키는 실제 조회 시 필요합니다.")
    st.stop()
if not hira_key:
    st.info("검색목록은 열 수 있지만, 약가·상세정보 조회에는 심평원 인증키가 필요합니다.")

try:
    all_rows = load_permitted_drugs(mfds_key, str(DATA_DIR), cache_day)
except Exception as exc:
    st.error(f"허가목록 수집에 실패했습니다: {exc}")
    st.exception(exc)
    st.stop()

normal_rows = [row for row in all_rows if row.get("CANCEL_NAME") == "정상"]
by_seq = {row.get("ITEM_SEQ", ""): row for row in normal_rows}
search_index, search_light = build_search_index(
    normal_rows, cache_day, len(normal_rows), detail_cache_mtime()
)
st.success(f"정상 품목 {len(normal_rows):,}건 준비 완료")

if "selection" not in st.session_state:
    st.session_state.selection = []
st.session_state.setdefault("sel_table_ver", 0)
ensure_group_state()
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_errors" not in st.session_state:
    st.session_state.last_errors = []
if "last_dosage" not in st.session_state:
    st.session_state.last_dosage = None
    st.session_state.last_seqs = []
if "last_reference_json" not in st.session_state:
    st.session_state.last_reference_json = None
if "group_mode" not in st.session_state:
    st.session_state.group_mode = False

section_header("1", "의약품 검색")
with st.container(border=True):
    st.markdown("**조회 방식**")
    group_mode = st.toggle(
        "신청의약품 · 비교의약품 그룹으로 관리",
        key="group_mode",
        help="필요할 때만 켜세요. 끄면 모든 품목을 하나의 일반 조회 목록으로 관리합니다.",
    )
    st.caption("비교표를 그룹·함량별로 만들 때만 켜세요. 기본 조회에서는 끈 상태로 사용합니다.")
previous_group_mode = st.session_state.get("group_mode_previous", group_mode)
if group_mode and not previous_group_mode:
    grouped_seqs = set(flatten_group_seqs())
    st.session_state.groups["applicant"]["seqs"].extend(
        seq for seq in st.session_state.selection if seq not in grouped_seqs
    )
elif not group_mode and previous_group_mode:
    st.session_state.selection = list(dict.fromkeys(flatten_group_seqs()))
st.session_state.group_mode_previous = group_mode

with st.expander("📂 파일로 품목 추가 (원내 비교 후보 추출 프로그램의 '앱 입력용 파일')"):
    st.caption(
        "EDI(보험)코드 → 한글 약품명 → 성분명 순서로 찾습니다. "
        "보험코드가 있으면 심평원 제품명과 바코드로 확인해 자동으로 연결하고, 없으면 식약처 제품명과 완전히 같을 때만 자동으로 연결합니다. "
        "나머지는 이름이나 성분이 같은 후보 중에서 직접 골라 주세요."
    )
    app_input_file = st.file_uploader("앱 입력용 파일 (xlsx)", type=["xlsx"], key="app_input_file")
    input_frame, number_choice = None, None
    if app_input_file:
        input_frame = pd.read_excel(app_input_file, dtype=str).fillna("")
        if "신청번호" in input_frame.columns and input_frame["신청번호"].str.strip().any():
            # 신청번호마다 비교표를 하나씩 만듭니다: 고른 번호의 신청의약품과 그 비교약만 불러옵니다.
            numbers = list(dict.fromkeys(n for n in input_frame["신청번호"].str.strip() if n))
            names = {
                n: ", ".join(input_frame[(input_frame["신청번호"].str.strip() == n) & (input_frame["구분"] == "신청의약품")]["약품명"].head(3))
                for n in numbers
            }
            number_choice = st.selectbox(
                "어느 신청의약품의 비교표를 만들까요? (신청번호를 바꿔 가며 하나씩 만드세요)",
                numbers, format_func=lambda n: f"{n} · {names.get(n) or '(신청의약품 없음)'}", key="app_input_number",
            )
    replace_groups = st.checkbox("지금 고른 품목을 비우고 파일 내용으로 새로 채우기", value=True, key="app_input_replace")
    if input_frame is not None and st.button("파일 읽고 품목 연결하기", disabled=not hira_key):
        missing_columns = [column for column in APP_INPUT_COLUMNS if column not in input_frame.columns]
        if missing_columns:
            st.error(f"앱 입력용 파일에 {', '.join(missing_columns)} 열이 없습니다.")
        else:
            if number_choice:
                input_frame = input_frame[input_frame["신청번호"].str.strip() == number_choice]
            with st.spinner("보험코드, 약품명, 성분명으로 품목을 찾는 중입니다…"):
                st.session_state.file_links, link_errors = link_app_input(input_frame, normal_rows, mfds_key, hira_key)
            for link_error in link_errors:
                st.warning(link_error)
    file_links = st.session_state.get("file_links")
    if file_links:
        auto_count = sum(1 for link in file_links if link["seq"])
        st.markdown(f"**자동 연결 {auto_count}건 / 직접 확인 {len(file_links) - auto_count}건**")
        for index, link in enumerate(file_links):
            label = f"{link['구분']} · {link['입력 약품명']}" + (f" (보험코드 {link['보험코드']})" if link["보험코드"] else "")
            if link["seq"]:
                st.markdown(f"✅ {label} → **{link['연결 품목']}** · {link['방법']}")
            else:
                choices = ["(넣지 않음)"] + [f"{c['ITEM_NAME']} · {c['ENTP_NAME']} · {c['ITEM_SEQ']}" for c in link["후보"]]
                st.selectbox(
                    f"⚠️ {label} — " + (f"{link.get('후보 근거') or '이름'}으로 찾은 후보 중에서 골라 주세요" if link["후보"]
                                       else "찾지 못했습니다. 검색에서 직접 추가해 주세요"),
                    choices, key=f"link_pick_{index}",
                )
        st.button("그룹에 추가", type="primary", on_click=apply_file_links, args=(file_links, replace_groups))

query = st.text_input(
    "의약품명 · 제약사명 · 성분명 · 주성분 영문명",
    placeholder="예: 타이레놀, 한미약품, 아세트아미노펜, acetaminophen",
)
target_group_id = None
if group_mode:
    target_col, add_group_col = st.columns([3, 1])
    with target_col:
        if st.session_state.get("search_target_group") not in st.session_state.groups:
            st.session_state.search_target_group = "applicant"
        target_group_id = st.selectbox(
            "선택 품목을 추가할 그룹",
            options=ordered_group_ids(st.session_state.groups),
            format_func=lambda gid: st.session_state.groups[gid]["label"],
            key="search_target_group",
        )
    with add_group_col:
        st.write("")
        st.write("")
        if st.button("＋ 비교약 그룹 추가", use_container_width=True):
            new_gid = next_comparator_group_id()
            st.session_state.groups[new_gid] = {"label": group_label(new_gid), "seqs": []}
            st.rerun()
matches = []
if query.strip():
    q = query.strip().casefold()
    for blob, row in search_index:
        if q in blob:
            matches.append(row)
            if len(matches) >= 200:
                break
    st.caption(f"검색결과 {len(matches)}건 표시 (최대 200건)")

# 검색 결과를 드롭다운이 아닌 전체 행이 보이는 선택 가능한 표로 표시합니다.
if matches:
    search_df = pd.DataFrame([
        {
            "의약품명": row.get("ITEM_NAME", ""),
            "제약사": row.get("ENTP_NAME", ""),
            "성분명": clean_ingredient(row.get("MAIN_ITEM_INGR", "")) or search_light.get(str(row.get("ITEM_SEQ", "")), ("", ""))[0],
            "주성분 영문명": row.get("MAIN_INGR_ENG", "") or search_light.get(str(row.get("ITEM_SEQ", "")), ("", ""))[1],
            "품목코드": row.get("ITEM_SEQ", ""),
        }
        for row in matches
    ])
    search_event = st.dataframe(
        search_df,
        use_container_width=True,
        hide_index=True,
        height=min(520, 36 + len(search_df) * 35),
        selection_mode="multi-row",
        on_select="rerun",
        # 검색어별로 위젯 상태를 분리해 첫 행이 자동 선택되지 않도록 합니다.
        key=f"search_results_table_{query.strip().casefold()}",
    )
    # selection.rows는 현재 검색표의 위치 인덱스이므로 반드시 iloc로 매핑합니다.
    search_selected_seqs = [
        str(search_df.iloc[index]["품목코드"])
        for index in search_event.selection.rows
        if 0 <= index < len(search_df)
    ]
    st.caption(f"검색 결과에서 선택한 품목: **{len(search_selected_seqs)}건**")
    add_label = (
        f"선택한 품목을 {st.session_state.groups[target_group_id]['label']}에 추가"
        if group_mode else "선택한 품목을 조회 목록에 추가"
    )
    # on_click 콜백: 버튼 클릭 → 콜백 실행 → 스크립트 1회 재실행 (기존의 st.rerun() 추가 재실행 제거)
    st.button(
        add_label, disabled=not search_selected_seqs, key="add_search_selection",
        on_click=add_to_selection, args=(group_mode, target_group_id, search_selected_seqs),
    )

if group_mode:
    section_header("2", "신청의약품 · 비교의약품 그룹")
    st.caption("함량은 제품명에서 자동 파싱됩니다. 잘못되었거나 비어 있으면 표에서 직접 수정하고, 제거할 행은 체크하세요.")
    group_items = build_group_items(by_seq)
    for gid in ordered_group_ids(st.session_state.groups):
        group_meta = st.session_state.groups[gid]
        items = [item for item in group_items if item["group_id"] == gid]
        with st.expander(f"{group_meta['label']} · {len(items)}개 품목", expanded=(gid == "applicant" or bool(items))):
            if not items:
                st.info("검색 결과에서 품목을 선택해 이 그룹에 추가하세요.")
            else:
                editor_df = pd.DataFrame([
                    {
                        "의약품명": item["item_name"], "제약사": item["entp_name"], "품목코드": item["seq"],
                        "함량": item["strength"], "자동파싱": item["parsed_strength"], "제거": False,
                    }
                    for item in items
                ])
                edited_df = st.data_editor(
                    editor_df, use_container_width=True, hide_index=True,
                    disabled=["의약품명", "제약사", "품목코드", "자동파싱"],
                    column_config={
                        "함량": st.column_config.TextColumn("함량(수정 가능)", help="비교표와 JSON에 반영될 함량입니다."),
                        "자동파싱": st.column_config.TextColumn("자동 파싱값"),
                        "제거": st.column_config.CheckboxColumn("제거"),
                    }, key=f"group_editor_{gid}",
                )
                for _, edited_row in edited_df.iterrows():
                    seq = str(edited_row["품목코드"])
                    st.session_state.strength_overrides[seq] = clean_whitespace(edited_row["함량"])
                remove_seqs = edited_df.loc[edited_df["제거"] == True, "품목코드"].astype(str).tolist()
                if st.button("체크한 품목 제거", disabled=not remove_seqs, key=f"remove_group_items_{gid}"):
                    remove_group_seqs(gid, remove_seqs)
                    st.rerun()
            if gid != "applicant" and st.button("이 비교약 그룹 삭제", key=f"delete_group_{gid}"):
                for seq in group_meta["seqs"]:
                    st.session_state.strength_overrides.pop(seq, None)
                del st.session_state.groups[gid]
                sync_selection_from_groups()
                st.rerun()
    selected_seqs = flatten_group_seqs()
    group_counts = " · ".join(
        f"{st.session_state.groups[gid]['label']} {len(st.session_state.groups[gid]['seqs'])}개"
        for gid in ordered_group_ids(st.session_state.groups)
    )
    st.write(f"현재 선택: **총 {len(selected_seqs)}개 품목** ({group_counts})")
else:
    section_header("2", "조회할 품목")
    selected_seqs = [seq for seq in st.session_state.selection if seq in by_seq]
    st.session_state.sel_rendered = selected_seqs
    if selected_seqs:
        selected_df = pd.DataFrame([
            {"의약품명": by_seq[seq].get("ITEM_NAME", ""), "제약사": by_seq[seq].get("ENTP_NAME", ""), "품목코드": seq}
            for seq in selected_seqs
        ])
        table_col, arrow_col = st.columns([12, 1])
        with table_col:
            selected_event = st.dataframe(
                selected_df, use_container_width=True, hide_index=True,
                selection_mode="multi-row", on_select="rerun",
                key=f"selected_items_table_{st.session_state.sel_table_ver}",
            )
        remove_seqs = {
            str(selected_df.iloc[index]["품목코드"])
            for index in selected_event.selection.rows if 0 <= index < len(selected_df)
        }
        with arrow_col:
            st.button("↑", key="sel_move_up", disabled=not remove_seqs,
                      on_click=move_selected_items, args=(-1,), use_container_width=True,
                      help="체크한 품목을 한 칸 위로")
            st.button("↓", key="sel_move_down", disabled=not remove_seqs,
                      on_click=move_selected_items, args=(1,), use_container_width=True,
                      help="체크한 품목을 한 칸 아래로")
        if st.button("선택한 품목 제거", disabled=not remove_seqs, key="remove_selected_items"):
            st.session_state.selection = [seq for seq in st.session_state.selection if seq not in remove_seqs]
            st.rerun()
    else:
        st.info("검색 결과에서 조회할 품목을 추가하세요.")
    st.write(f"현재 선택: **총 {len(selected_seqs)}개 품목**")

selected_rows = [by_seq[seq] for seq in selected_seqs if seq in by_seq]

section_header("3", "조회 설정")
if "preset_new_drug_intro" not in st.session_state:
    st.session_state.preset_new_drug_intro = all(st.session_state.get(f"extra_{key}", False) for key in NEW_DRUG_PRESET_KEYS)
if "preset_all_fields" not in st.session_state:
    st.session_state.preset_all_fields = all(st.session_state.get(f"extra_{key}", False) for key in EXTRA_FIELD_ORDER)
preset_columns = st.columns(2)
with preset_columns[0]:
    st.checkbox(
        "[신약 도입 준비]",
        key="preset_new_drug_intro",
        on_change=apply_new_drug_preset,
        help="신약 도입 검토에 자주 쓰는 허가 항목을 한 번에 선택/해제합니다.",
    )
with preset_columns[1]:
    st.checkbox(
        "[전체] 식약처 제공 항목",
        key="preset_all_fields",
        on_change=apply_all_fields_preset,
        help="기본·추가 항목과 의미 있는 식약처 상세 필드를 MFDS_열로 가져옵니다. XML 원문과 빈 필드는 제외합니다.",
    )

selected_extras = []
extra_columns = st.columns(3)
for index, key in enumerate(EXTRA_FIELD_ORDER):
    with extra_columns[index % 3]:
        if st.checkbox(EXTRA_FIELD_LABELS[key], key=f"extra_{key}", on_change=sync_field_presets):
            selected_extras.append(key)

summary_view = st.checkbox(
    "요약 버전으로 보기",
    help="AI가 새로운 의학적 판단을 생성하지 않고, 원문에서 앞부분과 문장 단위 내용을 발췌해 짧게 표시합니다.",
)

dosage_choice = st.radio(
    "용법·용량 표시",
    cx.DOSAGE_CHOICES,
    horizontal=True,
    key="dosage_choice",
    help="간단/일반/상세는 원문 앞부분을 잘라 보여 주는 미리보기입니다. 기준에 맞춘 최종 요약은 Excel을 받아 Claude에게 '용법·용량 요약해 줘'라고 요청하세요. Excel에는 항상 원문 시트가 들어갑니다.",
)

price_reference_date = st.date_input(
    "심평원 약가 기준일",
    value=datetime.now(KST).date(),
    help="이 날짜에 적용 중인 약가 이력만 선택합니다. 적용 시작일과 판매 종료일을 함께 판정합니다.",
)

applicant_ready = not group_mode or bool(st.session_state.groups["applicant"]["seqs"])
if group_mode and not applicant_ready and selected_seqs:
    st.warning("조회하려면 신청의약품 그룹에 품목을 하나 이상 추가하세요.")

lookup_button_label = "그룹 전체 품목 조회" if group_mode else "선택한 품목 조회"
if st.button(lookup_button_label, type="primary", disabled=not selected_seqs or not applicant_ready or not (mfds_key and hira_key)):
    group_lookup = None
    if group_mode:
        current_group_items = build_group_items(by_seq)
        group_lookup = {item["seq"]: item for item in current_group_items}
    selected_rows = [by_seq[seq] for seq in selected_seqs if seq in by_seq]
    with st.spinner("식약처 상세정보와 심평원 약가를 조회하는 중입니다…"):
        result_df, errors, reference_bundle = lookup_selected(
            selected_rows, mfds_key, hira_key, selected_extras, price_reference_date, group_lookup,
            include_all_fields=bool(st.session_state.get("preset_all_fields", False)),
        )
    st.session_state.last_result = result_df
    st.session_state.last_errors = errors
    st.session_state.last_reference_json = reference_bundle
    st.session_state.last_dosage = cx.build_dosage_summaries(dosage_products(reference_bundle))
    st.session_state.last_seqs = [str(product["mfds"]["item_seq"]) for product in reference_bundle["products"]]
    st.rerun()

if st.session_state.last_result is not None:
    section_header("4", "조회 결과")
    result_df = st.session_state.last_result
    filtered_result_df, dosage_level = apply_dosage_version(result_df, dosage_choice)

    dosage_info = st.session_state.last_dosage
    if dosage_info:
        shown = "원문" if dosage_level == "원문" else f"{dosage_level} 버전"
        st.caption(
            f"용법·용량: **{shown}** 표시 중 · 추천 버전은 **{dosage_info['recommended_level']}** "
            f"({dosage_info['reason']}) · 화면의 간단/일반/상세는 원문 발췌 미리보기입니다. "
            "기준에 맞춘 최종 요약은 Excel을 받아 Claude에게 '용법·용량 요약해 줘'라고 요청하세요."
        )
        if dosage_info.get("warnings"):
            with st.expander(f"용법·용량 요약 확인 필요 {len(dosage_info['warnings'])}건"):
                for warning in dosage_info["warnings"]:
                    st.warning(warning)

    excel_comparison = (
        make_comparison_df(apply_text_layout(make_summary_df(filtered_result_df) if summary_view else filtered_result_df))
        if len(filtered_result_df) >= 2 else None
    )
    excel_detail = make_display_df(filtered_result_df, summary_view=summary_view, transpose_view=False)
    excel_date = (st.session_state.last_reference_json or {}).get("reference_date", "")
    st.download_button(
        "비교표 Excel 다운로드",
        data=cx.to_excel_bytes(
            excel_comparison, excel_detail, title="의약품 비교표",
            note_lines=[
                f"약가 기준일: {excel_date}",
                f"용법·용량: {'원문' if dosage_level == '원문' else dosage_level + ' 버전'} ({dosage_info['source'] if dosage_info else '원문'}) — 약사 확인 필요",
            ],
            dosage_sources=dosage_sources(result_df, st.session_state.last_reference_json),
        ),
        file_name=f"의약품비교표_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

    result_tab, comparison_tab = st.tabs(["상세 결과", "여러 약품 비교표"])

    with result_tab:
        transpose_view = st.checkbox(
            "행/열 전환", key="result_transpose", value=True,
            help="표시와 CSV 다운로드 모두 행/열을 전환합니다. 켜면 약 하나가 세로줄 하나가 되고, 화면 폭에 맞춰 각 약의 너비가 자동으로 좁아지거나 넓어집니다.",
        )
        displayed_df = make_display_df(filtered_result_df, summary_view=summary_view, transpose_view=transpose_view)
        if summary_view:
            st.caption("요약 버전: 원문에서 문장 단위로 발췌한 표시용 요약입니다. 임상적 판단을 대신하지 않습니다.")
        render_resizable_wrapped_table(displayed_df, show_index=transpose_view, height=720, table_key="detail")
        # 화면에 표시한 동일한 DataFrame을 사용하므로 행/열 전환 상태가 CSV에도 반영됩니다.
        csv_bytes = displayed_df.to_csv(index=transpose_view, encoding="utf-8-sig").encode("utf-8-sig")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_suffix = "_행열전환" if transpose_view else ""
        st.download_button("결과 CSV 다운로드", data=csv_bytes, file_name=f"의약품조회결과_{timestamp}{csv_suffix}.csv", mime="text/csv")
        if st.session_state.last_reference_json is not None:
            reference_json_bytes = json.dumps(
                st.session_state.last_reference_json, ensure_ascii=False, indent=2
            ).encode("utf-8")
            reference_date = st.session_state.last_reference_json.get("reference_date", "")
            st.download_button(
                "AI 검토용 JSON 다운로드",
                data=reference_json_bytes,
                file_name=f"의약품_공식레퍼런스_{reference_date}_{timestamp}.json",
                mime="application/json",
                help="비교표 또는 PPT와 함께 Work에 올려 사실관계 검토에 사용합니다.",
            )
            priced_products = [
                product for product in st.session_state.last_reference_json.get("products", [])
                if product.get("hira_prices")
            ]
            if priced_products:
                with st.expander("심평원 약가 원본 필드 확인 (포장정보 필드 점검용)"):
                    st.caption("품목별로 심평원 API가 돌려준 약가 항목의 원본 필드입니다. 포장·규격이 어느 필드에 있는지 확인할 때 사용하세요.")
                    for product in priced_products[:5]:
                        st.markdown(f"**{product['mfds']['product_name']}** · 약가 {len(product['hira_prices'])}건")
                        st.json([price["raw"] for price in product["hira_prices"]], expanded=False)

    with comparison_tab:
        if len(filtered_result_df) < 2:
            st.info("두 품목 이상 조회하면 비교표가 표시됩니다.")
        else:
            comparison_df = excel_comparison
            comparison_caption = (
                "행은 조회 항목, 열은 그룹·함량별 의약품입니다. 신청의약품은 맨 오른쪽에 표시됩니다."
                if group_mode else "행은 조회 항목, 열은 선택한 의약품입니다."
            )
            st.caption(f"{comparison_caption} 헤더 경계를 드래그해 컬럼 너비를 조절할 수 있습니다.")
            render_resizable_wrapped_table(comparison_df, show_index=True, height=760, table_key="comparison")
            comparison_csv = comparison_df.to_csv(index=True, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button("비교표 CSV 다운로드", data=comparison_csv, file_name=f"의약품비교표_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")

    if st.session_state.last_errors:
        with st.expander(f"API 경고/오류 {len(st.session_state.last_errors)}건"):
            for error in st.session_state.last_errors:
                st.warning(error)
