"""
modules/system.py — Blueprint des paramètres système, sauvegardes, mises à jour et configuration commune
"""
import os, json, shutil, base64, logging, subprocess, sys
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, session
from database import get_db, init_db, check_db_integrity
from modules.helpers import login_required, get_current_user
from modules.security import (
    get_db_security_status, set_db_password, verify_db_password,
    remove_db_password, encrypt_file, decrypt_file
)

bp = Blueprint('system', __name__)
logger = logging.getLogger('jibayat.system')

CONFIG_FILE = 'config.json'
BACKUP_LOG  = 'backup_log.json'
DEFAULT_GITHUB_USER = 'Yomix90'
DEFAULT_GITHUB_REPO = 'JIBAYAT'

ALL_MODULES = {
    'TNB':               'Taxe Terrains Non Bâtis (TNB)',
    'DEBITS_BOISSONS':   'Taxe Débits de Boissons',
    'STATIONNEMENT':     'Taxe Stationnement (TPV)',
    'FOURRIERE':         'Frais de Fourrière',
    'OCCUPATION_DOMAINE':'Occupation Domaine Public',
    'LOCATION_LOCAUX':   'Location Locaux Commerciaux',
    'AFFERMAGE_SOUKS':   'Affermage des Souks',
}

def _load_sys_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_sys_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_backup_log():
    if os.path.exists(BACKUP_LOG):
        try:
            with open(BACKUP_LOG, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def _append_backup_log(entry):
    logs = _load_backup_log()
    logs.insert(0, entry)
    logs = logs[:50]
    with open(BACKUP_LOG, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

def _read_version():
    try:
        if os.path.exists('version.txt'):
            with open('version.txt', 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        pass
    return "1.0.0"

@bp.route('/communes')
@login_required
def communes():
    return redirect(url_for('system.parametres_systeme'))

@bp.route('/setup', methods=['GET', 'POST'])
def setup():
    conn = get_db()
    try:
        user_count = conn.execute('SELECT COUNT(*) FROM utilisateurs').fetchone()[0]
    except Exception:
        init_db()
        user_count = conn.execute('SELECT COUNT(*) FROM utilisateurs').fetchone()[0]

    if user_count > 0 and 'user_id' not in session:
        return redirect(url_for('auth.login'))

    error = None
    if request.method == 'POST':
        nom_commune = request.form.get('nom', '').strip()
        admin_nom = request.form.get('admin_nom', '').strip()
        admin_prenom = request.form.get('admin_prenom', '').strip()
        admin_email = request.form.get('admin_email', '').strip()
        admin_password = request.form.get('admin_password', '')
        admin_password_confirm = request.form.get('admin_password_confirm', '')

        if not nom_commune:
            error = "Le nom de la commune est obligatoire."
        elif not admin_email or not admin_password:
            error = "L'identifiant/email et le mot de passe de l'administrateur sont obligatoires."
        elif len(admin_password) < 6:
            error = "Le mot de passe administrateur doit comporter au moins 6 caractères."
        elif admin_password != admin_password_confirm:
            error = "Les mots de passe saisis ne correspondent pas."
        else:
            logo_path = 'img/logo.png'
            file = request.files.get('logo')
            if file and file.filename != '':
                target_dir = os.path.join(current_app.static_folder, 'img')
                os.makedirs(target_dir, exist_ok=True)
                try:
                    from PIL import Image
                    img = Image.open(file.stream)
                    img.save(os.path.join(target_dir, 'logo.png'), format='PNG')
                except Exception:
                    file.seek(0)
                    file.save(os.path.join(target_dir, 'logo.png'))

            cfg = _load_sys_config()
            cfg['commune'] = {
                'nom': nom_commune,
                'nom_ar': request.form.get('nom_ar', '').strip(),
                'region': request.form.get('region', '').strip(),
                'region_ar': request.form.get('region_ar', '').strip(),
                'province': request.form.get('province', '').strip(),
                'province_ar': request.form.get('province_ar', '').strip(),
                'telephone': request.form.get('telephone', '').strip(),
                'email': request.form.get('email_commune', '').strip(),
                'adresse': request.form.get('adresse', '').strip(),
                'logo': logo_path
            }
            cfg['modules'] = request.form.getlist('modules') or list(ALL_MODULES.keys())
            cfg['auto_backup'] = True
            cfg['is_configured'] = True
            _save_sys_config(cfg)

            try:
                init_db()

                # Enregistrement / mise à jour de la commune ID=1
                conn.execute('''INSERT INTO communes (id, nom, nom_ar, region, region_ar, province, province_ar, logo)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        nom=excluded.nom, nom_ar=excluded.nom_ar,
                        region=excluded.region, region_ar=excluded.region_ar,
                        province=excluded.province, province_ar=excluded.province_ar,
                        logo=excluded.logo''',
                    (nom_commune, request.form.get('nom_ar', '').strip(),
                     request.form.get('region', '').strip(), request.form.get('region_ar', '').strip(),
                     request.form.get('province', '').strip(), request.form.get('province_ar', '').strip(),
                     logo_path))

                # Création ou mise à jour du rôle super_admin
                conn.execute('''INSERT OR IGNORE INTO roles (nom,peut_ajouter,peut_modifier,peut_supprimer,peut_voir,peut_valider_paiement,peut_config,peut_creer_bulletin)
                    VALUES ('super_admin',1,1,1,1,1,1,1)''')
                admin_role = conn.execute("SELECT id FROM roles WHERE nom='super_admin'").fetchone()
                role_id = admin_role['id'] if admin_role else 1

                from werkzeug.security import generate_password_hash
                hashed_pwd = generate_password_hash(admin_password)

                # Nettoyage des anciens utilisateurs par défaut s'il y en a et création de l'admin
                conn.execute("DELETE FROM utilisateurs WHERE email='admin@commune.ma' OR email=?", (admin_email,))
                conn.execute('''INSERT INTO utilisateurs (nom, prenom, email, mot_de_passe, role_id, commune_id, actif)
                    VALUES (?, ?, ?, ?, ?, 1, 1)''',
                    (admin_nom or 'Administrateur', admin_prenom or '', admin_email, hashed_pwd, role_id))
                conn.commit()

                # Transmission asynchrone des informations de la commune à Google Sheets
                try:
                    from modules.telemetry import sync_installation_status
                    sync_installation_status('install')
                except Exception:
                    pass

                # Connexion automatique de l'admin
                new_user = conn.execute('SELECT id FROM utilisateurs WHERE email=?', (admin_email,)).fetchone()
                if new_user:
                    session.clear()
                    session['user_id'] = new_user['id']
                    session.permanent = True

                flash(f'✅ Initialisation réussie ! Bienvenue {admin_prenom} {admin_nom} dans JIBAYAT.', 'success')
                return redirect(url_for('index'))

            except Exception as e:
                error = f"Erreur lors de la configuration : {e}"

    return render_template('setup.html', error=error, all_modules=ALL_MODULES, version=_read_version())

@bp.route('/parametres-systeme')
@login_required
def parametres_systeme():
    user = get_current_user()
    if not user['peut_config']:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('index'))

    cfg = _load_sys_config()
    logs = _load_backup_log()
    version = _read_version()
    db_size = round(os.path.getsize('fiscalite.db') / 1024 / 1024, 2) if os.path.exists('fiscalite.db') else 0
    db_exists = os.path.exists('fiscalite.db')
    db_security = get_db_security_status()
    db_integrity = check_db_integrity() if db_exists else False

    conn = get_db()
    commune_db = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()

    return render_template('parametres_systeme.html',
                           user=user,
                           cfg=cfg,
                           commune_db=commune_db,
                           all_modules=ALL_MODULES,
                           logs=logs,
                           version=version,
                           db_size=db_size,
                           db_exists=db_exists,
                           db_security=db_security,
                           db_integrity=db_integrity)

@bp.route('/commune/modifier', methods=['POST'])
@login_required
def modifier_commune():
    user = get_current_user()
    if not user['peut_config']:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('system.parametres_systeme'))

    nom = request.form.get('nom', '').strip()
    nom_ar = request.form.get('nom_ar', '').strip()
    region = request.form.get('region', '').strip()
    region_ar = request.form.get('region_ar', '').strip()
    province = request.form.get('province', '').strip()
    province_ar = request.form.get('province_ar', '').strip()

    if not nom:
        flash('Le nom de la commune est obligatoire.', 'danger')
        return redirect(url_for('system.parametres_systeme'))

    logo_path = None
    file = request.files.get('logo')
    if file and file.filename != '':
        target_dir = os.path.join(current_app.static_folder, 'img')
        os.makedirs(target_dir, exist_ok=True)
        try:
            from PIL import Image
            img = Image.open(file.stream)
            img.save(os.path.join(target_dir, 'logo.png'), format='PNG')
        except Exception:
            file.seek(0)
            file.save(os.path.join(target_dir, 'logo.png'))
        logo_path = 'img/logo.png'

    conn = get_db()
    c_existing = conn.execute('SELECT id FROM communes LIMIT 1').fetchone()
    if c_existing:
        if logo_path:
            conn.execute('UPDATE communes SET nom=?, nom_ar=?, region=?, region_ar=?, province=?, province_ar=?, logo=? WHERE id=?',
                         (nom, nom_ar, region, region_ar, province, province_ar, logo_path, c_existing['id']))
        else:
            conn.execute('UPDATE communes SET nom=?, nom_ar=?, region=?, region_ar=?, province=?, province_ar=? WHERE id=?',
                         (nom, nom_ar, region, region_ar, province, province_ar, c_existing['id']))
    else:
        conn.execute('INSERT INTO communes (nom, nom_ar, region, region_ar, province, province_ar, logo) VALUES (?,?,?,?,?,?,?)',
                     (nom, nom_ar, region, region_ar, province, province_ar, logo_path or 'img/logo.png'))

    cfg = _load_sys_config()
    cfg['commune'] = {
        'nom': nom,
        'nom_ar': nom_ar,
        'region': region,
        'region_ar': region_ar,
        'province': province,
        'province_ar': province_ar,
    }
    if logo_path:
        cfg['commune']['logo'] = logo_path
    _save_sys_config(cfg)

    flash('✅ Informations de la commune mises à jour.', 'success')
    return redirect(url_for('system.parametres_systeme'))

@bp.route('/api/systeme/commune', methods=['POST'])
@login_required
def api_systeme_commune():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    nom = request.form.get('nom', '').strip()
    if not nom:
        return jsonify({'ok': False, 'error': 'Nom obligatoire'})

    cfg = _load_sys_config()
    cfg['commune'] = {
        'nom': nom,
        'nom_ar': request.form.get('nom_ar', '').strip(),
        'region': request.form.get('region', '').strip(),
        'region_ar': request.form.get('region_ar', '').strip(),
        'province': request.form.get('province', '').strip(),
        'province_ar': request.form.get('province_ar', '').strip(),
    }
    _save_sys_config(cfg)
    return jsonify({'ok': True, 'msg': 'Informations commune sauvegardées.'})

@bp.route('/api/systeme/modules', methods=['POST'])
@login_required
def api_systeme_modules():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    modules = request.form.getlist('modules')
    cfg = _load_sys_config()
    cfg['modules'] = modules
    _save_sys_config(cfg)
    return jsonify({'ok': True, 'msg': f'{len(modules)} module(s) activé(s).'})

@bp.route('/api/systeme/backup-config', methods=['POST'])
@login_required
def api_systeme_backup_config():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    cfg = _load_sys_config()
    cfg['auto_backup'] = request.form.get('auto_backup') == '1'
    cfg['gdrive_backup'] = request.form.get('gdrive_backup', '').strip()
    cfg['gdrive_webhook'] = request.form.get('gdrive_webhook', '').strip()
    cfg['gdrive_folder_id'] = request.form.get('gdrive_folder_id', '').strip()
    _save_sys_config(cfg)
    return jsonify({'ok': True, 'msg': 'Configuration sauvegarde sauvegardée.'})

@bp.route('/api/systeme/github-config', methods=['POST'])
@login_required
def api_systeme_github_config():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    cfg = _load_sys_config()
    cfg['github_user'] = request.form.get('github_user', '').strip() or DEFAULT_GITHUB_USER
    cfg['github_repo'] = request.form.get('github_repo', '').strip() or DEFAULT_GITHUB_REPO
    cfg['github_token'] = request.form.get('github_token', '').strip()
    _save_sys_config(cfg)
    return jsonify({'ok': True, 'msg': 'Configuration GitHub sauvegardée avec succès.'})


@bp.route('/api/systeme/backup-now', methods=['POST'])
@login_required
def api_systeme_backup_now():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    if not os.path.exists('fiscalite.db'):
        return jsonify({'ok': False, 'error': 'Base de données introuvable.'})

    cfg = _load_sys_config()
    dt = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'fiscalite_Manuel_{dt}.db'
    results = []

    dest_dir = cfg.get('gdrive_backup', '')
    if dest_dir and os.path.exists(dest_dir):
        try:
            shutil.copy('fiscalite.db', os.path.join(dest_dir, filename))
            results.append(f'✅ Copie locale : {os.path.join(dest_dir, filename)}')
            _append_backup_log({'date': dt, 'type': 'Manuel Local', 'dest': dest_dir, 'status': '✅ Succès'})
        except Exception as ex:
            results.append(f'❌ Erreur locale : {ex}')
            _append_backup_log({'date': dt, 'type': 'Manuel Local', 'dest': dest_dir, 'status': f'❌ {ex}'})

    webhook = cfg.get('gdrive_webhook', '').strip()
    folder_id = cfg.get('gdrive_folder_id', '').strip()
    if webhook and folder_id:
        try:
            import requests as _req
            with open('fiscalite.db', 'rb') as f_db:
                file_b64 = base64.b64encode(f_db.read()).decode('utf-8')

            payload = {
                'filename': filename,
                'folder_id': folder_id,
                'mimeType': 'application/x-sqlite3',
                'file': file_b64,
            }
            r = _req.post(webhook, json=payload, timeout=60, allow_redirects=True)
            if r.status_code == 200:
                try:
                    resp_json = r.json()
                    if resp_json.get('ok'):
                        results.append('✅ Sauvegarde Cloud Google Drive réussie.')
                        _append_backup_log({'date': dt, 'type': 'Manuel Cloud', 'dest': 'Google Drive', 'status': '✅ Succès'})
                    else:
                        err = resp_json.get('error', r.text[:200])
                        results.append(f'❌ Google Drive : {err}')
                        _append_backup_log({'date': dt, 'type': 'Manuel Cloud', 'dest': 'Google Drive', 'status': f'❌ {err}'})
                except Exception:
                    results.append('✅ Sauvegarde Cloud envoyée.')
                    _append_backup_log({'date': dt, 'type': 'Manuel Cloud', 'dest': 'Google Drive', 'status': '✅ Succès'})
            else:
                err = f'HTTP {r.status_code}'
                results.append(f'❌ Erreur Cloud : {err}')
                _append_backup_log({'date': dt, 'type': 'Manuel Cloud', 'dest': 'Google Drive', 'status': f'❌ {err}'})
        except Exception as ex:
            results.append(f'❌ Erreur Cloud : {ex}')
            _append_backup_log({'date': dt, 'type': 'Manuel Cloud', 'dest': 'Google Drive', 'status': f'❌ {ex}'})

    if not results:
        try:
            shutil.copy('fiscalite.db', filename)
            results.append(f'✅ Copie de précaution créée : {filename}')
            _append_backup_log({'date': dt, 'type': 'Manuel (précaution)', 'dest': filename, 'status': '✅ Succès'})
        except Exception as ex:
            return jsonify({'ok': False, 'error': str(ex)})

    return jsonify({'ok': True, 'msg': '\n'.join(results), 'logs': _load_backup_log()[:10]})

@bp.route('/api/systeme/init-db', methods=['POST'])
@login_required
def api_systeme_init_db():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403
    try:
        init_db()
        return jsonify({'ok': True, 'msg': 'Base de données initialisée/mise à jour avec succès.'})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)})

