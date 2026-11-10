"""요청·응답 형식

Profile은 F-002 가구 프로필 초안이다. 백엔드와 필드가 확정되면 여기만 맞춘다.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Gu = Literal["처인구", "기흥구", "수지구"]
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


# 백엔드 ChildGrade 라벨 → 학년 숫자 (유치는 0 이하라 초등 정책 판정에서 빠진다)
GRADE_LABELS = {"유치5세": -2, "유치6세": -1, "유치7세": 0,
                "초1": 1, "초2": 2, "초3": 3, "초4": 4, "초5": 5, "초6": 6}
GRADE_NAMES = {v: k for k, v in GRADE_LABELS.items()}
BACKEND_SITUATIONS = {"DUAL_INCOME": "dual_income", "SINGLE_PARENT": "single_parent", "MULTI_CHILD": "multi_child"}


class CareTime(BaseModel):
    """하교 후 돌봄이 필요한 시간 (예: 13:00~18:00)"""
    start: str = Field(..., pattern=TIME_PATTERN, examples=["13:00"])
    end: str = Field(..., pattern=TIME_PATTERN, examples=["18:00"])

    @field_validator("start", "end", mode="before")
    @classmethod
    def _drop_seconds(cls, v):
        # 백엔드 LocalTime 직렬화 "13:00:00" → "13:00"
        if isinstance(v, str) and len(v) == 8 and v.count(":") == 2:
            return v[:5]
        return v


class Child(BaseModel):
    nickname: Optional[str] = Field(None, max_length=30, description="자녀 닉네임")
    grade: int = Field(..., ge=-2, le=6, description='학년: 1~6 또는 백엔드 라벨 "초1"~"초6", "유치5세"~"유치7세"')

    @field_validator("grade", mode="before")
    @classmethod
    def _grade_label(cls, v):
        if isinstance(v, str) and v in GRADE_LABELS:
            return GRADE_LABELS[v]
        return v

    @property
    def is_elementary(self):
        return 1 <= self.grade <= 6

    @property
    def grade_name(self):
        return GRADE_NAMES[self.grade]

    @property
    def label(self):
        return self.nickname or self.grade_name


class Profile(BaseModel):
    """가족 정보 입력 화면(03-03)과 같은 항목. 소득·특수가구는 입력받지 않는다.

    백엔드 가구 정보 응답(HouseholdResponse) 형식도 그대로 받는다:
    region.guName/dongName, situations ["DUAL_INCOME", ...], children[].grade "초2", careNeedStartTime/EndTime
    """
    gu: Optional[Gu] = Field(None, description="거주 구")
    dong: Optional[str] = Field(None, description="거주 읍·면·동", examples=["구갈동"])
    dual_income: bool = Field(False, description="가정 상황: 맞벌이")
    single_parent: bool = Field(False, description="가정 상황: 한부모")
    multi_child: bool = Field(False, description="가정 상황: 다자녀")
    care_time: Optional[CareTime] = Field(None, description="하교 후 돌봄이 필요한 시간 (평일)")
    children: List[Child] = Field(..., min_length=1, max_length=10, description="자녀 정보 (1명 이상)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "gu": "기흥구", "dong": "구갈동",
                "dual_income": True, "single_parent": False, "multi_child": False,
                "care_time": {"start": "13:00", "end": "18:00"},
                "children": [{"nickname": "첫째", "grade": 1}],
            }]
        }
    }

    @model_validator(mode="before")
    @classmethod
    def _from_backend(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        region = data.pop("region", None)
        if isinstance(region, dict):
            data.setdefault("gu", region.get("guName"))
            data.setdefault("dong", region.get("dongName"))
        situations = data.pop("situations", None)
        if situations is not None:
            for s in situations:
                if s in BACKEND_SITUATIONS:
                    data.setdefault(BACKEND_SITUATIONS[s], True)
        start, end = data.pop("careNeedStartTime", None), data.pop("careNeedEndTime", None)
        if start and end and not data.get("care_time"):
            data["care_time"] = {"start": start, "end": end}
        data.pop("id", None)
        return data

    @property
    def elementary_children(self):
        return [c for c in self.children if c.is_elementary]

    @property
    def youngest_elementary(self):
        kids = self.elementary_children
        return min(kids, key=lambda c: c.grade) if kids else None


class Source(BaseModel):
    name: str
    url: Optional[str] = None
    updated_at: Optional[str] = Field(None, description="원본 수정일")
    fetched_at: Optional[str] = Field(None, description="수집일")


# ---------------------------------------------------------------------------
# F-003 정책 추천
# ---------------------------------------------------------------------------

Status = Literal["eligible", "check", "ineligible"]


class MatchRequest(BaseModel):
    profile: Profile
    include_ineligible: bool = Field(False, description="해당하지 않는 정책도 함께 받기")
    limit: Optional[int] = Field(None, ge=1, le=100)


class PolicyMatch(BaseModel):
    id: str
    name: str
    agency: Optional[str]
    region: str = Field(..., description="yongin / gyeonggi / national")
    category: Optional[str]
    summary: Optional[str]
    status: Status = Field(..., description="eligible(해당 가능) / check(조건 확인 필요) / ineligible(해당 안 됨)")
    score: int = Field(..., ge=0, le=100, description="적합도 점수")
    reasons: List[str] = Field(..., description="점수·판단 근거")
    check_items: List[str] = Field(..., description="신청 전 직접 확인해야 하는 조건")
    labels: List[str] = Field(..., description="화면 표시용 라벨 (예: 소득 조건 확인 필요, 다문화가족 대상)")
    condition_types: List[Literal["income", "special_group", "other"]] = Field(
        ..., description="확인 필요 조건 종류: 소득 / 특정 가구(다문화·장애 등) / 그 밖의 조건"
    )
    target_children: List[str] = Field(..., description="대상 학년에 해당하는 자녀 (닉네임 또는 초N)")
    notes: List[str] = Field(..., description="참고 사항 (판정에는 영향 없음)")
    apply_period: Optional[str]
    source: Source


class MatchResponse(BaseModel):
    total: int = Field(..., description="eligible + check 정책 수 (홈 화면 '총 N건')")
    eligible_count: int
    check_count: int
    special_group_count: int = Field(..., description="다문화·장애 등 특정 가구 대상이라 확인이 필요한 정책 수")
    total_without_special: int = Field(..., description="특정 가구 대상 정책을 뺀 수 (홈 화면 숫자로 쓸 수 있음)")
    policies: List[PolicyMatch]


# ---------------------------------------------------------------------------
# F-004 정책 요약
# ---------------------------------------------------------------------------

SummaryKey = Literal["eligibility", "benefits", "documents", "period"]


class SummaryItem(BaseModel):
    title: str = Field(..., description="신청 자격 / 지원 혜택 / 필요 서류 / 신청 기간")
    text: str
    evidence: List[str] = Field(..., description="근거가 된 원문 항목 이름 (지원대상, 선정기준 등)")


class HouseholdDocument(BaseModel):
    household_type: Optional[str]
    detail_type: Optional[str]
    documents: Optional[str]
    how_to_get: Optional[str]


class Tip(BaseModel):
    text: str
    generated: bool = Field(..., description="true = Gemini 생성, false = 규칙 기반 대체 문구")


class SummaryRequest(BaseModel):
    profile: Optional[Profile] = None


class SummaryLookupRequest(BaseModel):
    """정책 ID 대신 백엔드가 가진 값으로 찾기: policy_id, source_url, title 중 하나"""
    policy_id: Optional[str] = Field(None, description="정부24 서비스ID")
    source_url: Optional[str] = Field(None, description="백엔드 policies.source_url (svcId 포함)")
    title: Optional[str] = Field(None, description="백엔드 policies.title")
    profile: Optional[Profile] = None

    @model_validator(mode="after")
    def _need_one(self):
        if not (self.policy_id or self.source_url or self.title):
            raise ValueError("policy_id, source_url, title 중 하나는 있어야 합니다")
        return self


class SummaryResponse(BaseModel):
    policy_id: str
    name: str
    agency: Optional[str]
    status: Optional[Status] = Field(None, description="프로필이 있을 때만: 해당 가능 배지")
    summary: List[SummaryItem] = Field(..., description="4대 핵심 정보 (자격, 혜택, 서류, 기간 순)")
    summary_generated: bool = Field(..., description="false면 원문 발췌로 만든 대체 요약")
    household_documents: List[HouseholdDocument] = Field(
        default_factory=list, description="가정 유형별 입증서류 (아이돌봄 서비스만)"
    )
    tip: Optional[Tip] = Field(None, description="가구 맞춤 팁 (프로필이 있을 때만)")
    apply: dict = Field(..., description="신청 방법·접수기관·문의처·온라인 신청 URL")
    sources: List[Source]
    info_date: Optional[str] = Field(None, description="정보 기준일 (원본 수정일)")


# ---------------------------------------------------------------------------
# F-009 돌봄 공백 분석
# ---------------------------------------------------------------------------

class CareGapRequest(BaseModel):
    profile: Profile
    child_index: Optional[int] = Field(
        None, ge=0, description="분석할 자녀 (children 순서, 0부터). 없으면 학년이 가장 낮은 초등학생 자녀"
    )
    period: Literal["semester", "vacation"] = Field("semester", description="학기 중 / 방학 중")
    school_end: Optional[str] = Field(
        None, pattern=TIME_PATTERN, description="하교 시간 (학기 중). 없으면 학년별 기본값"
    )
    care_time: Optional[CareTime] = Field(None, description="없으면 profile.care_time 사용")
    max_results: int = Field(3, ge=1, le=10)


class TimeRange(BaseModel):
    start: str
    end: str
    minutes: int


class FacilityBrief(BaseModel):
    id: str
    name: str
    type: str
    gu: Optional[str]
    dong: Optional[str]
    address: Optional[str]
    phone: Optional[str]
    hours: Optional[TimeRange] = Field(None, description="해당 기간 운영시간. null = 정보 없음")
    covers: Optional[TimeRange] = Field(None, description="이 시설이 맡는 시간")
    fee: dict
    meal: Optional[bool]
    snack: Optional[bool]
    pickup: Optional[bool]
    application_info: Optional[str] = Field(None, description="시설 신청 안내 원문")
    source: str
    verified_at: Optional[str]


class CareGapPlan(BaseModel):
    facilities: List[FacilityBrief]
    covered_minutes: int
    coverage_rate: float = Field(..., description="공백 시간 중 채워지는 비율 (0~1)")
    remaining: List[TimeRange] = Field(..., description="이 조합으로도 남는 공백")
    reasons: List[str]


class RelatedPolicy(BaseModel):
    id: str
    name: str
    status: Status
    reason: str


class CareGapResponse(BaseModel):
    child: str = Field(..., description="분석한 자녀 (닉네임 또는 초N)")
    period: str
    care_time: TimeRange
    school_end: Optional[str]
    gap: List[TimeRange] = Field(..., description="돌봄 공백 시간대")
    gap_minutes: int
    plans: List[CareGapPlan]
    related_policies: List[RelatedPolicy] = Field(..., description="남는 공백을 채울 수 있는 돌봄 정책")
    notes: List[str]


# ---------------------------------------------------------------------------
# AI 돌봄·배움 챗봇
# ---------------------------------------------------------------------------

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(..., max_length=2000)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, examples=["아이돌봄 서비스는 어디서 신청하고 서류는 뭐가 필요해요?"])
    profile: Optional[Profile] = None
    history: List[ChatTurn] = Field(default_factory=list, description="이전 대화 (최근 4턴만 사용)")
    user_name: Optional[str] = Field(None, max_length=20, description="답변에서 부를 이름 (예: 김용인)")


class ChatItem(BaseModel):
    title: str = Field(..., description="번호 목록 제목 (예: 신청처, 제출 서류, 접수 기간)")
    text: str


class ChatSource(BaseModel):
    type: Literal["policy", "facility"]
    id: str
    title: str = Field(..., description="정책명 또는 시설명")
    name: Optional[str] = Field(None, description="출처 기관·데이터 이름")
    url: Optional[str] = None
    updated_at: Optional[str] = Field(None, description="정보 기준일")


class ChatPolicyLink(BaseModel):
    id: str
    name: str
    status: Optional[Status] = Field(None, description="프로필이 있을 때 판정")


class ChatFacilityLink(BaseModel):
    id: str
    name: str


class ChatResponse(BaseModel):
    answer_id: str = Field(..., description="답변 ID (도움됨/아님 피드백 저장용)")
    model: Optional[str] = Field(None, description="답변을 만든 모델 (Gemini를 쓰지 않았으면 null)")
    profile_label: Optional[str] = Field(None, description="'초1 · 기흥구 구갈동 · 맞벌이'")
    grounded: bool = Field(..., description="false면 '근거 없음' 배지")
    generated: bool = Field(..., description="false면 Gemini 없이 만든 답변 (근거 없음 또는 자료 목록)")
    intro: str
    items: List[ChatItem] = Field(..., description="번호 목록 (없으면 빈 배열)")
    sources: List[ChatSource] = Field(..., description="근거 출처")
    related_policies: List[ChatPolicyLink] = Field(..., description="관련 정책 바로가기")
    related_facilities: List[ChatFacilityLink]
    suggested_questions: List[str] = Field(..., description="추천 질문")
