@echo off
REM RAF launcher for Windows: starts the API (port 8000) and the web UI (port 5173) in two windows.
REM Everything (virtualenv, caches, data) stays inside this project folder.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || goto :error
)
if not exist ".scratch" mkdir ".scratch"

echo Installing backend requirements, cache kept in .scratch\pip-cache ...
".venv\Scripts\python.exe" -m pip install --cache-dir ".scratch\pip-cache" -q -r backend\requirements.txt || goto :error

if not exist "frontend\node_modules" (
  echo Installing frontend packages, cache kept in .scratch\npm-cache ...
  pushd frontend
  call npm.cmd install --cache "..\.scratch\npm-cache" --no-audit --no-fund || goto :error
  popd
)

start "RAF API" cmd /k "cd /d %~dp0backend && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "RAF UI" cmd /k "cd /d %~dp0frontend && npm.cmd run dev"

echo.
echo RAF is starting:  http://localhost:5173
echo Make sure Ollama is running and the model is pulled:  ollama pull gemma4:12b
goto :eof

:error
echo Setup failed. See the messages above.
exit /b 1

