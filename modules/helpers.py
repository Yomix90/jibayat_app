"""modules/helpers.py — Fonctions partagées entre tous les blueprints"""
import hashlib
from flask import session, redirect, url_for, flash
from functools import wraps
from datetime import datetime, date
from database import get_db

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def get_current_user():
    if 'user_id' not in session: return None
    conn = get_db()
    try:
        user = conn.execute('''SELECT u.*, r.nom as role_nom,
            r.peut_ajouter, r.peut_modifier, r.peut_supprimer, r.peut_voir,
            r.peut_valider_paiement, r.peut_config, r.peut_creer_bulletin,
            com.nom as commune_nom
            FROM utilisateurs u JOIN roles r ON u.role_id=r.id
            LEFT JOIN communes com ON u.commune_id=com.id WHERE u.id=?''',
            (session['user_id'],)).fetchone()
    except Exception:
        session.pop('user_id', None)
        user = None
    return user

def get_user_module_permissions(user, module_code):
    """Retourne les permissions de l'utilisateur pour un module donné.
    Retourne un dict {peut_voir, peut_ajouter, peut_modifier, peut_supprimer}.
    Les super_admin/admin ont tous les droits par défaut.
    """
    if user is None:
        return {'peut_voir': 0, 'peut_ajouter': 0, 'peut_modifier': 0, 'peut_supprimer': 0}
    # Admin / super_admin : accès total
    if user['role_nom'] in ('super_admin', 'admin'):
        return {'peut_voir': 1, 'peut_ajouter': 1, 'peut_modifier': 1, 'peut_supprimer': 1}
    conn = get_db()
    row = conn.execute(
        '''SELECT rmp.* FROM role_module_permissions rmp
           WHERE rmp.role_id = ? AND rmp.module_code = ?''',
        (user['role_id'], module_code)
    ).fetchone()
    if row:
        return {
            'peut_voir':      row['peut_voir'],
            'peut_ajouter':   row['peut_ajouter'],
            'peut_modifier':  row['peut_modifier'],
            'peut_supprimer': row['peut_supprimer'],
        }
    # Pas de règle = pas d'accès
    return {'peut_voir': 0, 'peut_ajouter': 0, 'peut_modifier': 0, 'peut_supprimer': 0}

def get_all_user_modules(user):
    """Retourne tous les modules avec permissions pour un utilisateur."""
    if user is None:
        return {}
    conn = get_db()
    try:
        modules = conn.execute('SELECT * FROM app_modules WHERE actif=1 ORDER BY ordre').fetchall()
        result = {}
        for m in modules:
            result[m['code']] = get_user_module_permissions(user, m['code'])
    except Exception:
        result = {}
    return result

def module_required(module_code, perm='peut_voir'):
    """Décorateur qui vérifie l'accès à un module spécifique."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = get_current_user()
            perms = get_user_module_permissions(user, module_code)
            if not perms.get(perm, 0):
                flash(f'Accès refusé au module {module_code}. Contactez votre administrateur.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def get_param(module, code, default=0):
    conn = get_db()
    row = conn.execute('SELECT valeur FROM parametres_calcul WHERE module=? AND code=?', (module, code)).fetchone()
    try: return float(row['valeur']) if row else default
    except: return default

def calculer_penalites(montant, date_ech_str, date_pay_str=None, module='GLOBAL'):
    """Calcule pénalité (10%) + majoration (5% 1er mois + 0.5% par mois COMPLET supérieur).
    Un mois commencé mais non terminé n'est PAS comptabilisé dans les 0.5%.
    """
    if not date_pay_str: date_pay_str = date.today().isoformat()
    try:
        d_ech = datetime.strptime(date_ech_str[:10], '%Y-%m-%d').date()
        d_pay = datetime.strptime(date_pay_str[:10], '%Y-%m-%d').date()
    except: return 0, 0
    if d_pay <= d_ech: return 0, 0
    pen  = round(montant * get_param(module, 'PENALITE_RETARD', 10) / 100, 2)
    maj1 = get_param(module, 'MAJORATION_1ER_MOIS', 5) / 100
    majS = get_param(module, 'MAJORATION_MOIS_SUP', 0.5) / 100
    jours = (d_pay - d_ech).days
    # Mois COMPLETS de retard (floor) — un mois commencé ne compte pas
    mois_complets = jours // 30
    # 5% s'applique dès le 1er jour de retard (même mois partiel)
    # 0.5% uniquement pour les mois COMPLETS au-delà du 1er mois
    extra_mois = max(0, mois_complets - 1)
    maj = round(montant * maj1 + montant * majS * extra_mois, 2)
    return pen, maj

def gen_num(prefix, table, col='numero', db_conn=None):
    """Genere un numero unique base sur MAX (safe en boucle et concurrence)."""
    conn = db_conn or get_db()
    year = datetime.now().year
    # Validation des noms de table/colonne pour éviter les injections SQL
    _validate_sql_name(table)
    _validate_sql_name(col)
    row = conn.execute(
        f"SELECT MAX({col}) as m FROM {table} WHERE {col} LIKE ?",
        (f"{prefix}{year}%",)
    ).fetchone()
    if row and row['m']:
        try:
            n = int(str(row['m'])[-5:]) + 1
        except Exception:
            n = conn.execute(f'SELECT COUNT(*) as c FROM {table}').fetchone()['c'] + 1
    else:
        n = 1
    return f"{prefix}{year}{n:05d}"

# ── Validation noms SQL (protection injections) ──────────────
import re as _re
_VALID_SQL_NAME = _re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def _validate_sql_name(name):
    """Lève ValueError si le nom n'est pas un identifiant SQL valide."""
    if not _VALID_SQL_NAME.match(name):
        raise ValueError(f"Nom SQL invalide: {name!r}")

def annees_non_payees(module, ref_id, debut=None):
    conn = get_db()
    if debut is None:
        debut = int(get_param(module, 'ANNEES_DEBUT', 2020))
    payees = {r['annee'] for r in conn.execute(
        "SELECT DISTINCT annee FROM declarations WHERE module=? AND reference_id=? AND statut='paye'",
        (module, ref_id)).fetchall()}
    return [a for a in range(debut, datetime.now().year + 1) if a not in payees]

def get_tarifs_module(module):
    conn = get_db()
    rows = conn.execute('''SELECT t.* FROM tarifs t
        JOIN rubriques r ON t.rubrique_id=r.id
        WHERE r.module=? AND t.actif=1
        ORDER BY t.valeur''', (module,)).fetchall()
    return rows
