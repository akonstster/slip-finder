"""Обход папки логов ARCUS и дозапись новых/изменённых файлов в базу."""
import logging
import threading
import time
from pathlib import Path

from .parser import parse_file
from .store import Store

log = logging.getLogger(__name__)


def index_once(store: Store, logs_dir: Path) -> int:
    """Возвращает число переразобранных файлов."""
    logs_dir = Path(logs_dir)
    if not logs_dir.is_dir():
        log.warning("Папка логов не найдена: %s", logs_dir)
        return 0
    known = store.file_state()
    done = 0
    for path in sorted(logs_dir.glob("*.log")):
        try:
            st = path.stat()
            if known.get(path.name) == (st.st_size, st.st_mtime):
                continue
            slip = parse_file(path)
        except OSError as e:
            # ARCUS может держать файл открытым: попробуем в следующий проход
            log.info("Пропуск %s: %s", path.name, e)
            continue
        except Exception:
            log.exception("Не удалось разобрать %s", path.name)
            slip = None
        store.save(path.name, st.st_size, st.st_mtime, slip)
        done += 1
    if done:
        log.info("Проиндексировано файлов: %d", done)
    return done


class Indexer(threading.Thread):
    def __init__(self, store: Store, logs_dir: Path, interval: float = 30):
        super().__init__(daemon=True, name="indexer")
        self.store, self.logs_dir, self.interval = store, Path(logs_dir), interval
        self.last_scan_ts: float | None = None
        self._wake = threading.Event()
        self._scan_lock = threading.Lock()

    def scan(self) -> int:
        """Синхронный проход; фон и кнопка «Сканировать» не пересекаются."""
        with self._scan_lock:
            n = index_once(self.store, self.logs_dir)
            self.last_scan_ts = time.time()
            return n

    def set_logs_dir(self, path: Path):
        with self._scan_lock:
            self.logs_dir = Path(path)

    def run(self):
        while True:
            try:
                self.scan()
            except Exception:
                log.exception("Ошибка индексации")
            self._wake.wait(self.interval)
            self._wake.clear()

    def kick(self):
        self._wake.set()
