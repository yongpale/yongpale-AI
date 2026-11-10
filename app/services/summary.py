"""F-004 정책 요약: 4대 핵심 정보(미리 생성) + 가구 맞춤 팁(실시간) + 출처"""

import json

from app import config, data_loader
from app.services import gemini
from app.services.matching import HOUSEHOLD_FLAGS, evaluate

CHILDCARE_SERVICE_ID = "423000000362"  # 아이돌봄 서비스
CHILDCARE_DOCS_SOURCE = "한국건강가정진흥원 아이돌봄 정부지원 자격여부 입증서류 및 확인방법 정보 (공공데이터포털)"

ITEM_TITLES = {
    "eligibility": "신청 자격",
    "benefits": "지원 혜택",
    "documents": "필요 서류",
    "period": "신청 기간",
}
NO_INFO = "원문에 안내가 없어요. 문의처에 확인해 주세요."
FALLBACK_MAX = 300

# 프로필 → 입증서류 가정 유형
HOUSEHOLD_DOC_TYPES = {
    "dual_income": "맞벌이 가정",
    "single_parent": "한부모 가정",
    "multi_child": "다자녀 가정",
}

_tip_cache = gemini.FileCache("tips.json")


def _excerpt(*texts):
    text = "\n".join(t for t in texts if t)
    if not text:
        return None
    return text if len(text) <= FALLBACK_MAX else text[:FALLBACK_MAX].rstrip() + "…"


def fallback_summary(policy):
    """미리 만든 요약이 없을 때 원문을 잘라서 보여준다"""
    t, a = policy["texts"], policy["apply"]
    period = " / ".join(x for x in (a.get("deadline"), a.get("reception") and f"접수: {a['reception']}") if x)
    return {
        "eligibility": {"text": _excerpt(t.get("target"), t.get("criteria")) or NO_INFO,
                        "evidence": [n for k, n in (("target", "지원대상"), ("criteria", "선정기준")) if t.get(k)]},
        "benefits": {"text": _excerpt(t.get("benefits")) or NO_INFO,
                     "evidence": ["지원내용"] if t.get("benefits") else []},
        "documents": {"text": _excerpt(t.get("documents"), t.get("documents_self_check")) or NO_INFO,
                      "evidence": ["구비서류"] if t.get("documents") else []},
        "period": {"text": period or NO_INFO,
                   "evidence": [n for k, n in (("deadline", "신청기한"), ("reception", "접수기관")) if a.get(k)]},
    }


def household_documents(policy, profile):
    """아이돌봄 서비스: 가구 유형에 맞는 정부지원 입증서류"""
    if policy["id"] != CHILDCARE_SERVICE_ID:
        return []
    docs = data_loader.load_childcare_documents()
    if profile is not None:
        wanted = [t for field, t in HOUSEHOLD_DOC_TYPES.items() if getattr(profile, field)]
        if wanted:
            docs = [d for d in docs if any((d["household_type"] or "").startswith(w) for w in wanted)]
    return [
        {k: d[k] for k in ("household_type", "detail_type", "documents", "how_to_get")}
        for d in docs
    ]


def profile_text(profile):
    parts = ["자녀 " + ", ".join(f"초{c.grade}" for c in profile.children)]
    if profile.gu:
        parts.append(f"용인시 {profile.gu} {profile.dong or ''}".strip())
    parts += [label for field, label in HOUSEHOLD_FLAGS if getattr(profile, field)]
    if profile.care_time:
        parts.append(f"돌봄 필요 {profile.care_time.start}~{profile.care_time.end}")
    return " / ".join(parts)


TIP_PROMPT = """너는 용인시 초등학생 자녀를 둔 부모에게 정책 신청을 도와주는 상담사다.
아래 가구 정보와 정책 자료를 보고, 이 가구가 이 정책을 신청할 때 도움이 되는 맞춤 팁을 써라.

규칙
- 2문장 이내, 존댓말("~해요", "~하세요")
- 이 가구 상황(학년, 맞벌이·한부모·다자녀 등)과 직접 관련된 내용만
- 정책 자료에 없는 내용(금액, 기간, 서류, 기관)은 절대 만들지 마라
- 이 서비스는 가구 소득과 다문화·장애 등 특정 가구 여부를 입력받지 않는다. 확인 필요 조건이 있으면
  "기준 중위소득 ○% 이하 가구 대상이에요, 해당되는지 확인해 보세요"처럼 해당 여부를 확인하도록 안내해라
- 판정이 '조건 확인 필요'이면 "받을 수 있어요", "신청하세요"처럼 대상이라고 단정하지 마라
- 인사말, 머리말 없이 팁 문장만 써라

가구 정보: {profile}
판정: {status}
확인 필요 조건: {check_items}
정책: {name} ({agency})
요약:
{summary}
원문(지원대상·선정기준):
{texts}
"""


