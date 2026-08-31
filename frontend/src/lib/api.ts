export type Stock = {
  code: string;
  name: string;
  market: string;
  last_price: number | null;
  prev_close: number | null;
  change_pct: number | null;
};

export type OhlcvBar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type Order = {
  id: number;
  code: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  filled_at: string;
  status: string;
  order_type: "market" | "limit";
  limit_price: number | null;
};

export type Position = {
  code: string;
  quantity: number;
  avg_price: number;
};

export type Portfolio = {
  cash: number;
  evaluated_value: number;
  total_value: number;
  unrealized_pnl: number;
  positions: Position[];
};

export type PortfolioSnapshot = {
  ts: string;
  total_value: number;
  cash: number;
  evaluated_value: number;
  pnl: number;
};

export type AgentCandidate = Stock & {
  volume: number | null;
};

export type AgentDecision = {
  code: string;
  action: string;
  quantity?: number;
  [key: string]: unknown;
};

export type AgentRun = {
  id: number;
  ts: string;
  candidates: string[];
  decisions: AgentDecision[];
  reasoning: string;
  order_ids: number[];
};

export type AgentStatus = {
  model_connected: boolean;
  provider: string | null;
  model: string | null;
  execution_mode: "observe" | "paper_auto";
  auto_execution_enabled: boolean;
  safety: { max_position_pct: number; max_daily_loss_pct: number; human_approval_required: boolean };
};

export type StockAnalytics = {
  as_of: string | null;
  close: number | null;
  day: { open: number | null; high: number | null; low: number | null; volume: number | null };
  moving_averages: { ma5: number | null; ma20: number | null; ma60: number | null; ma120: number | null };
  momentum: { rsi14: number | null; macd: number | null; macd_signal: number | null; macd_histogram: number | null };
  volatility: {
    annualized_pct: number | null;
    atr14: number | null;
    bollinger_upper: number | null;
    bollinger_middle: number | null;
    bollinger_lower: number | null;
  };
  volume: { average_20: number | null; ratio_20: number | null };
  ranges: { high_20: number | null; low_20: number | null; high_52w: number | null; low_52w: number | null };
  technical_bias: { score: number; label: "bullish" | "neutral" | "bearish" };
};

export type RiskPosition = Position & {
  current_price: number;
  market_value: number;
  cost_basis: number;
  unrealized_pnl: number;
  return_pct: number;
  weight_pct: number;
};

export type PortfolioRisk = Omit<Portfolio, "positions"> & {
  initial_capital: number;
  total_return_pct: number;
  cash_ratio_pct: number;
  invested_ratio_pct: number;
  max_position_weight_pct: number;
  concentration_hhi: number;
  max_drawdown_pct: number;
  positions: RiskPosition[];
  risk_flags: { level: "warning" | "danger"; code: string; message: string }[];
};

export type PriceAlert = {
  id: number;
  code: string;
  direction: "above" | "below";
  target_price: number;
  active: boolean;
  created_at: string;
  triggered_at: string | null;
};

export type JournalEntry = {
  code: string;
  thesis: string;
  invalidation: string;
  target_price: number | null;
  tags: string[];
  updated_at: string | null;
};

export type NewsItem = {
  id: string;
  code: string;
  source: string;
  published_at: string | null;
  title: string;
  summary: string;
  url: string;
  image_url: string | null;
};

export type MarketIndex = {
  symbol: string;
  name: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  market_status: string | null;
  traded_at: string | null;
};

export type RankedStock = {
  code: string;
  name: string;
  market: string | null;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  trading_value: number | null;
  market_value: number | null;
};

export type MarketOverview = {
  indices: MarketIndex[];
  rankings: { gainers: RankedStock[]; losers: RankedStock[]; market_cap: RankedStock[] };
  source: string;
  updated_at: string | null;
};

export type FinancialSeries = {
  periods: { key: string; label: string; consensus: boolean }[];
  metrics: Record<string, Record<string, number | null>>;
};

