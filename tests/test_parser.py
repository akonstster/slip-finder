"""Фикстуры синтетические: tools/make_fixtures.py (формат как у ARCUS, данные выдуманные)."""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from slip_finder.parser import parse_file, parse_text

FIXTURES = Path(__file__).parent / "fixtures"
MSK = timezone(timedelta(hours=3))
TID = "12345678"


@pytest.mark.parametrize(
    "name, amount_kop, card_type, last4, auth_code, rrn, receipt_no",
    [
        ("260115093425.log", 20800, "Visa", "1111", "123456", "000000000007", "7"),
        ("260115093501.log", 25800, "MIR", "2222", "654321", "000000000008", "8"),
        ("260115093518.log", 25800, "MIR", "3333", "A1B2C3", "000000000009", "9"),
        ("260115093651.log", 38000, "MIR", "4444", "111222", "000000000010", "10"),
        # MIR PAY: маска на 15 звёздочек с F, код строчными буквами
        ("260115093931.log", 200, "MIR PAY", "5555", "abcDEF", "000000000011", "11"),
    ],
)
def test_approved(name, amount_kop, card_type, last4, auth_code, rrn, receipt_no):
    slip = parse_file(FIXTURES / name)
    assert slip is not None
    assert slip.kind == "purchase"
    assert slip.approved
    assert slip.status == "Успешно"
    assert slip.amount_kop == amount_kop
    assert slip.card_type == card_type
    assert slip.last4 == last4
    assert slip.auth_code == auth_code
    assert slip.rrn == rrn
    assert slip.receipt_no == receipt_no
    assert slip.tid == TID
    # Имя файла = локальное время начала операции, слип чуть позже
    started = datetime.strptime(name[:12], "%y%m%d%H%M%S").replace(tzinfo=MSK)
    slip_time = datetime.fromtimestamp(slip.ts, MSK)
    assert timedelta(0) <= slip_time - started < timedelta(minutes=2)


@pytest.mark.parametrize(
    "name, rc, status, last4, auth_code, amount_kop",
    [
        # ARCUS пропускает пустые поля, блок короче 8 строк
        ("260115100000.log", "212", "Отказ ввода карты", "", "", 51400),
        ("260115101000.log", "305", "Карта не обслуживается", "6666", "", 148100),
        # Код авторизации есть, но это отказ
        ("260115102000.log", "116", "Недостаточно средств", "7777", "222333", 129600),
    ],
)
def test_declines(name, rc, status, last4, auth_code, amount_kop):
    slip = parse_file(FIXTURES / name)
    assert not slip.approved
    assert (slip.rc, slip.status, slip.last4, slip.auth_code, slip.amount_kop) == (
        rc, status, last4, auth_code, amount_kop)
    assert slip.card_type == "MIR"
    assert slip.tid == TID


def test_refund_keeps_original_purchase():
    purchase = parse_file(FIXTURES / "260115110000.log")
    refund = parse_file(FIXTURES / "260115110100.log")
    assert (purchase.kind, refund.kind) == ("purchase", "refund")
    # Возврат выводит RRN и код исходной оплаты, поэтому ключ — имя файла
    assert purchase.rrn == refund.rrn == "000000000015"
    assert purchase.auth_code == refund.auth_code == "333444"
    assert purchase.key != refund.key
    # У возврата свой номер чека; кассе нужен номер исходной оплаты
    assert (purchase.receipt_no, refund.receipt_no) == ("15", "16")


def test_tms_session_is_skipped():
    assert parse_file(FIXTURES / "260115120000.log") is None


def test_tech_operation_without_command_is_skipped():
    assert parse_text("1790231665 - ARCUS\n1790231665 - START\n") is None


def test_no_bank_answer():
    text = "1790231665 - External Command\n1790231665 - 1\x1b1\x1b643\x1b100.00\x1b\x1b\n1790231690 - ENDTR\n"
    slip = parse_text(text, "y.log")
    assert not slip.approved
    assert slip.amount_kop == 10000
    assert slip.status == "Нет ответа"
    assert slip.key == "y.log"
