# 0단계 소스 프로브

`docs/phase0_source_audit.md`의 근거를 만든 재실행용 스크립트입니다. Python 3.10+ 표준 라이브러리만 사용하고, 키는 코드에 넣지 않습니다.

| 스크립트 | 확인 대상 | 인증 |
|---|---|---|
| `naver_probe.py` | NAVER API HUB 뉴스 검색, 데이터랩 검색어 트렌드, 쇼핑인사이트(화장품/미용 50000002) | `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`가 있으면 `X-NCP-APIGW-API-KEY-ID`/`X-NCP-APIGW-API-KEY` 헤더를 붙이고, 없으면 붙이지 않음(프록시 주입 환경) |
| `gemini_probe.py [model]` | 모델 목록, 인자로 준 모델에 JSON 스키마 출력 1회 | `GEMINI_API_KEY`가 있으면 `x-goog-api-key` 헤더 |
| `web_probe.py [key ...]` | `sources.py`의 업계지·커머스·규제·경쟁사: robots.txt, 홈, RSS, 기사 1건, 목록 페이지 | 없음 |
| `eurlex_probe.py` | EU 화장품 규정(1223/2009) 개정 법령 목록 — CELLAR SPARQL | 없음 |
| `customs_probe.py [YYYYMM]` | 관세청 품목별 국가별 수출입실적 HS 3302/3303/3304 | `DATA_GO_KR_SERVICE_KEY` (없으면 요청 계획만 출력) |

결과는 `scripts/probe/out/`에 JSON으로 저장됩니다(웹 소스는 `out/web/<key>.json`).

주의: 요청은 소스당 3~6건, 요청 사이 1초 간격입니다. 이 결과는 클라우드 세션 출구 IP 기준이며, GitHub Actions 러너 IP에서는 차단 여부가 다를 수 있습니다. Actions에서 한 번 더 돌려 비교하세요.
