"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { FileBarChart, RefreshCw, Users } from "lucide-react";
import { getStockInsight, type FinancialSeries } from "@/lib/api";
import { changeColorClass, formatChangePct, formatPrice } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type InsightTab = "financials" | "flows" | "research" | "peers";

const METRIC_CODES = ["per", "pbr", "eps", "bps", "dividendYieldRatio", "foreignRate"];
const FINANCIAL_ROWS = ["매출액", "영업이익", "당기순이익", "영업이익률", "순이익률", "ROE", "부채비율", "EPS", "PER", "PBR", "주당배당금"];

export function StockInsightPanel({ code }: { code: string }) {
  const insight = useSWR(["/api/stocks", code, "insight"], () => getStockInsight(code), { refreshInterval: 300000, revalidateOnFocus: false });
  const [tab, setTab] = useState<InsightTab>("financials");
  const data = insight.data;
  const upside = data?.consensus.target_price && data.quote.price
    ? ((data.consensus.target_price - data.quote.price) / data.quote.price) * 100
    : null;

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">기업 정보</h2>
          <p className="mt-0.5 text-[10px] text-muted-foreground">재무, 수급, 컨센서스, 동종업계</p>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={() => insight.mutate()} aria-label="기업 정보 새로고침">
          <RefreshCw className={cn("h-3.5 w-3.5", insight.isValidating && "animate-spin")} />
        </Button>
      </header>

      {insight.isLoading ? (
        <div className="h-96 animate-pulse bg-muted/25" />
      ) : insight.error || !data ? (
        <div className="px-5 py-12 text-center text-xs text-muted-foreground">기업 정보를 불러오지 못했습니다.</div>
      ) : (
        <>
          <div className="grid grid-cols-2 border-b border-border">
            <InsightMetric label="목표주가" value={formatPrice(data.consensus.target_price)} detail={data.consensus.as_of ?? "컨센서스"} />
            <InsightMetric label="상승 여력" value={formatChangePct(upside)} tone={changeColorClass(upside)} detail={`현재가 ${formatPrice(data.quote.price)}`} />
          </div>
          <div className="grid grid-cols-3 border-b border-border">
            {METRIC_CODES.map((metricCode) => {
              const metric = data.metrics[metricCode];
              return <InsightMetric key={metricCode} label={metric?.label ?? metricCode.toUpperCase()} value={metric?.value ?? "-"} detail={metric?.as_of ?? ""} compact />;
            })}
          </div>

          <div className="flex overflow-x-auto border-b border-border bg-muted/20 p-1">
            {([
              ["financials", "재무"], ["flows", "수급"], ["research", "리서치"], ["peers", "동종업계"],
            ] as [InsightTab, string][]).map(([key, label]) => (
              <button key={key} type="button" onClick={() => setTab(key)} className={cn("min-w-16 flex-1 rounded-lg px-2 py-1.5 text-[10px] transition", tab === key ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>{label}</button>
            ))}
          </div>

          <div className="max-h-[420px] overflow-auto">
            {tab === "financials" && <Financials annual={data.financials.annual} quarter={data.financials.quarter} />}
            {tab === "flows" && <InvestorFlows rows={data.investor_flows} />}
            {tab === "research" && <Research rows={data.research} />}
            {tab === "peers" && <Peers rows={data.peers} />}
          </div>

          {data.company_summary.length > 0 && (
            <div className="border-t border-border px-4 py-3">
              <p className="text-[10px] font-medium text-muted-foreground">기업 개요</p>
              <p className="mt-1.5 line-clamp-3 text-xs leading-5 text-foreground/80">{data.company_summary.join(" ")}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Financials({ annual, quarter }: { annual: FinancialSeries; quarter: FinancialSeries }) {
  const [periodType, setPeriodType] = useState<"annual" | "quarter">("quarter");
  const series = periodType === "annual" ? annual : quarter;
  return (
    <div className="min-w-[540px] p-3">
      <div className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground"><FileBarChart className="h-3 w-3" />단위: 억원, %, 배, 원</span>
        <div className="flex rounded-lg bg-muted/60 p-0.5">
          <button type="button" onClick={() => setPeriodType("quarter")} className={cn("rounded-md px-2 py-1 text-[9px]", periodType === "quarter" && "bg-background shadow-sm")}>분기</button>
          <button type="button" onClick={() => setPeriodType("annual")} className={cn("rounded-md px-2 py-1 text-[9px]", periodType === "annual" && "bg-background shadow-sm")}>연간</button>
        </div>
      </div>
      <table className="w-full text-[10px]">
        <thead><tr className="text-muted-foreground"><th className="pb-2 text-left font-normal">항목</th>{series.periods.map((period) => <th key={period.key} className="pb-2 text-right font-normal">{period.label}{period.consensus && <span className="ml-1 text-amber-500">E</span>}</th>)}</tr></thead>
        <tbody>{FINANCIAL_ROWS.filter((row) => series.metrics[row]).map((row) => <tr key={row} className="border-t border-border/70"><td className="py-2 text-muted-foreground">{row}</td>{series.periods.map((period) => <td key={period.key} className="py-2 text-right font-mono">{formatFinancial(series.metrics[row]?.[period.key])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function InvestorFlows({ rows }: { rows: Awaited<ReturnType<typeof getStockInsight>>["investor_flows"] }) {
  return <div className="p-3"><div className="mb-2 flex items-center gap-1.5 text-[10px] text-muted-foreground"><Users className="h-3 w-3" />순매수 수량</div><table className="w-full text-[10px]"><thead><tr className="text-muted-foreground"><th className="pb-2 text-left font-normal">일자</th><th className="pb-2 text-right font-normal">외국인</th><th className="pb-2 text-right font-normal">기관</th><th className="pb-2 text-right font-normal">개인</th></tr></thead><tbody>{rows.map((row) => <tr key={row.date} className="border-t border-border/70"><td className="py-2 font-mono text-muted-foreground">{formatDate(row.date)}</td><FlowCell value={row.foreign} /><FlowCell value={row.institution} /><FlowCell value={row.individual} /></tr>)}</tbody></table></div>;
}

function Research({ rows }: { rows: Awaited<ReturnType<typeof getStockInsight>>["research"] }) {
  return <div className="space-y-1 p-2">{rows.length === 0 ? <Empty /> : rows.map((row) => <div key={row.id} className="rounded-lg px-2 py-2 hover:bg-muted/50"><div className="flex items-center justify-between gap-3"><p className="truncate text-xs font-medium">{row.title}</p><span className="shrink-0 text-[9px] text-muted-foreground">{formatDate(row.date)}</span></div><p className="mt-1 text-[10px] text-muted-foreground">{row.broker} / 조회 {row.views?.toLocaleString("ko-KR") ?? "-"}</p></div>)}</div>;
}

function Peers({ rows }: { rows: Awaited<ReturnType<typeof getStockInsight>>["peers"] }) {
  return <div className="space-y-1 p-2">{rows.length === 0 ? <Empty /> : rows.map((row) => <Link key={row.code} href={`/stocks/${row.code}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-lg px-2 py-2 hover:bg-muted/50"><div className="min-w-0"><p className="truncate text-xs font-medium">{row.name}</p><p className="font-mono text-[9px] text-muted-foreground">{row.code} {row.market}</p></div><div className="text-right"><p className="font-mono text-xs">{formatPrice(row.price)}</p><p className={`font-mono text-[9px] ${changeColorClass(row.change_pct)}`}>{formatChangePct(row.change_pct)}</p></div></Link>)}</div>;
}

function InsightMetric({ label, value, detail, tone, compact = false }: { label: string; value: string; detail: string; tone?: string; compact?: boolean }) {
  return <div className={cn("border-b border-r border-border px-4 py-3 even:border-r-0", compact && "px-3 py-2.5 [&:nth-child(3n)]:border-r-0 [&:nth-last-child(-n+3)]:border-b-0")}><p className="text-[9px] text-muted-foreground">{label}</p><p className={cn("mt-1 font-mono font-medium", compact ? "text-xs" : "text-sm", tone)}>{value}</p>{detail && <p className="mt-0.5 text-[8px] text-muted-foreground">{detail}</p>}</div>;
}

function FlowCell({ value }: { value: number | null }) { return <td className={cn("py-2 text-right font-mono", changeColorClass(value))}>{value == null ? "-" : new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1, signDisplay: "always" }).format(value)}</td>; }
function formatFinancial(value: number | null | undefined) { return value == null ? "-" : new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(value); }
function formatDate(value: string) { return value?.length === 8 ? `${value.slice(2, 4)}.${value.slice(4, 6)}.${value.slice(6, 8)}` : value; }
function Empty() { return <div className="py-10 text-center text-xs text-muted-foreground">표시할 데이터가 없습니다.</div>; }
