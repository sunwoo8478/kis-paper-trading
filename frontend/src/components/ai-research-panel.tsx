"use client";

import useSWR from "swr";
import { Activity, Bot, Check, Clock3, RefreshCw } from "lucide-react";
import { getAgentCandidates, getAgentRuns } from "@/lib/api";
import { changeColorClass, formatChangePct } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function AiResearchPanel({ code, className }: { code?: string; className?: string }) {
  const candidates = useSWR("/api/agent/candidates", getAgentCandidates, { refreshInterval: 15000 });
  const runs = useSWR("/api/agent/runs", getAgentRuns, { refreshInterval: 15000 });

  const latestRun = runs.data?.[0];
  const candidate = code ? candidates.data?.find((item) => item.code === code) : undefined;
  const matchedDecision = code
    ? runs.data
        ?.flatMap((run) => run.decisions.map((decision) => ({ decision, run })))
        .find((item) => item.decision.code === code)
    : undefined;
  const decision = code ? matchedDecision?.decision : latestRun?.decisions[0];
  const decisionReasoning = code ? matchedDecision?.run.reasoning : latestRun?.reasoning;
  const hasError = Boolean(candidates.error || runs.error);
  const isLoading = !candidates.data || !runs.data;

  const refresh = () => {
    candidates.mutate();
    runs.mutate();
  };

  return (
    <section className={cn("overflow-hidden rounded-xl border border-border bg-card text-foreground shadow-sm", className)}>
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div className="flex gap-3">
          <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <Bot className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">AI 리서치</h2>
              <span className="rounded border border-border px-2 py-0.5 text-[10px] text-muted-foreground">AGENT</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">후보 탐색부터 주문 판단까지 한 흐름으로 기록합니다.</p>
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={refresh}
          aria-label="AI 데이터 새로고침"
          className="text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <RefreshCw className={cn("h-4 w-4", (candidates.isValidating || runs.isValidating) && "animate-spin")} />
        </Button>
      </div>

      <div className="grid grid-cols-2 divide-x divide-border border-b border-border">
        <StatusCell
          label="운용 상태"
          value={hasError ? "연결 확인 필요" : isLoading ? "불러오는 중" : "모니터링 중"}
          icon={<Activity className="h-3.5 w-3.5" />}
          active={!hasError && !isLoading}
        />
        <StatusCell
          label={code ? "현재 종목" : "분석 후보"}
          value={code ? (candidate ? "후보 포함" : "후보 외") : `${candidates.data?.length ?? 0}개`}
          icon={candidate || !code ? <Check className="h-3.5 w-3.5" /> : <Clock3 className="h-3.5 w-3.5" />}
          active={Boolean(candidate || !code)}
        />
      </div>

      <div className="space-y-5 px-5 py-5">
        {code && candidate && (
          <div>
            <p className="text-[11px] font-medium text-muted-foreground">실시간 컨텍스트</p>
            <div className="mt-2 flex items-end justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-foreground">{candidate.name}</p>
                <p className="mt-0.5 font-mono text-xs text-muted-foreground">{candidate.market} / {candidate.code}</p>
              </div>
              <p className={cn("font-mono text-sm font-medium", changeColorClass(candidate.change_pct))}>
                {formatChangePct(candidate.change_pct)}
              </p>
            </div>
          </div>
        )}

        <div>
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] font-medium text-muted-foreground">최근 판단</p>
            {latestRun?.ts && (
              <time className="text-[10px] text-muted-foreground">{formatTime(latestRun.ts)}</time>
            )}
          </div>
          <div className="mt-2 border-l border-emerald-400/40 pl-3">
            {decision ? (
              <>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground">{decision.code}</span>
                  <DecisionBadge action={decision.action} />
                  {decision.quantity !== undefined && <span className="text-xs text-muted-foreground">{decision.quantity}주</span>}
                </div>
                <p className="mt-2 text-sm leading-6 text-foreground/80">
                  {decisionReasoning}
                </p>
              </>
            ) : latestRun ? (
              <p className="text-sm leading-6 text-foreground/80">
                {code ? "이 종목에 대한 최근 매매 판단은 없습니다." : latestRun.reasoning}
              </p>
            ) : (
              <p className="text-sm leading-6 text-muted-foreground">에이전트 실행 기록이 쌓이면 판단 근거가 이곳에 표시됩니다.</p>
            )}
          </div>
        </div>

        <div className="border-t border-border pt-4">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">마지막 실행</span>
            <span className="font-mono text-foreground/80">{latestRun ? `#${latestRun.id}` : "-"}</span>
          </div>
          <div className="mt-2 flex items-center justify-between text-xs">
            <span className="text-muted-foreground">연결 주문</span>
            <span className="font-mono text-foreground/80">{latestRun?.order_ids.length ?? 0}건</span>
          </div>
        </div>
      </div>
    </section>
  );
}

function StatusCell({ label, value, icon, active }: { label: string; value: string; icon: React.ReactNode; active: boolean }) {
  return (
    <div className="px-5 py-3.5">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className={cn("mt-1.5 flex items-center gap-1.5 text-xs font-medium", active ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground")}>
        {icon}
        {value}
      </p>
    </div>
  );
}

function DecisionBadge({ action }: { action: string }) {
  const label = action === "buy" ? "매수" : action === "sell" ? "매도" : "관망";
  return (
    <span className={cn(
      "rounded px-1.5 py-0.5 text-[10px] font-semibold",
      action === "buy" ? "bg-rose-500/10 text-rose-600 dark:text-rose-400" : action === "sell" ? "bg-blue-500/10 text-blue-600 dark:text-blue-400" : "bg-muted text-muted-foreground"
    )}>
      {label}
    </span>
  );
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
