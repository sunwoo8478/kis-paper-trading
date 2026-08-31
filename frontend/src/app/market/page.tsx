import { MarketWorkbench } from "@/components/market-workbench";
import { MarketNewsPanel } from "@/components/market-news-panel";

export default function MarketPage() {
  return (
    <div className="space-y-5">
      <header>
        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Market monitor</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">국내 시장</h1>
        <p className="mt-2 text-sm text-muted-foreground">주요 지수와 실시간 종목 순위, 시장 뉴스를 함께 확인합니다.</p>
      </header>
      <MarketWorkbench expanded />
      <MarketNewsPanel marketMode />
    </div>
  );
}
