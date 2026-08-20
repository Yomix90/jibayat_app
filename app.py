"""
app.py — Orchestrateur principal Flask léger & modulaire
Toutes les routes métier sont organisées dans modules/
"""
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, send_file, flash)
import sys, io, json, os, shutil, threading, logging, urllib.request as _urllib_req
from datetime import datetime, date, timedelta
import secrets as _secrets

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler('jibayat.log'), logging.StreamHandler()]
)
logger = logging.getLogger('jibayat')

# ── DB & helpers ────────────────────────────────────────────
from database import get_db, close_db, init_db
from modules.helpers import (login_required, get_current_user,
                              get_param, calculer_penalites, gen_num, annees_non_payees,
                              get_user_module_permissions, get_all_user_modules)

# ── Blueprints ───────────────────────────────────────────────
from modules.auth          import bp as auth_bp
from modules.users         import bp as users_bp
from modules.bulletins     import bp as bulletins_bp
from modules.avis          import bp as avis_bp
from modules.system        import bp as system_bp

from modules.config        import bp as config_bp
from modules.contribuables import bp as ctb_bp
from modules.tnb           import bp as tnb_bp
from modules.tdb           import bp as tdb_bp
from modules.stationnement import bp as sta_bp
from modules.fourriere     import bp as fou_bp
from modules.occupation    import bp as odp_bp
from modules.location      import bp as loc_bp
from modules.souks         import bp as sou_bp
from modules.regie         import bp as regie_bp
from modules.emission      import bp as emission_bp
from modules.registre     import bp as registre_bp
from modules.licensing    import bp as licensing_bp, get_license_status
from modules.updater     import bp as updater_bp, start_background_checker as _start_updater

# ── Application ──────────────────────────────────────────────
from modules.security import SECURITY_HEADERS, check_runtime_integrity

check_runtime_integrity()

