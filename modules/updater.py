"""
modules/updater.py — Système de Mise à Jour Automatique OTA (Over-The-Air) pour JIBAYAT
  • Vérification périodique des mises à jour via GitHub Releases API
  • Téléchargement sécurisé avec vérification SHA-256
  • Sauvegarde préventive automatique des données utilisateur
  • Protection des fichiers critiques (DB, config, uploads)
  • Migration automatique du schéma DB après mise à jour
  • Rollback automatique en cas d'échec
  • API REST pour l'interface web
"""
import os
import sys
import json
import shutil
import hashlib
import logging
import threading
import time
import zipfile
import subprocess
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

from flask import Blueprint, jsonify, request

bp = Blueprint('updater', __name__)
logger = logging.getLogger('jibayat.updater')

CONFIG_FILE = 'config.json'
VERSION_FILE = 'version.txt'
BACKUP_LOG = 'backup_log.json'
DEFAULT_GITHUB_USER = 'Yomix90'
DEFAULT_GITHUB_REPO = 'JIBAYAT'
CHECK_INTERVAL_HOURS = 6

# Fichiers et dossiers qui ne doivent JAMAIS être écrasés lors d'une mise à jour
PROTECTED_ITEMS = {
    'fiscalite.db',
    'fiscalite.db-shm',
    'fiscalite.db-wal',
    'config.json',
    'backup_log.json',
    'jibayat.log',
    'jibayat_debug.log',
    'uploads',
    'static/exports',
}

# Extensions de fichiers de sauvegarde à ne jamais écraser
PROTECTED_EXTENSIONS = {'.db', '.log', '.jibenc', '.enc'}


# ─────────────────────────────────────────────
# 1. ÉTAT GLOBAL DU SYSTÈME DE MISE À JOUR
# ─────────────────────────────────────────────
class UpdateState:
    """Stocke l'état de la vérification/téléchargement de MAJ en mémoire."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.available = False
        self.remote_version = ''
        self.local_version = ''
        self.release_name = ''
        self.release_notes = ''
        self.download_url = ''
        self.published_at = ''
        self.checksum = ''
        self.last_check = None
        self.updating = False
        self.update_progress = 0
        self.update_status = ''
        self.update_error = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'available': self.available,
            'remote_version': self.remote_version,
            'local_version': self.local_version,
            'release_name': self.release_name,
            'release_notes': self.release_notes,
            'download_url': self.download_url,
            'published_at': self.published_at,
            'last_check': self.last_check.strftime('%d/%m/%Y %H:%M') if self.last_check else None,
            'updating': self.updating,
            'update_progress': self.update_progress,
            'update_status': self.update_status,
            'update_error': self.update_error,
        }

_state = UpdateState()
_check_lock = threading.Lock()


# ─────────────────────────────────────────────
# 2. HELPERS
# ─────────────────────────────────────────────
def _load_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _read_version() -> str:
    try:
        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        pass
    return "1.0.0"


def _version_tuple(v: str) -> tuple:
    """Convertit '1.4.9' en (1, 4, 9) pour comparaison."""
    try:
        return tuple(int(x) for x in v.replace('v', '').split('.') if x.isdigit())
    except Exception:
        return (0,)


def _append_backup_log(entry: dict):
    logs = []
    if os.path.exists(BACKUP_LOG):
        try:
            with open(BACKUP_LOG, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.insert(0, entry)
    logs = logs[:50]
    with open(BACKUP_LOG, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def _sha256_file(path: str) -> str:
    """Calcule le hash SHA-256 d'un fichier."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _is_protected(relative_path: str) -> bool:
    """Vérifie si un chemin relatif est protégé et ne doit pas être écrasé."""
    normalized = relative_path.replace('\\', '/')
    # Vérifier les fichiers et dossiers explicitement protégés
    for protected in PROTECTED_ITEMS:
        if normalized == protected or normalized.startswith(protected + '/'):
            return True
    # Vérifier les extensions protégées
    _, ext = os.path.splitext(normalized)
    if ext.lower() in PROTECTED_EXTENSIONS:
        return True
    # Protéger les fichiers de sauvegarde pré-MAJ
    basename = os.path.basename(normalized)
    if basename.startswith('fiscalite_Pre') or basename.startswith('fiscalite_Avant'):
        return True
    return False


