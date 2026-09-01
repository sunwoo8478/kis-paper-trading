"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Activity, Bell, BookOpen, Bot, Building2, Newspaper, RefreshCw, ShoppingCart, Star, Wrench } from "lucide-react";
import { ApiError, addToWatchlist, type OhlcvBar, getKisBalance, getKisBrokerOrders, getKisBuyingPower, getStockHistory, getStockQuote, getWatchlist, removeFromWatchlist, searchStocks } from "@/lib/api";
import { changeColorClass, formatChangePct, formatPrice } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CandleChart } from "@/components/candle-chart";
import { OrderForm } from "@/components/order-form";
import { RefreshBadge } from "@/components/refresh-badge";
import { AiResearchPanel } from "@/components/ai-research-panel";
import { TechnicalAnalysisPanel } from "@/components/technical-analysis-panel";
import { PriceAlertPanel } from "@/components/price-alert-panel";
import { TradeJournalPanel } from "@/components/trade-journal-panel";
import { MarketNewsPanel } from "@/components/market-news-panel";
import { StockInsightPanel } from "@/components/stock-insight-panel";
import { RealtimeQuoteStrip } from "@/components/realtime-quote-strip";
import { TradeToolsPanel } from "@/components/trade-tools-panel";
import { cn } from "@/lib/utils";

type Timeframe = "1M" | "3M" | "6M" | "1Y" | "ALL";
type WorkspaceTab = "order" | "analysis" | "insight" | "tools" | "ai" | "news" | "alerts" | "journal";

const TIMEFRAMES: { key: Timeframe; label: string; limit: number | null }[] = [
  { key: "1M", label: "1M", limit: 22 }, { key: "3M", label: "3M", limit: 66 }, { key: "6M", label: "6M", limit: 132 }, { key: "1Y", label: "1Y", limit: 252 }, { key: "ALL", label: "전체", limit: null },
];
const KRW = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

