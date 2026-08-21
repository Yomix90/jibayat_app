@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title JIBAYAT — Centre de Contrôle & Déploiement

REM ── Détection de Python ────────────────────────────────────
set "PYTHON="
if exist "C:\Python314\python.exe" set "PYTHON=C:\Python314\python.exe"
if not defined PYTHON (
    where py >nul 2>&1 && set "PYTHON=py"
)
if not defined PYTHON (
    where python >nul 2>&1 && set "PYTHON=python"
)

:MENU
cls
color 0B
cd /d "%~dp0"

REM Lecture dynamique de la version
set "APP_VER=1.5.2"
if exist "version.txt" (
    set /p APP_VER=<version.txt
)

echo.
echo  ╔═════════════════════════════════════════════════════════════════════════════╗
echo  ║                                                                             ║
echo  ║   🏛️   J I B A Y A T  —  CENTRE DE CONTRÔLE ^& GESTION FISCALE               ║
echo  ║   ─────────────────────────────────────────────────────────────             ║
echo  ║   📦  Version Actuelle  : v!APP_VER!                                           ║
echo  ║   👨‍💻  Auteur            : Yomix90                                           ║
echo  ║   🌐  Dépôt Public MAJ  : Yomix90/jibayat-releases                          ║
echo  ║                                                                             ║
echo  ╚═════════════════════════════════════════════════════════════════════════════╝
echo.
echo  ┌─── EXÉCUTION ^& DEV ─────────────────────────────────────────────────────────┐
echo  │  [1]  🚀 Démarrer JIBAYAT (Serveur local ^& Navigateur)                     │
echo  │  [2]  🗄️  Initialiser / Mettre à jour la Base de Données (fiscalite.db)     │
echo  │  [3]  📥 Installer / Mettre à jour les dépendances Python (pip)             │
echo  ├─── COMPILATION ^& DISTRIBUTION ──────────────────────────────────────────────┤
echo  │  [4]  📦 Compiler l'Installateur Autonome (dist\JIBAYAT_Setup.exe)          │
echo  │  [5]  ⚙️  Compiler l'Exécutable seul (dist\JIBAYAT\JIBAYAT.exe)               │
echo  │  [6]  🔑 Compiler le Générateur de Licences (dist\JIBAYAT_Keygen.exe)        │
echo  ├─── SYNCHRONISATION GITHUB ──────────────────────────────────────────────────┤
echo  │  [7]  ⬇️  Git Pull (Mettre à jour depuis le dépôt GitHub distant)            │
echo  │  [8]  ⬆️  Git Push (Publier vers Dépôt Privé + Dépôt Public Releases)        │
echo  ├─── MAINTENANCE ─────────────────────────────────────────────────────────────┤
echo  │  [9]  🧹 Nettoyer les caches et fichiers de build temporaires              │
echo  │  [0]  🚪 Quitter                                                            │
echo  └─────────────────────────────────────────────────────────────────────────────┘
echo.
set /p "CHOIX=  👉 Choisissez une option [0-9] : "

if "%CHOIX%"=="1" goto CMD_RUN
if "%CHOIX%"=="2" goto CMD_INITDB
if "%CHOIX%"=="3" goto CMD_PIP
if "%CHOIX%"=="4" goto CMD_BUILD_SETUP
if "%CHOIX%"=="5" goto CMD_BUILD_EXE
if "%CHOIX%"=="6" goto CMD_BUILD_KEYGEN
if "%CHOIX%"=="7" goto CMD_PULL
if "%CHOIX%"=="8" goto CMD_PUSH
if "%CHOIX%"=="9" goto CMD_CLEAN
if "%CHOIX%"=="0" goto CMD_EXIT

