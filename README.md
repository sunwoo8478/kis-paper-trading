# 국내주식 모의투자 대시보드 (KIS Paper Trading)

한국투자증권 Open API(`koreainvestment/open-trading-api`) 연동 전에 전략을 검증하는 KOSPI/KOSDAQ 자율 모의투자 웹앱. 시세 감시부터 AI 판단, 위험 제한, 모의 체결, 성과 기록까지 자동으로 반복한다.

## 구조

```
backend/    FastAPI + SQLite
frontend/   Next.js + shadcn/ui
docs/       설계 스펙 및 구현 계획 문서
```

## 현재 단계: 24시간 자율 모의운용

사용자 대시보드와 운영 주문은 한국투자증권 대회형 모의계좌만 사용한다. 로컬 체결 시뮬레이터는 화면과 운영 경로에서 분리하고 자동 테스트·백테스트용 내부 검증 엔진으로만 유지한다. 두 계좌의 주문·잔고·사이클 기록은 섞이지 않는다.

- **시세·시장 상태**: 네이버 증권 현재가와 장 상태를 사용하며, pykrx로 저장한 일봉은 워크포워드 검증에 사용한다.
- **자율 운용**: 서버 프로세스는 24시간 유지하고 정규장에 5분 간격으로 후보 분석, 로컬 EXAONE 판단, 위험 검증, 모의 체결을 수행한다. 장 종료·휴장 상태에서는 주문하지 않는다.
- **주문 체결**: 자체 시뮬레이션(`SimulatedExecutor`). 슬리피지·수수료·매도세를 반영한다.
- **안전장**: 종목당 최대 비중, 일일 손실 한도, 손절·수익보호, 주문 수 제한, 동일 종목 재주문 쿨다운을 코드에서 강제한다.
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

로컬 AI 코파일럿에서 Context7 최신 개발 문서를 사용하려면 다음 값을 추가한다. 일반 투자 질문에는 Context7를 호출하지 않으며, 채팅에서 `/docs next.js 질문` 또는 `/context7 /owner/repo 질문` 형식으로 요청할 때만 사용한다.

```
CONTEXT7_ENABLED=true
CONTEXT7_API_KEY=발급받은_키
```

종목 마스터 + 가격이력 적재 (전체 KOSPI+KOSDAQ ~2,700종목, 순차 처리라 느림 — 확인용으로는 일부만 로딩하는 것을 권장):

```bash
uv run --env-file .env python -m app.load_market_data
```

서버 실행:

```bash
uv run --env-file .env uvicorn app.main:app --reload --port 8000
```

자율운용 설정 예시:

```env
AI_AUTONOMOUS_ENABLED=true
AI_AUTONOMOUS_INTERVAL_SECONDS=300
AI_AUTONOMOUS_MAX_ORDERS_PER_CYCLE=10
AI_AUTONOMOUS_CASH_RESERVE_PCT=0
AI_AUTONOMOUS_COOLDOWN_MINUTES=60
AI_AUTONOMOUS_STOP_LOSS_PCT=5
AI_AUTONOMOUS_TAKE_PROFIT_PCT=12
AI_MAX_POSITION_PCT=20
AI_MAX_DAILY_LOSS_PCT=3
SIMULATED_SLIPPAGE_BPS=5
SIMULATED_COMMISSION_BPS=1.5
SIMULATED_SELL_TAX_BPS=15
```

시장 국면(`market_regime`)별 목표 투자비중 재정의 (기본값 아래와 동일, 낙폭에 따라 추가로 축소됨). `bearish`는 하락 국면 세분화 이전의 레거시 값이며, 하락 국면은 실제로는 낙폭·RSI에 따라 `correction`/`oversold`/`structural_decline`/`recession_rebalance` 중 하나로 분류된다:

```env
AI_BULLISH_TARGET_EXPOSURE_PCT=100
AI_NEUTRAL_TARGET_EXPOSURE_PCT=80
AI_CORRECTION_TARGET_EXPOSURE_PCT=60
AI_OVERSOLD_TARGET_EXPOSURE_PCT=50
AI_STRUCTURAL_DECLINE_TARGET_EXPOSURE_PCT=20
AI_RECESSION_REBALANCE_TARGET_EXPOSURE_PCT=0
AI_BEARISH_TARGET_EXPOSURE_PCT=20
```