if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    candidates = [
        getattr(sys, '_MEIPASS', ''),
        os.path.join(exe_dir, '_internal'),
        exe_dir,
    ]
    template_dir = None
    static_dir = None
    for cand in candidates:
        if cand and os.path.exists(os.path.join(cand, 'templates')):
            template_dir = os.path.join(cand, 'templates')
            static_dir = os.path.join(cand, 'static')
            break
    if not template_dir:
        template_dir = os.path.join(exe_dir, '_internal', 'templates')
        static_dir = os.path.join(exe_dir, '_internal', 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
else:
    app = Flask(__name__)

# Fermeture automatique des connexions BDD en fin de requête
app.teardown_appcontext(close_db)

# Initialisation automatique du schéma BDD au démarrage
try:
    with app.app_context():
        init_db()
except Exception as _e:
    logger.error(f"Erreur initialisation schéma BDD: {_e}")

# ── Clé secrète & Configuration des Cookies de Session ───────
try:
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as _f:
            _sys_cfg = json.load(_f)
    else:
        _sys_cfg = {}
except Exception:
    _sys_cfg = {}

_secret_key = os.environ.get('JIBAYAT_SECRET_KEY') or _sys_cfg.get('secret_key')
if not _secret_key:
    _secret_key = _secrets.token_hex(32)
    _sys_cfg['secret_key'] = _secret_key
    try:
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(_sys_cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    logger.info("Clé secrète générée et persistée avec succès.")

app.secret_key = _secret_key
app.permanent_session_lifetime = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Activé uniquement si HTTPS explicite (sinon bloque les connexions locales http://localhost:5050)
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'

# ── En-têtes HTTP de Sécurité ────────────────────────────────
@app.after_request
def _apply_security_headers(response):
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response

# ── Protection des Fichiers Sensibles, CSRF & Licences ───────
FORBIDDEN_EXTENSIONS = ('.db', '.sqlite', '.sqlite3', '.log', '.env', '.json', '.sql', '.py', '.git', '.bat', '.spec')
EXEMPT_LICENSE_PREFIXES = ('/activation', '/api/systeme/activate', '/api/systeme/license-status', '/login', '/logout', '/setup', '/static')

@app.before_request
def _security_and_csrf_check():
    clean_path = request.path.lower()

    # 1. Bloquer l'accès direct aux fichiers sensibles et path traversal
    if any(clean_path.endswith(ext) for ext in FORBIDDEN_EXTENSIONS) or '..' in clean_path:
        if not clean_path.startswith('/api/'):
            logger.warning(f"Tentative d'accès non autorisé à un fichier sensible : {request.path} depuis {request.remote_addr}")
            return jsonify({'ok': False, 'error': 'Accès interdit'}), 403

    # 2. Redirection vers /setup si l'application n'est pas encore configurée (0 utilisateur)
    if not clean_path.startswith('/static') and not clean_path.startswith('/setup'):
        try:
            conn = get_db()
            u_count = conn.execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0]
            if u_count == 0:
                return redirect(url_for('setup'))
        except Exception:
            pass

    # 3. Vérification de la licence & période d'essai (Redirection si expiré sans clé)
    if not any(clean_path.startswith(p) for p in EXEMPT_LICENSE_PREFIXES):
        lic_stat = get_license_status()
        if lic_stat.get('requires_activation'):
            if request.is_json or request.headers.get('Accept') == 'application/json':
                return jsonify({'ok': False, 'error': 'Période d\'essai expirée. Clé d\'activation requise.', 'requires_activation': True}), 402
            return redirect(url_for('licensing.activation_page'))

    # 3. Vérification CSRF sur les méthodes modificatrices
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    # Routes anonymes exclues du CSRF
    if request.path in ('/login', '/setup', '/activation', '/api/systeme/activate'):
        return
    token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or token != session.get('_csrf_token'):
        logger.warning(f"CSRF échec: {request.method} {request.path} depuis {request.remote_addr}")
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({'ok': False, 'error': 'Token CSRF invalide'}), 403
        flash('Session expirée ou requête invalide. Veuillez réessayer.', 'danger')
        return redirect(url_for('index'))

@app.context_processor
def _inject_global_context():
    if '_csrf_token' not in session:
        session['_csrf_token'] = _secrets.token_hex(32)
    return {
        'csrf_token': session['_csrf_token'],
        'license_status': get_license_status()
    }

# ── Enregistrement des Blueprints ─────────────────────────────
for bp_item in (auth_bp, users_bp, bulletins_bp, avis_bp, system_bp,
               config_bp, ctb_bp, tnb_bp, tdb_bp, sta_bp, fou_bp, odp_bp, loc_bp, sou_bp, regie_bp):
    app.register_blueprint(bp_item)

app.register_blueprint(emission_bp, url_prefix='/emission')
app.register_blueprint(registre_bp)
app.register_blueprint(licensing_bp)
app.register_blueprint(updater_bp)

# Aliases d'endpoints pour rétro-compatibilité des templates
aliases = [
    ('/login', 'login', 'auth.login', ['GET', 'POST']),
    ('/logout', 'logout', 'auth.logout', ['GET']),
    ('/utilisateurs', 'utilisateurs', 'users.utilisateurs', ['GET']),
    ('/utilisateurs/ajouter', 'ajouter_utilisateur', 'users.ajouter_utilisateur', ['POST']),
    ('/utilisateurs/<int:id>/modifier', 'modifier_utilisateur', 'users.modifier_utilisateur', ['POST']),
    ('/utilisateurs/<int:id>/supprimer', 'supprimer_utilisateur', 'users.supprimer_utilisateur', ['POST']),
    ('/utilisateurs/<int:user_id>/permissions', 'user_permissions', 'users.api_user_permissions', ['GET']),
    ('/roles/ajouter', 'ajouter_role', 'users.ajouter_role', ['POST']),
    ('/roles/<int:id>/modifier', 'modifier_role', 'users.modifier_role', ['POST']),
    ('/roles/<int:id>/supprimer', 'supprimer_role', 'users.supprimer_role', ['POST']),
    ('/roles/permissions', 'roles_permissions', 'users.roles_permissions', ['GET']),
    ('/roles/<int:role_id>/permissions/sauvegarder', 'sauvegarder_permissions_role', 'users.sauvegarder_permissions_role', ['POST']),
    ('/paiements', 'paiements', 'bulletins.paiements', ['GET']),
    ('/avis', 'avis', 'avis.avis', ['GET']),
    ('/parametres-systeme', 'parametres_systeme', 'system.parametres_systeme', ['GET']),
    ('/commune/modifier', 'modifier_commune', 'system.modifier_commune', ['POST']),
    ('/communes', 'communes', 'system.communes', ['GET']),
    ('/setup', 'setup', 'system.setup', ['GET', 'POST']),
]

for rule, ep, view_ep, methods in aliases:
    if view_ep in app.view_functions:
        app.add_url_rule(rule, endpoint=ep, view_func=app.view_functions[view_ep], methods=methods)

def handle_url_build_error(error, endpoint, values):
    """Fallback automatique pour les templates appelant url_for('nom_sans_blueprint')"""
    for bp in app.blueprints:
        candidates = [
            f"{bp}.{endpoint}",
            f"{bp}.api_{endpoint}",
            f"{bp}.{endpoint.replace('api_', '')}"
        ]
        for candidate in candidates:
            if candidate in app.view_functions:
                return url_for(candidate, **values)
    raise error

app.url_build_error_handlers.append(handle_url_build_error)

GITHUB_USER   = 'Yomix90'
GITHUB_REPO   = 'jibayat-releases'

def _read_version():
    try:
        if os.path.exists('version.txt'):
            with open('version.txt', 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception as e:
        logger.debug(f"Lecture version: {e}")
    return "1.0.0"

UPDATE_AVAILABLE = False

from werkzeug.exceptions import HTTPException

@app.route('/favicon.ico')
def favicon():
    logo_path = os.path.join(app.static_folder, 'img/logo.png')
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype='image/png')
    return '', 204

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    logger.error(f"Erreur serveur non gérée sur {request.method} {request.path}: {e}", exc_info=True)
    if request.is_json or request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'Erreur interne du serveur'}), 500
    return render_template('500.html'), 500

