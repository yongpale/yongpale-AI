"""AI 돌봄·배움 챗봇: 정책·시설 문서를 검색해서(RAG) 근거가 있을 때만 답한다.

- 답변 근거는 검색된 문서뿐이다. 근거가 없으면 '근거 없음'으로 답하고 사실처럼 말하지 않는다.
- 답변에 쓴 문서로 출처와 '관련 정책 바로가기'를 만든다.
- Gemini가 실패하면 검색된 자료 목록으로 대신 답한다.
"""

import json
import uuid
from typing import List

from pydantic import BaseModel

from app import config, data_loader
from app.services import documents, gemini, retrieval
from app.services.matching import HOUSEHOLD_FLAGS, evaluate
from app.services.regions import same_dong

TOP_K = 6
HISTORY_TURNS = 4
# 키워드 검색일 때 이 점수보다 낮으면 관련 문서가 없다고 본다
KEYWORD_MIN_SCORE = 0.2
NO_GROUND_INTRO = (
    "확인되지 않은 정보예요.\n"
    "등록된 정책·시설 자료에서 근거를 찾지 못했어요.\n"
    "확인되지 않은 내용은 사실처럼 답하지 않아요."
)
DEFAULT_SUGGESTIONS = ["우리 아이가 받을 수 있는 지원은?", "근처 돌봄센터 알려줘"]
POLICY_SUGGESTIONS = ["신청 기간 알려줘", "서류 발급처는?", "지원 금액은 얼마야?"]
FACILITY_SUGGESTIONS = ["운영시간 알려줘", "이용료는 얼마야?", "급식도 나와?"]

_answer_cache = gemini.FileCache("chat_answers.json")


class AnswerItem(BaseModel):
    title: str
    text: str


class GeneratedAnswer(BaseModel):
    grounded: bool
    intro: str
    items: List[AnswerItem]
    used_doc_ids: List[str]


PROMPT = """너는 용인시 초등학생 자녀를 둔 부모를 돕는 '아이케어 AI' 상담 챗봇이다.
아래 [자료]만 근거로 [질문]에 답해라.

규칙
- [자료]에 없는 내용(금액, 기간, 서류, 기관, 자격)은 절대 만들지 마라.
- [자료]에서 질문에 대한 근거를 찾을 수 없으면 grounded=false로 하고 intro, items는 비워라.
  질문이 틀린 전제를 담고 있어도(예: 자료에 없는 수당) grounded=false로 해라.
- 시설 자료의 '정보 없음'은 운영하지 않는다는 뜻이 아니다. "정보가 없어 시설에 확인이 필요해요"라고 답해라.
- 이 서비스는 가구 소득과 다문화·장애 등 특정 가구 여부를 입력받지 않는다.
- 정책 자료의 [이 가구 판정]을 반영해라.
  '조건 확인 필요'인 정책은 "신청할 수 있다"고 단정하지 말고, 그 정책 설명에 확인할 조건(소득 기준 등)을 함께 써라.
  '해당 안 됨'인 정책은 이 가구가 대상이 아니라고 알려줘라.
- intro: 1~2문장 요약 답변. {name_rule}
- items: 신청처, 제출 서류, 접수 기간, 운영시간처럼 단계나 항목으로 나눌 수 있으면 2~4개로 나눠라. title은 짧은 명사, text는 1~2문장.
- 존댓말("~해요", "~하세요")로 쉽게 써라.
- used_doc_ids: 답변에 실제로 근거로 쓴 자료의 id만 넣어라.

[가구 정보] {profile}
[이전 대화]
{history}
[자료]
{docs}
[질문] {question}
"""


def profile_label(profile):
    """'초1 · 기흥구 구갈동 · 맞벌이'"""
    if profile is None:
        return None
    parts = ["·".join(c.grade_name for c in profile.children)]
    if profile.gu:
        parts.append(" ".join(x for x in (profile.gu, profile.dong) if x))
    parts += [label for field, label in HOUSEHOLD_FLAGS if getattr(profile, field)]
    return " · ".join(parts)


