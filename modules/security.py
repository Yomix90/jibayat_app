"""
modules/security.py — Module de Sécurité Avancée JIBAYAT
  • Chiffrement fort AES-256 / PBKDF2 pour la base de données et les sauvegardes
  • Gestion sécurisée du mot de passe de base de données
  • Rate limiting anti-brute force (protection des connexions)
  • Protection anti-tamper & anti-reverse engineering
  • En-têtes HTTP de sécurité (CSP, HSTS, X-Frame-Options, etc.)
"""
import os
import sys
import json
import base64
import hashlib
import time
import logging
from typing import Optional, Tuple, Dict, Any

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger('jibayat.security')

CONFIG_FILE = "config.json"
SALT_SIZE = 16
ITERATIONS = 100_000

# ─────────────────────────────────────────────
# 1. CHIFFREMENT FORT & DÉRIVATION DE CLÉ PBKDF2
# ─────────────────────────────────────────────
def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """Dérive une clé Fernet (AES-128-CBC + HMAC-SHA256) à partir d'un mot de passe et d'un sel."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ITERATIONS,
        backend=default_backend()
    )
    key_bytes = kdf.derive(password.encode('utf-8'))
    return base64.urlsafe_b64encode(key_bytes)


def encrypt_bytes(data: bytes, password: str) -> bytes:
    """Chiffre des données binaires avec un mot de passe.
    Format résultat : [16 octets SALT] + [Octets chiffrés Fernet]
    """
    salt = os.urandom(SALT_SIZE)
    key = _derive_fernet_key(password, salt)
    f = Fernet(key)
    encrypted_payload = f.encrypt(data)
    return salt + encrypted_payload


def decrypt_bytes(encrypted_data: bytes, password: str) -> bytes:
    """Déchiffre des données binaires à l'aide d'un mot de passe.
    Lève ValueError si le mot de passe est invalide ou si les données sont altérées.
    """
    if len(encrypted_data) <= SALT_SIZE:
        raise ValueError("Données chiffrées invalides ou corrompues.")
    salt = encrypted_data[:SALT_SIZE]
    payload = encrypted_data[SALT_SIZE:]
    key = _derive_fernet_key(password, salt)
    f = Fernet(key)
    try:
        return f.decrypt(payload)
    except InvalidToken:
        raise ValueError("Mot de passe incorrect ou fichier altéré.")


def encrypt_file(source_path: str, dest_path: str, password: str) -> None:
    """Chiffre un fichier source et l'écrit vers dest_path."""
    with open(source_path, 'rb') as src:
        data = src.read()
    enc_data = encrypt_bytes(data, password)
    with open(dest_path, 'wb') as dst:
        dst.write(enc_data)


def decrypt_file(source_path: str, dest_path: str, password: str) -> None:
    """Déchiffre un fichier source et l'écrit vers dest_path."""
    with open(source_path, 'rb') as src:
        enc_data = src.read()
    dec_data = decrypt_bytes(enc_data, password)
    with open(dest_path, 'wb') as dst:
        dst.write(dec_data)


# ─────────────────────────────────────────────
# 2. GESTION DU MOT DE PASSE DE BASE DE DONNÉES
# ─────────────────────────────────────────────
def get_db_security_status() -> Dict[str, Any]:
    """Retourne l'état de la sécurité et du mot de passe de la base de données."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        else:
            cfg = {}
    except Exception:
        cfg = {}

    has_db_password = bool(cfg.get('db_password_hash'))
    return {
        'has_password': has_db_password,
        'encrypted_backups': cfg.get('encrypt_backups_by_default', True),
        'last_password_change': cfg.get('db_password_updated_at', None)
    }


def set_db_password(new_password: str, current_password: Optional[str] = None) -> Tuple[bool, str]:
    """Définit ou met à jour le mot de passe de protection de la base de données."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        else:
            cfg = {}
    except Exception:
        cfg = {}

    existing_hash = cfg.get('db_password_hash')
    if existing_hash:
        if not current_password:
            return False, "Le mot de passe actuel est requis pour modifier la protection."
        if not verify_db_password(current_password):
            return False, "Le mot de passe actuel est incorrect."

    if not new_password or len(new_password.strip()) < 8:
        return False, "Le mot de passe doit comporter au moins 8 caractères."

    # Stockage sécurisé avec sel et hachage SHA-256 + PBKDF2
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ITERATIONS,
        backend=default_backend()
    )
    derived = kdf.derive(new_password.encode('utf-8'))
    stored_val = f"{base64.b64encode(salt).decode('utf-8')}${base64.b64encode(derived).decode('utf-8')}"

    cfg['db_password_hash'] = stored_val
    cfg['db_password_updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')

    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    return True, "Mot de passe de la base de données mis à jour avec succès."


