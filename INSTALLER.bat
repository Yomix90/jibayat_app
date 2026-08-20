@echo off
chcp 65001 >nul
title JIBAYAT — Programme d'Installation & Déploiement Officiel
color 0F

echo.
echo  ======================================================================
echo     🏛️  JIBAYAT — GESTION DE LA FISCALITÉ COMMUNALE MAROCAINE
echo  ======================================================================
echo     👨‍💻  Développeur : YOUSSEF
echo     📞  Contact / WhatsApp : +212 662-082795
echo     📧  Support & Email   : yomix90@gmail.com
echo     🔑  Licence Master    : JBYT-LFFF-FF0D-B795-5F03
echo  ======================================================================
echo.

cd /d "%~dp0"

echo  [1/5] Détection de l'environnement Python...
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
            echo.
            echo  ❌ ERREUR : Python est introuvable sur cette machine.
            echo     Veuillez installer Python 3.10 ou supérieur (en cochant "Add to PATH").
            echo.
            pause
            exit /b 1
        )
    )
)
echo      --> Python détecté : %PYTHON%
echo.

echo  [2/5] Installation des dépendances et bibliothèques requises...
%PYTHON% -m pip install --upgrade pip >nul 2>&1
%PYTHON% -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo  ⚠️ Avertissement lors de l'installation de certains packages (poursuite...).
) else (
    echo      --> Toutes les dépendances sont installées avec succès.
)
echo.

echo  [3/5] Initialisation sécurisée de la Base de Données...
%PYTHON% -c "from database import init_db; init_db(); print('      --> Base de données initialisée avec succès.')"
echo.

echo  [4/5] Création du raccourci sur le Bureau de Windows...
set SCRIPT_DIR=%~dp0
set SHORTCUT_VBS=%TEMP%\CreateJibayatShortcut.vbs

echo Set oWS = WScript.CreateObject("WScript.Shell") > "%SHORTCUT_VBS%"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\JIBAYAT.lnk" >> "%SHORTCUT_VBS%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%SHORTCUT_VBS%"
echo oLink.TargetPath = "%SCRIPT_DIR%DEMARRER.bat" >> "%SHORTCUT_VBS%"
echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> "%SHORTCUT_VBS%"
echo oLink.Description = "JIBAYAT — Gestion Fiscale Communale" >> "%SHORTCUT_VBS%"
if exist "%SCRIPT_DIR%static\img\logo.png" (
    echo oLink.IconLocation = "%SCRIPT_DIR%static\img\logo.png, 0" >> "%SHORTCUT_VBS%"
)
echo oLink.Save >> "%SHORTCUT_VBS%"

cscript //nologo "%SHORTCUT_VBS%" >nul 2>&1
if exist "%SHORTCUT_VBS%" del /f /q "%SHORTCUT_VBS%"
echo      --> Raccourci 'JIBAYAT' créé sur votre Bureau.
echo.

echo  [5/5] Finalisation du déploiement...
echo.
echo  ======================================================================
echo     🎉 INSTALLATION TERMINÉE AVEC SUCCÈS !
echo  ======================================================================
echo.
echo     📌 Pour lancer le logiciel :
echo        Double-cliquez sur l'icône 'JIBAYAT' sur votre Bureau
echo        ou exécutez 'DEMARRER.bat'.
echo.
echo     🔑 Code d'activation Développeur (YOUSSEF) :
echo        JBYT-LFFF-FF0D-B795-5F03 (Illimitée / À vie)
echo.
echo     📞 Pour toute assistance ou génération de nouvelles licences :
echo        Youssef — Tél / WhatsApp : +212 662-082795
echo        Email : yomix90@gmail.com
echo  ======================================================================
echo.
pause
