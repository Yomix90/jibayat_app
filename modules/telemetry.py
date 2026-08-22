"""
modules/telemetry.py — Liaison Google Sheets pour la télémétrie des communes et les suggestions
Envoie les données de manière asynchrone (non-bloquante) via Webhook Google Apps Script.
"""
import json
import os
import threading
import logging
import socket
import uuid
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

_logger = logging.getLogger('jibayat.telemetry')
CONFIG_FILE = 'config.json'
VERSION_FILE = 'version.txt'

# URL officielle du webhook Google Apps Script (intégrée par défaut)
DEFAULT_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzVbZPmKK8kjFYvZI0D7ZvcUVJMyKdLHgGO_WU-Rf6XlE_UJI8rXWFmI5yIlBpUIMVM1g/exec"


def _get_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def get_mac_address() -> str:
    """Obtient l'adresse MAC physique réelle de la machine."""
    try:
        mac_num = uuid.getnode()
        mac_hex = f"{mac_num:012X}"
        return ":".join(mac_hex[i:i+2] for i in range(0, 12, 2))
    except Exception:
        return "00:00:00:00:00:00"


def get_unique_machine_id() -> str:
    """Génère un identifiant unique universel pour ce PC (MAC + Hostname + MachineGuid)."""
    cfg = _get_config()
    if cfg.get('machine_id'):
        return cfg['machine_id']

    mac = get_mac_address()
    host = socket.gethostname() if hasattr(socket, 'gethostname') else 'HOST'

    guid = ""
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        except Exception:
            pass

    clean_mac = mac.replace(':', '')[-6:]
    raw = f"{mac}_{host}_{guid}".encode('utf-8')
    h = hashlib.sha256(raw).hexdigest()[:8].upper()
    unique_id = f"PC-{clean_mac}-{h}"

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                c = json.load(f)
            c['machine_id'] = unique_id
            c['mac_address'] = mac
            c['installation_id'] = unique_id
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(c, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    return unique_id


def _get_installation_id() -> str:
    return get_unique_machine_id()


def _get_app_version() -> str:
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            pass
    return "1.5.2"


def _get_commune_info() -> Dict[str, str]:
    """Récupère les informations réelles et authentiques de la commune depuis la DB ou config.json."""
    nom = ""
    nom_ar = ""
    region = ""
    province = ""
    code = "COM-01"

    # 1. Vérification dans la base SQLite
    try:
        from database import get_db
        conn = get_db()
        c = conn.execute("SELECT nom, nom_ar, region, province, code FROM communes WHERE id=1").fetchone()
        if c:
            db_nom = (c['nom'] or '').strip()
            if db_nom and db_nom.lower() not in ('ma commune', 'commune', 'ma_commune', 'mon commune'):
                nom = db_nom
            nom_ar = c['nom_ar'] or ''
            region = c['region'] or ''
            province = c['province'] or ''
            code = c['code'] or 'COM-01'
    except Exception:
        pass

    # 2. Compléter depuis config.json si absent
    cfg = _get_config()
    cm = cfg.get('commune', {})
    if not nom:
        cfg_nom = cm.get('nom', '').strip()
        if cfg_nom and cfg_nom.lower() not in ('ma commune', 'commune', 'ma_commune', 'mon commune'):
            nom = cfg_nom
    if not nom_ar:
        nom_ar = cm.get('nom_ar', '')
    if not region:
        region = cm.get('region', '')
    if not province:
        province = cm.get('province', '')
    if not code:
        code = cm.get('code', 'COM-01')

    # Fallback propre
    if not nom:
        nom = "Commune Non Configurée"

    return {
        'nom': nom,
        'nom_ar': nom_ar,
        'region': region,
        'province': province,
        'code': code
    }


def _send_http_post(url: str, data: Dict[str, Any], timeout: int = 10) -> bool:
    """Envoie un POST JSON sécurisé et tolérant aux erreurs vers le webhook Google Apps Script."""
    target_url = url or DEFAULT_WEBHOOK_URL
    if not target_url or not target_url.startswith('https://'):
        _logger.debug("Aucune URL HTTPS de webhook Google Sheets configurée.")
        return False

    try:
        import requests
        resp = requests.post(
            target_url,
            json=data,
            headers={
                'Content-Type': 'application/json; charset=utf-8',
                'User-Agent': f'JIBAYAT-Telemetry/{_get_app_version()}'
            },
            timeout=timeout,
            allow_redirects=True
        )
        status = resp.status_code
        _logger.info(f"Télémétrie transmise à Google Sheets (HTTP {status})")
        return status in (200, 201, 302)
    except Exception:
        try:
            json_data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(
                target_url,
                data=json_data,
                headers={
                    'Content-Type': 'application/json; charset=utf-8',
                    'User-Agent': f'JIBAYAT-Telemetry/{_get_app_version()}'
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                _logger.info(f"Télémétrie transmise à Google Sheets via fallback (HTTP {status})")
                return status in (200, 201, 302)
        except Exception as e:
            _logger.debug(f"Échec de l'envoi de la télémétrie Google Sheets : {e}")
            return False


def dispatch_async(target_fn, *args, **kwargs):
    """Exécute une fonction dans un thread d'arrière-plan sans bloquer l'application."""
    thread = threading.Thread(target=target_fn, args=args, kwargs=kwargs, daemon=True)
    thread.start()


def sync_installation_status(action: str = 'ping'):
    """
    Transmet l'état de l'installation et de la licence de la commune vers Google Sheets.
    Appel asynchrone non-bloquant.
    """
    def _worker():
        try:
            cfg = _get_config()
            webhook_url = cfg.get('telemetry_webhook_url') or cfg.get('feedback_webhook') or DEFAULT_WEBHOOK_URL
            if not webhook_url:
                return

            from modules.licensing import get_license_status
            lic = get_license_status()
            commune = _get_commune_info()
            inst_id = get_unique_machine_id()
            mac = get_mac_address()

            payload = {
                'action': action,
                'machine_id': inst_id,
                'mac_address': mac,
                'installation_id': inst_id,
                'commune_nom': commune.get('nom'),
                'commune_nom_ar': commune.get('nom_ar'),
                'commune_code': commune.get('code'),
                'region': commune.get('region'),
                'province': commune.get('province'),
                'hostname': socket.gethostname() if hasattr(socket, 'gethostname') else '',
                'version': _get_app_version(),
                'modules_actifs': ", ".join(cfg.get('modules', [])) if isinstance(cfg.get('modules'), list) else '',
                'is_activated': lic.get('is_activated', False),
                'in_trial': lic.get('in_trial', False),
                'license_state': 'Activé' if lic.get('is_activated') else ('Essai' if lic.get('in_trial') else 'Expiré'),
                'license_key': lic.get('license_key', ''),
                'license_expiry': lic.get('expiry_date', ''),
                'days_left': lic.get('days_left', 0),
                'install_date': lic.get('install_date', ''),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            _send_http_post(webhook_url, payload)
        except Exception as e:
            _logger.debug(f"Erreur worker sync_installation_status : {e}")

    dispatch_async(_worker)


def send_feedback_to_sheet(nom: str, email: str, message: str, type_feedback: str = 'Suggestion', note: str = ''):
    """
    Transmet un avis ou une suggestion d'un utilisateur vers Google Sheets avec le nom de sa commune.
    Appel asynchrone non-bloquant.
    """
    def _worker():
        try:
            cfg = _get_config()
            webhook_url = cfg.get('telemetry_webhook_url') or cfg.get('feedback_webhook') or DEFAULT_WEBHOOK_URL
            if not webhook_url:
                return

            commune = _get_commune_info()
            inst_id = get_unique_machine_id()
            mac = get_mac_address()

            payload = {
                'action': 'feedback',
                'machine_id': inst_id,
                'mac_address': mac,
                'installation_id': inst_id,
                'commune_nom': commune.get('nom'),
                'commune_nom_ar': commune.get('nom_ar'),
                'region': commune.get('region'),
                'province': commune.get('province'),
                'nom': nom,
                'email': email,
                'type_feedback': type_feedback,
                'note': note,
                'message': message,
                'version': _get_app_version(),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            _send_http_post(webhook_url, payload)
        except Exception as e:
            _logger.debug(f"Erreur worker send_feedback_to_sheet : {e}")

    dispatch_async(_worker)
