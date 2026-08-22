"""
modules/auth.py — Blueprint d'authentification (login, logout)
"""
import hashlib, logging
from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db
from modules.security import check_login_rate_limit, record_failed_login, reset_login_attempts

logger = logging.getLogger('jibayat.auth')
bp = Blueprint('auth', __name__)

def _read_version():
    import os
    try:
        if os.path.exists('version.txt'):
            with open('version.txt', 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        pass
    return "1.5.2"

@bp.route('/login', methods=['GET', 'POST'])
def login():
    conn = get_db()
    commune = conn.execute('SELECT * FROM communes WHERE id=1').fetchone()
    commune_nom = (commune['nom'] if commune and commune['nom'] else 'COMMUNE').upper()
    commune_nom_ar = commune['nom_ar'] if commune and commune['nom_ar'] else ''
    commune_logo = commune['logo'] if commune and commune['logo'] else 'img/logo.png'
    app_version = _read_version()
    ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr or '127.0.0.1').split(',')[0].strip()
    
    if request.method == 'POST':
        # Vérification du rate limiting anti brute-force
        allowed, wait_sec = check_login_rate_limit(ip_addr)
        if not allowed:
            logger.warning(f"Tentatives de connexion excessives bloquées pour l'IP {ip_addr}")
            return render_template(
                'login.html',
                error=f"Trop de tentatives infructueuses. Veuillez patienter {wait_sec} secondes.",
                commune_nom=commune_nom,
                commune_nom_ar=commune_nom_ar,
                commune_logo=commune_logo,
                app_version=app_version
            ), 429

        username_input = (request.form.get('username') or request.form.get('email') or '').strip()
        pwd_submitted = request.form.get('password', '')
        user = conn.execute(
            'SELECT * FROM utilisateurs WHERE (username=? OR email=?) AND actif=1',
            (username_input, username_input)
        ).fetchone()
        
        if user:
            # 1. Vérification werkzeug.security
            authenticated = check_password_hash(user['mot_de_passe'], pwd_submitted)
            
            # 2. Fallback pour les anciens mots de passe SHA-256 (Migration transparente)
            if not authenticated:
                legacy_hash = hashlib.sha256(pwd_submitted.encode()).hexdigest()
                if legacy_hash == user['mot_de_passe']:
                    authenticated = True
                    new_hash = generate_password_hash(pwd_submitted)
                    conn.execute('UPDATE utilisateurs SET mot_de_passe=? WHERE id=?', (new_hash, user['id']))
                    conn.commit()
                    logger.info(f"Mot de passe de l'utilisateur ID {user['id']} migré vers werkzeug.security avec succès.")
            
            if authenticated:
                reset_login_attempts(ip_addr)
                session.clear()
                session['user_id'] = user['id']
                session.permanent = True
                return redirect(url_for('index'))
            
        record_failed_login(ip_addr)
        return render_template('login.html', error='Nom d\'utilisateur ou mot de passe incorrect', 
                               commune_nom=commune_nom, commune_nom_ar=commune_nom_ar, 
                               commune_logo=commune_logo, app_version=app_version)
        
    return render_template('login.html', commune_nom=commune_nom, commune_nom_ar=commune_nom_ar, 
                           commune_logo=commune_logo, app_version=app_version)

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