def _rerank(results, profile):
    """프로필 기준으로 순위 조정: 같은 동·구 시설은 올리고, 해당하지 않는 정책은 내린다"""
    if profile is None:
        return results
    adjusted = []
    for doc, score in results:
        if doc["type"] == "facility":
            f = next((x for x in data_loader.load_facilities() if x["id"] == doc["ref_id"]), None)
            if f and profile.dong and same_dong(f.get("dong"), profile.dong):
                score += 0.03
            elif f and profile.gu and f.get("gu") == profile.gu:
                score += 0.015
        else:
            policy = data_loader.get_policy(doc["ref_id"])
            if policy and evaluate(policy, profile).status == "ineligible":
                score -= 0.03
        adjusted.append((doc, score))
    adjusted.sort(key=lambda x: -x[1])
    return adjusted


STATUS_LABEL = {"eligible": "해당 가능", "check": "조건 확인 필요", "ineligible": "해당 안 됨"}


def _doc_for_prompt(doc, profile):
    """정책 문서에는 이 가구의 판정 결과를 붙인다"""
    text = doc["text"]
    if doc["type"] == "policy" and profile is not None:
        policy = data_loader.get_policy(doc["ref_id"])
        if policy:
            e = evaluate(policy, profile)
            detail = ", ".join((e.reasons if e.status == "ineligible" else e.check_items) or e.reasons)
            text = f"[이 가구 판정] {STATUS_LABEL[e.status]}" + (f" ({detail})" if detail else "") + "\n" + text
    return f"<자료 id={doc['id']}>\n{text}\n</자료>"


def _condition_reminder(used_docs, profile, generated):
    """답변이 확인 필요 조건을 빠뜨렸으면 규칙으로 덧붙인다 (해당 안 되는 정책을 신청 가능하다고 오해하지 않게)"""
    if profile is None:
        return None
    answer_text = generated.intro + " ".join(i.text for i in generated.items)
    missing = []
    for d in used_docs:
        if d["type"] != "policy":
            continue
        policy = data_loader.get_policy(d["ref_id"])
        e = evaluate(policy, profile)
        if e.status == "check" and e.check_items:
            condition = e.check_items[0]
            keyword = "소득" if "소득" in condition else condition[:6]
            if keyword not in answer_text:
                missing.append(f"{policy['name']}: {condition}")
    if not missing:
        return None
    return {"title": "확인할 조건", "text": " / ".join(missing)}


def _search_query(question, history):
    """'신청 기간 알려줘' 같은 이어지는 질문은 직전 사용자 질문을 함께 검색한다"""
    previous = [h.text for h in history if h.role == "user"][-1:]
    return " ".join(previous + [question])


def _sources_and_links(docs, profile):
    sources, policies, facilities = [], [], []
    for d in docs:
        sources.append({
            "type": d["type"],
            "id": d["ref_id"],
            "title": d["title"],
            "name": d["source"]["name"],
            "url": d["source"]["url"],
            "updated_at": d["source"]["updated_at"],
        })
        if d["type"] == "policy":
            status = None
            if profile is not None:
                policy = data_loader.get_policy(d["ref_id"])
                status = evaluate(policy, profile).status if policy else None
            policies.append({"id": d["ref_id"], "name": d["title"], "status": status})
        else:
            facilities.append({"id": d["ref_id"], "name": d["title"]})
    return sources, policies, facilities


def _suggestions(docs, question=""):
    """추천 질문 2개 (방금 한 질문과 같은 것은 뺀다)"""
    if not docs:
        candidates = DEFAULT_SUGGESTIONS
    else:
        candidates = POLICY_SUGGESTIONS if docs[0]["type"] == "policy" else FACILITY_SUGGESTIONS
    asked = question.replace(" ", "").rstrip("?")
    return [q for q in candidates if q.replace(" ", "").rstrip("?") != asked][:2]


