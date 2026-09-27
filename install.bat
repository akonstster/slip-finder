@echo off
setlocal
rem Установка slip-finder на кассовый ПК. Запускать из папки, где лежит slip-finder.exe.

set "SRC=%~dp0slip-finder.exe"
set "DEST=%LOCALAPPDATA%\Programs\slip-finder"
set "LOGS=C:\Arcus2\logs"

if not exist "%SRC%" (
    echo Не найден slip-finder.exe рядом с install.bat
    pause
    exit /b 1
)

echo === Установка slip-finder ("Найти чек") ===
echo.

rem Обновление поверх: старый экземпляр держит exe открытым
tasklist /fi "imagename eq slip-finder.exe" 2>nul | find /i "slip-finder.exe" >nul
if not errorlevel 1 (
    echo Закрываю запущенный slip-finder...
    taskkill /im slip-finder.exe /f >nul 2>&1
    timeout /t 2 /nobreak >nul
)

if not exist "%DEST%" mkdir "%DEST%"
copy /y "%SRC%" "%DEST%\slip-finder.exe" >nul
if errorlevel 1 (
    echo Не удалось скопировать программу в %DEST%
    pause
    exit /b 1
)
echo Программа скопирована в %DEST%

:ask_logs
rem Пустой путь нельзя: "\" - это корень диска, и проверка ниже бы прошла
if defined LOGS if exist "%LOGS%\*" goto logs_ok
echo.
echo Папка логов ARCUS не найдена: %LOGS%
set "LOGS="
set /p "LOGS=Введите путь к папке логов ARCUS (например D:\Arcus2\logs): "
if not defined LOGS goto ask_logs
set "LOGS=%LOGS:"=%"
goto ask_logs

:logs_ok
echo Папка логов: %LOGS%

rem --install сохраняет путь в настройки и создаёт ярлыки: автозагрузка + "Найти чек" на рабочем столе
start "" /wait "%DEST%\slip-finder.exe" --install --logs "%LOGS%"
if errorlevel 1 (
    echo Не удалось создать ярлыки
    pause
    exit /b 1
)
echo Ярлыки созданы: автозагрузка и "Найти чек" на рабочем столе

start "" "%DEST%\slip-finder.exe"
echo.
echo Готово. Программа запущена: иконка чека у часов, страница поиска откроется в браузере.
echo Первый разбор логов может занять до минуты.
pause
