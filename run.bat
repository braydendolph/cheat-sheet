@echo off
rem Run Cheat Sheet from source (needs Python 3.9+).
cd /d "%~dp0"
set PY=py
where py >nul 2>nul || set PY=python
%PY% -c "import PIL" 2>nul || %PY% -m pip install -r requirements.txt
where pyw >nul 2>nul && (start "" pyw main.py) || (start "" pythonw main.py)
