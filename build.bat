@echo off
rem Сборка dist\slip-finder.exe (один файл, без консоли)
cd /d "%~dp0"
if not exist .venv py -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller pytest
.venv\Scripts\python -m pytest -q || exit /b 1
if not exist build mkdir build
.venv\Scripts\python -c "from slip_finder.tray import make_icon_image as m; m(256).save('build/icon.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])"
.venv\Scripts\pyinstaller --noconfirm --onefile --noconsole --name slip-finder --icon build\icon.ico ^
  --add-data "slip_finder\static;slip_finder\static" ^
  --add-data "slip_finder\rc_res.ini;slip_finder" run.py || exit /b 1
rem На кассу переносится вся папка dist: exe + установщик
copy /y install.bat dist\install.bat >nul
