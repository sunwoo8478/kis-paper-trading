const KRW = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

export function formatPrice(value: number | null): string {
  return value === null ? "-" : `${KRW.format(value)}원`;
}

export function formatChangePct(value: number | null): string {
  if (value === null) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function changeColorClass(value: number | null): string {
  if (value === null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-red-600" : "text-blue-600";
}
