@echo off
title JIBAYAT — Build Keygen Desktop EXE
color 0B
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║     JIBAYAT — Compilation du Keygen Desktop (.exe)  ║
echo  ╚══════════════════════════════════════════════════════╝
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
            echo  ❌ Python introuvable.
            pause
            exit /b 1
        )
    )
)

echo [1/2] Nettoyage et préparation...
if exist "build\JIBAYAT_Keygen" rmdir /s /q "build\JIBAYAT_Keygen"

echo [2/2] Compilation de JIBAYAT_Keygen.exe (Onefile)...
%PYTHON% -m PyInstaller --onefile --windowed --name "JIBAYAT_Keygen" --clean --optimize 2 keygen_app.py

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  ❌ Échec de la compilation du Keygen.
    pause
    exit /b 1
)

echo.
echo  ======================================================
echo  ✅ Succès ! L'application bureau est disponible ici :
echo     dist\JIBAYAT_Keygen.exe
echo  ======================================================
echo.
pause
