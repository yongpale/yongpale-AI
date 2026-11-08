"""
정책 데이터 전처리 (3단계: 검토 결과 반영해 최종본 만들기)

입력
  data/processed/policy_candidates.json   (scripts/preprocess_policies.py 결과)
  data/review/policy_review.csv           (scripts/extract_policy_conditions.py 결과를 사람이 검토한 표)

출력
  data/processed/policies.json

검토 방법
  policy_review.csv 를 엑셀·Numbers로 열어 include 열을 Y(포함) / N(제외)로 정하고,
  추출 값이 틀린 칸은 직접 고친 뒤 CSV 형식으로 저장한다.

실행
  python3 scripts/build_policies.py
"""

import csv
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = BASE_DIR / "data" / "processed" / "policy_candidates.json"
REVIEW_FILE = BASE_DIR / "data" / "review" / "policy_review.csv"
OUT_FILE = BASE_DIR / "data" / "processed" / "policies.json"

REQUIREMENTS = {"required", "preferred", "not_mentioned"}


def to_int(value):
    value = (value or "").strip()
    return int(float(value)) if value else None


def to_bool(value):
    return (value or "").strip().lower() in ("true", "y", "yes", "1")


def to_text(value):
    value = (value or "").strip()
    return value or None


def to_requirement(value, row_id, column):
    value = (value or "").strip() or "not_mentioned"
    if value not in REQUIREMENTS:
        print(f"[오류] {row_id} {column} 값 '{value}' → required / preferred / not_mentioned 중 하나여야 합니다")
        sys.exit(1)
    return value


def match_from_row(row):
    return {
        "category": to_text(row["category"]),
        "grade_min": to_int(row["grade_min"]),
        "grade_max": to_int(row["grade_max"]),
        "dual_income": to_requirement(row["dual_income"], row["id"], "dual_income"),
        "single_parent": to_requirement(row["single_parent"], row["id"], "single_parent"),
        "multi_child": to_requirement(row["multi_child"], row["id"], "multi_child"),
        "low_income_only": to_bool(row["low_income_only"]),
        "income_limit": to_text(row["income_limit"]),
        "other_requirements": [x.strip() for x in (row["other_requirements"] or "").split(" / ") if x.strip()],
        "apply_period": to_text(row["apply_period"]),
    }


def main():
    with open(CANDIDATES_FILE, encoding="utf-8") as f:
        candidates = {p["id"]: p for p in json.load(f)}
    # 엑셀에서 저장하면 BOM이 붙을 수 있어서 utf-8-sig
    with open(REVIEW_FILE, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # 엑셀이 긴 숫자 ID를 4.23E+11 처럼 바꾸는 경우를 대비해 서비스명+기관명으로도 찾는다
    by_name = {(p["name"], p["agency"]): pid for pid, p in candidates.items()}

    policies = []
    for row in rows:
        if (row["include"] or "").strip().upper() != "Y":
            continue
        pid = row["id"].strip()
        if pid not in candidates:
            pid = by_name.get((row["name"].strip(), row["agency"].strip()))
        if pid is None:
            print(f"[오류] 후보에서 찾을 수 없는 정책: {row['id']} {row['name']}")
            sys.exit(1)
        policy = dict(candidates[pid])
        policy["match"] = match_from_row(row)
        policies.append(policy)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)
    print(f"검토 {len(rows)}건 중 포함 {len(policies)}건")
    print(f"  저장: {OUT_FILE.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
