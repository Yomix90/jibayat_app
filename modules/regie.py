"""modules/regie.py — Régie : Carnets de timbres & Tickets"""
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
from datetime import date, datetime
from database import get_db
from modules.helpers import login_required, get_current_user, permission_required

bp = Blueprint('regie', __name__, url_prefix='/regie')

# ─── Helpers ────────────────────────────────────────────────────────────────

def _gen_numero_bordereau(conn):
    n = conn.execute("SELECT COUNT(*)+1 as n FROM regie_bordereaux").fetchone()['n']
    return f"BRD{date.today().year}{n:05d}"

def _valeur_carnet(valeur):
    return round(valeur['valeur_unitaire'] * valeur['nb_unites_carnet'], 2)

# ─── Dashboard ───────────────────────────────────────────────────────────────

@bp.route('/')
@login_required
def index():
    user = get_current_user()
    conn = get_db()

    stock_par_type = conn.execute('''
        SELECT v.designation, v.valeur_unitaire, v.nb_unites_carnet,
               COUNT(c.id) as nb_stock
        FROM regie_valeurs v
        LEFT JOIN regie_carnets c ON c.valeur_id = v.id AND c.statut = 'en_stock'
        WHERE v.actif = 1
        GROUP BY v.id
    ''').fetchall()

    affectes = conn.execute('''
        SELECT c.*, v.designation, v.valeur_unitaire, v.nb_unites_carnet,
               s.nom as service_nom, e.nom as emp_nom, e.prenom as emp_prenom
        FROM regie_carnets c
        JOIN regie_valeurs v ON v.id = c.valeur_id
        LEFT JOIN regie_services s ON s.id = c.service_id
        LEFT JOIN regie_employes e ON e.id = c.employe_id
        WHERE c.statut = 'affecte'
        ORDER BY c.date_affectation DESC LIMIT 20
    ''').fetchall()

    stats = {
        'total_paquets': conn.execute("SELECT COUNT(*) FROM regie_paquets").fetchone()[0],
        'total_carnets': conn.execute("SELECT COUNT(*) FROM regie_carnets").fetchone()[0],
        'en_stock': conn.execute("SELECT COUNT(*) FROM regie_carnets WHERE statut='en_stock'").fetchone()[0],
        'affectes': conn.execute("SELECT COUNT(*) FROM regie_carnets WHERE statut='affecte'").fetchone()[0],
        'consommes': conn.execute("SELECT COUNT(*) FROM regie_carnets WHERE statut='consomme'").fetchone()[0],
        'total_verse': conn.execute("SELECT COALESCE(SUM(montant_verse),0) FROM regie_carnets WHERE statut='consomme'").fetchone()[0],
    }

    stats_services = conn.execute('''
        SELECT s.nom, 
               SUM(CASE WHEN c.statut='affecte' THEN 1 ELSE 0 END) as carnets_affectes,
               SUM(CASE WHEN c.statut='consomme' THEN 1 ELSE 0 END) as carnets_consommes,
               COALESCE(SUM(c.montant_verse),0) as total_verse
        FROM regie_services s
        LEFT JOIN regie_carnets c ON c.service_id = s.id
        WHERE s.actif = 1
        GROUP BY s.id
        ORDER BY total_verse DESC, s.nom
    ''').fetchall()

    stats_employes = conn.execute('''
        SELECT e.nom, e.prenom, s.nom as service_nom,
               SUM(CASE WHEN c.statut='affecte' THEN 1 ELSE 0 END) as carnets_affectes,
               SUM(CASE WHEN c.statut='consomme' THEN 1 ELSE 0 END) as carnets_consommes,
               COALESCE(SUM(c.montant_verse),0) as total_verse
        FROM regie_employes e
        LEFT JOIN regie_services s ON s.id = e.service_id
        LEFT JOIN regie_carnets c ON c.employe_id = e.id
        WHERE e.actif = 1
        GROUP BY e.id
        ORDER BY total_verse DESC LIMIT 10
    ''').fetchall()

    annee_cur = datetime.now().year
    mois_labels = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']
    mois_verse = []
    
    for m in range(1, 13):
        mois_verse.append(conn.execute(
            "SELECT COALESCE(SUM(montant_verse),0) FROM regie_carnets WHERE statut='consomme' AND strftime('%Y',date_versement_employe)=? AND strftime('%m',date_versement_employe)=?",
            (str(annee_cur), f'{m:02d}')
        ).fetchone()[0])

    conn.close()
    return render_template('regie/index.html',
        user=user, stock_par_type=stock_par_type,
        affectes=[dict(a) for a in affectes], stats=stats,
        stats_services=[dict(s) for s in stats_services],
        stats_employes=[dict(e) for e in stats_employes],
        annee_cur=annee_cur, mois_labels=mois_labels, mois_verse=mois_verse)


