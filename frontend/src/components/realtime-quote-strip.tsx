"use client";

import useSWR from "swr";
import { getRealtimeSnapshot } from "@/lib/api";
import { formatPrice } from "@/lib/format";

export function RealtimeQuoteStrip({ code }: { code: string }) {
  const quote = useSWR(["/api/stocks", code, "realtime"], () => getRealtimeSnapshot(code), {
    refreshInterval: 5000,
    revalidateOnFocus: false,
  });
  const data = quote.data;
  const metrics = [
    ["시가", formatPrice(data?.open ?? null)],
    ["고가", formatPrice(data?.high ?? null)],
    ["저가", formatPrice(data?.low ?? null)],
    ["거래량", compact(data?.volume ?? null)],
    ["거래대금", compactWon(data?.trading_value ?? null)],
    ["시가총액", compactWon(data?.market_value ?? null)],
    ["통합 거래량", compact(data?.integrated.volume ?? null)],
    ["NXT 가격", formatPrice(data?.after_hours.price ?? null)],
  ];

  return (
    <div className="grid grid-cols-4 border-t border-border sm:grid-cols-8">
      {metrics.map(([label, value]) => (
        <div key={label} className="border-b border-r border-border px-3 py-2 sm:border-b-0 last:border-r-0">
          <p className="text-[8px] text-muted-foreground">{label}</p>
          <p className="mt-1 truncate font-mono text-[10px] font-medium">{quote.isLoading ? "-" : value}</p>
        </div>
      ))}
    </div>
  );
}

function compact(value: number | null) {
  return value == null ? "-" : new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function compactWon(value: number | null) {
  return value == null ? "-" : `${new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 }).format(value)}원`;
}