def condition_sentence(condition):
    """'소득 기준: 기준 중위소득 50% 이하' → '기준 중위소득 50% 이하 가구 대상이에요, 해당되는지 확인해 보세요.'"""
    if condition.startswith("소득 기준: "):
        return f"{condition[len('소득 기준: '):]} 가구 대상이에요, 해당되는지 확인해 보세요."
    if condition.endswith(" 대상"):
        return f"{condition} 정책이에요, 해당되는지 확인해 보세요."
    return f"신청 전에 '{condition}' 조건을 확인해 보세요."


def fallback_tip(policy, profile, status, reasons, check_items):
    sentences = []
    m = policy["match"]
    preferred = [label for field, label in HOUSEHOLD_FLAGS
                 if getattr(profile, field) and m.get(field) in ("preferred", "required")]
    if preferred:
        sentences.append(f"{'·'.join(preferred)} 가구는 이 정책의 지원 대상에 해당해요.")
    if check_items:
        sentences.append(condition_sentence(check_items[0]))
    contact = policy["apply"].get("contact")
    if contact and len(sentences) < 2:
        sentences.append(f"자세한 내용은 {contact}로 문의하세요.")
    if not sentences:
        sentences.append("필요 서류를 미리 준비해 두면 신청이 빨라요.")
    return " ".join(sentences[:2])


def make_tip(policy, profile, summary_items, status, reasons, check_items):
    key = _tip_cache.key(
        TIP_PROMPT, policy["id"], policy["source"]["updated_at"], profile.model_dump(exclude={"dong"}), status
    )
    cached = _tip_cache.get(key)
    if cached:
        return {"text": cached, "generated": True}

    prompt = TIP_PROMPT.format(
        profile=profile_text(profile),
        status={"eligible": "해당 가능", "check": "조건 확인 필요", "ineligible": "해당 안 됨"}[status],
        check_items=", ".join(check_items) or "없음",
        name=policy["name"],
        agency=policy["agency"],
        summary=json.dumps({ITEM_TITLES[k]: v["text"] for k, v in summary_items.items()}, ensure_ascii=False),
        texts=(policy["texts"].get("target") or "") + "\n" + (policy["texts"].get("criteria") or ""),
    )
    text = gemini.generate_text(prompt, model=config.GEMINI_LITE_MODEL)
    if text:
        _tip_cache.set(key, text)
        return {"text": text, "generated": True}
    return {"text": fallback_tip(policy, profile, status, reasons, check_items), "generated": False}


def get_summary(policy_id, profile=None):
    policy = data_loader.get_policy(policy_id)
    if policy is None:
        return None

    stored = data_loader.load_policy_summaries().get(policy_id)
    # 원문이 바뀐 뒤 요약을 다시 만들지 않았으면 원문 발췌를 쓴다
    if stored and stored.get("source_updated_at") == policy["source"]["updated_at"]:
        items = {k: stored[k] for k in ITEM_TITLES}
        generated = True
    else:
        items = fallback_summary(policy)
        generated = False

    status = tip = None
    if profile is not None:
        e = evaluate(policy, profile)
        status = e.status
        tip = make_tip(policy, profile, items, e.status, e.reasons, e.check_items)

    docs = household_documents(policy, profile)
    sources = [policy["source"]]
    if docs:
        sources.append({"name": CHILDCARE_DOCS_SOURCE})

    return {
        "policy_id": policy["id"],
        "name": policy["name"],
        "agency": policy["agency"],
        "status": status,
        "summary": [
            {"title": ITEM_TITLES[k], "text": items[k]["text"], "evidence": items[k]["evidence"]}
            for k in ITEM_TITLES
        ],
        "summary_generated": generated,
        "household_documents": docs,
        "tip": tip,
        "apply": {
            "how_to_apply": policy["texts"].get("how_to_apply"),
            **policy["apply"],
        },
        "sources": sources,
        "info_date": policy["source"].get("updated_at"),
    }
