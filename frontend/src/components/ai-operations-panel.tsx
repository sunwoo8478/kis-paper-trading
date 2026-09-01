"use client";

import { useState } from "react";
import useSWR from "swr";
import { Activity, Bot, Clock3, Gauge, Power, RefreshCw, TrendingDown } from "lucide-react";
import {
  getAutonomousStatus,
  getExperimentStatus,
  getKisAutonomousStatus,
  runAutonomousCycle,
  runKisAutonomousCycle,
  startAutonomousTrading,
  startKisAutonomousTrading,
  stopAutonomousTrading,
  stopKisAutonomousTrading,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

export function AiOperationsPanel({ source = "kis" }: { source?: "kis" | "local" }) {
  const isKis = source === "kis";
  const localAutonomous = useSWR(isKis ? null : "/api/agent/autonomous/status", getAutonomousStatus, { refreshInterval: 5000 });
  const kisAutonomous = useSWR(isKis ? "/api/kis/autonomous/status" : null, getKisAutonomousStatus, { refreshInterval: 5000 });
  const experimentStatus = useSWR(isKis ? null : "/api/agent/experiment", getExperimentStatus, { refreshInterval: 5000 });
  const [pendingAction, setPendingAction] = useState<"toggle" | "run" | null>(null);
  const engine = isKis ? kisAutonomous.data : localAutonomous.data;
  const latestOrderIds = isKis
    ? kisAutonomous.data?.latest_cycle?.broker_order_ids
    : localAutonomous.data?.latest_cycle?.order_ids;
  const experiment = experimentStatus.data?.experiment;

  const toggleEngine = async () => {
    setPendingAction("toggle");
    try {
      if (isKis) {
        const next = engine?.enabled ? await stopKisAutonomousTrading() : await startKisAutonomousTrading();
        await kisAutonomous.mutate(next, { revalidate: false });
      } else {
        const next = engine?.enabled ? await stopAutonomousTrading() : await startAutonomousTrading();
        await localAutonomous.mutate(next, { revalidate: false });
      }
    } finally {
      setPendingAction(null);
    }
  };

  const runNow = async () => {
    setPendingAction("run");
    try {
      if (isKis) await runKisAutonomousCycle();
      else await runAutonomousCycle();
      if (isKis) await kisAutonomous.mutate();
      else await localAutonomous.mutate();
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
        <Cell icon={Power} label="24H 모의 엔진" value={engine?.enabled ? isKis ? "KIS ACTIVE" : "LOCAL ACTIVE" : "STOPPED"} tone={engine?.enabled ? "ready" : "warning"} />
        <Cell icon={Clock3} label="시장 상태" value={engine?.market_open ? "정규장" : "장외 감시"} tone={engine?.market_open ? "ready" : undefined} />
        <Cell icon={Gauge} label={isKis ? "실행 계좌" : "AI 실험 수익률"} value={isKis ? "KIS 모의투자" : formatPct(experiment?.return_pct)} tone={isKis || (experiment?.return_pct ?? 0) >= 0 ? "ready" : "warning"} />
        <Cell icon={TrendingDown} label={isKis ? "엔진 단계" : "실험 최대 낙폭"} value={isKis ? cycleLabel(engine?.phase) : formatPct(experiment?.max_drawdown_pct)} tone={isKis && engine?.phase === "error" || (experiment?.max_drawdown_pct ?? 0) < -3 ? "warning" : undefined} />
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
        {(kisAutonomous.error || localAutonomous.error || experimentStatus.error) && <p className="col-span-2 text-[9px] text-destructive">자율운용 상태를 불러오지 못했습니다.</p>}
        <p className="col-span-2 truncate text-[9px] text-muted-foreground">{isKis ? "한국투자증권 대회형 모의계좌 주문" : experiment ? `${experiment.name} / KOSPI 대비 ${formatPct(experiment.alpha_pct ?? undefined)} / 실제 주문 없음` : "로컬 실험 기준선 준비 중"}</p>
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
function formatPct(value?: number) { return value === undefined ? "-" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`; }
