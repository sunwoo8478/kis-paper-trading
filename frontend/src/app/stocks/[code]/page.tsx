"use client";

import { useParams } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import {
  getStockHistory,
  getWatchlist,
  addToWatchlist,
  removeFromWatchlist,
  searchStocks,
  getPortfolio,
  ApiError,
} from "@/lib/api";
import { formatPrice, formatChangePct, changeColorClass } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshBadge } from "@/components/refresh-badge";
import { CandleChart } from "@/components/candle-chart";
import { OrderForm } from "@/components/order-form";

export default function StockDetailPage() {
  const params = useParams<{ code: string }>();
  const code = params.code;

  const history = useSWR(["/api/stocks", code, "history"], () => getStockHistory(code), {
    refreshInterval: 10000,
  });
  const watchlist = useSWR("/api/watchlist", getWatchlist, { refreshInterval: 10000 });
  const quote = useSWR(["/api/stocks", code, "quote"], async () => {
    const results = await searchStocks(code);
    return results.find((s) => s.code === code) ?? null;
  }, { refreshInterval: 10000 });
  const portfolio = useSWR("/api/portfolio", getPortfolio, { refreshInterval: 10000 });

  const isWatched = (watchlist.data ?? []).some((s) => s.code === code);
  const myPosition = (portfolio.data?.positions ?? []).find((p) => p.code === code);

  const toggleWatch = async () => {
    try {
      if (isWatched) {
        await removeFromWatchlist(code);
      } else {
        await addToWatchlist(code);
      }
      watchlist.mutate();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "관심종목 처리 실패");
    }
  };

  const refreshAfterOrder = () => {
    history.mutate();
    portfolio.mutate();
    quote.mutate();
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            {quote.data ? `${quote.data.name} (${code})` : code}
          </h1>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-bold">{formatPrice(quote.data?.last_price ?? null)}</span>
            <span className={changeColorClass(quote.data?.change_pct ?? null)}>
              {formatChangePct(quote.data?.change_pct ?? null)}
            </span>
          </div>
        </div>
        <RefreshBadge
          hasError={Boolean(history.error)}
          isValidating={history.isValidating}
          onRefresh={() => history.mutate()}
        />
      </div>

      {myPosition && (
        <Card>
          <CardContent className="flex items-center gap-6 py-4 text-sm">
            <span>
              보유수량 <span className="font-semibold">{myPosition.quantity}주</span>
            </span>
            <span>
              평단가 <span className="font-semibold">{formatPrice(myPosition.avg_price)}</span>
            </span>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>가격 차트</CardTitle>
          <Button variant="outline" size="sm" onClick={toggleWatch}>
            {isWatched ? "관심종목 해제" : "관심종목 추가"}
          </Button>
        </CardHeader>
        <CardContent>
          {(history.data ?? []).length > 0 ? (
            <CandleChart data={history.data ?? []} />
          ) : (
            <p className="text-sm text-muted-foreground">가격 데이터 없음</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>주문</CardTitle>
        </CardHeader>
        <CardContent>
          <OrderForm
            code={code}
            currentPrice={quote.data?.last_price ?? null}
            onOrdered={refreshAfterOrder}
          />
        </CardContent>
      </Card>
    </div>
  );
}
