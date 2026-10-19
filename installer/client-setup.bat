@echo off
REM ============================================================
REM  Law Firm — Client Setup (run on each office computer/laptop)
REM
REM  Clients don't need any software installed — just a web browser.
REM  This script creates a desktop shortcut called "Law Firm" that
REM  opens the case management system on the office host computer.
REM ============================================================
setlocal

echo ============================================================
echo  Law Firm Client Setup
echo ============================================================
echo.
echo  This computer will connect to the Law Firm server running
echo  on the office host computer.
echo.

:askip
set /p HOSTIP="Enter the host computer's IP address (e.g. 192.168.1.100): "
if "%HOSTIP%"=="" (
    echo  Please enter an IP address.
    goto askip
)

set URL=http://%HOSTIP%:5000

echo.
echo  Testing connection to %URL% ...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%URL%/login' -UseBasicParsing -TimeoutSec 5; Write-Host '  OK - server is reachable.' } catch { Write-Host '  WARNING: could not reach the server. The shortcut will still be created, but check the IP address and that the host is running.' }"

echo.
echo  Creating desktop shortcut "Law Firm"...
powershell -NoProfile -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Law Firm.lnk')); $s.TargetPath = '%URL%'; $s.Description = 'Law Firm Case Management'; $s.Save(); Write-Host '  Shortcut created on your desktop.'"

echo.
echo ============================================================
echo  Done. Double-click the "Law Firm" icon on your desktop.
echo  If it doesn't connect, ask whoever set up the host computer
echo  for the correct IP address (see MAINTENANCE.md).
echo ============================================================
pause
