import pytest

from app.integrations.kis import KisApiError, KisPaperClient, KisPaperConfig


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST_TOKEN", url, kwargs))
        return self.responses.pop(0)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _config(**overrides):
    values = {
        "app_key": "paper-key",
        "app_secret": "paper-secret",
        "account_number": "12345678",
        "product_code": "01",
        "order_enabled": False,
    }
    values.update(overrides)
    return KisPaperConfig(**values)


def test_client_configures_automatic_retry_when_no_session_given():
    client = KisPaperClient(_config())

    adapter = client.session.get_adapter("https://openapivts.koreainvestment.com")

    assert adapter.max_retries.total == 2


def test_status_never_exposes_credentials():
    client = KisPaperClient(_config())

    status = client.status()

    assert status["configured"] is True
    assert status["account_masked"] == "1234****-01"
    assert "paper-key" not in str(status)
    assert "paper-secret" not in str(status)


def test_authentication_is_cached():
    session = _Session([_Response({"access_token": "token", "expires_in": 3600})])
    client = KisPaperClient(_config(), session)

    assert client.authenticate() == "token"
    assert client.authenticate() == "token"
    assert len(session.calls) == 1


def test_token_cache_survives_client_restart(tmp_path):
    cache_path = tmp_path / "token.json"
    config = _config(token_cache_path=str(cache_path))
    first_session = _Session([
        _Response({"access_token": "persistent-token", "expires_in": 3600})
    ])
    first = KisPaperClient(config, first_session)
    assert first.authenticate() == "persistent-token"

    second_session = _Session([])
    second = KisPaperClient(config, second_session)

    assert second.authenticate() == "persistent-token"
    assert second_session.calls == []
    assert oct(cache_path.stat().st_mode & 0o777) == "0o600"


def test_quote_uses_official_paper_api_fields():
    session = _Session([
        _Response({"access_token": "token", "expires_in": 3600}),
        _Response({
            "rt_cd": "0",
            "output": {
                "stck_prpr": "73500",
                "prdy_vrss": "1200",
                "prdy_ctrt": "1.66",
                "acml_vol": "123456",
                "new_mkop_cls_code": "2",
            },
        }),
    ])
    client = KisPaperClient(_config(), session)

    quote = client.get_quote("005930")

    assert quote["price"] == 73_500
    assert quote["change_pct"] == 1.66
    assert quote["source"] == "kis-paper"
    assert session.calls[1][2]["headers"]["tr_id"] == "FHKST01010100"


def test_balance_requires_account_number():
    client = KisPaperClient(_config(account_number=""))

    with pytest.raises(KisApiError, match="계좌번호"):
        client.get_balance()


def test_balance_maps_positions_and_summary():
    session = _Session([
        _Response({"access_token": "token", "expires_in": 3600}),
        _Response({
            "rt_cd": "0",
            "output1": [{
                "pdno": "005930",
                "prdt_name": "삼성전자",
                "hldg_qty": "3",
                "ord_psbl_qty": "2",
                "pchs_avg_pric": "70000",
                "prpr": "73500",
                "evlu_amt": "220500",
                "evlu_pfls_amt": "10500",
                "evlu_pfls_rt": "5.0",
            }],
            "output2": [{
                "dnca_tot_amt": "1000000",
                "prvs_rcdl_excc_amt": "999000",
                "tot_evlu_amt": "1220500",
                "pchs_amt_smtl_amt": "210000",
                "scts_evlu_amt": "220500",
                "evlu_pfls_smtl_amt": "10500",
            }],
        }),
    ])
    client = KisPaperClient(_config(), session)

    balance = client.get_balance()

    assert balance["cash"] == 999_000
    assert balance["settled_cash"] == 1_000_000
    assert balance["total_value"] == 1_220_500
    assert balance["positions"][0]["quantity"] == 3
    assert session.calls[1][2]["headers"]["tr_id"] == "VTTC8434R"


