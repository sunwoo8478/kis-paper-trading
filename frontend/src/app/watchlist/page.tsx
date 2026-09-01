"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { getWatchlist, removeFromWatchlist, ApiError } from "@/lib/api";
import { formatPrice, formatChangePct, changeColorClass } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { RefreshBadge } from "@/components/refresh-badge";
import { cn } from "@/lib/utils";

type SortKey = "change" | "price" | "name";

export default function WatchlistPage() {
  const watchlist = useSWR("/api/watchlist", getWatchlist, { refreshInterval: 10000 });
  const [sort, setSort] = useState<SortKey>("change");
  const rows = useMemo(() => {
    const source = [...(watchlist.data ?? [])];
    return source.sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name, "ko");
      if (sort === "price") return (b.last_price ?? 0) - (a.last_price ?? 0);
      return Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0);
    });
  }, [sort, watchlist.data]);
  const advancers = rows.filter((stock) => (stock.change_pct ?? 0) > 0).length;
  const decliners = rows.filter((stock) => (stock.change_pct ?? 0) < 0).length;
  const averageChange = rows.length ? rows.reduce((sum, stock) => sum + (stock.change_pct ?? 0), 0) / rows.length : 0;

  const handleRemove = async (code: string) => {
    try {
      await removeFromWatchlist(code);
      watchlist.mutate();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "관심종목 삭제 실패");
    }
  };

  return (
    <div className="space-y-8">
      <section className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Watchlist</p>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">관심종목</h1>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">관심 유니버스의 방향성과 변동 폭을 빠르게 비교합니다.</p>
        </div>
        <RefreshBadge
          hasError={Boolean(watchlist.error)}
          isValidating={watchlist.isValidating}
          onRefresh={() => watchlist.mutate()}
        />
      </section>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <WatchMetric label="관심 유니버스" value={`${rows.length}종목`} />
        <WatchMetric label="상승" value={`${advancers}종목`} tone="text-red-500" />
        <WatchMetric label="하락" value={`${decliners}종목`} tone="text-blue-500" />
        <WatchMetric label="평균 등락률" value={formatChangePct(averageChange)} tone={changeColorClass(averageChange)} />
      </section>

      <div className="flex justify-end">
        <div className="flex rounded-lg border border-border bg-card p-0.5">
          {(["change", "price", "name"] as SortKey[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setSort(item)}
              className={cn("rounded-md px-3 py-1.5 text-xs transition", sort === item ? "bg-muted font-medium" : "text-muted-foreground")}
            >
              {item === "change" ? "변동성순" : item === "price" ? "가격순" : "이름순"}
            </button>
          ))}
        </div>
      </div>

      <Card className="border-border bg-card shadow-sm">
        <CardHeader className="border-b bg-muted/40">
          <CardTitle>목록</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>종목코드</TableHead>
                <TableHead>종목명</TableHead>
                <TableHead className="text-right">현재가</TableHead>
                <TableHead className="text-right">전일대비</TableHead>
                <TableHead className="text-right">관리</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-10 text-center text-muted-foreground">
                    관심종목 없음
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((stock) => (
                  <TableRow key={stock.code}>
                    <TableCell>
                      <Link href={`/stocks/${stock.code}`} className="font-medium text-foreground hover:underline">
                        {stock.code}
                      </Link>
                    </TableCell>
                    <TableCell>{stock.name}</TableCell>
                    <TableCell className="text-right">{formatPrice(stock.last_price)}</TableCell>
                    <TableCell className={`text-right ${changeColorClass(stock.change_pct)}`}>
                      {formatChangePct(stock.change_pct)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="outline" size="sm" onClick={() => handleRemove(stock.code)}>
                        삭제
                      </Button>
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

function WatchMetric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className={`mt-1 font-mono text-sm font-medium ${tone ?? ""}`}>{value}</p>
    </div>
  );
}
