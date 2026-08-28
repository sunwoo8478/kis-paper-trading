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
}): Promise<{ order_id: number; code: string; side: string; quantity: number; fill_price: number }> {
  return postJson("/api/orders", order);
}

export async function getPortfolio(): Promise<Portfolio> {
  return fetcher<Portfolio>("/api/portfolio");
}

export async function getPortfolioHistory(): Promise<PortfolioSnapshot[]> {
  return fetcher<PortfolioSnapshot[]>("/api/portfolio/history");
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
