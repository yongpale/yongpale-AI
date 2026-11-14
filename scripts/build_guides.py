"""
챗봇 안내 문서 만들기

정책·시설 데이터를 묶어 요약한 문서와 법령 원문 정의를 만든다. 새 사실은 넣지 않고 기존 데이터만 정리한다.
"다함께돌봄센터가 뭐예요?", "3학년이 되면 뭐가 달라져요?"처럼 개별 정책·시설 문서로는 답하기 어려운 질문의 근거로 쓴다.

입력
  data/processed/policies.json, facilities.json
  data/raw/official_guides.json   법령 원문 (다함께돌봄센터, 지역아동센터 정의)

출력
  data/processed/guides.json

실행
  python3 scripts/build_guides.py
  python3 scripts/build_embeddings.py   (안내 문서를 검색에 넣으려면 이어서 실행)
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services.matching import SPECIAL_LABEL, special_groups  # noqa: E402

RAW_DIR = config.DATA_DIR / "raw"
OUT_FILE = config.PROCESSED_DIR / "guides.json"
POLICY_SOURCE = "행정안전부 대한민국 공공서비스(혜택) 정보"
FACILITY_SOURCE = "경기도 아동언제나돌봄 우리동네 돌봄자원 찾기"
REGION_LABEL = {"yongin": "용인시", "gyeonggi": "경기도", "national": "중앙정부"}
CATEGORIES = ["돌봄", "방과후·학습", "교육비"]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def policy_tags(p):
    """'소득 조건', '다문화가족 대상' 같은 짧은 조건 표시"""
    m = p["match"]
    tags = [f"{SPECIAL_LABEL[g]} 대상" for g in sorted(special_groups(p))]
    if m.get("low_income_only"):
        tags.append("소득 조건")
    for field, label in (("dual_income", "맞벌이"), ("single_parent", "한부모"), ("multi_child", "다자녀")):
        if m.get(field) == "required":
            tags.append(f"{label} 가구만")
        elif m.get(field) == "preferred":
            tags.append(f"{label} 우대")
    return tags


def policy_line(p):
    m = p["match"]
    grade = "" if (m["grade_min"], m["grade_max"]) == (1, 6) else f", 초{m['grade_min']}~초{m['grade_max']}"
    tags = policy_tags(p)
    tag = f" [{', '.join(tags)}]" if tags else ""
    return f"- {p['name']} ({REGION_LABEL[p['region']]}, {m['category']}{grade}){tag}"


def latest(policies):
    return max(p["source"]["updated_at"] for p in policies)


def grade_guides(policies):
    guides = []
    for g in range(1, 7):
        ok = [p for p in policies if p["match"]["grade_min"] <= g <= p["match"]["grade_max"]]
        new = [p for p in ok if p["match"]["grade_min"] == g and g > 1]
        ended = [p for p in policies if p["match"]["grade_max"] == g - 1]
        lines = [
            f"초등학교 {g}학년 자녀가 대상에 포함되는 정책은 {len(ok)}건이에요.",
            f"그중 소득 조건이 있는 정책 {sum(1 for p in ok if p['match'].get('low_income_only'))}건, "
            f"다문화·장애 등 특정 가구 대상 정책 {sum(1 for p in ok if special_groups(p))}건이에요.",
        ]
        if g > 1:
            lines.append(f"초{g - 1}에서 초{g}이 되면서 새로 대상이 되는 정책: "
                         + (", ".join(p["name"] for p in new) if new else "없음"))
            lines.append(f"초{g - 1}까지만 대상이라 초{g}부터 대상이 아닌 정책: "
                         + (", ".join(p["name"] for p in ended) if ended else "없음"))
        lines.append(f"초{g} 대상 정책 목록:")
        lines += [policy_line(p) for p in ok]
        guides.append({
            "id": f"grade-{g}",
            "source_type": "policy",
            "title": f"초등 {g}학년 대상 정책 안내",
            "text": "\n".join(lines),
            "source_name": POLICY_SOURCE,
            "source_url": None,
            "updated_at": latest(ok),
        })
    return guides


def category_guides(policies):
    guides = []
    for cat in CATEGORIES:
        items = [p for p in policies if p["match"]["category"] == cat]
        lines = [
            f"'{cat}' 분야 정책은 {len(items)}건이에요 "
            f"(용인시 {sum(1 for p in items if p['region'] == 'yongin')}건, "
            f"경기도 {sum(1 for p in items if p['region'] == 'gyeonggi')}건, "
            f"중앙정부 {sum(1 for p in items if p['region'] == 'national')}건).",
            f"소득 조건 없이 신청 자격이 정해진 정책: "
            + ", ".join(p["name"] for p in items if not p["match"].get("low_income_only") and not special_groups(p)),
            "정책 목록:",
        ] + [policy_line(p) for p in items]
        guides.append({
            "id": f"category-{cat}",
            "source_type": "policy",
            "title": f"{cat} 분야 정책 안내",
            "text": "\n".join(lines),
            "source_name": POLICY_SOURCE,
            "source_url": None,
            "updated_at": latest(items),
        })
    return guides


def hours_summary(items, period):
    known = [f["hours"][period] for f in items if f["hours"].get(period)]
    if not known:
        return f"정보 없음 ({len(items)}곳 모두)"
    opens = sorted(h["open"] for h in known)
    closes = sorted(h["close"] for h in known)
    missing = len(items) - len(known)
    text = f"여는 시간 {opens[0]}~{opens[-1]}, 닫는 시간 {closes[0]}~{closes[-1]} (정보 있는 {len(known)}곳 기준)"
    return text + (f", {missing}곳은 정보 없음" if missing else "")


def facility_type_guide(ftype, facilities, official):
    items = [f for f in facilities if f["type"] == ftype]
    by_gu = Counter(f["gu"] for f in items)
    ages = Counter("연령 제한 없음" if f["all_ages"] else
                   (f"{f['age_min']}~{f['age_max']}세" if f["age_min"] is not None else "정보 없음") for f in items)
    free = sum(1 for f in items if (f["fee"] or {}).get("type") == "free")
    paid = [f["fee"] for f in items if (f["fee"] or {}).get("type") == "paid" and f["fee"].get("amount")]
    paid_text = ", ".join(sorted({f"{'하루' if x.get('unit') == 'day' else '월'} {x['amount']:,}원" for x in paid}))
    saturday = sum(1 for f in items if f["hours"].get("saturday"))
    lines = []
    if official:
        lines += [f"[법령 정의] {official['source_name']}", official["text"], ""]
    lines += [
        f"[용인시 현황] 용인시 {ftype}는 {len(items)}곳이에요 "
        f"(처인구 {by_gu.get('처인구', 0)}곳, 기흥구 {by_gu.get('기흥구', 0)}곳, 수지구 {by_gu.get('수지구', 0)}곳).",
        "이용 연령: " + ", ".join(f"{k} {v}곳" for k, v in ages.most_common()),
        "학기 중 운영시간: " + hours_summary(items, "semester"),
        "방학 중 운영시간: " + hours_summary(items, "vacation"),
        f"토요일 운영시간 정보가 있는 곳: {saturday}곳 (나머지는 정보 없음이며 미운영이라는 뜻은 아님)",
        f"이용료: 무료 {free}곳" + (f", 유료 {len(paid)}곳 ({paid_text})" if paid else "")
        + (f", 정보 없음 {len(items) - free - len(paid)}곳" if len(items) - free - len(paid) else ""),
        f"급식 제공 {sum(1 for f in items if f['meal'])}곳, 간식 제공 {sum(1 for f in items if f['snack'])}곳, "
        f"등하원 지원 {sum(1 for f in items if f['pickup'])}곳 (나머지는 정보 없음)",
        "잔여석·현원 정보는 없어서 시설에 직접 문의해야 해요.",
    ]
    return {
        "id": f"facility-type-{ftype}",
        "source_type": "facility",
        "title": f"{ftype} 안내",
        "text": "\n".join(lines),
        "source_name": (official["source_name"] + ", " if official else "") + FACILITY_SOURCE,
        "source_url": official["source_url"] if official else None,
        "updated_at": max(f["verified_at"] for f in items),
    }


def main():
    policies = load(config.PROCESSED_DIR / "policies.json")
    facilities = load(config.PROCESSED_DIR / "facilities.json")
    official = {o["facility_type"]: o for o in load(RAW_DIR / "official_guides.json")}

    guides = [facility_type_guide(t, facilities, official.get(t)) for t in ("다함께돌봄센터", "지역아동센터")]
    guides += grade_guides(policies) + category_guides(policies)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(guides, f, ensure_ascii=False, indent=2)
    print(f"안내 문서 {len(guides)}건 저장: {OUT_FILE.relative_to(config.BASE_DIR)}")
    for g in guides:
        print(f"  {g['id']:28} {len(g['text']):5}자  {g['title']}")


if __name__ == "__main__":
    main()
