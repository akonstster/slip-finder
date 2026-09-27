"""Обезличивание логов ARCUS перед добавлением в tests/fixtures.

Убирает то, что парсеру не нужно, но относится к данным карт и банка:
hex-дампы EMV-тегов (срок действия карты 5F24 и пр.), зашифрованный обмен
с процессингом (WRITE/READ), адрес хоста процессинга. Из дампа ответа
пин-пада (RecvOWTags) остаются только теги из SAFE_TAGS.

    python tools/sanitize_log.py tests/fixtures/*.log
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from slip_finder.parser import iter_tlv  # noqa: E402

TS = re.compile(rb"^(\d{9,11}) - ")
HEX_DUMP = re.compile(rb"^\d{9,11} - ((?:[0-9A-F]{2} )+)")
WRITE = re.compile(rb"^(\d{9,11} - WRITE:\d+:).+$")
READ_REPLY = re.compile(rb"^(\d{9,11} - \d+:).+$")
IPV4 = re.compile(rb"\b(?!2\.0\.0\.48\b)\d{1,3}(?:\.\d{1,3}){3}\b")  # 2.0.0.48 — версия ARCUS
SAFE_TAGS = {0x5F22}  # номер чека


def _encode_tlv(tag: int, value: bytes) -> bytes:
    return tag.to_bytes((tag.bit_length() + 7) // 8, "big") + bytes([len(value)]) + value


def _dump_lines(ts: bytes, data: bytes, eol: bytes) -> list[bytes]:
    return [ts + b" - " + b"".join(b"%02X " % c for c in data[i:i + 16]) + eol
            for i in range(0, len(data), 16)]


def sanitize(data: bytes) -> bytes:
    out = []
    in_write = False
    recv_ts, recv_data, recv_eol = None, bytearray(), b""

    def flush_recv():
        nonlocal recv_ts, recv_data
        if recv_ts is not None:
            safe = b"".join(_encode_tlv(t, v) for t, v in iter_tlv(bytes(recv_data)) if t in SAFE_TAGS)
            out.extend(_dump_lines(recv_ts, safe, recv_eol))
        recv_ts, recv_data = None, bytearray()

    for line in data.split(b"\n"):
        body = line.rstrip(b"\r")
        eol = line[len(body):]
        m_ts = TS.match(body)
        if not m_ts:
            # Продолжение бинарной строки WRITE; остальные продолжения (чек) оставляем
            if in_write:
                continue
            flush_recv()
            out.append(line)
            continue
        in_write = False
        m = HEX_DUMP.match(body)
        if m:
            if recv_ts is not None:
                recv_data += bytes.fromhex(m.group(1).replace(b" ", b"").decode())
            continue
        flush_recv()
        if b"RecvOWTags" in body:
            recv_ts, recv_eol = m_ts.group(1), eol
            out.append(line)
            continue
        m = WRITE.match(body)
        if m:
            in_write = True
            line = m.group(1) + b"<hidden>" + eol
        else:
            m = READ_REPLY.match(body)
            if m:
                line = m.group(1) + eol
        out.append(IPV4.sub(b"10.0.0.1", line))
    flush_recv()
    return b"\n".join(out)


def main(paths):
    for p in map(Path, paths):
        before = p.read_bytes()
        after = sanitize(before)
        if after != before:
            p.write_bytes(after)
            print(f"{p.name}: {len(before)} -> {len(after)} bytes")


if __name__ == "__main__":
    main(sys.argv[1:])