아래 세 값은 기본적으로 비활성 상태이며, 실거래 유사 제약을 켜려면 명시적으로 설정해야 한다:

```env
AI_CANDIDATE_STALE_DAYS=9999
AI_CANDIDATE_MIN_AVG_TRADING_VALUE=0
SIMULATED_MAX_VOLUME_PARTICIPATION_PCT=0
```

### 한국투자증권 대회형 모의투자 연결

KIS 모의투자 계좌가 서비스의 유일한 사용자 계좌다. 로컬 시뮬레이션 계좌는 테스트와 백테스트에서만 사용한다.

```env
KIS_PAPER_APP_KEY=모의투자_앱키
KIS_PAPER_APP_SECRET=모의투자_앱시크릿
KIS_PAPER_ACCOUNT_NUMBER=모의계좌번호_앞8자리
KIS_PAPER_PRODUCT_CODE=01
KIS_PAPER_BASE_URL=https://openapivts.koreainvestment.com:29443
KIS_PAPER_ORDER_ENABLED=false
KIS_PAPER_AUTONOMOUS_ENABLED=false
KIS_PAPER_AUTONOMOUS_INTERVAL_SECONDS=300
KIS_PAPER_STRATEGY_MODE=competition_3m
KIS_PAPER_MAX_ORDERS_PER_CYCLE=10
KIS_PAPER_CANDIDATE_POOL_SIZE=30
KIS_PAPER_REJECTED_SYMBOL_LOOKBACK=50
KIS_PAPER_EXCLUDED_CODES=
KIS_COMPETITION_UNIVERSE_SIZE=200
KIS_COMPETITION_MIN_AVG_TRADING_VALUE=1000000000
KIS_COMPETITION_MIN_PRICE=1000
KIS_COMPETITION_MAX_20D_RETURN_PCT=120
KIS_COMPETITION_MAX_VOLATILITY_PCT=120
KIS_COMPETITION_MAX_POSITIONS=10
KIS_COMPETITION_MAX_POSITION_PCT=12
KIS_COMPETITION_BASE_POSITION_PCT=12
KIS_COMPETITION_HARD_STOP_PCT=6
KIS_COMPETITION_TRAILING_STOP_ATR=2.5
KIS_COMPETITION_DAILY_STOP_PCT=2.5
KIS_COMPETITION_MAX_DRAWDOWN_STOP_PCT=8
KIS_PAPER_MAX_POSITION_PCT=20
KIS_PAPER_STOP_LOSS_PCT=5
KIS_PAPER_TAKE_PROFIT_PCT=12
KIS_PAPER_COOLDOWN_MINUTES=60
KIS_PAPER_CASH_RESERVE_PCT=0
KIS_PAPER_MAX_VOLUME_PARTICIPATION_PCT=0
KIS_PAPER_ROTATION_SELL_SCORE=-1000
```

- `GET /kis/status?verify=true`: 앱 키 인증 및 연결 상태 확인
- `GET /kis/quote/{code}`: KIS 공식 현재가 조회
- `GET /kis/balance`: 모의계좌 잔고 조회
- `GET /kis/history`: KIS 전용 자산 스냅샷 조회
- `GET /kis/broker-orders`: 당일 KIS 주문·체결·미체결 조회 및 내부 주문 대사
- `GET /kis/orders`: 별도 저장된 KIS 주문 이력
- `GET /kis/autonomous/status`: KIS 자동매매 상태와 최근 사이클 조회
- `POST /kis/autonomous/start`, `/stop`, `/run`: KIS 자동매매 시작·중지·즉시 실행
- `GET /kis/autonomous/cycles`: KIS 자동매매 사이클 이력