export type StockInsight = {
  code: string;
  name: string;
  quote: { price: number | null; change: number | null; change_pct: number | null; market_status: string | null; traded_at: string | null; after_hours_price: number | null };
  metrics: Record<string, { label: string; value: string | null; as_of: string | null }>;
  consensus: { score: number | null; target_price: number | null; as_of: string | null };
  investor_flows: { date: string; foreign: number | null; institution: number | null; individual: number | null; foreign_ownership_pct: number | null; close: number | null }[];
  research: { id: string; broker: string; title: string; date: string; views: number | null }[];
  peers: RankedStock[];
  company_summary: string[];
  financials: { annual: FinancialSeries; quarter: FinancialSeries };
  source: string;
};

export type RealtimeSnapshot = {
  code: string;
  name: string;
  market: string | null;
  market_status: string | null;
  traded_at: string | null;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  trading_value: number | null;
  market_value: number | null;
  integrated: { open: number | null; high: number | null; low: number | null; volume: number | null; trading_value: number | null };
  after_hours: { session: string | null; status: string | null; price: number | null; change_pct: number | null; volume: number | null };
  source: string;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function fetcher<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
  return response.json();
}

export async function searchStocks(query: string): Promise<Stock[]> {
  return fetcher<Stock[]>(`/api/stocks?q=${encodeURIComponent(query)}`);
}

export async function getStockHistory(code: string): Promise<OhlcvBar[]> {
  return fetcher<OhlcvBar[]>(`/api/stocks/${code}/history`);
}

export type Quote = {
  code: string;
  price: number;
};

export async function getStockQuote(code: string): Promise<Quote> {
  return fetcher<Quote>(`/api/stocks/${code}/quote`);
}

export async function getWatchlist(): Promise<Stock[]> {
  return fetcher<Stock[]>("/api/watchlist");
}

export async function addToWatchlist(code: string): Promise<void> {
  await postJson("/api/watchlist", { code });
}

