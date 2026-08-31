"use client";

import { Bot, ChevronRight, LockKeyhole, Radar, ShieldCheck } from "lucide-react";
import type { AgentStatus } from "@/lib/api";

export function AiOperationsPanel({ candidateCount, riskFlags, latestRunId, linkedOrders, status }: { candidateCount: number; riskFlags: number; latestRunId: number | null; linkedOrders: number; status?: AgentStatus }) {
  const openCopilot = () => window.dispatchEvent(new Event("open-ai-copilot"));
  return (
    <section className="flex h-full flex-col border-b border-border bg-card xl:col-span-3 xl:border-b-0">
      <header className="flex min-h-14 items-center justify-between border-b border-border bg-muted/25 px-4 py-3"><div><h2 className="flex items-center gap-2 text-sm font-semibold"><Bot className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />AI 운용 감독</h2><p className="mt-0.5 text-[9px] text-muted-foreground">모델 연결과 주문 권한을 분리 관리</p></div><button type="button" onClick={openCopilot} className="flex items-center gap-1 text-[9px] text-muted-foreground hover:text-foreground">코파일럿<ChevronRight className="h-3 w-3" /></button></header>
      <div className="grid flex-1 grid-cols-2">
        <Cell icon={Radar} label="분석 후보" value={`${candidateCount}개`} tone="ready" />
        <Cell icon={ShieldCheck} label="위험 신호" value={`${riskFlags}건`} tone={riskFlags ? "warning" : "ready"} />
        <Cell icon={LockKeyhole} label="자동 주문" value={status?.auto_execution_enabled ? "모의 운용" : "잠금"} tone={status?.auto_execution_enabled ? "ready" : "warning"} />
        <Cell icon={Bot} label="최근 실행" value={latestRunId ? `#${latestRunId} / ${linkedOrders}건` : "기록 없음"} />
      </div>
      <button type="button" onClick={openCopilot} className="border-t border-border px-4 py-3 text-left transition hover:bg-muted/40 active:translate-y-px"><p className="text-[10px] font-medium">현재 계좌 브리핑 열기</p><p className="mt-1 text-[9px] text-muted-foreground">어느 화면에서든 동일한 운용 컨텍스트를 유지합니다.</p></button>
    </section>
  );
}

function Cell({ icon: Icon, label, value, tone }: { icon: typeof Bot; label: string; value: string; tone?: "ready" | "warning" }) { return <div className="flex min-h-[82px] flex-col justify-between border-b border-r border-border p-3 even:border-r-0"><Icon className="h-3.5 w-3.5 text-muted-foreground" /><div><p className="text-[9px] text-muted-foreground">{label}</p><p className={cnTone(tone)}>{value}</p></div></div>; }
function cnTone(tone?: "ready" | "warning") { return `mt-1 font-mono text-[10px] font-medium ${tone === "ready" ? "text-emerald-600 dark:text-emerald-400" : tone === "warning" ? "text-amber-600 dark:text-amber-400" : "text-foreground"}`; }
