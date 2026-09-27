"""Разбор одного лога ARCUS 2 (один файл = одна операция пин-пада)."""
import re
import sys
from dataclasses import dataclass, asdict
from functools import cache
from pathlib import Path

LINE_RE = re.compile(r"^(\d{9,11}) - (.*)$")
# Поля команды кассы разделены ESC: класс␛id␛валюта␛сумма␛… (класс/id по ops.ini)
EXT_CMD_SEP = "\x1b"

# id операций класса 1 (финансовые) из ops.ini; классы 2/3/9 — сверки, меню, пинг
OP_KINDS = {
    "1": "purchase", "2": "purchase",
    "11": "refund",
    "5": "cancel", "6": "cancel", "9": "cancel", "10": "cancel",
    "109": "purchase",  # СБП
    "110": "refund",
}

KIND_LABELS = {
    "purchase": "Оплата",
    "refund": "Возврат",
    "cancel": "Отмена",
    "other": "Операция",
}

# Коды ISO 8583:1993, которых нет в rc_res.ini, но они встречаются в логах
EXTRA_RC = {
    "116": "Недостаточно средств",
    "117": "Неверный PIN",
    "903": "Повторите операцию",
}

PAN_RE = re.compile(r"^[\d*]{8,}[A-F]?$")
TID_RE = re.compile(r"^\d{8}$")
AUTH_RE = re.compile(r"^[0-9A-Za-z]{6}$")  # у MIR PAY бывают строчные буквы
RRN_RE = re.compile(r"^\d{12}$")
RC_RE = re.compile(r"^\d{2,3}$")
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


@dataclass
class Slip:
    file: str
    ts: int  # unix-время операции
    kind: str
    op_raw: str
    rc: str
    approved: bool
    pan_mask: str
    last4: str
    tid: str
    auth_code: str
    card_type: str
    status: str
    amount_kop: int
    rrn: str
    receipt_no: str = ""  # номер чека терминала, касса спрашивает его при возврате

    @property
    def key(self) -> str:
        # Не RRN: возврат выводит RRN и код исходной оплаты
        return self.file

    def as_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d


@cache
def rc_descriptions() -> dict[str, str]:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "slip_finder"
    out = dict(EXTRA_RC)
    for line in (base / "rc_res.ini").read_text(encoding="utf-8").splitlines():
        code, sep, text = line.partition("=")
        if sep and not code.startswith("#"):
            out[code.strip()] = text.strip()
    return out


def _lines(text: str):
    """Строки лога как (ts, value); строки-продолжения приклеиваются к предыдущей."""
    out = []
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if m:
            out.append([int(m.group(1)), m.group(2)])
        elif out:
            out[-1][1] += "\n" + raw
    return out


def _last4(pan_mask: str) -> str:
    digits = re.findall(r"\d+", pan_mask)
    return digits[-1][-4:] if digits else ""


HEX_DUMP_RE = re.compile(r"^((?:[0-9A-F]{2} ){1,16})")
RECEIPT_TAG = 0x5F22  # номер чека, 2 байта little-endian (дубль в 1F8104)


def iter_tlv(data: bytes):
    """BER-TLV: (тег, значение). Хвост без длины молча отбрасывается."""
    i = 0
    while i < len(data):
        tag = data[i]
        i += 1
        if tag & 0x1F == 0x1F:
            while i < len(data) and data[i] & 0x80:
                tag = (tag << 8) | data[i]
                i += 1
            if i < len(data):
                tag = (tag << 8) | data[i]
                i += 1
        if i >= len(data):
            return
        length = data[i]
        i += 1
        if length & 0x80:
            n = length & 0x7F
            length = int.from_bytes(data[i:i + n], "big")
            i += n
        yield tag, data[i:i + length]
        i += length