def _no_ground(answer_id, profile):
    return {
        "answer_id": answer_id,
        "profile_label": profile_label(profile),
        "grounded": False,
        "generated": False,
        "intro": NO_GROUND_INTRO,
        "items": [],
        "sources": [],
        "related_policies": [],
        "related_facilities": [],
        "suggested_questions": DEFAULT_SUGGESTIONS,
    }


def _fallback(answer_id, profile, docs, question):
    """Gemini 실패: 검색된 자료를 목록으로 보여준다"""
    summaries = data_loader.load_policy_summaries()
    items = []
    for d in docs[:3]:
        if d["type"] == "policy":
            s = summaries.get(d["ref_id"])
            text = s["eligibility"]["text"] if s else (data_loader.get_policy(d["ref_id"]) or {}).get("summary") or ""
        else:
            text = next((line for line in d["text"].split("\n") if line.startswith("주소")), "")
        items.append({"title": d["title"], "text": text})
    sources, policies, facilities = _sources_and_links(docs[:3], profile)
    return {
        "answer_id": answer_id,
        "profile_label": profile_label(profile),
        "grounded": True,
        "generated": False,
        "intro": "지금은 답변을 만들 수 없어서 질문과 관련된 자료를 대신 보여드려요.",
        "items": items,
        "sources": sources,
        "related_policies": policies,
        "related_facilities": facilities,
        "suggested_questions": _suggestions(docs, question),
    }


def answer(question, profile=None, history=None, user_name=None):
    history = (history or [])[-HISTORY_TURNS * 2:]
    answer_id = uuid.uuid4().hex

    results, method = retrieval.search(_search_query(question, history), top_k=TOP_K)
    if method == "keyword":
        results = [(d, s) for d, s in results if s >= KEYWORD_MIN_SCORE]
    results = _rerank(results, profile)
    docs = [d for d, _ in results]
    if not docs:
        return _no_ground(answer_id, profile)

    cache_key = _answer_cache.key(
        documents.text_hash(PROMPT), question.strip(), [h.model_dump() for h in history],
        profile.model_dump() if profile else None, user_name, [d["id"] for d in docs],
    )
    cached = _answer_cache.get(cache_key)
    if cached:
        generated = GeneratedAnswer.model_validate(cached)
    else:
        prompt = PROMPT.format(
            name_rule=f'"{user_name} 님"으로 부를 수 있다.' if user_name else "",
            profile=profile_label(profile) or "정보 없음",
            history="\n".join(f"{'사용자' if h.role == 'user' else 'AI'}: {h.text}" for h in history) or "없음",
            docs="\n\n".join(_doc_for_prompt(d, profile) for d in docs),
            question=question,
        )
        generated = gemini.generate_json(prompt, GeneratedAnswer, model=config.GEMINI_LITE_MODEL)
        if generated is None:
            return _fallback(answer_id, profile, docs, question)
        _answer_cache.set(cache_key, json.loads(generated.model_dump_json()))

    by_id = {d["id"]: d for d in docs}
    used = [by_id[i] for i in dict.fromkeys(generated.used_doc_ids) if i in by_id]
    # 근거 문서 없이 답했다고 하면 근거 없음으로 처리
    if not generated.grounded or not used:
        return _no_ground(answer_id, profile)

    sources, policies, facilities = _sources_and_links(used, profile)
    items = [i.model_dump() for i in generated.items]
    reminder = _condition_reminder(used, profile, generated)
    if reminder:
        items.append(reminder)
    return {
        "answer_id": answer_id,
        "model": config.GEMINI_LITE_MODEL,
        "profile_label": profile_label(profile),
        "grounded": True,
        "generated": True,
        "intro": generated.intro,
        "items": items,
        "sources": sources,
        "related_policies": policies,
        "related_facilities": facilities,
        "suggested_questions": _suggestions(used, question),
    }
