"""검색(RAG)용 문서: 정책 하나 = 문서 하나, 시설 하나 = 문서 하나

임베딩 생성(scripts/build_embeddings.py)과 챗봇 답변 근거(app/services/chat.py)가 같은 문서를 쓴다.
시설 데이터의 null은 '정보 없음'이다. 문서에도 '정보 없음'으로 적어서 '운영 안 함'으로 읽히지 않게 한다.
"""

from hashlib import sha256

from app import data_loader

MAX_TEXT = 1800
NO_INFO = "정보 없음"
POLICY_SOURCE_NAME = "행정안전부 대한민국 공공서비스(혜택) 정보"
SUMMARY_TITLES = {"eligibility": "신청 자격", "benefits": "지원 혜택", "documents": "필요 서류", "period": "신청 기간"}


def _cut(text, limit=500):
    if not text:
        return None
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _lines(pairs):
    return "\n".join(f"{k}: {v}" for k, v in pairs if v)


def policy_doc(policy, summary=None):
    t, a, m = policy["texts"], policy["apply"], policy["match"]
    pairs = [
        ("정책명", policy["name"]),
        ("소관기관", policy["agency"]),
        ("분야", m.get("category")),
        ("요약", policy.get("summary")),
    ]
    if summary:
        pairs += [(SUMMARY_TITLES[k], summary[k]["text"]) for k in SUMMARY_TITLES if k in summary]
    pairs += [
        ("지원대상 원문", _cut(t.get("target"))),
        ("선정기준 원문", _cut(t.get("criteria"))),
        ("지원내용 원문", _cut(t.get("benefits"))),
        ("신청방법 원문", _cut(t.get("how_to_apply"), 300)),
        ("구비서류 원문", _cut(t.get("documents"), 300)),
        ("신청기한", a.get("deadline")),
        ("접수기관", a.get("reception")),
        ("문의처", a.get("contact")),
        ("온라인 신청", a.get("online_url")),
        ("참고", m.get("notes")),
    ]
    text = _lines(pairs)
    return {
        "id": f"policy:{policy['id']}",
        "type": "policy",
        "ref_id": policy["id"],
        "title": policy["name"],
        "text": text[:MAX_TEXT],
        "source": {
            "name": POLICY_SOURCE_NAME,
            "url": policy["source"].get("url"),
            "updated_at": policy["source"].get("updated_at"),
        },
    }


def _hours(h):
    if not h or not h.get("open") or not h.get("close"):
        return NO_INFO
    return f"{h['open']}~{h['close']}"


def _flag(value):
    return "제공" if value else NO_INFO


def _fee(fee):
    fee = fee or {}
    if fee.get("type") == "free":
        return "무료"
    if fee.get("amount"):
        unit = {"day": "하루", "month": "월"}.get(fee.get("unit"), "")
        return f"{unit} {fee['amount']:,}원".strip()
    return NO_INFO


def _ages(f):
    if f.get("all_ages"):
        return "연령 제한 없음"
    if f.get("age_min") is None and f.get("age_max") is None:
        return NO_INFO
    return f"{f.get('age_min') or ''}~{f.get('age_max') or ''}세"


def facility_doc(f):
    hours = f.get("hours") or {}
    temp = f.get("temp_care_hours") or {}
    pairs = [
        ("시설명", f["name"]),
        ("유형", f["type"]),
        ("주소", f.get("address")),
        ("지역", " ".join(x for x in (f.get("gu"), f.get("dong")) if x)),
        ("전화", f.get("phone")),
        ("이용 연령", _ages(f)),
        ("학기 중 운영시간", _hours(hours.get("semester"))),
        ("방학 중 운영시간", _hours(hours.get("vacation"))),
        ("토요일 운영시간", _hours(hours.get("saturday"))),
        ("일시돌봄 운영시간(학기 중)", _hours(temp.get("semester")) if temp else None),
        ("이용료", _fee(f.get("fee"))),
        ("급식", _flag(f.get("meal"))),
        ("간식", _flag(f.get("snack"))),
        ("등하원 지원", _flag(f.get("pickup"))),
        ("정원", f"{f['capacity']}명" if f.get("capacity") else NO_INFO),
        ("프로그램", _cut(" / ".join(f.get("programs") or []), 400)),
        ("신청 안내", _cut(f.get("application_info"), 300)),
    ]
    return {
        "id": f"facility:{f['id']}",
        "type": "facility",
        "ref_id": f["id"],
        "title": f["name"],
        "text": _lines(pairs)[:MAX_TEXT],
        "source": {"name": f.get("source"), "url": None, "updated_at": f.get("verified_at")},
    }


def all_documents():
    summaries = data_loader.load_policy_summaries()
    docs = [policy_doc(p, summaries.get(p["id"])) for p in data_loader.load_policies()]
    docs += [facility_doc(f) for f in data_loader.load_facilities()]
    return docs


def text_hash(text):
    return sha256(text.encode("utf-8")).hexdigest()[:16]
