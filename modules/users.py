"""
modules/users.py — Blueprint de gestion des utilisateurs, rôles et permissions RBAC
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash
from database import get_db
from modules.helpers import login_required, get_current_user, permission_required

bp = Blueprint('users', __name__)

@bp.route('/utilisateurs')
@login_required
@permission_required('config')
def utilisateurs():
    user = get_current_user()
    conn = get_db()
    items = conn.execute('''SELECT u.*, r.nom as role_nom FROM utilisateurs u
        JOIN roles r ON u.role_id=r.id WHERE u.actif=1 ORDER BY u.id ASC''').fetchall()
    roles = conn.execute('SELECT * FROM roles').fetchall()
    commune = conn.execute('SELECT * FROM communes WHERE id=1').fetchone()
    modules = conn.execute('SELECT * FROM app_modules WHERE actif=1 ORDER BY ordre').fetchall()
    perms_raw = conn.execute('SELECT * FROM role_module_permissions').fetchall()
    perms = {}
    for p in perms_raw:
        perms.setdefault(p['role_id'], {})[p['module_code']] = dict(p)
    return render_template('admin/utilisateurs.html',
        user=user, items=items, roles=roles, commune=commune,
        modules=modules, perms=perms)

@bp.route('/utilisateurs/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def ajouter_utilisateur():
    user = get_current_user()
    if not user or not user['peut_config']:
        flash('Accès réservé aux administrateurs ❌', 'danger')
        return redirect(url_for('users.utilisateurs'))
    f = request.form
    nom = f['nom'].strip()
    prenom = f['prenom'].strip()
    email = f.get('email', '').strip()
    username = f.get('username', '').strip() or (email.split('@')[0] if email else nom.lower())
    pwd = generate_password_hash(f['password'])
    
    conn = get_db()
    existing = conn.execute('SELECT id FROM utilisateurs WHERE username=?', (username,)).fetchone()
    if existing:
        flash(f'Ce nom d\'utilisateur « {username} » est déjà utilisé ❌', 'danger')
    else:
        conn.execute('INSERT INTO utilisateurs (username,nom,prenom,email,mot_de_passe,role_id,commune_id) VALUES (?,?,?,?,?,?,1)',
            (username, nom, prenom, email, pwd, f['role_id']))
        conn.commit()
        flash(f'Utilisateur « {username} » ajouté avec succès ✅', 'success')
    return redirect(url_for('users.utilisateurs'))

@bp.route('/utilisateurs/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def modifier_utilisateur(id):
    f = request.form
    nom = f['nom'].strip()
    prenom = f['prenom'].strip()
    email = f.get('email', '').strip()
    username = f.get('username', '').strip() or (email.split('@')[0] if email else nom.lower())
    
    conn = get_db()
    existing = conn.execute('SELECT id FROM utilisateurs WHERE username=? AND id != ?', (username, id)).fetchone()
    if existing:
        flash(f'Le nom d\'utilisateur « {username} » est déjà pris par un autre compte ❌', 'danger')
        return redirect(url_for('users.utilisateurs'))

    if f.get('password'):
        pwd = generate_password_hash(f['password'])
        conn.execute('UPDATE utilisateurs SET username=?,nom=?,prenom=?,email=?,mot_de_passe=?,role_id=?,commune_id=1 WHERE id=?',
            (username, nom, prenom, email, pwd, f['role_id'], id))
    else:
        conn.execute('UPDATE utilisateurs SET username=?,nom=?,prenom=?,email=?,role_id=?,commune_id=1 WHERE id=?',
            (username, nom, prenom, email, f['role_id'], id))
    conn.commit()
    flash(f'Utilisateur « {username} » modifié ✅', 'success')
    return redirect(url_for('users.utilisateurs'))

@bp.route('/utilisateurs/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def supprimer_utilisateur(id):
    conn = get_db()
    if id == session.get('user_id'):
        flash('Impossible de supprimer votre propre compte ❌', 'danger')
        return redirect(url_for('users.utilisateurs'))
    conn.execute('UPDATE utilisateurs SET actif=0 WHERE id=?', (id,))
    conn.commit()
    flash('Utilisateur désactivé ✅', 'success')
    return redirect(url_for('users.utilisateurs'))

# ── Rôles ────────────────────────────────────────────────────
@bp.route('/roles/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def ajouter_role():
    f = request.form
    conn = get_db()
    conn.execute('''INSERT OR IGNORE INTO roles
        (nom,peut_voir,peut_ajouter,peut_modifier,peut_supprimer,peut_creer_bulletin,peut_valider_paiement,peut_config)
        VALUES (?,?,?,?,?,?,?,?)''',
        (f['nom'],
         1 if f.get('peut_voir') else 0,
         1 if f.get('peut_ajouter') else 0,
         1 if f.get('peut_modifier') else 0,
         1 if f.get('peut_supprimer') else 0,
         1 if f.get('peut_creer_bulletin') else 0,
         1 if f.get('peut_valider_paiement') else 0,
         1 if f.get('peut_config') else 0))
    conn.commit()
    flash('Rôle créé ✅', 'success')
    return redirect(url_for('users.utilisateurs'))

@bp.route('/roles/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def modifier_role(id):
    f = request.form
    conn = get_db()
    conn.execute('''UPDATE roles SET nom=?,peut_voir=?,peut_ajouter=?,peut_modifier=?,
        peut_supprimer=?,peut_creer_bulletin=?,peut_valider_paiement=?,peut_config=? WHERE id=?''',
        (f['nom'],
         1 if f.get('peut_voir') else 0,
         1 if f.get('peut_ajouter') else 0,
         1 if f.get('peut_modifier') else 0,
         1 if f.get('peut_supprimer') else 0,
         1 if f.get('peut_creer_bulletin') else 0,
         1 if f.get('peut_valider_paiement') else 0,
         1 if f.get('peut_config') else 0,
         id))
    conn.commit()
    flash('Rôle modifié ✅', 'success')
    return redirect(url_for('users.utilisateurs'))

@bp.route('/roles/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def supprimer_role(id):
    conn = get_db()
    nb = conn.execute('SELECT COUNT(*) FROM utilisateurs WHERE role_id=? AND actif=1', (id,)).fetchone()[0]
    if nb > 0:
        flash(f'Impossible : {nb} utilisateur(s) utilisent ce rôle ❌', 'danger')
    else:
        conn.execute('DELETE FROM roles WHERE id=?', (id,))
        conn.commit()
        flash('Rôle supprimé ✅', 'success')
    return redirect(url_for('users.utilisateurs'))

# ── Permissions RBAC ─────────────────────────────────────────
@bp.route('/roles/permissions')
@login_required
@permission_required('config')
def roles_permissions():
    return redirect(url_for('users.utilisateurs') + '#tab-droits')

@bp.route('/roles/<int:role_id>/permissions/sauvegarder', methods=['POST'])
@login_required
@permission_required('config')
def sauvegarder_permissions_role(role_id):
    user = get_current_user()
    if not user['peut_config']:
        flash('Accès refusé ❌', 'danger')
        return redirect(url_for('users.roles_permissions'))
    conn = get_db()
    modules = conn.execute('SELECT code FROM app_modules WHERE actif=1').fetchall()
    for m in modules:
        code = m['code']
        voir = 1 if request.form.get(f'{code}_voir') else 0
        ajouter = 1 if request.form.get(f'{code}_ajouter') else 0
        modifier = 1 if request.form.get(f'{code}_modifier') else 0
        supprimer = 1 if request.form.get(f'{code}_supprimer') else 0
        conn.execute('''INSERT INTO role_module_permissions
            (role_id, module_code, peut_voir, peut_ajouter, peut_modifier, peut_supprimer)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(role_id, module_code) DO UPDATE SET
                peut_voir=excluded.peut_voir,
                peut_ajouter=excluded.peut_ajouter,
                peut_modifier=excluded.peut_modifier,
                peut_supprimer=excluded.peut_supprimer''',
            (role_id, code, voir, ajouter, modifier, supprimer))
    conn.commit()
    flash('Permissions mises à jour ✅', 'success')
    return redirect(url_for('users.utilisateurs') + '#tab-droits')

@bp.route('/api/roles/<int:role_id>/permissions')
@login_required
def api_role_permissions(role_id):
    conn = get_db()
    rows = conn.execute('SELECT * FROM role_module_permissions WHERE role_id=?', (role_id,)).fetchall()
    res = {r['module_code']: dict(r) for r in rows}
    return jsonify(res)

@bp.route('/utilisateurs/<int:user_id>/permissions')
@login_required
def api_user_permissions(user_id):
    conn = get_db()
    rows = conn.execute('''
        SELECT rmp.* FROM role_module_permissions rmp
        JOIN utilisateurs u ON u.role_id = rmp.role_id
        WHERE u.id = ?''', (user_id,)).fetchall()
    res = {r['module_code']: dict(r) for r in rows}
    return jsonify(res)
