"""
정책 데이터 전처리 (1단계: 규칙 기반 후보 선정)

입력 (scripts/fetch_public_data.py 결과)
  data/raw/gov24_service_list.json
  data/raw/gov24_child_details.json
  data/raw/gov24_child_conditions.json
  data/raw/childcare_documents.json

출력
  data/processed/policy_candidates.json    초등 자녀 가구 대상 정책 후보 (원문 보존)
  data/processed/childcare_documents.json  아이돌봄 정부지원 입증서류 (가정 유형별)

다음 단계에서 후보마다 매칭 조건(맞벌이·한부모·다자녀, 학년 등)을 추출하고
사람이 검토한 뒤 data/processed/policies.json 으로 확정한다.

실행
  python3 scripts/preprocess_policies.py
"""

import json
import re
from datetime import date
from pathlib import Path

from fetch_public_data import is_available_in_yongin, is_child_related

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
OUT_DIR = BASE_DIR / "data" / "processed"

SOURCE_NAME = "행정안전부 대한민국 공공서비스(혜택) 정보 (공공데이터포털)"
DOCS_SOURCE_NAME = "한국건강가정진흥원 아이돌봄 정부지원 자격여부 입증서류 및 확인방법 정보 (공공데이터포털)"
CHILDCARE_SERVICE_ID = "423000000362"  # 아이돌봄 서비스

# 초등학생 나이 (만 나이)
ELEMENTARY_AGE = (6, 12)

# 초등 자녀 가구와 관계있을 수 있는 서비스분야
FIELDS = {"보육·교육", "보호·돌봄", "생활안정", "문화·환경", "보건·의료", "행정·안전"}

# 서비스명에 들어 있으면 초등 자녀 가구 대상이 아닌 것으로 보는 단어
EXCLUDE_NAME_KEYWORDS = [
    "노인", "어르신", "효도", "경로", "대학", "고교", "고등", "중·고", "중고", "청년",
    "출산", "임신", "신혼", "난임", "영유아", "어린이집", "누리과정", "보육료", "교복", "창업", "취업",
]

# 지원조건 코드표 (공공서비스 API 명세 supportConditions_model)
GENDER_CODES = {"JA0101": "남성", "JA0102": "여성"}
INCOME_CODES = {
    "JA0201": "중위소득 0~50%",
    "JA0202": "중위소득 51~75%",
    "JA0203": "중위소득 76~100%",
    "JA0204": "중위소득 101~200%",
    "JA0205": "중위소득 200% 초과",
}
# 개인 특성. JA0322(해당사항없음)이 Y면 특별한 해당 사항이 없는 사람도 대상
PERSONAL_CODES = {
    "JA0301": "예비부모/난임",
    "JA0302": "임산부",
    "JA0303": "출산/입양",
    "JA0313": "농업인",
    "JA0314": "어업인",
    "JA0315": "축산업인",
    "JA0316": "임업인",
    "JA0317": "초등학생",
    "JA0318": "중학생",
    "JA0319": "고등학생",
    "JA0320": "대학생/대학원생",
    "JA0326": "근로자/직장인",
    "JA0327": "구직자/실업자",
    "JA0328": "장애인",
    "JA0329": "국가보훈대상자",
    "JA0330": "질병/질환자",
}
PERSONAL_NONE = "JA0322"
# 가구 특성. JA0410(해당사항없음)이 Y면 특별한 해당 사항이 없는 가구도 대상
HOUSEHOLD_CODES = {
    "JA0401": "다문화가족",
    "JA0402": "북한이탈주민",
    "JA0403": "한부모가정/조손가정",
    "JA0404": "1인가구",
    "JA0411": "다자녀가구",
    "JA0412": "무주택세대",
    "JA0413": "신규전입",
    "JA0414": "확대가족",
}
HOUSEHOLD_NONE = "JA0410"
STUDENT_CODES = ["JA0317", "JA0318", "JA0319", "JA0320"]


