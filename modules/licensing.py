"""
modules/licensing.py — Système de Gestion des Licences & Codes d'Activation JIBAYAT
  • Période d'essai initiale (30 jours par défaut, activation optionnelle)
  • Validation cryptographique robuste par HMAC-SHA256
  • Clés de format : JBYT-XXXX-XXXX-XXXX-XXXX
  • Types de licence : 30 jours, 90 jours, 365 jours, Illimitée / À vie
  • Générateur de codes d'activation intégré (CLI & Interface)
"""
import os
import sys
import json
import time
import hmac
import hashlib
import base64
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, session, current_app
)
from database import get_db

bp = Blueprint('licensing', __name__)

CONFIG_FILE = "config.json"
DEFAULT_TRIAL_DAYS = 30
# Sel de signature cryptographique interne (protégé contre la falsification)
# Chargé depuis variable d'environnement ou config.json (jamais hardcodé en production)
def _load_sign_secret() -> bytes:
    """Charge le secret HMAC depuis l'environnement ou la config."""
    secret = os.environ.get('JIBAYAT_SIGN_SECRET', '').strip()
    if secret:
        return secret.encode('utf-8')
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            s = cfg.get('sign_secret', '').strip()
            if s:
                return s.encode('utf-8')
    except Exception:
        pass
    # Fallback par défaut (à changer en production)
    return b"JIBAYAT_FISCALITE_COMMUNALE_SECURE_SIGN_KEY_2026"

MASTER_SIGN_SECRET = _load_sign_secret()

# ─────────────────────────────────────────────
# 1. MOTEUR CRYPTOGRAPHIQUE DES CLÉS DE LICENCE
# ─────────────────────────────────────────────
TYPE_CODES = {
    '30':   'M1',   # 1 Mois / 30 Jours
    '90':   'M3',   # 3 Mois / 90 Jours
    '365':  'Y1',   # 1 An / 365 Jours
    'LIFE': 'LF',   # Licence Perpétuelle / À vie
}

CODE_TO_TYPE = {v: k for k, v in TYPE_CODES.items()}


def _clean_key(key: str) -> str:
    """Nettoie une clé (supprime tirets, espaces et met en majuscules)."""
    return key.upper().replace('-', '').replace(' ', '').replace('JBYT', '').strip()


def generate_license_key(license_type: str = '365',
                         commune_name: str = '',
                         days: Optional[int] = None) -> str:
    """
    Génère une clé d'activation signée cryptographiquement.
    Format : JBYT-XXXX-XXXX-XXXX-XXXX (Payload 8 caractères + Signature HMAC 8 caractères)
    """
    type_code = TYPE_CODES.get(str(license_type).upper(), 'Y1')

    if type_code == 'LF':
        expiry_days = 65535
    elif days is not None:
        expiry_days = min(int(days), 65535)
    elif type_code == 'M1':
        expiry_days = 30
    elif type_code == 'M3':
        expiry_days = 90
    else:
        expiry_days = 365

    # Payload (8 chars) = Type (2) + Jours validité hex (4) + Sel/Flag aléatoire hex (2)
    days_hex = f"{expiry_days:04X}"
    salt_hex = os.urandom(1).hex().upper()  # 2 caractères hex

    payload = f"{type_code}{days_hex}{salt_hex}"  # 8 caractères

    # Signature HMAC-SHA256 sur les 8 caractères du payload
    sig = hmac.new(MASTER_SIGN_SECRET, payload.encode('utf-8'), hashlib.sha256).hexdigest()[:8].upper()

    full_code = f"{payload}{sig}"  # 16 caractères au total
    formatted_key = f"JBYT-{full_code[0:4]}-{full_code[4:8]}-{full_code[8:12]}-{full_code[12:16]}"
    return formatted_key


def verify_license_key(key: str, commune_name: str = '') -> Tuple[bool, Dict[str, Any], str]:
    """
    Vérifie l'authenticité et la validité d'une clé d'activation.
    Retourne (est_valide, metadata_dict, message).
    """
    if not key:
        return False, {}, "Veuillez saisir une clé d'activation."

    clean = _clean_key(key)
    if len(clean) != 16:
        return False, {}, "Format de clé d'activation invalide (doit comporter 16 caractères après JBYT-)."

    payload = clean[:8]  # Type (2) + Days (4) + Salt (2)
    provided_sig = clean[8:16]  # Signature fournie (8)

    type_code = payload[:2]
    if type_code not in CODE_TO_TYPE:
        return False, {}, "Type de licence inconnu ou altéré."

    try:
        valid_days = int(payload[2:6], 16)
    except ValueError:
        return False, {}, "Données de durée de validité corrompues."

    # Recalcul de la signature HMAC attendue
    expected_sig = hmac.new(MASTER_SIGN_SECRET, payload.encode('utf-8'), hashlib.sha256).hexdigest()[:8].upper()

    if not hmac.compare_digest(provided_sig, expected_sig):
        return False, {}, "Clé d'activation invalide (signature cryptographique incorrecte)."

    matched_type = CODE_TO_TYPE[type_code]
    is_lifetime = matched_type == 'LIFE' or valid_days >= 65535

    type_label = {
        '30': 'Mensuelle (30 jours)',
        '90': 'Trimestrielle (90 jours)',
        '365': 'Annuelle (365 jours)',
        'LIFE': 'Illimitée (À vie)'
    }.get(matched_type, 'Standard')

    meta = {
        'type': matched_type,
        'type_label': type_label,
        'days': valid_days,
        'is_lifetime': is_lifetime
    }
    return True, meta, "Clé d'activation valide."


