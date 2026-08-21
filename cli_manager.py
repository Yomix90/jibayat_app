"""
cli_manager.py — Tableau de Bord Interactif & Centre de Contrôle JIBAYAT
Exécute toutes les opérations d'administration, compilation et synchronisation.
"""
import os
import sys
import subprocess
import shutil
import time

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_version():
    try:
        with open('version.txt', 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return '1.5.2'

def banner():
    ver = get_version()
    print("\033[96m" + "=" * 75)
    print("   🏛️   J I B A Y A T  —  CENTRE DE CONTRÔLE & GESTION FISCALE")
    print("   " + "─" * 67)
    print(f"   📦 Version : v{ver}  |  👨‍💻 Auteur : Yomix90  |  🌐 Dépôt MAJ : jibayat-releases")
    print("=" * 75 + "\033[0m\n")

def show_menu():
    clear_screen()
    banner()
    print("\033[92m  [1]  🚀 Démarrer JIBAYAT (Serveur Web & Navigateur)\033[0m")
    print("\033[93m  [2]  🗄️  Initialiser / Migrer la Base de Données (fiscalite.db)\033[0m")
    print("\033[93m  [3]  📥 Installer les Dépendances Python (pip install)\033[0m")
    print("  " + "─" * 67)
    print("\033[94m  [4]  📦 Compiler l'Installateur Complet (dist/JIBAYAT_Setup.exe)\033[0m")
    print("\033[94m  [5]  ⚙️  Compiler l'Exécutable seul (dist/JIBAYAT/JIBAYAT.exe)\033[0m")
    print("\033[94m  [6]  🔑 Compiler le Générateur de Licences (JIBAYAT_Keygen.exe)\033[0m")
    print("  " + "─" * 67)
    print("\033[95m  [7]  ⬇️  Git Pull (Mettre à jour depuis GitHub)\033[0m")
    print("\033[95m  [8]  ⬆️  Git Push (Publier vers Dépôt Privé + Dépôt Releases Public)\033[0m")
    print("  " + "─" * 67)
    print("\033[90m  [9]  🧹 Nettoyer les Fichiers Temporaires & Caches de Build\033[0m")
    print("\033[91m  [0]  🚪 Quitter\033[0m")
    print("\n" + "=" * 75)

def run_app():
    clear_screen()
    print("\n🚀 Lancement de JIBAYAT...\n")
    subprocess.run([sys.executable, "launcher.py"])

def init_db():
    clear_screen()
    print("\n🗄️ Initialisation de la base de données...\n")
    try:
        from database import init_db as _init
        _init()
        print("\n✅ Base de données initialisée et vérifiée avec succès !\n")
    except Exception as e:
        print(f"\n❌ Erreur : {e}\n")
    input("Appuyez sur Entrée pour continuer...")

def install_deps():
    clear_screen()
    print("\n📥 Installation des dépendances...\n")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller", "pillow", "pystray"])
    print("\n✅ Installation terminée !\n")
    input("Appuyez sur Entrée pour continuer...")

def build_setup():
    clear_screen()
    print("\n📦 Compilation de l'Installateur Autonome JIBAYAT_Setup.exe...\n")
    subprocess.run([sys.executable, "build_package.py"])
    input("\nAppuyez sur Entrée pour continuer...")

def build_exe():
    clear_screen()
    print("\n⚙️ Compilation de JIBAYAT.exe (launcher.spec)...\n")
    dist_dir = os.path.join("dist", "JIBAYAT")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir, ignore_errors=True)
    res = subprocess.run([sys.executable, "-m", "PyInstaller", "-y", "launcher.spec"])
    if res.returncode == 0:
        print("\n✅ Compilation réussie dans dist/JIBAYAT/JIBAYAT.exe !\n")
    else:
        print("\n❌ Échec de la compilation.\n")
    input("Appuyez sur Entrée pour continuer...")

def build_keygen():
    clear_screen()
    print("\n🔑 Compilation de JIBAYAT_Keygen.exe...\n")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed",
        "--name", "JIBAYAT_Keygen",
        "--icon", "app.ico",
        "keygen_app.py"
    ]
    subprocess.run(cmd)
    print("\n✅ Keygen compilé dans dist/JIBAYAT_Keygen.exe !\n")
    input("Appuyez sur Entrée pour continuer...")

def git_pull():
    clear_screen()
    print("\n⬇️ Récupération des modifications depuis GitHub...\n")
    subprocess.run(["git", "pull", "origin", "main"])
    print("\n✅ Terminé !\n")
    input("Appuyez sur Entrée pour continuer...")

def git_push():
    clear_screen()
    ver = get_version()
    print("\n⬆️ Publication Git vers tous les dépôts...\n")
    msg = input(f"💬 Message du commit [Entrée pour commit auto v{ver}] : ").strip()
    if not msg:
        msg = f"chore(release): update JIBAYAT v{ver}"

    print("\n[1/2] Dépôt Privé (Code Source)...")
    subprocess.run(["git", "add", "."])
    subprocess.run(["git", "commit", "-m", msg])
    subprocess.run(["git", "push", "origin", "main"])
    subprocess.run(["git", "push", "-f", "deploy", "main"])

    print("\n[2/2] Dépôt Public Releases (Yomix90/jibayat-releases)...")
    if os.path.exists("releases_repo"):
        os.chdir("releases_repo")
        if not os.path.exists(".git"):
            subprocess.run(["git", "init", "-b", "main"])
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/Yomix90/jibayat-releases.git"])
        subprocess.run(["git", "add", "."])
        subprocess.run(["git", "commit", "-m", f"docs(release): update v{ver}"])
        subprocess.run(["git", "push", "-f", "-u", "origin", "main"])
        os.chdir("..")

    print("\n✅ Synchronisation terminée avec succès sur tous les dépôts !\n")
    input("Appuyez sur Entrée pour continuer...")

def clean_project():
    clear_screen()
    print("\n🧹 Nettoyage des fichiers temporaires...\n")
    if os.path.exists("build"):
        shutil.rmtree("build", ignore_errors=True)
    if os.path.exists("app_payload.zip"):
        try: os.remove("app_payload.zip")
        except: pass
    if os.path.exists("__pycache__"):
        shutil.rmtree("__pycache__", ignore_errors=True)

    for root, dirs, files in os.walk("."):
        for d in dirs:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
        for f in files:
            if f.endswith(".pyc"):
                try: os.remove(os.path.join(root, f))
                except: pass

    print("✅ Nettoyage terminé !\n")
    input("Appuyez sur Entrée pour continuer...")

def main():
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)
    while True:
        show_menu()
        choix = input("  👉 Choisissez une option [0-9] : ").strip()
        if choix == '1':
            run_app()
        elif choix == '2':
            init_db()
        elif choix == '3':
            install_deps()
        elif choix == '4':
            build_setup()
        elif choix == '5':
            build_exe()
        elif choix == '6':
            build_keygen()
        elif choix == '7':
            git_pull()
        elif choix == '8':
            git_push()
        elif choix == '9':
            clean_project()
        elif choix == '0':
            clear_screen()
            print("\n👋 Au revoir !\n")
            break
        else:
            print("\n❌ Option invalide.")
            time.sleep(1)

if __name__ == '__main__':
    main()