echo.
echo  ❌ Option non reconnue.
timeout /t 2 >nul
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  1. DÉMARRER JIBAYAT
REM ═══════════════════════════════════════════════════════════════
:CMD_RUN
cls
color 0A
echo.
echo  ======================================================================
echo    🚀 Lancement de JIBAYAT (v!APP_VER!)...
echo  ======================================================================
echo.
if not defined PYTHON (
    color 0C
    echo  ❌ Python est introuvable. Veuillez l'installer.
    pause
    goto MENU
)
%PYTHON% launcher.py
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  2. INITIALISER BASE DE DONNÉES
REM ═══════════════════════════════════════════════════════════════
:CMD_INITDB
cls
color 0E
echo.
echo  ======================================================================
echo    🗄️  Initialisation et Migration de la Base de Données...
echo  ======================================================================
echo.
%PYTHON% -c "from database import init_db; init_db(); print('\n✅ Base de données initialisée et vérifiée avec succès !')"
echo.
pause
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  3. INSTALLER DÉPENDANCES
REM ═══════════════════════════════════════════════════════════════
:CMD_PIP
cls
color 0B
echo.
echo  ======================================================================
echo    📥 Installation des dépendances Python requises...
echo  ======================================================================
echo.
%PYTHON% -m pip install --upgrade pip
%PYTHON% -m pip install -r requirements.txt
%PYTHON% -m pip install pyinstaller pillow pystray
echo.
echo  ✅ Dépendances installées avec succès !
echo.
pause
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  4. COMPILER JIBAYAT_SETUP.EXE
REM ═══════════════════════════════════════════════════════════════
:CMD_BUILD_SETUP
cls
color 0E
echo.
echo  ======================================================================
echo    📦 Compilation de l'Installateur Autonome JIBAYAT_Setup.exe...
echo  ======================================================================
echo.
%PYTHON% build_package.py
echo.
pause
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  5. COMPILER JIBAYAT.EXE SEUL
REM ═══════════════════════════════════════════════════════════════
:CMD_BUILD_EXE
cls
color 0E
echo.
echo  ======================================================================
echo    ⚙️  Compilation des binaires JIBAYAT (launcher.spec)...
echo  ======================================================================
echo.
if exist "dist\JIBAYAT" rmdir /s /q "dist\JIBAYAT"
%PYTHON% -m PyInstaller -y launcher.spec
echo.
if exist "dist\JIBAYAT\JIBAYAT.exe" (
    color 0A
    echo  ✅ Compilation réussie dans : dist\JIBAYAT\JIBAYAT.exe
) else (
    color 0C
    echo  ❌ Échec de la compilation.
)
echo.
pause
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  6. COMPILER KEYGEN
REM ═══════════════════════════════════════════════════════════════
:CMD_BUILD_KEYGEN
cls
color 0E
echo.
echo  ======================================================================
echo    🔑 Compilation du Générateur de Licences (Keygen)...
echo  ======================================================================
echo.
%PYTHON% -m PyInstaller --onefile --windowed --name "JIBAYAT_Keygen" --icon "app.ico" keygen_app.py
echo.
if exist "dist\JIBAYAT_Keygen.exe" (
    color 0A
    echo  ✅ Keygen prêt dans : dist\JIBAYAT_Keygen.exe
)
echo.
pause
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  7. GIT PULL
REM ═══════════════════════════════════════════════════════════════
:CMD_PULL
cls
color 0B
echo.
echo  ======================================================================
echo    ⬇️  Récupération des mises à jour depuis GitHub...
echo  ======================================================================
echo.
git pull origin main
echo.
pause
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  8. GIT PUSH (DOUBLE DÉPÔT : PRIVÉ + RELEASES PUBLIC)
REM ═══════════════════════════════════════════════════════════════
:CMD_PUSH
cls
color 0B
echo.
echo  ======================================================================
echo    ⬆️  Publication Git (Dépôt Privé + Dépôt Public Releases)...
echo  ======================================================================
echo.
set /p "COMMIT_MSG=  💬 Message du commit [Entrée pour commit auto] : "
if "!COMMIT_MSG!"=="" set "COMMIT_MSG=chore(release): update JIBAYAT v!APP_VER!"

echo.
echo  [1/2] Envoi sur le Dépôt Privé (Code Source)...
git add .
git commit -m "!COMMIT_MSG!"
git push origin main
git push deploy main 2>nul

echo.
echo  [2/2] Envoi sur le Dépôt Public Releases (Yomix90/jibayat-releases)...
if exist "releases_repo" (
    cd releases_repo
    if not exist ".git" (
        git init -b main
        git remote add origin https://github.com/Yomix90/jibayat-releases.git
    )
    git add .
    git commit -m "docs(release): update v!APP_VER!"
    git push -f -u origin main
    cd ..
)

echo.
color 0A
echo  ✅ Synchronisation terminée avec succès sur tous les dépôts !
echo.
pause
goto MENU


REM ═══════════════════════════════════════════════════════════════
REM  9. NETTOYER CACHES ET BUILDS
REM ═══════════════════════════════════════════════════════════════
:CMD_CLEAN
cls
color 0E
echo.
echo  ======================================================================
echo    🧹 Nettoyage des fichiers de build et caches...
echo  ======================================================================
echo.
if exist "build" rmdir /s /q "build"
if exist "app_payload.zip" del /f /q "app_payload.zip"
if exist "__pycache__" rmdir /s /q "__pycache__"
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
del /s /q *.pyc 2>nul
echo.
color 0A
echo  ✅ Nettoyage terminé !
echo.
pause
goto MENU


:CMD_EXIT
exit /b 0
