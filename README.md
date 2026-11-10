# 아이케어 용인 AI 서버

용인시 아동 돌봄·배움 매칭 플랫폼 '아이케어 용인'의 AI 파트입니다.
백엔드가 HTTP로 호출하는 FastAPI 서버입니다.

| 기능 | 엔드포인트 | Gemini 사용 |
|---|---|---|
| F-003 맞춤형 정책 추천 | `POST /ai/policies/match` | 사용 안 함 (규칙 기반) |
| F-004 정책 요약·맞춤 팁 | `POST /ai/policies/{policy_id}/summary` | 4항목 요약은 미리 생성, 맞춤 팁만 실시간 |
| F-009 돌봄 공백 분석 | `POST /ai/care-gap` | 사용 안 함 (규칙 기반) |
| AI 돌봄·배움 챗봇 | `POST /ai/chat` | 질문마다 검색 임베딩 1회 + 답변 생성 1회 |
| 상태 확인 | `GET /health` | |

## 실행

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 값 채우기
uvicorn app.main:app --reload
```

- API 문서(요청·응답 예시, 직접 호출해 보기): http://localhost:8000/docs
- 테스트: `python3 -m pytest` (Gemini를 호출하지 않음)

## 구조

```
app/
  main.py               엔드포인트
  schemas.py            요청·응답 형식 (Profile = F-002 가구 프로필 초안)
  data_loader.py        데이터 읽기 (백엔드 데이터 형식이 정해지면 이 파일만 수정)
  config.py             .env 설정
  services/
    matching.py         F-003 판정·적합도 점수
    summary.py          F-004 요약·입증서류·맞춤 팁
    care_gap.py         F-009 공백 계산·시설 조합
    chat.py             챗봇 답변 (검색 → 근거 있을 때만 답변)
    retrieval.py        정책·시설 문서 검색 (임베딩, 실패 시 키워드)
    documents.py        검색용 문서 만들기 (정책 1건 = 문서 1개, 시설 1곳 = 문서 1개)
    gemini.py           Gemini 호출, 실패 시 None, 결과 파일 캐시
