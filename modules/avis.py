"""
modules/avis.py — Blueprint de gestion des avis de non-paiement et lettres de relance
"""
from datetime import date, datetime
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import get_db
from modules.helpers import login_required, get_current_user, gen_num

bp = Blueprint('avis', __name__)

MODULE_LABELS = {
    'TNB': 'Taxe Terrains Non Bâtis',
    'DEBITS_BOISSONS': 'Débits de Boissons',
    'STATIONNEMENT': 'Stationnement TPV',
    'OCCUPATION_DOMAINE': 'Occupation Domaine Public',
    'FOURRIERE': 'Fourrière',
    'LOCATION_LOCAUX': 'Location Locaux Commerciaux',
    'AFFERMAGE_SOUKS': 'Affermage Souks',
}
MODULE_ICONS = {
    'TNB': '🏗️', 'DEBITS_BOISSONS': '🍺', 'STATIONNEMENT': '🚌',
    'OCCUPATION_DOMAINE': '🏕️', 'FOURRIERE': '🚗',
    'LOCATION_LOCAUX': '🏪', 'AFFERMAGE_SOUKS': '🛒',
}

def _get_impaye_par_module(conn, module=None):
    q = '''
        SELECT d.id as decl_id, d.module, d.annee, d.trimestre,
               d.montant_total, d.montant_principal, d.penalite_retard,
               d.statut, d.date_echeance, d.numero as decl_numero,
               c.id as ctb_id, c.nom, c.prenom, c.raison_sociale,
               c.cin, c.ice, c.telephone, c.adresse, c.numero as ctb_numero,
               a.id as avis_id, a.numero_avis, a.date_emission as avis_date,
               a.statut as avis_statut, a.lot_id, a.lettre_id
        FROM declarations d
        JOIN contribuables c ON c.id = d.contribuable_id
        LEFT JOIN avis_non_paiement a ON a.declaration_id = d.id
        WHERE d.statut NOT IN ("paye","annule") AND d.montant_total > 0
    '''
    params = []
    if module:
        q += ' AND d.module = ?'
        params.append(module)
    q += ' ORDER BY d.module, c.nom, d.annee DESC'
    return conn.execute(q, params).fetchall()

def _get_stats_recouvrement(conn):
    par_module = conn.execute('''
        SELECT module,
               COUNT(*) as nb_impayes,
               COUNT(DISTINCT contribuable_id) as nb_redevables,
               SUM(montant_total) as total_du,
               COUNT(CASE WHEN statut="emis" THEN 1 END) as nb_emis,
               SUM(CASE WHEN statut="paye" THEN montant_total ELSE 0 END) as total_recouvre
        FROM declarations
        GROUP BY module ORDER BY total_du DESC
    ''').fetchall()
    par_annee = conn.execute('''
        SELECT annee, module,
               COUNT(CASE WHEN statut NOT IN ("paye","annule") THEN 1 END) as nb_impayes,
               SUM(CASE WHEN statut NOT IN ("paye","annule") THEN montant_total ELSE 0 END) as total_du
        FROM declarations
        GROUP BY annee, module ORDER BY annee DESC, module
    ''').fetchall()
    return [dict(r) for r in par_module], [dict(r) for r in par_annee]

@bp.route('/avis')
@login_required
def avis():
    user = get_current_user()
    conn = get_db()
    module_filtre = request.args.get('module', '')
    statut_filtre = request.args.get('statut', '')
    annee_filtre = request.args.get('annee', '')

    rows = _get_impaye_par_module(conn, module_filtre or None)

    if statut_filtre:
        rows = [r for r in rows if (r['avis_statut'] or '') == statut_filtre]
    if annee_filtre:
        rows = [r for r in rows if str(r['annee']) == annee_filtre]

    modules_data = defaultdict(lambda: {'rows': [], 'total': 0, 'nb_ctb': set()})
    for r in rows:
        m = r['module']
        modules_data[m]['rows'].append(dict(r))
        modules_data[m]['total'] += float(r['montant_total'] or 0)
        modules_data[m]['nb_ctb'].add(r['ctb_id'])

    modules_list = []
    for mod, d in sorted(modules_data.items()):
        modules_list.append({
            'module': mod,
            'label': MODULE_LABELS.get(mod, mod),
            'icon': MODULE_ICONS.get(mod, '📋'),
            'rows': d['rows'],
            'total': round(d['total'], 2),
            'nb_redevables': len(d['nb_ctb']),
            'nb_avis_emis': sum(1 for r in d['rows'] if r.get('avis_id')),
        })

    stats_module, stats_annee = _get_stats_recouvrement(conn)
    total_global = sum(m['total'] for m in modules_list)

    lettres = conn.execute('''
        SELECT l.*, u.nom as agent_nom
        FROM lettres_notification l
        LEFT JOIN utilisateurs u ON u.id = l.agent_id
        ORDER BY l.date_creation DESC LIMIT 50
    ''').fetchall()

    annees = [r['annee'] for r in conn.execute(
        'SELECT DISTINCT annee FROM declarations ORDER BY annee DESC').fetchall()]

    return render_template('admin/avis.html',
        user=user, modules_list=modules_list,
        stats_module=stats_module, stats_annee=stats_annee,
        total_global=total_global, lettres=lettres,
        annees=annees, module_filtre=module_filtre,
        statut_filtre=statut_filtre, annee_filtre=annee_filtre,
        MODULE_LABELS=MODULE_LABELS, MODULE_ICONS=MODULE_ICONS,
        today=date.today().isoformat())