# ─────────────────────────────────────────────
# 2. STATUT DE LICENCE & PÉRIODE D'ESSAI
# ─────────────────────────────────────────────
def get_license_status() -> Dict[str, Any]:
    """
    Retourne l'état complet de la licence du système :
    - En période d'essai (activation optionnelle)
    - Activé avec clé valide
    - Expiré (activation requise)
    """
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        else:
            cfg = {}
    except Exception:
        cfg = {}

    now = datetime.now()
    trial_days = cfg.get('trial_days', DEFAULT_TRIAL_DAYS)
    install_date_str = cfg.get('install_date')

    # Initialiser la date d'installation si absente
    if not install_date_str:
        install_date_str = now.strftime('%Y-%m-%d %H:%M:%S')
        cfg['install_date'] = install_date_str
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    try:
        install_date = datetime.strptime(install_date_str, '%Y-%m-%d %H:%M:%S')
    except Exception:
        install_date = now

    trial_end_date = install_date + timedelta(days=trial_days)
    trial_days_left = max(0, (trial_end_date.date() - now.date()).days)
    in_trial = now < trial_end_date

    # Vérification de la clé enregistrée
    license_key = cfg.get('license_key', '').strip()
    license_activated_at_str = cfg.get('license_activated_at')
    license_type = cfg.get('license_type', '')
    license_expiry_str = cfg.get('license_expiry')

    is_activated = False
    is_lifetime = False
    days_left = trial_days_left
    expiry_date_display = trial_end_date.strftime('%d/%m/%Y')
    license_label = f"Période d'essai ({trial_days_left} jours restants)"

    if license_key:
        is_valid, meta, _ = verify_license_key(license_key)
        if is_valid:
            is_lifetime = meta.get('is_lifetime', False)
            if is_lifetime:
                is_activated = True
                days_left = 99999
                expiry_date_display = "Illimitée (À vie)"
                license_label = "Licence Perpétuelle (À vie)"
            else:
                if license_expiry_str:
                    try:
                        lic_expiry = datetime.strptime(license_expiry_str, '%Y-%m-%d').date()
                        active_days_left = (lic_expiry - now.date()).days
                        if active_days_left >= 0:
                            is_activated = True
                            days_left = active_days_left
                            expiry_date_display = lic_expiry.strftime('%d/%m/%Y')
                            license_label = f"Licence Active ({days_left} jours restants)"
                    except Exception:
                        pass

    # L'activation est requise UNIQUEMENT si non activé ET période d'essai terminée
    requires_activation = (not is_activated) and (not in_trial)

    return {
        'is_activated': is_activated,
        'in_trial': in_trial,
        'trial_days_left': trial_days_left,
        'days_left': days_left,
        'is_lifetime': is_lifetime,
        'expiry_date': expiry_date_display,
        'license_label': license_label,
        'license_key': license_key,
        'requires_activation': requires_activation,
        'install_date': install_date.strftime('%d/%m/%Y')
    }


def apply_license_key(key: str, commune_name: str = '') -> Tuple[bool, str]:
    """Valide et enregistre une clé d'activation dans config.json."""
    is_valid, meta, msg = verify_license_key(key, commune_name)
    if not is_valid:
        return False, msg

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        else:
            cfg = {}

        now = datetime.now()
        cfg['license_key'] = key.strip()
        cfg['license_activated_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
        cfg['license_type'] = meta.get('type')

        if meta.get('is_lifetime'):
            cfg['license_expiry'] = '9999-12-31'
        else:
            days = meta.get('days', 365)
            expiry = now + timedelta(days=days)
            cfg['license_expiry'] = expiry.strftime('%Y-%m-%d')

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

        # Synchronisation télémétrique asynchrone avec Google Sheets
        try:
            from modules.telemetry import sync_installation_status
            sync_installation_status('activate')
        except Exception:
            pass

        return True, f"Licence validée avec succès ! ({meta.get('type_label')})"
    except Exception as ex:
        return False, f"Erreur lors de l'enregistrement de la licence : {str(ex)}"


# ─────────────────────────────────────────────
# 3. ROUTES FLASK POUR L'ACTIVATION
# ─────────────────────────────────────────────
@bp.route('/activation', methods=['GET', 'POST'])
def activation_page():
    status = get_license_status()

    if request.method == 'POST':
        key = request.form.get('license_key', '').strip()
        ok, msg = apply_license_key(key)
        if ok:
            flash(msg, 'success')
            return redirect(url_for('index'))
        else:
            flash(msg, 'danger')

    return render_template(
        'activation.html',
        status=status,
        version=get_sys_version()
    )


@bp.route('/api/systeme/license-status')
def api_license_status():
    return jsonify(get_license_status())


@bp.route('/api/systeme/activate', methods=['POST'])
def api_activate():
    key = request.form.get('license_key', '').strip()
    commune_nom = request.form.get('commune_nom', '')
    ok, msg = apply_license_key(key, commune_nom)
    return jsonify({'ok': ok, 'msg' if ok else 'error': msg})


def get_sys_version() -> str:
    try:
        if os.path.exists('version.txt'):
            with open('version.txt', 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        pass
    return "1.0.0"