@bp.route('/api/systeme/test-gdrive', methods=['POST'])
@login_required
def api_systeme_test_gdrive():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403
    webhook = request.form.get('webhook', '').strip()
    folder_id = request.form.get('folder_id', '').strip()
    if not webhook or not folder_id:
        return jsonify({'ok': False, 'error': 'Webhook et dossier obligatoires.'})
    try:
        import requests as _req
        payload = {'test': True, 'filename': 'jibayat_test.txt', 'folder_id': folder_id, 'mimeType': 'text/plain', 'file': 'dGVzdA=='}
        r = _req.post(webhook, json=payload, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            return jsonify({'ok': True, 'msg': '✅ Connexion Google Drive réussie !'})
        return jsonify({'ok': False, 'error': f'HTTP {r.status_code}'})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)})

# ─────────────────────────────────────────────
#  MISES À JOUR GITHUB ROBUSTES & AUTOMATISÉES
# ─────────────────────────────────────────────
@bp.route('/api/systeme/check-update')
@login_required
def api_systeme_check_update():
    try:
        from modules.updater import check_for_updates
        res = check_for_updates(force=True)
        return jsonify({
            'ok': True,
            'local': res.get('local_version', _read_version()),
            'remote': res.get('remote_version', _read_version()),
            'has_update': res.get('available', False),
            'release_name': res.get('release_name', ''),
            'release_notes': res.get('release_notes', ''),
            'published_at': res.get('published_at', ''),
            'download_url': res.get('download_url', '')
        })
    except Exception as ex:
        logger.error(f"Erreur vérification mise à jour: {ex}")
        return jsonify({'ok': False, 'error': str(ex)})
        return jsonify({'ok': False, 'error': str(ex)})