# ─────────────────────────────────────────────
# 3. VÉRIFICATION DES MISES À JOUR
# ─────────────────────────────────────────────
def check_for_updates(force: bool = False) -> Dict[str, Any]:
    """
    Vérifie si une nouvelle version est disponible sur GitHub Releases.
    Retourne l'état de la mise à jour.
    """
    global _state

    if not _check_lock.acquire(blocking=False):
        return _state.to_dict()

    try:
        # Éviter les vérifications trop fréquentes (sauf si forcé)
        if not force and _state.last_check:
            elapsed = datetime.now() - _state.last_check
            if elapsed < timedelta(hours=1):
                return _state.to_dict()

        try:
            import requests as _req
        except ImportError:
            import urllib.request
            _req = None

        cfg = _load_config()
        token = cfg.get('github_token', '').strip()
        gh_user = cfg.get('github_user', DEFAULT_GITHUB_USER).strip() or DEFAULT_GITHUB_USER
        gh_repo = cfg.get('github_repo', DEFAULT_GITHUB_REPO).strip() or DEFAULT_GITHUB_REPO
        local_version = _read_version()

        _state.local_version = local_version
        _state.last_check = datetime.now()

        headers = {'Accept': 'application/vnd.github.v3+json'}
        if token:
            headers['Authorization'] = f'token {token}'

        release_url = f'https://api.github.com/repos/{gh_user}/{gh_repo}/releases/latest'

        remote_version = None
        release_name = None
        release_body = None
        download_url = None
        published_at = None
        checksum = None

        if _req:
            try:
                r = _req.get(release_url, headers=headers, timeout=10)
                if r.status_code == 200:
                    rel_data = r.json()
                    tag = rel_data.get('tag_name', '').lstrip('v')
                    remote_version = tag
                    release_name = rel_data.get('name', f"Version {tag}")
                    release_body = rel_data.get('body', '')
                    published_at = rel_data.get('published_at', '')[:10]

                    for asset in rel_data.get('assets', []):
                        name = asset.get('name', '')
                        if name.endswith('.zip') and 'update' in name.lower():
                            download_url = asset.get('browser_download_url')
                        elif name.endswith('.sha256'):
                            # Télécharger le checksum
                            try:
                                cs_url = asset.get('browser_download_url')
                                cs_headers = {}
                                if token:
                                    cs_headers['Authorization'] = f'token {token}'
                                cs_r = _req.get(cs_url, headers=cs_headers, timeout=5)
                                if cs_r.status_code == 200:
                                    checksum = cs_r.text.strip().split()[0]
                            except Exception:
                                pass

                    # Si pas de ZIP spécifique update, chercher n'importe quel ZIP
                    if not download_url:
                        for asset in rel_data.get('assets', []):
                            if asset.get('name', '').endswith('.zip'):
                                download_url = asset.get('browser_download_url')
                                break
            except Exception as e:
                logger.warning(f"Erreur vérification releases GitHub: {e}")

        # Fallback sur version.txt si pas de release
        if not remote_version:
            try:
                txt_url = f'https://api.github.com/repos/{gh_user}/{gh_repo}/contents/version.txt'
                hdr = {'Accept': 'application/vnd.github.v3.raw'}
                if token:
                    hdr['Authorization'] = f'token {token}'
                if _req:
                    r = _req.get(txt_url, headers=hdr, timeout=8)
                    if r.status_code == 200:
                        remote_version = r.text.strip()
                else:
                    req = urllib.request.Request(txt_url, headers=hdr)
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        remote_version = resp.read().decode('utf-8').strip()
            except Exception as e:
                logger.debug(f"Fallback version.txt: {e}")

        if remote_version:
            has_update = _version_tuple(remote_version) > _version_tuple(local_version)
            _state.available = has_update
            _state.remote_version = remote_version
            _state.release_name = release_name or f"JIBAYAT v{remote_version}"
            _state.release_notes = release_body or "Mise à jour disponible."
            _state.download_url = download_url or ''
            _state.published_at = published_at or ''
            _state.checksum = checksum or ''
            _state.update_error = ''

            if has_update:
                logger.info(f"Mise à jour disponible : v{local_version} → v{remote_version}")
        else:
            _state.available = False
            _state.update_error = "Impossible de vérifier la version distante."

        return _state.to_dict()

    except Exception as e:
        logger.error(f"Erreur vérification MAJ: {e}")
        _state.update_error = str(e)
        return _state.to_dict()
    finally:
        _check_lock.release()


