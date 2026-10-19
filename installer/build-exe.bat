@echo off
REM ============================================================
REM  Build LawFirmServer.exe (run on Windows)
REM
REM  1. Install Python 3.11+ from python.org (check "Add to PATH")
REM  2. Open Command Prompt in the lawfirm folder and run:
REM         installer\build-exe.bat
REM  3. Output lands in:  dist\LawFirmServer\
REM ============================================================
setlocal

echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building LawFirmServer.exe (this takes a few minutes)...
pyinstaller installer\lawfirm.spec --noconfirm

echo.
echo ============================================================
echo  Done. The server is in:  dist\LawFirmServer\
echo  Run dist\LawFirmServer\LawFirmServer.exe to start the server.
echo  Or build the full installer with Inno Setup (see README).
echo ============================================================
pause