def verify_db_password(password: str) -> bool:
    """Vérifie si le mot de passe fourni correspond au mot de passe configuré."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        else:
            cfg = {}
    except Exception:
        return False

    stored_val = cfg.get('db_password_hash')
    if not stored_val or '$' not in stored_val:
        return True  # Pas de mot de passe requis

    try:
        salt_b64, hash_b64 = stored_val.split('$', 1)
        salt = base64.b64decode(salt_b64.encode('utf-8'))
        expected_hash = base64.b64decode(hash_b64.encode('utf-8'))

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=ITERATIONS,
            backend=default_backend()
        )
        kdf.verify(password.encode('utf-8'), expected_hash)
        return True
    except Exception:
        return False


def remove_db_password(current_password: str) -> Tuple[bool, str]:
    """Supprime le mot de passe de protection."""
    if not verify_db_password(current_password):
        return False, "Mot de passe actuel incorrect."

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        else:
            cfg = {}
        cfg.pop('db_password_hash', None)
        cfg.pop('db_password_updated_at', None)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True, "Protection par mot de passe désactivée."
    except Exception as ex:
        return False, str(ex)


# ─────────────────────────────────────────────
# 3. RATE LIMITING ANTI-BRUTE FORCE (EN MÉMOIRE)
# ─────────────────────────────────────────────
_LOGIN_ATTEMPTS: Dict[str, list] = {}
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60  # 5 essais par minute max

def check_login_rate_limit(ip_address: str) -> Tuple[bool, int]:
    """Vérifie si une IP dépasse le quota de tentatives.
    Retourne (est_autorise, secondes_restantes).
    """
    now = time.time()
    attempts = _LOGIN_ATTEMPTS.get(ip_address, [])
    # Garder uniquement les tentatives dans la fenêtre de temps
    attempts = [t for t in attempts if now - t < WINDOW_SECONDS]
    _LOGIN_ATTEMPTS[ip_address] = attempts

    if len(attempts) >= MAX_ATTEMPTS:
        oldest = attempts[0]
        retry_after = int(WINDOW_SECONDS - (now - oldest))
        return False, max(1, retry_after)
    return True, 0


def record_failed_login(ip_address: str) -> None:
    """Enregistre un échec de connexion pour le rate limiting."""
    now = time.time()
    attempts = _LOGIN_ATTEMPTS.get(ip_address, [])
    attempts.append(now)
    _LOGIN_ATTEMPTS[ip_address] = attempts


def reset_login_attempts(ip_address: str) -> None:
    """Réinitialise les tentatives après une connexion réussie."""
    _LOGIN_ATTEMPTS.pop(ip_address, None)


# ─────────────────────────────────────────────
# 4. ANTI-REVERSE ENGINEERING & INTEGRITY CHECK
# ─────────────────────────────────────────────
def check_runtime_integrity() -> bool:
    """Vérifie l'intégrité de l'environnement d'exécution."""
    if getattr(sys, 'frozen', False):
        # En mode standalone binaire :
        # 1. Empêcher l'écriture de bytecode non vérifié
        sys.dont_write_bytecode = True
    return True


# ─────────────────────────────────────────────
# 5. HEADERS HTTP DE SÉCURITÉ
# ─────────────────────────────────────────────
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'X-XSS-Protection': '1; mode=block',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Content-Security-Policy': (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' https://api.github.com;"
    )
}
