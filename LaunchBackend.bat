@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
start /min "" cmd /c "for /l %%i in (1,1,60) do (curl -s -o nul http://localhost:8000/ && start http://localhost:8000 && exit /b || timeout /t 1 >nul)"
uvicorn backend.api:app --port 8000
