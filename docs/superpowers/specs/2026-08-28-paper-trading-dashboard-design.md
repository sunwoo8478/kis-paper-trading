# 국내주식 모의투자 대시보드 — 설계 문서

날짜: 2026-08-28

## 배경 / 목적

한국투자증권 Open API(`koreainvestment/open-trading-api`)를 활용해 국내주식(KOSPI/KOSDAQ) 모의투자 대시보드를 만든다. 실제 주식창처럼 보유종목/손익/자산추이 그래프를 확인할 수 있는 고퀄리티 개인용 웹앱. 향후 해외주식까지 확장 예정.

현재 사용자는 한국투자증권 계좌/API 앱키가 없는 상태다. 계좌 개설에는 시간이 걸리므로, 계좌 준비 전까지는 무료 공개 데이터(pykrx)와 자체 주문 시뮬레이션으로 개발을 진행하고, 계좌/앱키가 준비되면 데이터·주문 계층만 교체해 KIS API로 전환한다.

## 범위

- 사용자: 본인 전용 (1인, 로그인/계정 분리 없음)
- 대상 종목: KOSPI+KOSDAQ 전체 (수천 개), 검색/거래 전부 가능
- 1단계(현재): pykrx EOD 데이터 + 자체 주문 시뮬레이션 엔진
- 2단계(계좌 준비 후): KIS 모의투자(vps) 실시간 연동으로 데이터/주문 계층 교체
- 해외주식 확장은 이후 별도 스펙에서 다룬다 (이번 스펙 범위 아님)

## 아키텍처

```
[Next.js 프론트엔드] <--REST/WS--> [FastAPI 백엔드] --> [MarketDataProvider 인터페이스]
                                        |                  ├─ PykrxProvider (1단계, EOD)
                                        |                  └─ KisProvider (2단계, 실시간 WS+REST)
                                        |
                                   [OrderExecutor 인터페이스]
                                        |                  ├─ SimulatedExecutor (1단계, 자체 체결)
                                        |                  └─ KisPaperExecutor (2단계, 실제 vps 주문 API)
                                        |
                                   [SQLite]
```

`MarketDataProvider`, `OrderExecutor`는 인터페이스로 분리하고, `.env`의 `MARKET_DATA_PROVIDER` / `ORDER_EXECUTOR` 값으로 구현체를 주입한다. 백엔드 나머지 로직(포트폴리오 계산, DB, API 라우트)과 프론트엔드는 두 단계 모두 동일한 코드를 그대로 쓴다.

### 1단계 동작

- 종목 마스터 + 가격: pykrx로 매일 1회 KOSPI/KOSDAQ 전체 적재 (`get_market_ticker_list`, `get_market_ohlcv`)
- 주문 체결: 매수/매도 주문 시 해당 종목 최신 종가로 즉시 체결 (호가/장중 변동 없음 — 알려진 한계)
- 포트폴리오: 가상 초기자본 설정 → 체결마다 잔고/보유수량 갱신 → 주기적으로 잔고 스냅샷을 SQLite에 적재해 자산추이 그래프 생성
- 1단계에서 쌓인 체결/스냅샷 이력은 2단계 전환 후에도 유지 (DB가 이력의 단일 진실 공급원)

### 2단계 동작 (계좌 준비 후)

- `KisProvider`: 보유+관심종목은 WebSocket 실시간 구독, 전체 종목은 주기 REST 폴링(수초~수십초 간격, 레이트리밋 고려)
- `KisPaperExecutor`: KIS 모의투자(vps) 주문 API로 실제 가상계좌에 주문
- `kis_auth.py` 등 `open-trading-api` 인증/함수는 그대로 서브모듈/vendored 라이브러리로 사용
- 나중에 실전투자 전환도 설정값(svr=prod)만 바꾸면 됨 (이번 스펙 범위 밖, 참고용)

## 화면 구성

- **대시보드**: 총자산/평가손익 요약, 자산추이 라인차트(equity curve), 보유종목 테이블
- **종목검색/스크리너**: 전체 종목 테이블, 검색/정렬/필터
- **종목상세**: 캔들차트(lightweight-charts) + 매수/매도 주문폼 + 관심종목 토글
- **관심종목**: 리스트, 최신가 표시(2단계에서 실시간으로 전환)
- **주문내역**: 체결 이력 테이블

## 데이터 모델 (SQLite)

- `stocks` (code, name, market, sector, ...) — 종목 마스터
- `price_history` (code, date, open, high, low, close, volume) — OHLCV 캐시
- `watchlist` (code)
- `account` (cash_balance, initial_capital)
- `positions` (code, quantity, avg_price)
- `orders` (id, code, side, quantity, price, filled_at, status)
- `portfolio_snapshots` (timestamp, total_value, cash, evaluated_value, pnl)

## 에러 처리

- pykrx 스크래핑 실패/차단: 캐시된 마지막 데이터로 폴백 + 마지막 갱신시각 UI 표시, 백오프 재시도
- 시뮬레이션 주문: 잔고/보유수량 부족 시 400 반환, UI에 사유 노출
- (2단계) 토큰 만료 자동 재발급, KIS 레이트리밋(EGW00201) 백오프, WebSocket 끊김 시 재연결

## 테스트

- 포트폴리오 계산(평단가/손익) 로직 유닛테스트 (pytest)
- `MarketDataProvider`/`OrderExecutor`는 목(mock) 구현체로 단위테스트, 실제 pykrx 호출은 별도 통합테스트로 마킹
- 프론트엔드는 주요 페이지 스모크 테스트 수준 (이 단계에서 풀 e2e는 과함)

## 기술 스택

- 백엔드: Python, FastAPI, SQLite
- 프론트엔드: Next.js(React), lightweight-charts
- 데이터: pykrx (1단계), KIS Open API (2단계)
- 위치: `~/kis-paper-trading` (신규 독립 프로젝트, `open-trading-api`는 서브모듈/vendored 의존성으로 참조)
