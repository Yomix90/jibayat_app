"""
launcher.py — Lanceur minimal JIBAYAT
  • Démarre le serveur Flask en arrière-plan
  • Ouvre l'application dans le navigateur
  • Si première installation → ouvre /setup directement
  • Icône dans la barre de notification Windows (system tray)
"""
import tkinter as tk
from tkinter import messagebox
import json, os, socket, webbrowser, threading
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
import pystray
import sys, traceback
sys.stdout = open('jibayat_debug.log', 'w')
sys.stderr = sys.stdout

from app import app, init_db
from werkzeug.serving import make_server

# ─────────────────────────────────────────────
CONFIG_FILE = "config.json"
VERSION_FILE = "version.txt"
PORT = 5050

# ─────────────────────────────────────────────
#  SERVER THREAD
# ─────────────────────────────────────────────
class ServerThread(threading.Thread):
    def __init__(self, flask_app) -> None:  # type: ignore[type-arg]
        super().__init__(daemon=True)
        self.server = make_server("0.0.0.0", PORT, flask_app)
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


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def read_version() -> str:
    try:
        with open(VERSION_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return "1.0.0"


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def make_tray_icon() -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, size - 4, size - 4], fill="#1e3a5f")
    try:
        font = ImageFont.load_default()
        d.text((18, 14), "JB", fill="white", font=font)
    except Exception:
        pass
    d.ellipse([44, 44, 60, 60], fill="#e8a020")
    return img


def is_first_run() -> bool:
    return not os.path.exists(CONFIG_FILE)


def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """Attend que le serveur Flask réponde avant d'ouvrir le navigateur."""
    import time
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
#  MINI FENÊTRE TRAY
# ─────────────────────────────────────────────
class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.ip_local = get_local_ip()
        self.version  = read_version()
        self.server_thread: Optional[ServerThread] = None
        self._tray_icon: Optional[pystray.Icon] = None
        self._tray_running = False

        # Fenêtre principale invisible (juste pour le message tray)
        self.withdraw()
        self.title("JIBAYAT")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Démarrer le serveur immédiatement
        self._start_server()

    def _start_server(self) -> None:
        try:
            self.server_thread = ServerThread(app)
            self.server_thread.start()
        except Exception as e:
            messagebox.showerror("Erreur démarrage serveur", str(e))
            self.destroy()
            return

        # Ouvrir le navigateur une fois le serveur prêt
        threading.Thread(target=self._open_when_ready, daemon=True).start()

        # Lancer le tray
        self._start_tray()

    def _open_when_ready(self) -> None:
        """Attend que Flask réponde puis ouvre le navigateur."""
        if wait_for_server("127.0.0.1", PORT, timeout=12):
            if is_first_run():
                url = f"http://127.0.0.1:{PORT}/setup"
            else:
                url = f"http://127.0.0.1:{PORT}/"
            webbrowser.open(url)
        else:
            self.after(0, lambda: messagebox.showerror(
                "Erreur", "Le serveur n'a pas démarré à temps."))

    def _start_tray(self) -> None:
        icon_image = make_tray_icon()
        ip = self.ip_local
        port = PORT
        ver = self.version

        menu = pystray.Menu(
            pystray.MenuItem(
                f"🏛️  JIBAYAT v{ver}",
                lambda *_: webbrowser.open(f"http://{ip}:{port}/"),
                default=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "🌐  Ouvrir Application (réseau)",
                lambda *_: webbrowser.open(f"http://{ip}:{port}/"),
            ),
            pystray.MenuItem(
                "💻  Ouvrir Application (local)",
                lambda *_: webbrowser.open(f"http://127.0.0.1:{port}/"),
            ),
            pystray.MenuItem(
                "⚙️  Paramètres Système",
                lambda *_: webbrowser.open(f"http://127.0.0.1:{port}/parametres-systeme"),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🔄  Redémarrer JIBAYAT", self._restart_from_tray),
            pystray.MenuItem("✖  Quitter JIBAYAT", self._quit_from_tray),
        )

        self._tray_icon = pystray.Icon("JIBAYAT", icon_image, f"JIBAYAT v{ver} — Serveur actif", menu)
        self._tray_running = True
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

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
        self._quit_from_tray(None, None)  # type: ignore[arg-type]


# ─────────────────────────────────────────────
#  POINT D'ENTRÉE
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app_launcher = LauncherApp()
    app_launcher.mainloop()