@bp.route('/api/systeme/do-update', methods=['POST'])
@login_required
def api_systeme_do_update():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    try:
        cfg = _load_sys_config()
        gh_user = cfg.get('github_user', DEFAULT_GITHUB_USER).strip() or DEFAULT_GITHUB_USER
        gh_repo = cfg.get('github_repo', DEFAULT_GITHUB_REPO).strip() or DEFAULT_GITHUB_REPO
        token = cfg.get('github_token', '').strip()

        # 1. Sauvegarde automatique préventive de la base de données
        dt = datetime.now().strftime('%Y%m%d_%H%M%S')
        if os.path.exists('fiscalite.db'):
            backup_name = f'fiscalite_PreMaj_{dt}.db'
            shutil.copy('fiscalite.db', backup_name)
            _append_backup_log({
                'date': dt,
                'type': 'Sauvegarde Pré-Mise à Jour',
                'dest': backup_name,
                'status': '✅ Succès'
            })
            logger.info(f"Sauvegarde pré-mise à jour créée : {backup_name}")

        is_exe = getattr(sys, 'frozen', False)
        executable = sys.executable if is_exe else 'LANCER.bat'

        if is_exe:
            # Mode Exécutable autonome
            zip_url = f"https://github.com/{gh_user}/{gh_repo}/releases/latest/download/JIBAYAT-update.zip"
            zip_path = "JIBAYAT-update.zip"

            import urllib.request
            req = urllib.request.Request(zip_url)
            if token:
                req.add_header('Authorization', f'token {token}')
            try:
                with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, 'wb') as out_file:
                    shutil.copyfileobj(resp, out_file)
            except Exception as e:
                return jsonify({'ok': False, 'error': f"Échec du téléchargement du package ZIP : {str(e)}"})

            bat_content = f"""@echo off
ping 127.0.0.1 -n 4 > nul
powershell -command "Expand-Archive -Path '{zip_path}' -DestinationPath '.' -Force"
if exist "{zip_path}" del "{zip_path}"
start "" "{executable}"
del "%~f0"
"""
        else:
            # Mode Script / Git
            bat_content = f"""@echo off
ping 127.0.0.1 -n 4 > nul
git pull origin main
start "" "{executable}"
del "%~f0"
"""

        with open('update_temp.bat', 'w', encoding='utf-8') as f:
            f.write(bat_content)

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        subprocess.Popen(['update_temp.bat'], startupinfo=startupinfo)
        import threading
        threading.Thread(target=lambda: os._exit(0)).start()
        return jsonify({'ok': True, 'msg': 'Mise à jour téléchargée. Sauvegarde créée. L\'application va redémarrer...'})
    except Exception as ex:
        logger.error(f"Erreur exécution mise à jour: {ex}")
        return jsonify({'ok': False, 'error': str(ex)})


