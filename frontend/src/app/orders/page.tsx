"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Download, X } from "lucide-react";
import { toast } from "sonner";
import { ApiError, cancelOrder, getOrders } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { RefreshBadge } from "@/components/refresh-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const KRW = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

export default function OrdersPage() {
  const orders = useSWR("/api/orders", getOrders, { refreshInterval: 10000 });
  const [side, setSide] = useState<"all" | "buy" | "sell">("all");
  const [query, setQuery] = useState("");
  const allRows = useMemo(() => orders.data ?? [], [orders.data]);
  const rows = useMemo(
    () => allRows.filter((order) => (side === "all" || order.side === side) && order.code.includes(query.trim())),
    [allRows, query, side]
  );
  const filledRows = allRows.filter((order) => order.status === "filled");
  const pendingCount = allRows.filter((order) => order.status === "pending").length;
  const buyValue = filledRows.filter((order) => order.side === "buy").reduce((sum, order) => sum + order.quantity * order.price, 0);
  const sellValue = filledRows.filter((order) => order.side === "sell").reduce((sum, order) => sum + order.quantity * order.price, 0);

  const cancel = async (orderId: number) => {
    try {
      await cancelOrder(orderId);
      orders.mutate();
      toast.success("대기주문을 취소했습니다.");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "대기주문 취소 실패");
    }
  };

  return (
    <div className="space-y-8">
      <section className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Orders</p>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">주문내역</h1>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">체결 흐름을 필터링하고 거래대금을 점검하거나 CSV로 보관합니다.</p>
        </div>
        <RefreshBadge
          hasError={Boolean(orders.error)}
          isValidating={orders.isValidating}
          onRefresh={() => orders.mutate()}
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
                    <TableCell>{new Date(order.filled_at).toLocaleString("ko-KR")}</TableCell>
                    <TableCell className="font-medium text-foreground">{order.code}</TableCell>
                    <TableCell>
                      <Badge variant={order.side === "buy" ? "destructive" : "default"}>
                        {order.side === "buy" ? "매수" : "매도"}
                      </Badge>
                    </TableCell>
                    <TableCell>{order.order_type === "limit" ? "지정가" : "시장가"}</TableCell>
                    <TableCell className="text-right">{order.quantity}</TableCell>
                    <TableCell className="text-right font-mono">{KRW.format(order.status === "pending" ? (order.limit_price ?? order.price) : order.price)}원</TableCell>
                    <TableCell>{statusLabel(order.status)}</TableCell>
                    <TableCell className="text-right">
                      {order.status === "pending" && (
                        <Button variant="ghost" size="icon-sm" onClick={() => cancel(order.id)} aria-label="대기주문 취소">
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      )}
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

function exportOrders(rows: Awaited<ReturnType<typeof getOrders>>) {
  const header = ["id", "filled_at", "code", "side", "order_type", "quantity", "price", "limit_price", "status"];
  const csv = [header.join(","), ...rows.map((order) => [order.id, order.filled_at, order.code, order.side, order.order_type, order.quantity, order.price, order.limit_price ?? "", order.status].join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `orders-${new Date().toISOString().slice(0, 10)}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}
