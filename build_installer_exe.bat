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
            echo  ❌ Python introuvable.
            pause
            exit /b 1
        )
    )
)

echo [1/4] Compilation des binaires protégés (JIBAYAT.exe)...
if exist "dist\JIBAYAT" rmdir /s /q "dist\JIBAYAT"
%PYTHON% -m PyInstaller -y launcher.spec
if %errorlevel% neq 0 (
    color 0C
    echo  ❌ Échec de la compilation des binaires JIBAYAT.
    pause
    exit /b 1
)

echo.
echo [2/4] Création du package applicatif compressé (app_payload.zip)...
%PYTHON% -c "
import zipfile, os

zip_name = 'app_payload.zip'
if os.path.exists(zip_name):
    os.remove(zip_name)

source_dir = r'dist\JIBAYAT'
with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(source_dir):
        for f in files:
            path = os.path.join(root, f)
            arcname = os.path.relpath(path, source_dir)
            zf.write(path, arcname)

print('      --> Archive binaire créée (' + str(round(os.path.getsize(zip_name)/1024/1024, 2)) + ' Mo).')
"

if not exist "app_payload.zip" (
    color 0C
    echo  ❌ Échec de la création de app_payload.zip.
    pause
    exit /b 1
)

echo.
echo [3/4] Nettoyage et préparation...
if exist "build\JIBAYAT_Setup" rmdir /s /q "build\JIBAYAT_Setup"

echo.
echo [4/4] Compilation du Setup Exécutable (JIBAYAT_Setup.exe)...
%PYTHON% -m PyInstaller --onefile --windowed --name "JIBAYAT_Setup" --add-data "app_payload.zip;." --clean --optimize 2 installer_gui.py

if %errorlevel% neq 0 (
    color 0C
    echo  ❌ Échec de la compilation de JIBAYAT_Setup.exe.
    pause
    exit /b 1
)

REM Nettoyer app_payload.zip temporaire
if exist "app_payload.zip" del /f /q "app_payload.zip"

echo.
echo  ==================================================================
echo  ✅ Succès ! L'installateur autonome complet est disponible ici :
echo     dist\JIBAYAT_Setup.exe
echo  ==================================================================
echo.
pause
