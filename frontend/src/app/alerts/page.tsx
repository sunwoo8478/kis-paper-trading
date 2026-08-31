"use client";

import Link from "next/link";
import useSWR from "swr";
import { Bell, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError, deletePriceAlert, getPriceAlerts } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { RefreshBadge } from "@/components/refresh-badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function AlertsPage() {
  const alerts = useSWR("/api/alerts", () => getPriceAlerts(), { refreshInterval: 15000 });
  const rows = alerts.data ?? [];
  const active = rows.filter((alert) => alert.active).length;
  const triggered = rows.length - active;

  const remove = async (id: number) => {
    try {
      await deletePriceAlert(id);
      alerts.mutate();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "가격 알림 삭제 실패");
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs text-muted-foreground">Price alerts</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">가격 알림 센터</h1>
          <p className="mt-2 text-sm text-muted-foreground">종목 화면에서 설정한 돌파·이탈 조건을 한곳에서 관리합니다.</p>
        </div>
        <RefreshBadge hasError={Boolean(alerts.error)} isValidating={alerts.isValidating} onRefresh={() => alerts.mutate()} />
      </header>

      <section className="grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-border bg-border">
        <AlertMetric label="전체" value={`${rows.length}건`} />
        <AlertMetric label="감시 중" value={`${active}건`} />
        <AlertMetric label="조건 도달" value={`${triggered}건`} />
      </section>

      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Bell className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">알림 목록</h2>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow><TableHead>종목</TableHead><TableHead>조건</TableHead><TableHead className="text-right">목표 가격</TableHead><TableHead>상태</TableHead><TableHead>등록 시각</TableHead><TableHead className="text-right">관리</TableHead></TableRow></TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="py-12 text-center text-muted-foreground">종목 상세 화면에서 첫 가격 알림을 등록할 수 있습니다.</TableCell></TableRow>
              ) : rows.map((alert) => (
                <TableRow key={alert.id}>
                  <TableCell><Link href={`/stocks/${alert.code}`} className="font-mono font-medium hover:underline">{alert.code}</Link></TableCell>
                  <TableCell>{alert.direction === "above" ? "상향 돌파" : "하향 이탈"}</TableCell>
                  <TableCell className="text-right font-mono">{formatPrice(alert.target_price)}</TableCell>
                  <TableCell><span className={alert.active ? "text-muted-foreground" : "text-emerald-500"}>{alert.active ? "감시 중" : "조건 도달"}</span></TableCell>
                  <TableCell className="text-muted-foreground">{new Date(alert.created_at).toLocaleString("ko-KR")}</TableCell>
                  <TableCell className="text-right"><Button variant="ghost" size="icon-sm" onClick={() => remove(alert.id)} aria-label="가격 알림 삭제"><Trash2 className="h-3.5 w-3.5" /></Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  );
}

function AlertMetric({ label, value }: { label: string; value: string }) {
  return <div className="bg-card px-4 py-3"><p className="text-[10px] text-muted-foreground">{label}</p><p className="mt-1 font-mono text-sm font-medium">{value}</p></div>;
}
