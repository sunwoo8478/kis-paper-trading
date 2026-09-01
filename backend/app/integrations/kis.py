import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class KisApiError(RuntimeError):
    """Sanitized KIS transport or business error."""


@dataclass(frozen=True)
class KisPaperConfig:
    app_key: str
    app_secret: str
    account_number: str = ""
    product_code: str = "01"
    base_url: str = "https://openapivts.koreainvestment.com:29443"
    order_enabled: bool = False
    token_cache_path: str = ""
    min_request_interval_seconds: float = 0.0

    @classmethod
    def from_env(cls) -> "KisPaperConfig":
        return cls(
            app_key=os.getenv("KIS_PAPER_APP_KEY", "").strip(),
            app_secret=os.getenv("KIS_PAPER_APP_SECRET", "").strip(),
            account_number=os.getenv("KIS_PAPER_ACCOUNT_NUMBER", "").strip(),
            product_code=os.getenv("KIS_PAPER_PRODUCT_CODE", "01").strip() or "01",
            base_url=os.getenv(
                "KIS_PAPER_BASE_URL",
                "https://openapivts.koreainvestment.com:29443",
            ).rstrip("/"),
            order_enabled=os.getenv("KIS_PAPER_ORDER_ENABLED", "false").lower()
            in {"1", "true", "yes"},
            token_cache_path=os.getenv(
                "KIS_PAPER_TOKEN_CACHE",
                ".kis-paper-token.json",
            ).strip(),
            min_request_interval_seconds=max(
                0.0,
                float(os.getenv("KIS_PAPER_MIN_REQUEST_INTERVAL_SECONDS", "0.5")),
            ),
        )

    @property
    def credentials_configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

    @property
    def account_configured(self) -> bool:
        return len(self.account_number) == 8 and len(self.product_code) == 2