# ─── Paquets ─────────────────────────────────────────────────────────────────

@bp.route('/paquets')
@login_required
def paquets():
    user = get_current_user()
    conn = get_db()
    statut = request.args.get('statut', '')
    q = '''
        SELECT p.*, v.designation,
               COUNT(c.id) as nb_carnets,
               SUM(CASE WHEN c.statut='en_stock' THEN 1 ELSE 0 END) as nb_stock,
               SUM(CASE WHEN c.statut='affecte' THEN 1 ELSE 0 END) as nb_affecte,
               SUM(CASE WHEN c.statut='consomme' THEN 1 ELSE 0 END) as nb_consomme
        FROM regie_paquets p
        LEFT JOIN regie_valeurs v ON v.id = p.valeur_id
        LEFT JOIN regie_carnets c ON c.paquet_id = p.id
    '''
    params = []
    if statut:
        q += ' WHERE p.statut = ?'
        params.append(statut)
    q += ' GROUP BY p.id ORDER BY p.date_creation DESC'
    paquets = conn.execute(q, params).fetchall()
    valeurs = conn.execute("SELECT * FROM regie_valeurs WHERE actif=1").fetchall()
    conn.close()
    return render_template('regie/paquets.html',
        user=user, paquets=[dict(p) for p in paquets],
        valeurs=valeurs, statut_filtre=statut)


@bp.route('/paquets/ajouter', methods=['POST'])
@login_required
@permission_required('ajouter', 'regie')
def ajouter_paquet():
    user = get_current_user()
    f = request.form
    conn = get_db()
    # Calcul automatique du nombre de vignettes
    try:
        qte = int(f['num_dernier']) - int(f['num_premier']) + 1
    except (ValueError, TypeError):
        qte = 0
    conn.execute('''INSERT INTO regie_paquets
        (valeur_id, numero_paquet, num_premier, num_dernier, quantite_vignettes, date_reception, agent_id)
        VALUES (?,?,?,?,?,?,?)''',
        (f['valeur_id'], f['numero_paquet'], f['num_premier'], f['num_dernier'],
         qte, f['date_reception'], user['id'] if user else 1))
    conn.commit()
    conn.close()
    flash('Paquet enregistré avec succès ✅', 'success')
    return redirect(url_for('regie.paquets'))


@bp.route('/paquets/<int:pid>/modifier', methods=['POST'])
@login_required
@permission_required('modifier', 'regie')
def modifier_paquet(pid):
    f = request.form
    conn = get_db()
    paquet = conn.execute('SELECT * FROM regie_paquets WHERE id=?', (pid,)).fetchone()
    if not paquet:
        conn.close()
        flash('Paquet introuvable', 'danger')
        return redirect(url_for('regie.paquets'))
        
    if paquet['statut'] != 'recu':
        conn.close()
        flash('Impossible de modifier un paquet déjà ouvert.', 'danger')
        return redirect(url_for('regie.paquets'))

    # Recalcul automatique de la quantité
    try:
        qte = int(f['num_dernier']) - int(f['num_premier']) + 1
    except (ValueError, TypeError):
        qte = 0
        
    conn.execute('''UPDATE regie_paquets SET
        valeur_id=?, numero_paquet=?, num_premier=?, num_dernier=?, quantite_vignettes=?, date_reception=?
        WHERE id=?''',
        (f['valeur_id'], f['numero_paquet'], f['num_premier'], f['num_dernier'],
         qte, f['date_reception'], pid))
    conn.commit()
    conn.close()
    flash('Paquet modifié avec succès ✅', 'success')
    return redirect(url_for('regie.paquets'))