# ─────────────────────────────────────────────
# 4. SAUVEGARDE PRÉVENTIVE
# ─────────────────────────────────────────────
def _backup_before_update() -> Tuple[bool, str, str]:
    """
    Crée une sauvegarde complète des données utilisateur avant la mise à jour.
    Retourne (succès, message, chemin_backup).
    """
    dt = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = f'backup_pre_update_{dt}'

    try:
        os.makedirs(backup_dir, exist_ok=True)

        # 1. Sauvegarder la base de données
        if os.path.exists('fiscalite.db'):
            backup_db = os.path.join(backup_dir, 'fiscalite.db')
            shutil.copy2('fiscalite.db', backup_db)
            logger.info(f"Base de données sauvegardée : {backup_db}")

        # 2. Sauvegarder la configuration
        if os.path.exists(CONFIG_FILE):
            shutil.copy2(CONFIG_FILE, os.path.join(backup_dir, 'config.json'))

        # 3. Sauvegarder les uploads
        if os.path.exists('uploads') and os.listdir('uploads'):
            shutil.copytree('uploads', os.path.join(backup_dir, 'uploads'),
                          dirs_exist_ok=True)

        # 4. Sauvegarder le backup_log
        if os.path.exists(BACKUP_LOG):
            shutil.copy2(BACKUP_LOG, os.path.join(backup_dir, 'backup_log.json'))

        _append_backup_log({
            'date': dt,
            'type': 'Sauvegarde Pré-Mise à Jour Automatique',
            'dest': backup_dir,
            'status': '✅ Succès'
        })

        logger.info(f"Sauvegarde pré-MAJ créée : {backup_dir}")
        return True, f"Sauvegarde créée dans {backup_dir}", backup_dir

    except Exception as e:
        logger.error(f"Erreur sauvegarde pré-MAJ: {e}")
        return False, f"Erreur sauvegarde : {e}", ''


# ─────────────────────────────────────────────
# 5. APPLICATION DE LA MISE À JOUR
# ─────────────────────────────────────────────
def apply_update() -> Dict[str, Any]:
    """
    Télécharge et applique la mise à jour de manière sécurisée.
    Préserve les données utilisateur (DB, config, uploads).
    """
    global _state

    if _state.updating:
        return {'ok': False, 'error': 'Une mise à jour est déjà en cours.'}

    if not _state.available:
        return {'ok': False, 'error': 'Aucune mise à jour disponible.'}

    _state.updating = True
    _state.update_progress = 0
    _state.update_status = 'Démarrage de la mise à jour...'
    _state.update_error = ''

    try:
        cfg = _load_config()
        token = cfg.get('github_token', '').strip()
        gh_user = cfg.get('github_user', DEFAULT_GITHUB_USER).strip() or DEFAULT_GITHUB_USER
        gh_repo = cfg.get('github_repo', DEFAULT_GITHUB_REPO).strip() or DEFAULT_GITHUB_REPO
        is_exe = getattr(sys, 'frozen', False)

        # ── Étape 1 : Sauvegarde préventive ─────────────
        _state.update_progress = 10
        _state.update_status = '1/5 — Sauvegarde des données...'
        ok, msg, backup_dir = _backup_before_update()
        if not ok:
            raise RuntimeError(f"Échec de la sauvegarde : {msg}")

        # ── Étape 2 : Téléchargement ────────────────────
        _state.update_progress = 30
        _state.update_status = '2/5 — Téléchargement de la mise à jour...'

        dt = datetime.now().strftime('%Y%m%d_%H%M%S')

        if is_exe and _state.download_url:
            # Mode EXE : télécharger le ZIP depuis GitHub Releases
            zip_path = f'JIBAYAT-update-{dt}.zip'
            _download_file(_state.download_url, zip_path, token)
        elif not is_exe:
            # Mode Script : utiliser git pull
            zip_path = None
        else:
            raise RuntimeError("Aucune URL de téléchargement disponible dans la release GitHub.")

        # ── Étape 3 : Vérification d'intégrité ──────────
        _state.update_progress = 50
        _state.update_status = '3/5 — Vérification d\'intégrité...'

        if zip_path and _state.checksum:
            actual_hash = _sha256_file(zip_path)
            if actual_hash != _state.checksum:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                raise RuntimeError(
                    f"Checksum invalide ! Attendu: {_state.checksum[:16]}... "
                    f"Reçu: {actual_hash[:16]}... Le fichier pourrait être altéré."
                )
            logger.info("Checksum SHA-256 vérifié avec succès.")

        # ── Étape 4 : Application ───────────────────────
        _state.update_progress = 70
        _state.update_status = '4/5 — Application de la mise à jour...'

        if is_exe and zip_path:
            # Mode EXE : extraire le ZIP en protégeant les fichiers utilisateur
            _apply_zip_update(zip_path, backup_dir)
        else:
            # Mode Script : git pull
            _apply_git_update(token, gh_user, gh_repo)

        # ── Étape 5 : Migration DB + Redémarrage ───────
        _state.update_progress = 90
        _state.update_status = '5/5 — Migration de la base de données...'

        # Exécuter les migrations de schéma DB
        try:
            from database import init_db
            init_db()
            logger.info("Migrations de schéma DB exécutées avec succès.")
        except Exception as e:
            logger.warning(f"Migrations DB (non bloquant): {e}")

        _state.update_progress = 100
        _state.update_status = 'Mise à jour terminée ! Redémarrage...'
        _state.available = False

        _append_backup_log({
            'date': dt,
            'type': 'Mise à Jour OTA',
            'dest': f'v{_state.local_version} → v{_state.remote_version}',
            'status': '✅ Succès'
        })

        logger.info(f"Mise à jour appliquée : v{_state.local_version} → v{_state.remote_version}")

        # Planifier le redémarrage
        _schedule_restart(is_exe)

        return {
            'ok': True,
            'msg': f'Mise à jour v{_state.remote_version} installée avec succès ! '
                   f'Sauvegarde créée dans {backup_dir}. L\'application va redémarrer...',
            'backup_dir': backup_dir,
        }

    except Exception as e:
        logger.error(f"Erreur mise à jour OTA: {e}")
        _state.update_error = str(e)
        _state.update_status = f'Erreur : {e}'

        # Tentative de rollback
        if backup_dir:
            _rollback(backup_dir)

        return {'ok': False, 'error': str(e)}
    finally:
        _state.updating = False