def load(filename):
    with open(RAW_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def save(data, filename):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  저장: {path.relative_to(BASE_DIR)} ({len(data)}건)")


def clean(text):
    """줄바꿈 통일, 앞뒤 공백 제거, 빈 값과 '해당없음'은 None"""
    if text is None:
        return None
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if text in ("", "-", "해당없음"):
        return None
    return text


def to_date(value):
    """'20260511104632' 또는 '2026-05-11' → '2026-05-11'"""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def split_list(text):
    """'아이돌봄 지원법 시행령||아이돌봄 지원법' → ['아이돌봄 지원법 시행령', '아이돌봄 지원법']"""
    text = clean(text)
    if text is None:
        return []
    return [t.strip() for t in text.split("||") if t.strip()]


def flagged(cond, codes):
    return [label for code, label in codes.items() if cond.get(code) == "Y"]


def group(cond, codes, none_code):
    """개인·가구 특성: 표시된 항목이 없으면 제한 없음(None)"""
    allowed = flagged(cond, codes)
    none_ok = cond.get(none_code) == "Y"
    if not allowed and not none_ok:
        return None
    if none_ok and len(allowed) == len(codes):
        return None
    return {"allowed": allowed, "none_ok": none_ok}


def decode_conditions(cond):
    """지원조건 코드 → 읽을 수 있는 조건. None은 제한 없음(또는 정보 없음)

    코드가 Y인 것은 '이 대상은 제외하지 않는다'는 뜻이라 우대 조건이 아니다.
    """
    age_min = cond.get("JA0110")
    age_max = cond.get("JA0111")
    gender = flagged(cond, GENDER_CODES)
    income = flagged(cond, INCOME_CODES)
    return {
        "age_min": age_min if age_min else None,
        "age_max": age_max if age_max is not None and age_max < 100 else None,
        "gender": gender if len(gender) == 1 else None,
        "income": income if income and len(income) < len(INCOME_CODES) else None,
        "personal": group(cond, PERSONAL_CODES, PERSONAL_NONE),
        "household": group(cond, HOUSEHOLD_CODES, HOUSEHOLD_NONE),
    }


def region_of(item):
    agency = item.get("소관기관명", "")
    if "용인" in agency:
        return "yongin"
    if item.get("소관기관유형") in ("중앙행정기관", "공공기관"):
        return "national"
    return "gyeonggi"


def for_families(item):
    """개인 또는 가구가 신청할 수 있는 서비스 (법인·시설·소상공인 전용 제외)"""
    users = item.get("사용자구분", "").split("||")
    return "개인" in users or "가구" in users


def may_fit_elementary(item, cond):
    """초등 자녀 가구가 받을 가능성이 있는지 (넓게 남기고 다음 단계에서 다시 거름)"""
    age_min, age_max = cond.get("JA0110"), cond.get("JA0111")
    if age_min is not None and age_min > ELEMENTARY_AGE[1]:
        return False
    if age_max is not None and age_max < ELEMENTARY_AGE[0]:
        return False
    # 학생 구분이 있는데 초등학생이 빠져 있으면 중·고·대학생 대상
    if any(cond.get(k) == "Y" for k in STUDENT_CODES) and cond.get("JA0317") != "Y":
        return False
    if item.get("서비스분야") not in FIELDS:
        return False
    if any(k in item.get("서비스명", "") for k in EXCLUDE_NAME_KEYWORDS):
        return False
    return True


def build_policy(item, detail, cond, fetched_at):
    d = detail or {}
    return {
        "id": item["서비스ID"],
        "name": clean(item.get("서비스명")),
        "agency": clean(item.get("소관기관명")),
        "agency_type": clean(item.get("소관기관유형")),
        "department": clean(item.get("부서명")),
        "region": region_of(item),
        "category": clean(item.get("서비스분야")),
        "support_type": clean(item.get("지원유형")),
        "user_type": split_list(item.get("사용자구분")),
        "summary": clean(item.get("서비스목적요약")),
        # 요약·챗봇 근거로 쓰는 원문. 상세 API 값이 있으면 상세를 우선
        "texts": {
            "purpose": clean(d.get("서비스목적")),
            "target": clean(d.get("지원대상") or item.get("지원대상")),
            "criteria": clean(d.get("선정기준") or item.get("선정기준")),
            "benefits": clean(d.get("지원내용") or item.get("지원내용")),
            "how_to_apply": clean(d.get("신청방법") or item.get("신청방법")),
            "documents": clean(d.get("구비서류")),
            "documents_self_check": clean(d.get("본인확인필요구비서류")),
            "documents_official_check": clean(d.get("공무원확인구비서류")),
        },
        "apply": {
            "deadline_type": clean(item.get("신청기한유형")),
            "deadline": clean(d.get("신청기한") or item.get("신청기한")),
            "reception": clean(d.get("접수기관명") or item.get("접수기관")),
            "contact": clean(d.get("문의처") or item.get("전화문의")),
            "online_url": clean(d.get("온라인신청사이트URL")),
        },
        "laws": split_list(d.get("법령")) + split_list(d.get("자치법규")) + split_list(d.get("행정규칙")),
        "conditions": decode_conditions(cond),
        "source": {
            "name": SOURCE_NAME,
            "url": clean(item.get("상세조회URL")),
            "updated_at": to_date(item.get("수정일시")),
            "fetched_at": fetched_at,
        },
    }


def one_line(text):
    """'맞벌이 가정\\n(취업\\n증빙)' → '맞벌이 가정(취업 증빙)'"""
    text = clean(text)
    if text is None:
        return None
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"･ ", "･", text)
    return re.sub(r" \(", "(", text)