@bp.route('/paquets/<int:pid>/supprimer', methods=['POST'])
@login_required
@permission_required('supprimer', 'regie')
def supprimer_paquet(pid):
    conn = get_db()
    paquet = conn.execute('SELECT * FROM regie_paquets WHERE id=?', (pid,)).fetchone()
    if not paquet:
        conn.close()
        flash('Paquet introuvable', 'danger')
        return redirect(url_for('regie.paquets'))
        
    if paquet['statut'] != 'recu':
        conn.close()
        flash('Impossible de supprimer un paquet déjà ouvert.', 'danger')
        return redirect(url_for('regie.paquets'))
        
    conn.execute('DELETE FROM regie_paquets WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    flash('Paquet supprimé avec succès ✅', 'success')
    return redirect(url_for('regie.paquets'))


NB_CARNETS_PAR_PAQUET = 10

@bp.route('/paquets/<int:pid>/ouvrir', methods=['POST'])
@login_required
@permission_required('modifier', 'regie')
def ouvrir_paquet(pid):
    conn = get_db()
    paquet = conn.execute('SELECT * FROM regie_paquets WHERE id=?', (pid,)).fetchone()
    if not paquet:
        flash('Paquet introuvable', 'danger')
        conn.close()
        return redirect(url_for('regie.paquets'))

    # Check if carnets already generated
    existing = conn.execute('SELECT COUNT(*) FROM regie_carnets WHERE paquet_id=?', (pid,)).fetchone()[0]
    if existing > 0:
        flash('Ce paquet a déjà été ouvert.', 'warning')
        conn.close()
        return redirect(url_for('regie.paquets'))

    # Génération automatique de exactement 10 carnets
    try:
        dp = int(paquet['num_premier'])
        arr = int(paquet['num_dernier'])
    except (ValueError, TypeError):
        flash('Numéros de paquet invalides', 'danger')
        conn.close()
        return redirect(url_for('regie.paquets'))

    total = arr - dp + 1
    step = total // NB_CARNETS_PAR_PAQUET
    if step < 1:
        step = 1

    created = 0
    for i in range(NB_CARNETS_PAR_PAQUET):
        debut = dp + i * step
        # Le dernier carnet prend jusqu'au num_dernier pour éviter les restes
        fin = (dp + (i + 1) * step - 1) if i < NB_CARNETS_PAR_PAQUET - 1 else arr
        num_carnet = f"{paquet['numero_paquet']}-C{i+1:02d}"
        conn.execute('''INSERT OR IGNORE INTO regie_carnets
            (paquet_id, valeur_id, numero_carnet, num_premier, num_dernier)
            VALUES (?,?,?,?,?)''',
            (pid, paquet['valeur_id'], num_carnet, debut, fin))
        created += 1

    conn.execute("UPDATE regie_paquets SET statut='ouvert' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    flash(f'{created} carnets générés automatiquement ✅', 'success')
    return redirect(url_for('regie.carnets'))


# ─── Carnets ─────────────────────────────────────────────────────────────────

@bp.route('/carnets')
@login_required
def carnets():
    user = get_current_user()
    conn = get_db()

    statut  = request.args.get('statut', '')
    valeur  = request.args.get('valeur_id', '')
    service = request.args.get('service_id', '')
    employe = request.args.get('employe_id', '')

    q = '''
        SELECT c.*, v.designation, v.valeur_unitaire, v.nb_unites_carnet,
               s.nom as service_nom, e.nom as emp_nom, e.prenom as emp_prenom,
               p.numero_paquet
        FROM regie_carnets c
        JOIN regie_valeurs v ON v.id = c.valeur_id
        LEFT JOIN regie_services s ON s.id = c.service_id
        LEFT JOIN regie_employes e ON e.id = c.employe_id
        LEFT JOIN regie_paquets p ON p.id = c.paquet_id
        WHERE 1=1
    '''
    params = []
    if statut:
        q += ' AND c.statut = ?'; params.append(statut)
    if valeur:
        q += ' AND c.valeur_id = ?'; params.append(valeur)
    if service:
        q += ' AND c.service_id = ?'; params.append(service)
    if employe:
        q += ' AND c.employe_id = ?'; params.append(employe)
    q += ' ORDER BY c.id DESC'

    carnets = [dict(c) for c in conn.execute(q, params).fetchall()]
    services  = conn.execute("SELECT * FROM regie_services WHERE actif=1").fetchall()
    employes  = conn.execute('''SELECT e.*, s.nom as service_nom FROM regie_employes e
        LEFT JOIN regie_services s ON s.id = e.service_id WHERE e.actif=1''').fetchall()
    valeurs   = conn.execute("SELECT * FROM regie_valeurs WHERE actif=1").fetchall()
    conn.close()

    return render_template('regie/carnets.html',
        user=user, carnets=carnets,
        services=[dict(s) for s in services],
        employes=[dict(e) for e in employes],
        valeurs=valeurs,
        statut_filtre=statut, valeur_filtre=valeur,
        service_filtre=service, employe_filtre=employe)


@bp.route('/carnets/<int:cid>/affecter', methods=['POST'])
@login_required
@permission_required('modifier', 'regie')
def affecter_carnet(cid):
    f = request.form
    conn = get_db()
    conn.execute('''UPDATE regie_carnets SET statut='affecte', service_id=?, employe_id=?,
        date_affectation=? WHERE id=? AND statut='en_stock' ''',
        (f['service_id'], f['employe_id'], date.today().isoformat(), cid))
    conn.commit()
    conn.close()
    flash('Carnet affecté ✅', 'success')
    return redirect(url_for('regie.carnets'))


# ─── Versements ───────────────────────────────────────────────────────────────

@bp.route('/versements')
@login_required
def versements():
    user = get_current_user()
    conn = get_db()

    # Carnets affectés (prêts à être versés par les employés)
    affectes = conn.execute('''
        SELECT c.*, v.designation, v.valeur_unitaire, v.nb_unites_carnet,
               s.nom as service_nom, e.nom as emp_nom, e.prenom as emp_prenom,
               (v.valeur_unitaire * v.nb_unites_carnet) as valeur_theorique
        FROM regie_carnets c
        JOIN regie_valeurs v ON v.id = c.valeur_id
        LEFT JOIN regie_services s ON s.id = c.service_id
        LEFT JOIN regie_employes e ON e.id = c.employe_id
        WHERE c.statut = 'affecte'
        ORDER BY c.date_affectation
    ''').fetchall()

    # Carnets consommés (versés par les employés) mais pas encore inclus dans un bordereau percepteur
    en_attente_bordereau = conn.execute('''
        SELECT c.*, v.designation, v.valeur_unitaire, v.nb_unites_carnet,
               s.nom as service_nom, e.nom as emp_nom, e.prenom as emp_prenom,
               (v.valeur_unitaire * v.nb_unites_carnet) as valeur_theorique
        FROM regie_carnets c
        JOIN regie_valeurs v ON v.id = c.valeur_id
        LEFT JOIN regie_services s ON s.id = c.service_id
        LEFT JOIN regie_employes e ON e.id = c.employe_id
        WHERE c.statut = 'consomme' AND c.bordereau_id IS NULL
        ORDER BY c.date_versement_employe DESC
    ''').fetchall()

    # Totaux caisse en attente de bordereautage
    total_en_attente = sum((r['montant_verse'] or 0) for r in en_attente_bordereau)

    # Bordereaux existants
    bordereaux = conn.execute('''
        SELECT b.*, COUNT(c.id) as nb_carnets, SUM(c.montant_verse) as total_verse
        FROM regie_bordereaux b
        LEFT JOIN regie_carnets c ON c.bordereau_id = b.id
        GROUP BY b.id ORDER BY b.date_creation DESC LIMIT 50
    ''').fetchall()

    conn.close()
    return render_template('regie/versements.html',
        user=user,
        affectes=[dict(a) for a in affectes],
        en_attente_bordereau=[dict(r) for r in en_attente_bordereau],
        total_en_attente=total_en_attente,
        bordereaux=[dict(b) for b in bordereaux])


@bp.route('/versements/employe', methods=['POST'])
@login_required
@permission_required('valider_paiement')
def versement_employe():
    f = request.form
    carnet_id = f.get('carnet_id')
    montant = float(f.get('montant_verse', 0))
    date_vers = f.get('date_versement', date.today().isoformat())

    conn = get_db()
    carnet = conn.execute('''SELECT c.*, v.valeur_unitaire, v.nb_unites_carnet
        FROM regie_carnets c JOIN regie_valeurs v ON v.id=c.valeur_id
        WHERE c.id=?''', (carnet_id,)).fetchone()

    if not carnet:
        flash('Carnet introuvable', 'danger')
        conn.close()
        return redirect(url_for('regie.versements'))

    valeur_theorique = carnet['valeur_unitaire'] * carnet['nb_unites_carnet']
    ecart = round(montant - valeur_theorique, 2)

    conn.execute('''UPDATE regie_carnets SET statut='consomme', montant_verse=?,
        ecart=?, date_versement_employe=?, observation=? WHERE id=?''',
        (montant, ecart, date_vers, f.get('observation',''), carnet_id))
    conn.commit()
    conn.close()

    if ecart != 0:
        flash(f'Versement enregistré ⚠️ Écart de caisse : {ecart:+.2f} DH', 'warning')
    else:
        flash('Versement employé enregistré ✅ Aucun écart.', 'success')
    return redirect(url_for('regie.versements'))


@bp.route('/versements/bordereau', methods=['POST'])
@login_required
@permission_required('valider_paiement')
def creer_bordereau():
    user = get_current_user()
    f = request.form
    ids_raw = f.getlist('carnet_ids')
    date_vers = f.get('date_versement', date.today().isoformat())
    if not ids_raw:
        flash('Aucun carnet sélectionné', 'warning')
        return redirect(url_for('regie.versements'))

    conn = get_db()
    # Numéro de bordereau : saisi manuellement par le régisseur (numéro du registre percepteur)
    # Fallback auto-généré si vide
    num_manuel = f.get('numero_bordereau', '').strip()
    num = num_manuel if num_manuel else _gen_numero_bordereau(conn)

    # Vérifier unicité du numéro
    existing = conn.execute("SELECT id FROM regie_bordereaux WHERE numero=?", (num,)).fetchone()
    if existing:
        conn.close()
        flash(f'⚠️ Le numéro de bordereau "{num}" existe déjà. Utilisez un numéro différent.', 'danger')
        return redirect(url_for('regie.versements'))

    conn.execute("INSERT INTO regie_bordereaux (numero, date_versement, agent_id) VALUES (?,?,?)",
                 (num, date_vers, user['id'] if user else 1))
    brd_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    total = 0
    for cid in ids_raw:
        c = conn.execute("SELECT montant_verse FROM regie_carnets WHERE id=?", (cid,)).fetchone()
        if c:
            total += c['montant_verse'] or 0
            conn.execute('''UPDATE regie_carnets SET bordereau_id=?, date_versement_percepteur=?
                WHERE id=?''', (brd_id, date_vers, cid))

    conn.execute("UPDATE regie_bordereaux SET montant_total=? WHERE id=?", (round(total,2), brd_id))
    conn.commit()
    conn.close()
    flash(f'Bordereau N° {num} créé — Total : {total:.2f} DH ✅', 'success')
    return redirect(url_for('regie.versements'))


@bp.route('/versements/bordereau/<int:bid>/imprimer')
@login_required
def imprimer_bordereau(bid):
    user = get_current_user()
    conn = get_db()
    bordereau = conn.execute("SELECT * FROM regie_bordereaux WHERE id=?", (bid,)).fetchone()
    if not bordereau:
        flash('Bordereau introuvable', 'danger')
        conn.close()
        return redirect(url_for('regie.versements'))

    carnets = conn.execute('''
        SELECT c.*, v.designation, v.valeur_unitaire, v.nb_unites_carnet,
               s.nom as service_nom, e.nom as emp_nom, e.prenom as emp_prenom
        FROM regie_carnets c
        JOIN regie_valeurs v ON v.id = c.valeur_id
        LEFT JOIN regie_services s ON s.id = c.service_id
        LEFT JOIN regie_employes e ON e.id = c.employe_id
        WHERE c.bordereau_id = ?
        ORDER BY c.id
    ''', (bid,)).fetchall()

    commune = conn.execute("SELECT * FROM communes LIMIT 1").fetchone()
    conn.close()
    return render_template('regie/bordereau_print.html',
        user=user,
        bordereau=dict(bordereau),
        carnets=[dict(c) for c in carnets],
        commune=dict(commune) if commune else {},
        today=date.today().isoformat())


# ─── Configuration ────────────────────────────────────────────────────────────

@bp.route('/config')
@login_required
@permission_required('config')
def config():
    user = get_current_user()
    conn = get_db()
    services  = conn.execute("SELECT s.*, COUNT(e.id) as nb_emp FROM regie_services s LEFT JOIN regie_employes e ON e.service_id=s.id AND e.actif=1 GROUP BY s.id ORDER BY s.nom").fetchall()
    employes  = conn.execute("SELECT e.*, s.nom as service_nom FROM regie_employes e LEFT JOIN regie_services s ON s.id=e.service_id ORDER BY e.nom").fetchall()
    valeurs   = conn.execute("SELECT * FROM regie_valeurs ORDER BY designation").fetchall()
    conn.close()
    return render_template('regie/config.html',
        user=user,
        services=[dict(s) for s in services],
        employes=[dict(e) for e in employes],
        valeurs=[dict(v) for v in valeurs])


@bp.route('/config/service/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def ajouter_service():
    conn = get_db()
    conn.execute("INSERT INTO regie_services (nom) VALUES (?)", (request.form['nom'],))
    conn.commit(); conn.close()
    flash('Service ajouté ✅', 'success')
    return redirect(url_for('regie.config'))


@bp.route('/config/service/<int:sid>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def modifier_service(sid):
    conn = get_db()
    conn.execute("UPDATE regie_services SET nom=? WHERE id=?", (request.form['nom'], sid))
    conn.commit(); conn.close()
    flash('Service modifié ✅', 'success')
    return redirect(url_for('regie.config'))


@bp.route('/config/service/<int:sid>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def supprimer_service(sid):
    conn = get_db()
    nb = conn.execute("SELECT COUNT(*) FROM regie_employes WHERE service_id=? AND actif=1", (sid,)).fetchone()[0]
    if nb > 0:
        flash(f'Impossible : {nb} employé(s) rattaché(s) à ce service ❌', 'danger')
    else:
        conn.execute("DELETE FROM regie_services WHERE id=?", (sid,))
        conn.commit()
        flash('Service supprimé ✅', 'success')
    conn.close()
    return redirect(url_for('regie.config'))


@bp.route('/config/service/<int:sid>/toggle', methods=['POST'])
@login_required
@permission_required('config')
def toggle_service(sid):
    conn = get_db()
    conn.execute("UPDATE regie_services SET actif = 1-actif WHERE id=?", (sid,))
    conn.commit(); conn.close()
    return redirect(url_for('regie.config'))


@bp.route('/config/employe/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def ajouter_employe():
    f = request.form
    conn = get_db()
    conn.execute("INSERT INTO regie_employes (matricule, nom, prenom, service_id) VALUES (?,?,?,?)",
                 (f.get('matricule',''), f['nom'], f.get('prenom',''), f['service_id']))
    conn.commit(); conn.close()
    flash('Employé ajouté ✅', 'success')
    return redirect(url_for('regie.config'))


@bp.route('/config/employe/<int:eid>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def modifier_employe(eid):
    f = request.form
    conn = get_db()
    conn.execute("UPDATE regie_employes SET nom=?, prenom=?, matricule=?, service_id=? WHERE id=?",
                 (f['nom'], f.get('prenom',''), f.get('matricule',''), f['service_id'], eid))
    conn.commit(); conn.close()
    flash('Employé modifié ✅', 'success')
    return redirect(url_for('regie.config'))


@bp.route('/config/employe/<int:eid>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def supprimer_employe(eid):
    conn = get_db()
    nb = conn.execute("SELECT COUNT(*) FROM regie_carnets WHERE employe_id=?", (eid,)).fetchone()[0]
    if nb > 0:
        flash(f'Impossible : cet employé a {nb} carnet(s) associé(s) ❌', 'danger')
    else:
        conn.execute("DELETE FROM regie_employes WHERE id=?", (eid,))
        conn.commit()
        flash('Employé supprimé ✅', 'success')
    conn.close()
    return redirect(url_for('regie.config'))


@bp.route('/config/employe/<int:eid>/toggle', methods=['POST'])
@login_required
@permission_required('config')
def toggle_employe(eid):
    conn = get_db()
    conn.execute("UPDATE regie_employes SET actif = 1-actif WHERE id=?", (eid,))
    conn.commit(); conn.close()
    return redirect(url_for('regie.config'))


@bp.route('/config/valeur/ajouter', methods=['POST'])
@login_required
@permission_required('config')
def ajouter_valeur():
    f = request.form
    conn = get_db()
    conn.execute("INSERT INTO regie_valeurs (type_valeur, designation, valeur_unitaire, nb_unites_carnet) VALUES (?,?,?,?)",
                 (f.get('type_valeur','timbre'), f['designation'], float(f['valeur_unitaire']), int(f['nb_unites_carnet'])))
    conn.commit(); conn.close()
    flash('Type de valeur ajouté ✅', 'success')
    return redirect(url_for('regie.config'))


@bp.route('/config/valeur/<int:vid>/modifier', methods=['POST'])
@login_required
@permission_required('config')
def modifier_valeur(vid):
    f = request.form
    conn = get_db()
    conn.execute("UPDATE regie_valeurs SET designation=?, valeur_unitaire=?, nb_unites_carnet=?, type_valeur=? WHERE id=?",
                 (f['designation'], float(f['valeur_unitaire']), int(f['nb_unites_carnet']), f.get('type_valeur','timbre'), vid))
    conn.commit(); conn.close()
    flash('Type de valeur modifié ✅', 'success')
    return redirect(url_for('regie.config'))


@bp.route('/config/valeur/<int:vid>/supprimer', methods=['POST'])
@login_required
@permission_required('config')
def supprimer_valeur(vid):
    conn = get_db()
    nb = conn.execute("SELECT COUNT(*) FROM regie_carnets WHERE valeur_id=?", (vid,)).fetchone()[0]
    if nb > 0:
        flash(f'Impossible : {nb} carnet(s) utilisent ce type ❌', 'danger')
    else:
        conn.execute("DELETE FROM regie_valeurs WHERE id=?", (vid,))
        conn.commit()
        flash('Type de valeur supprimé ✅', 'success')
    conn.close()
    return redirect(url_for('regie.config'))


@bp.route('/config/employes-par-service/<int:sid>')
def employes_par_service(sid):
    conn = get_db()
    emps = conn.execute("SELECT id, nom, prenom FROM regie_employes WHERE service_id=? AND actif=1", (sid,)).fetchall()
    conn.close()
    return jsonify([dict(e) for e in emps])


# ─── RELEVÉS TGR ──────────────────────────────────────────────────────────────

@bp.route('/tgr')
@login_required
def tgr_index():
    user = get_current_user()
    return render_template('regie/tgr_view.html', user=user, meta=None, operations=[])


@bp.route('/tgr/upload', methods=['POST'])
@login_required
@permission_required('valider_paiement')
def tgr_upload():
    user = get_current_user()
    if 'fichier' not in request.files:
        flash('Aucun fichier sélectionné', 'danger')
        return redirect(url_for('regie.tgr_index'))
    
    file = request.files['fichier']
    if file.filename == '':
        flash('Aucun fichier sélectionné', 'danger')
        return redirect(url_for('regie.tgr_index'))
        
    if not file.filename.lower().endswith(('.xls', '.xlsx', '.xlsm')):
        flash('Format non supporté. Veuillez utiliser un fichier Excel (.xls, .xlsx)', 'danger')
        return redirect(url_for('regie.tgr_index'))
        
    from modules.tgr_parser import parse_releve
    import tempfile
    
    # Save temporarily to parse
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(file.filename)[1])
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(file.read())
            
        meta, ops = parse_releve(path)
        
        # Save parsed data to session or temporary file if we want to export later
        # Since it's web, we can just pass it to the template, but for export we'll need it again.
        # Actually, best is to store the uploaded file somewhere safe temporarily, 
        # or parse and store JSON in session. JSON is better if it's small, but ops can be large.
        # Let's keep the temp file and pass its path to the session.
        from flask import session
        session['tgr_last_file'] = path
        
        flash(f'Import réussi : {len(ops)} opérations trouvées.', 'success')
        return render_template('regie/tgr_view.html', user=user, meta=meta, operations=ops)
        
    except Exception as e:
        os.remove(path)
        flash(f'Erreur lors du traitement du fichier : {str(e)}', 'danger')
        return redirect(url_for('regie.tgr_index'))


@bp.route('/tgr/export')
@login_required
def tgr_export():
    from flask import session
    path = session.get('tgr_last_file')
    if not path or not os.path.exists(path):
        flash('Aucun fichier chargé récemment.', 'warning')
        return redirect(url_for('regie.tgr_index'))
        
    from modules.tgr_parser import parse_releve, exporter_xlsx
    import tempfile
    
    debut = request.args.get('debut')
    fin = request.args.get('fin')
    rub = request.args.get('rubrique')
    search = request.args.get('search', '').lower()
    
    try:
        meta, ops = parse_releve(path)
        
        filtered_ops = []
        tot_g = 0.0
        for op in ops:
            match = True
            if rub and op.libelle_rubrique != rub: match = False
            if debut and op.date and op.date.isoformat() < debut: match = False
            if fin and op.date and op.date.isoformat() > fin: match = False
            if search:
                search_str = f"{op.partie_versante} {op.libelle_rubrique} {op.ref_paiement}".lower()
                if search not in search_str: match = False
            
            if match:
                filtered_ops.append(op)
                tot_g += op.total
                
        # Update meta with filtered total for the export
        meta.total_general = tot_g
        
        fd, out_path = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        
        exporter_xlsx(meta, filtered_ops, out_path)
        
        filename = f"Activite_mensuelle_{meta.periode_debut.strftime('%Y%m%d') if meta.periode_debut else 'export'}.xlsx"
        return send_file(out_path, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f'Erreur lors de l\'export : {str(e)}', 'danger')
        return redirect(url_for('regie.tgr_index'))

@bp.route('/tgr/pdf')
@login_required
def tgr_pdf():
    from flask import session
    path = session.get('tgr_last_file')
    if not path or not os.path.exists(path):
        flash('Aucun fichier chargé récemment.', 'warning')
        return redirect(url_for('regie.tgr_index'))
        
    from modules.tgr_parser import parse_releve, chiffre_en_lettre
    
    debut = request.args.get('debut')
    fin = request.args.get('fin')
    rub = request.args.get('rubrique')
    search = request.args.get('search', '').lower()
    
    try:
        meta, ops = parse_releve(path)
        
        filtered_ops = []
        tot_g = 0.0
        for op in ops:
            match = True
            if rub and op.libelle_rubrique != rub: match = False
            if debut and op.date and op.date.isoformat() < debut: match = False
            if fin and op.date and op.date.isoformat() > fin: match = False
            if search:
                search_str = f"{op.partie_versante} {op.libelle_rubrique} {op.ref_paiement}".lower()
                if search not in search_str: match = False
                
            if match:
                filtered_ops.append(op)
                tot_g += op.total
                
        meta.total_general = tot_g
        lettres = chiffre_en_lettre(tot_g)
        
        from database import get_db
        _conn = get_db()
        _cr = _conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
        _cd = dict(_cr) if _cr else {}
        _conn.close()
        return render_template('regie/tgr_pdf.html', meta=meta, operations=filtered_ops, lettres=lettres, date_today=date.today().strftime('%d/%m/%Y'),
                               commune_ar=_cd.get('nom_ar', ''), province_ar=_cd.get('province_ar', ''), region_ar=_cd.get('region_ar', ''))
    except Exception as e:
        flash(f'Erreur lors de la génération PDF : {str(e)}', 'danger')
        return redirect(url_for('regie.tgr_index'))

