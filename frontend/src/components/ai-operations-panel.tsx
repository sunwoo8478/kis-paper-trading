"use client";

import { useState } from "react";
import useSWR from "swr";
import { Activity, Bot, Clock3, Gauge, Power, RefreshCw, TrendingDown } from "lucide-react";
import {
  getKisAutonomousStatus,
  runKisAutonomousCycle,
  startKisAutonomousTrading,
  stopKisAutonomousTrading,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

export function AiOperationsPanel() {
  const kisAutonomous = useSWR("/api/kis/autonomous/status", getKisAutonomousStatus, { refreshInterval: 5000 });
  const [pendingAction, setPendingAction] = useState<"toggle" | "run" | null>(null);
  const engine = kisAutonomous.data;
  const latestOrderIds = kisAutonomous.data?.latest_cycle?.broker_order_ids;

  const toggleEngine = async () => {
    setPendingAction("toggle");
    try {
      const next = engine?.enabled ? await stopKisAutonomousTrading() : await startKisAutonomousTrading();
      await kisAutonomous.mutate(next, { revalidate: false });
    } finally {
      setPendingAction(null);
    }
  };

  const runNow = async () => {
    setPendingAction("run");
    try {
      await runKisAutonomousCycle();
      await kisAutonomous.mutate();
    } finally {
      setPendingAction(null);
    }
  };

  return (
    <section className="flex h-full flex-col border-b border-border bg-card xl:col-span-3 xl:border-b-0">
      <header className="flex min-h-14 items-center justify-between border-b border-border bg-muted/25 px-4 py-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold"><Bot className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />자율운용 감독</h2>
          <p className="mt-0.5 text-[9px] text-muted-foreground">24시간 감시, 장중 주문 실행</p>
        </div>
        <span className={`font-mono text-[9px] font-medium ${engine?.enabled ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}`}>{engine?.running ? "분석 중" : engine?.enabled ? "가동 중" : "중지"}</span>
      </header>

      <div className="grid flex-1 grid-cols-2">
        <Cell icon={Power} label="24H 모의 엔진" value={engine?.enabled ? "KIS ACTIVE" : "STOPPED"} tone={engine?.enabled ? "ready" : "warning"} />
        <Cell icon={Clock3} label="시장 상태" value={engine?.market_open ? "정규장" : "장외 감시"} tone={engine?.market_open ? "ready" : undefined} />
        <Cell icon={Gauge} label="운용 전략" value={engine?.strategy_mode === "competition_3m" ? "3M COMPETITION" : "STANDARD"} tone="ready" />
        <Cell icon={TrendingDown} label="엔진 단계" value={cycleLabel(engine?.phase)} tone={engine?.phase === "error" ? "warning" : undefined} />
        <Cell icon={Activity} label="최근 사이클" value={cycleLabel(engine?.latest_cycle?.status)} tone={engine?.latest_cycle?.status === "error" ? "warning" : undefined} />
        <Cell icon={Bot} label="최근 자율 주문" value={latestOrderLabel(latestOrderIds)} />
      </div>

      <div className="grid grid-cols-2 gap-2 border-t border-border p-3">
        <Button type="button" size="sm" variant={engine?.enabled ? "outline" : "default"} onClick={toggleEngine} disabled={!engine || pendingAction !== null} className="text-[10px]">
          <Power className="h-3.5 w-3.5" />{pendingAction === "toggle" ? "처리 중" : engine?.enabled ? "운용 중지" : "운용 시작"}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={runNow} disabled={!engine?.enabled || pendingAction !== null || engine?.running} className="text-[10px]">
          <RefreshCw className={`h-3.5 w-3.5 ${pendingAction === "run" ? "animate-spin" : ""}`} />즉시 분석
        </Button>
        {kisAutonomous.error && <p className="col-span-2 text-[9px] text-destructive">자율운용 상태를 불러오지 못했습니다.</p>}
        <p className="col-span-2 truncate text-[9px] text-muted-foreground">{engine?.latest_cycle?.market_regime ?? "시장 분석 대기"} · 목표 투자비중 {engine?.latest_cycle?.target_exposure_pct?.toFixed(0) ?? "-"}% · 데이터 {engine?.market_data_as_of ?? "갱신 중"}</p>
      </div>
    </section>
  );
}

function Cell({ icon: Icon, label, value, tone }: { icon: typeof Bot; label: string; value: string; tone?: "ready" | "warning" }) {
  return <div className="flex min-h-[58px] items-center gap-2.5 border-b border-r border-border px-3 even:border-r-0 [&:nth-last-child(-n+2)]:border-b-0"><Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /><div className="min-w-0"><p className="text-[9px] text-muted-foreground">{label}</p><p className={cnTone(tone)}>{value}</p></div></div>;
}

function cnTone(tone?: "ready" | "warning") { return `mt-0.5 truncate font-mono text-[10px] font-medium ${tone === "ready" ? "text-emerald-600 dark:text-emerald-400" : tone === "warning" ? "text-amber-600 dark:text-amber-400" : "text-foreground"}`; }
function cycleLabel(value?: string) { if (!value) return "대기"; if (value === "executed") return "주문 실행"; if (value === "observed") return "관찰 완료"; if (value === "market_closed") return "장외 대기"; if (value === "error") return "오류"; return value; }
function latestOrderLabel(orderIds?: (number | string)[]) { return orderIds?.length ? `#${orderIds.at(-1)} / ${orderIds.length}건` : "신규 주문 없음"; }