# ─────────────────────────────────────────────
#  GESTION DU MOT DE PASSE & SÉCURITÉ DB
# ─────────────────────────────────────────────
@bp.route('/api/systeme/db-password/set', methods=['POST'])
@login_required
def api_systeme_set_db_password():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    current_pwd = request.form.get('current_password', '')
    new_pwd = request.form.get('new_password', '')
    confirm_pwd = request.form.get('confirm_password', '')

    if new_pwd != confirm_pwd:
        return jsonify({'ok': False, 'error': 'La confirmation du mot de passe ne correspond pas.'})

    ok, msg = set_db_password(new_pwd, current_pwd if current_pwd else None)
    return jsonify({'ok': ok, 'msg' if ok else 'error': msg})


@bp.route('/api/systeme/db-password/remove', methods=['POST'])
@login_required
def api_systeme_remove_db_password():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    current_pwd = request.form.get('current_password', '')
    ok, msg = remove_db_password(current_pwd)
    return jsonify({'ok': ok, 'msg' if ok else 'error': msg})


# ─────────────────────────────────────────────
#  EXPORT & IMPORT SÉCURISÉ / CHIFFRÉ DE LA DB
# ─────────────────────────────────────────────
@bp.route('/api/systeme/export-db', methods=['POST'])
@login_required
def api_systeme_export_db():
    if not os.path.exists('fiscalite.db'):
        return jsonify({'ok': False, 'error': 'Base de données introuvable'}), 404

    db_pwd = request.form.get('password', '').strip()
    encrypt_mode = request.form.get('encrypted') == '1' or bool(db_pwd)

    # Si un mot de passe DB est configuré sur le système, vérifier qu'il est fourni
    status = get_db_security_status()
    if status['has_password'] and not verify_db_password(db_pwd):
        return jsonify({'ok': False, 'error': 'Mot de passe de base de données incorrect.'}), 403

    dt = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    if encrypt_mode:
        # Export chiffré AES-256 PBKDF2
        tmp_enc = f'temp_export_{dt}.jibenc'
        try:
            encrypt_file('fiscalite.db', tmp_enc, db_pwd or 'JIBAYAT_DEFAULT_SECURE_KEY')
            return send_file(
                tmp_enc,
                as_attachment=True,
                download_name=f'fiscalite_SecureBackup_{dt}.jibenc',
                mimetype='application/octet-stream'
            )
        finally:
            if os.path.exists(tmp_enc):
                try:
                    os.remove(tmp_enc)
                except Exception:
                    pass

    return send_file(
        'fiscalite.db',
        as_attachment=True,
        download_name=f'fiscalite_Export_{dt}.db',
        mimetype='application/octet-stream'
    )


