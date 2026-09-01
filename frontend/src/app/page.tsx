"use client";

import Link from "next/link";
import useSWR from "swr";
import { Bell, ChevronRight, ListOrdered, Radar, ShieldCheck } from "lucide-react";
import { getAgentCandidates, getKisAutonomousStatus, getKisBalance, getKisBrokerOrders, getKisBuyingPower, getKisPortfolioHistory, getPriceAlerts, getWatchlist } from "@/lib/api";
import { changeColorClass, formatChangePct, formatPrice } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RefreshBadge } from "@/components/refresh-badge";
import { EquityChart } from "@/components/equity-chart";
import { AiOperationsPanel } from "@/components/ai-operations-panel";
import { MarketWorkbench } from "@/components/market-workbench";
import { MarketNewsPanel } from "@/components/market-news-panel";

const KRW = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
const EMBEDDED_CARD = "h-full min-w-0 gap-0 rounded-none border-0 py-0 shadow-none ring-0";

export default function DashboardPage() {
  const kisBalance = useSWR("/api/kis/balance", getKisBalance, { refreshInterval: 10000 });
  const kisBuyingPower = useSWR("/api/kis/buying-power", () => getKisBuyingPower(), { refreshInterval: 10000 });
  const kisHistory = useSWR("/api/kis/history", getKisPortfolioHistory, { refreshInterval: 10000 });
  const kisOrders = useSWR("/api/kis/broker-orders", getKisBrokerOrders, { refreshInterval: 10000 });
  const kisEngine = useSWR("/api/kis/autonomous/status", getKisAutonomousStatus, { refreshInterval: 5000 });
  const watchlist = useSWR("/api/watchlist", getWatchlist, { refreshInterval: 10000 });
  const candidates = useSWR("/api/agent/candidates", getAgentCandidates, { refreshInterval: 15000 });
  const alerts = useSWR("/api/alerts", () => getPriceAlerts(), { refreshInterval: 15000 });

  const refresh = () => { kisBalance.mutate(); kisBuyingPower.mutate(); kisHistory.mutate(); kisOrders.mutate(); kisEngine.mutate(); watchlist.mutate(); candidates.mutate(); alerts.mutate(); };
  const totalValue = kisBalance.data?.total_value;
  const cash = kisBalance.data?.cash;
  const pnl = kisBalance.data?.pnl;
  const evaluatedValue = kisBalance.data?.evaluated_value;
  const investedRatioPct = totalValue ? (evaluatedValue ?? 0) / totalValue * 100 : undefined;
  const positions = (kisBalance.data?.positions ?? []).map((position) => ({
        code: position.code,
        quantity: position.quantity,
        avg_price: position.avg_price,
        current_price: position.current_price,
        market_value: position.market_value,
        unrealized_pnl: position.pnl,
        return_pct: position.return_pct,
        weight_pct: totalValue ? position.market_value / totalValue * 100 : 0,
      }));
  const ownedCodes = positions.map((position) => position.code);
  const nameByCode = new Map([
    ...(candidates.data ?? []).map((stock) => [stock.code, stock.name] as const),
    ...(watchlist.data ?? []).map((stock) => [stock.code, stock.name] as const),
    ...(kisBalance.data?.positions ?? []).map((position) => [position.code, position.name] as const),
  ]);
  const recentOrders = (kisOrders.data ?? []).slice(0, 6).map((order) => ({ id: order.broker_order_id, status: order.status, side: order.side, code: order.code, order_type: "market", quantity: order.requested_quantity, filled_quantity: order.filled_quantity, price: order.avg_fill_price ?? 0, time: formatKisOrderTime(order.order_time) }));
  const pendingOrders = (kisOrders.data ?? []).filter((order) => order.remaining_quantity > 0).length;
  const orderableCash = kisBuyingPower.data?.cash_only_buying_power ?? kisBuyingPower.data?.orderable_cash;
  const reservedCash = cash !== undefined && cash !== null && orderableCash !== undefined && orderableCash !== null
    ? Math.max(0, cash - orderableCash)
    : 0;
  const activeAlerts = (alerts.data ?? []).filter((alert) => alert.active).length;
  const chartData = kisHistory.data?.map((snapshot) => ({ time: snapshot.ts, value: snapshot.total_value })) ?? [];
  const dataError = kisBalance.error || kisBuyingPower.error || kisOrders.error || kisEngine.error;
  const validating = kisBalance.isValidating || kisBuyingPower.isValidating || kisOrders.isValidating;

  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <section className="grid border-b border-border xl:grid-cols-12">
        <header className="flex min-h-24 items-center justify-between gap-4 border-b border-border px-5 py-4 xl:col-span-4 xl:border-b-0 xl:border-r">
          <div>
            <p className="text-[9px] font-medium text-muted-foreground">AI OPERATIONS</p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight">AI 운용 콘솔</h1>
            <p className="mt-2 text-[9px] font-medium text-emerald-600 dark:text-emerald-400">KIS 모의계좌 · 자동운용</p>
            <p className="mt-1 font-mono text-[9px] text-muted-foreground">{kisBalance.data?.account_masked ?? "KIS 연결 확인 중"}</p>
          </div>
          <RefreshBadge hasError={Boolean(dataError)} isValidating={validating} onRefresh={refresh} />
        </header>
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:col-span-8 xl:grid-cols-6">
          <Metric label="총자산" value={formatPrice(totalValue ?? null)} />
          <Metric label="예수금" value={formatPrice(cash ?? null)} />
          <Metric label="미체결 예약" value={formatPrice(reservedCash)} tone="text-amber-600 dark:text-amber-400" />
          <Metric label="실제 주문 가능" value={formatPrice(orderableCash ?? null)} tone="text-emerald-600 dark:text-emerald-400" />
          <Metric label="투자 비중" value={investedRatioPct === undefined ? "-" : `${investedRatioPct.toFixed(1)}%`} />
          <Metric label="평가손익" value={formatPrice(pnl ?? null)} tone={changeColorClass(pnl ?? null)} />
        </div>
      </section>

      <section className="grid border-b border-border xl:h-[330px] xl:grid-cols-12">
        <Card className={`${EMBEDDED_CARD} border-b border-border xl:col-span-7 xl:border-b-0 xl:border-r`}>
          <CardHeader className="flex min-h-14 flex-row items-center justify-between border-b bg-muted/25 px-4 py-3">
            <div><CardTitle className="text-sm">보유 종목</CardTitle><p className="mt-0.5 text-[9px] text-muted-foreground">KIS 모의계좌 / 전체 {positions.length}종목 / 투자금 {formatPrice(evaluatedValue ?? null)}</p></div>
            <div className="flex items-center gap-3"><span className="font-mono text-[9px] text-emerald-600 dark:text-emerald-400">투자 비중 {investedRatioPct?.toFixed(2) ?? "-"}%</span><Link href="/risk" className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground">리스크 상세<ChevronRight className="h-3 w-3" /></Link></div>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 overflow-auto p-0">
            <Table>
              <TableHeader><TableRow><TableHead>종목</TableHead><TableHead className="text-right">현재가</TableHead><TableHead className="text-right">평가금액</TableHead><TableHead className="text-right">평가손익</TableHead><TableHead className="text-right">수익률</TableHead><TableHead className="text-right">비중</TableHead></TableRow></TableHeader>
              <TableBody>{positions.length === 0 ? <TableRow><TableCell colSpan={6} className="h-28 text-center text-muted-foreground">보유 종목이 없습니다.</TableCell></TableRow> : positions.map((position) => (
                <TableRow key={position.code}>
                  <TableCell><Link href={`/stocks/${position.code}`} className="text-xs font-medium hover:underline">{nameByCode.get(position.code) ?? position.code}</Link><p className="mt-0.5 font-mono text-[9px] text-muted-foreground">{position.code} / {position.quantity}주</p></TableCell>
                  <TableCell className="text-right font-mono text-xs">{formatPrice(position.current_price)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{formatPrice(position.market_value)}</TableCell>
                  <TableCell className={`text-right font-mono text-xs ${changeColorClass(position.unrealized_pnl)}`}>{formatPrice(position.unrealized_pnl)}</TableCell>
                  <TableCell className={`text-right font-mono text-xs ${changeColorClass(position.return_pct)}`}>{formatChangePct(position.return_pct)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{position.weight_pct.toFixed(1)}%</TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          </CardContent>
        </Card>
        <div className="min-h-0 min-w-0 xl:col-span-5"><MarketNewsPanel codes={ownedCodes} compact className="h-full rounded-none border-0 shadow-none" /></div>
      </section>

      <MarketWorkbench className="rounded-none border-0 border-b border-border shadow-none" />

      <section className="grid border-b border-border xl:h-[330px] xl:grid-cols-12">
        <Card className={`${EMBEDDED_CARD} border-b border-border xl:col-span-6 xl:border-b-0 xl:border-r`}>
          <CardHeader className="min-h-14 border-b bg-muted/25 px-4 py-3"><CardTitle className="text-sm">자산 곡선</CardTitle></CardHeader>
          <CardContent className="min-h-0 flex-1 p-4">{chartData.length > 0 ? <EquityChart data={chartData} /> : <EmptyCopy title="기록 없음" text="체결이 쌓이면 자산 곡선이 표시됩니다." />}</CardContent>
        </Card>
        <Operations pendingOrders={pendingOrders} activeAlerts={activeAlerts} riskFlags={kisEngine.data?.last_error ? 1 : 0} />
        <AiOperationsPanel />
      </section>

      <Card className={`${EMBEDDED_CARD} max-h-[310px]`}>
        <CardHeader className="flex min-h-14 flex-row items-center justify-between border-b bg-muted/25 px-4 py-3"><div><CardTitle className="text-sm">최근 주문</CardTitle><p className="mt-0.5 text-[9px] text-muted-foreground">한국투자증권 당일 주문 및 체결</p></div><Link href="/orders" className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground">전체 주문<ChevronRight className="h-3 w-3" /></Link></CardHeader>
        <CardContent className="overflow-auto p-0"><Table><TableHeader><TableRow><TableHead>상태</TableHead><TableHead>구분</TableHead><TableHead>종목</TableHead><TableHead>유형</TableHead><TableHead className="text-right">주문 / 체결</TableHead><TableHead className="text-right">평균 체결가</TableHead><TableHead className="text-right">시간</TableHead></TableRow></TableHeader><TableBody>{recentOrders.length === 0 ? <TableRow><TableCell colSpan={7} className="h-24 text-center text-muted-foreground">주문 기록이 없습니다.</TableCell></TableRow> : recentOrders.map((order) => <TableRow key={order.id}><TableCell className="text-xs text-muted-foreground">{order.status === "partial" ? "부분체결" : order.status === "pending" ? "대기" : order.status === "filled" ? "체결" : order.status}</TableCell><TableCell className={order.side === "buy" ? "text-red-500" : "text-blue-500"}>{order.side === "buy" ? "매수" : "매도"}</TableCell><TableCell className="font-mono font-medium">{order.code}</TableCell><TableCell className="text-muted-foreground">{order.order_type === "limit" ? "지정가" : "시장가"}</TableCell><TableCell className="text-right font-mono">{order.quantity} / {order.filled_quantity}</TableCell><TableCell className="text-right font-mono">{order.price ? `${KRW.format(order.price)}원` : "-"}</TableCell><TableCell className="text-right text-xs text-muted-foreground">{order.time}</TableCell></TableRow>)}</TableBody></Table></CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) { return <div className="flex min-h-24 flex-col justify-center border-b border-r border-border px-4 last:border-r-0 sm:[&:nth-last-child(-n+3)]:border-b-0 xl:border-b-0"><p className="text-[9px] text-muted-foreground">{label}</p><p className={`mt-1.5 font-mono text-sm font-medium ${tone ?? "text-foreground"}`}>{value}</p></div>; }

function formatKisOrderTime(value: string) { return value.length === 6 ? `${value.slice(0, 2)}:${value.slice(2, 4)}:${value.slice(4, 6)}` : value || "-"; }

function Operations({ pendingOrders, activeAlerts, riskFlags }: { pendingOrders: number; activeAlerts: number; riskFlags: number }) {
  const links = [{ href: "/orders", icon: ListOrdered, label: "대기 주문", value: `${pendingOrders}건` }, { href: "/alerts", icon: Bell, label: "활성 알림", value: `${activeAlerts}건` }, { href: "/risk", icon: ShieldCheck, label: "리스크 신호", value: `${riskFlags}건` }, { href: "/screener", icon: Radar, label: "시장 스크리너", value: "열기" }];
  return <section className="border-b border-border bg-card xl:col-span-3 xl:border-b-0 xl:border-r"><header className="min-h-14 border-b border-border bg-muted/25 px-4 py-3"><h2 className="text-sm font-semibold">운영 센터</h2><p className="text-[9px] text-muted-foreground">주문과 위험 신호</p></header><div className="grid grid-cols-2">{links.map((item) => <Link key={item.href} href={item.href} className="flex min-h-[108px] flex-col justify-between border-b border-r border-border p-3 transition even:border-r-0 [&:nth-last-child(-n+2)]:border-b-0 hover:bg-muted/40"><item.icon className="h-3.5 w-3.5 text-muted-foreground" /><span><span className="block text-[9px] text-muted-foreground">{item.label}</span><span className="mt-1 block font-mono text-xs font-medium">{item.value}</span></span></Link>)}</div></section>;
}

function EmptyCopy({ title, text }: { title: string; text: string }) { return <div className="flex h-full flex-col items-center justify-center text-center"><p className="text-xs font-medium">{title}</p><p className="mt-1 text-[10px] text-muted-foreground">{text}</p></div>; }