def test_buying_power_maps_cash_without_margin():
    session = _Session([
        _Response({"access_token": "token", "expires_in": 3600}),
        _Response({
            "rt_cd": "0",
            "output": {
                "ord_psbl_cash": "3200000",
                "nrcvb_buy_amt": "3100000",
                "nrcvb_buy_qty": "11",
                "max_buy_amt": "3300000",
                "max_buy_qty": "12",
            },
        }),
    ])
    client = KisPaperClient(_config(), session)

    buying_power = client.get_buying_power("005930", 260000)

    assert buying_power["orderable_cash"] == 3_200_000
    assert buying_power["cash_only_buying_power"] == 3_100_000
    assert buying_power["cash_only_quantity"] == 11
    assert session.calls[1][2]["headers"]["tr_id"] == "VTTC8908R"
    assert session.calls[1][2]["params"]["ORD_DVSN"] == "01"


def test_order_is_locked_until_explicitly_enabled():
    client = KisPaperClient(_config(order_enabled=False))

    with pytest.raises(KisApiError, match="잠겨"):
        client.place_cash_order("005930", "buy", 1)


def test_enabled_order_uses_current_paper_transaction_id():
    session = _Session([
        _Response({"access_token": "token", "expires_in": 3600}),
        _Response({
            "rt_cd": "0",
            "output": {"ODNO": "12345", "KRX_FWDG_ORD_ORGNO": "91252"},
        }),
    ])
    client = KisPaperClient(_config(order_enabled=True), session)

    order = client.place_cash_order("005930", "buy", 1)

    assert order["broker_order_id"] == "12345"
    assert session.calls[1][2]["headers"]["tr_id"] == "VTTC0012U"
    assert session.calls[1][2]["json"]["ORD_DVSN"] == "01"


def test_cancel_order_is_locked_until_explicitly_enabled():
    client = KisPaperClient(_config(order_enabled=False))

    with pytest.raises(KisApiError, match="잠겨"):
        client.cancel_order("0000015242", "00950")


def test_cancel_order_sends_full_quantity_cancel_request():
    session = _Session([
        _Response({"access_token": "token", "expires_in": 3600}),
        _Response({"rt_cd": "0", "output": {"ODNO": "0000015242"}}),
    ])
    client = KisPaperClient(_config(order_enabled=True), session)

    result = client.cancel_order("0000015242", "00950")

    assert result["status"] == "cancelled"
    assert result["broker_order_id"] == "0000015242"
    assert session.calls[1][2]["headers"]["tr_id"] == "VTTC0013U"
    assert session.calls[1][2]["json"]["RVSE_CNCL_DVSN_CD"] == "02"
    assert session.calls[1][2]["json"]["QTY_ALL_ORD_YN"] == "Y"
    assert session.calls[1][2]["json"]["ORGN_ODNO"] == "0000015242"
    assert session.calls[1][2]["json"]["KRX_FWDG_ORD_ORGNO"] == "00950"


def test_daily_orders_distinguishes_partial_and_filled():
    session = _Session([
        _Response({"access_token": "token", "expires_in": 3600}),
        _Response({
            "rt_cd": "0",
            "output1": [
                {
                    "odno": "1", "ord_gno_brno": "00950", "pdno": "005930",
                    "prdt_name": "삼성전자", "sll_buy_dvsn_cd": "02",
                    "ord_qty": "10", "tot_ccld_qty": "3", "rmn_qty": "7",
                    "rjct_qty": "0", "cncl_yn": "N", "avg_prvs": "70000",
                    "ord_tmd": "101500",
                },
                {
                    "odno": "2", "ord_gno_brno": "00950", "pdno": "000660",
                    "prdt_name": "SK하이닉스", "sll_buy_dvsn_cd": "02",
                    "ord_qty": "2", "tot_ccld_qty": "2", "rmn_qty": "0",
                    "rjct_qty": "0", "cncl_yn": "N", "avg_prvs": "300000",
                    "ord_tmd": "101600",
                },
            ],
        }),
    ])
    client = KisPaperClient(_config(), session)

    orders = client.get_daily_orders("20260901")

    assert orders[0]["status"] == "partial"
    assert orders[0]["remaining_quantity"] == 7
    assert orders[1]["status"] == "filled"
    assert session.calls[1][2]["headers"]["tr_id"] == "VTTC0081R"