def _check_update_startup():
    global UPDATE_AVAILABLE
    try:
        import requests as _req, json
        cfg = {}
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        token = cfg.get('github_token', '').strip()
        url = f'https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/version.txt'
        headers = {'Accept': 'application/vnd.github.v3.raw'}
        if token:
            headers['Authorization'] = f'token {token}'
        r = _req.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            remote = r.text.strip()
            local = _read_version()
            def vt(v):
                try: return tuple(int(x) for x in v.split('.'))
                except: return (0,)
            if vt(remote) > vt(local):
                UPDATE_AVAILABLE = True
    except Exception as e:
        logger.debug(f"Vérification mise à jour: {e}")

    # Synchronisation télémétrique asynchrone avec Google Sheets
    try:
        from modules.telemetry import sync_installation_status
        sync_installation_status('ping')
    except Exception as e:
        logger.debug(f"Sync télémétrie startup: {e}")

threading.Thread(target=_check_update_startup, daemon=True).start()

# Démarrage du vérificateur de mises à jour périodique OTA & Nettoyage
try:
    from modules.updater import cleanup_temp_files
    cleanup_temp_files()
    _start_updater()
except Exception as e:
    logger.debug(f"Démarrage updater / cleanup: {e}")

@app.context_processor
def inject_global_vars():
    user = get_current_user()
    user_modules = get_all_user_modules(user) if user else {}
    # État de l'updater OTA
    try:
        from modules.updater import _state as _updater_state
        updater_info = _updater_state.to_dict()
    except Exception:
        updater_info = {'available': False}
    return {
        'sys_version': _read_version(),
        'sys_has_update': UPDATE_AVAILABLE or updater_info.get('available', False),
        'user_modules': user_modules,
        'updater': updater_info,
    }

