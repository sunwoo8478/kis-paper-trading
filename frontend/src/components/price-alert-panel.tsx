"use client";

import { useState } from "react";
import useSWR from "swr";
import { Bell, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError, createPriceAlert, deletePriceAlert, getPriceAlerts } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export function PriceAlertPanel({ code, currentPrice }: { code: string; currentPrice: number | null }) {
  const alerts = useSWR(["/api/alerts", code], () => getPriceAlerts(code), { refreshInterval: 15000 });
  const [direction, setDirection] = useState<"above" | "below">("above");
  const [target, setTarget] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const create = async () => {
    const targetPrice = Number(target);
    if (!Number.isFinite(targetPrice) || targetPrice <= 0) {
      toast.error("목표 가격을 확인해 주세요.");
      return;
    }
    setSubmitting(true);
    try {
      await createPriceAlert({ code, direction, target_price: targetPrice });
      setTarget("");
      alerts.mutate();
      toast.success("가격 알림을 등록했습니다.");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "가격 알림 등록 실패");
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (id: number) => {
    try {
      await deletePriceAlert(id);
      alerts.mutate();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "가격 알림 삭제 실패");
    }
  };

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Bell className="h-4 w-4 text-muted-foreground" />
        <div>
          <h2 className="text-sm font-semibold">가격 알림</h2>
          <p className="text-[10px] text-muted-foreground">현재가 {formatPrice(currentPrice)}</p>
        </div>
      </header>
      <div className="space-y-3 p-4">
        <div className="grid grid-cols-2 rounded-lg bg-muted/50 p-0.5">
          {(["above", "below"] as const).map((item) => (
            <button key={item} type="button" onClick={() => setDirection(item)} className={cn("rounded-md py-1.5 text-xs transition", direction === item ? "bg-background font-medium shadow-sm" : "text-muted-foreground")}>
              {item === "above" ? "상향 돌파" : "하향 이탈"}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <Input type="number" min={1} value={target} onChange={(event) => setTarget(event.target.value)} placeholder="목표 가격" className="h-9" />
          <Button onClick={create} disabled={submitting} className="h-9 px-3">등록</Button>
        </div>
        <div className="space-y-2 pt-1">
          {(alerts.data ?? []).length === 0 ? (
            <p className="py-2 text-center text-xs text-muted-foreground">등록된 알림이 없습니다.</p>
          ) : (
            (alerts.data ?? []).slice(0, 5).map((alert) => (
              <div key={alert.id} className="flex items-center justify-between gap-3 border-t border-border pt-2 text-xs">
                <div>
                  <p className="font-mono font-medium">{formatPrice(alert.target_price)}</p>
                  <p className={cn("mt-0.5 text-[10px]", alert.active ? "text-muted-foreground" : "text-emerald-500")}>
                    {alert.active ? (alert.direction === "above" ? "상향 돌파 대기" : "하향 이탈 대기") : "조건 도달"}
                  </p>
                </div>
                <Button variant="ghost" size="icon-xs" onClick={() => remove(alert.id)} aria-label="가격 알림 삭제">
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
