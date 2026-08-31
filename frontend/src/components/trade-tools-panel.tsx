"use client";

import { useMemo, useState } from "react";
import { Calculator } from "lucide-react";
import { Input } from "@/components/ui/input";
import { formatPrice } from "@/lib/format";

export function TradeToolsPanel({ currentPrice, availableCash }: { currentPrice: number | null; availableCash: number | null }) {
  const [accountRisk, setAccountRisk] = useState("1");
  const [stopPrice, setStopPrice] = useState(currentPrice ? String(Math.round(currentPrice * 0.95)) : "");
  const [targetPrice, setTargetPrice] = useState(currentPrice ? String(Math.round(currentPrice * 1.1)) : "");
  const result = useMemo(() => {
    const entry = currentPrice ?? 0;
    const cash = availableCash ?? 0;
    const stop = Number(stopPrice);
    const target = Number(targetPrice);
    const riskPct = Number(accountRisk);
    const riskBudget = cash * riskPct / 100;
    const perShareRisk = Math.max(0, entry - stop);
    const riskQuantity = perShareRisk > 0 ? Math.floor(riskBudget / perShareRisk) : 0;
    const cashQuantity = entry > 0 ? Math.floor(cash / entry) : 0;
    const quantity = Math.min(riskQuantity, cashQuantity);
    const expectedProfit = Math.max(0, target - entry) * quantity;
    const expectedLoss = perShareRisk * quantity;
    return { riskBudget, quantity, expectedProfit, expectedLoss, ratio: expectedLoss > 0 ? expectedProfit / expectedLoss : 0 };
  }, [accountRisk, availableCash, currentPrice, stopPrice, targetPrice]);

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <header className="flex items-center gap-2 border-b border-border px-4 py-3"><Calculator className="h-4 w-4 text-muted-foreground" /><div><h2 className="text-sm font-semibold">트레이드 계산기</h2><p className="text-[10px] text-muted-foreground">손절 기준 포지션 크기와 손익 시나리오</p></div></header>
      <div className="grid grid-cols-2 gap-3 p-4">
        <Field label="계좌 위험 비율"><Input type="number" min="0.1" step="0.1" value={accountRisk} onChange={(event) => setAccountRisk(event.target.value)} className="h-9 font-mono" /></Field>
        <Field label="위험 예산"><Readout value={formatPrice(result.riskBudget)} /></Field>
        <Field label="손절 가격"><Input type="number" value={stopPrice} onChange={(event) => setStopPrice(event.target.value)} className="h-9 font-mono" /></Field>
        <Field label="목표 가격"><Input type="number" value={targetPrice} onChange={(event) => setTargetPrice(event.target.value)} className="h-9 font-mono" /></Field>
      </div>
      <div className="grid grid-cols-2 border-t border-border">
        <Result label="권장 수량" value={`${result.quantity.toLocaleString("ko-KR")}주`} />
        <Result label="손익비" value={result.ratio ? `1 : ${result.ratio.toFixed(2)}` : "-"} />
        <Result label="예상 이익" value={formatPrice(result.expectedProfit)} tone="text-red-500" />
        <Result label="예상 손실" value={formatPrice(-result.expectedLoss)} tone="text-blue-500" />
      </div>
      <p className="border-t border-border px-4 py-3 text-[9px] leading-4 text-muted-foreground">계산 결과는 주문 전 계획을 위한 참고값입니다. 슬리피지와 수수료는 포함하지 않습니다.</p>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="space-y-1.5"><span className="text-[9px] text-muted-foreground">{label}</span>{children}</label>; }
function Readout({ value }: { value: string }) { return <div className="flex h-9 items-center rounded-lg border border-input bg-muted/25 px-3 font-mono text-xs">{value}</div>; }
function Result({ label, value, tone }: { label: string; value: string; tone?: string }) { return <div className="border-b border-r border-border px-4 py-3 even:border-r-0 [&:nth-last-child(-n+2)]:border-b-0"><p className="text-[9px] text-muted-foreground">{label}</p><p className={`mt-1 font-mono text-xs font-medium ${tone ?? ""}`}>{value}</p></div>; }