@app.context_processor
def inject_global_counts():
    try:
        if 'user_id' not in session:
            return {'nb_attente': 0}
        conn = get_db()
        nb = conn.execute("SELECT COUNT(*) as c FROM bulletins WHERE statut='en_attente'").fetchone()['c']
        return {'nb_attente': nb}
    except Exception:
        return {'nb_attente': 0}

# ════════════════════════════════════════════════════════════
#  DASHBOARD PRINCIPAL
# ════════════════════════════════════════════════════════════
@app.route('/')
@login_required
def index():
    user = get_current_user()
    conn = get_db()
    annee_cur = datetime.now().year

    def q(sql, *args):
        row = conn.execute(sql, args).fetchone()
        return row[0] if row else 0

    stats = {
        'contribuables':     q('SELECT COUNT(*) FROM contribuables WHERE actif=1'),
        'bulletins_attente': q("SELECT COUNT(*) FROM bulletins WHERE statut='en_attente'"),
        'avis_emis':         q("SELECT COUNT(*) FROM avis_non_paiement WHERE statut='emis'"),
        'total_emis':        q('SELECT COALESCE(SUM(montant_total),0) FROM declarations'),
        'total_paye':        q("SELECT COALESCE(SUM(montant),0) FROM bulletins WHERE statut='paye'"),
    }

    modules_stats = {
        'TNB': {
            'label': 'TNB — Terrains', 'icon': '🏗️', 'color': '#e8a020',
            'count': q('SELECT COUNT(*) FROM tnb_terrains'),
            'emis':  q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module='TNB' AND annee=?", annee_cur),
            'paye':  q("SELECT COALESCE(SUM(b.montant),0) FROM bulletins b JOIN declarations d ON b.declaration_id=d.id WHERE d.module='TNB' AND b.statut='paye' AND d.annee=?", annee_cur),
            'url': 'tnb.tnb_liste',
        },
        'TDB': {
            'label': 'Débits Boissons', 'icon': '🍺', 'color': '#8e44ad',
            'count': q('SELECT COUNT(*) FROM tdb_etablissements'),
            'emis':  q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module='DEBITS_BOISSONS' AND annee=?", annee_cur),
            'paye':  q("SELECT COALESCE(SUM(b.montant),0) FROM bulletins b JOIN declarations d ON b.declaration_id=d.id WHERE d.module='DEBITS_BOISSONS' AND b.statut='paye' AND d.annee=?", annee_cur),
            'url': 'tdb.tdb_liste',
        },
        'STA': {
            'label': 'Stationnement', 'icon': '🚗', 'color': '#2980b9',
            'count': q('SELECT COUNT(*) FROM sta_vehicules'),
            'emis':  q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module='STATIONNEMENT' AND annee=?", annee_cur),
            'paye':  q("SELECT COALESCE(SUM(b.montant),0) FROM bulletins b JOIN declarations d ON b.declaration_id=d.id WHERE d.module='STATIONNEMENT' AND b.statut='paye' AND d.annee=?", annee_cur),
            'url': 'sta.sta_liste',
        },
        'FOU': {
            'label': 'Fourrière', 'icon': '🔑', 'color': '#c0392b',
            'count': q('SELECT COUNT(*) FROM fou_dossiers'),
            'emis':  q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module='FOURRIERE' AND annee=?", annee_cur),
            'paye':  q("SELECT COALESCE(SUM(b.montant),0) FROM bulletins b JOIN declarations d ON b.declaration_id=d.id WHERE d.module='FOURRIERE' AND b.statut='paye' AND d.annee=?", annee_cur),
            'url': 'fou.fou_liste',
        },
        'ODP': {
            'label': 'Occupation D.P.', 'icon': '🏕️', 'color': '#27ae60',
            'count': q('SELECT COUNT(*) FROM odp_occupations'),
            'emis':  q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module='OCCUPATION_DOMAINE' AND annee=?", annee_cur),
            'paye':  q("SELECT COALESCE(SUM(b.montant),0) FROM bulletins b JOIN declarations d ON b.declaration_id=d.id WHERE d.module='OCCUPATION_DOMAINE' AND b.statut='paye' AND d.annee=?", annee_cur),
            'url': 'odp.odp_liste',
        },
        'LOC': {
            'label': 'Location Locaux', 'icon': '🏪', 'color': '#16a085',
            'count': q('SELECT COUNT(*) FROM loc_locaux'),
            'emis':  q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module='LOCATION_LOCAUX' AND annee=?", annee_cur),
            'paye':  q("SELECT COALESCE(SUM(b.montant),0) FROM bulletins b JOIN declarations d ON b.declaration_id=d.id WHERE d.module='LOCATION_LOCAUX' AND b.statut='paye' AND d.annee=?", annee_cur),
            'url': 'loc.loc_liste',
        },
        'SOU': {
            'label': 'Souks', 'icon': '🛒', 'color': '#d35400',
            'count': q('SELECT COUNT(*) FROM sou_contrats'),
            'emis':  q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module='AFFERMAGE_SOUKS' AND annee=?", annee_cur),
            'paye':  q("SELECT COALESCE(SUM(b.montant),0) FROM bulletins b JOIN declarations d ON b.declaration_id=d.id WHERE d.module='AFFERMAGE_SOUKS' AND b.statut='paye' AND d.annee=?", annee_cur),
            'url': 'sou.sou_liste',
        },
    }

    recent_bulletins = conn.execute('''
        SELECT b.*, d.module, d.annee, c.nom, c.prenom, c.raison_sociale
        FROM bulletins b
        JOIN declarations d ON b.declaration_id=d.id
        LEFT JOIN contribuables c ON b.contribuable_id=c.id
        ORDER BY b.date_creation DESC LIMIT 8''').fetchall()

    recent_decls = conn.execute('''
        SELECT d.*, c.nom, c.prenom, c.raison_sociale
        FROM declarations d
        LEFT JOIN contribuables c ON d.contribuable_id=c.id
        ORDER BY d.date_creation DESC LIMIT 8''').fetchall()

    commune = conn.execute('SELECT * FROM communes WHERE id=1').fetchone()

    # ── Données graphiques mensuels & répartition par module ──
    mois_labels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
    mois_emis = [0.0] * 12
    mois_paye = [0.0] * 12

    rows_emis = conn.execute('''
        SELECT strftime('%m', date_declaration) as m, SUM(montant_total)
        FROM declarations WHERE strftime('%Y', date_declaration) = ?
        GROUP BY m
    ''', (str(annee_cur),)).fetchall()
    for r in rows_emis:
        if r[0] and r[0].isdigit():
            idx = int(r[0]) - 1
            if 0 <= idx < 12: mois_emis[idx] = round(float(r[1] or 0), 2)

    rows_paye = conn.execute('''
        SELECT strftime('%m', date_paiement) as m, SUM(montant)
        FROM bulletins WHERE statut='paye' AND strftime('%Y', date_paiement) = ?
        GROUP BY m
    ''', (str(annee_cur),)).fetchall()
    for r in rows_paye:
        if r[0] and r[0].isdigit():
            idx = int(r[0]) - 1
            if 0 <= idx < 12: mois_paye[idx] = round(float(r[1] or 0), 2)

    chart_modules_labels = [m['label'] for m in modules_stats.values()]
    chart_modules_data   = [m['emis'] for m in modules_stats.values()]
    chart_modules_colors = [m['color'] for m in modules_stats.values()]

    return render_template('index.html',
        user=user, stats=stats, modules_stats=modules_stats,
        recent_bulletins=recent_bulletins, recent_decls=recent_decls,
        commune=commune, annee_cur=annee_cur,
        mois_labels=mois_labels, mois_emis=mois_emis, mois_paye=mois_paye,
        chart_modules_labels=chart_modules_labels, chart_modules_data=chart_modules_data,
        chart_modules_colors=chart_modules_colors)


