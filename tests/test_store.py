from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from slip_finder.indexer import index_once
from slip_finder.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
MSK = timezone(timedelta(hours=3))


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    assert index_once(s, FIXTURES) == 11  # 10 операций + TMS-сессия, которая не попадает в базу
    return s


def codes(store, q):
    return sorted(r["auth_code"] for r in store.search(q, None, None))


def test_reindex_is_noop(store):
    assert index_once(store, FIXTURES) == 0
    assert store.stats()["count"] == 10


def test_amount(store):
    assert codes(store, "258") == ["654321", "A1B2C3"]
    assert codes(store, "208,00") == ["123456"]
    assert codes(store, "2.00") == ["abcDEF"]


def test_last4(store):
    assert codes(store, "1111") == ["123456"]


def test_auth_code_and_card_type(store):
    assert codes(store, "a1b2c3") == ["A1B2C3"]
    assert codes(store, "visa") == ["123456"]


def test_combined_tokens(store):
    assert codes(store, "258 mir") == ["654321", "A1B2C3"]
    assert codes(store, "258 visa") == []


def test_refund_and_purchase_both_found(store):
    rows = store.search("10", None, None)
    assert sorted(r["kind_label"] for r in rows) == ["Возврат", "Оплата"]


def test_period_filter(store):
    noon = int(datetime(2026, 1, 15, 12, 0, tzinfo=MSK).timestamp())
    assert store.search("", noon, None) == []
    assert len(store.search("", None, noon)) == 10