계좌번호가 없거나 `KIS_PAPER_ORDER_ENABLED=false`이면 KIS 주문은 항상 차단된다. `KIS_PAPER_AUTONOMOUS_ENABLED`는 엔진의 최초 상태만 정하며, 이후 시작·중지 상태는 DB에 유지된다. 엔진은 당일 미체결 주문이 있으면 해당 종목의 중복 주문만 막고, KIS 실시간 주문가능금액 범위에서 다른 후보의 주문은 계속한다. 먼저 조회와 잔고 대사를 검증한 후에만 주문 전송을 활성화한다.

`KIS_PAPER_CANDIDATE_POOL_SIZE`는 AI가 한 사이클에서 비교할 기술 후보 수다. KIS가 매매 불가로 거절한 종목은 최근 `KIS_PAPER_REJECTED_SYMBOL_LOOKBACK`개 사이클 동안 자동 제외하며, 운영자가 항상 제외할 종목은 `KIS_PAPER_EXCLUDED_CODES`에 쉼표로 구분해 지정할 수 있다. `KIS_PAPER_MAX_VOLUME_PARTICIPATION_PCT`는 종목의 평균 거래량 대비 1회 주문 수량 상한이며 기본값 0은 비활성(무제한)이다. 값이 없으면 시장가 주문이 실제 유동성보다 커서 대량 미체결로 남아 이후 사이클 전체를 막을 수 있다. `KIS_PAPER_ROTATION_SELL_SCORE`는 손절·익절 기준에 못 미쳐도 보유 종목의 기술점수가 이 값 이하로 약화되면 선제적으로 매도해 다른 후보로 로테이션하며, 기본값 -1000은 사실상 비활성이다.

`KIS_PAPER_STRATEGY_MODE=competition_3m`은 3개월 원시 수익률 대회용 모드다. 최근 5·20·60일 상대모멘텀, 위험조정 모멘텀, 거래량 가속과 20일 신고가 접근도를 결합하고 시장 전체 상승 비율·20일선 상단 비율로 목표 투자비중을 0~100% 사이에서 조절한다. 종목별 변동성에 따라 5~12% 수준으로 크기를 조절하며 최대 10종목, 6% 초기 손실 제한, 2.5 ATR 추적손절을 사용한다. 일간 -2.5% 또는 계좌 최대낙폭 -8%에 도달하면 목표 투자비중을 0%로 낮춘다. 매 거래일 첫 분석 전에 직전 완료 거래일의 KOSPI·KOSDAQ 전체 일봉을 일괄 갱신한다. 검증은 `GET /kis/autonomous/backtest/competition?days=60&universe=200`으로 실행한다.

정상 장중에는 현금 보유 목표를 0%로 두고 종목당 최대 비중 안에서 가용 현금을 전액 분산한다. 체결 단위와 거래 비용 때문에 생기는 소액 잔액만 남는다. 운용 상태와 최근 사이클은 `/agent/autonomous/status`, `/agent/autonomous/cycles`에서 확인한다. 시작·중지·즉시 분석은 각각 `/agent/autonomous/start`, `/stop`, `/run`, 저장된 일봉 워크포워드 검증은 `POST /agent/autonomous/backtest?days=60&universe=50`을 사용한다.

AI 전용 성과 실험은 `POST /agent/experiment/start`로 기존 상태를 내부 보관한 뒤 새 초기자본에서 시작하고, `GET /agent/experiment`에서 실험 수익률·최대 낙폭·KOSPI 대비 초과수익을 확인한다. 현재 macOS 환경에서는 `ops/com.kis-paper-trading.backend.plist`가 LaunchAgent로 등록되어 로그인 후 자동 시작, 장애 시 재시작, 운용 중 유휴 절전 방지를 담당한다. 상태는 `/health`와 `launchctl print gui/501/com.kis-paper-trading.backend`로 확인한다.

테스트:

```bash
uv run pytest tests/ -v
```

## 프론트엔드 실행

프론트엔드는 `main` 브랜치의 `frontend/`에 포함되어 있다. 대시보드, 주문내역, 리스크, 종목 주문창과 AI 코파일럿은 모두 KIS 모의계좌만 사용한다.

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
