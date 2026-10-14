# beauty_trend — 작업 규칙

월간 뷰티·향료 트렌드 리포트 파이프라인. 설계는 `PLAN.md`, 소스 감사는 `docs/phase0_source_audit.md`, 실행법은 `README.md`.

## 문체 (매번 지킬 것)

- 리포트에 나가는 한국어(템플릿 문구, 프롬프트, 메일)는 `docs/style_guide.md`를 따른다. 규칙 정본은 `config/style.yaml`.
- 템플릿이나 문구를 바꾼 뒤 `python -m pytest -q`를 돌려 `tests/test_style.py`가 통과해야 한다.
- 유지보수자가 결과물의 어색한 표현을 지적하면: 해당 문구를 고치고, 같은 유형이 다시 나오지 않도록 `config/style.yaml`에 규칙(또는 `copy_banned` 항목)을 추가하고, `tests/test_style.py`에 그 예문을 넣는다.
- LLM 문장 고쳐 쓰기(`trend/style.py`)는 표현만 바꾼다. doc_ids·quote는 그대로이고, 고친 문장도 verify를 다시 거친다. 이 순서를 바꾸지 않는다.

## 사실·숫자

- 숫자는 코드가 계산해 표·차트에만 넣는다. LLM 문장에는 숫자를 쓰지 않는다(verify가 걸러 냄).
- 확인하지 않은 것을 확인했다고 쓰지 않는다. 소스 관련 판단은 프로브로 직접 확인하고 `docs/phase0_source_audit.md`에 남긴다.

## 보안

- 저장소는 public이다. 키·토큰은 코드·커밋·로그에 넣지 않는다(GitHub Secrets만).
- 기사 본문 전문은 커밋하지 않는다(`config/report.yaml`의 `storage.commit_fulltext: false`).
