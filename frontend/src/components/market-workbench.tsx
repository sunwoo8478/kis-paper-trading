"use client";

import Link from "next/link";
import useSWR from "swr";
import { ArrowDownRight, ArrowUpRight, Building2, RefreshCw } from "lucide-react";
import { getMarketOverview, type RankedStock } from "@/lib/api";
import { changeColorClass, formatChangePct, formatPrice } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function MarketWorkbench({ expanded = false, className }: { expanded?: boolean; className?: string }) {
  const market = useSWR("/api/market/overview", getMarketOverview, { refreshInterval: 15000, revalidateOnFocus: false });
  const limit = expanded ? 8 : 6;

  return (
    <section className={cn("overflow-hidden rounded-xl border border-border bg-card shadow-sm", className)}>
      <header className="flex flex-col gap-4 border-b border-border px-4 py-3.5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-sm font-semibold">실시간 시장 스캐너</h2>
          <p className="mt-0.5 text-[10px] text-muted-foreground">코스피·코스닥 통합 순위, 15초 자동 갱신</p>
        </div>
        <div className="flex items-center gap-5">
          {(market.data?.indices ?? []).map((index) => (
            <div key={index.symbol} className="flex items-baseline gap-2">
              <span className="text-[10px] text-muted-foreground">{index.name}</span>
              <span className="font-mono text-sm font-medium">{index.price?.toLocaleString("ko-KR") ?? "-"}</span>
              <span className={`font-mono text-[10px] ${changeColorClass(index.change_pct)}`}>{formatChangePct(index.change_pct)}</span>
            </div>
          ))}
          <Button variant="ghost" size="icon-sm" onClick={() => market.mutate()} aria-label="시장 순위 새로고침">
            <RefreshCw className={cn("h-3.5 w-3.5", market.isValidating && "animate-spin")} />
          </Button>
        </div>
      </header>

      {market.isLoading ? (
        <div className="grid lg:grid-cols-3">{Array.from({ length: 3 }).map((_, index) => <div key={index} className="h-80 animate-pulse border-r border-border bg-muted/20 last:border-r-0" />)}</div>
      ) : market.error ? (
        <div className="px-5 py-12 text-center text-sm text-muted-foreground">시장 데이터를 불러오지 못했습니다. 새로고침 후 다시 확인해 주세요.</div>
      ) : (
        <div className="grid divide-y divide-border lg:grid-cols-3 lg:divide-x lg:divide-y-0">
          <RankTable title="상승률" rows={market.data?.rankings.gainers.slice(0, limit) ?? []} mode="change" />
          <RankTable title="하락률" rows={market.data?.rankings.losers.slice(0, limit) ?? []} mode="change" />
          <RankTable title="시가총액" rows={market.data?.rankings.market_cap.slice(0, limit) ?? []} mode="marketCap" />
        </div>
      )}
    </section>
  );
}

function RankTable({ title, rows, mode }: { title: string; rows: RankedStock[]; mode: "change" | "marketCap" }) {
  return (
    <div>
      <div className="flex items-center justify-between border-b border-border bg-muted/25 px-4 py-2.5">
        <p className="text-xs font-medium">{title}</p>
        <span className="text-[9px] text-muted-foreground">KOSPI + KOSDAQ</span>
      </div>
      <div className="px-2 py-1">
        {rows.map((stock, index) => (
          <Link key={stock.code} href={`/stocks/${stock.code}`} className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 py-2 transition hover:bg-muted/50 active:translate-y-px">
            <span className="font-mono text-[9px] text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{stock.name}</p>
              <p className="mt-0.5 font-mono text-[9px] text-muted-foreground">{stock.code} {stock.market}</p>
            </div>
            <div className="text-right">
              <p className="font-mono text-[11px]">{formatPrice(stock.price)}</p>
              {mode === "change" ? (
                <p className={`mt-0.5 flex items-center justify-end gap-0.5 font-mono text-[9px] ${changeColorClass(stock.change_pct)}`}>
                  {(stock.change_pct ?? 0) >= 0 ? <ArrowUpRight className="h-2.5 w-2.5" /> : <ArrowDownRight className="h-2.5 w-2.5" />}
                  {formatChangePct(stock.change_pct)}
                </p>
              ) : (
                <p className="mt-0.5 flex items-center justify-end gap-1 text-[9px] text-muted-foreground"><Building2 className="h-2.5 w-2.5" />{compactWon(stock.market_value)}</p>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function compactWon(value: number | null) {
  if (value === null) return "-";
  return `${new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 }).format(value)}원`;
}
