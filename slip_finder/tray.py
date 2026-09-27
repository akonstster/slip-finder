"""Иконка в трее: клик открывает страницу поиска."""
import logging
import threading
import webbrowser

from PIL import Image, ImageDraw
import pystray

log = logging.getLogger(__name__)


def make_icon_image(size: int = 64) -> Image.Image:
    """Белый чек с зубчатым краем на синем квадрате."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(12 * s), fill=(31, 111, 235))
    left, right, top, bottom = 16 * s, 48 * s, 9 * s, 50 * s
    teeth = 4
    step = (right - left) / teeth
    outline = [(left, top), (right, top), (right, bottom)]
    for i in range(teeth):
        x = right - step * i
        outline += [(x - step / 2, bottom + 5 * s), (x - step, bottom)]
    d.polygon(outline, fill="white")
    for i, width in enumerate((22, 16, 22, 12)):
        y = (17 + i * 8) * s
        d.rectangle([21 * s, y, (21 + width) * s, y + 3 * s], fill=(31, 111, 235))
    return img


def run_tray(url: str, scan, on_exit):
    """Блокирует поток до выхода из меню трея."""
    def open_page(icon=None, item=None):
        webbrowser.open(url)

    def do_scan(icon, item):
        def work():
            n = scan()
            icon.notify(f"Новых файлов: {n}" if n else "Новых операций нет", "slip-finder")
        threading.Thread(target=work, daemon=True).start()

    def do_exit(icon, item):
        icon.stop()
        on_exit()

    menu = pystray.Menu(
        pystray.MenuItem("Открыть поиск", open_page, default=True),
        pystray.MenuItem("Сканировать логи сейчас", do_scan),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", do_exit),
    )
    icon = pystray.Icon("slip-finder", make_icon_image(), "Найти чек (slip-finder)", menu)
    icon.run()
