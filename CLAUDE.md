# beauty_trend — 작업 규칙

월간 뷰티·향료 트렌드 리포트 파이프라인. 설계는 `PLAN.md`, 소스 감사는 `docs/phase0_source_audit.md`, 실행법은 `README.md`.

## 문체 (매번 지킬 것)

- 리포트에 나가는 한국어(템플릿 문구, 프롬프트, 메일)는 `docs/style_guide.md`를 따른다. 규칙 정본은 `config/style.yaml`.
- `plain-korean-writing` 스킬 규칙도 따른다(줄표, 가운뎃점 금지 등). 결과물을 내기 전에 독자가 보는 글을 스킬의 `check_plain_korean.py`로 검사해 거부를 0으로 만든다.
- 템플릿이나 문구를 바꾼 뒤 `python -m pytest -q`를 돌려 `tests/test_style.py`가 통과해야 한다.
- 유지보수자가 결과물의 어색한 표현을 지적하면: 해당 문구를 고치고, 같은 유형이 다시 나오지 않도록 `config/style.yaml`에 규칙(또는 `copy_banned` 항목)을 추가하고, `tests/test_style.py`에 그 예문을 넣는다.
- LLM 문장 고쳐 쓰기(`trend/style.py`)는 표현만 바꾼다. doc_ids·quote는 그대로이고, 고친 문장도 verify를 다시 거친다. 이 순서를 바꾸지 않는다.

## 시각 표기

- 유지보수자에게 시각을 말할 때는 KST로 적는다(예: 23:40 KST). 컨테이너 시계는 UTC이므로 `TZ=Asia/Seoul date`로 확인한다.
- 리포트, 로그, 파일 이름의 날짜도 KST 기준이다(`trend/util.py`의 `now_kst`, `kst_date`).

## 사실·숫자

- 숫자는 코드가 계산해 표·차트에만 넣는다. LLM 문장에는 숫자를 쓰지 않는다(verify가 걸러 냄).
- 확인하지 않은 것을 확인했다고 쓰지 않는다. 소스 관련 판단은 프로브로 직접 확인하고 `docs/phase0_source_audit.md`에 남긴다.

## 모델 작업 (2026-10-16부터)

- 기사 정리, 리포트 문장, 근거 검증은 외부 API가 아니라 예약된 Claude 작업 세션이 한다(`config/models.yaml`의 `backend: session`). 절차는 `docs/session_routine.md`.
- verify 요청은 쓴 쪽과 다른 새 서브에이전트(`verifier-…`)만 답한다. 코드가 이름 규칙을 강제한다. 메인 세션은 답을 직접 쓰지 않는다.
- 요청 파일과 기사 본문(`data/private/`, `work/`)은 커밋하지 않는다.

## LLM 비용

- 기사를 대량으로 정리하거나 다시 정리하기 전에 금액부터 센다. `enrich`는 예상 금액이 `config/models.yaml`의 `confirm_over_krw`를 넘거나 `--upgrade`이면 `--yes` 없이는 돌지 않고 추정치만 낸다.
- 정리 항목을 늘릴 때는 전체를 다시 정리하지 말고, 그 항목이 필요한 후보 기사만 골라 처리하는 방법을 먼저 찾는다(2026-10-15에 전체 재정리로 약 240만 토큰을 썼다).
- 같은 소식을 다룬 기사는 하나만 모델을 부르고 나머지는 분류를 복사한다(`enrich.copy_record`).
- 세션에서 모델을 부른 장부는 `usage/`에 모아 커밋한다(토큰 수만 있고 기사 내용은 없다). `python -m trend usage`로 결제서와 같은 미국 태평양 시간 날짜별로 본다.

## 보안

- 저장소는 public이다. 키·토큰은 코드·커밋·로그에 넣지 않는다(GitHub Secrets만).
- 기사 본문 전문은 커밋하지 않는다(`config/report.yaml`의 `storage.commit_fulltext: false`).
