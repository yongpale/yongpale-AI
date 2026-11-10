# 돌봄시설 데이터

## 원본
| 파일 | 내용 | 출처 | 확인일 |
|---|---|---|---|
| raw/yongin_dahamkke_centers.xlsx | 용인시 다함께돌봄센터 26곳 | 경기도 아동언제나돌봄 우리동네 돌봄자원 찾기 | 2026-10-29 |
| raw/yongin_jiyeok_child_centers.xlsx | 용인시 지역아동센터 34곳 | 경기도 아동언제나돌봄 우리동네 돌봄자원 찾기 | 2026-10-29 |

## 가공 방법
```bash
pip install pandas openpyxl
python scripts/preprocess_facilities.py
```
결과는 `processed/facilities.json`(중첩 구조), `processed/facilities.csv`(DB 적재용 평면 구조)로 저장됩니다.

## 컬럼 설명 (facilities.csv)
| 컬럼 | 타입 | 설명 | 예시 |
|---|---|---|---|
| id | string | 시설 ID | YI00250032 |
| name | string | 센터명 | 용인시 다함께돌봄센터 2호점 |
| type | string | 다함께돌봄센터 / 지역아동센터 | 다함께돌봄센터 |
| gu | string | 구 | 기흥구 |
| dong | string, null | 주소에서 추출한 읍·면·동 (도로명만 있으면 null) | 구갈동 |
| address | string | 주소 원문 | |
| phone | string | 연락처 | 031-281-2513 |
| lat, lng | float, null | 좌표 (아직 비어 있음, 지오코딩 필요) | |
| age_min, age_max | int, null | 이용 가능 연령 | 6, 12 |
| all_ages | bool | 연령 제한 없음 | false |
| semester_open/close | "HH:MM", null | 학기 중 운영시간 (다함께돌봄은 정기돌봄 기준) | 10:00 / 19:00 |
| vacation_open/close | "HH:MM", null | 방학 중 운영시간 | 09:00 / 19:00 |
| saturday_open/close | "HH:MM", null | 토요일 운영시간 (null이면 미운영 또는 정보 없음) | |
| temp_semester_open/close | "HH:MM", null | 일시돌봄 학기 중 (다함께돌봄센터만) | |
| temp_vacation_open/close | "HH:MM", null | 일시돌봄 방학 중 (다함께돌봄센터만) | |
| fee_type | string | free / paid / unknown | free |
| fee_unit | string, null | day / month | |
| fee_amount | int, null | 이용료(원) | 2200 |
| meal, snack, pickup | bool, null | 급식 / 간식 / 등하원 지원. true = 제공, null = 정보 없음 (원본에 '미제공' 표기가 없어 false는 없음) | true |
| capacity | int, null | 정원 (다함께돌봄은 정기돌봄 정원) | 44 |
| temp_capacity | int, null | 일시돌봄 정원 | 2 |
| programs | string | 프로그램 원문, " / "로 구분 | |
| application_info | string, null | 신청 안내 원문 | |
| source | string | 출처 | |
| verified_at | date | 원본 확인일 | 2026-10-29 |

## 참고
- 시간은 "HH:MM" 문자열이라 문자열 비교로도 대소 비교가 됩니다. ("09:00" < "13:00")
- 현원 정보는 원본에 없습니다.
- programs, application_info는 챗봇·요약 기능에서 사용하므로 삭제하지 말아 주세요.
- 다함께돌봄센터 21호점은 원본에 운영시간·이용료·프로그램이 모두 비어 있습니다.
- 다함께돌봄센터 원본에는 토요일 운영시간, 등하원 지원 항목이 없어 항상 null입니다.
- dong은 주소에 적힌 읍·면·동을 그대로 사용합니다. 주소에 동 이름이 없고 행정복지센터 이름에만 있는 경우(보정동)는 그 이름을 씁니다.

---

# 정책 데이터

## 원본
| 파일 | 내용 | 출처 |
|---|---|---|
| raw/gov24_service_list.json | 공공서비스 전체 목록 (10,942건) | 행정안전부 대한민국 공공서비스(혜택) 정보 |
| raw/gov24_child_details.json | 아동·돌봄 관련 서비스 상세 | 〃 |
| raw/gov24_child_conditions.json | 아동·돌봄 관련 서비스 지원조건 (JA 코드) | 〃 |
| raw/childcare_documents.json | 아이돌봄 정부지원 입증서류 (28건) | 한국건강가정진흥원 아이돌봄 정부지원 자격여부 입증서류 및 확인방법 정보 |

## 수집·가공 방법
```bash
python3 scripts/fetch_public_data.py         # 원본 수집 (API 호출, 일일 한도 주의)
python3 scripts/preprocess_policies.py       # 후보 선정 (API 호출 없음)
```

## 후보 선정 단계 (preprocess_policies.py)
1. 아동·돌봄 키워드 포함 (서비스명, 목적, 지원대상, 분야)
2. 용인시 주민 이용 가능: 중앙행정기관·공공기관, 경기도, 경기도교육청, 용인시, 경기도 산하 기관
3. 개인·가구 대상 (법인·시설·소상공인 전용 제외)
4. 초등 자녀 가구 가능성: 대상 연령이 6~12세와 겹침, 학생 구분이 있으면 초등학생 포함, 서비스분야, 제외 키워드(노인, 대학, 고교, 출산 등)

규칙만으로는 관계없는 서비스(견학 프로그램, 발전소 주변지역 장학금 등)가 남아 있어서, 다음 단계에서 한 번 더 거르고 사람이 검토한 뒤 `processed/policies.json`으로 확정합니다.