@app.route('/module/<module>/dashboard')
@login_required
def mod_dashboard(module):
    mod_upper = module.upper()
    conn = get_db()
    user = get_current_user()
    annee_cur = datetime.now().year

    mod_config = {
        'TNB': {
            'module_key': 'TNB', 'code': 'TNB', 'label': 'Terrains Non Bâtis',
            'icon': '🏗️', 'color': '#e8a020', 'table': 'tnb_terrains',
            'liste_url': url_for('tnb.tnb_liste')
        },
        'TDB': {
            'module_key': 'DEBITS_BOISSONS', 'code': 'DEBITS_BOISSONS', 'label': 'Débits de Boissons',
            'icon': '🍺', 'color': '#8e44ad', 'table': 'tdb_etablissements',
            'liste_url': url_for('tdb.tdb_liste')
        },
        'STA': {
            'module_key': 'STATIONNEMENT', 'code': 'STATIONNEMENT', 'label': 'Stationnement (TPV)',
            'icon': '🚗', 'color': '#2980b9', 'table': 'sta_vehicules',
            'liste_url': url_for('sta.sta_liste')
        },
        'FOU': {
            'module_key': 'FOURRIERE', 'code': 'FOURRIERE', 'label': 'Fourrière Communale',
            'icon': '🔑', 'color': '#c0392b', 'table': 'fou_dossiers',
            'liste_url': url_for('fou.fou_liste')
        },
        'ODP': {
            'module_key': 'OCCUPATION_DOMAINE', 'code': 'OCCUPATION_DOMAINE', 'label': 'Occupation Domaine Public',
            'icon': '🏕️', 'color': '#27ae60', 'table': 'odp_occupations',
            'liste_url': url_for('odp.odp_liste')
        },
        'LOC': {
            'module_key': 'LOCATION_LOCAUX', 'code': 'LOCATION_LOCAUX', 'label': 'Location Locaux Commerciaux',
            'icon': '🏪', 'color': '#16a085', 'table': 'loc_locaux',
            'liste_url': url_for('loc.loc_liste')
        },
        'SOU': {
            'module_key': 'AFFERMAGE_SOUKS', 'code': 'AFFERMAGE_SOUKS', 'label': 'Affermage des Souks',
            'icon': '🛒', 'color': '#d35400', 'table': 'sou_contrats',
            'liste_url': url_for('sou.sou_liste')
        },
    }

    cfg = mod_config.get(mod_upper)
    if not cfg:
        flash(f'Module {module} inconnu', 'danger')
        return redirect(url_for('index'))

    code_db = cfg['code']
    table = cfg['table']

    def q(sql, *args):
        r = conn.execute(sql, args).fetchone()
        return r[0] if r and r[0] is not None else 0

    total_dossiers = q(f"SELECT COUNT(*) FROM {table}")
    nb_decl_annee = q("SELECT COUNT(*) FROM declarations WHERE module=? AND annee=?", code_db, annee_cur)
    nb_emis = q("SELECT COUNT(*) FROM declarations WHERE module=? AND annee=? AND montant_total > 0", code_db, annee_cur)
    nb_sous_seuil = q("SELECT COUNT(*) FROM declarations WHERE module=? AND annee=? AND montant_total = 0", code_db, annee_cur)

    total_emis = float(q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module=?", code_db))
    total_paye = float(q("""SELECT COALESCE(SUM(b.montant),0) FROM bulletins b
                             JOIN declarations d ON b.declaration_id=d.id
                             WHERE d.module=? AND b.statut='paye'""", code_db))
    nb_paye = q("""SELECT COUNT(b.id) FROM bulletins b
                   JOIN declarations d ON b.declaration_id=d.id
                   WHERE d.module=? AND b.statut='paye'""", code_db)

    total_impaye = float(q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module=? AND statut NOT IN ('paye','annule')", code_db))
    nb_impaye = q("SELECT COUNT(*) FROM declarations WHERE module=? AND statut NOT IN ('paye','annule')", code_db)
    nb_annule = q("SELECT COUNT(*) FROM declarations WHERE module=? AND statut='annule'", code_db)

    taux_recouvrement = round((total_paye / total_emis * 100) if total_emis > 0 else 0.0, 1)
    nb_avis = q("SELECT COUNT(a.id) FROM avis_non_paiement a JOIN declarations d ON a.declaration_id=d.id WHERE d.module=? AND a.statut='emis'", code_db)

    stats = {
        'total_dossiers': total_dossiers,
        'nb_decl_annee': nb_decl_annee,
        'nb_emis': nb_emis,
        'nb_sous_seuil': nb_sous_seuil,
        'total_emis': total_emis,
        'total_paye': total_paye,
        'nb_paye': nb_paye,
        'total_impaye': total_impaye,
        'nb_impaye': nb_impaye,
        'nb_annule': nb_annule,
        'taux_recouvrement': taux_recouvrement,
        'nb_avis': nb_avis,
    }

    # ── Courbe mensuelle ───────────────────────────────────────
    mois_labels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
    mois_emis = [0.0] * 12
    mois_paye = [0.0] * 12

    rows_e = conn.execute('''
        SELECT strftime('%m', date_declaration) as m, SUM(montant_total)
        FROM declarations WHERE module=? AND strftime('%Y', date_declaration)=?
        GROUP BY m
    ''', (code_db, str(annee_cur))).fetchall()
    for r in rows_e:
        if r[0] and r[0].isdigit():
            idx = int(r[0]) - 1
            if 0 <= idx < 12: mois_emis[idx] = round(float(r[1] or 0), 2)

    rows_p = conn.execute('''
        SELECT strftime('%m', b.date_paiement) as m, SUM(b.montant)
        FROM bulletins b JOIN declarations d ON b.declaration_id=d.id
        WHERE d.module=? AND b.statut='paye' AND strftime('%Y', b.date_paiement)=?
        GROUP BY m
    ''', (code_db, str(annee_cur))).fetchall()
    for r in rows_p:
        if r[0] and r[0].isdigit():
            idx = int(r[0]) - 1
            if 0 <= idx < 12: mois_paye[idx] = round(float(r[1] or 0), 2)

    # ── Historique par année ──────────────────────────────────
    stats_par_annee = []
    annees = range(annee_cur - 4, annee_cur + 1)
    for a in annees:
        e = float(q("SELECT COALESCE(SUM(montant_total),0) FROM declarations WHERE module=? AND annee=?", code_db, a))
        p = float(q("""SELECT COALESCE(SUM(b.montant),0) FROM bulletins b
                       JOIN declarations d ON b.declaration_id=d.id
                       WHERE d.module=? AND d.annee=? AND b.statut='paye'""", code_db, a))
        if e > 0 or p > 0:
            stats_par_annee.append({'annee': a, 'total_emis': e, 'total_paye': p})

    recent_decls = conn.execute("""
        SELECT d.*, c.nom, c.prenom, c.raison_sociale
        FROM declarations d
        LEFT JOIN contribuables c ON d.contribuable_id=c.id
        WHERE d.module=?
        ORDER BY d.date_creation DESC LIMIT 8
    """, (code_db,)).fetchall()

    recent_bulletins = conn.execute("""
        SELECT b.*, c.nom, c.prenom, c.raison_sociale
        FROM bulletins b
        JOIN declarations d ON b.declaration_id=d.id
        LEFT JOIN contribuables c ON d.contribuable_id=c.id
        WHERE d.module=?
        ORDER BY b.date_creation DESC LIMIT 8
    """, (code_db,)).fetchall()

    return render_template('module_dashboard.html',
        user=user, mod_info=cfg, cfg=cfg, stats=stats,
        mois_labels=mois_labels, mois_emis=mois_emis, mois_paye=mois_paye,
        stats_par_annee=stats_par_annee,
        recent_decls=recent_decls, recent_bulletins=recent_bulletins,
        annee_cur=annee_cur)


if __name__ == '__main__':
    init_db()
    import socket as _sock
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
    except Exception:
        ip = 'localhost'
    print(f"\n{'='*55}\n  JIBAYAT — Gestion Fiscale Communale\n  Local : http://localhost:5050\n  Réseau: http://{ip}:5050\n{'='*55}\n")
    app.run(host='0.0.0.0', port=5050, debug=False)
