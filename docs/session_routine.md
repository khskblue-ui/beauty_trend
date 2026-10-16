# 작업 세션 루틴 (모델 작업을 Claude가 맡는 방식)

2026-10-16부터 기사 정리(enrich), 리포트 문장 쓰기(write), 근거 검증(verify)은 외부 API가 아니라
예약된 Claude Code 작업 세션이 한다(`config/models.yaml`의 `backend: session`). 파이프라인 코드는
모델을 부르지 않고 요청 파일을 남긴다. 세션은 요청을 서브에이전트에게 나눠 주고, 답을 가져와
같은 명령을 다시 돌린다. 원문 인용 확인, 숫자 금지, 이름 확인 같은 코드 검사는 그대로다.

## 지켜야 할 규칙

- **쓰는 쪽과 검증하는 쪽을 나눈다.** verify 요청은 새로 띄운 서브에이전트만 답한다. 이 에이전트는
  verify 요청 파일만 받고, enrich나 write 요청은 보지 않는다. 답을 가져올 때 `--by`는
  `verifier-…`로 시작해야 하며, 코드가 이 규칙을 강제한다(enrich, write 답에는 `verifier` 이름을 못 쓴다).
- **세션(메인)은 직접 답을 쓰지 않는다.** 일꾼 서브에이전트에게 나눠 준다. 메인은 명령 실행, 파일 전달,
  가져오기, 커밋만 한다.
- **원문에 없는 인용을 만들지 않는다.** 일꾼 지시문에 반드시 넣는다. 지어낸 인용은 코드가 버린다.
- **기사 본문과 요청 파일(`data/private/`)은 커밋하지 않는다.** 저장소가 public이다.
- 시각은 KST로 적는다.

## 준비 (매일, 월간 공통)

```bash
pip install -q -r requirements.txt          # 월간에 PDF가 필요 없으면 playwright 설치는 건너뛴다
git fetch -q origin data && (git worktree add data data 2>/dev/null || (cd data && git pull -q origin data))
export DATA_DIR=data
```

## 매일 (06:30 KST)

1. 수집: `python -m trend collect --backfill-since "$(TZ=Asia/Seoul date -d '3 days ago' +%F)"`
2. 정리: `python -m trend enrich` → 결과의 `waiting_for_answers`가 0이 될 때까지 아래를 되풀이한다.
   - `python -m trend llm export --role enrich --out work/enrich_<k>.json --limit 40`
   - 일꾼 서브에이전트(`enricher-<k>`)에게 준다. 동시에 4개까지. 일꾼 지시문:
     "work/enrich_<k>.json의 how_to_answer를 따른다. 각 item에 systems[item.system] 규칙을 적용해
     schemas[item.schema]에 맞는 JSON 하나로 답한다. 목록 항목(제품, 날짜가 있는 행사, 이름이 나온 원료)은
     빠짐없이 채우고, 이름은 기사 표기 그대로 쓴다. 인용(*_quote, quote)은 prompt 안의 기사 문장을
     한 글자도 바꾸지 않고 복사하고, 없으면 null 또는 빈 배열이다. 결과를
     [{"id":…, "data":…}] 목록으로 work/enrich_<k>.ans.json에 쓴다. 다른 파일은 만들거나 고치지 않는다."
   - `python -m trend llm import --file work/enrich_<k>.ans.json --by enricher-<k>`
     (거부된 항목은 이유를 보고 같은 일꾼에게 다시 맡긴다)
   - `python -m trend enrich`를 다시 돌린다.
3. 제품 검수: `python -m trend check-products` → `waiting_for_answers`가 0이 될 때까지
   - `python -m trend llm export --role verify --out work/verify_<k>.json`
   - **새 서브에이전트** `verifier-<날짜>-<k>`에게 이 파일만 준다. 지시문: "[근거]만 보고 [문장]이 참인지
     판정한다. 근거에 없는 내용이 하나라도 있으면 not_supported, 애매하면 uncertain."
   - `python -m trend llm import --file work/verify_<k>.ans.json --by verifier-<날짜>-<k>`
   - `python -m trend check-products`를 다시 돌린다.
4. 커밋: `cd data && git add -A && git commit -qm "collect+enrich $(TZ=Asia/Seoul date +%F) (session)" && git push -q origin data`
5. 끝으로 한 줄 보고: 새 기사 수, 정리 수, 복사 수, 거부 수, 남은 요청 수.

실패한 날(사용 한도, 세션 오류)은 다음 날 같은 절차가 이어서 처리한다. 남은 요청은
`python -m trend llm pending`으로 본다.

## 월간 (25일 시험본, 1일 정식본, 09:30 KST)

- 25일: 이번 달 시험본 `MONTH=$(TZ=Asia/Seoul date +%Y-%m)`, `FLAG=--dry-run`
- 1일: 전월 정식본 `MONTH=` 전월, `FLAG=` 없음

1. 그 달 기사가 모두 정리됐는지 확인: `python -m trend enrich --month $MONTH`의 `waiting_for_answers`가 0,
   `python -m trend check-products --month $MONTH`도 0. 아니면 매일 절차 2~3을 먼저 한다.
2. `python -m trend report --month $MONTH $FLAG --no-pdf` → 상태가 `pending`이면(종료 코드 3)
   - write 요청: `llm export --role write` → 일꾼 `writer-<k>` → `llm import --by writer-<k>`
   - verify 요청: `llm export --role verify` → **새** `verifier-…` → `llm import --by verifier-…`
   - 리포트 명령을 다시 돌린다. 문장 쓰기 → 문체 고쳐 쓰기 → 근거 검증 순서라 보통 3~4번 돈다.
3. 상태가 `dry_run` 또는 `publish`/`hold`가 되면 그 실행 폴더에서 확인한다.
   - 문체: 결과 JSON의 `style.warnings`가 비어 있어야 한다. `plain-korean-writing` 스킬이 있으면
     독자가 보는 글을 그 검사기로 돌려 거부를 0으로 만든다.
   - 슬라이드 넘침이 의심되면 `python -m trend render --run-dir <폴더> --no-pdf` 후 브라우저로 본다.
4. 그 실행 폴더에 `READY` 파일을 만들고 data 브랜치에 커밋, 푸시한다(PDF는 커밋하지 않는다).
   같은 날 13:47 KST에 Actions(report-monthly)가 PDF를 만들어 메일로 보낸다.

## 되돌리기

외부 API로 돌아가려면 `config/models.yaml`의 각 단계 `backend`를 `gemini`로 바꾼다. 그때는
`enrich`가 예상 금액을 먼저 보여 주고, 큰 작업은 `--yes` 없이 돌지 않는다.
