# 0단계 — 소스 실현성 감사 결과

- 확인일: 2026-10-14 (KST 저녁)
- 확인 환경: (1) Claude Code 클라우드 세션, (2) GitHub Actions 러너(`phase0-probe` 실행 [#1](https://github.com/khskblue-ui/beauty_trend/actions/runs/38573654350)·[#2](https://github.com/khskblue-ui/beauty_trend/actions/runs/38574342316), 2026-10-14 13:40Z). 두 환경의 차이는 "5. IP 위험" 참고.
- 근거: `scripts/probe/` 스크립트로 직접 요청한 결과(`scripts/probe/out/*.json`). 공식 문서만으로 확인한 항목은 "문서 확인"으로, 요청으로 확인하지 못한 항목은 "미확인"으로 표기했다.
- 요청량: 소스당 3~6건(robots.txt, 홈, RSS, 기사 1건, 목록 페이지), 요청 사이 1초 간격. 웹 프로브는 일부 소스에서 오류 수정 후 2회 실행했다.

## 요약

1. **네이버 API HUB 4개 엔드포인트 모두 200 확인.** 프록시 헤더 주입이 동작했다(401/403 없음). 뉴스 검색, 데이터랩 검색어 트렌드, 쇼핑인사이트 분야별·키워드별 트렌드(화장품/미용 `50000002`)의 응답 형식을 확보했다.
2. **Gemini 정상 동작(세션·러너 모두).** `gemini-3.8-flash`로 JSON 스키마 출력을 확인했다. 결정: enrich `gemini-3.8-flash`, write `gemini-4-argon`(2026-10-14 변경).
3. **국내 업계지는 4곳이 RSS를 제공한다**(코스모닝·장업신문·뷰티경제·코스인코리아). 전문을 주는 곳은 뷰티경제(`content:encoded`) 하나이고, 나머지 3곳은 요약만 준다. 기사 페이지는 robots.txt상 허용되므로 본문은 기사 URL로 받아야 한다. CMN은 robots.txt가 `/rss/`를 금지하므로 RSS를 쓰지 않는다.
4. **네이버 뉴스 검색으로는 업계지를 대체할 수 없다.** "화장품 신제품 출시"와 "향료"로 최신 400건을 조회했는데, 업계지 원문 링크는 뷰티경제 2건뿐이었다. 업계지는 RSS로 직접 수집해야 한다.
5. **커머스(올리브영·무신사)는 제외한다.** 올리브영은 robots.txt부터 Cloudflare 챌린지(403)를 반환한다. 무신사는 robots.txt가 허용 목록에 없는 봇(`*`)에 전체 경로를 금지한다.
6. **글로벌 업계지는 4곳이 RSS를 제공하지만 모두 요약만 준다.** 전문을 무료로 읽을 수 있는 곳은 Premium Beauty News뿐이었다. WWD는 유료벽(`isAccessibleForFree: false`)이 있다. GCI는 RSS는 받히지만 기사 페이지가 Cloudflare 챌린지로 막힌다. **CosmeticsDesign(Europe/Asia)은 2026년 3월 폐간되어 410을 반환한다.**
7. **규제는 4곳 모두 변경 감지가 가능하다.**
   - EU: eur-lex.europa.eu는 AWS WAF 챌린지(202)를 반환한다. 대신 EU 출판국 CELLAR SPARQL(키 불필요)로 화장품 규정 1223/2009의 개정 법령 목록을 받는 데 성공했다.
   - 식약처: RSS 4종(보도자료·고시전문·행정예고·최근 개정 법령)이 200이다. (세션에서 보인 간헐적 연결 리셋은 세션 프록시 터널 문제로 확인됨 — 아래 정정 참고)
   - FDA: 세션 IP에서는 200이었으나 **Actions 러너 IP에서는 robots.txt를 포함한 모든 요청이 404**. 미국 규제는 Federal Register API(FDA, `"cosmetic product"`)로 대체한다(러너 200 확인).
   - IFRA: 뉴스 목록 페이지 diff(RSS 없음).
8. **경쟁 향료사는 3곳 수집 가능, IFF는 보류.** Givaudan과 Symrise는 RSS, dsm-firmenich는 날짜가 붙은 HTML 목록이 있다. IFF는 www와 IR 사이트 모두 이 IP에서 403(Cloudflare)이다.
9. **관세청 HS 3302/3303/3304는 문서까지만 확인했다.** data.go.kr 서비스키가 필요하고, `cntyCd`(국가코드)가 필수라 국가별로 호출해야 한다. 매월 15일경 전월분까지 갱신된다. 키가 없어 호출하지 않았다.

## MVP 확정 소스 목록

| 용도 | 소스 | 수집 방식 |
|---|---|---|
| 키워드 보조 지표 | 네이버 데이터랩 검색어 트렌드 | `POST /search-trend/v1/search` |
| 키워드 보조 지표(쇼핑) | 네이버 쇼핑인사이트 | `POST /shopping/v1/categories`, `/shopping/v1/category/keywords` (화장품/미용 `50000002`) |
| 국내 뉴스(일반지) | 네이버 뉴스 검색 | `GET /search/v1/news` (`sort=date`, 질의어 사전 + 제외어 필터) |
| 국내 업계지 | 코스모닝, 장업신문, 뷰티경제, 코스인코리아 | RSS(매일). 요약만 주는 곳은 기사 URL에서 본문 수집(robots 허용 경로) |
| 글로벌 업계지 | Cosmetics Business, Premium Beauty News, WWD Beauty | RSS 제목·요약만 사용(헤드라인급 근거 등급). PBN은 본문 접근 가능 |
| 규제(EU) | EU CELLAR SPARQL | 1223/2009 개정 법령 목록 diff → EUR-Lex 링크 생성 |
| 규제(국내) | 식약처 RSS: 보도자료 `ntc0021`, 고시전문 `data0005`, 행정예고 `data0009`, 최근 개정 법령 `data0008` | RSS + 제목 키워드 필터("화장품" 등) |
| 규제(미국) | Federal Register API(기관=FDA, 질의 `"cosmetic product"`) | JSON API `GET /api/v1/documents.json`에 `publication_date[gte]` 필터, 하루 1회 이하 |
| 규제(향료) | IFRA 뉴스 목록 페이지 | 페이지 diff(새 기사 링크 감지) |
| 경쟁사 | Givaudan RSS, Symrise RSS, dsm-firmenich 뉴스 목록 | RSS / 페이지 diff |
| LLM | Gemini enrich `gemini-3.8-flash`, write `gemini-4-argon`(Stable) — 대체 `gemini-3.5-flash` / `gemini-3.1-pro-preview` | REST `generateContent` + `responseSchema`, `thinkingConfig`로 예산 제한 |

보류: CMN(HTML 목록 스크래핑 필요), GCI(RSS 요약만, 기사 접근 차단), BeautyMatter(RSS·사이트맵 없음), IFF(차단), 관세청(키 필요).
제외: 올리브영, 무신사뷰티, CosmeticsDesign-Europe/Asia(폐간), fda.gov 직접 수집(러너 IP 404 → Federal Register로 대체).

## 1. 네이버 API HUB

호스트는 `https://naverapihub.apigw.ntruss.com`이고, 인증 헤더는 `X-NCP-APIGW-API-KEY-ID`와 `X-NCP-APIGW-API-KEY`다. 이 세션에서는 프록시가 헤더를 주입했고, 코드는 헤더 없이 호출했다. `naver_probe.py`는 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`가 있을 때만 헤더를 직접 붙인다.

| API | 경로(공식 문서) | 결과 | 응답 형식 |
|---|---|---|---|
| 뉴스 검색 | `GET /search/v1/news?query=&display(≤100)&start(≤1000)&sort=sim\|date` | **200** (1.6s), 질의 "향수" total 563,731 | `lastBuildDate,total,start,display,items[title,originallink,link,description,pubDate]`. `pubDate`는 RFC 822 `+0900`. 제목·요약에 `<b>`와 HTML 엔티티가 들어 있음 |
| 데이터랩 검색어 트렌드 | `POST /search-trend/v1/search` (keywordGroups ≤5, 그룹당 키워드 ≤20, 2016-01-01부터) | **200** (0.9s) | `results[title,keywords,data[period,ratio]]`. 요청 안에서 최댓값을 100으로 두는 상대값 |
| 쇼핑인사이트 분야별 | `POST /shopping/v1/categories` (category ≤3, 2017-08-01부터) | **200** (0.8s), 화장품/미용 `50000002` | `results[title,category,data[period,ratio]]` |
| 쇼핑인사이트 분야 내 키워드별 | `POST /shopping/v1/category/keywords` (keyword ≤5, param은 1개) | **200** (0.9s) | `results[title,keyword,data[period,ratio]]` |
| (참고) 기기별·성별·연령별 | `/shopping/v1/category/device`, `/shopping/v1/category/keyword/gender` 등 | 호출 안 함(문서 확인) | 동일 패턴 |

한도와 요금(공식 문서 기준):
- 요금: "한시적으로 무료로 제공되며, 유료 전환 시 사전에 별도 공지". 종량제 예정이고 요율은 미공개. [NAVER API HUB 개요](https://guide.ncloud-docs.com/docs/apihub-overview)
- 월 한도: 검색(뉴스 포함 검색 API 합산) 775,000건, 데이터랩 검색어 트렌드 50,000건, 쇼핑인사이트 50,000건(별도 산정). 무료 기간에는 증액 불가. 한도에 도달하면 자동 차단되고, 50%·80%·100% 도달 시 메일 알림.
- 속도: API 키당 50 RPS, 초과 시 429.
- **문서 간 불일치**: 뉴스 검색 API 페이지는 "검색 API의 하루 호출 한도는 25,000회"라고 하고, 개요 페이지는 월 775,000건이라고 한다. 우리 사용량(하루 수백 건 이하)에서는 어느 쪽이든 문제가 없다.

구현 시 주의:
- 응답 `Content-Type`이 `text/plain;charset=UTF-8`이다. JSON 파싱은 Content-Type에 의존하지 않아야 한다.
- 뉴스 검색에서 "향수"는 동음이의어(nostalgia)라 연예·게임 기사가 섞여 나왔다. 질의어 사전과 제외어 필터가 필요하다.
- 업계지 커버리지가 거의 없다(요약 4번). 뉴스 검색은 일반지·통신사용으로만 쓴다.
- 데이터랩 값은 요청 단위 상대값이다. 월별 비교는 PLAN대로 앵커 키워드를 같은 요청에 넣어야 한다.
- 원래 키는 401/403일 때를 대비해 오류 분기를 넣어야 한다. 마이그레이션 가이드는 "오류 응답 형식·상태 코드가 기존과 다를 수 있음"이라고 안내한다. 이번 세션에서는 오류 응답을 관찰하지 못했다.

## 2. Gemini API

- 모델 목록(`GET /v1beta/models`): 200. `generateContent`를 지원하는 모델 46개.
  - Flash 계열(텍스트): `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`, 별칭 `gemini-flash-latest`·`gemini-flash-lite-latest`, 프리뷰 `gemini-3-flash-preview`·`gemini-3.1-flash-lite-preview`
  - Pro 계열(텍스트): `gemini-2.5-pro`, `gemini-3.1-pro-preview`, 별칭 `gemini-pro-latest`
  - PLAN의 "고정 모델 ID" 원칙에 따라 `*-latest` 별칭은 쓰지 않는다.
- JSON 출력 테스트 1회: `gemini-3.8-flash`, `responseMimeType=application/json` + `responseSchema`, temperature 0 → **200**. 출력은 `{"brand":"딥티크","notes":["무화과","시더우드"]}`로 스키마에 맞았다. `modelVersion: gemini-3.8-flash`.
  - 토큰: 입력 36, 출력 18, **thinking 255**(기본으로 켜져 있음). enrich 단계 비용을 산정할 때 thinking 토큰을 넣거나, `thinkingConfig`로 예산을 제한해야 한다.
  - 러너에서 `GEMINI_API_KEY`로 같은 테스트를 2회 반복: 결과 동일, thinking 327·320 토큰.
- 모델 메타데이터(`GET /v1beta/models/{id}`): `gemini-3.8-flash`는 입력 1,048,576·출력 65,536 토큰, thinking 지원. `gemini-2.5-pro`는 "Stable release (June 17th, 2025)". `gemini-3.1-pro-preview`는 프리뷰.
- 단가([공식 가격표](https://ai.google.dev/gemini-api/docs/pricing), 유료 등급, 100만 토큰당):

  | 모델 | 입력 | 출력(thinking 포함) | 비고 |
  |---|---|---|---|
  | `gemini-3.8-flash` | $0.75 → **2027-01-01부터 $1.50** | $3.75 → **$7.50** | 2026년 말까지 도입가. Batch는 50% |
  | `gemini-3.5-flash-lite` | $0.30 | $2.50 | 대체 후보 |
  | `gemini-2.5-pro` | $1.25(≤200k) | $10.00 | GA |
  | `gemini-3.1-pro-preview` | $2.00 | $12.00 | 프리뷰 |

- **결정(2026-10-14, 1차)**: enrich `gemini-3.8-flash`, write `gemini-2.5-pro`. **같은 날 write를 `gemini-4-argon`으로 변경**(유지보수자 지정). Argon은 공식 모델 페이지에 Stable로 표시, 단가 입력 $2.00·출력 $10.00(100만 토큰당, 2026-11-30까지) → 2026-12-01부터 $4.00·$20.00, 무료 등급 없음. JSON 스키마 테스트 통과. 같은 페이지에 `gemini-2.5-pro`는 과거 사용자에게만 제공된다고 적혀 있다. 대체 모델 config: enrich `gemini-3.5-flash`, write `gemini-3.1-pro-preview`.
  - 비용 추정(가정: 월 기사 1,500건 × 입력 1,500 + 출력·thinking 450 토큰): enrich 약 $4/월, 2027년 단가로 약 $8/월. thinking이 출력의 약 90%라 `thinkingConfig.thinkingBudget`을 낮게 두는 효과가 크다. 1단계에서 품질과 함께 측정한다.
  - `gemini-2.5-pro`는 2025-06 출시라 3.x 계열보다 먼저 단종될 수 있다. 모델 ID를 config로 분리하고 단종 공지를 감시한다(PLAN 운영·보안).
- 미확인: 이 프로젝트가 유료 등급인지(응답 `serviceTier: standard`만으로는 판단 불가). PLAN상 무료 등급 입력은 제품 개선에 쓰일 수 있으므로 결제 연결을 확인해야 한다.

## 3. 웹 소스 감사 표

표기: robots ✓ = 해당 경로가 `*`와 우리 UA에 허용됨. "본문"은 기사 페이지 `<p>` 텍스트 길이(유료벽·차단 여부 확인용).

### 국내 업계지

| 소스 | 엔드포인트 | 접근 결과 | 전문/요약 | 날짜 필드 | robots/약관 | 판정 | 비고 |
|---|---|---|---|---|---|---|---|
| 코스모닝 | `https://www.cosmorning.com/data/rss/news.xml` | RSS 200, 50건(10-06~10-14) / 기사 200 | 요약(평균 169자). 기사 페이지 본문 1.5천 자 | `dc:date` `2026-10-14 17:48:55` (**타임존 없음 → KST로 해석**) | robots: `Yeti`만 명시, 그 외 제한 없음 ✓ / 약관 미확인 | **채택** | 본문은 기사 URL에서 수집 |
| 장업신문 | `https://www.jangup.com/rss/allArticle.xml` | RSS 200, 50건(10-08~10-14) / 기사 200 | 요약(평균 299자). 본문 2.4천 자 | `pubDate` `2026-10-14 10:55:00` (**타임존 없음, 비RFC 형식**) | `Disallow: /admin/`만 ✓ / 약관 미확인 | **채택** | `/rss/` 안내 페이지는 403이지만 피드 URL은 200 |
| CMN(주간신문씨엠엔) | RSS 없음(robots 금지). 목록 `https://www.cmn.co.kr/main/` → `/sub/news/news_view.asp?news_idx=N` | 홈 200, 정적 HTML(가시 텍스트 약 2만 자) | HTML에서 본문 추출 필요 | 미확인(목록·기사 페이지 날짜 위치 미조사) | **`Disallow: /rss/`** (`*`), 기사 경로는 ✓ / 약관 미확인 | **보류** | RSS를 의도적으로 막음. HTML 스크래퍼를 만들지는 1단계 이후 결정. robots.txt 요청에서 연결 리셋 1회 |
| 뷰티경제 | `https://cdn.thebk.co.kr/rss/gn_rss_allArticle.xml` | RSS 200, 50건(10-12~10-14) / 기사 200 | **전문**(`content:encoded` 약 4천 자) | `pubDate` RFC 822 `+0900` | ✓ (`GPTBot`만 전체 금지, bingbot crawl-delay 30) / 약관 미확인 | **채택** | 피드가 약 2일치만 보관 → **매일 수집 필수** |
| 코스인코리아 | `https://www.cosinkorea.com/data/rss/news.xml` | RSS 200, 25건(10-12~10-14) / 기사 200 | 요약(평균 167자). 본문 4.2천 자 | `dc:date` 타임존 없음 | `Allow: /` ✓ / 약관 미확인 | **채택** | 피드가 약 2일치 → 매일 수집 필수 |

### 국내 커머스

| 소스 | 엔드포인트 | 접근 결과 | 전문/요약 | 날짜 필드 | robots/약관 | 판정 | 비고 |
|---|---|---|---|---|---|---|---|
| 올리브영 랭킹·신상품 | `/store/main/getBestList.do`, `/store/main/getNewList.do` | **robots.txt부터 403** (`cf-mitigated: challenge`, Cloudflare, 페이지 제목 "잠시만 기다려 주세요") | - | - | robots 확인 불가(챌린지) / 약관 페이지도 외부 fetch 403 → 미확인 | **제외** | 우회는 시도하지 않음. JS 챌린지를 통과해야 해서 무인 운영에 맞지 않음 |
| 무신사뷰티 랭킹 | `/main/beauty/ranking` | robots.txt 200, 랭킹 페이지 200이지만 가시 텍스트 11자(**JS 렌더링 필요**). 이후 curl 요청은 Cloudflare "you have been blocked" | - | - | **robots: 허용 목록 봇 외 `*`는 `/` 전체 금지** / 약관 미확인 | **제외** | robots 금지만으로 제외 사유가 충분 |

### 글로벌 업계지

| 소스 | 엔드포인트 | 접근 결과 | 전문/요약 | 날짜 필드 | robots/약관 | 판정 | 비고 |
|---|---|---|---|---|---|---|---|
| WWD Beauty | `https://wwd.com/beauty-industry-news/feed/` | RSS 200, 10건 / 기사 200 | 요약(평균 124자). **유료벽**: 기사 JSON-LD `isAccessibleForFree: "false"` | `pubDate` RFC 822 | ✓ (`anthropic-ai`, `cohere-ai` 등 AI 봇은 금지) / 약관 미확인 | **채택(제목·요약만)** | 헤드라인급 근거 등급. 본문 수집 안 함 |
| Cosmetics Business | `https://www.cosmeticsbusiness.com/rss` | RSS 200, 19건 / 기사 200 | 요약(평균 217자). 기사 본문 1만 자, 일부 "premium content" 표식 | `pubDate` RFC 822 | `Allow: /` ✓ / 약관 미확인 | **채택(요약 위주)** | 프리미엄 기사는 본문 일부만 공개되는 것으로 추정(미확인) |
| Premium Beauty News | `https://www.premiumbeautynews.com/spip.php?page=backend` | RSS 200, 22건 / 기사 200 | 요약(평균 511자, 가장 김). 본문 2.7천 자 무료 | `dc:date` ISO 8601 UTC | ✓, `Crawl-delay: 1` / 약관 미확인 | **채택** | 글로벌 중 유일하게 무료 본문 확인 |
| CosmeticsDesign-Europe | `www.cosmeticsdesign-europe.com` | **410 Gone** | - | - | - | **제외** | 공지: "2026년 3월에 CosmeticsDesign.com, -Europe, -Asia를 폐간"했고, 뷰티 보도는 NutraIngredients.com으로 이관 |
| CosmeticsDesign-Asia | `www.cosmeticsdesign-asia.com` | **410 Gone** | - | - | - | **제외** | 위와 같음 |
| BeautyMatter | `https://beautymatter.com/` | 홈 200, 기사 200(본문 8.4천 자, 페이지 소스에 "paywall" 문자열) | RSS 없음(`/feed`, `/rss` 404). robots에 적힌 `sitemap.xml`도 404 | 미확인 | ✓ / 약관 미확인 | **보류** | 새 기사를 감지하려면 홈 목록 diff가 필요. 유료 범위 미확인 |
| Global Cosmetic Industry | `https://www.gcimagazine.com/__rss/website-scheduled-content.xml?input=%7B%22sectionAlias%22%3A%22home%22%7D` (`/rss/`에서 301) | RSS 200, 25건 / **홈·robots·기사 403 Cloudflare 챌린지** | 요약(평균 102자) | `pubDate` RFC 822 `-0500` | robots 확인 불가 / 약관 미확인 | **보류** | robots를 확인할 수 없는 상태에서는 채택하지 않음. 리포트 링크는 "접근 제한"으로 표시될 것 |

### 규제

| 소스 | 엔드포인트 | 접근 결과 | 전문/요약 | 날짜 필드 | robots/약관 | 판정 | 비고 |
|---|---|---|---|---|---|---|---|
| IFRA | `https://ifrafragrance.org/latest-updates/ifra-news` (+ `/standards-library`) | 200, 정적 HTML. 목록에서 날짜 17개 추출 | 목록 → 기사 링크 | 본문 텍스트 `08 October 2026` 형식 | ✓ | **채택(페이지 diff)** | RSS 없음. 개정 공지는 뉴스 기사로 게시됨(예: "52nd Amendment … Global Cosmetics Regulations 2026"). Standards Library는 날짜가 없어 해시 diff만 가능 |
| EUR-Lex | `eur-lex.europa.eu` | **202 + `x-amzn-waf-action: challenge`** (robots.txt 포함) | - | - | robots 확인 불가 | 사이트 직접 수집 **제외** | 리포트 링크로는 사용. 링크 검사 시 202/챌린지를 "접근 제한"으로 처리해야 함 |
| EU CELLAR SPARQL | `https://publications.europa.eu/webapi/rdf/sparql` | **200** (0.7s, 키 불필요) | 법령 목록(CELEX, 문서일, 영문 제목) | `cdm:work_date_document` | 공개 API | **채택** | 1223/2009 개정 법령 10건 조회. 최신은 `32026R0909`(2026-04-27), `32026R0078`(2026-01-12). PLAN의 2023/1545(`32023R1545`)도 확인 |
| 식약처 | RSS 안내 `https://www.mfds.go.kr/www/rss/list.do` → `.../www/rss/brd.do?brdId=` `ntc0021`(보도자료), `data0005`(고시전문), `data0009`(행정예고), `data0008`(최근 개정 법령) | 4종 모두 **200**, 각 29건 | 제목 위주(`description` 비어 있음) | `pubDate` RFC 822 GMT | `User-agent: * Allow:/` ✓ | **채택** | 세션에서 보인 연결 리셋(ECONNRESET)은 세션 프록시 터널 문제였다(2026-10-14 정정). 러너에서는 정상. 화장품 외 항목이 대부분이라 제목 필터 필요 |
| FDA MoCRA | 보도자료 RSS `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml` + MoCRA 페이지 + `/cosmetics/cosmetics-news-events` | 세션: RSS 200(20건), 페이지 200 / **러너: 전부 404**(robots.txt 포함, 본문 9자 — 데이터센터 IP 차단으로 추정) | RSS 요약 226자 | RSS RFC 822(EDT) | 세션에서 ✓ | **제외(직접 수집)** | 러너에서 2회 연속 404. 리포트 링크로만 사용하고 링크 검사에서는 "접근 제한"으로 처리 |
| Federal Register (FDA) | `https://www.federalregister.gov/api/v1/documents.json?conditions[agencies][]=food-and-drug-administration&conditions[term]="cosmetic product"&order=newest` (RSS는 `documents.rss`) | 세션: JSON 200, 해당 문서 106건(예: 2026-01-22 "FDA Records Access Authority for Cosmetics; Draft Guidance") / 러너: RSS 200(최근 1건만) | 제목·요약·문서 유형(Rule/Proposed Rule/Notice) | `publication_date` | `/api/v1/` 허용 ✓ (`/documents/search` 등은 금지) / 키 불필요 | **채택** | **세션 IP에서 약 1분 동안 7건을 요청하자 IP가 차단됨**("Your IP address has been blocked, Support Code 02"). 하루 1회, 요청 간 간격 필수. RSS는 최근분만 담으므로 JSON API에 날짜 필터를 쓴다. `"cosmetic"` 단독 질의는 FD&C Act 문구 때문에 무관한 문서가 잡히므로 쓰지 않음 |

### 경쟁 향료사

| 소스 | 엔드포인트 | 접근 결과 | 전문/요약 | 날짜 필드 | robots/약관 | 판정 | 비고 |
|---|---|---|---|---|---|---|---|
| Givaudan | `https://www.givaudan.com/rss` ("Last 25 media releases") | RSS 200, 25건 / 기사 200(본문 1.5만 자) | 요약 266자, 본문 무료 | `pubDate` **`21 September 2026` (비RFC)** | ✓ | **채택** | 25건 중 마지막 항목이 2015-10-07(선정 기준 미확인) → 수집 시 날짜로 직접 필터·정렬 |
| dsm-firmenich | `https://our-company.dsm-firmenich.com/en/our-company/news.html` | 200, 정적 HTML, 날짜 34개 | 목록 → 기사 | `14 October 2026` 형식 | ✓ | **채택(페이지 diff)** | 공식 RSS는 찾지 못함 |
| IFF | `https://www.iff.com/news/`, `https://ir.iff.com/news-events/press-releases`, `https://ir.iff.com/rss/news-releases.xml` | **모두 403** (www는 Cloudflare 챌린지) | - | - | robots.txt 200, `/news/` 허용 | **보류** | 이 IP에서는 차단. Actions IP에서 재확인하거나, 보도자료 배포처(뉴스와이어) 경유를 검토 |
| Symrise | `https://www.symrise.com/newsroom/press-releases/rss.xml` | RSS 200, **579건**(2010~) / 기사 200 | 요약 216자, 본문 무료 | `pubDate` RFC 822 `+0200` | ✓ | **채택** | 피드가 크므로(전체 이력) 최근 N건만 사용 |

### 통계

| 소스 | 엔드포인트 | 접근 결과 | 전문/요약 | 날짜 필드 | robots/약관 | 판정 | 비고 |
|---|---|---|---|---|---|---|---|
| 관세청 품목별 국가별 수출입실적(GW) | `GET https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList` ([data.go.kr 15100475](https://www.data.go.kr/data/15100475/openapi.do)) | **호출 안 함(키 없음)**, 문서만 확인 | XML: `year, statCd, statKor, hsCd, expWgt, expDlr, impWgt, impDlr, balPayments` | `strtYymm`/`endYymm`(≤1년) | 공공데이터 이용허락. 개발계정 자동승인, **일 10,000건** | **보류(키 필요)** | **`cntyCd` 필수** → 국가별 호출 필요(예: 상위 10개국 × HS 3개 = 30건/월). **매월 15일경 전월분까지 갱신** → 1일 발행 리포트에는 전전월 확정치를 싣는 것이 안전. `hsSgn`에 4자리를 넣었을 때 하위 코드가 합산되는지는 미확인 |

## 4. 리포트 섹션별 충족 판정(MVP)

| # | 섹션 | 판정 | 근거 소스 / 부족한 점 |
|---|---|---|---|
| 0 | 표지 | 가능 | 통계 기준월은 데이터랩(전월까지)과 관세청(보류)으로 나눠 표기 |
| 1 | 3줄 요약 | 가능 | 다른 섹션의 검증 통과 문장에 의존 |
| 2 | 이달의 키워드 | **가능** | 국내 업계지 RSS 4곳(하루 약 40~60건) + 네이버 뉴스 → 빈도 급증, 데이터랩·쇼핑인사이트로 보조. 전월 비교는 업계지 누적이 한 달 이상 쌓인 뒤부터 가능 |
| 3 | 신제품 트래커(국내) | **가능(조건부)** | 업계지 4곳. 요약만 주는 3곳은 기사 본문 수집이 필요(robots 허용). 출시일 추출 품질은 1단계에서 검증 |
| 4 | 향 노트 픽 | **가능(n 미지수)** | 노트가 명시된 기사는 본문이 있어야 잡힘. n≥30이 될지는 미확인 → 처음에는 목록형 |
| 5 | 고객사 워치 | **숨김(보류 항목)** | 소스는 준비됨(업계지 + 네이버 뉴스 검색으로 고객사명 질의 가능). 고객사 목록이 필요 |
| 6 | 시장 동향 | **가능** | 국내: 업계지 + 네이버 뉴스. 글로벌: Cosmetics Business, PBN, WWD(요약만 → 헤드라인급 등급) |
| 7 | 규제·원료·경쟁사 | **가능** | EU(CELLAR), 식약처 RSS, Federal Register(FDA), IFRA, Givaudan·Symrise·dsm-firmenich. IFF는 공백. FDA 보도자료는 러너에서 차단되어 빠짐 |
| 8 | 영업 시그널 | **숨김/제한** | 고객사 목록이 없으면 대상이 없음. 자사 프로필이 없으면 매칭 미반영 고지 |
| 9 | 부록 | 가능 | 소스별 성공/실패 커버리지 표는 위 프로브 구조를 재사용 |
| 2차 | 수출 통계 | 보류 | 관세청 키 필요 |
| 2차 | 랭킹 기반 급상승 | 불가 | 올리브영·무신사 제외. 쇼핑인사이트 키워드 클릭 추이로 일부 대체 가능 |

## 5. IP 위험(GitHub Actions) — 러너 재확인 결과

`phase0-probe` 워크플로를 러너(ubuntu-latest)에서 실행해 세션 결과와 비교했다.

| 소스 | 클라우드 세션 | Actions 러너 | 영향 |
|---|---|---|---|
| 네이버 API HUB 4종 | 200(프록시 헤더 주입) | **200(`NAVER_CLIENT_ID`/`SECRET`로 헤더 직접 첨부)** | 운영 방식 그대로 동작 확인 |
| Gemini `gemini-3.8-flash` | 200, JSON 정상 | **200, JSON 정상**(`GEMINI_API_KEY`) | 동일 |
| EU CELLAR SPARQL | 200 | 200 | 동일 |
| 국내 업계지 4곳 RSS·기사, CMN 홈 | 200 | 200 | 동일 |
| 글로벌 업계지(WWD·CB·PBN RSS, GCI RSS) | 200 | 200 | 동일(GCI 기사·홈은 둘 다 Cloudflare 403) |
| 식약처 RSS 4종 | 200(간헐 연결 리셋 — 세션 프록시 원인) | 200(리셋 없음) | 문제 없음 |
| IFRA, Givaudan, Symrise, dsm-firmenich | 200 | 200 | 동일 |
| IFF, 올리브영, EUR-Lex 사이트 | 403/202 챌린지 | 403/202 챌린지 | 동일하게 차단 |
| 무신사 robots | 200(`*` 전체 금지) | 200(`*` 전체 금지) | 동일 |
| **FDA(fda.gov)** | 200 | **404(robots.txt 포함 전부)** | **유일한 차이** → Federal Register로 대체 |
| Federal Register | 200 → 7건째 IP 차단 | RSS 200 | 호출 빈도 제한 필요 |

결론: 러너 IP에서도 MVP 소스는 FDA를 빼고 모두 동작한다. 러너 IP는 실행마다 바뀌므로, 수집기는 소스별 성공/실패를 기록하고 주간 헬스체크(PLAN)로 감시한다.

## 6. 결정 사항(2026-10-14, 유지보수자 승인)

- MVP 소스는 위 "MVP 확정 소스 목록"으로 확정. FDA 직접 수집은 제외하고 Federal Register로 대체.
- CMN: 보류 유지. 1단계 MVP에서는 수집하지 않고, 업계지 4곳의 커버리지가 부족하면 HTML 수집을 검토한다.
- 업계지 이용약관: 리포트에는 1~2문장 인용 + 링크만 싣고, 원문 전문은 비공개 보관 후 기간이 지나면 삭제한다(PLAN 원칙). 이 수준으로 진행한다.
- Gemini: enrich `gemini-3.8-flash`, write `gemini-4-argon`.
- 관세청: 서비스키를 받기 전까지 2차로 보류.

## 7. 지난 기사 백필 경로(2026-10-15 확인)

RSS는 며칠치만 보관한다(9월분 시험본에서 업계지 9월 기사 0건). 피드에서 빠진 기사를 채우는 경로를 소스별로 직접 확인했다(`collect --backfill-since`, `config/sources.yaml`의 `archive`).

| 소스 | 경로 | robots | 날짜 |
|---|---|---|---|
| 장업신문, 뷰티경제 | `/news/articleList.html?sc_sdate=D&sc_edate=D&view_type=sm`(하루씩). `page=N`은 무시되어 첫 페이지만 나옴 | 허용 | 기사 `article:published_time` |
| 코스모닝·코스인코리아 | `/news/article_list_all.html?page=N` | 허용 | 기사 JSON-LD `datePublished` |
| Premium Beauty News | 분야별 목록 10곳(`/en/markets-trends/` 등, 각 최근 30건). `debut_articles` 페이지 넘김은 무시되어 같은 화면이 나옴. 링크는 `<base href>` 기준 상대 경로 | 허용 | 기사 JSON-LD `datePublished` |
| WWD Beauty | `/beauty-industry-news/feed/?paged=N` | 허용 | 피드 `pubDate`(제목·요약만) |
| Cosmetics Business | `sitemap.xml`(약 14MB, 3.9만 URL) | 허용 | 기사 페이지에 게시일이 없어 `<lastmod>` 사용. 피드에 있던 19건 중 17건은 게시일과 같고 2건은 하루 차이(수정일이라 늦을 수 있음). `date_source: sitemap_lastmod`로 표시 |

## 8. 쇼핑인사이트 인기 검색어(2026-10-15 확인)

- API(`/shopping/v1/category/keywords`)는 요청한 검색어(최대 5개)의 클릭 추이만 준다. 분야별 인기 검색어 순위는 API에 없다.
- 순위가 보이는 데이터랩 웹 화면은 robots.txt가 `Disallow: /`(첫 화면만 허용)라 수집하지 않는다.
- 그래서 리포트는 설정(`shopping_terms`)에 정한 제품 5개의 주별 클릭 추이를 싣는다. 반달 데이터가 낮아 보이지 않게 완결된 주까지만 받는다.

## 9. LLM 비용 점검(2026-10-16)

- 구글 결제서의 Flash 단가는 입출력 합산 1천 토큰당 약 1.9원이다(10/14, 10/15 결제분에서 역산).
- 10/15(미국 태평양 시간) Flash 514만 토큰 가운데 511만 토큰은 이 저장소의 작업 세션 몫이다(`usage/session_2026-10-14_16.jsonl`). 그 가운데 약 240만 토큰은 행사와 원료 항목을 넣으며 10월 기사 2,048건 전체를 다시 정리한 몫이다.
- 매일 수집 Actions는 하루 약 45만~62만 토큰(약 900~1,200원)을 쓴다.
- gemini-3.5-flash-lite 비교(10월 기사 30건, 3.8-flash 결과 기준): 관련 여부 30/30, 분류 24/30, 사건 종류 23/30, 제품 23/31, 행사 날짜 9/9, 원료 21/35. 제품과 원료를 놓치는 비율이 높아 바꾸지 않는다. Flash-Lite 단가는 확인하지 않았다.
- 매일 수집의 3일 되읽기: 코스인코리아는 피드가 http, 지난 기사 목록이 https 링크라 같은 기사가 다른 id로 36건 저장되고 두 번 정리됐다. 수집 때 주소를 scheme과 www 없이 비교해 건너뛰게 고쳤다(`util.url_key`).
- 본문 입력 상한(6,000자)을 3,000자로 줄이면 10월 본문 1,198건 가운데 176건이 잘리고 입력이 약 25만 자 준다(전체 사용량의 4% 안팎). 효과가 작아 그대로 둔다.

## 10. 10월 수집 점검과 보충(2026-10-30)

10월 중간 리포트 전에 출처별·게시일별 기사 수를 표로 놓고 빈 곳을 하나씩 확인했다. 보충 전 4,080건, 보충 후 4,286건.

- **장업신문** 10/12, 10/19, 10/27의 2~4건은 빠진 것이 아니다. 날짜별 목록이 그날 '4건', '3건', '2건'으로 표시되고 저장된 수와 같다.
- **보충 수집**(`collect --backfill-since 2026-10-01 --naver-pages 10`): 국내 업계지 37건(대부분 10/29~30), 네이버 뉴스 149건, WWD 2건, PBN 1건. 네이버는 10/26에 58건, 10/27에 29건이 새로 들어왔다(그중 83건이 'K뷰티 수출'). 매일 수집이 검색어당 첫 쪽(100건)만 읽어 기사가 몰린 날 뒤쪽을 놓쳤다. 매일 루틴을 `--naver-pages 5`로 바꾸고, 추가 쪽은 백필 기간(사흘)보다 오래된 기사가 나오면 멈춘다.
- **Premium Beauty News**: 분야별 목록은 최근 30건만 보여 수집 시작(10/14) 전 기사가 비어 있었다. 기사 번호가 연속(`spip.php?article28282`)이라 28276~28445를 직접 열어 10월 영어 기사 14건을 더했다. 프랑스어판은 번호가 따로 있어 건너뛰었고, 28305와 28426은 첫 화면으로 돌아간다(지운 기사).
- **식약처**: 10/20~10/29 열흘 동안 세션과 Actions 모두 받지 못했다. Actions도 늘 되는 것은 아니다(10/30 05:47 예약 실행은 성공, 12:50 수동 실행은 네 게시판 모두 시간 초과).
  - 정책브리핑(korea.kr)이 식약처 보도자료를 그대로 싣는다. 목록 `briefing/pressReleaseList.do?repCodeType=D&repCode=A00027&startDate=…&endDate=…`(한 쪽 20건), 세션에서 받힌다. 본문은 첨부(hwpx, pdf)에만 있어 hwpx의 문단 글을 본문으로 썼다(pdf는 줄바꿈이 문장 중간에 들어가 인용이 어긋난다).
  - 10월 식약처 보도자료 72건 가운데 화장품 관련으로 빠진 것은 3건이었다. 10/8 K-뷰티 할랄 인증 세미나(제목에 '화장품'이 없어 제목 거르기에서 빠짐, '뷰티'를 거르기 단어에 추가), 10/20 「화장품의 점자 표시 등에 대한 가이드라인」 제정, 10/21 천연물 기반 화장품 원료 심포지엄. 링크는 정책브리핑 주소로 남겼다.
  - 고시와 행정예고는 정책브리핑에 없다. 네이버 뉴스 검색(화장품 행정예고, 화장품 고시 개정 등 8개 검색어)으로 10월 화장품 고시·행정예고 보도가 없음을 확인했다. 식약처 게시판 자체는 확인하지 못했다.
- **중복 저장**: 코스인코리아 10/14~15 기사 28건이 http와 https 주소로 두 번 저장돼 있다(9절의 수정 전 수집분). 리포트가 달의 기사를 읽을 때 url_key로 한 번만 센다(`normalize.load_month`). 행사는 기사 두 건 이상이 조건이라 중복이 그 조건을 혼자 채울 수 있었다. 백필도 url_key로 이미 받은 기사를 건너뛴다(이번 보충에서 코스인코리아 104건을 다시 연 원인).
- **수집 기록**: 같은 날 두 번째 실행이 첫 실행의 실패 기록을 남기고, 둘째 실행의 피드 결과가 '+backfill' 키에 덮였다. 이제 같은 키끼리 합친다(어느 한 번이라도 성공하면 그날은 성공, 새 기사 수는 더함). 날짜별 목록 하나가 실패하면 나머지 날짜를 모두 건너뛰던 것도 그날만 건너뛰게 고쳤다.

## 미확인 항목

1. 국내 업계지 5곳의 이용약관·저작권 정책(무단 전재 금지 조항이 자동 수집이나 요약 인용에 미치는 영향). robots.txt만 확인했다.
2. 올리브영·무신사 이용약관의 자동 수집 조항. 약관 페이지가 403/404라 원문을 보지 못했다. robots·차단만으로 이미 제외했으므로 판정에는 영향이 없다.
3. GCI의 robots.txt(Cloudflare 챌린지로 받지 못함).
4. BeautyMatter의 유료벽 범위와 새 기사 감지 방법(RSS·사이트맵 없음).
5. Cosmetics Business 프리미엄 기사의 본문 공개 범위.
6. CMN 목록·기사 페이지의 날짜 필드 위치(HTML 구조 미조사).
7. IFF 보도자료를 수집할 수 있는 경로(러너 IP 재확인, 보도자료 배포 서비스 경유).
8. ~~식약처 연결 리셋의 원인~~ → 해결: 세션 프록시 상태 기록(`ws_closed_mid_exchange`, mfds.go.kr·cdn.thebk.co.kr·cmn.co.kr)에 세션 프록시 터널이 끊긴 기록이 남아 있었다. 식약처 서버 문제가 아니며 러너에서도 재현되지 않았다. (2026-10-30 추가: 러너에서도 시간 초과가 한 번 났다. 10절 참고)
9. 관세청 API의 실제 응답, `hsSgn` 4자리 합산 여부, 품목 기준(국가 비필수) 대체 API의 존재. 서비스키가 필요하다.
10. 네이버 API HUB 검색 한도가 일 25,000인지 월 775,000인지(문서 간 불일치). 키 오류 시 401/403 응답 형식(헤더 직접 첨부는 러너에서 200 확인, 오류 응답은 미관찰).
11. Gemini 프로젝트의 결제 등급(유료 등급 여부). 응답 `serviceTier: standard`만으로는 판단할 수 없다. AI Studio 또는 Cloud 콘솔에서 결제 계정 연결 여부를 확인해야 한다.
12. FDA 404가 데이터센터 IP 일반 차단인지 GitHub 러너 대역 한정인지. Federal Register의 IP 차단 기준(요청 수·시간 창).
13. 업계지 기사에 향 노트가 명시되는 빈도(섹션 4의 n≥30 가능성).