scripts/                데이터 수집·전처리 (data/README.md 참고)
data/processed/         서버가 읽는 데이터
tests/
```

## 가구 프로필 (F-002 초안)

```json
{
  "gu": "기흥구", "dong": "구갈동", "grade": 1,
  "dual_income": true, "single_parent": false, "multi_child": false,
  "low_income": null, "income_percent": null,
  "special": [],
  "care_time": {"start": "13:00", "end": "19:00"}
}
```

| 필드 | 설명 |
|---|---|
| gu, dong | 처인구 / 기흥구 / 수지구, 읍·면·동 |
| grade | 자녀 학년 1~6 |
| dual_income, single_parent, multi_child | 맞벌이, 한부모·조손, 다자녀 |
| low_income | 기초생활수급·차상위 등 저소득 여부. 모르면 null |
| income_percent | 기준 중위소득 대비 소득(%). 모르면 null |
| special | multicultural(다문화), disability(장애·특수교육), north_korean_defector(북한이탈주민), veteran(국가보훈대상자), out_of_school(학교 밖 아동) |
| care_time | 평일 돌봄이 필요한 시간대 |

프로필에서 모르는 값(null)은 "조건 확인 필요"로 판정하고, 틀린 값으로 가정하지 않습니다.

## F-003 정책 추천

`POST /ai/policies/match`  `{"profile": {...}, "include_ineligible": false, "limit": null}`

- `status`: `eligible`(해당 가능 배지) / `check`(조건 확인 필요) / `ineligible`(해당 안 됨, 기본은 응답에서 제외)
- `score`: 적합도 0~100. 판정 기본점(해당 가능 60, 확인 필요 40) + 가구 조건 일치(필수 +15, 우대 +10, 특정 가구 +15) + 지역(용인 +10, 경기 +5) + 돌봄 시간이 필요한 가구의 돌봄·방과후 정책 +10
- `reasons`: 점수 근거, `check_items`: 신청 전 확인할 조건, `notes`: 참고 사항
- `total`: 홈 화면 "총 N건의 지원 정책" (eligible + check)

## F-004 정책 요약

`POST /ai/policies/{policy_id}/summary`  `{"profile": {...}}` (profile은 선택)

- `summary`: 신청 자격 / 지원 혜택 / 필요 서류 / 신청 기간. `evidence`는 근거가 된 원문 항목
  - `scripts/generate_policy_summaries.py`로 미리 만든 `data/processed/policy_summaries.json`을 사용
  - 요약이 없거나 원문이 바뀐 정책은 원문 발췌로 대신하고 `summary_generated: false`
- `tip`: 가구 맞춤 팁 (profile이 있을 때). `generated: false`면 Gemini 실패로 규칙 기반 문구
  - 같은 정책·같은 프로필 조건은 `data/cache/tips.json`에 저장해 다시 호출하지 않음
- `household_documents`: 아이돌봄 서비스의 가정 유형별 입증서류
- `sources`, `info_date`: 출처와 정보 기준일 (화면 표시용)

## F-009 돌봄 공백 분석

`POST /ai/care-gap`  `{"profile": {...}, "period": "semester", "school_end": null, "care_time": null}`

- 공백 = 돌봄 필요 시간(care_time) - 학교에 있는 시간. 방학(`vacation`)은 필요 시간 전체
- 하교 시간을 안 주면 학년별 기본값(초1·2 13:00, 초3·4 14:30, 초5·6 15:00)
- `plans`: 한 곳 또는 두 곳을 이어서 이용하는 시설 조합. 남는 공백이 적은 순, 가까운 순(같은 동 > 같은 구), 이용료 순
- `related_policies`: 시설로 못 채우는 공백에 이용할 수 있는 돌봄 서비스 (아이돌봄 서비스 등)
- 시설 좌표가 아직 없어서 거리는 동·구 일치로만 판단합니다. 운영시간이 비어 있는 시설은 추천에서 뺍니다.

## AI 돌봄·배움 챗봇

`POST /ai/chat`

```json
{
  "question": "아이돌봄 서비스는 어디서 신청하고 서류는 뭐가 필요해요?",
  "profile": {"gu": "기흥구", "dong": "구갈동", "grade": 1, "dual_income": true},
  "history": [{"role": "user", "text": "..."}, {"role": "assistant", "text": "..."}],
  "user_name": "김용인"
}
```

| 응답 필드 | 화면 |
|---|---|
| `profile_label` | 상단 "가구 프로필 적용 중" (초1 · 기흥구 구갈동 · 맞벌이) |
| `intro`, `items` | 답변 첫 문장과 번호 목록 (신청처, 제출 서류, 접수 기간 등) |
| `sources` | 근거 출처 카드 (정책·시설명, 출처, 기준일, 링크) |
| `related_policies` | 관련 정책 바로가기 (정책 id → 정책 상세 화면) |
| `grounded` | false면 "근거 없음" 배지. 자료에 없는 내용은 답하지 않음 |
| `answer_id` | 도움됨/아님 피드백 저장용 ID (저장은 백엔드) |
| `suggested_questions` | 추천 질문 칩 |

- 정책 36건 + 시설 60곳을 검색해서 상위 6개 문서만 근거로 답합니다. 프로필의 동·구 시설과 해당 가능한 정책을 우선합니다.
- 프로필 판정이 "조건 확인 필요"인 정책은 확인할 조건(소득 기준 등)을 답변에 함께 넣습니다.
- 시설 정보의 빈 값은 "정보 없음"으로 답합니다 (예: 토요일 운영시간이 없으면 "미운영"이 아니라 "확인 필요").
- `history`는 이전 대화로, "신청 기간 알려줘" 같은 이어지는 질문에 씁니다 (최근 4턴).
- Gemini가 실패하면 검색된 자료 목록으로 답합니다 (`generated: false`).
- 데이터를 바꾸면 `python3 scripts/build_embeddings.py`로 검색 임베딩을 다시 만듭니다 (바뀐 문서만).

## Gemini 무료 한도

- `gemini-3.5-flash`는 하루 20회라 요약 미리 만들기에만 씁니다.
- 서버는 `GEMINI_LITE_MODEL`(기본 `gemini-3.5-flash-lite`)로 맞춤 팁과 챗봇 답변을 만들고, 실패하면 대체 응답을 보냅니다.
- 같은 질문·같은 프로필의 답변과 팁은 `data/cache/`에 저장해 다시 호출하지 않습니다.
- 임베딩(`gemini-embedding-001`)은 무료 등급에서 분당 3만 토큰 한도가 있어 스크립트가 나눠서 보냅니다.
- `GEMINI_ENABLED=0`이면 Gemini를 호출하지 않습니다.
