"""
build_package.py — Script de Compilation Complet de JIBAYAT & JIBAYAT_Setup.exe
  1. Compile l'application principale via launcher.spec -> dist/JIBAYAT/
  2. Compresse le dossier binaire dans app_payload.zip
  3. Compile l'assistant autonome installer_gui.py -> dist/JIBAYAT_Setup.exe
  4. Nettoie les fichiers temporaires
"""
import os
import sys
import shutil
import zipfile
import subprocess

def log(step, msg):
    print(f"\n[{step}] {msg}")

def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root_dir)

    print("\n" + "=" * 65)
    print("  🏛️  JIBAYAT — Compilation de l'Installateur Autonome (.EXE)")
    print("=" * 65)

    # ── Étape 1 : Compilation des binaires JIBAYAT ──────────
    log("1/4", "Compilation des binaires JIBAYAT avec PyInstaller (launcher.spec)...")
    dist_app = os.path.join(root_dir, 'dist', 'JIBAYAT')
    if os.path.exists(dist_app):
        try:
            shutil.rmtree(dist_app)
        except Exception:
            pass

    cmd1 = [sys.executable, "-m", "PyInstaller", "-y", "launcher.spec"]
    res1 = subprocess.run(cmd1)
    if res1.returncode != 0:
        print("\n❌ Erreur lors de la compilation des binaires JIBAYAT.")
        sys.exit(1)

    if not os.path.exists(dist_app):
        print(f"\n❌ Erreur : Dossier binaire introuvable ({dist_app}).")
        sys.exit(1)

    print("   --> Binaires compilés avec succès dans dist/JIBAYAT/")

    # ── Étape 2 : Création de app_payload.zip ───────────────
    log("2/4", "Création du package compressé app_payload.zip...")
    zip_path = os.path.join(root_dir, 'app_payload.zip')
    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except Exception:
            pass

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(dist_app):
            for file in files:
                full_p = os.path.join(root, file)
                arc_p = os.path.relpath(full_p, dist_app)
                zf.write(full_p, arc_p)

    zip_size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
    print(f"   --> Archive app_payload.zip créée ({zip_size_mb} Mo).")

    # ── Étape 3 : Nettoyage build précédent ──────────────────
    log("3/4", "Nettoyage des fichiers de build temporaires...")
    build_setup = os.path.join(root_dir, 'build', 'JIBAYAT_Setup')
    if os.path.exists(build_setup):
        shutil.rmtree(build_setup, ignore_errors=True)

    # ── Étape 4 : Compilation de l'installateur JIBAYAT_Setup ─
    log("4/4", "Compilation de JIBAYAT_Setup.exe avec PyInstaller...")
    cmd2 = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "JIBAYAT_Setup",
        "--add-data", "app_payload.zip;.",
        "--add-data", "version.txt;.",
        "--clean",
        "--optimize", "2",
        "installer_gui.py"
    ]
    res2 = subprocess.run(cmd2)

    # Nettoyer app_payload.zip
    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except Exception:
            pass

    if res2.returncode != 0:
        print("\n❌ Erreur lors de la compilation de JIBAYAT_Setup.exe.")
        sys.exit(1)

    setup_exe = os.path.join(root_dir, 'dist', 'JIBAYAT_Setup.exe')
    if not os.path.exists(setup_exe):
        print(f"\n❌ Erreur : Fichier introuvable ({setup_exe}).")
        sys.exit(1)

    exe_size_mb = round(os.path.getsize(setup_exe) / (1024 * 1024), 2)
    print("\n" + "=" * 65)
    print("  ✅ SUCCÈS ! L'installateur autonome est prêt :")
    print(f"     📁 {setup_exe} ({exe_size_mb} Mo)")
    print("=" * 65 + "\n")

if __name__ == '__main__':
    main()
