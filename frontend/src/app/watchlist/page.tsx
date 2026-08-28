"use client";

import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { getWatchlist, removeFromWatchlist, ApiError } from "@/lib/api";
import { formatPrice, formatChangePct, changeColorClass } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { RefreshBadge } from "@/components/refresh-badge";

export default function WatchlistPage() {
  const watchlist = useSWR("/api/watchlist", getWatchlist, { refreshInterval: 10000 });

  const handleRemove = async (code: string) => {
    try {
      await removeFromWatchlist(code);
      watchlist.mutate();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "관심종목 삭제 실패");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">관심종목</h1>
        <RefreshBadge
          hasError={Boolean(watchlist.error)}
          isValidating={watchlist.isValidating}
          onRefresh={() => watchlist.mutate()}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>관심종목 목록</CardTitle>
        </CardHeader>
        <CardContent>
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
              {(watchlist.data ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    관심종목 없음
                  </TableCell>
                </TableRow>
              )}
              {(watchlist.data ?? []).map((stock) => (
                <TableRow key={stock.code}>
                  <TableCell>
                    <Link href={`/stocks/${stock.code}`} className="text-blue-600 hover:underline">
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
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
