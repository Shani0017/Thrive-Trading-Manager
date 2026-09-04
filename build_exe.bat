@echo off
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --windowed --name "THRIVE Trade Manager" --collect-data customtkinter --collect-data matplotlib --add-data "assets;assets" --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 --exclude-module pandas --exclude-module scipy --exclude-module torch --exclude-module tensorflow --exclude-module IPython --exclude-module notebook main.py
echo.
echo Build complete. Find the app at "dist\THRIVE Trade Manager.exe"
pause
