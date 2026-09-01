"use client";

import useSWR from "swr";
import { Activity, Gauge, RefreshCw } from "lucide-react";
import { getStockAnalytics } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function TechnicalAnalysisPanel({ code }: { code: string }) {
  const analytics = useSWR(["/api/stocks", code, "analytics"], () => getStockAnalytics(code), { refreshInterval: 30000 });
  const data = analytics.data;
  const bias = data?.technical_bias;

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" />
          <div>
            <h2 className="text-sm font-semibold">기술 분석</h2>
            <p className="text-[10px] text-muted-foreground">일봉 기준 서버 계산</p>
          </div>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={() => analytics.mutate()} aria-label="기술 분석 새로고침">
          <RefreshCw className={cn("h-3.5 w-3.5", analytics.isValidating && "animate-spin")} />
        </Button>
      </header>

      <div className="grid grid-cols-[1fr_auto] items-center gap-4 border-b border-border px-4 py-4">
        <div>
          <p className="text-[10px] text-muted-foreground">기술 편향</p>
          <p className="mt-1 text-sm font-medium">{bias ? biasLabel(bias.label) : "계산 중"}</p>
          <p className="mt-1 text-[10px] leading-4 text-muted-foreground">추세, 모멘텀, 과열도를 조합한 참고 지표입니다.</p>
        </div>
        <div className={cn("flex h-14 w-14 items-center justify-center rounded-full border font-mono text-lg font-semibold", biasTone(bias?.label))}>
          {bias?.score ?? "-"}
        </div>
      </div>

      <div className="grid grid-cols-2 border-b border-border">
        <AnalysisCell label="RSI 14" value={formatNumber(data?.momentum.rsi14)} detail={rsiLabel(data?.momentum.rsi14)} />
        <AnalysisCell label="MACD 히스토그램" value={formatNumber(data?.momentum.macd_histogram)} detail={signalLabel(data?.momentum.macd_histogram)} />
        <AnalysisCell label="ATR 14" value={formatPrice(data?.volatility.atr14 ?? null)} detail="평균 진폭" />
        <AnalysisCell label="거래량 강도" value={data?.volume.ratio_20 == null ? "-" : `${data.volume.ratio_20.toFixed(2)}x`} detail="20일 평균 대비" />
      </div>

      <div className="px-4 py-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-medium">
          <Gauge className="h-3.5 w-3.5 text-muted-foreground" />
          가격 레벨
        </div>
        <div className="grid grid-cols-2 gap-x-5 gap-y-3">
          <Level label="52주 고가" value={data?.ranges.high_52w ?? null} />
          <Level label="52주 저가" value={data?.ranges.low_52w ?? null} />
          <Level label="볼린저 상단" value={data?.volatility.bollinger_upper ?? null} />
          <Level label="볼린저 하단" value={data?.volatility.bollinger_lower ?? null} />
          <Level label="MA 20" value={data?.moving_averages.ma20 ?? null} />
          <Level label="MA 120" value={data?.moving_averages.ma120 ?? null} />
        </div>
      </div>
    </section>
  );
}

function AnalysisCell({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="border-b border-r border-border px-4 py-3 even:border-r-0 [&:nth-last-child(-n+2)]:border-b-0">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-sm font-medium">{value}</p>
      <p className="mt-0.5 text-[9px] text-muted-foreground">{detail}</p>
    </div>
  );
}

function Level({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{formatPrice(value)}</span>
    </div>
  );
}

function formatNumber(value: number | null | undefined) {
  return value == null ? "-" : value.toFixed(2);
}

function biasLabel(value: "bullish" | "neutral" | "bearish") {
  return value === "bullish" ? "상승 우위" : value === "bearish" ? "하락 우위" : "중립";
}

function biasTone(value?: "bullish" | "neutral" | "bearish") {
  if (value === "bullish") return "border-red-500/30 bg-red-500/5 text-red-500";
  if (value === "bearish") return "border-blue-500/30 bg-blue-500/5 text-blue-500";
  return "border-border bg-muted/40 text-muted-foreground";
}

function rsiLabel(value: number | null | undefined) {
  if (value == null) return "데이터 부족";
  if (value >= 70) return "과매수 구간";
  if (value <= 30) return "과매도 구간";
  return "중립 구간";
}

function signalLabel(value: number | null | undefined) {
  if (value == null) return "데이터 부족";
  return value > 0 ? "상승 모멘텀" : value < 0 ? "하락 모멘텀" : "중립";
}
