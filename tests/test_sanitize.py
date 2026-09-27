import importlib.util
from pathlib import Path

from slip_finder.parser import parse_text

spec = importlib.util.spec_from_file_location(
    "sanitize_log", Path(__file__).parent.parent / "tools" / "sanitize_log.py")
sanitize_log = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sanitize_log)

# 5F22 = номер чека 11, 5F24 = срок действия карты 31.07.31, 5A = маска PAN
LOG = (
    b"1790231971 - External Command\r\n"
    b"1790231971 - 1\x1b1\x1b643\x1b2.00\x1b\x1b\r\n"
    b"1790231978 - IP 203.0.113.7:16993 GetState...\r\n"
    b"1790231980 - WRITE:2:\xc0\x81binary\r\n"
    b"more binary\r\n"
    b"1790231982 - RecvOWTags (14 bytes)\r\n"
    b"1790231982 - 5F 22 02 0B 00 5F 24 03 31 07 31 5A 02 DD DD _\"...._$.1.1Z...\r\n"
    b"1790231982 - Starting output to [C:\\Arcus2\\chek.out]\r\n"
    b"1790231982 - 000\r\n"
    b"1790231982 - 123456\r\n"
    b"1790231982 - MIR\r\n"
    b"1790231982 - Output to file finished\r\n"
)


def test_keeps_receipt_drops_card_data():
    out = sanitize_log.sanitize(LOG)
    assert b"5F 22 02 0B 00" in out
    assert b"5F 24" not in out and b"31 07 31" not in out
    assert b"203.0.113" not in out and b"binary" not in out
    assert parse_text(out.decode("cp1251"), "t.log").receipt_no == "11"