def _download_file(url: str, dest: str, token: str = ''):
    """Télécharge un fichier depuis une URL avec support auth GitHub."""
    try:
        import requests as _req
        headers = {}
        if token:
            headers['Authorization'] = f'token {token}'
            headers['Accept'] = 'application/octet-stream'
        r = _req.get(url, headers=headers, timeout=120, stream=True, allow_redirects=True)
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url)
        if token:
            req.add_header('Authorization', f'token {token}')
            req.add_header('Accept', 'application/octet-stream')
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, 'wb') as out:
            shutil.copyfileobj(resp, out)

    logger.info(f"Fichier téléchargé : {dest} ({os.path.getsize(dest)} octets)")


def _apply_zip_update(zip_path: str, backup_dir: str):
    """Extrait le ZIP en protégeant les fichiers utilisateur."""
    extract_dir = tempfile.mkdtemp(prefix='jibayat_update_')

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # Déterminer le dossier racine dans le ZIP (pourrait être un sous-dossier)
        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            source_root = os.path.join(extract_dir, entries[0])
        else:
            source_root = extract_dir

        # Copier les fichiers en protégeant les données utilisateur
        app_root = _get_app_root()
        copied = 0
        skipped = 0

        for root, dirs, files in os.walk(source_root):
            rel_root = os.path.relpath(root, source_root)
            target_root = os.path.join(app_root, rel_root) if rel_root != '.' else app_root

            for file in files:
                rel_path = os.path.join(rel_root, file) if rel_root != '.' else file
                if _is_protected(rel_path):
                    skipped += 1
                    logger.debug(f"Protégé (non écrasé) : {rel_path}")
                    continue

                src = os.path.join(root, file)
                dst = os.path.join(target_root, file)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1

        logger.info(f"MAJ appliquée : {copied} fichiers mis à jour, {skipped} fichiers protégés")

    finally:
        # Nettoyage
        shutil.rmtree(extract_dir, ignore_errors=True)
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass


def _apply_git_update(token: str, gh_user: str, gh_repo: str):
    """Applique la mise à jour via git pull (mode développement)."""
    app_root = _get_app_root()
    env = os.environ.copy()

    if token:
        # Configurer l'authentification git
        git_url = f'https://{token}@github.com/{gh_user}/{gh_repo}.git'
        try:
            subprocess.run(
                ['git', 'remote', 'set-url', 'origin', git_url],
                cwd=app_root, capture_output=True, timeout=10
            )
        except Exception:
            pass

    result = subprocess.run(
        ['git', 'pull', 'origin', 'main'],
        cwd=app_root, capture_output=True, text=True, timeout=60, env=env
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git pull échoué : {error_msg}")

    logger.info(f"git pull réussi : {result.stdout.strip()}")


def _get_app_root() -> str:
    """Retourne le dossier racine de l'application."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rollback(backup_dir: str):
    """Restaure les fichiers critiques depuis la sauvegarde en cas d'échec."""
    try:
        if not os.path.exists(backup_dir):
            return

        # Restaurer la base de données
        backup_db = os.path.join(backup_dir, 'fiscalite.db')
        if os.path.exists(backup_db):
            shutil.copy2(backup_db, 'fiscalite.db')
            logger.info("Rollback : base de données restaurée.")

        # Restaurer la configuration
        backup_cfg = os.path.join(backup_dir, 'config.json')
        if os.path.exists(backup_cfg):
            shutil.copy2(backup_cfg, CONFIG_FILE)
            logger.info("Rollback : configuration restaurée.")

        logger.info("Rollback terminé.")
        _append_backup_log({
            'date': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'type': 'Rollback Mise à Jour',
            'dest': backup_dir,
            'status': '⚠️ Rollback effectué'
        })
    except Exception as e:
        logger.error(f"Erreur rollback: {e}")


def _schedule_restart(is_exe: bool):
    """Planifie un redémarrage de l'application après la mise à jour."""
    def _do_restart():
        time.sleep(2)  # Laisser le temps à la réponse HTTP de partir
        if is_exe:
            executable = sys.executable
            bat_content = f"""@echo off
ping 127.0.0.1 -n 3 > nul
start "" "{executable}"
del "%~f0"
"""
            bat_path = 'restart_after_update.bat'
            with open(bat_path, 'w', encoding='utf-8') as f:
                f.write(bat_content)

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            subprocess.Popen([bat_path], startupinfo=startupinfo)
        os._exit(0)

    threading.Thread(target=_do_restart, daemon=True).start()


# ─────────────────────────────────────────────
# 6. VÉRIFICATION PÉRIODIQUE EN ARRIÈRE-PLAN
# ─────────────────────────────────────────────
_bg_thread_started = False

def start_background_checker():
    """Lance un thread daemon qui vérifie les mises à jour périodiquement."""
    global _bg_thread_started
    if _bg_thread_started:
        return
    _bg_thread_started = True

    def _checker_loop():
        # Premier check après 30 secondes (laisser l'app démarrer)
        time.sleep(30)
        while True:
            try:
                check_for_updates()
                if _state.available:
                    logger.info(
                        f"🔔 Mise à jour disponible : v{_state.local_version} → v{_state.remote_version}"
                    )
            except Exception as e:
                logger.debug(f"Vérification périodique MAJ: {e}")
            # Attendre l'intervalle configuré
            time.sleep(CHECK_INTERVAL_HOURS * 3600)

    t = threading.Thread(target=_checker_loop, daemon=True, name='updater-bg')
    t.start()
    logger.info(f"Vérificateur MAJ démarré (intervalle: {CHECK_INTERVAL_HOURS}h)")


# ─────────────────────────────────────────────
# 7. ROUTES API FLASK
# ─────────────────────────────────────────────
@bp.route('/api/updater/status')
def api_updater_status():
    """Retourne l'état actuel du système de mise à jour (pour polling JS)."""
    return jsonify(_state.to_dict())


@bp.route('/api/updater/check', methods=['POST'])
def api_updater_check():
    """Force une vérification immédiate des mises à jour."""
    from modules.helpers import get_current_user
    user = get_current_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Non connecté'}), 401

    result = check_for_updates(force=True)
    return jsonify({
        'ok': True,
        **result
    })


@bp.route('/api/updater/apply', methods=['POST'])
def api_updater_apply():
    """Applique la mise à jour disponible."""
    from modules.helpers import get_current_user
    user = get_current_user()
    if not user or not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès réservé aux administrateurs'}), 403

    # Lancer la MAJ dans un thread pour ne pas bloquer la réponse HTTP
    result = {'ok': True, 'msg': 'Mise à jour en cours...'}

    def _async_update():
        apply_update()

    if _state.updating:
        return jsonify({'ok': False, 'error': 'Une mise à jour est déjà en cours.'})

    _state.updating = True
    _state.update_progress = 0
    _state.update_status = 'Démarrage...'
    threading.Thread(target=_async_update, daemon=True).start()

    return jsonify(result)


@bp.route('/api/updater/changelog')
def api_updater_changelog():
    """Retourne le contenu du CHANGELOG.md."""
    changelog_path = os.path.join(_get_app_root(), 'CHANGELOG.md')
    if os.path.exists(changelog_path):
        with open(changelog_path, 'r', encoding='utf-8') as f:
            return jsonify({'ok': True, 'content': f.read()})
    return jsonify({'ok': True, 'content': 'Aucun historique de versions disponible.'})
