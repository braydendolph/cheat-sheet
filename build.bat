@echo off
rem Builds dist\CheatSheet.exe and, if Inno Setup 6 is installed, the installer.
cd /d "%~dp0"
set PY=py
where py >nul 2>nul || set PY=python
%PY% -m pip install --upgrade -r requirements.txt pyinstaller || goto :fail
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name CheatSheet ^
  --icon assets\icon.ico --add-data "assets;assets" --add-data "games;games" main.py || goto :fail
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% installer\CheatSheet.iss || goto :fail
  echo.
  echo Done: dist\CheatSheet.exe and dist\CheatSheet-Setup-*.exe
) else (
  echo.
  echo Done: dist\CheatSheet.exe
  echo Install Inno Setup 6 from https://jrsoftware.org/isdl.php to also build the installer.
)
pause
exit /b 0
:fail
echo.
echo Build failed.
pause
exit /b 1
