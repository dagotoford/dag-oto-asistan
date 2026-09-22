@echo off
python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller --noconfirm --windowed --name "DagOtoAsistan" main.py
echo.
echo EXE: dist\DagOtoAsistan\DagOtoAsistan.exe
pause