def build_childcare_documents(raw):
    docs = []
    for x in raw:
        docs.append({
            "household_type": one_line(x.get("gvmtSprtDvsnNm")),
            "detail_type": one_line(x.get("sprtTrgtNm")),
            "documents": clean(x.get("flfllDcmntCn")),
            "how_to_get": clean(x.get("idntyAndIssuMeanCn")),
            "base_year": clean(x.get("crtrYr")),
            "data_date": to_date(x.get("dataCrtrYmd")),
        })
    docs.sort(key=lambda x: (x["household_type"] or "", x["detail_type"] or ""))
    return docs


def main():
    service_list = load("gov24_service_list.json")
    details = {x["서비스ID"]: x for x in load("gov24_child_details.json")}
    conditions = {x["서비스ID"]: x for x in load("gov24_child_conditions.json")}
    fetched_at = date.fromtimestamp((RAW_DIR / "gov24_service_list.json").stat().st_mtime).isoformat()

    steps = [
        ("아동·돌봄 관련", is_child_related),
        ("용인시 주민 이용 가능", is_available_in_yongin),
        ("개인·가구 대상", for_families),
        ("지원조건 수집됨", lambda s: s["서비스ID"] in conditions),
        ("초등 자녀 가구 가능성", lambda s: may_fit_elementary(s, conditions[s["서비스ID"]])),
    ]
    items = service_list
    print(f"[정책] 전체 {len(items)}건")
    for label, check in steps:
        items = [s for s in items if check(s)]
        print(f"  → {label}: {len(items)}건")

    policies = [
        build_policy(s, details.get(s["서비스ID"]), conditions[s["서비스ID"]], fetched_at)
        for s in items
    ]
    missing_detail = sum(1 for s in items if s["서비스ID"] not in details)
    if missing_detail:
        print(f"  상세 정보 없음 {missing_detail}건 (목록 정보로 채움)")

    childcare_docs = build_childcare_documents(load("childcare_documents.json"))
    for p in policies:
        if p["id"] == CHILDCARE_SERVICE_ID:
            p["household_documents"] = {
                "source": DOCS_SOURCE_NAME,
                "file": "data/processed/childcare_documents.json",
            }

    region_order = {"yongin": 0, "gyeonggi": 1, "national": 2}
    policies.sort(key=lambda p: (region_order[p["region"]], p["agency"] or "", p["name"] or ""))

    save(policies, "policy_candidates.json")
    save(childcare_docs, "childcare_documents.json")
    print("\n완료")


if __name__ == "__main__":
    main()
