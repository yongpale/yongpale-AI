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
