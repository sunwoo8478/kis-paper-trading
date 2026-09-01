"use client";

import Image from "next/image";
import useSWR from "swr";
import { useState } from "react";
import { ArrowUpRight, ChevronLeft, ChevronRight, ImageIcon, Newspaper, RefreshCw } from "lucide-react";
import { getMarketNews, getMarketOverview, getStockNews, type NewsItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function MarketNewsPanel({ codes = [], stockCode, compact = false, marketMode = false, className }: { codes?: string[]; stockCode?: string; compact?: boolean; marketMode?: boolean; className?: string }) {
  const [page, setPage] = useState(1);
  const pageSize = compact ? 6 : 12;
  const overview = useSWR(marketMode ? "/api/market/overview:news" : null, getMarketOverview, { refreshInterval: 60000, revalidateOnFocus: false });
  const marketCodes = marketMode
    ? [...(overview.data?.rankings.market_cap.slice(0, 3) ?? []), ...(overview.data?.rankings.gainers.slice(0, 3) ?? [])].map((item) => item.code)
    : codes;
  const key = stockCode
    ? ["/api/stocks/news", stockCode, page]
    : marketMode && marketCodes.length === 0 ? null : ["/api/news", [...marketCodes].sort().join(","), page];
  const news = useSWR(key, () => stockCode ? getStockNews(stockCode, pageSize, page) : getMarketNews(marketCodes, pageSize, page), {
    refreshInterval: 60000,
    revalidateOnFocus: false,
  });
  const items = news.data ?? [];

  return (
    <section className={cn("flex overflow-hidden rounded-xl border border-border bg-card shadow-sm", "flex-col", className)}>
      <header className="flex items-center justify-between gap-4 border-b border-border px-4 py-3.5">
        <div className="flex items-center gap-2.5">
          <Newspaper className="h-4 w-4 text-muted-foreground" />
          <div>
            <h2 className="text-sm font-semibold">{stockCode ? "종목 뉴스" : marketMode ? "시장 뉴스" : "보유 종목 뉴스"}</h2>
            <p className="text-[10px] text-muted-foreground">{stockCode ? `${stockCode} 관련 최신 기사` : marketMode ? "시가총액과 상승률 상위 종목 중심" : "포트폴리오 종목 중심 최신 기사"}</p>
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          <Button variant="ghost" size="icon-sm" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page === 1} aria-label="이전 뉴스 페이지"><ChevronLeft className="h-3.5 w-3.5" /></Button>
          <span className="min-w-8 text-center font-mono text-[9px] text-muted-foreground">{page}</span>
          <Button variant="ghost" size="icon-sm" onClick={() => setPage((value) => value + 1)} disabled={!news.isLoading && items.length < pageSize} aria-label="다음 뉴스 페이지"><ChevronRight className="h-3.5 w-3.5" /></Button>
          <Button variant="ghost" size="icon-sm" onClick={() => news.mutate()} aria-label="뉴스 새로고침"><RefreshCw className={cn("h-3.5 w-3.5", news.isValidating && "animate-spin")} /></Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
        {news.isLoading || (marketMode && overview.isLoading) ? (
          Array.from({ length: compact ? 4 : 6 }).map((_, index) => (
            <div key={index} className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 px-4 py-3">
              <div className="aspect-[4/3] animate-pulse bg-muted/50" />
              <div className="space-y-2 py-1"><div className="h-2 w-2/5 animate-pulse bg-muted/50" /><div className="h-3 w-full animate-pulse bg-muted/50" /><div className="h-3 w-3/4 animate-pulse bg-muted/50" /></div>
            </div>
          ))
        ) : items.length === 0 ? (
          <div className="px-5 py-10 text-center">
            <p className="text-sm font-medium">표시할 뉴스가 없습니다.</p>
            <p className="mt-1 text-xs text-muted-foreground">뉴스 제공처 연결 상태를 확인하거나 잠시 후 새로고침해 주세요.</p>
          </div>
        ) : (
          items.slice(0, pageSize).map((item) => (
            <a
              key={`${item.code}-${item.id}`}
              href={item.url || undefined}
              target="_blank"
              rel="noreferrer"
              className={cn(
                "group grid min-h-[76px] items-center gap-3 px-4 py-3 transition hover:bg-muted/40",
                item.image_url ? "grid-cols-[72px_minmax(0,1fr)_auto]" : "grid-cols-[minmax(0,1fr)_auto]",
              )}
            >
              {item.image_url && <NewsThumbnail item={item} />}
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                  <span className="font-mono">{item.code}</span>
                  <span>{item.source}</span>
                  <time>{formatNewsTime(item.published_at)}</time>
                </div>
                <p className="mt-1 line-clamp-2 text-sm font-medium leading-5 text-foreground">{item.title}</p>
                {!compact && item.summary && <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{item.summary}</p>}
              </div>
              <ArrowUpRight className="mt-1 h-3.5 w-3.5 text-muted-foreground transition group-hover:text-foreground" />
            </a>
          ))
        )}
      </div>
    </section>
  );
}

function NewsThumbnail({ item }: { item: NewsItem }) {
  const [failed, setFailed] = useState(false);

  return (
    <div className="relative aspect-[4/3] overflow-hidden border border-border bg-muted/40">
      <ImageIcon className="absolute left-1/2 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 text-muted-foreground/50" />
      {!failed && item.image_url && (
        <Image
          src={item.image_url}
          alt=""
          fill
          sizes="72px"
          className="object-cover transition duration-200 group-hover:scale-[1.03]"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}

function formatNewsTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
