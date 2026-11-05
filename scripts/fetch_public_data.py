"""
공공데이터포털 API 원본 수집

1) 행정안전부 대한민국 공공서비스(혜택) 정보
   - 전체 목록을 받은 뒤 아동·돌봄 관련 서비스만 골라 상세 정보 조회
2) 한국건강가정진흥원 아이돌봄 정부지원 자격여부 입증서류

출력 (가공 전 원본)
  data/raw/gov24_service_list.json      공공서비스 전체 목록
  data/raw/gov24_child_details.json     아동·돌봄 관련 서비스 상세
  data/raw/gov24_child_conditions.json  아동·돌봄 관련 서비스 지원조건
  data/raw/childcare_documents.json     아이돌봄 입증서류

실행
  python3 scripts/fetch_public_data.py          전체 수집
  python3 scripts/fetch_public_data.py --test   연결 확인만 (첫 페이지만 조회)
  python3 scripts/fetch_public_data.py --docs   아이돌봄 입증서류만
  python3 scripts/fetch_public_data.py --gov24  공공서비스만
  (--test는 --docs, --gov24와 같이 쓸 수 있음)

.env
  DATA_GO_KR_KEY=발급받은_인증키
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"

load_dotenv(BASE_DIR / ".env")
SERVICE_KEY = os.getenv("DATA_GO_KR_KEY")

GOV24_BASE = "https://api.odcloud.kr/api/gov24/v3"
DOCS_URL = "https://apis.data.go.kr/1383000/idis/qualificationDocumentsService/getQualificationDocumentsList"

# 아동·돌봄 관련 서비스를 고르는 키워드
CHILD_KEYWORDS = ["아동", "초등", "돌봄", "방과후", "아이", "자녀", "양육", "보육", "늘봄", "어린이"]

TIMEOUT = 30


def save(data, filename):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  저장: {path.relative_to(BASE_DIR)} ({len(data) if isinstance(data, list) else 1}건)")


def request_json(url, params, retries=3):
    for attempt in range(1, retries + 1):
        try:
            res = requests.get(url, params=params, timeout=TIMEOUT)
            break
        except requests.RequestException as e:
            # 오류 메시지에 인증키가 포함된 URL이 찍히지 않도록 종류만 출력
            print(f"  연결 실패 ({type(e).__name__}), {attempt}/{retries}회")
            if attempt == retries:
                print(f"\n[오류] {url} 에 연결할 수 없습니다. 인터넷 연결을 확인하고 다시 실행하세요.")
                sys.exit(1)
            time.sleep(3 * attempt)
    try:
        return res.json()
    except ValueError:
        print(f"\n[오류] JSON 응답이 아닙니다 (HTTP {res.status_code})")
        print(res.text[:500])
        sys.exit(1)


# ---------------------------------------------------------------------------
# 1. 공공서비스(혜택) 정보
# ---------------------------------------------------------------------------

def gov24_get(path, page=1, per_page=1000, extra=None):
    params = {"serviceKey": SERVICE_KEY, "page": page, "perPage": per_page, "returnType": "JSON"}
    if extra:
        params.update(extra)
    data = request_json(f"{GOV24_BASE}/{path}", params)
    if "data" not in data:
        print(f"\n[오류] {path} 응답에 data가 없습니다")
        print(json.dumps(data, ensure_ascii=False)[:500])
        sys.exit(1)
    return data


def fetch_gov24_list(test=False):
    print("[공공서비스] 목록 조회")
    first = gov24_get("serviceList", page=1, per_page=10 if test else 1000)
    total = first.get("totalCount", len(first["data"]))
    items = list(first["data"])
    print(f"  전체 {total}건")

    if test:
        print("  응답 키:", list(first.keys()))
        if items:
            print("  항목 키:", list(items[0].keys()))
        return items

    page = 2
    while len(items) < total:
        data = gov24_get("serviceList", page=page)
        if not data["data"]:
            break
        items.extend(data["data"])
        print(f"  {len(items)}/{total}")
        page += 1
        time.sleep(0.3)
    return items


def is_child_related(item):
    text = " ".join(str(item.get(k, "")) for k in ("서비스명", "서비스목적요약", "지원대상", "서비스분야"))
    return any(k in text for k in CHILD_KEYWORDS)


def is_available_in_yongin(item):
    """용인시·경기도·중앙부처 서비스만 남기고 다른 지역 서비스는 제외

    소관기관유형 값: 중앙행정기관, 공공기관, 광역시도, 교육청, 시군구, 지방출자_출연기관, 지방공기업
    """
    agency = str(item.get("소관기관명", ""))
    agency_type = str(item.get("소관기관유형", ""))
    if "용인" in agency:
        return True
    if agency_type in ("중앙행정기관", "공공기관"):
        return True
    if agency_type == "광역시도":
        return agency == "경기도"
    if agency_type == "교육청":
        return agency == "경기도교육청"
    if agency_type in ("지방출자_출연기관", "지방공기업"):
        # 경기도 산하 기관(예: 경기도사회서비스원)만, 다른 시·군 소속(예: 경기도 고양시 상하수도사업소)은 제외
        return "경기" in agency and not re.match(r"경기도 \S+[시군]", agency)
    # 시군구: 용인시가 아닌 시·군·구
    return False


def fetch_gov24_details(service_ids):
    details, conditions = [], []
    print(f"[공공서비스] 상세·지원조건 조회 ({len(service_ids)}건)")
    for i, sid in enumerate(service_ids, 1):
        cond = {"cond[서비스ID::EQ]": sid}
        details.extend(gov24_get("serviceDetail", per_page=10, extra=cond)["data"])
        conditions.extend(gov24_get("supportConditions", per_page=10, extra=cond)["data"])
        if i % 20 == 0:
            print(f"  {i}/{len(service_ids)}")
        time.sleep(0.2)
    return details, conditions


# ---------------------------------------------------------------------------
# 2. 아이돌봄 입증서류
# ---------------------------------------------------------------------------

def find_items(obj):
    """응답 구조가 문서에 없어서, sprtTrgtNm이 들어 있는 목록을 찾아서 반환"""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "sprtTrgtNm" in obj[0]:
            return obj
        for v in obj:
            found = find_items(v)
            if found is not None:
                return found
    elif isinstance(obj, dict):
        if "sprtTrgtNm" in obj:
            return [obj]
        for v in obj.values():
            found = find_items(v)
            if found is not None:
                return found
    return None


def fetch_childcare_documents(test=False):
    print("[아이돌봄 입증서류] 조회")
    params = {"ServiceKey": SERVICE_KEY, "pageNo": 1, "numOfRows": 10 if test else 1000, "type": "json"}
    data = request_json(DOCS_URL, params)
    items = find_items(data)
    if items is None:
        print("\n[오류] 응답에서 데이터를 찾지 못했습니다. 응답 원문:")
        print(json.dumps(data, ensure_ascii=False)[:800])
        sys.exit(1)
    print(f"  {len(items)}건")
    if test and items:
        print("  항목 키:", list(items[0].keys()))
    return items


def main():
    if not SERVICE_KEY:
        print(".env에 DATA_GO_KR_KEY가 없습니다")
        sys.exit(1)

    test = "--test" in sys.argv
    only_docs = "--docs" in sys.argv
    only_gov24 = "--gov24" in sys.argv
    # 둘 다 없거나 둘 다 있으면 전체 수집
    run_gov24 = only_gov24 or not only_docs
    run_docs = only_docs or not only_gov24

    if run_gov24:
        service_list = fetch_gov24_list(test=test)
        if not test:
            save(service_list, "gov24_service_list.json")
            targets = [s for s in service_list if is_child_related(s) and is_available_in_yongin(s)]
            print(f"[공공서비스] 아동·돌봄 관련 후보 {len(targets)}건")
            details, conditions = fetch_gov24_details([s["서비스ID"] for s in targets])
            save(details, "gov24_child_details.json")
            save(conditions, "gov24_child_conditions.json")

    if run_docs:
        documents = fetch_childcare_documents(test=test)
        if not test:
            save(documents, "childcare_documents.json")

    if test:
        print("\n연결 확인 완료. 전체 수집은 --test 없이 실행하세요.")
        return

    print("\n완료")


if __name__ == "__main__":
    main()
