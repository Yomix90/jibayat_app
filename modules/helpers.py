"""modules/helpers.py — Fonctions partagées entre tous les blueprints"""
import os, json, hashlib
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
        if user:
            return dict(user)
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
    if not isinstance(user, dict):
        try:
            user = dict(user)
        except Exception:
            pass
    # Admin / super_admin : accès total
    role_name = str(user.get('role_nom', '')).lower()
    if role_name in ('super_admin', 'admin', 'administrateur') or user.get('role_id') == 1:
        return {'peut_voir': 1, 'peut_ajouter': 1, 'peut_modifier': 1, 'peut_supprimer': 1}

    mod_key = module_code.lower()

    # Si l'utilisateur a une restriction explicite sur modules_autorises
    modules_aut = user.get('modules_autorises', '') or ''
    if modules_aut:
        allowed_list = [m.strip().lower() for m in modules_aut.split(',') if m.strip()]
        if mod_key not in allowed_list and module_code.upper() not in [m.upper() for m in allowed_list]:
            return {'peut_voir': 0, 'peut_ajouter': 0, 'peut_modifier': 0, 'peut_supprimer': 0}

    # Vérification dans la table role_module_permissions si configurée
    conn = get_db()
    row = None
    try:
        row = conn.execute(
            '''SELECT rmp.* FROM role_module_permissions rmp
               WHERE rmp.role_id = ? AND LOWER(rmp.module_code) = ?''',
            (user.get('role_id'), mod_key)
        ).fetchone()
    except Exception:
        pass

    if row:
        return {
            'peut_voir':      int(row['peut_voir'] or 0),
            'peut_ajouter':   int(row['peut_ajouter'] or 0),
            'peut_modifier':  int(row['peut_modifier'] or 0),
            'peut_supprimer': int(row['peut_supprimer'] or 0),
        }

    return {
        'peut_voir':      int(user.get('peut_voir', 1)),
        'peut_ajouter':   int(user.get('peut_ajouter', 0)),
        'peut_modifier':  int(user.get('peut_modifier', 0)),
        'peut_supprimer': int(user.get('peut_supprimer', 0)),
    }

MODULE_ALIAS_MAP = {
    # TNB
    'tnb': 'TNB',
    'terrains': 'TNB',
    # Débits de boissons
    'tdb': 'DEBITS_BOISSONS',
    'debits_boissons': 'DEBITS_BOISSONS',
    'debits': 'DEBITS_BOISSONS',
    # Stationnement
    'sta': 'STATIONNEMENT',
    'stationnement': 'STATIONNEMENT',
    'tpv': 'STATIONNEMENT',
    'vehicules': 'STATIONNEMENT',
    # Fourrière
    'fou': 'FOURRIERE',
    'fourriere': 'FOURRIERE',
    'dossiers_fourriere': 'FOURRIERE',
    # Domaine public
    'odp': 'OCCUPATION_DOMAINE',
    'occupation_domaine': 'OCCUPATION_DOMAINE',
    'occupations': 'OCCUPATION_DOMAINE',
    'occupation': 'OCCUPATION_DOMAINE',
    # Location
    'loc': 'LOCATION_LOCAUX',
    'location_locaux': 'LOCATION_LOCAUX',
    'locations': 'LOCATION_LOCAUX',
    'location': 'LOCATION_LOCAUX',
    # Souks
    'sou': 'AFFERMAGE_SOUKS',
    'affermage_souks': 'AFFERMAGE_SOUKS',
    'souks': 'AFFERMAGE_SOUKS',
    'affermages': 'AFFERMAGE_SOUKS',
    'affermage': 'AFFERMAGE_SOUKS',
}

SYSTEM_FISCAL_MODULES = {
    'TNB', 'DEBITS_BOISSONS', 'STATIONNEMENT', 'FOURRIERE',
    'OCCUPATION_DOMAINE', 'LOCATION_LOCAUX', 'AFFERMAGE_SOUKS'
}

def is_system_module_active(module_code):
    """
    Vérifie si un module fiscal est activé dans la configuration globale du système (config.json).
    Les modules de base (contribuables, paiements, avis, regie, config, etc.) restent toujours actifs au niveau système.
    """
    if not module_code:
        return True
    mod_str = str(module_code).strip().lower()
    canonical = MODULE_ALIAS_MAP.get(mod_str, mod_str.upper())
    
    # Si ce n'est pas un des modules fiscaux configurables, c'est un module système actif
    if canonical not in SYSTEM_FISCAL_MODULES:
        return True
        
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                active_list = cfg.get('modules')
                if active_list is not None:
                    active_upper = [str(x).upper() for x in active_list]
                    active_lower = [str(x).lower() for x in active_list]
                    return (canonical in active_upper or mod_str in active_lower or mod_str.upper() in active_upper)
    except Exception:
        pass
    return True

