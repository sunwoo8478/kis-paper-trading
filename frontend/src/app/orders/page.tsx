"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Download } from "lucide-react";
import { getKisBrokerOrders } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { RefreshBadge } from "@/components/refresh-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const KRW = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

export default function OrdersPage() {
  const kisOrders = useSWR("/api/kis/broker-orders", getKisBrokerOrders, { refreshInterval: 10000 });
  const [side, setSide] = useState<"all" | "buy" | "sell">("all");
  const [query, setQuery] = useState("");
  const allRows = useMemo<DisplayOrder[]>(() => (kisOrders.data ?? []).map((order) => ({
        id: order.broker_order_id,
        time: formatKisOrderTime(order.order_time),
        code: order.code,
        name: order.name,
        side: order.side,
        orderType: "market",
        quantity: order.requested_quantity,
        filledQuantity: order.filled_quantity,
        price: order.avg_fill_price ?? 0,
        status: order.status,
      })), [kisOrders.data]);
  const rows = useMemo(
    () => allRows.filter((order) => (side === "all" || order.side === side) && order.code.includes(query.trim())),
    [allRows, query, side]
  );
  const filledRows = allRows.filter((order) => order.status === "filled");
  const pendingCount = allRows.filter((order) => order.status === "pending" || order.status === "partial").length;
  const buyValue = filledRows.filter((order) => order.side === "buy").reduce((sum, order) => sum + order.filledQuantity * order.price, 0);
  const sellValue = filledRows.filter((order) => order.side === "sell").reduce((sum, order) => sum + order.filledQuantity * order.price, 0);

  return (
    <div className="space-y-8">
      <section className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Orders</p>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">주문내역</h1>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">한국투자증권 모의계좌의 당일 주문과 부분 체결을 확인합니다.</p>
        </div>
        <RefreshBadge
          hasError={Boolean(kisOrders.error)}
          isValidating={kisOrders.isValidating}
          onRefresh={() => kisOrders.mutate()}
        />
      </section>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <OrderMetric label="전체 체결" value={`${filledRows.length}건`} />
        <OrderMetric label="대기 주문" value={`${pendingCount}건`} />
        <OrderMetric label="매수 거래대금" value={formatCompactPrice(buyValue)} />
        <OrderMetric label="순매수" value={formatCompactPrice(buyValue - sellValue)} />
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex rounded-lg bg-muted/50 p-0.5">
            {(["all", "buy", "sell"] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setSide(item)}
                className={cn("rounded-md px-3 py-1.5 text-xs transition", side === item ? "bg-background font-medium shadow-sm" : "text-muted-foreground")}
              >
                {item === "all" ? "전체" : item === "buy" ? "매수" : "매도"}
              </button>
            ))}
          </div>
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="종목코드 필터" className="h-8 w-full sm:w-44" />
        </div>
        <Button variant="outline" onClick={() => exportOrders(rows)} disabled={rows.length === 0}>
          <Download className="h-4 w-4" />
          CSV 내보내기
        </Button>
      </section>

      <Card className="border-border bg-card shadow-sm">
        <CardHeader className="border-b bg-muted/40">
          <CardTitle>체결 이력</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>시각</TableHead>
                <TableHead>종목코드</TableHead>
                <TableHead>구분</TableHead>
                <TableHead>주문유형</TableHead>
                <TableHead className="text-right">수량</TableHead>
                <TableHead className="text-right">가격</TableHead>
                <TableHead>상태</TableHead>
                <TableHead className="text-right">관리</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-10 text-center text-muted-foreground">
                    주문내역 없음
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((order) => (
                  <TableRow key={order.id}>
                    <TableCell>{order.time}</TableCell>
                    <TableCell className="font-medium text-foreground">{order.name ?? order.code}<span className="ml-2 font-mono text-[10px] text-muted-foreground">{order.code}</span></TableCell>
                    <TableCell>
                      <Badge variant={order.side === "buy" ? "destructive" : "default"}>
                        {order.side === "buy" ? "매수" : "매도"}
                      </Badge>
                    </TableCell>
                    <TableCell>{order.orderType === "limit" ? "지정가" : "시장가"}</TableCell>
                    <TableCell className="text-right font-mono">{order.quantity} / {order.filledQuantity}</TableCell>
                    <TableCell className="text-right font-mono">{order.price ? `${KRW.format(order.price)}원` : "-"}</TableCell>
                    <TableCell>{statusLabel(order.status)}</TableCell>
                    <TableCell className="text-right">
                      <span className="text-[10px] text-muted-foreground">KIS</span>
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

function statusLabel(status: string) {
  return status === "filled" ? "체결" : status === "pending" ? "대기" : status === "cancelled" ? "취소" : status;
}

function OrderMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-sm font-medium">{value}</p>
    </div>
  );
}

function formatCompactPrice(value: number) {
  return `${new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 }).format(value)}원`;
}

type DisplayOrder = { id: string; time: string; code: string; name: string | null; side: "buy" | "sell"; orderType: "market" | "limit"; quantity: number; filledQuantity: number; price: number; status: string };

function formatKisOrderTime(value: string) { return value.length === 6 ? `${value.slice(0, 2)}:${value.slice(2, 4)}:${value.slice(4, 6)}` : value || "-"; }

function exportOrders(rows: DisplayOrder[]) {
  const header = ["id", "time", "code", "name", "side", "order_type", "quantity", "filled_quantity", "price", "status"];
  const csv = [header.join(","), ...rows.map((order) => [order.id, order.time, order.code, order.name ?? "", order.side, order.orderType, order.quantity, order.filledQuantity, order.price, order.status].join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `orders-${new Date().toISOString().slice(0, 10)}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}
