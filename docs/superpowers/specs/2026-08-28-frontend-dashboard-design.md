# 국내주식 모의투자 대시보드 — 프론트엔드 설계 문서

날짜: 2026-08-28

## 배경 / 목적

백엔드([2026-08-28-paper-trading-dashboard-design.md](2026-08-28-paper-trading-dashboard-design.md), 구현 완료 후 `main`에 병합됨)가 제공하는 REST API(`GET /stocks`, `GET /stocks/{code}/history`, `GET/POST/DELETE /watchlist`, `POST/GET /orders`, `GET /portfolio`, `GET /portfolio/history`)를 소비하는 웹 대시보드를 만든다. 실제 주식창처럼 보유종목/손익/자산추이 그래프를 확인하고 매수/매도할 수 있는 화면.

UI는 깔끔함을 목표로 하되 디자인적 완성도(브랜딩, 커스텀 비주얼 등)는 신경쓰지 않는다 — shadcn/ui 기본 컴포넌트를 그대로 사용해 빠르게 구현한다.

## 범위

- 5개 화면 한 번에 구현: 대시보드, 종목검색, 종목상세, 관심종목, 주문내역
- 데이터 갱신: 10초 주기 자동 폴링 + 수동 새로고침 버튼
- 백엔드는 현재 1단계(pykrx EOD 데이터 + 자체 시뮬레이션 체결) — 프론트는 이 API를 그대로 소비하며, 나중에 백엔드가 2단계(KIS 실시간)로 바뀌어도 API 계약(엔드포인트/응답 형태)이 동일하므로 프론트 코드 변경 불필요
- 해외주식 확장은 범위 밖

## 아키텍처

```
Next.js (App Router, :3000) --fetch--> Next.js rewrites 프록시 (/api/*) --> FastAPI (:8000)
```

CORS 설정 없이 Next.js의 `rewrites`로 `/api/*` 요청을 백엔드로 프록시한다. 백엔드 코드는 건드리지 않는다.

## 데이터 갱신 전략

[SWR](https://swr.vercel.app/) 라이브러리 사용. 각 페이지의 데이터 훅에 `refreshInterval: 10000`(10초) 설정. 폴링/캐싱/재시도는 SWR이 처리하며 직접 구현하지 않는다. 각 화면에 수동 새로고침 버튼을 두어 `mutate()`로 즉시 재조회 가능하게 한다.

## 화면 구성 (Next.js App Router 라우트)

- `/` 대시보드 — 총자산/평가손익 요약 카드, 자산추이 라인차트(`GET /portfolio/history`), 보유종목 테이블(`GET /portfolio`)
- `/screener` 종목검색 — 전체 종목 테이블 + 검색바(`GET /stocks?q=`)
- `/stocks/[code]` 종목상세 — 캔들차트(`GET /stocks/{code}/history`, lightweight-charts) + 매수/매도 폼(`POST /orders`) + 관심종목 토글(`POST/DELETE /watchlist`)
- `/watchlist` 관심종목 — 관심종목 리스트(`GET /watchlist`) + 각 종목 최신가
- `/orders` 주문내역 — 체결 이력 테이블(`GET /orders`)

## 컴포넌트

Tailwind CSS + shadcn/ui의 기본 컴포넌트(Table, Card, Button, Dialog, Badge, Input, Toast)를 그대로 사용한다. 커스텀 CSS/디자인 작업은 최소화한다.

## 에러 처리

- SWR 페치 실패: 화면에 "마지막 갱신 실패, n초 전 데이터" 배지 표시, 기존 캐시 데이터는 그대로 보여줌
- 주문 실패(백엔드 400 응답, 예: 잔고 부족/보유수량 부족/시세조회 실패): Toast로 에러 메시지(`detail` 필드) 노출
- 존재하지 않는 종목 코드로 `/stocks/[code]` 접근: 404 처리

## 테스트

- 컴포넌트 단위 테스트는 하지 않는다(고퀄리티 UI가 아니라 동작 확인이 목표이므로 시각적 확인이 더 유효함)
- 각 페이지 최소 1개 스모크 테스트(Playwright)로 페이지 로드 + 핵심 데이터 렌더 확인
- 매수/매도 주문 흐름 1개 E2E 테스트(종목상세 페이지에서 주문 → 대시보드에 반영 확인)

## 기술 스택

- Next.js (App Router), TypeScript
- Tailwind CSS + shadcn/ui
- SWR (데이터 페칭/폴링)
- lightweight-charts (캔들차트, 자산추이 라인차트)
- Playwright (스모크/E2E 테스트)
- 위치: `~/kis-paper-trading/frontend` (백엔드와 같은 저장소, 별도 디렉토리)
