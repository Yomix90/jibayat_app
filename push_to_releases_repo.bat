@echo off
title JIBAYAT — Publication du Dépôt Public (Yomix90/jibayat-releases)
color 0B
echo.
echo  ╔════════════════════════════════════════════════════════════════╗
echo  ║  Publication vers le Dépôt Public : Yomix90/jibayat-releases  ║
echo  ║  (Aucun code source .py n'est exposé)                         ║
echo  ╚════════════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0releases_repo"

if not exist ".git" (
    echo Initialisation du dépôt Git pour les releases...
    git init -b main
    git remote add origin https://github.com/Yomix90/jibayat-releases.git
)

git add .
git commit -m "docs(release): public documentation and version manifest for JIBAYAT v1.5.0"
git push -u origin main

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ❌ Erreur : Assurez-vous que le dépôt Yomix90/jibayat-releases est créé sur GitHub.
    echo Rendez-vous sur https://github.com/new et créez le dépôt public 'jibayat-releases'.
    echo.
    pause
    exit /b 1
)

color 0A
echo.
echo ==================================================================
echo ✅ Dépôt public Yomix90/jibayat-releases mis à jour avec succès !
echo ==================================================================
echo.
pause