export default function StockDetailPage() {
  const params = useParams<{ code: string }>();
  const code = Array.isArray(params.code) ? params.code[0] : params.code;
  const [timeframe, setTimeframe] = useState<Timeframe>("3M");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("order");
  const history = useSWR(["/api/stocks", code, "history"], () => getStockHistory(code), { refreshInterval: 10000 });
  const watchlist = useSWR("/api/watchlist", getWatchlist, { refreshInterval: 10000 });
  const quote = useSWR(["/api/stocks", code, "quote"], async () => (await searchStocks(code)).find((stock) => stock.code === code) ?? null);
  const liveQuote = useSWR(["/api/stocks", code, "live-quote"], () => getStockQuote(code), { refreshInterval: 8000, onErrorRetry: () => {} });
  const kisBalance = useSWR("/api/kis/balance", getKisBalance, { refreshInterval: 10000 });
  const kisOrders = useSWR("/api/kis/broker-orders", getKisBrokerOrders, { refreshInterval: 10000 });
  const kisBuyingPower = useSWR(["/api/kis/buying-power", code], () => getKisBuyingPower(code), { refreshInterval: 10000 });
  const historyData = history.data ?? [];
  const chartData = selectHistory(historyData, timeframe);
  const watched = (watchlist.data ?? []).some((stock) => stock.code === code);
  const cash = kisBalance.data?.cash ?? null;
  const orderableCash = kisBuyingPower.data?.orderable_cash ?? null;
  const totalValue = kisBalance.data?.total_value ?? null;
  const evaluatedValue = kisBalance.data?.evaluated_value ?? null;
  const kisPosition = (kisBalance.data?.positions ?? []).find((entry) => entry.code === code) ?? null;
  const position = kisPosition && { quantity: kisPosition.quantity, avg_price: kisPosition.avg_price };
  const positionQuantity = kisPosition?.available_quantity ?? 0;
  const recentOrders = (kisOrders.data ?? [])
        .filter((order) => order.code === code)
        .slice(0, 5)
        .map((order) => ({
          id: order.broker_order_id,
          side: order.side,
          quantity: order.filled_quantity || order.requested_quantity,
          price: order.avg_fill_price ?? 0,
          filled_at: order.order_time,
        }));
  const latestBar = historyData.at(-1) ?? null;
  const technicals = calculateTechnicals(historyData);
  const currentPrice = liveQuote.data?.price ?? quote.data?.last_price ?? latestBar?.close ?? null;
  const prevClose = quote.data?.prev_close ?? null;
  const changePct = liveQuote.data && prevClose ? ((liveQuote.data.price - prevClose) / prevClose) * 100 : quote.data?.change_pct ?? null;

  const toggleWatch = async () => {
    try { if (watched) await removeFromWatchlist(code); else await addToWatchlist(code); watchlist.mutate(); }
    catch (error) { toast.error(error instanceof ApiError ? error.message : "관심종목 처리 실패"); }
  };
  const refreshAll = () => { history.mutate(); watchlist.mutate(); quote.mutate(); liveQuote.mutate(); kisBalance.mutate(); kisOrders.mutate(); kisBuyingPower.mutate(); };

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <section className="grid border-b border-border xl:grid-cols-12">
        <div className="flex min-h-28 items-center justify-between gap-4 border-b border-border px-5 py-4 xl:col-span-4 xl:border-b-0 xl:border-r">
          <div>
            <div className="flex items-center gap-1.5"><Badge variant="outline" className="rounded-md bg-transparent text-[9px]">{quote.data?.market ?? "시장"}</Badge><Badge variant="outline" className="rounded-md bg-transparent font-mono text-[9px]">{code}</Badge>{watched && <Badge className="rounded-md bg-foreground text-background">관심</Badge>}</div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">{quote.data ? quote.data.name : code}</h1>
            <p className="mt-1 text-[10px] text-muted-foreground">가격, 주문, 수급, 재무와 리서치</p>
          </div>
          <RefreshBadge hasError={Boolean(history.error || kisBalance.error || kisOrders.error || kisBuyingPower.error)} isValidating={history.isValidating || kisBalance.isValidating || kisOrders.isValidating || kisBuyingPower.isValidating} onRefresh={refreshAll} />
        </div>
        <div className="xl:col-span-8">
          <div className="flex min-h-11 items-center justify-end gap-2 border-b border-border px-3"><Button variant="ghost" size="sm" onClick={toggleWatch}><Star className="h-3.5 w-3.5" />{watched ? "관심 해제" : "관심 추가"}</Button><Button variant="ghost" size="sm" onClick={refreshAll}><RefreshCw className="h-3.5 w-3.5" />새로고침</Button></div>
          <div className="grid grid-cols-2 sm:grid-cols-4"><Metric label="현재가" value={formatPrice(currentPrice)} tone={changeColorClass(changePct)} /><Metric label="전일대비" value={formatChangePct(changePct)} tone={changeColorClass(changePct)} /><Metric label="보유수량" value={position ? `${position.quantity}주` : "-"} /><Metric label="평단가" value={position ? formatPrice(position.avg_price) : "-"} /></div>
          <p className="px-4 pb-2 text-[9px] text-muted-foreground">KIS 모의계좌 기준</p>
        </div>
      </section>

      <section className="grid items-stretch border-b border-border xl:grid-cols-12">
        <Card className="gap-0 rounded-none border-0 bg-card py-0 shadow-none ring-0 xl:col-span-8 xl:border-r 2xl:col-span-9">
          <CardHeader className="flex min-h-14 flex-col gap-3 border-b bg-muted/25 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"><CardTitle className="text-sm">가격 차트</CardTitle><div className="flex gap-1">{TIMEFRAMES.map((option) => <Button key={option.key} type="button" size="sm" variant={timeframe === option.key ? "default" : "ghost"} onClick={() => setTimeframe(option.key)}>{option.label}</Button>)}</div></CardHeader>
          <RealtimeQuoteStrip code={code} />
          <CardContent className="p-4">
            {chartData.length > 0 ? <div>
              <div className="mb-2 flex flex-wrap items-center gap-4 text-[9px] text-muted-foreground"><Legend color="bg-amber-500" label="MA20" /><Legend color="bg-violet-500" label="MA60" /><Legend color="bg-rose-500/40" label="상승 거래량" /><Legend color="bg-blue-500/40" label="하락 거래량" /></div>
              <CandleChart data={chartData} height={460} />
              <div className="mt-3 grid grid-cols-2 divide-x divide-y divide-border border-y border-border sm:grid-cols-3 xl:grid-cols-6 xl:divide-y-0"><TechnicalMetric label="일중 고가" value={formatPrice(latestBar?.high ?? null)} /><TechnicalMetric label="일중 저가" value={formatPrice(latestBar?.low ?? null)} /><TechnicalMetric label="MA20" value={formatPrice(technicals.ma20)} /><TechnicalMetric label="MA60" value={formatPrice(technicals.ma60)} /><TechnicalMetric label="거래량 강도" value={technicals.volumeRatio === null ? "-" : `${technicals.volumeRatio.toFixed(2)}x`} /><TechnicalMetric label="연환산 변동성" value={technicals.volatility === null ? "-" : `${technicals.volatility.toFixed(1)}%`} /></div>
              <div className="mt-3 grid gap-5 sm:grid-cols-2"><RangeBar label="20일 가격 위치" low={technicals.low20} high={technicals.high20} current={currentPrice} /><RangeBar label="보유 평단 위치" low={technicals.low20} high={technicals.high20} current={position?.avg_price ?? null} /></div>
            </div> : <EmptyCopy title="가격 데이터 없음" text="시장 데이터가 아직 적재되지 않았습니다." />}
          </CardContent>
        </Card>

        <aside className="min-h-0 xl:col-span-4 2xl:col-span-3">
          <section className="flex h-full min-h-[700px] flex-col overflow-hidden bg-muted/15">
            <div className="grid grid-cols-8 border-b border-border bg-card p-1">{WORKSPACE_TABS.map((tab) => <button key={tab.key} type="button" onClick={() => setWorkspaceTab(tab.key)} className={cn("flex min-w-0 flex-col items-center gap-1 rounded-lg px-0.5 py-2 text-[8px] transition", workspaceTab === tab.key ? "bg-foreground text-background shadow-sm" : "text-muted-foreground hover:bg-muted hover:text-foreground")}><tab.icon className="h-3.5 w-3.5" /><span>{tab.label}</span></button>)}</div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {workspaceTab === "order" && <Card className="gap-0 border-border bg-card py-0 shadow-none"><CardHeader className="border-b bg-muted/25 px-4 py-3"><CardTitle className="text-sm">KIS 주문 실행</CardTitle></CardHeader><CardContent className="p-4"><OrderForm code={code} currentPrice={currentPrice} availableCash={orderableCash} positionQuantity={positionQuantity} onOrdered={() => { history.mutate(); kisBalance.mutate(); kisOrders.mutate(); kisBuyingPower.mutate(); }} /></CardContent></Card>}
              {workspaceTab === "analysis" && <TechnicalAnalysisPanel code={code} />}{workspaceTab === "insight" && <StockInsightPanel code={code} />}{workspaceTab === "tools" && <TradeToolsPanel currentPrice={currentPrice} availableCash={orderableCash} />}{workspaceTab === "ai" && <AiResearchPanel code={code} />}{workspaceTab === "news" && <MarketNewsPanel stockCode={code} compact />}{workspaceTab === "alerts" && <PriceAlertPanel code={code} currentPrice={currentPrice} />}{workspaceTab === "journal" && <TradeJournalPanel code={code} />}
            </div>
          </section>
        </aside>
      </section>

      <section className="grid xl:grid-cols-12">
        <Card className="gap-0 rounded-none border-0 border-b bg-card py-0 shadow-none ring-0 xl:col-span-4 xl:border-b-0 xl:border-r"><CardHeader className="min-h-14 border-b bg-muted/25 px-4 py-3"><CardTitle className="text-sm">포지션 요약</CardTitle></CardHeader><CardContent className="grid grid-cols-2 gap-x-5 gap-y-3 p-5 text-xs"><Line label="총자산" value={formatPrice(totalValue)} /><Line label="현금" value={formatPrice(cash)} /><Line label="평가금액" value={formatPrice(evaluatedValue)} /><Line label="평가손익" value={position && currentPrice !== null ? `${KRW.format((currentPrice - position.avg_price) * position.quantity)}원` : "-"} /></CardContent></Card>
        <Card className="gap-0 rounded-none border-0 bg-card py-0 shadow-none ring-0 xl:col-span-8"><CardHeader className="min-h-14 border-b bg-muted/25 px-4 py-3"><CardTitle className="text-sm">최근 주문</CardTitle></CardHeader><CardContent className="grid gap-0 p-0 sm:grid-cols-2 xl:grid-cols-5">{recentOrders.length === 0 ? <div className="p-4 sm:col-span-2 xl:col-span-5"><EmptyCopy title="주문 없음" text="이 종목의 주문 기록이 아직 없습니다." /></div> : recentOrders.map((order) => <div key={order.id} className="border-b border-r border-border px-3 py-3 last:border-r-0"><div className="flex items-center justify-between gap-2"><p className={cn("text-[10px] font-medium", order.side === "buy" ? "text-red-500" : "text-blue-500")}>{order.side === "buy" ? "매수" : "매도"}</p><p className="font-mono text-[9px] text-muted-foreground">{order.quantity}주</p></div><p className="mt-1 font-mono text-xs">{KRW.format(order.price)}원</p><p className="mt-1 text-[8px] text-muted-foreground">{new Date(order.filled_at).toLocaleString("ko-KR")}</p></div>)}</CardContent></Card>
      </section>
    </div>
  );
}

