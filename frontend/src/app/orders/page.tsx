"use client";

import useSWR from "swr";
import { getOrders } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { RefreshBadge } from "@/components/refresh-badge";

const KRW = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

export default function OrdersPage() {
  const orders = useSWR("/api/orders", getOrders, { refreshInterval: 10000 });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">주문내역</h1>
        <RefreshBadge
          hasError={Boolean(orders.error)}
          isValidating={orders.isValidating}
          onRefresh={() => orders.mutate()}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>체결 이력</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>시각</TableHead>
                <TableHead>종목코드</TableHead>
                <TableHead>구분</TableHead>
                <TableHead className="text-right">수량</TableHead>
                <TableHead className="text-right">체결가</TableHead>
                <TableHead>상태</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(orders.data ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    주문내역 없음
                  </TableCell>
                </TableRow>
              )}
              {(orders.data ?? []).map((order) => (
                <TableRow key={order.id}>
                  <TableCell>{new Date(order.filled_at).toLocaleString("ko-KR")}</TableCell>
                  <TableCell>{order.code}</TableCell>
                  <TableCell>
                    <Badge variant={order.side === "buy" ? "destructive" : "default"}>
                      {order.side === "buy" ? "매수" : "매도"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">{order.quantity}</TableCell>
                  <TableCell className="text-right">{KRW.format(order.price)}원</TableCell>
                  <TableCell>{order.status}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
