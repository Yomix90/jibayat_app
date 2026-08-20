"""
installer_gui.py — Assistant d'Installation Graphique (Setup Wizard) pour JIBAYAT
Extrait le package applicatif autonome (app_payload.zip) dans le dossier cible choisi
et configure automatiquement la licence 30 jours, la base de données et le raccourci Bureau.
"""
import sys
import os
import shutil
import json
import time
import zipfile
import subprocess
import threading
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Clé secrète maîtresse HMAC pour générer des clés valides si besoin
MASTER_SIGN_SECRET = b"JIBAYAT_FISCALITE_COMMUNALE_SECURE_SIGN_KEY_2026"

DEV_NAME = "YOUSSEF"
DEV_PHONE = "+212 662-082795"
DEV_EMAIL = "yomix90@gmail.com"
APP_VERSION = "1.0.0"


def generate_30d_key(commune_nom: str = "Commune") -> str:
    """Génère une clé valide de 30 jours signée par HMAC-SHA256."""
    import hmac, hashlib
    days_hex = f"{30:04X}"
    salt_hex = os.urandom(1).hex().upper()
    payload = f"M1{days_hex}{salt_hex}"
    sig = hmac.new(MASTER_SIGN_SECRET, payload.encode('utf-8'), hashlib.sha256).hexdigest()[:8].upper()
    full_code = f"{payload}{sig}"
    return f"JBYT-{full_code[0:4]}-{full_code[4:8]}-{full_code[8:12]}-{full_code[12:16]}"


def create_windows_shortcut(target_exe, shortcut_path, icon_path="", working_dir=""):
    """Crée un raccourci Windows .lnk propre via VBScript pointant vers le dossier d'installation."""
    try:
        vbs_path = os.path.join(os.environ.get('TEMP', '.'), 'create_lnk.vbs')
        with open(vbs_path, 'w', encoding='utf-8') as f:
            f.write(f'''Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{target_exe}"
oLink.WorkingDirectory = "{working_dir}"
oLink.Description = "JIBAYAT — Gestion Fiscale Communale"
''')
            if icon_path and os.path.exists(icon_path):
                f.write(f'oLink.IconLocation = "{icon_path}, 0"\n')
            f.write('oLink.Save\n')

        subprocess.run(f'cscript //nologo "{vbs_path}"', shell=True, capture_output=True)
        if os.path.exists(vbs_path):
            os.remove(vbs_path)
        return True
    except Exception:
        return False


class JibayatSetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Assistant d'Installation — JIBAYAT (v{APP_VERSION})")
        self.geometry("640x510")
        self.minsize(600, 480)
        self.resizable(False, False)
        self.configure(bg="#0f172a")

        self.current_step = 1
        
        # Localiser le dossier ressource (PyInstaller _MEIPASS ou dossier script)
        if getattr(sys, 'frozen', False):
            self.bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            self.bundle_dir = os.path.dirname(os.path.abspath(__file__))

        # Dossier d'installation par défaut : C:\JIBAYAT
        drive = os.environ.get('SystemDrive', 'C:')
        default_dir = os.path.join(drive, '\\JIBAYAT')
        self.var_install_dir = tk.StringVar(value=default_dir)
        self.var_commune_nom = tk.StringVar(value="Commune")
        self.var_create_desktop_icon = tk.BooleanVar(value=True)
        self.var_launch_after = tk.BooleanVar(value=True)

        self.setup_ui()
        self.show_step(1)

    def setup_ui(self):
        # ── Header Banner
        self.header = tk.Frame(self, bg="#1e293b", height=80, padx=20, pady=12)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.lbl_head_title = tk.Label(self.header, text="🏛️ Installation de JIBAYAT",
                                       bg="#1e293b", fg="#fbbf24", font=("Segoe UI", 14, "bold"))
        self.lbl_head_title.pack(anchor="w")

        self.lbl_head_sub = tk.Label(self.header, text="Gestion de la Fiscalité Communale Marocaine",
                                     bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 9))
        self.lbl_head_sub.pack(anchor="w")

        # ── Content Area
        self.content_frame = tk.Frame(self, bg="#0f172a", padx=25, pady=20)
        self.content_frame.pack(fill="both", expand=True)

        # ── Footer / Navigation
        self.footer = tk.Frame(self, bg="#1e293b", height=60, padx=20, pady=12)
        self.footer.pack(fill="x", side="bottom")

        self.lbl_dev_info = tk.Label(self.footer, text=f"👨‍💻 Développeur : {DEV_NAME} | 📞 {DEV_PHONE}",
                                     bg="#1e293b", fg="#64748b", font=("Segoe UI", 8))
        self.lbl_dev_info.pack(side="left")

        self.btn_cancel = tk.Button(self.footer, text="Annuler", bg="#334155", fg="#ffffff",
                                    relief="flat", padx=12, pady=4, cursor="hand2", command=self.destroy)
        self.btn_cancel.pack(side="right", padx=(8, 0))

        self.btn_next = tk.Button(self.footer, text="Suivant >", bg="#f59e0b", fg="#0f172a",
                                  font=("Segoe UI", 9, "bold"), relief="flat", padx=16, pady=4,
                                  cursor="hand2", command=self.next_step)
        self.btn_next.pack(side="right")

        self.btn_back = tk.Button(self.footer, text="< Précédent", bg="#334155", fg="#ffffff",
                                  relief="flat", padx=12, pady=4, cursor="hand2", command=self.prev_step)
        self.btn_back.pack(side="right", padx=(0, 8))

    def clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def show_step(self, step):
        self.current_step = step
        self.clear_content()

        if step == 1:
            self.lbl_head_title.config(text="Bienvenue dans l'assistant d'installation")
            self.lbl_head_sub.config(text="Licence d'évaluation de 30 jours incluse.")
            self.btn_back.config(state="disabled")
            self.btn_next.config(text="Suivant >")

            tk.Label(self.content_frame, text="Bienvenue dans l'assistant d'installation de JIBAYAT.",
                     bg="#0f172a", fg="#f8fafc", font=("Segoe UI", 12, "bold"), wraplength=550, justify="left").pack(anchor="w", pady=(0, 10))

            info_text = (
                "Ce programme va installer et déployer le logiciel JIBAYAT dans le répertoire de votre choix.\n\n"
                "📌 Caractéristiques de cette version :\n"
                "  • Licence d'évaluation officielle de 30 jours activée automatiquement.\n"
                "  • Base de données SQLite locale autonome et sécurisée.\n"
                "  • Création du raccourci officiel sur le Bureau pointant vers le dossier installé.\n\n"
                f"👨‍💻 Développeur officiel : {DEV_NAME}\n"
                f"📞 Contact / WhatsApp : {DEV_PHONE}\n"
                f"📧 Support Technique : {DEV_EMAIL}\n\n"
                "Cliquez sur 'Suivant' pour configurer l'emplacement d'installation."
            )
            tk.Label(self.content_frame, text=info_text, bg="#0f172a", fg="#cbd5e1",
                     font=("Segoe UI", 9), wraplength=550, justify="left").pack(anchor="w")

        elif step == 2:
            self.lbl_head_title.config(text="Dossier d'installation & Commune")
            self.lbl_head_sub.config(text="Choisissez l'emplacement où installer JIBAYAT.")
            self.btn_back.config(state="normal")
            self.btn_next.config(text="Installer >")

            tk.Label(self.content_frame, text="1. Dossier de destination :",
                     bg="#0f172a", fg="#f8fafc", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

            dir_box = tk.Frame(self.content_frame, bg="#0f172a")
            dir_box.pack(fill="x", pady=(0, 14))

            ent_dir = tk.Entry(dir_box, textvariable=self.var_install_dir, bg="#1e293b", fg="#ffffff",
                               insertbackground="#ffffff", font=("Segoe UI", 9), relief="flat")
            ent_dir.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))

            btn_browse = tk.Button(dir_box, text="Parcourir...", bg="#334155", fg="#ffffff",
                                   relief="flat", padx=10, cursor="hand2", command=self.browse_dir)
            btn_browse.pack(side="right")

            tk.Label(self.content_frame, text="2. Nom de la Commune :",
                     bg="#0f172a", fg="#f8fafc", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

            ent_commune = tk.Entry(self.content_frame, textvariable=self.var_commune_nom, bg="#1e293b", fg="#ffffff",
                                   insertbackground="#ffffff", font=("Segoe UI", 9), relief="flat")
            ent_commune.pack(fill="x", pady=(0, 16), ipady=4)

            # Options
            tk.Checkbutton(self.content_frame, text="Créer une icône sur le Bureau (pointant vers le dossier installé)",
                           variable=self.var_create_desktop_icon, bg="#0f172a", fg="#e2e8f0",
                           selectcolor="#1e293b", activebackground="#0f172a", activeforeground="#ffffff",
                           font=("Segoe UI", 9)).pack(anchor="w", pady=2)

            tk.Checkbutton(self.content_frame, text="Lancer JIBAYAT à la fin de l'installation",
                           variable=self.var_launch_after, bg="#0f172a", fg="#e2e8f0",
                           selectcolor="#1e293b", activebackground="#0f172a", activeforeground="#ffffff",
                           font=("Segoe UI", 9)).pack(anchor="w", pady=2)

        elif step == 3:
            self.lbl_head_title.config(text="Installation en cours...")
            self.lbl_head_sub.config(text="Déploiement des fichiers et configuration...")
            self.btn_back.config(state="disabled")
            self.btn_next.config(state="disabled")
            self.btn_cancel.config(state="disabled")

            self.lbl_progress_status = tk.Label(self.content_frame, text="Préparation des fichiers...",
                                                bg="#0f172a", fg="#fbbf24", font=("Segoe UI", 10, "bold"))
            self.lbl_progress_status.pack(anchor="w", pady=(20, 10))

            self.progress_bar = ttk.Progressbar(self.content_frame, mode='determinate', length=500)
            self.progress_bar.pack(fill="x", pady=(0, 15))

            self.txt_log = tk.Text(self.content_frame, bg="#1e293b", fg="#94a3b8", height=8,
                                   font=("Consolas", 8), relief="flat", padx=8, pady=8)
            self.txt_log.pack(fill="both", expand=True)

            threading.Thread(target=self.run_installation, daemon=True).start()

        elif step == 4:
            self.lbl_head_title.config(text="Installation Réussie !")
            self.lbl_head_sub.config(text="JIBAYAT a été installé avec succès.")
            self.btn_back.pack_forget()
            self.btn_cancel.pack_forget()
            self.btn_next.config(text="Terminer", state="normal", command=self.finish_setup)

            tk.Label(self.content_frame, text="🎉 Déploiement Terminé !",
                     bg="#0f172a", fg="#4ade80", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 8))

            target_dir = os.path.abspath(self.var_install_dir.get())
            success_info = (
                "JIBAYAT est maintenant installé et prêt à l'emploi !\n\n"
                f"📁 Répertoire d'installation : {target_dir}\n"
                "🔑 Licence activée : 30 jours (Renouvelable)\n"
                "🖥️ Raccourci Bureau : Créé et lié directement au dossier d'installation.\n\n"
                "📌 Coordonnées Développeur / Support :\n"
                f"  • Développeur : {DEV_NAME}\n"
                f"  • Tél / WhatsApp : {DEV_PHONE}\n"
                f"  • Email : {DEV_EMAIL}\n"
            )
            tk.Label(self.content_frame, text=success_info, bg="#0f172a", fg="#cbd5e1",
                     font=("Segoe UI", 9), wraplength=550, justify="left").pack(anchor="w")

    def browse_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.var_install_dir.get())
        if chosen:
            self.var_install_dir.set(chosen)

    def next_step(self):
        if self.current_step == 1:
            self.show_step(2)
        elif self.current_step == 2:
            self.show_step(3)

    def prev_step(self):
        if self.current_step == 2:
            self.show_step(1)

    def log(self, msg):
        if hasattr(self, 'txt_log') and self.txt_log.winfo_exists():
            self.txt_log.insert(tk.END, f"{msg}\n")
            self.txt_log.see(tk.END)
            self.update_idletasks()
        else:
            print(f"[INSTALL] {msg}")

    def update_progress(self, val, status_text=""):
        if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
            self.progress_bar['value'] = val
        if status_text and hasattr(self, 'lbl_progress_status') and self.lbl_progress_status.winfo_exists():
            self.lbl_progress_status.config(text=status_text)
        self.update_idletasks()

    def run_installation(self):
        target_dir = os.path.abspath(self.var_install_dir.get())
        commune_nom = self.var_commune_nom.get().strip() or "Commune"

        try:
            self.update_progress(10, "1/5 Création du dossier cible...")
            self.log(f"Création du dossier de destination : {target_dir}")
            os.makedirs(target_dir, exist_ok=True)
            time.sleep(0.3)

            self.update_progress(30, "2/5 Extraction des fichiers de l'application...")

            payload_zip = os.path.join(self.bundle_dir, 'app_payload.zip')

            if os.path.exists(payload_zip):
                self.log(f"Extraction du package applicatif binaire...")
                with zipfile.ZipFile(payload_zip, 'r') as zf:
                    zf.extractall(target_dir)
                self.log("Binaire et bibliothèques extraits avec succès.")
            elif os.path.exists(os.path.join(self.bundle_dir, 'dist', 'JIBAYAT')):
                # Copie depuis dist/JIBAYAT
                self.log("Déploiement depuis la distribution binaire...")
                src_bin = os.path.join(self.bundle_dir, 'dist', 'JIBAYAT')
                for item in os.listdir(src_bin):
                    s = os.path.join(src_bin, item)
                    d = os.path.join(target_dir, item)
                    if os.path.isdir(s):
                        if os.path.exists(d):
                            shutil.rmtree(d, ignore_errors=True)
                        shutil.copytree(s, d)
                    else:
                        shutil.copy2(s, d)
                self.log("Distribution binaire déployée.")
            else:
                self.log("ERREUR : Package binaire app_payload.zip introuvable !")
                raise FileNotFoundError("Le package binaire compilé est introuvable.")

            # Protection absolue du code source : supprimer tout fichier .py ou script de dev accidentel dans target_dir
            for root, dirs, files in os.walk(target_dir):
                if os.path.basename(root) == '_internal':
                    continue  # Ne pas toucher aux bibliothèques compilées de _internal
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in ('.py', '.bat', '.spec', '.log', '.md', '.txt', '.js') and f not in ('config.json', 'version.txt'):
                        try:
                            os.remove(os.path.join(root, f))
                        except Exception:
                            pass
                for d in list(dirs):
                    if d in ('modules', 'build', 'dist', '__pycache__', '.git'):
                        try:
                            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                        except Exception:
                            pass
                    # Si templates et static sont bien dans _internal, masquer/supprimer les doublons visibles à la racine
                    if root == target_dir and d in ('templates', 'static'):
                        if os.path.exists(os.path.join(target_dir, '_internal', d)):
                            try:
                                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                            except Exception:
                                pass

            self.log("Code source et templates HTML protégés dans l'infrastructure interne.")

            time.sleep(0.3)
            self.update_progress(60, "3/5 Configuration de la licence 30 jours...")

            # Génération d'une clé de 30 jours officielle
            license_30d = generate_30d_key(commune_nom)
            now = datetime.now()
            expiry_date = (now + timedelta(days=30)).strftime('%Y-%m-%d')

            config_path = os.path.join(target_dir, 'config.json')
            cfg = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}

            cfg['install_date'] = now.strftime('%Y-%m-%d %H:%M:%S')
            cfg['trial_days'] = 30
            cfg['license_key'] = license_30d
            cfg['license_type'] = '30'
            cfg['license_expiry'] = expiry_date
            cfg['license_activated_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
            if 'commune' not in cfg:
                cfg['commune'] = {}
            cfg['commune']['nom'] = commune_nom
            cfg['telemetry_webhook_url'] = "https://script.google.com/macros/s/AKfycbzVbZPmKK8kjFYvZI0D7ZvcUVJMyKdLHgGO_WU-Rf6XlE_UJI8rXWFmI5yIlBpUIMVM1g/exec"

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)

            self.log(f"Licence 30 jours configurée (Validité jusqu'au {expiry_date})")
            self.log(f"Clé générée : {license_30d}")

            # Envoi asynchrone de la notification d'installation au Google Sheet du développeur
            def _send_install_telemetry():
                try:
                    import requests
                    requests.post(
                        "https://script.google.com/macros/s/AKfycbzVbZPmKK8kjFYvZI0D7ZvcUVJMyKdLHgGO_WU-Rf6XlE_UJI8rXWFmI5yIlBpUIMVM1g/exec",
                        json={
                            'action': 'install',
                            'commune_nom': commune_nom,
                            'commune_code': 'COM-01',
                            'version': '1.0.0',
                            'license_key': license_30d,
                            'license_state': 'Période d\'essai (30j)',
                            'license_expiry': expiry_date,
                            'days_left': 30,
                            'install_date': now.strftime('%Y-%m-%d %H:%M:%S'),
                            'is_activated': False,
                            'in_trial': True,
                            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S')
                        },
                        timeout=10
                    )
                except Exception:
                    pass

            threading.Thread(target=_send_install_telemetry, daemon=True).start()

            time.sleep(0.3)
            self.update_progress(80, "4/5 Initialisation de la base de données...")

            # Initialiser SQLite dans target_dir
            try:
                import sqlite3
                db_path = os.path.join(target_dir, 'fiscalite.db')
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS communes (
                    id INTEGER PRIMARY KEY, nom TEXT, nom_ar TEXT,
                    president_fr TEXT, president_ar TEXT,
                    region TEXT, region_ar TEXT, province TEXT, province_ar TEXT, logo TEXT,
                    code TEXT, actif INTEGER DEFAULT 1
                )''')
                c.execute("INSERT OR REPLACE INTO communes (id, nom) VALUES (1, ?)", (commune_nom,))
                conn.commit()
                conn.close()
                self.log(f"Base de données initialisée : {db_path}")
            except Exception as e:
                self.log(f"Note DB : {e}")

            time.sleep(0.3)
            self.update_progress(90, "5/5 Création du raccourci Bureau vers le dossier d'installation...")

            if self.var_create_desktop_icon.get():
                desktop = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')
                shortcut_lnk = os.path.join(desktop, 'JIBAYAT.lnk')
                
                # Déterminer la cible : JIBAYAT.exe (exécutable binaire compilé)
                target_exe = os.path.join(target_dir, 'JIBAYAT.exe')
                if not os.path.exists(target_exe):
                    target_exe = os.path.join(target_dir, 'DEMARRER.bat')
                
                # Déterminer l'icône
                icon_path = os.path.join(target_dir, '_internal', 'static', 'img', 'logo.png')
                if not os.path.exists(icon_path):
                    icon_path = os.path.join(target_dir, 'static', 'img', 'logo.png')

                create_windows_shortcut(target_exe, shortcut_lnk, icon_path, target_dir)
                self.log(f"Raccourci Bureau créé : {shortcut_lnk}")
                self.log(f"Cible du raccourci : {target_exe}")
                self.log(f"Dossier de travail : {target_dir}")

            self.update_progress(100, "Installation achevée avec succès !")
            self.log("Déploiement complet terminé.")
            time.sleep(0.5)

            # Passer à l'étape finale
            self.after(200, lambda: self.show_step(4))

        except Exception as ex:
            self.update_progress(0, "Erreur lors de l'installation")
            self.log(f"ERREUR : {str(ex)}")
            messagebox.showerror("Erreur d'installation", f"Une erreur s'est produite :\n{str(ex)}")
            if hasattr(self, 'btn_cancel') and self.btn_cancel.winfo_exists():
                self.btn_cancel.config(state="normal")

    def finish_setup(self):
        target_dir = os.path.abspath(self.var_install_dir.get())
        if self.var_launch_after.get():
            launcher_bat = os.path.join(target_dir, 'DEMARRER.bat')
            launcher_exe = os.path.join(target_dir, 'JIBAYAT.exe')
            if os.path.exists(launcher_exe):
                os.startfile(launcher_exe)
            elif os.path.exists(launcher_bat):
                os.startfile(launcher_bat)
        self.destroy()


if __name__ == "__main__":
    app = JibayatSetupWizard()
    app.mainloop()
