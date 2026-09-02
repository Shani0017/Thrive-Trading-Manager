@echo off
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --windowed --name MT5TradeManager main.py
echo.
echo Build complete. Find the app at dist\MT5TradeManager.exe
pause
