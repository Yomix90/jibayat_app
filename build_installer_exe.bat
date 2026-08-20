@echo off
title JIBAYAT — Compilation du Setup Autonome (JIBAYAT_Setup.exe)
color 0B
echo.
echo  ╔════════════════════════════════════════════════════════════════╗
echo  ║     JIBAYAT — Compilation Complète de l'Installateur .EXE      ║
echo  ╚════════════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

set PYTHON=C:\Python314\python.exe
if not exist "%PYTHON%" (
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON=py
    ) else (
        where python >nul 2>&1
        if %errorlevel% equ 0 (
            set PYTHON=python
        ) else (
            color 0C
            echo  ❌ Python introuvable sur ce système.
            pause
            exit /b 1
        )
    )
)

%PYTHON% build_package.py

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  ❌ Une erreur s'est produite lors de la compilation.
    echo.
    pause
    exit /b 1
)

color 0A
pause
