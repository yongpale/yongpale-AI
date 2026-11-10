"""요청·응답 형식

Profile은 F-002 가구 프로필 초안이다. 백엔드와 필드가 확정되면 여기만 맞춘다.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Gu = Literal["처인구", "기흥구", "수지구"]
SpecialGroup = Literal["multicultural", "disability", "north_korean_defector", "veteran", "out_of_school"]
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class CareTime(BaseModel):
    """돌봄이 필요한 시간대 (예: 13:00~19:00)"""
    start: str = Field(..., pattern=TIME_PATTERN, examples=["13:00"])
    end: str = Field(..., pattern=TIME_PATTERN, examples=["19:00"])


class Profile(BaseModel):
    gu: Optional[Gu] = Field(None, description="거주 구")
    dong: Optional[str] = Field(None, description="거주 읍·면·동", examples=["구갈동"])
    grade: int = Field(..., ge=1, le=6, description="자녀 학년 (초1~초6)")
    dual_income: bool = Field(False, description="맞벌이")
    single_parent: bool = Field(False, description="한부모·조손")
    multi_child: bool = Field(False, description="다자녀")
    low_income: Optional[bool] = Field(
        None, description="기초생활수급·차상위 등 저소득 가구 여부. 모르면 null"
    )
    income_percent: Optional[int] = Field(
        None, ge=0, le=1000, description="기준 중위소득 대비 가구 소득(%). 모르면 null"
    )
    special: List[SpecialGroup] = Field(
        default_factory=list,
        description="해당하는 가구 특성: multicultural(다문화), disability(장애·특수교육), "
                    "north_korean_defector(북한이탈주민), veteran(국가보훈대상자), "
                    "out_of_school(미취학·학업중단 등 학교 밖 아동)",
    )
    care_time: Optional[CareTime] = Field(None, description="돌봄이 필요한 시간대 (평일)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "gu": "기흥구", "dong": "구갈동", "grade": 1,
                "dual_income": True, "single_parent": False, "multi_child": False,
                "low_income": None, "income_percent": None, "special": [],
                "care_time": {"start": "13:00", "end": "19:00"},
            }]
        }
    }


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
    notes: List[str] = Field(..., description="참고 사항 (판정에는 영향 없음)")
    apply_period: Optional[str]
    source: Source


class MatchResponse(BaseModel):
    total: int = Field(..., description="eligible + check 정책 수 (홈 화면 '총 N건')")
    eligible_count: int
    check_count: int
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
    period: str
    care_time: TimeRange
    school_end: Optional[str]
    gap: List[TimeRange] = Field(..., description="돌봄 공백 시간대")
    gap_minutes: int
    plans: List[CareGapPlan]
    related_policies: List[RelatedPolicy] = Field(..., description="남는 공백을 채울 수 있는 돌봄 정책")
    notes: List[str]
