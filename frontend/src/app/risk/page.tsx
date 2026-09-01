"use client";

import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { getKisBalance, getKisPortfolioHistory } from "@/lib/api";
import { changeColorClass, formatChangePct, formatPrice } from "@/lib/format";
import { RefreshBadge } from "@/components/refresh-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function RiskPage() {
  const kisBalance = useSWR("/api/kis/balance", getKisBalance, { refreshInterval: 10000 });
  const kisHistory = useSWR("/api/kis/history", getKisPortfolioHistory, { refreshInterval: 10000 });
  const balance = kisBalance.data;
  const initialCapital = balance ? balance.total_value - balance.pnl : 0;
  const kisPositions = (balance?.positions ?? []).map((position) => ({
    ...position,
    cost_basis: position.avg_price * position.quantity,
    unrealized_pnl: position.pnl,
    weight_pct: balance?.total_value ? position.market_value / balance.total_value * 100 : 0,
  }));
  const maxPositionWeight = kisPositions.reduce((max, position) => Math.max(max, position.weight_pct), 0);
  const weights = kisPositions.map((position) => position.weight_pct / 100);
  const kisDrawdown = maxDrawdownPct((kisHistory.data ?? []).map((snapshot) => snapshot.total_value));
  const data = balance ? {
    total_value: balance.total_value,
    total_return_pct: initialCapital ? balance.pnl / initialCapital * 100 : 0,
    invested_ratio_pct: balance.total_value ? balance.evaluated_value / balance.total_value * 100 : 0,
    cash_ratio_pct: balance.total_value ? balance.cash / balance.total_value * 100 : 0,
    max_position_weight_pct: maxPositionWeight,
    max_drawdown_pct: kisDrawdown,
    concentration_hhi: weights.reduce((sum, weight) => sum + weight * weight, 0),
    unrealized_pnl: balance.pnl,
    initial_capital: initialCapital,
    evaluated_value: balance.evaluated_value,
    positions: kisPositions,
    risk_flags: kisPositions.filter((position) => position.weight_pct > 20).map((position) => ({ level: "warning" as const, code: position.code, message: `${position.name} 비중이 20%를 초과했습니다.` })),
  } : undefined;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs text-muted-foreground">Portfolio risk</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">계좌 리스크 워크스페이스</h1>
          <p className="mt-2 text-sm text-muted-foreground">KIS 모의계좌 {balance?.account_masked ?? "연결 확인 중"}의 노출, 집중도와 손익을 점검합니다.</p>
        </div>
        <RefreshBadge hasError={Boolean(kisBalance.error || kisHistory.error)} isValidating={kisBalance.isValidating || kisHistory.isValidating} onRefresh={() => Promise.all([kisBalance.mutate(), kisHistory.mutate()])} />
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
                      <TableCell><Link href={`/stocks/${position.code}`} className="font-medium hover:underline">{position.name}<span className="ml-2 font-mono text-[10px] text-muted-foreground">{position.code}</span></Link></TableCell>
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

function maxDrawdownPct(values: number[]) {
  let peak = 0;
  let maxDrawdown = 0;
  for (const value of values) {
    peak = Math.max(peak, value);
    if (peak > 0) maxDrawdown = Math.min(maxDrawdown, (value - peak) / peak * 100);
  }
  return maxDrawdown;
}
