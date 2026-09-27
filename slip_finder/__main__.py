"""slip-finder: поиск кода авторизации по логам ARCUS 2."""
import argparse
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__, config
from .config import APP_DIR
from .indexer import Indexer, index_once
from .store import Store
from .web import make_server


def _launch_cmd() -> tuple[str, str]:
    """(target, базовые аргументы) для ярлыков."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else sys.executable), "-m slip_finder"


def install_shortcuts():
    target, base = _launch_cmd()
    workdir = str(Path(target).parent) if getattr(sys, "frozen", False) else os.getcwd()
    shortcuts = [
        # Автозагрузка: тихо индексирует в фоне и висит в трее, браузер не открывает
        ("Startup", "slip-finder.lnk", f"{base} --no-browser".strip()),
        ("Desktop", "Найти чек.lnk", base),
    ]
    q = lambda s: "'" + str(s).replace("'", "''") + "'"  # строка PowerShell в одинарных кавычках
    for folder, name, args in shortcuts:
        ps = (
            "$s=(New-Object -ComObject WScript.Shell);"
            f"$d=[Environment]::GetFolderPath({q(folder)});"
            f"$l=$s.CreateShortcut((Join-Path $d {q(name)}));"
            f"$l.TargetPath={q(target)};$l.Arguments={q(args)};"
            f"$l.WorkingDirectory={q(workdir)};$l.Save()"
        )
        # Явные потоки: у exe без консоли унаследованных дескрипторов может не быть
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode:
            raise RuntimeError(f"ярлык {folder}\\{name}: {r.stderr.strip() or r.stdout.strip()}")
        logging.info("Ярлык создан: %s\\%s -> %s %s", folder, name, target, args)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="slip-finder", description=__doc__)
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--logs", help="папка логов ARCUS (по умолчанию из настроек)")
    ap.add_argument("--db", type=Path, default=APP_DIR / "slips.db")
    ap.add_argument("--port", type=int, help="порт страницы (по умолчанию из настроек)")
    ap.add_argument("--interval", type=float, default=30, help="период опроса логов, сек")
    ap.add_argument("--no-browser", action="store_true", help="не открывать страницу")
    ap.add_argument("--no-tray", action="store_true", help="без иконки в трее")
    ap.add_argument("--index-once", action="store_true", help="проиндексировать и выйти")
    ap.add_argument("--install", action="store_true",
                    help="ярлыки в автозагрузке и на рабочем столе; с --logs/--port сохраняет их в настройки")
    args = ap.parse_args(argv)

    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[RotatingFileHandler(APP_DIR / "slip-finder.log", maxBytes=1_000_000,
                                      backupCount=3, encoding="utf-8")]
        + ([logging.StreamHandler()] if sys.stderr else []),
    )

    settings = config.load()
    if args.install:
        logging.info("--install: exe=%s, logs=%r, пользователь=%s",
                     sys.executable, args.logs, os.environ.get("USERNAME"))
        # Строкой, не Path: Path("") == "." и пустой путь прошёл бы проверку
        if args.logs is not None and (not args.logs.strip() or not Path(args.logs).is_dir()):
            logging.error("--install: папка логов не найдена: %r", args.logs)
            sys.exit(2)
        try:
            if args.logs or args.port:
                if args.logs:
                    settings["logs_dir"] = str(Path(args.logs))
                if args.port:
                    settings["port"] = args.port
                config.save(settings)
                logging.info("Настройки сохранены: %s", config.SETTINGS_FILE)
            install_shortcuts()
        except Exception:
            logging.exception("--install не удался")
            sys.exit(1)
        return

    logs_dir = Path(args.logs or settings["logs_dir"])
    port = args.port or int(settings["port"])

    store = Store(args.db)
    if args.index_once:
        n = index_once(store, logs_dir)
        print(f"Файлов разобрано: {n}; в базе: {store.stats()['count']}")
        return

    url = f"http://127.0.0.1:{port}/"
    indexer = Indexer(store, logs_dir, args.interval)
    try:
        server = make_server(store, indexer, port)
    except OSError:
        # Уже запущен (например, из автозагрузки): просто показываем страницу
        if not args.no_browser:
            webbrowser.open(url)
        return

    indexer.start()
    logging.info("slip-finder: %s, логи %s, база %s", url, logs_dir, args.db)
    if not args.no_browser:
        webbrowser.open(url)

    tray = None
    if not args.no_tray:
        try:
            from . import tray
        except ImportError:
            logging.warning("pystray/Pillow не установлены, работаю без иконки в трее")
    if tray is None:
        server.serve_forever()
        return

    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    tray.run_tray(url, indexer.scan, server.shutdown)


if __name__ == "__main__":
    main()
