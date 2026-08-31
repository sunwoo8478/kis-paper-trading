"use client";

import Link from "next/link";
import useSWR from "swr";
import { getMarketOverview } from "@/lib/api";
import { changeColorClass, formatChangePct } from "@/lib/format";

export function MarketTape() {
  const market = useSWR("/api/market/overview", getMarketOverview, { refreshInterval: 15000, revalidateOnFocus: false });
  const movers = [
    ...(market.data?.rankings.gainers.slice(0, 2) ?? []),
    ...(market.data?.rankings.losers.slice(0, 2) ?? []),
  ];

  return (
    <div className="border-b border-border bg-muted/25">
      <div className="mx-auto flex h-9 max-w-[1760px] items-center gap-5 overflow-x-auto px-4 text-[10px] sm:px-6 xl:px-8">
        <Link href="/market" className="shrink-0 font-medium text-foreground hover:underline">시장 현황</Link>
        {(market.data?.indices ?? []).map((index) => (
          <div key={index.symbol} className="flex shrink-0 items-center gap-2 border-l border-border pl-5">
            <span className="text-muted-foreground">{index.name}</span>
            <span className="font-mono font-medium">{index.price?.toLocaleString("ko-KR") ?? "-"}</span>
            <span className={`font-mono ${changeColorClass(index.change_pct)}`}>{formatChangePct(index.change_pct)}</span>
          </div>
        ))}
        <div className="h-3 w-px shrink-0 bg-border" />
        {movers.map((stock) => (
          <Link key={`${stock.code}-${stock.change_pct}`} href={`/stocks/${stock.code}`} className="flex shrink-0 items-center gap-2 hover:text-foreground">
            <span className="text-muted-foreground">{stock.name}</span>
            <span className={`font-mono ${changeColorClass(stock.change_pct)}`}>{formatChangePct(stock.change_pct)}</span>
          </Link>
        ))}
        <span className="ml-auto shrink-0 text-muted-foreground">{market.isLoading ? "시장 데이터 불러오는 중" : market.error ? "시장 데이터 연결 확인" : "15초 갱신"}</span>
      </div>
    </div>
  );
}
