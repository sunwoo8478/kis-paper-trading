from .. import repository
from ..integrations.kis import KisApiError, KisPaperClient
from .base import OrderExecutionError, OrderExecutor, OrderResult


class KisPaperExecutor(OrderExecutor):
    """KIS competition paper-account executor, isolated from local fills."""

    def __init__(self, client: KisPaperClient, conn):
        self.client = client
        self.conn = conn

    def place_order(
        self,
        code: str,
        side: str,
        quantity: int,
        order_type: str = "market",
        limit_price: float | None = None,
        reason: str = "KIS 모의투자 주문",
    ) -> OrderResult:
        try:
            submitted = self.client.place_cash_order(
                code,
                side,
                quantity,
                order_type,
                limit_price,
            )
        except (KisApiError, ValueError) as exc:
            raise OrderExecutionError(str(exc)) from exc
        broker_order_id = str(submitted.get("broker_order_id") or "") or None
        local_order_id = repository.insert_kis_paper_order(
            self.conn,
            broker_order_id=broker_order_id,
            code=code,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            status=str(submitted.get("status") or "submitted"),
            reason=reason,
        )
        return OrderResult(
            order_id=local_order_id,
            broker_order_id=broker_order_id,
            code=code,
            side=side,
            quantity=quantity,
            fill_price=None,
            status="submitted",
            order_type=order_type,
            limit_price=limit_price,
        )

    def process_pending_orders(self) -> int:
        # KIS is the source of truth; reconciliation happens through balance/order APIs.
        return 0
