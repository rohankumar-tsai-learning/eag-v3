@echo off
REM Gandalf the Organizer - Startup Script for Windows
REM This script helps start the backend server quickly

echo.
echo ========================================
echo   Gandalf the Organizer - Backend
echo ========================================
echo.

REM Use Python Launcher with Python 3.12
set "PY_CMD=py -3.12"

REM Check if Python 3.12 is installed
%PY_CMD% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3.12 is not installed or not available via the py launcher
    echo Please install Python 3.12 from python.org
    pause
    exit /b 1
)

echo ✅ Python 3.12 found
echo.

REM Check if we're in the right directory
if not exist "main.py" (
    echo ERROR: main.py not found
    echo Please run this script from the backend directory
    echo Current directory: %cd%
    pause
    exit /b 1
)

echo ✅ Backend directory found
echo.

REM Resolve existing virtual environment (prefer already-selected env, then parent/root .venv)
set "VENV_PYTHON="

if defined VIRTUAL_ENV (
    if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
        set "VENV_PYTHON=%VIRTUAL_ENV%\Scripts\python.exe"
        echo ✅ Using currently selected virtual environment: %VIRTUAL_ENV%
    )
)

if not defined VENV_PYTHON (
    if exist "..\.venv\Scripts\python.exe" (
        set "VENV_PYTHON=..\.venv\Scripts\python.exe"
        echo ✅ Using parent virtual environment: ..\.venv
    )
)

if not defined VENV_PYTHON (
    if exist "..\..\.venv\Scripts\python.exe" (
        set "VENV_PYTHON=..\..\.venv\Scripts\python.exe"
        echo ✅ Using root virtual environment: ..\..\.venv
    )
)

if not defined VENV_PYTHON (
    echo ERROR: No existing virtual environment found.
    echo Expected one of:
    echo   1. Selected environment in VIRTUAL_ENV
    echo   2. ..\.venv\Scripts\python.exe
    echo   3. ..\..\.venv\Scripts\python.exe
    echo.
    echo Please create a single environment in the parent/root folder and rerun.
    pause
    exit /b 1
)

echo.

REM Check if requirements are installed
"%VENV_PYTHON%" -m pip list | findstr fastapi >nul 2>&1
if %errorlevel% neq 0 (
    echo 📦 Installing dependencies...
    "%VENV_PYTHON%" -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
    echo ✅ Dependencies installed
) else (
    echo ✅ Dependencies already installed
)

echo.

REM Check if .env file exists
if not exist ".env" (
    echo ⚠️  WARNING: .env file not found
    echo.
    echo Please create .env file with:
    echo   1. Copy: .env.template to .env
    echo   2. Edit .env and add your GEMINI_API_KEY
    echo   3. Get key from: https://aistudio.google.com/
    echo.
    pause
)

echo.
echo ========================================
echo   Starting Backend Server...
echo ========================================
echo.
echo 📍 Server will run on: http://localhost:8000
echo 📚 API Docs: http://localhost:8000/docs
echo 🧪 Health: http://localhost:8000/health
echo.
echo 💡 Next steps:
echo   1. Open Chrome → chrome://extensions/
echo   2. Enable "Developer mode"
echo   3. Click "Load unpacked" → select "extension" folder
echo   4. Click Gandalf icon in toolbar
echo.
echo Press Ctrl+C to stop the server
echo.

"%VENV_PYTHON%" main.py