const WORKSPACE_TABS: { key: WorkspaceTab; label: string; icon: typeof ShoppingCart }[] = [
  { key: "order", label: "주문", icon: ShoppingCart }, { key: "analysis", label: "분석", icon: Activity }, { key: "insight", label: "기업", icon: Building2 }, { key: "tools", label: "도구", icon: Wrench }, { key: "ai", label: "AI", icon: Bot }, { key: "news", label: "뉴스", icon: Newspaper }, { key: "alerts", label: "알림", icon: Bell }, { key: "journal", label: "저널", icon: BookOpen },
];

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) { return <div className="flex min-h-[68px] flex-col justify-center border-r border-border px-4 last:border-r-0"><p className="text-[9px] text-muted-foreground">{label}</p><p className={`mt-1 font-mono text-sm font-medium ${tone ?? "text-foreground"}`}>{value}</p></div>; }
function Line({ label, value }: { label: string; value: string }) { return <div className="flex items-center justify-between gap-3"><span className="text-muted-foreground">{label}</span><span className="font-mono font-medium">{value}</span></div>; }
function EmptyCopy({ title, text }: { title: string; text: string }) { return <div className="border border-dashed border-border bg-muted/20 px-4 py-6 text-center"><p className="text-xs font-medium">{title}</p><p className="mt-1 text-[10px] text-muted-foreground">{text}</p></div>; }
function Legend({ color, label }: { color: string; label: string }) { return <span className="flex items-center gap-1.5"><span className={`h-1 w-3 rounded-full ${color}`} />{label}</span>; }
function TechnicalMetric({ label, value }: { label: string; value: string }) { return <div className="px-3 py-2.5"><p className="text-[8px] text-muted-foreground">{label}</p><p className="mt-1 font-mono text-[10px] font-medium">{value}</p></div>; }
function RangeBar({ label, low, high, current }: { label: string; low: number | null; high: number | null; current: number | null }) { const position = low !== null && high !== null && current !== null && high > low ? Math.min(100, Math.max(0, ((current - low) / (high - low)) * 100)) : null; return <div><div className="flex items-center justify-between text-[9px] text-muted-foreground"><span>{label}</span><span className="font-mono">{position === null ? "-" : `${position.toFixed(0)}%`}</span></div><div className="relative mt-2 h-px bg-border">{position !== null && <span className="absolute top-1/2 h-2.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground" style={{ left: `${position}%` }} />}</div><div className="mt-1.5 flex justify-between font-mono text-[8px] text-muted-foreground"><span>{formatPrice(low)}</span><span>{formatPrice(high)}</span></div></div>; }
function selectHistory(data: OhlcvBar[], timeframe: Timeframe) { const option = TIMEFRAMES.find((entry) => entry.key === timeframe); return !option || option.limit === null ? data : data.slice(-option.limit); }
function calculateTechnicals(data: OhlcvBar[]) { const closes = data.map((bar) => bar.close); const last20 = data.slice(-20); const ma = (period: number) => { if (closes.length < period) return null; const values = closes.slice(-period); return values.reduce((sum, value) => sum + value, 0) / values.length; }; const avgVolume20 = last20.length ? last20.reduce((sum, bar) => sum + bar.volume, 0) / last20.length : null; const latestVolume = data.at(-1)?.volume ?? null; const returns = closes.slice(1).map((close, index) => Math.log(close / closes[index])).filter(Number.isFinite); const mean = returns.length ? returns.reduce((sum, value) => sum + value, 0) / returns.length : 0; const variance = returns.length > 1 ? returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (returns.length - 1) : null; return { ma20: ma(20), ma60: ma(60), high20: last20.length ? Math.max(...last20.map((bar) => bar.high)) : null, low20: last20.length ? Math.min(...last20.map((bar) => bar.low)) : null, volumeRatio: avgVolume20 && latestVolume !== null ? latestVolume / avgVolume20 : null, volatility: variance === null ? null : Math.sqrt(variance) * Math.sqrt(252) * 100 }; }
