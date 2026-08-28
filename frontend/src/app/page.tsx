"use client";

import useSWR from "swr";
import { getPortfolio, getPortfolioHistory } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RefreshBadge } from "@/components/refresh-badge";
import { EquityChart } from "@/components/equity-chart";

const KRW = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

export default function DashboardPage() {
  const portfolio = useSWR("/api/portfolio", getPortfolio, { refreshInterval: 10000 });
  const history = useSWR("/api/portfolio/history", getPortfolioHistory, { refreshInterval: 10000 });

  const hasError = Boolean(portfolio.error || history.error);
  const isValidating = portfolio.isValidating || history.isValidating;

  const refresh = () => {
    portfolio.mutate();
    history.mutate();
  };

  const positions = portfolio.data?.positions ?? [];
  const chartData =
    history.data?.map((snapshot) => ({ time: snapshot.ts, value: snapshot.total_value })) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">대시보드</h1>
        <RefreshBadge hasError={hasError} isValidating={isValidating} onRefresh={refresh} />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <SummaryCard label="총자산" value={portfolio.data ? `${KRW.format(portfolio.data.total_value)}원` : "-"} />
        <SummaryCard label="현금" value={portfolio.data ? `${KRW.format(portfolio.data.cash)}원` : "-"} />
        <SummaryCard
          label="평가금액"
          value={portfolio.data ? `${KRW.format(portfolio.data.evaluated_value)}원` : "-"}
        />
        <SummaryCard
          label="평가손익"
          value={portfolio.data ? `${KRW.format(portfolio.data.unrealized_pnl)}원` : "-"}
          highlight={portfolio.data ? portfolio.data.unrealized_pnl >= 0 : undefined}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>자산추이</CardTitle>
        </CardHeader>
        <CardContent>
          {chartData.length > 0 ? (
            <EquityChart data={chartData} />
          ) : (
            <p className="text-sm text-muted-foreground">아직 쌓인 자산 이력이 없음</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>보유종목</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>종목코드</TableHead>
                <TableHead className="text-right">수량</TableHead>
                <TableHead className="text-right">평단가</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={3} className="text-center text-muted-foreground">
                    보유종목 없음
                  </TableCell>
                </TableRow>
              )}
              {positions.map((position) => (
                <TableRow key={position.code}>
                  <TableCell>{position.code}</TableCell>
                  <TableCell className="text-right">{position.quantity}</TableCell>
                  <TableCell className="text-right">{KRW.format(position.avg_price)}원</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-normal text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p
          className={
            highlight === undefined
              ? "text-lg font-semibold"
              : highlight
                ? "text-lg font-semibold text-red-600"
                : "text-lg font-semibold text-blue-600"
          }
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