## 필드 설명 (processed/policy_candidates.json)
| 필드 | 설명 |
|---|---|
| id | 서비스ID |
| name, agency, agency_type, department | 서비스명, 소관기관명, 소관기관유형, 부서명 |
| region | yongin / gyeonggi / national |
| category, support_type, user_type | 서비스분야, 지원유형, 사용자구분 |
| summary | 서비스목적요약 |
| texts | 원문: purpose(목적), target(지원대상), criteria(선정기준), benefits(지원내용), how_to_apply(신청방법), documents(구비서류), documents_self_check(본인확인 필요 서류), documents_official_check(공무원 확인 서류) |
| apply | deadline_type, deadline, reception(접수기관), contact(문의처), online_url |
| laws | 근거 법령·자치법규·행정규칙 |
| conditions | 지원조건 코드 해석 결과 (아래) |
| source | name, url(정부24 상세 페이지), updated_at(원본 수정일), fetched_at(수집일) |
| household_documents | 아이돌봄 서비스에만 있음. 가정 유형별 입증서류는 `processed/childcare_documents.json` 참고 |

### conditions
| 필드 | 설명 |
|---|---|
| age_min, age_max | 대상 연령. null은 제한 없음 |
| gender | 한쪽 성별만 대상일 때만 값이 있음 |
| income | 대상 중위소득 구간 목록. null은 제한 없음 |
| personal | 개인 특성 (초등학생, 장애인, 근로자 등). `allowed` = 대상 특성, `none_ok` = 해당 사항이 없어도 대상 |
| household | 가구 특성 (한부모, 다자녀, 다문화 등). 구조는 personal과 같음 |

- 원본 코드의 Y는 "이 대상을 제외하지 않는다"는 뜻이라 우대 조건이 아닙니다.
- 맞벌이 여부는 코드에 없어서 원문(target, criteria)에서 추출해야 합니다.
- 상세 정보가 없는 서비스는 목록 API 값으로 채워서 documents 등이 null일 수 있습니다.

## 참고
- 입증서류 데이터의 기준연도(base_year)는 2020년입니다. 화면에 기준일을 함께 표시해 주세요.
- 원본 텍스트는 요약·챗봇 근거로 쓰므로 수정하지 말아 주세요.

## 조건 추출·검토 (extract_policy_conditions.py → build_policies.py)
```bash
python3 scripts/extract_policy_conditions.py   # Gemini로 후보별 매칭 조건 추출 → review/policy_review.csv
python3 scripts/build_policies.py              # 검토한 policy_review.csv 의 include=Y 만 policies.json 으로
```
추출 캐시(`interim/`)와 검토 표(`review/`)는 작업용이라 저장소에 올리지 않습니다. 개발에는 `processed/policies.json`만 사용하면 됩니다.

## 검토 결과 (2026-11-08, 후보 170건 → 36건)
- 기준: 용인시에 사는 초등 자녀 가구가 직접 신청·이용할 수 있는 **돌봄·방과후·교육비** 정책
- 제외
  - 기관·시설 운영 지원 (예: 청소년복지시설 운영 지원, 정신건강복지센터 운영 지원)
  - 성인·특정 집단 전용 (예: 국가보훈대상자 주택우선공급, 군인 재해보상 유족급여, 누구나 돌봄)
  - 견학·체험관 등 단발성 프로그램 (예: 한국잡월드 입장료, 어린이 교통안전체험관)
  - 학교 단위로 선정되는 사업 (예: 교육복지우선지원, 초등학생 승강기 안전교육)
  - 용인시가 참여하지 않는 사업 (예: 다자녀가정 아이돌봄 본인부담금, 14개 시·군만 참여)
  - 신청이 필요 없는 보편 지원 (예: 학교급식경비 지원)
- 범위 밖이라 제외했지만 초등 자녀 가구와 관련 있는 정책: 경기도 어린이청소년 교통비 지원, 아동수당, 12세 이하 어린이 국가예방접종, 인플루엔자 국가예방접종, 아동 입원진료비 지원, 발달재활서비스 바우처, 언어발달지원, 위(Wee) 클래스 상담, 학교급식비 지원. 필요하면 추가할 수 있습니다.
- 추출 값을 직접 고친 것
  - 아이돌봄 서비스: notes에 "양육 공백 가정(맞벌이·한부모·장애부모·다자녀 등)이면 소득에 따라 정부 지원" 추가. 맞벌이·한부모·다자녀는 지원 사유 중 하나라 preferred 유지
  - 결식아동급식지원: category 건강·의료 → 돌봄
  - 스포츠 강좌 이용권 지원: category 교육비 → 방과후·학습
  - 탈북청소년 및 북한이탈주민 자녀 화상영어 지원: 학년 1~6 → 3~6 (만 9세 이상)
  - 장애인활동지원급여지원(경기도), 국가보훈대상자 보훈장학금 지원, 다문화가족 방문교육서비스: other_requirements를 원문에 맞게 정리

## 필드 설명 (processed/policies.json)
policy_candidates.json 필드에 `match`가 추가됩니다.

| 필드 | 설명 |
|---|---|
| match.category | 돌봄 / 방과후·학습 / 교육비 |
| match.grade_min, grade_max | 대상 초등 학년 (1~6) |
| match.dual_income, single_parent, multi_child | 맞벌이 / 한부모·조손 / 다자녀. `required` = 그 가구만 대상, `preferred` = 우선 선정·추가 지원 또는 지원 사유 중 하나, `not_mentioned` = 조건 없음 |
| match.low_income_only | 저소득 가구만 대상이면 true |
| match.income_limit | 소득 기준 문구 (원문 요약) |
| match.other_requirements | 그 밖의 필수 조건 (다문화가족, 특수교육대상자, 거주 기간 등) |
| match.apply_period | 신청 기간 문구 |
| match.notes | 참고 사항 (판정에 쓰지 않음. 예: 아이돌봄 서비스의 정부 지원 기준) |