def recv_tags(lines) -> bytes:
    """Байты hex-дампа после «RecvOWTags (N bytes)» — теги ответа пин-пада."""
    out = bytearray()
    collecting = False
    for _, v in lines:
        if v.startswith("RecvOWTags"):
            collecting, out = True, bytearray()
            continue
        if collecting:
            m = HEX_DUMP_RE.match(v)
            if not m:
                collecting = False
                continue
            out += bytes.fromhex(m.group(1).replace(" ", ""))
    return bytes(out)


def receipt_no(lines) -> str:
    for tag, value in iter_tlv(recv_tags(lines)):
        if tag == RECEIPT_TAG and value:
            return str(int.from_bytes(value, "little"))
    return ""


def parse_block(values: list[str]) -> dict:
    """Блок chek.out: rc, маска, TID, код, карта, статус, копейки, RRN.

    ARCUS не пишет пустые поля, поэтому у отказов строк меньше, и поля
    опознаются по виду, а не по номеру строки.
    """
    vals = [v for v in values if v]
    take = lambda cond, idx: vals.pop(idx) if vals and cond(vals[idx]) else ""
    f = {}
    f["rc"] = take(RC_RE.match, 0)
    f["rrn"] = take(RRN_RE.match, -1)
    f["amount"] = take(str.isdigit, -1)
    f["pan_mask"] = take(lambda v: "*" in v and PAN_RE.match(v), 0)
    f["tid"] = take(TID_RE.match, 0)
    f["auth_code"] = vals.pop(0) if len(vals) >= 2 and AUTH_RE.match(vals[0]) else ""
    # Остаются «карта» и/или «статус»; одинокое русское значение — это статус
    if len(vals) == 1 and CYRILLIC_RE.search(vals[0]):
        vals.insert(0, "")
    f["card_type"] = vals[0] if vals else ""
    f["status"] = " ".join(vals[1:])
    return f


def parse_text(text: str, file: str = "") -> Slip | None:
    lines = _lines(text)

    op_raw = ""
    kind = "other"
    cmd_amount_kop = 0
    for i, (_, value) in enumerate(lines):
        if value.strip() == "External Command" and i + 1 < len(lines):
            fields = lines[i + 1][1].strip().split(EXT_CMD_SEP)
            op_raw = "/".join(f for f in fields if f)
            fields += [""] * (4 - len(fields))
            op_class, op_id, _currency, amount = fields[:4]
            if op_class != "1":
                return None  # сверка, меню, TMS, пинг пин-пада
            kind = OP_KINDS.get(op_id, "other")
            if re.fullmatch(r"\d+(\.\d+)?", amount):
                cmd_amount_kop = round(float(amount) * 100)
            break
    if not op_raw:
        return None

    start = next(
        (i for i, (_, v) in enumerate(lines) if v.startswith("Starting output to")),
        None,
    )
    if start is None:
        # Обрыв до ответа банка: чека нет
        ts = lines[-1][0] if lines else 0
        return Slip(file, ts, kind, op_raw, "", False, "", "", "", "", "", "Нет ответа",
                    cmd_amount_kop, "")

    block = []
    for _, v in lines[start + 1:]:
        if v.startswith("Output to file finished"):
            break
        block.append(v.strip())
    f = parse_block(block)

    rc = f["rc"]
    approved = rc in ("000", "00")
    status = f["status"]
    if not approved or not status:
        status = rc_descriptions().get(rc) or status or ("Нет ответа" if not rc else f"Код {rc}")
    return Slip(
        file=file,
        ts=lines[start][0],
        kind=kind,
        op_raw=op_raw,
        rc=rc,
        approved=approved,
        pan_mask=f["pan_mask"],
        last4=_last4(f["pan_mask"]),
        tid=f["tid"],
        auth_code=f["auth_code"],
        card_type=f["card_type"],
        status=status,
        amount_kop=int(f["amount"]) if f["amount"] else cmd_amount_kop,
        rrn=f["rrn"],
        receipt_no=receipt_no(lines),
    )


def parse_file(path: Path) -> Slip | None:
    text = Path(path).read_bytes().decode("cp1251", errors="replace")
    return parse_text(text, file=Path(path).name)
