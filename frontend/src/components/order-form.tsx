"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { placeOrder, ApiError } from "@/lib/api";
import { formatPrice } from "@/lib/format";

const TOAST_DURATION_MS = 8000;

export function OrderForm({
  code,
  currentPrice,
  availableCash,
  positionQuantity,
  onOrdered,
}: {
  code: string;
  currentPrice: number | null;
  availableCash?: number | null;
  positionQuantity?: number;
  onOrdered: () => void;
}) {
  const [quantity, setQuantity] = useState("1");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [pendingSide, setPendingSide] = useState<"buy" | "sell" | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const parsedQuantity = Number(quantity);
  const parsedLimitPrice = Number(limitPrice);
  const isQuantityValid = Number.isInteger(parsedQuantity) && parsedQuantity > 0;
  const isLimitValid = orderType === "market" || (Number.isFinite(parsedLimitPrice) && parsedLimitPrice > 0);
  const orderPrice = orderType === "limit" && isLimitValid ? parsedLimitPrice : currentPrice;
  const estimatedCost =
    isQuantityValid && orderPrice !== null ? parsedQuantity * orderPrice : null;
  const buyBlocked = availableCash != null && estimatedCost !== null && estimatedCost > availableCash;
  const sellBlocked =
    positionQuantity !== undefined &&
    isQuantityValid &&
    parsedQuantity > positionQuantity;

  const requestOrder = (side: "buy" | "sell") => {
    if (!isQuantityValid) {
      toast.error("수량은 1 이상의 정수여야 함");
      return;
    }
    if (!isLimitValid) {
      toast.error("지정가를 입력해 주세요.");
      return;
    }
    if (side === "buy" && buyBlocked) {
      toast.error("주문 가능 현금이 부족함");
      return;
    }
    if (side === "sell" && sellBlocked) {
      toast.error("보유 수량보다 많이 매도할 수 없음");
      return;
    }
    setPendingSide(side);
  };

  const confirmOrder = async () => {
    if (pendingSide === null) return;
    const side = pendingSide;

    setSubmitting(true);
    try {
      const result = await placeOrder({
        code,
        side,
        quantity: parsedQuantity,
        order_type: orderType,
        limit_price: orderType === "limit" ? parsedLimitPrice : null,
      });
      toast.success(
        result.status === "pending"
          ? `${side === "buy" ? "매수" : "매도"} 지정가 주문이 대기열에 등록되었습니다.`
          : `${side === "buy" ? "매수" : "매도"} 체결: ${result.quantity}주 @ ${formatPrice(result.fill_price)}`,
        { duration: TOAST_DURATION_MS }
      );
      onOrdered();
      setPendingSide(null);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "주문 실패", {
        duration: TOAST_DURATION_MS,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="space-y-4">
        <div className="grid grid-cols-2 rounded-lg bg-muted/50 p-0.5">
          {(["market", "limit"] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => {
                setOrderType(type);
                if (type === "limit" && currentPrice !== null && !limitPrice) setLimitPrice(String(currentPrice));
              }}
              className={`rounded-md py-2 text-xs transition ${orderType === type ? "bg-background font-medium shadow-sm" : "text-muted-foreground"}`}
            >
              {type === "market" ? "시장가" : "지정가"}
            </button>
          ))}
        </div>

        {orderType === "limit" && (
          <div className="space-y-2">
            <label htmlFor="limit-price" className="text-xs text-muted-foreground">지정 가격</label>
            <Input id="limit-price" type="number" min={1} value={limitPrice} onChange={(event) => setLimitPrice(event.target.value)} className="h-10 font-mono" />
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-[100px_1fr]">
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">수량</p>
            <Input
              type="number"
              min={1}
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              className="h-10"
            />
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">빠른 선택</p>
            <div className="flex flex-wrap gap-2">
              {[1, 10, 50, 100, 500].map((preset) => (
                <Button key={preset} variant="outline" size="sm" onClick={() => setQuantity(String(preset))}>
                  {preset}주
                </Button>
              ))}
            </div>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <Button variant="destructive" onClick={() => requestOrder("buy")} className="h-11">
            매수
          </Button>
          <Button variant="outline" onClick={() => requestOrder("sell")} className="h-11">
            매도
          </Button>
        </div>

        <div className="rounded-xl border bg-muted/30 p-3 text-xs leading-5 text-muted-foreground">
          <div className="flex items-center justify-between gap-3">
            <span>주문 수량</span>
            <span className="font-medium text-foreground">{isQuantityValid ? `${parsedQuantity}주` : "-"}</span>
          </div>
          <div className="mt-2 flex items-center justify-between gap-3">
            <span>{orderType === "market" ? "예상 금액" : "지정가 주문금액"}</span>
            <span className="font-medium text-foreground">
              {estimatedCost !== null ? formatPrice(estimatedCost) : "-"}
            </span>
          </div>
          {availableCash != null && (
            <div className="mt-2 flex items-center justify-between gap-3">
              <span>주문 가능 현금</span>
              <span className={buyBlocked ? "font-medium text-destructive" : "font-medium text-foreground"}>
                {formatPrice(availableCash)}
              </span>
            </div>
          )}
          {positionQuantity !== undefined && (
            <div className="mt-2 flex items-center justify-between gap-3">
              <span>보유 수량</span>
              <span className={sellBlocked ? "font-medium text-destructive" : "font-medium text-foreground"}>
                {positionQuantity}주
              </span>
            </div>
          )}
        </div>
      </div>

      <Dialog open={pendingSide !== null} onOpenChange={(open) => !open && setPendingSide(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{pendingSide === "buy" ? "매수" : "매도"} 주문 확인</DialogTitle>
            <DialogDescription>
              {code} {parsedQuantity}주 {pendingSide === "buy" ? "매수" : "매도"}
              {orderPrice !== null && (
                <>
                  <br />
                  {orderType === "market" ? "현재가 기준 예상금액" : "지정가 주문금액"}: {estimatedCost !== null ? formatPrice(estimatedCost) : "-"}
                  <br />
                  {orderType === "market" ? "실제 체결가는 주문 시점 시세에 따라 달라질 수 있습니다." : "조건을 충족할 때까지 대기주문으로 유지됩니다."}
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingSide(null)} disabled={submitting}>
              취소
            </Button>
            <Button onClick={confirmOrder} disabled={submitting}>
              {submitting ? "처리중..." : "확인"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
