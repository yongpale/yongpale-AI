"""
용인시 돌봄시설 데이터 전처리

입력
  data/raw/yongin_dahamkke_centers.xlsx      다함께돌봄센터
  data/raw/yongin_jiyeok_child_centers.xlsx  지역아동센터

출력
  data/processed/facilities.json
  data/processed/facilities.csv

실행
  python scripts/preprocess_facilities.py
"""

import json
import re
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
OUT_DIR = BASE_DIR / "data" / "processed"

DAHAMKKE_FILE = RAW_DIR / "yongin_dahamkke_centers.xlsx"
JIYEOK_FILE = RAW_DIR / "yongin_jiyeok_child_centers.xlsx"

# 주소에서 동 이름처럼 보이지만 건물 이름인 것들
NOT_DONG = {"관리동", "공동시설동", "시설동"}


def clean(value):
    """빈 값(NaN, '-', 공백)은 None으로 통일"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text in ("", "-", "nan"):
        return None
    return text


def parse_hours(value):
    """'10:00 ~ 19:00' -> {'open': '10:00', 'close': '19:00'}"""
    text = clean(value)
    if not text:
        return None
    match = re.match(r"(\d{1,2}:\d{2})\s*~\s*(\d{1,2}:\d{2})", text)
    if not match:
        return None
    open_time, close_time = match.groups()
    return {"open": open_time.zfill(5), "close": close_time.zfill(5)}


def parse_age(value):
    """'8세~16세' -> (8, 16), '전연령' -> (None, None, True)"""
    text = clean(value)
    if not text:
        return None, None, False
    if "전연령" in text:
        return None, None, True
    match = re.match(r"(\d+)\s*세?\s*~\s*(\d+)\s*세?", text)
    if not match:
        return None, None, False
    return int(match.group(1)), int(match.group(2)), False


def parse_fee(value):
    """'무료' / '유료 (일2,200 원)' / '유료 (월50,000 원)' 정리"""
    text = clean(value)
    if not text:
        return {"type": "unknown", "unit": None, "amount": None}
    if "무료" in text:
        return {"type": "free", "unit": None, "amount": 0}

    unit = None
    if "일" in text:
        unit = "day"
    elif "월" in text:
        unit = "month"

    amount_match = re.search(r"([\d,]+)\s*원", text)
    amount = int(amount_match.group(1).replace(",", "")) if amount_match else None
    return {"type": "paid", "unit": unit, "amount": amount}


def is_provided(value):
    """'제공' -> True, 빈칸 -> None (원본에 '미제공' 표기가 없어 빈칸은 정보 없음으로 처리)"""
    return True if clean(value) == "제공" else None


def to_int(value):
    text = clean(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def extract_dong(address):
    """주소에서 읍/면/동 추출. 도로명 주소만 있으면 None"""
    text = clean(address)
    if not text:
        return None

    candidates = re.findall(r"(?<![가-힣\d])([가-힣]{1,5}\d?(?:동|읍|면))(?![가-힣])", text)
    for name in candidates:
        if name in NOT_DONG or name.endswith("구"):
            continue
        return name

    # 주소에 동 이름이 없고 '보정동행정복지센터'처럼 기관명에만 있는 경우
    center_match = re.search(r"([가-힣]{1,5}\d?동)행정복지센터", text)
    if center_match:
        return center_match.group(1)
    return None


def split_programs(value):
    """'보호 프로그램: ... / 교육 프로그램: ...' -> 리스트"""
    text = clean(value)
    if not text:
        return []
    return [part.strip() for part in text.split(" / ") if part.strip()]


def base_record(row, facility_type):
    age_min, age_max, all_ages = parse_age(row.get("이용가능연령"))
    return {
        "id": clean(row.get("시설ID")),
        "name": clean(row.get("센터명")),
        "type": facility_type,
        "gu": clean(row.get("구")),
        "dong": extract_dong(row.get("주소")),
        "address": clean(row.get("주소")),
        "phone": clean(row.get("연락처")),
        "lat": None,
        "lng": None,
        "age_min": age_min,
        "age_max": age_max,
        "all_ages": all_ages,
        "fee": parse_fee(row.get("이용료")),
        "meal": is_provided(row.get("급식")),
        "snack": is_provided(row.get("간식")),
        "pickup": is_provided(row.get("등하원지원")),
        "programs": split_programs(row.get("프로그램")),
        "application_info": clean(row.get("신청안내")),
        "source": clean(row.get("출처")),
        "verified_at": str(row.get("확인일"))[:10] if clean(row.get("확인일")) else None,
    }


def load_dahamkke():
    df = pd.read_excel(DAHAMKKE_FILE)
    records = []
    for _, row in df.iterrows():
        record = base_record(row, "다함께돌봄센터")
        record["hours"] = {
            "semester": parse_hours(row.get("정기돌봄_학기중")),
            "vacation": parse_hours(row.get("정기돌봄_방학중")),
            "saturday": None,
        }
        record["temp_care_hours"] = {
            "semester": parse_hours(row.get("일시돌봄_학기중")),
            "vacation": parse_hours(row.get("일시돌봄_방학중")),
        }
        record["capacity"] = to_int(row.get("정기돌봄_정원"))
        record["temp_capacity"] = to_int(row.get("일시돌봄_정원"))
        records.append(record)
    return records


def load_jiyeok():
    df = pd.read_excel(JIYEOK_FILE)
    records = []
    for _, row in df.iterrows():
        record = base_record(row, "지역아동센터")
        record["hours"] = {
            "semester": parse_hours(row.get("학기중_운영시간")),
            "vacation": parse_hours(row.get("방학중_운영시간")),
            "saturday": parse_hours(row.get("토요일_운영시간")),
        }
        record["temp_care_hours"] = None
        record["capacity"] = to_int(row.get("정원"))
        record["temp_capacity"] = None
        records.append(record)
    return records


def to_flat_row(record):
    """DB 적재용 CSV 한 줄"""
    hours = record["hours"] or {}
    temp = record["temp_care_hours"] or {}

    def h(block, key, field):
        return (block.get(key) or {}).get(field)

    return {
        "id": record["id"],
        "name": record["name"],
        "type": record["type"],
        "gu": record["gu"],
        "dong": record["dong"],
        "address": record["address"],
        "phone": record["phone"],
        "lat": record["lat"],
        "lng": record["lng"],
        "age_min": record["age_min"],
        "age_max": record["age_max"],
        "all_ages": record["all_ages"],
        "semester_open": h(hours, "semester", "open"),
        "semester_close": h(hours, "semester", "close"),
        "vacation_open": h(hours, "vacation", "open"),
        "vacation_close": h(hours, "vacation", "close"),
        "saturday_open": h(hours, "saturday", "open"),
        "saturday_close": h(hours, "saturday", "close"),
        "temp_semester_open": h(temp, "semester", "open"),
        "temp_semester_close": h(temp, "semester", "close"),
        "temp_vacation_open": h(temp, "vacation", "open"),
        "temp_vacation_close": h(temp, "vacation", "close"),
        "fee_type": record["fee"]["type"],
        "fee_unit": record["fee"]["unit"],
        "fee_amount": record["fee"]["amount"],
        "meal": record["meal"],
        "snack": record["snack"],
        "pickup": record["pickup"],
        "capacity": record["capacity"],
        "temp_capacity": record["temp_capacity"],
        "programs": " / ".join(record["programs"]),
        "application_info": record["application_info"],
        "source": record["source"],
        "verified_at": record["verified_at"],
    }


def main():
    facilities = load_dahamkke() + load_jiyeok()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUT_DIR / "facilities.json", "w", encoding="utf-8") as f:
        json.dump(facilities, f, ensure_ascii=False, indent=2)

    flat = pd.DataFrame([to_flat_row(r) for r in facilities])
    flat.to_csv(OUT_DIR / "facilities.csv", index=False, encoding="utf-8-sig")

    print(f"시설 {len(facilities)}곳 저장 완료")
    print(flat["type"].value_counts().to_string())
    print(f"동 정보 없음: {flat['dong'].isna().sum()}곳")


if __name__ == "__main__":
    main()