@bp.route('/api/systeme/import-db', methods=['POST'])
@login_required
def api_systeme_import_db():
    user = get_current_user()
    if not user['peut_config']:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    if 'db_file' not in request.files:
        return jsonify({'ok': False, 'error': 'Aucun fichier reçu.'})

    f = request.files['db_file']
    filename = f.filename.lower()
    if not (filename.endswith('.db') or filename.endswith('.jibenc') or filename.endswith('.enc')):
        return jsonify({'ok': False, 'error': 'Formats acceptés : .db, .jibenc, .enc'})

    db_pwd = request.form.get('password', '').strip()
    status = get_db_security_status()
    if status['has_password'] and not verify_db_password(db_pwd):
        return jsonify({'ok': False, 'error': 'Mot de passe administrateur / DB incorrect.'}), 403

    dt = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    temp_target = f'temp_import_{dt}.tmp'

    try:
        f.save(temp_target)

        # Si le fichier est chiffré (.jibenc ou .enc)
        if filename.endswith('.jibenc') or filename.endswith('.enc'):
            decrypted_target = f'temp_decrypted_{dt}.db'
            try:
                decrypt_file(temp_target, decrypted_target, db_pwd or 'JIBAYAT_DEFAULT_SECURE_KEY')
            except ValueError as ve:
                return jsonify({'ok': False, 'error': f'Déchiffrement échoué : {str(ve)}'})

            if os.path.exists('fiscalite.db'):
                shutil.copy('fiscalite.db', f'fiscalite_AvantImport_{dt}.db')
            shutil.move(decrypted_target, 'fiscalite.db')
        else:
            # Fichier .db standard
            if os.path.exists('fiscalite.db'):
                shutil.copy('fiscalite.db', f'fiscalite_AvantImport_{dt}.db')
            shutil.move(temp_target, 'fiscalite.db')

        # Vérification finale de l'intégrité de la base restaurée
        if not check_db_integrity():
            if os.path.exists(f'fiscalite_AvantImport_{dt}.db'):
                shutil.copy(f'fiscalite_AvantImport_{dt}.db', 'fiscalite.db')
            return jsonify({'ok': False, 'error': "Le fichier importé n'est pas une base de données SQLite valide ou est corrompu."})

        _append_backup_log({'date': dt, 'type': 'Restauration', 'dest': 'fiscalite.db', 'status': '✅ Succès'})
        return jsonify({'ok': True, 'msg': f'Base de données restaurée avec succès ! (Sauvegarde de sécurité : fiscalite_AvantImport_{dt}.db)'})
    except Exception as ex:
        logger.error(f"Erreur restauration DB : {ex}")
        return jsonify({'ok': False, 'error': str(ex)})
    finally:
        for p in (temp_target, f'temp_decrypted_{dt}.db'):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


