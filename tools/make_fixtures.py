"""Генерирует синтетические логи ARCUS 2 для tests/fixtures.

Формат повторяет настоящие логи (cp1251, CRLF, префикс «<unix> - », поля
команды через ESC, блок chek.out без пустых полей, номер чека в теге 5F22
дампа RecvOWTags), но все данные выдуманные: терминал, банк, магазин,
карты, коды, RRN. Реальные логи в репозиторий не кладём.

    python tools/make_fixtures.py
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
MSK = timezone(timedelta(hours=3))
TID = "12345678"
ESC = "\x1b"

HEADER = [
    "USEJL OFF",
    "ARCUS version: 2.0.0.48",
    "Ini path:",
    "C:\\Arcus2\\INI\\",
    "PORT:",
    "COM8",
    "START",
]
SLIP_HEADER = ["       ТЕСТ-БАНК", "      ===================", "        Тестовый магазин"]

# name, класс, id, сумма(руб), поля chek.out (None = ARCUS не пишет строку), номер чека
CASES = [
    # Одобренные оплаты
    ("260115093425", 1, 1, "208.00",
     ["000", "************1111", TID, "123456", "Visa", "Успешно", "20800", "000000000007"], 7),
    ("260115093501", 1, 1, "258.00",
     ["000", "************2222", TID, "654321", "MIR", "Успешно", "25800", "000000000008"], 8),
    ("260115093518", 1, 1, "258.00",
     ["000", "************3333", TID, "A1B2C3", "MIR", "Успешно", "25800", "000000000009"], 9),
    ("260115093651", 1, 1, "380.00",
     ["000", "************4444", TID, "111222", "MIR", "Успешно", "38000", "000000000010"], 10),
    # MIR PAY: маска на 15 звёздочек с F, код строчными буквами
    ("260115093931", 1, 1, "2.00",
     ["000", "***************5555F", TID, "abcDEF", "MIR PAY", "Успешно", "200", "000000000011"], 11),
    # Отказ 212: нет карты и кода, блок короче 8 строк
    ("260115100000", 1, 1, "514.00",
     ["212", None, TID, None, "MIR", "Отказ ввода карты", "51400", None], 12),
    # Отказ 305: карта есть, кода нет
    ("260115101000", 1, 1, "1481.00",
     ["305", "************6666", TID, None, "MIR", "Карта не обслуживается", "148100", None], 13),
    # Отказ 116: код авторизации есть, но это не одобрение
    ("260115102000", 1, 1, "1296.00",
     ["116", "************7777", TID, "222333", "MIR", "Answer code is not received", "129600",
      "000000000014"], 14),
    # Оплата и возврат: возврат выводит RRN и код исходной оплаты, номер чека свой
    ("260115110000", 1, 1, "10.00",
     ["000", "************8888", TID, "333444", "Mastercard", "Успешно", "1000", "000000000015"], 15),
    ("260115110100", 1, 11, "10.00",
     ["000", "************8888", TID, "333444", "Mastercard", "Успешно", "1000", "000000000015"], 16),
    # Сессия TMS (класс 2): техоперация, в поиск не попадает
    ("260115120000", 2, 1, "00.00", ["000", "tms", "MIR", "Успешно"], None),
]


def dump(ts: int, data: bytes) -> list[str]:
    return [f"{ts} - " + "".join(f"{b:02X} " for b in data[i:i + 16])
            for i in range(0, len(data), 16)]


def make_log(name, op_class, op_id, amount, fields, receipt):
    start = int(datetime.strptime(name, "%y%m%d%H%M%S").replace(tzinfo=MSK).timestamp())
    t_end = start + 12
    lines = [(start, s) for s in HEADER]
    lines += [(start, "External Command"),
              (start, ESC.join(["1" if op_class == 1 else str(op_class), str(op_id), "643", amount, "", ""]))]
    lines += [(start + 1, "STATUS:Вставьте карту в пин-пад"),
              (start + 5, "STATUS:Авторизация"),
              (start + 6, "IP 10.0.0.1:16993 GetState..."),
              (start + 6, "WRITE:2:<hidden>"),
              (t_end, "STORERC:000"),
              (t_end, "PRINT:" + "\r\n".join(SLIP_HEADER))]
    out = [f"{ts} - {v}" for ts, v in lines]
    if receipt is not None:
        tlv = bytes([0x5F, 0x22, 0x02]) + receipt.to_bytes(2, "little")
        out.append(f"{t_end} - RecvOWTags ({len(tlv)} bytes)")
        out += dump(t_end, tlv)
    out.append(f"{t_end} - Starting output to [C:\\Arcus2\\chek.out]")
    out += [f"{t_end} - {v}" for v in fields if v is not None]
    out.append(f"{t_end} - Output to file finished")
    out.append(f"{t_end} - ENDTR")
    return ("\r\n".join(out) + "\r\n").encode("cp1251")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.log"):
        old.unlink()
    for case in CASES:
        (OUT / f"{case[0]}.log").write_bytes(make_log(*case))
    print(f"{len(CASES)} logs -> {OUT}")


if __name__ == "__main__":
    main()