export async function removeFromWatchlist(code: string): Promise<void> {
  const response = await fetch(`/api/watchlist/${code}`, { method: "DELETE" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
}

export async function getOrders(): Promise<Order[]> {
  return fetcher<Order[]>("/api/orders");
}

export async function placeOrder(order: {
  code: string;
  side: "buy" | "sell";
  quantity: number;
  order_type?: "market" | "limit";
  limit_price?: number | null;
}): Promise<{ order_id: number; code: string; side: string; quantity: number; fill_price: number | null; status: string; order_type: string; limit_price: number | null }> {
  return postJson("/api/orders", order);
}

export async function cancelOrder(orderId: number): Promise<void> {
  const response = await fetch(`/api/orders/${orderId}`, { method: "DELETE" });
  if (!response.ok) throw new ApiError(response.status, "대기주문 취소 실패");
}

export async function getPortfolio(): Promise<Portfolio> {
  return fetcher<Portfolio>("/api/portfolio");
}

export async function getPortfolioHistory(): Promise<PortfolioSnapshot[]> {
  return fetcher<PortfolioSnapshot[]>("/api/portfolio/history");
}

export async function getAgentCandidates(): Promise<AgentCandidate[]> {
  return fetcher<AgentCandidate[]>("/api/agent/candidates");
}

export async function getAgentRuns(): Promise<AgentRun[]> {
  return fetcher<AgentRun[]>("/api/agent/runs");
}

export async function getAgentStatus(): Promise<AgentStatus> {
  return fetcher<AgentStatus>("/api/agent/status");
}

export type ChatResponse = {
  answer: string;
  decisions: AgentDecision[];
  order_ids: number[];
  blocked: { decision: AgentDecision; reason: string }[];
};

export async function askCopilot(
  prompt: string,
  scope: string,
  stockCode: string | null
): Promise<ChatResponse> {
  return postJson<ChatResponse>("/api/agent/chat", { prompt, scope, stock_code: stockCode });
}

export type CopilotChatMessage = { role: "user" | "assistant"; content: string };
export type CopilotMeta = { order_ids: number[]; blocked: { decision: AgentDecision; reason: string }[] };
const COPILOT_META_MARKER = "<<<COPILOT_META>>>";

export async function streamCopilot(
  prompt: string,
  scope: string,
  stockCode: string | null,
  history: CopilotChatMessage[],
  onChunk: (visibleTextSoFar: string) => void
): Promise<CopilotMeta> {
  const response = await fetch("/api/agent/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, scope, stock_code: stockCode, history }),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let visibleFrozen = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    if (!visibleFrozen) {
      const markerIndex = buffer.indexOf(COPILOT_META_MARKER);
      const jsonFenceIndex = buffer.indexOf("```json");
      const cutoff = markerIndex >= 0 ? markerIndex : jsonFenceIndex >= 0 ? jsonFenceIndex : buffer.length;
      onChunk(buffer.slice(0, cutoff));
      if (markerIndex >= 0) visibleFrozen = true;
    }
  }

  const markerIndex = buffer.indexOf(COPILOT_META_MARKER);
  if (markerIndex < 0) return { order_ids: [], blocked: [] };
  try {
    return JSON.parse(buffer.slice(markerIndex + COPILOT_META_MARKER.length));
  } catch {
    return { order_ids: [], blocked: [] };
  }
}

export async function getStockAnalytics(code: string): Promise<StockAnalytics> {
  return fetcher<StockAnalytics>(`/api/stocks/${code}/analytics`);
}

export async function getPortfolioRisk(): Promise<PortfolioRisk> {
  return fetcher<PortfolioRisk>("/api/portfolio/risk");
}

export async function getMarketNews(codes: string[] = [], limit = 20, page = 1): Promise<NewsItem[]> {
  const params = new URLSearchParams({ limit: String(limit), page: String(page) });
  if (codes.length > 0) params.set("codes", codes.join(","));
  return fetcher<NewsItem[]>(`/api/news?${params.toString()}`);
}

export async function getStockNews(code: string, limit = 10, page = 1): Promise<NewsItem[]> {
  return fetcher<NewsItem[]>(`/api/stocks/${code}/news?limit=${limit}&page=${page}`);
}

export async function getMarketOverview(): Promise<MarketOverview> {
  return fetcher<MarketOverview>("/api/market/overview");
}

export async function getStockInsight(code: string): Promise<StockInsight> {
  return fetcher<StockInsight>(`/api/stocks/${code}/insight`);
}

export async function getRealtimeSnapshot(code: string): Promise<RealtimeSnapshot> {
  return fetcher<RealtimeSnapshot>(`/api/stocks/${code}/realtime`);
}

export async function getPriceAlerts(code?: string): Promise<PriceAlert[]> {
  return fetcher<PriceAlert[]>(`/api/alerts${code ? `?code=${encodeURIComponent(code)}` : ""}`);
}

export async function createPriceAlert(input: { code: string; direction: "above" | "below"; target_price: number }): Promise<PriceAlert> {
  return postJson<PriceAlert>("/api/alerts", input);
}

export async function deletePriceAlert(alertId: number): Promise<void> {
  const response = await fetch(`/api/alerts/${alertId}`, { method: "DELETE" });
  if (!response.ok) throw new ApiError(response.status, "가격 알림 삭제 실패");
}

export async function getJournalEntry(code: string): Promise<JournalEntry> {
  return fetcher<JournalEntry>(`/api/journal/${code}`);
}

export async function saveJournalEntry(code: string, entry: Omit<JournalEntry, "code" | "updated_at">): Promise<JournalEntry> {
  const response = await fetch(`/api/journal/${code}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
  if (!response.ok) throw new ApiError(response.status, "트레이딩 저널 저장 실패");
  return response.json();
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new ApiError(response.status, errorBody.detail ?? response.statusText);
  }
  return response.json();
}