@bp.route('/avis/generer', methods=['POST'])
@login_required
def generer_avis():
    user = get_current_user()
    conn = get_db()
    module = request.form.get('module', '')
    lot_id = f"LOT{datetime.now().strftime('%Y%m%d%H%M%S')}"

    q = '''SELECT * FROM declarations
           WHERE statut NOT IN ("paye","annule") AND montant_total > 0
           AND id NOT IN (SELECT declaration_id FROM avis_non_paiement WHERE statut="emis")'''
    params = []
    if module:
        q += ' AND module=?'
        params.append(module)

    decls = conn.execute(q, params).fetchall()
    count = 0
    for d in decls:
        num = gen_num('AVS', 'avis_non_paiement', 'numero_avis', db_conn=conn)
        conn.execute('''INSERT INTO avis_non_paiement
            (numero_avis,declaration_id,contribuable_id,commune_id,montant_du,date_emission,lot_id)
            VALUES (?,?,?,?,?,?,?)''',
            (num, d['id'], d['contribuable_id'], d['commune_id'],
             d['montant_total'], date.today().isoformat(), lot_id))
        count += 1

    conn.commit()
    flash(f'{count} avis générés ✅ (lot: {lot_id})', 'success')
    return redirect(url_for('avis.avis'))

@bp.route('/avis/generer-individuel', methods=['POST'])
@login_required
def generer_avis_individuel():
    decl_id = request.form.get('declaration_id')
    if not decl_id:
        flash('Déclaration manquante', 'danger')
        return redirect(url_for('avis.avis'))
    conn = get_db()
    d = conn.execute('SELECT * FROM declarations WHERE id=?', (decl_id,)).fetchone()
    if d:
        num = gen_num('AVS', 'avis_non_paiement', 'numero_avis', db_conn=conn)
        lot_id = f"LOT{datetime.now().strftime('%Y%m%d%H%M%S')}"
        conn.execute('''INSERT INTO avis_non_paiement
            (numero_avis,declaration_id,contribuable_id,commune_id,montant_du,date_emission,lot_id)
            VALUES (?,?,?,?,?,?,?)''',
            (num, d['id'], d['contribuable_id'], d['commune_id'],
             d['montant_total'], date.today().isoformat(), lot_id))
        conn.commit()
        flash(f'Avis {num} créé ✅', 'success')
    return redirect(url_for('avis.avis'))

@bp.route('/avis/lettre/generer', methods=['POST'])
@login_required
def generer_lettre():
    user = get_current_user()
    conn = get_db()
    module = request.form.get('module', '')
    type_lettre = request.form.get('type_lettre', 'relance')
    avis_ids_raw = request.form.get('avis_ids', '')
    avis_ids = [int(x) for x in avis_ids_raw.split(',') if x.strip().isdigit()]

    if not avis_ids:
        q = '''SELECT a.id, a.montant_du, a.contribuable_id, a.declaration_id
               FROM avis_non_paiement a
               JOIN declarations d ON d.id = a.declaration_id
               WHERE a.statut="emis"'''
        params = []
        if module:
            q += ' AND d.module=?'
            params.append(module)
        avis_rows = conn.execute(q, params).fetchall()
    else:
        avis_rows = conn.execute(
            f'SELECT id, montant_du, contribuable_id, declaration_id FROM avis_non_paiement WHERE id IN ({",".join("?" for _ in avis_ids)})',
            avis_ids
        ).fetchall()

    if not avis_rows:
        flash('Aucun avis à inclure dans la lettre.', 'warning')
        return redirect(url_for('avis.avis'))

    n = conn.execute('SELECT COUNT(*) as c FROM lettres_notification').fetchone()['c'] + 1
    num_lettre = f"LTR{datetime.now().year}{n:05d}"
    lot_id = f"LOT{datetime.now().strftime('%Y%m%d%H%M%S')}"
    total = sum(float(r['montant_du']) for r in avis_rows)

    conn.execute('''INSERT INTO lettres_notification
        (numero_lettre, lot_id, module, type_lettre, statut, date_generation,
         agent_id, nb_redevables, montant_total)
        VALUES (?,?,?,?,"brouillon",?,?,?,?)''',
        (num_lettre, lot_id, module, type_lettre, date.today().isoformat(),
         user['id'] if user else None, len(avis_rows), round(total, 2)))
    lettre_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    for r in avis_rows:
        conn.execute('''INSERT INTO lettres_details
            (lettre_id, avis_id, declaration_id, contribuable_id, montant_du)
            VALUES (?,?,?,?,?)''',
            (lettre_id, r['id'], r['declaration_id'], r['contribuable_id'], r['montant_du']))
        conn.execute('UPDATE avis_non_paiement SET lettre_id=? WHERE id=?', (lettre_id, r['id']))

    conn.commit()
    flash(f'Lettre {num_lettre} créée en brouillon — {len(avis_rows)} redevable(s) ✅', 'success')
    return redirect(url_for('avis.lettre_imprimer', id=lettre_id))

