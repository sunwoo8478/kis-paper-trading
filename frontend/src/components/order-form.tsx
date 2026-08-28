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
  onOrdered,
}: {
  code: string;
  currentPrice: number | null;
  onOrdered: () => void;
}) {
  const [quantity, setQuantity] = useState("1");
  const [pendingSide, setPendingSide] = useState<"buy" | "sell" | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const parsedQuantity = Number(quantity);
  const isQuantityValid = Number.isInteger(parsedQuantity) && parsedQuantity > 0;
  const estimatedCost =
    isQuantityValid && currentPrice !== null ? parsedQuantity * currentPrice : null;

  const requestOrder = (side: "buy" | "sell") => {
    if (!isQuantityValid) {
      toast.error("수량은 1 이상의 정수여야 함");
      return;
    }
    setPendingSide(side);
  };

  const confirmOrder = async () => {
    if (pendingSide === null) return;
    const side = pendingSide;

    setSubmitting(true);
    try {
      const result = await placeOrder({ code, side, quantity: parsedQuantity });
      toast.success(
        `${side === "buy" ? "매수" : "매도"} 체결: ${result.quantity}주 @ ${formatPrice(result.fill_price)}`,
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
      <div className="flex items-center gap-2">
        <Input
          type="number"
          min={1}
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          className="w-24"
        />
        <Button variant="destructive" onClick={() => requestOrder("buy")}>
          매수
        </Button>
        <Button variant="outline" onClick={() => requestOrder("sell")}>
          매도
        </Button>
      </div>

      <Dialog open={pendingSide !== null} onOpenChange={(open) => !open && setPendingSide(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{pendingSide === "buy" ? "매수" : "매도"} 주문 확인</DialogTitle>
            <DialogDescription>
              {code} {parsedQuantity}주 {pendingSide === "buy" ? "매수" : "매도"}
              {currentPrice !== null && (
                <>
                  <br />
                  현재가 기준 예상금액: {estimatedCost !== null ? formatPrice(estimatedCost) : "-"}
                  <br />
                  (실제 체결가는 주문 시점 시세에 따라 달라질 수 있음)
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
