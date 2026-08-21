@echo off
title JIBAYAT — Centre de Controle
cd /d "%~dp0"

REM ── Detection de Python ────────────────────────────────────
set "PY_BIN="
if exist "C:\Python314\python.exe" set "PY_BIN=C:\Python314\python.exe"
if not defined PY_BIN (
    where py >nul 2>&1 && set "PY_BIN=py"
)
if not defined PY_BIN (
    where python >nul 2>&1 && set "PY_BIN=python"
)

if defined PY_BIN (
    %PY_BIN% cli_manager.py
    if %errorlevel% equ 0 exit /b 0
)

REM ── Fallback si Python direct ─────────────────────────────
cls
echo ======================================================================
echo    JIBAYAT - Centre de Controle
echo ======================================================================
echo.
echo  [1] Demarrer JIBAYAT (launcher.py)
echo  [2] Compiler JIBAYAT_Setup.exe
echo  [3] Quitter
echo.
set /p "C=Choix: "
if "%C%"=="1" python launcher.py
if "%C%"=="2" python build_package.py
exit /b 0