@bp.route('/avis/lettre/<int:id>/imprimer')
@login_required
def lettre_imprimer(id):
    user = get_current_user()
    conn = get_db()
    lettre = conn.execute('SELECT * FROM lettres_notification WHERE id=?', (id,)).fetchone()
    if not lettre:
        flash('Lettre introuvable', 'danger')
        return redirect(url_for('avis.avis'))

    details = conn.execute('''
        SELECT ld.*, c.nom, c.prenom, c.raison_sociale, c.cin, c.adresse, c.telephone,
               d.annee, d.module, d.numero as decl_numero, d.montant_total,
               d.montant_principal, d.penalite_retard,
               a.numero_avis, a.date_emission
        FROM lettres_details ld
        JOIN contribuables c ON c.id = ld.contribuable_id
        JOIN declarations d ON d.id = ld.declaration_id
        LEFT JOIN avis_non_paiement a ON a.id = ld.avis_id
        WHERE ld.lettre_id = ?
        ORDER BY c.nom, d.annee
    ''', (id,)).fetchall()

    commune = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    return render_template('admin/lettre_notification.html',
        user=user, lettre=dict(lettre),
        details=[dict(d) for d in details],
        commune=dict(commune) if commune else {},
        MODULE_LABELS=MODULE_LABELS,
        today=date.today().isoformat())

@bp.route('/avis/lettre/<int:id>/approuver', methods=['POST'])
@login_required
def lettre_approuver(id):
    conn = get_db()
    conn.execute('''UPDATE lettres_notification
        SET statut="envoyee", date_envoi=? WHERE id=? AND statut="brouillon"''',
        (date.today().isoformat(), id))
    conn.commit()
    lettre = conn.execute('SELECT numero_lettre FROM lettres_notification WHERE id=?', (id,)).fetchone()
    if lettre:
        flash(f'Lettre {lettre["numero_lettre"]} marquée comme envoyée ✅', 'success')
    return redirect(url_for('avis.avis') + '#lettres')

@bp.route('/avis/lettre/<int:id>/annuler', methods=['POST'])
@login_required
def lettre_annuler(id):
    conn = get_db()
    conn.execute('UPDATE lettres_notification SET statut="annulee" WHERE id=?', (id,))
    conn.execute('UPDATE avis_non_paiement SET lettre_id=NULL WHERE lettre_id=?', (id,))
    conn.commit()
    flash('Lettre annulée', 'warning')
    return redirect(url_for('avis.avis') + '#lettres')

@bp.route('/avis/export-excel')
@login_required
def avis_export_excel():
    conn = get_db()
    module = request.args.get('module', '')
    rows = _get_impaye_par_module(conn, module or None)
    data = []
    for r in rows:
        data.append({
            'Module': MODULE_LABELS.get(r['module'], r['module']),
            'N° Déclaration': r['decl_numero'],
            'Redevable': f"{r['nom']} {r['prenom'] or r['raison_sociale'] or ''}".strip(),
            'CIN/ICE': r['cin'] or '',
            'Téléphone': r['telephone'] or '',
            'Adresse': r['adresse'] or '',
            'Année': r['annee'],
            'Montant Dû (DH)': round(float(r['montant_total'] or 0), 2),
            'N° Avis': r['numero_avis'] or '',
            'Date Avis': r['avis_date'] or '',
            'Statut Avis': r['avis_statut'] or 'Sans avis',
        })
    return jsonify(data)
