# 국내주식 모의투자 대시보드 (KIS Paper Trading)

한국투자증권 Open API(`koreainvestment/open-trading-api`)를 활용할 예정인 KOSPI/KOSDAQ 모의투자 웹앱. 실제 주식창처럼 보유종목·손익·자산추이·현재가/등락률을 보여주고, 매수/매도 시뮬레이션이 가능하다.

## 구조

```
backend/    FastAPI + SQLite (완료, main에 병합됨)
frontend/   Next.js + shadcn/ui (worktree-frontend-dashboard 브랜치, 아직 main 미병합)
docs/       설계 스펙 및 구현 계획 문서
```

## 현재 단계 (Stage 1)

한국투자증권 계좌가 아직 없어서, 계좌 준비 전까지는 무료 데이터로 개발 중이다.

- **시세**: [pykrx](https://github.com/sharebook-kr/pykrx)로 가져오는 EOD(장마감 후 일별) 데이터. 실시간 아님 — 하루 한 번 갱신되는 값.
- **주문 체결**: 자체 시뮬레이션(`SimulatedExecutor`). 매수/매도 시 최신 종가로 즉시 체결.
- **확장 설계**: `MarketDataProvider` / `OrderExecutor` 인터페이스로 분리되어 있어, 나중에 KIS 계좌가 준비되면 실시간 구현체로 갈아끼우기만 하면 됨(다른 코드 변경 불필요).

## 백엔드 실행

```bash
cd backend
uv sync
```

`backend/.env` 파일을 만들고 KRX 계정 정보를 채운다 (data.krx.co.kr 무료 가입 필요 — pykrx가 2026년 로그인 정책 변경으로 이 값이 없으면 시세를 못 가져옴):

```
KRX_ID=본인_아이디
KRX_PW=본인_비밀번호
```

`.env`는 `.gitignore`에 포함되어 커밋되지 않는다. 절대 코드나 커밋에 직접 넣지 말 것.

종목 마스터 + 가격이력 적재 (전체 KOSPI+KOSDAQ ~2,700종목, 순차 처리라 느림 — 확인용으로는 일부만 로딩하는 것을 권장):

```bash
uv run --env-file .env python -m app.load_market_data
```

서버 실행:

```bash
uv run --env-file .env uvicorn app.main:app --reload --port 8000
```

테스트:

```bash
uv run pytest tests/ -v
```

## 프론트엔드 실행

현재 `worktree-frontend-dashboard` 브랜치에 있다 (`git checkout worktree-frontend-dashboard`, 또는 main 병합 후).

```bash
cd frontend
npm install
npm run dev -- --port 3000
```

`http://localhost:3000` — 백엔드(`:8000`)가 먼저 떠 있어야 한다. `next.config.ts`의 rewrites가 `/api/*` 요청을 백엔드로 프록시한다.

## 화면

- `/` 대시보드 — 총자산/평가손익, 자산추이 그래프, 보유종목
- `/screener` 종목검색 — 전체 종목 + 현재가/전일대비
- `/stocks/[code]` 종목상세 — 캔들차트, 현재가, 보유수량, 매수/매도(확인 다이얼로그 포함)
- `/watchlist` 관심종목
- `/orders` 주문내역

## 문서

- [설계 스펙](docs/superpowers/specs/) — 백엔드/프론트엔드 설계 문서
- [구현 계획](docs/superpowers/plans/) — 백엔드 TDD 구현 계획