def get_all_user_modules(user):
    """Retourne tous les modules avec permissions pour un utilisateur."""
    if user is None:
        return {}
    conn = get_db()
    try:
        modules = conn.execute('SELECT * FROM app_modules WHERE actif=1 ORDER BY ordre').fetchall()
        result = {}
        for m in modules:
            if is_system_module_active(m['code']):
                result[m['code']] = get_user_module_permissions(user, m['code'])
    except Exception:
        result = {}
    return result

def check_user_permission(user, action, module_code=None):
    """
    Vérifie si l'utilisateur possède l'autorisation pour l'action donnée :
    - action in ('voir', 'ajouter', 'modifier', 'supprimer', 'creer_bulletin', 'valider_paiement', 'config')
    - module_code (optionnel, ex: 'sou', 'tdb', 'odp', 'sta', 'fou', 'tnb', 'loc', 'contribuables')
    """
    if not user:
        return False
    if not isinstance(user, dict):
        try:
            user = dict(user)
        except Exception:
            pass

    # 1. Si un module_code est spécifié, vérifier d'abord s'il est activé au niveau système
    if module_code and not is_system_module_active(module_code):
        return False

    # 2. super_admin et admin ont un accès complet aux modules activés
    role_name = str(user.get('role_nom', '')).lower()
    if role_name in ('super_admin', 'admin', 'administrateur') or user.get('role_id') == 1:
        return True
    
    # Permissions spéciales / métiers
    if action == 'config':
        return bool(user.get('peut_config', 0))
    if action == 'valider_paiement':
        return bool(user.get('peut_valider_paiement', 0))
    if action == 'creer_bulletin':
        return bool(user.get('peut_creer_bulletin', 0))

    # Permissions génériques (voir, ajouter, modifier, supprimer)
    global_perm = bool(user.get(f'peut_{action}', 0))
    
    # Si un module_code est spécifié, on vérifie aussi la matrice RBAC par module
    if module_code:
        mod_perms = get_user_module_permissions(user, module_code)
        mod_perm = bool(mod_perms.get(f'peut_{action}', 0))
        return global_perm and mod_perm

    return global_perm

def permission_required(action, module_code=None):
    """Décorateur qui vérifie les habilitations de l'utilisateur."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = get_current_user()
            if not check_user_permission(user, action, module_code):
                flash('Accès non autorisé : votre profil ne dispose pas des droits requis pour cette opération 🚫', 'danger')
                from flask import request
                return redirect(request.referrer or url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator

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

def majore_centimes(val: float) -> float:
    """Majore systématiquement au centime supérieur (ex: 945.721 -> 945.73)."""
    if not val or val <= 0:
        return 0.0
    import math
    v = round(float(val), 6)
    return math.ceil(round(v * 100, 4)) / 100


def calculer_penalites(montant, date_ech_str, date_pay_str=None, module='GLOBAL'):
    """Calcule pénalité (10%) + majoration (5% 1er mois + 0.5% par mois de retard supplémentaire).
    Conforme à la loi 47-06 relative à la fiscalité des collectivités territoriales.
    Toute fraction de mois entamée compte pour un mois entier.
    Les montants après la virgule sont automatiquement majorés au centime supérieur.
    """
    if not date_pay_str:
        date_pay_str = date.today().isoformat()
    try:
        d_ech = datetime.strptime(date_ech_str[:10], '%Y-%m-%d').date()
        d_pay = datetime.strptime(date_pay_str[:10], '%Y-%m-%d').date()
    except Exception:
        return 0.0, 0.0

    if d_pay <= d_ech:
        return 0.0, 0.0

    pen_pct = get_param(module, 'PENALITE_RETARD', 10) / 100
    maj1 = get_param(module, 'MAJORATION_1ER_MOIS', 5) / 100
    majS = get_param(module, 'MAJORATION_MOIS_SUP', 0.5) / 100

    # Pénalité de retard majorée au centime supérieur
    pen = majore_centimes(montant * pen_pct)

    # Calcul exact des mois de retard selon la règle fiscale (calendaire) :
    diff_mois = (d_pay.year - d_ech.year) * 12 + (d_pay.month - d_ech.month)
    if d_pay.day > d_ech.day and diff_mois > 0 and d_ech.day < 28:
        diff_mois += 1
    total_mois = max(1, diff_mois)

    # 5% pour le 1er mois, et 0.5% par mois supplémentaire
    extra_mois = max(0, total_mois - 1)
    maj = majore_centimes(montant * maj1 + montant * majS * extra_mois)

    return pen, maj

def get_next_seq_num(table, col='numero', db_conn=None):
    """Retourne le prochain numéro séquentiel sous forme de chaîne ('1', '2', '3', ...)"""
    conn = db_conn or get_db()
    _validate_sql_name(table)
    _validate_sql_name(col)
    try:
        row = conn.execute(f"SELECT MAX(CAST({col} AS INTEGER)) as m FROM {table} WHERE {col} GLOB '[0-9]*'").fetchone()
        if row and row['m'] is not None and row['m'] > 0:
            return str(row['m'] + 1)
    except Exception:
        pass
    try:
        cnt = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()['c']
        return str(cnt + 1 if cnt > 0 else 1)
    except Exception:
        return "1"

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
