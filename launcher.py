"""
launcher.py — Lanceur enrichi & Barre de notification Windows (System Tray) pour JIBAYAT
  • Démarre le serveur Flask en arrière-plan (thread autonome)
  • Icône haute définition avec logo par défaut et voyant de statut en ligne (🟢)
  • Menu contextuel complet : Accès direct, État commune, Machine ID, Copie URL, Sauvegarde, Explorateur
  • Notification Windows au démarrage
"""
import tkinter as tk
from tkinter import messagebox
import json, os, sys, socket, webbrowser, threading, time, shutil, subprocess, hashlib
from datetime import datetime
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
import pystray

from app import app, init_db
from werkzeug.serving import make_server

# ─────────────────────────────────────────────
CONFIG_FILE = "config.json"
VERSION_FILE = "version.txt"
DEFAULT_PORT = 5050


# ─────────────────────────────────────────────
#  HELPERS & SYSTEM INFO
# ─────────────────────────────────────────────
def read_version() -> str:
    try:
        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return "1.5.2"


def get_commune_nom() -> str:
    try:
        from modules.telemetry import _get_commune_info
        info = _get_commune_info()
        return info.get('nom') or "Commune"
    except Exception:
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                return cfg.get('commune', {}).get('nom') or "Commune"
        except Exception:
            pass
    return "Commune"


def get_machine_id() -> str:
    try:
        from modules.telemetry import get_unique_machine_id
        return get_unique_machine_id()
    except Exception:
        return "PC-LOCAL"


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def copy_to_clipboard(text: str) -> None:
    """Copie une chaîne de texte dans le presse-papiers Windows."""
    try:
        subprocess.run(['clip.exe'], input=text.strip().encode('utf-16le'), check=True)
    except Exception:
        try:
            r = tk.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(text)
            r.update()
            r.destroy()
        except Exception:
            pass


def make_tray_icon() -> Image.Image:
    """Génère l'icône haute définition pour la barre des tâches avec logo.png et voyant 🟢."""
    size = 64
    base_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(base_img)

    # Fond capsule sombre élégant
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=16, fill="#0b1322", outline="#f59e0b", width=2)

    candidates = [
        os.path.join('static', 'img', 'logo.png'),
        os.path.join('_internal', 'static', 'img', 'logo.png'),
        os.path.join('static', 'img', 'app.ico'),
        os.path.join('_internal', 'static', 'img', 'app.ico'),
        'app.ico',
        os.path.join('_internal', 'app.ico'),
    ]

    logo_loaded = False
    for c in candidates:
        if os.path.exists(c):
            try:
                raw_logo = Image.open(c).convert('RGBA')
                # Redimensionner le logo au centre
                raw_logo.thumbnail((44, 44), Image.LANCZOS)
                x = (size - raw_logo.width) // 2
                y = (size - raw_logo.height) // 2
                base_img.paste(raw_logo, (x, y), raw_logo)
                logo_loaded = True
                break
            except Exception:
                pass

    if not logo_loaded:
        # Fallback monogramme doré
        try:
            font = ImageFont.load_default()
            d.text((20, 20), "JB", fill="#fbbf24", font=font)
        except Exception:
            pass

    # Voyant vert d'activité (En ligne 🟢)
    d.ellipse([size - 18, size - 18, size - 4, size - 4], fill="#10b981", outline="#ffffff", width=2)
    return base_img


# ─────────────────────────────────────────────
#  SERVER THREAD
# ─────────────────────────────────────────────
class ServerThread(threading.Thread):
    def __init__(self, flask_app, port: int = DEFAULT_PORT) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.server = make_server("0.0.0.0", port, flask_app)
        self.server.timeout = 1
        ctx = flask_app.app_context()
        ctx.push()

    def run(self) -> None:
        self.server.serve_forever(poll_interval=0.5)

    def shutdown(self) -> None:
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass


_single_instance_mutex = None

def check_and_acquire_single_instance(port: int = DEFAULT_PORT) -> bool:
    """Empêche les lancements multiples de l'application."""
    global _single_instance_mutex

    # 1. Vérifier si le port est déjà actif
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        res = s.connect_ex(('127.0.0.1', port))
        s.close()
        if res == 0:
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return False
    except Exception:
        pass

    # 2. Mutex Windows pour verrouiller l'instance
    if os.name == 'nt':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            mutex_name = "Global\\JIBAYAT_APP_SINGLE_INSTANCE_MUTEX_2026"
            _single_instance_mutex = kernel32.CreateMutexW(None, False, mutex_name)
            last_err = kernel32.GetLastError()
            if last_err == 183:  # ERROR_ALREADY_EXISTS
                webbrowser.open(f"http://127.0.0.1:{port}/")
                return False
        except Exception:
            pass

    return True


def is_first_run() -> bool:
    try:
        import sqlite3
        if not os.path.exists("fiscalite.db"):
            return True
        conn = sqlite3.connect("fiscalite.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM utilisateurs")
        row = c.fetchone()
        conn.close()
        return row is None or row[0] == 0
    except Exception:
        return True


def wait_for_server(host: str, port: int, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=0.5)
            s.close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