class KisPaperClient:
    TOKEN_PATH = "/oauth2/tokenP"
    QUOTE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
    BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
    ORDER_PATH = "/uapi/domestic-stock/v1/trading/order-cash"
    DAILY_ORDERS_PATH = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
    BUYING_POWER_PATH = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
    CANCEL_PATH = "/uapi/domestic-stock/v1/trading/order-rvsecncl"

    def __init__(
        self,
        config: KisPaperConfig | None = None,
        session: requests.Session | None = None,
    ):
        self.config = config or KisPaperConfig.from_env()
        if session is not None:
            self.session = session
        else:
            self.session = requests.Session()
            retry = Retry(total=2, connect=2, read=2, backoff_factor=0.3, status_forcelist=[502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()
        self._http_lock = threading.Lock()
        self._last_request_at = 0.0
        self._load_token_cache()

    def status(self, verify: bool = False) -> dict[str, Any]:
        authenticated = False
        error = None
        if verify and self.config.credentials_configured:
            try:
                self.authenticate()
                authenticated = True
            except KisApiError as exc:
                error = str(exc)
        elif self._token and self._token_expires_at > time.time():
            authenticated = True
        return {
            "environment": "paper",
            "configured": self.config.credentials_configured,
            "authenticated": authenticated,
            "account_configured": self.config.account_configured,
            "account_masked": self._masked_account(),
            "order_enabled": self.config.order_enabled and self.config.account_configured,
            "base_url": self.config.base_url,
            "error": error,
        }

    def authenticate(self, force: bool = False) -> str:
        if not self.config.credentials_configured:
            raise KisApiError("KIS 모의투자 앱 키가 설정되지 않았습니다")
        with self._token_lock:
            if not force and self._token and self._token_expires_at > time.time() + 60:
                return self._token
            with self._http_lock:
                self._throttle()
                response = self.session.post(
                    f"{self.config.base_url}{self.TOKEN_PATH}",
                    json={
                        "grant_type": "client_credentials",
                        "appkey": self.config.app_key,
                        "appsecret": self.config.app_secret,
                    },
                    headers={"content-type": "application/json"},
                    timeout=10,
                )
                self._last_request_at = time.monotonic()
            payload = self._response_payload(response, "토큰 발급")
            token = str(payload.get("access_token") or "")
            if not token:
                raise KisApiError("KIS 토큰 발급 응답에 접근 토큰이 없습니다")
            expires_in = max(300, int(payload.get("expires_in") or 86_400))
            self._token = token
            self._token_expires_at = time.time() + expires_in
            self._save_token_cache()
            return token

    def get_quote(self, code: str) -> dict[str, Any]:
        if not code or not code.isalnum() or len(code) not in {6, 7}:
            raise ValueError("종목코드는 6~7자리여야 합니다")
        payload = self._request(
            "GET",
            self.QUOTE_PATH,
            "FHKST01010100",
            params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code},
        )
        output = payload.get("output") or {}
        return {
            "code": code,
            "price": self._number(output.get("stck_prpr")),
            "change": self._number(output.get("prdy_vrss")),
            "change_pct": self._number(output.get("prdy_ctrt")),
            "volume": int(self._number(output.get("acml_vol")) or 0),
            "market_status": output.get("new_mkop_cls_code"),
            "source": "kis-paper",
        }

    def get_balance(self) -> dict[str, Any]:
        self._require_account()
        payload = self._request(
            "GET",
            self.BALANCE_PATH,
            "VTTC8434R",
            params={
                "CANO": self.config.account_number,
                "ACNT_PRDT_CD": self.config.product_code,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )
        positions = []
        for row in payload.get("output1") or []:
            quantity = int(self._number(row.get("hldg_qty")) or 0)
            if quantity <= 0:
                continue
            positions.append({
                "code": row.get("pdno"),
                "name": row.get("prdt_name"),
                "quantity": quantity,
                "available_quantity": int(self._number(row.get("ord_psbl_qty")) or 0),
                "avg_price": self._number(row.get("pchs_avg_pric")),
                "current_price": self._number(row.get("prpr")),
                "market_value": self._number(row.get("evlu_amt")),
                "pnl": self._number(row.get("evlu_pfls_amt")),
                "return_pct": self._number(row.get("evlu_pfls_rt")),
            })
        summary_rows = payload.get("output2") or []
        summary = summary_rows[0] if summary_rows else {}
        settled_cash = self._number(summary.get("dnca_tot_amt"))
        available_cash = self._number(summary.get("prvs_rcdl_excc_amt"))
        if available_cash is None:
            available_cash = settled_cash
        return {
            "account_masked": self._masked_account(),
            "positions": positions,
            "cash": available_cash,
            "settled_cash": settled_cash,
            "total_value": self._number(summary.get("tot_evlu_amt")),
            "purchase_value": self._number(summary.get("pchs_amt_smtl_amt")),
            "evaluated_value": self._number(summary.get("scts_evlu_amt")),
            "pnl": self._number(summary.get("evlu_pfls_smtl_amt")),
            "source": "kis-paper",
        }

    def get_buying_power(self, code: str = "005930", price: float | None = None) -> dict[str, Any]:
        self._require_account()
        if not code or not code.isalnum() or len(code) not in {6, 7}:
            raise ValueError("종목코드는 6~7자리여야 합니다")
        if price is None:
            price = self.get_quote(code).get("price")
        if price is None or price <= 0:
            raise ValueError("주문 가능 조회를 위한 기준 가격이 필요합니다")
        payload = self._request(
            "GET",
            self.BUYING_POWER_PATH,
            "VTTC8908R",
            params={
                "CANO": self.config.account_number,
                "ACNT_PRDT_CD": self.config.product_code,
                "PDNO": code,
                "ORD_UNPR": str(int(price)),
                "ORD_DVSN": "01",
                "CMA_EVLU_AMT_ICLD_YN": "N",
                "OVRS_ICLD_YN": "N",
            },
        )
        output = payload.get("output") or {}
        return {
            "code": code,
            "reference_price": price,
            "orderable_cash": self._number(output.get("ord_psbl_cash")),
            "cash_only_buying_power": self._number(output.get("nrcvb_buy_amt")),
            "cash_only_quantity": int(self._number(output.get("nrcvb_buy_qty")) or 0),
            "max_buying_power": self._number(output.get("max_buy_amt")),
            "max_quantity": int(self._number(output.get("max_buy_qty")) or 0),
            "source": "kis-paper",
        }

    def place_cash_order(
        self,
        code: str,
        side: str,
        quantity: int,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        self._require_account()
        if not self.config.order_enabled:
            raise KisApiError("KIS 모의투자 주문 전송이 잠겨 있습니다")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        if order_type == "limit" and (limit_price is None or limit_price <= 0):
            raise ValueError("limit price must be positive")
        tr_id = "VTTC0012U" if side == "buy" else "VTTC0011U"
        payload = self._request(
            "POST",
            self.ORDER_PATH,
            tr_id,
            json_body={
                "CANO": self.config.account_number,
                "ACNT_PRDT_CD": self.config.product_code,
                "PDNO": code,
                "ORD_DVSN": "01" if order_type == "market" else "00",
                "ORD_QTY": str(quantity),
                "ORD_UNPR": "0" if order_type == "market" else str(int(limit_price or 0)),
                "EXCG_ID_DVSN_CD": "KRX",
                "SLL_TYPE": "01" if side == "sell" else "",
                "CNDT_PRIC": "",
            },
        )
        output = payload.get("output") or {}
        return {
            "broker_order_id": output.get("ODNO") or output.get("odno"),
            "branch_code": output.get("KRX_FWDG_ORD_ORGNO") or output.get("krx_fwdg_ord_orgno"),
            "order_time": output.get("ORD_TMD") or output.get("ord_tmd"),
            "code": code,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "status": "submitted",
            "source": "kis-paper",
        }

    def cancel_order(self, broker_order_id: str, branch_code: str, quantity: int = 0) -> dict[str, Any]:
        self._require_account()
        if not self.config.order_enabled:
            raise KisApiError("KIS 모의투자 주문 전송이 잠겨 있습니다")
        payload = self._request(
            "POST",
            self.CANCEL_PATH,
            "VTTC0013U",
            json_body={
                "CANO": self.config.account_number,
                "ACNT_PRDT_CD": self.config.product_code,
                "KRX_FWDG_ORD_ORGNO": branch_code,
                "ORGN_ODNO": broker_order_id,
                "ORD_DVSN": "00",
                "RVSE_CNCL_DVSN_CD": "02",
                "ORD_QTY": str(max(0, quantity)),
                "ORD_UNPR": "0",
                "QTY_ALL_ORD_YN": "Y" if quantity <= 0 else "N",
            },
        )
        output = payload.get("output") or {}
        return {
            "broker_order_id": output.get("ODNO") or output.get("odno") or broker_order_id,
            "status": "cancelled",
            "source": "kis-paper",
        }

    def get_daily_orders(self, date: str | None = None) -> list[dict[str, Any]]:
        self._require_account()
        query_date = date or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
        payload = self._request(
            "GET",
            self.DAILY_ORDERS_PATH,
            "VTTC0081R",
            params={
                "CANO": self.config.account_number,
                "ACNT_PRDT_CD": self.config.product_code,
                "INQR_STRT_DT": query_date,
                "INQR_END_DT": query_date,
                "SLL_BUY_DVSN_CD": "00",
                "PDNO": "",
                "CCLD_DVSN": "00",
                "INQR_DVSN": "00",
                "INQR_DVSN_3": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )
        orders = []
        for row in payload.get("output1") or []:
            requested = int(self._number(row.get("ord_qty")) or 0)
            filled = int(self._number(row.get("tot_ccld_qty")) or 0)
            remaining = int(self._number(row.get("rmn_qty")) or 0)
            rejected = int(self._number(row.get("rjct_qty")) or 0)
            cancelled = row.get("cncl_yn") == "Y"
            if cancelled:
                status = "cancelled"
            elif rejected >= requested and requested:
                status = "rejected"
            elif remaining > 0 and filled > 0:
                status = "partial"
            elif remaining > 0:
                status = "pending"
            else:
                status = "filled"
            orders.append({
                "broker_order_id": row.get("odno"),
                "branch_code": row.get("ord_gno_brno"),
                "code": row.get("pdno"),
                "name": row.get("prdt_name"),
                "side": "buy" if row.get("sll_buy_dvsn_cd") == "02" else "sell",
                "requested_quantity": requested,
                "filled_quantity": filled,
                "remaining_quantity": remaining,
                "rejected_quantity": rejected,
                "avg_fill_price": self._number(row.get("avg_prvs")),
                "status": status,
                "order_time": row.get("ord_tmd"),
            })
        return orders

    def _request(
        self,
        method: str,
        path: str,
        tr_id: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self.authenticate()
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        with self._http_lock:
            self._throttle()
            try:
                response = self.session.request(
                    method,
                    f"{self.config.base_url}{path}",
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=10,
                )
            except requests.RequestException as exc:
                raise KisApiError(f"KIS {path} 통신 지연 또는 연결 실패") from exc
            finally:
                self._last_request_at = time.monotonic()
        return self._response_payload(response, path)

    def _throttle(self) -> None:
        interval = self.config.min_request_interval_seconds
        remaining = interval - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _response_payload(response, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise KisApiError(f"KIS {operation} 응답을 해석할 수 없습니다") from exc
        if response.status_code >= 400:
            message = payload.get("msg1") or payload.get("error_description") or "HTTP 오류"
            raise KisApiError(f"KIS {operation} 실패 ({response.status_code}): {message}")
        if "rt_cd" in payload and str(payload.get("rt_cd")) != "0":
            message = payload.get("msg1") or "거래 API 오류"
            code = payload.get("msg_cd") or "UNKNOWN"
            raise KisApiError(f"KIS {operation} 실패 ({code}): {message}")
        return payload

    def _require_account(self) -> None:
        if not self.config.account_configured:
            raise KisApiError("KIS 모의계좌번호 8자리와 상품코드 2자리가 필요합니다")

    def _masked_account(self) -> str | None:
        if not self.config.account_configured:
            return None
        return f"{self.config.account_number[:4]}****-{self.config.product_code}"

    def _load_token_cache(self) -> None:
        if not self.config.token_cache_path:
            return
        path = Path(self.config.token_cache_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            token = str(payload.get("access_token") or "")
            expires_at = float(payload.get("expires_at") or 0)
        except (OSError, ValueError, TypeError):
            return
        if token and expires_at > time.time() + 60:
            self._token = token
            self._token_expires_at = expires_at

    def _save_token_cache(self) -> None:
        if not self.config.token_cache_path or not self._token:
            return
        path = Path(self.config.token_cache_path)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps({
                    "access_token": self._token,
                    "expires_at": self._token_expires_at,
                }),
                encoding="utf-8",
            )
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
        except OSError as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise KisApiError("KIS 토큰 캐시를 안전하게 저장하지 못했습니다") from exc

    @staticmethod
    def _number(value) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None
