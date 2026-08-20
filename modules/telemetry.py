"""
modules/telemetry.py — Liaison Google Sheets pour la télémétrie des communes et les suggestions
Envoie les données de manière asynchrone (non-bloquante) via Webhook Google Apps Script.
"""
import json
import os
import threading
import logging
import socket
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


def _get_app_version() -> str:
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            pass
    return "1.0.0"


def _get_commune_info() -> Dict[str, str]:
    """Récupère les informations de la commune depuis la DB ou config.json."""
    try:
        from database import get_db
        conn = get_db()
        c = conn.execute("SELECT nom, region, province, code FROM communes WHERE id=1").fetchone()
        if c:
            return {
                'nom': c['nom'] or 'Commune',
                'region': c['region'] or '',
                'province': c['province'] or '',
                'code': c['code'] or 'COM-01'
            }
    except Exception:
        pass

    cfg = _get_config()
    cm = cfg.get('commune', {})
    return {
        'nom': cm.get('nom', 'Commune'),
        'region': cm.get('region', ''),
        'province': cm.get('province', ''),
        'code': cm.get('code', 'COM-01')
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
            webhook_url = cfg.get('telemetry_webhook_url', DEFAULT_WEBHOOK_URL)
            if not webhook_url:
                return

            from modules.licensing import get_license_status
            lic = get_license_status()
            commune = _get_commune_info()

            payload = {
                'action': action,
                'commune_nom': commune.get('nom'),
                'commune_code': commune.get('code'),
                'region': commune.get('region'),
                'province': commune.get('province'),
                'version': _get_app_version(),
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
    Transmet un avis ou une suggestion d'un utilisateur vers Google Sheets.
    Appel asynchrone non-bloquant.
    """
    def _worker():
        try:
            cfg = _get_config()
            webhook_url = cfg.get('telemetry_webhook_url', DEFAULT_WEBHOOK_URL)
            if not webhook_url:
                return

            commune = _get_commune_info()
            payload = {
                'action': 'feedback',
                'commune_nom': commune.get('nom'),
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
