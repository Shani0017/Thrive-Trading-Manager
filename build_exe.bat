@echo off
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --windowed --name MT5TradeManager --collect-data customtkinter --collect-data matplotlib --add-data "assets;assets" --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 --exclude-module pandas --exclude-module scipy --exclude-module torch --exclude-module tensorflow --exclude-module IPython --exclude-module notebook main.py
echo.
echo Build complete. Find the app at dist\MT5TradeManager.exe
pause
