# 월간 뷰티·향료 트렌드 리포트 파이프라인

향료 회사 영업팀용 월간 리포트를 무인으로 만드는 파이프라인입니다. 설계는 [PLAN.md](PLAN.md), 소스 감사 결과는 [docs/phase0_source_audit.md](docs/phase0_source_audit.md)에 있습니다.

## 흐름

| 언제 | 워크플로 | 하는 일 |
|---|---|---|
| 매일 06:17 KST | `collect-daily` | 수집 → enrich(Gemini Flash) → `data` 브랜치 커밋, 기사 본문은 비공개 아티팩트(90일) |
| 매주 월 08:53 KST | `health-weekly` | 소스별 실패·0건·급감 점검. 경보면 job 실패 → GitHub 알림 메일 |
| 매월 25일 09:47 KST | `report-monthly` | 이번 달 드라이런(유지보수자에게만) |
| 매월 1일 09:47 KST | `report-monthly` | 전월 리포트 생성 → 품질 게이트 → 발행 또는 보류 |

결과물: PDF(상사 제출용 문서) + 슬라이드형 모션 HTML(`templates/motion/`, 시안 A·B·C). 수집 현황·방법론은 유지보수자 메일에만 들어갑니다.

월간 단계: `normalize`(중복 묶기·보도자료 태그·엔티티) → `aggregate`(숫자는 모두 코드) → `write`(Gemini, 문장마다 출처·원문 인용) → `verify`(인용 일치·숫자 금지·엔티티·근거 함의, 실패 문장 삭제) → `gate`(섹션 최소 기준, 핵심 과반 미달 시 보류) → `render`(HTML·PDF) → `deliver`(SMTP).

## 로컬 실행

```bash
pip install -r requirements.txt
export DATA_DIR=./data                     # 기본값
python -m trend collect                    # --only cosmorning,naver_news / --since 2026-09-01 --naver-pages 10
python -m trend enrich --month 2026-09
python -m trend report --month 2026-09 --dry-run   # --no-pdf, SKIP_LINK_CHECK=1, MOTION_VARIANTS=accord
python -m trend render --run-dir data/reports/2026-09/<실행>   # 템플릿만 바꿨을 때: LLM 호출 없이 다시 그리기(몇 초)
python -m trend report --month 2026-10 --until 2026-10-15 --dry-run   # 월중 중간 보고(전월 비교 없음)
python -m trend collect --backfill-since 2026-10-01   # 피드에서 빠진 날을 업계지 지난 기사 목록에서 채우기
python -m trend enrich --month 2026-10 --upgrade      # 예상 금액만 보여 주고 멈춤. 돌리려면 --yes
python -m trend llm pending                           # 세션 방식: 답을 기다리는 요청 수
python -m trend llm export --role enrich --out work/e1.json --limit 40   # 일꾼에게 줄 묶음
python -m trend llm import --file work/e1.ans.json --by enricher-1     # 일꾼 답 가져오기(verify는 --by verifier-…)
python -m trend usage --since 2026-10-01              # 장부 합산(결제서와 같은 미국 태평양 시간 날짜, Flash 단가로 원 환산)
python -m trend health --days 7
python -m pytest -q
```

## 설정

- `config/sources.yaml`: 수집 소스(0단계 감사에서 채택한 것만)
- `config/models.yaml`: Gemini 모델 ID(고정)와 대체 모델, thinking 예산
- `config/report.yaml`: 섹션 기준, 시행일 캘린더, 고객사 목록(비어 있으면 고객사 섹션 숨김), `storage.commit_fulltext`
- `config/entities.yaml`: 브랜드·회사 별칭

## Secrets (Settings → Secrets and variables → Actions)

| 이름 | 용도 | 필수 |
|---|---|---|
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | NAVER API HUB | 예 |
| `GEMINI_API_KEY` | Gemini(유료 등급 프로젝트) | 예 |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | 메일 발송 | 메일을 보내려면 |
| `MAINTAINER_EMAIL` | 드라이런·보류 경보 수신 | 메일을 보내려면 |
| `RECIPIENT_EMAIL` | 정식 수신자. 비어 있으면 유지보수자에게만 발송 | 아니오 |

SMTP가 없으면 메일은 건너뛰고 결과물은 Actions 아티팩트로만 남습니다.

## 데이터 보관

`data` 브랜치(코드와 분리된 orphan 브랜치)에 수집 메타데이터·추출 결과·실행 기록을 커밋합니다. 저장소가 public인 동안 기사 본문 전문은 커밋하지 않고 Actions 아티팩트(90일)에만 둡니다. 리포트 PDF도 아티팩트에만 있습니다.
