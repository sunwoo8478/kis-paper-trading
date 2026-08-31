"use client";

import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { getPortfolioRisk } from "@/lib/api";
import { changeColorClass, formatChangePct, formatPrice } from "@/lib/format";
import { RefreshBadge } from "@/components/refresh-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function RiskPage() {
  const risk = useSWR("/api/portfolio/risk", getPortfolioRisk, { refreshInterval: 10000 });
  const data = risk.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs text-muted-foreground">Portfolio risk</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">계좌 리스크 워크스페이스</h1>
          <p className="mt-2 text-sm text-muted-foreground">노출, 집중도, 낙폭과 종목별 손익 기여도를 점검합니다.</p>
        </div>
        <RefreshBadge hasError={Boolean(risk.error)} isValidating={risk.isValidating} onRefresh={() => risk.mutate()} />
      </header>

      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-3 xl:grid-cols-6">
        <RiskMetric label="총자산" value={formatPrice(data?.total_value ?? null)} />
        <RiskMetric label="누적 수익률" value={formatChangePct(data?.total_return_pct ?? null)} tone={changeColorClass(data?.total_return_pct ?? null)} />
        <RiskMetric label="투자 비중" value={data ? `${data.invested_ratio_pct.toFixed(1)}%` : "-"} />
        <RiskMetric label="현금 비중" value={data ? `${data.cash_ratio_pct.toFixed(1)}%` : "-"} />
        <RiskMetric label="최대 종목 비중" value={data ? `${data.max_position_weight_pct.toFixed(1)}%` : "-"} />
        <RiskMetric label="최대 낙폭" value={data ? `${data.max_drawdown_pct.toFixed(2)}%` : "-"} tone={data && data.max_drawdown_pct < 0 ? "text-blue-500" : undefined} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">포지션 노출</h2>
            <p className="mt-1 text-[10px] text-muted-foreground">현재가 기준 평가금액과 계좌 내 비중</p>
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>종목</TableHead>
                  <TableHead className="text-right">수량</TableHead>
                  <TableHead className="text-right">평단</TableHead>
                  <TableHead className="text-right">현재가</TableHead>
                  <TableHead className="text-right">평가금액</TableHead>
                  <TableHead className="text-right">손익</TableHead>
                  <TableHead className="text-right">수익률</TableHead>
                  <TableHead className="text-right">비중</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data?.positions ?? []).length === 0 ? (
                  <TableRow><TableCell colSpan={8} className="py-12 text-center text-muted-foreground">보유 포지션이 없습니다.</TableCell></TableRow>
                ) : (
                  data?.positions.map((position) => (
                    <TableRow key={position.code}>
                      <TableCell><Link href={`/stocks/${position.code}`} className="font-mono font-medium hover:underline">{position.code}</Link></TableCell>
                      <TableCell className="text-right font-mono">{position.quantity}</TableCell>
                      <TableCell className="text-right font-mono">{formatPrice(position.avg_price)}</TableCell>
                      <TableCell className="text-right font-mono">{formatPrice(position.current_price)}</TableCell>
                      <TableCell className="text-right font-mono">{formatPrice(position.market_value)}</TableCell>
                      <TableCell className={`text-right font-mono ${changeColorClass(position.unrealized_pnl)}`}>{formatPrice(position.unrealized_pnl)}</TableCell>
                      <TableCell className={`text-right font-mono ${changeColorClass(position.return_pct)}`}>{formatChangePct(position.return_pct)}</TableCell>
                      <TableCell className="text-right font-mono">{position.weight_pct.toFixed(1)}%</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </div>

        <aside className="space-y-4">
          <section className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold">리스크 진단</h2>
            </div>
            <div className="mt-4 space-y-3 text-xs">
              <Diagnostic label="집중도 HHI" value={data ? data.concentration_hhi.toFixed(3) : "-"} />
              <Diagnostic label="미실현 손익" value={formatPrice(data?.unrealized_pnl ?? null)} tone={changeColorClass(data?.unrealized_pnl ?? null)} />
              <Diagnostic label="초기 자본" value={formatPrice(data?.initial_capital ?? null)} />
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold">주의 항목</h2>
            </div>
            <div className="mt-4 space-y-2">
              {(data?.risk_flags ?? []).length === 0 ? (
                <p className="text-xs leading-5 text-muted-foreground">현재 설정된 리스크 임계치를 초과한 항목이 없습니다.</p>
              ) : (
                data?.risk_flags.map((flag) => (
                  <div key={flag.code} className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-700 dark:text-amber-300">
                    {flag.message}
                  </div>
                ))
              )}
            </div>
          </section>
        </aside>
      </section>
    </div>
  );
}

function RiskMetric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return <div className="bg-card px-4 py-3"><p className="text-[10px] text-muted-foreground">{label}</p><p className={`mt-1 font-mono text-sm font-medium ${tone ?? ""}`}>{value}</p></div>;
}

function Diagnostic({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return <div className="flex items-center justify-between gap-4"><span className="text-muted-foreground">{label}</span><span className={`font-mono ${tone ?? ""}`}>{value}</span></div>;
}
