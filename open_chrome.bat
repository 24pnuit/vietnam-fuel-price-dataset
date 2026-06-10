@echo off
echo Dang mo Chrome voi remote debugging...
echo Giu nguyen cua so Chrome nay trong khi chay chuong trinh.
echo.

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%TEMP%\chrome-debug"

echo Chrome da mo. Ban co the dong cua so nay.
timeout /t 3 >nul