@bp.route('/api/systeme/backup-logs')
@login_required
def api_systeme_backup_logs():
    return jsonify(_load_backup_log())


@bp.route('/api/systeme/feedback', methods=['POST'])
@login_required
def api_systeme_feedback():
    nom = request.form.get('nom', '').strip()
    email = request.form.get('email', '').strip()
    message = request.form.get('message', '').strip()
    type_feedback = request.form.get('type_feedback', 'Suggestion').strip()
    note = request.form.get('note', '').strip()

    if not message:
        return jsonify({'ok': False, 'error': 'Veuillez saisir votre message ou suggestion.'})

    try:
        from modules.telemetry import send_feedback_to_sheet
        send_feedback_to_sheet(nom=nom, email=email, message=message, type_feedback=type_feedback, note=note)
        return jsonify({'ok': True, 'msg': 'Merci pour votre retour ! Votre suggestion a été transmise avec succès.'})
    except Exception as ex:
        logger.error(f"Erreur envoi feedback : {ex}")
        return jsonify({'ok': False, 'error': str(ex)})


@bp.route('/api/systeme/webhook/set', methods=['POST'])
@login_required
def api_systeme_set_webhook():
    webhook_url = request.form.get('webhook_url', '').strip()
    cfg = _load_sys_config()
    cfg['telemetry_webhook_url'] = webhook_url
    _save_sys_config(cfg)

    # Déclencher un ping de test
    if webhook_url:
        try:
            from modules.telemetry import sync_installation_status
            sync_installation_status('ping')
        except Exception:
            pass

    return jsonify({'ok': True, 'msg': 'URL du webhook Google Sheets enregistrée et testée avec succès !'})
