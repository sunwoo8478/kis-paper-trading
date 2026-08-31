"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { Search } from "lucide-react";
import { searchStocks } from "@/lib/api";
import { formatPrice, formatChangePct, changeColorClass } from "@/lib/format";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RefreshBadge } from "@/components/refresh-badge";
import { cn } from "@/lib/utils";

type MarketFilter = "ALL" | "KOSPI" | "KOSDAQ";
type SortKey = "change" | "price" | "name";

export default function ScreenerPage() {
  const [query, setQuery] = useState("");
  const [market, setMarket] = useState<MarketFilter>("ALL");
  const [sort, setSort] = useState<SortKey>("change");
  const stocks = useSWR(["/api/stocks", query], () => searchStocks(query), {
    refreshInterval: 10000,
  });

  const results = useMemo(() => {
    const rows = (stocks.data ?? []).filter((stock) => market === "ALL" || stock.market === market);
    return rows.sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name, "ko");
      if (sort === "price") return (b.last_price ?? 0) - (a.last_price ?? 0);
      return Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0);
    });
  }, [market, sort, stocks.data]);
  const advancers = results.filter((stock) => (stock.change_pct ?? 0) > 0).length;
  const decliners = results.filter((stock) => (stock.change_pct ?? 0) < 0).length;

  return (
    <div className="space-y-8">
      <section className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Screener</p>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">종목 스크리너</h1>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
              시장, 변동 폭, 가격 기준으로 유니버스를 좁혀 분석 대상을 찾습니다.
            </p>
          </div>
          <RefreshBadge
            hasError={Boolean(stocks.error)}
            isValidating={stocks.isValidating}
            onRefresh={() => stocks.mutate()}
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              placeholder="종목코드 또는 종목명"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-12 rounded-xl border-border bg-card pl-11 shadow-sm"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {["삼성", "SK", "NAVER", "카카오"].map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setQuery(preset)}
                className="rounded-full border border-border bg-card px-3 py-2 text-sm text-muted-foreground transition hover:text-foreground"
              >
                {preset}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-2">
          {(["ALL", "KOSPI", "KOSDAQ"] as MarketFilter[]).map((item) => (
            <button key={item} type="button" onClick={() => setMarket(item)} className={cn("rounded-lg px-3 py-1.5 text-xs transition", market === item ? "bg-foreground text-background" : "bg-muted text-muted-foreground")}>
              {item === "ALL" ? "전체 시장" : item}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">상승 {advancers} · 하락 {decliners}</span>
          <span className="mx-1 h-4 w-px bg-border" />
          {(["change", "price", "name"] as SortKey[]).map((item) => (
            <button key={item} type="button" onClick={() => setSort(item)} className={cn("rounded-md px-2 py-1", sort === item ? "bg-muted font-medium" : "text-muted-foreground")}>
              {item === "change" ? "변동성" : item === "price" ? "가격" : "이름"}
            </button>
          ))}
        </div>
      </section>

      <Card className="border-border bg-card shadow-sm">
        <CardHeader className="border-b bg-muted/40">
          <CardTitle>검색 결과</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>종목코드</TableHead>
                <TableHead>종목명</TableHead>
                <TableHead>시장</TableHead>
                <TableHead className="text-right">현재가</TableHead>
                <TableHead className="text-right">전일 종가</TableHead>
                <TableHead className="text-right">전일대비</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {results.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                    검색 결과 없음
                  </TableCell>
                </TableRow>
              ) : (
                results.map((stock) => (
                  <TableRow key={stock.code}>
                    <TableCell>
                      <Link href={`/stocks/${stock.code}`} className="font-medium text-foreground hover:underline">
                        {stock.code}
                      </Link>
                    </TableCell>
                    <TableCell>{stock.name}</TableCell>
                    <TableCell className="text-muted-foreground">{stock.market}</TableCell>
                    <TableCell className="text-right">{formatPrice(stock.last_price)}</TableCell>
                    <TableCell className="text-right text-muted-foreground">{formatPrice(stock.prev_close)}</TableCell>
                    <TableCell className={`text-right ${changeColorClass(stock.change_pct)}`}>
                      {formatChangePct(stock.change_pct)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