# ─────────────────────────────────────────────
#  LAUNCHER GUI & SYSTEM TRAY
# ─────────────────────────────────────────────
class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.port = DEFAULT_PORT
        self.ip_local = get_local_ip()
        self.version = read_version()
        self.commune = get_commune_nom()
        self.machine = get_machine_id()
        self.server_thread: Optional[ServerThread] = None
        self._tray_icon: Optional[pystray.Icon] = None
        self._tray_running = False

        self.withdraw()
        self.title("JIBAYAT")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._start_server()

    def _start_server(self) -> None:
        try:
            self.server_thread = ServerThread(app, port=self.port)
            self.server_thread.start()
        except Exception as e:
            messagebox.showerror("Erreur démarrage serveur", str(e))
            self.destroy()
            return

        threading.Thread(target=self._open_when_ready, daemon=True).start()
        self._start_tray()

    def _open_when_ready(self) -> None:
        if wait_for_server("127.0.0.1", self.port, timeout=12):
            url = f"http://127.0.0.1:{self.port}/setup" if is_first_run() else f"http://127.0.0.1:{self.port}/"
            webbrowser.open(url)
            
            # Notification Windows d'accueil
            if self._tray_icon:
                try:
                    self._tray_icon.notify(
                        title="🏛️ JIBAYAT — Système Prêt",
                        message=f"Serveur actif pour {self.commune}\nAccès : http://{self.ip_local}:{self.port}"
                    )
                except Exception:
                    pass
        else:
            self.after(0, lambda: messagebox.showerror("Erreur", "Le serveur n'a pas démarré à temps."))

    def _start_tray(self) -> None:
        icon_image = make_tray_icon()
        ip = self.ip_local
        port = self.port
        ver = self.version
        commune_name = self.commune
        machine_code = self.machine

        url_local = f"http://127.0.0.1:{port}/"
        url_net = f"http://{ip}:{port}/"

        menu = pystray.Menu(
            pystray.MenuItem(f"🏛️  JIBAYAT PRO v{ver}  🟢", lambda *_: webbrowser.open(url_local), default=True),
            pystray.MenuItem(f"🏢  Commune : {commune_name}", lambda *_: None, enabled=False),
            pystray.MenuItem(f"💻  Poste ID : {machine_code}", lambda *_: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🌐  Ouvrir l'Application (Local)", lambda *_: webbrowser.open(url_local)),
            pystray.MenuItem("📡  Ouvrir sur le Réseau (IP)", lambda *_: webbrowser.open(url_net)),
            pystray.MenuItem("📊  Tableau de Bord & Recettes", lambda *_: webbrowser.open(f"http://127.0.0.1:{port}/")),
            pystray.MenuItem("👥  Registre des Contribuables", lambda *_: webbrowser.open(f"http://127.0.0.1:{port}/contribuables")),
            pystray.MenuItem("⚙️  Paramètres & Modules", lambda *_: webbrowser.open(f"http://127.0.0.1:{port}/parametres-systeme")),
            pystray.MenuItem("📋  Copier l'Adresse Réseau", lambda *_: self._copy_url(url_net)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("💾  Créer une Sauvegarde Immédiate", lambda *_: self._do_quick_backup()),
            pystray.MenuItem("📁  Ouvrir le Dossier d'Installation", lambda *_: os.startfile(os.getcwd()) if hasattr(os, 'startfile') else None),
            pystray.MenuItem("🔄  Redémarrer le Serveur", self._restart_from_tray),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("✖  Quitter JIBAYAT", self._quit_from_tray),
        )

        tooltip_text = f"🏛️ JIBAYAT (v{ver})\nCommune : {commune_name}\nServeur actif sur {url_local}"
        self._tray_icon = pystray.Icon("JIBAYAT", icon_image, tooltip_text, menu)
        self._tray_running = True
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _copy_url(self, url: str) -> None:
        copy_to_clipboard(url)
        if self._tray_icon:
            try:
                self._tray_icon.notify(title="📋 Lien copié", message=f"L'adresse réseau a été copiée :\n{url}")
            except Exception:
                pass

    def _do_quick_backup(self) -> None:
        if os.path.exists("fiscalite.db"):
            try:
                sauv_dir = "sauvegardes"
                os.makedirs(sauv_dir, exist_ok=True)
                dt = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = os.path.join(sauv_dir, f"fiscalite_TrayBackup_{dt}.db")
                shutil.copy2("fiscalite.db", dest)
                if self._tray_icon:
                    self._tray_icon.notify(title="💾 Sauvegarde Réussie", message=f"Base copiée vers :\n{dest}")
            except Exception as e:
                if self._tray_icon:
                    self._tray_icon.notify(title="⚠️ Erreur Sauvegarde", message=str(e))

    def _quit_from_tray(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self._tray_icon:
            self._tray_icon.stop()
        if self.server_thread:
            threading.Thread(target=self.server_thread.shutdown, daemon=True).start()
        self.after(0, self.destroy)

    def _restart_from_tray(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self._tray_icon:
            self._tray_icon.stop()
        if self.server_thread:
            threading.Thread(target=self.server_thread.shutdown, daemon=True).start()
        self.after(500, self._do_restart)

    def _do_restart(self) -> None:
        self.destroy()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def _on_close(self) -> None:
        self._quit_from_tray(None, None)


# ─────────────────────────────────────────────
#  POINT D'ENTRÉE
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if not check_and_acquire_single_instance():
        sys.exit(0)
    app_gui = LauncherApp()
    app_gui.mainloop()
