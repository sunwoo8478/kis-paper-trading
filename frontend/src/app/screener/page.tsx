"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { searchStocks } from "@/lib/api";
import { formatPrice, formatChangePct, changeColorClass } from "@/lib/format";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RefreshBadge } from "@/components/refresh-badge";

export default function ScreenerPage() {
  const [query, setQuery] = useState("");
  const stocks = useSWR(["/api/stocks", query], () => searchStocks(query), {
    refreshInterval: 10000,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">종목검색</h1>
        <RefreshBadge
          hasError={Boolean(stocks.error)}
          isValidating={stocks.isValidating}
          onRefresh={() => stocks.mutate()}
        />
      </div>

      <Input
        placeholder="종목코드 또는 종목명 검색"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      <Card>
        <CardHeader>
          <CardTitle>검색 결과</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>종목코드</TableHead>
                <TableHead>종목명</TableHead>
                <TableHead>시장</TableHead>
                <TableHead className="text-right">현재가</TableHead>
                <TableHead className="text-right">전일대비</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(stocks.data ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    검색 결과 없음
                  </TableCell>
                </TableRow>
              )}
              {(stocks.data ?? []).map((stock) => (
                <TableRow key={stock.code}>
                  <TableCell>
                    <Link href={`/stocks/${stock.code}`} className="text-blue-600 hover:underline">
                      {stock.code}
                    </Link>
                  </TableCell>
                  <TableCell>{stock.name}</TableCell>
                  <TableCell>{stock.market}</TableCell>
                  <TableCell className="text-right">{formatPrice(stock.last_price)}</TableCell>
                  <TableCell className={`text-right ${changeColorClass(stock.change_pct)}`}>
                    {formatChangePct(stock.change_pct)}
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
