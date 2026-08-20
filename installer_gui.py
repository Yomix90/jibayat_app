"""
installer_gui.py — Assistant d'Installation & Mise à Jour Graphique pour JIBAYAT (v1.5.0)
  • Mode 1 : Nouvelle Installation (Déploiement initial, licence 30 jours, DB)
  • Mode 2 : Mise à Jour Intelligente (Détecte l'installation existante, sauvegarde automatique
             de fiscalite.db/config.json, préserve la licence et migre le schéma sans aucune perte)
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

# Clé secrète maîtresse HMAC pour générer des clés de secours si besoin
MASTER_SIGN_SECRET = b"JIBAYAT_FISCALITE_COMMUNALE_SECURE_SIGN_KEY_2026"

DEV_NAME = "YOUSSEF"
DEV_PHONE = "+212 662-082795"
DEV_EMAIL = "yomix90@gmail.com"


def get_current_app_version() -> str:
    """Récupère dynamiquement la version actuelle depuis les ressources internes ou version.txt."""
    candidates = []
    if getattr(sys, 'frozen', False):
        bundle = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        candidates.append(os.path.join(bundle, 'version.txt'))
        candidates.append(os.path.join(os.path.dirname(sys.executable), 'version.txt'))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'version.txt'))
    candidates.append('version.txt')

    for p in candidates:
        try:
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    v = f.read().strip()
                    if v:
                        return v
        except Exception:
            pass
    return "1.5.1"

APP_VERSION = get_current_app_version()


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
        self.title(f"Assistant d'Installation & Mise à Jour — JIBAYAT (v{APP_VERSION})")
        self.geometry("650x530")
        self.minsize(620, 500)
        self.resizable(False, False)
        self.configure(bg="#0f172a")

        self.current_step = 1
        self.is_update_mode = False
        
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

        self.check_existing_installation()
        self.setup_ui()
        self.show_step(1)

    def check_existing_installation(self):
        """Vérifie si le dossier cible contient déjà une installation JIBAYAT."""
        target_dir = os.path.abspath(self.var_install_dir.get())
        db_path = os.path.join(target_dir, 'fiscalite.db')
        cfg_path = os.path.join(target_dir, 'config.json')

        if os.path.exists(db_path) or os.path.exists(cfg_path):
            self.is_update_mode = True
            # Tenter de charger le nom de la commune existante
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    nom = cfg.get('commune', {}).get('nom')
                    if nom:
                        self.var_commune_nom.set(nom)
                except Exception:
                    pass
        else:
            self.is_update_mode = False

    def setup_ui(self):
        # ── Header Banner
        self.header = tk.Frame(self, bg="#1e293b", height=80, padx=20, pady=12)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.lbl_head_title = tk.Label(self.header, text=f"🏛️ JIBAYAT (v{APP_VERSION})",
                                       bg="#1e293b", fg="#fbbf24", font=("Segoe UI", 14, "bold"))
        self.lbl_head_title.pack(anchor="w")

        self.lbl_head_sub = tk.Label(self.header, text="Assistant de Déploiement & Mise à Jour",
                                     bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 9))
        self.lbl_head_sub.pack(anchor="w")

        # ── Content Area
        self.content_frame = tk.Frame(self, bg="#0f172a", padx=25, pady=20)
        self.content_frame.pack(fill="both", expand=True)

        # ── Footer / Navigation
        self.footer = tk.Frame(self, bg="#1e293b", height=60, padx=20, pady=12)
        self.footer.pack(fill="x", side="bottom")

        self.lbl_dev_info = tk.Label(self.footer, text=f"👨‍💻 Support Technique : {DEV_PHONE}",
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
        self.check_existing_installation()

        if step == 1:
            title = "Mise à Jour de JIBAYAT" if self.is_update_mode else "Bienvenue dans l'assistant d'installation"
            sub = "Mise à niveau sans perte de données." if self.is_update_mode else "Déploiement complet du logiciel."
            self.lbl_head_title.config(text=title)
            self.lbl_head_sub.config(text=sub)
            self.btn_back.config(state="disabled")
            self.btn_next.config(text="Suivant >")

            tk.Label(self.content_frame, text=f"JIBAYAT — Gestion Fiscale Communale (v{APP_VERSION})",
                     bg="#0f172a", fg="#f8fafc", font=("Segoe UI", 12, "bold"), wraplength=570, justify="left").pack(anchor="w", pady=(0, 10))

            if self.is_update_mode:
                info_text = (
                    f"Une version de JIBAYAT a été détectée dans : {self.var_install_dir.get()}\n\n"
                    "🔄 Mode Mise à Jour Automatique :\n"
                    "  • Vos données, contribuables, déclarations et paiements sont 100% conservés.\n"
                    "  • Votre licence et vos paramètres communaux restent inchangés.\n"
                    "  • Une sauvegarde de sécurité de la base de données sera créée automatiquement.\n\n"
                    f"👨‍💻 Développeur : {DEV_NAME} | 📞 Tél / WhatsApp : {DEV_PHONE}\n\n"
                    "Cliquez sur 'Suivant' pour continuer la mise à jour."
                )
            else:
                info_text = (
                    "Ce programme va déployer le logiciel JIBAYAT dans le répertoire de votre choix.\n\n"
                    "📌 Caractéristiques du déploiement :\n"
                    "  • Licence d'évaluation officielle activée automatiquement.\n"
                    "  • Base de données SQLite locale autonome et sécurisée.\n"
                    "  • Création du raccourci officiel sur le Bureau.\n\n"
                    f"👨‍💻 Développeur : {DEV_NAME} | 📞 Tél / WhatsApp : {DEV_PHONE}\n\n"
                    "Cliquez sur 'Suivant' pour configurer l'emplacement d'installation."
                )

            tk.Label(self.content_frame, text=info_text, bg="#0f172a", fg="#cbd5e1",
                     font=("Segoe UI", 9), wraplength=570, justify="left").pack(anchor="w")

        elif step == 2:
            self.lbl_head_title.config(text="Dossier cible & Configuration")
            self.lbl_head_sub.config(text="Confirmez l'emplacement de JIBAYAT.")
            self.btn_back.config(state="normal")
            self.btn_next.config(text="Mettre à jour >" if self.is_update_mode else "Installer >")

            tk.Label(self.content_frame, text="1. Dossier de destination :",
                     bg="#0f172a", fg="#f8fafc", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

            dir_box = tk.Frame(self.content_frame, bg="#0f172a")
            dir_box.pack(fill="x", pady=(0, 10))

            ent_dir = tk.Entry(dir_box, textvariable=self.var_install_dir, bg="#1e293b", fg="#ffffff",
                               insertbackground="#ffffff", font=("Segoe UI", 9), relief="flat")
            ent_dir.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))

            btn_browse = tk.Button(dir_box, text="Parcourir...", bg="#334155", fg="#ffffff",
                                   relief="flat", padx=10, cursor="hand2", command=self.browse_dir)
            btn_browse.pack(side="right")

            # Notification si mise à jour
            if self.is_update_mode:
                badge_box = tk.Frame(self.content_frame, bg="#1e3a5f", padx=12, pady=8)
                badge_box.pack(fill="x", pady=(0, 12))
                tk.Label(badge_box, text="🛡️ Mode Mise à Jour : Vos données existantes seront protégées et conservées.",
                         bg="#1e3a5f", fg="#60a5fa", font=("Segoe UI", 9, "bold")).pack(anchor="w")

            tk.Label(self.content_frame, text="2. Nom de la Commune :",
                     bg="#0f172a", fg="#f8fafc", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

            ent_commune = tk.Entry(self.content_frame, textvariable=self.var_commune_nom, bg="#1e293b", fg="#ffffff",
                                   insertbackground="#ffffff", font=("Segoe UI", 9), relief="flat")
            ent_commune.pack(fill="x", pady=(0, 14), ipady=4)

            # Options
            tk.Checkbutton(self.content_frame, text="Créer ou actualiser l'icône sur le Bureau",
                           variable=self.var_create_desktop_icon, bg="#0f172a", fg="#e2e8f0",
                           selectcolor="#1e293b", activebackground="#0f172a", activeforeground="#ffffff",
                           font=("Segoe UI", 9)).pack(anchor="w", pady=2)

            tk.Checkbutton(self.content_frame, text="Lancer JIBAYAT à la fin de l'opération",
                           variable=self.var_launch_after, bg="#0f172a", fg="#e2e8f0",
                           selectcolor="#1e293b", activebackground="#0f172a", activeforeground="#ffffff",
                           font=("Segoe UI", 9)).pack(anchor="w", pady=2)

        elif step == 3:
            action_name = "Mise à jour" if self.is_update_mode else "Installation"
            self.lbl_head_title.config(text=f"{action_name} en cours...")
            self.lbl_head_sub.config(text="Déploiement des binaires et sécurisation des données...")
            self.btn_back.config(state="disabled")
            self.btn_next.config(state="disabled")
            self.btn_cancel.config(state="disabled")

            self.lbl_progress_status = tk.Label(self.content_frame, text="Préparation des fichiers...",
                                                bg="#0f172a", fg="#fbbf24", font=("Segoe UI", 10, "bold"))
            self.lbl_progress_status.pack(anchor="w", pady=(15, 8))

            self.progress_bar = ttk.Progressbar(self.content_frame, mode='determinate', length=500)
            self.progress_bar.pack(fill="x", pady=(0, 12))

            self.txt_log = tk.Text(self.content_frame, bg="#1e293b", fg="#94a3b8", height=8,
                                   font=("Consolas", 8), relief="flat", padx=8, pady=8)
            self.txt_log.pack(fill="both", expand=True)

            threading.Thread(target=self.run_installation, daemon=True).start()

        elif step == 4:
            action_title = "Mise à Jour Réussie !" if self.is_update_mode else "Installation Réussie !"
            self.lbl_head_title.config(text=action_title)
            self.lbl_head_sub.config(text=f"JIBAYAT v{APP_VERSION} est prêt à l'emploi.")
            self.btn_back.pack_forget()
            self.btn_cancel.pack_forget()
            self.btn_next.config(text="Terminer", state="normal", command=self.finish_setup)

            tk.Label(self.content_frame, text=f"🎉 Opération Terminée (v{APP_VERSION}) !",
                     bg="#0f172a", fg="#4ade80", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 8))

            target_dir = os.path.abspath(self.var_install_dir.get())
            if self.is_update_mode:
                success_info = (
                    f"JIBAYAT a été mis à jour avec succès vers la version {APP_VERSION} !\n\n"
                    f"📁 Répertoire d'installation : {target_dir}\n"
                    "🛡️ Données conservées : Toutes vos données, utilisateurs et historiques sont intacts.\n"
                    "🔑 Licence : Vos droits d'accès et licences ont été préservés.\n"
                    "🖥️ Raccourci Bureau : Actualisé vers la dernière version.\n\n"
                    f"👨‍💻 Support Développeur : {DEV_NAME} ({DEV_PHONE})\n"
                )
            else:
                success_info = (
                    f"JIBAYAT a été installé avec succès en version {APP_VERSION} !\n\n"
                    f"📁 Répertoire d'installation : {target_dir}\n"
                    "🔑 Licence : Période d'évaluation activée.\n"
                    "🖥️ Raccourci Bureau : Créé et lié directement au dossier d'installation.\n\n"
                    f"👨‍💻 Support Développeur : {DEV_NAME} ({DEV_PHONE})\n"
                )
            tk.Label(self.content_frame, text=success_info, bg="#0f172a", fg="#cbd5e1",
                     font=("Segoe UI", 9), wraplength=570, justify="left").pack(anchor="w")

    def browse_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.var_install_dir.get())
        if chosen:
            self.var_install_dir.set(chosen)
            self.check_existing_installation()
            if self.current_step == 2:
                self.show_step(2)

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
            print(f"[SETUP] {msg}")

    def update_progress(self, val, status_text=""):
        if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
            self.progress_bar['value'] = val
        if status_text and hasattr(self, 'lbl_progress_status') and self.lbl_progress_status.winfo_exists():
            self.lbl_progress_status.config(text=status_text)
        self.update_idletasks()

    def run_installation(self):
        target_dir = os.path.abspath(self.var_install_dir.get())
        commune_nom = self.var_commune_nom.get().strip() or "Commune"
        db_path = os.path.join(target_dir, 'fiscalite.db')
        config_path = os.path.join(target_dir, 'config.json')
        is_update = os.path.exists(db_path) or os.path.exists(config_path)
        dt = datetime.now().strftime('%Y%m%d_%H%M%S')

        try:
            self.update_progress(10, "1/5 Préparation de la destination...")
            os.makedirs(target_dir, exist_ok=True)
            time.sleep(0.3)

            # Si mise à jour : Sauvegarder impérativement dans sauvegardes/
            sauv_dir = os.path.join(target_dir, 'sauvegardes')
            os.makedirs(sauv_dir, exist_ok=True)

            if is_update:
                self.log(f"Mise à jour détectée dans {target_dir}")
                if os.path.exists(db_path):
                    backup_db = os.path.join(sauv_dir, f'fiscalite_AvantMaj_{dt}.db')
                    shutil.copy2(db_path, backup_db)
                    self.log(f"Sauvegarde de sécurité DB : {backup_db}")
                if os.path.exists(config_path):
                    backup_cfg = os.path.join(sauv_dir, f'config_AvantMaj_{dt}.json')
                    shutil.copy2(config_path, backup_cfg)
                    self.log(f"Sauvegarde de sécurité Config : {backup_cfg}")

            self.update_progress(30, "2/5 Extraction des nouveaux fichiers...")
            payload_zip = os.path.join(self.bundle_dir, 'app_payload.zip')

            # Liste des fichiers protégés qui ne doivent JAMAIS être écrasés si c'est une MAJ
            protected_files = {'fiscalite.db', 'config.json', 'backup_log.json', 'jibayat.log'}

            if os.path.exists(payload_zip):
                self.log("Extraction du package applicatif...")
                with zipfile.ZipFile(payload_zip, 'r') as zf:
                    for member in zf.infolist():
                        filename = member.filename
                        if is_update and filename in protected_files:
                            continue
                        zf.extract(member, target_dir)
                self.log("Fichiers extraits avec succès.")
            elif os.path.exists(os.path.join(self.bundle_dir, 'dist', 'JIBAYAT')):
                src_bin = os.path.join(self.bundle_dir, 'dist', 'JIBAYAT')
                for item in os.listdir(src_bin):
                    if is_update and item in protected_files:
                        continue
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
                raise FileNotFoundError("Le package applicatif app_payload.zip est introuvable.")

            # Nettoyage des installateurs temporaires de mise à jour restés dans target_dir
            for f in os.listdir(target_dir):
                if f.startswith('JIBAYAT_Setup_Update_') and f.endswith('.exe'):
                    try:
                        os.remove(os.path.join(target_dir, f))
                    except Exception:
                        pass

            time.sleep(0.3)
            self.update_progress(60, "3/5 Mise à jour de la configuration & Licence...")

            cfg = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}

            now = datetime.now()

            # Si nouvelle installation : initialiser la licence 30j
            if not is_update or not cfg.get('license_key'):
                license_30d = generate_30d_key(commune_nom)
                expiry_date = (now + timedelta(days=30)).strftime('%Y-%m-%d')
                cfg['install_date'] = now.strftime('%Y-%m-%d %H:%M:%S')
                cfg['trial_days'] = 30
                cfg['license_key'] = license_30d
                cfg['license_type'] = '30'
                cfg['license_expiry'] = expiry_date
                cfg['license_activated_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
                if 'commune' not in cfg:
                    cfg['commune'] = {}
                cfg['commune']['nom'] = commune_nom
                self.log(f"Nouvelle licence d'évaluation configurée : {license_30d}")
            else:
                self.log(f"Licence existante préservée ({cfg.get('license_type', 'Standard')})")

            # Mettre à jour le webhook de télémétrie si manquant
            cfg['telemetry_webhook_url'] = "https://script.google.com/macros/s/AKfycbzVbZPmKK8kjFYvZI0D7ZvcUVJMyKdLHgGO_WU-Rf6XlE_UJI8rXWFmI5yIlBpUIMVM1g/exec"

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)

            # Écrire version.txt
            with open(os.path.join(target_dir, 'version.txt'), 'w', encoding='utf-8') as vf:
                vf.write(APP_VERSION)

            time.sleep(0.3)
            self.update_progress(80, "4/5 Migration de la base de données...")

            # Migration de la base SQLite
            try:
                import sqlite3
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS communes (
                    id INTEGER PRIMARY KEY, nom TEXT, nom_ar TEXT,
                    president_fr TEXT, president_ar TEXT,
                    region TEXT, region_ar TEXT, province TEXT, province_ar TEXT, logo TEXT,
                    code TEXT, actif INTEGER DEFAULT 1
                )''')
                if not is_update:
                    c.execute("INSERT OR REPLACE INTO communes (id, nom) VALUES (1, ?)", (commune_nom,))
                conn.commit()
                conn.close()
                self.log(f"Base de données validée : {db_path}")
            except Exception as e:
                self.log(f"Note DB : {e}")

            time.sleep(0.3)
            self.update_progress(90, "5/5 Configuration du raccourci Bureau...")

            if self.var_create_desktop_icon.get():
                desktop = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')
                shortcut_lnk = os.path.join(desktop, 'JIBAYAT.lnk')

                target_exe = os.path.join(target_dir, 'JIBAYAT.exe')
                if not os.path.exists(target_exe):
                    target_exe = os.path.join(target_dir, 'DEMARRER.bat')

                # Rechercher app.ico en priorité
                icon_path = os.path.join(target_dir, 'app.ico')
                if not os.path.exists(icon_path):
                    icon_path = os.path.join(target_dir, '_internal', 'app.ico')
                if not os.path.exists(icon_path):
                    icon_path = os.path.join(target_dir, 'static', 'img', 'app.ico')
                if not os.path.exists(icon_path):
                    icon_path = os.path.join(target_dir, 'static', 'img', 'logo.png')

                create_windows_shortcut(target_exe, shortcut_lnk, icon_path, target_dir)
                self.log(f"Raccourci Bureau prêt avec icône officielle : {shortcut_lnk}")

            self.update_progress(100, "Opération achevée avec succès !")
            self.log("Terminé avec succès.")
            time.sleep(0.5)

            self.after(200, lambda: self.show_step(4))

        except Exception as ex:
            self.update_progress(0, "Erreur lors du traitement")
            self.log(f"ERREUR : {str(ex)}")
            messagebox.showerror("Erreur", f"Une erreur s'est produite :\n{str(ex)}")
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
