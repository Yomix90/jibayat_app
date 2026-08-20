"""
modules/bulletins.py — Blueprint de gestion des bulletins de versement et validation des paiements
"""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import get_db
from modules.helpers import login_required, get_current_user, gen_num

bp = Blueprint('bulletins', __name__)

@bp.route('/paiements')
@login_required
def paiements():
    user = get_current_user()
    conn = get_db()
    items = conn.execute('''SELECT b.*, d.module, d.annee, d.reference_id,
            c.nom, c.prenom, c.raison_sociale
        FROM bulletins b
        JOIN declarations d ON b.declaration_id=d.id
        LEFT JOIN contribuables c ON b.contribuable_id=c.id
        ORDER BY b.date_creation DESC''').fetchall()
    decls_sans_bulletin = conn.execute('''SELECT d.*, c.nom, c.prenom, c.raison_sociale FROM declarations d
        JOIN contribuables c ON d.contribuable_id=c.id
        WHERE d.statut="emis" AND d.montant_total>0
        AND d.id NOT IN (SELECT declaration_id FROM bulletins WHERE statut IN ("en_attente","paye"))
        ORDER BY d.date_creation DESC''').fetchall()
    return render_template('paiements/paiements.html', user=user, items=items,
                           decls=decls_sans_bulletin, today=date.today().isoformat())

@bp.route('/bulletins/creer', methods=['POST'])
@login_required
def creer_bulletin():
    user = get_current_user()
    if not user['peut_creer_bulletin']:
        flash('Accès refusé', 'danger')
        return redirect(url_for('bulletins.paiements'))
    f = request.form
    conn = get_db()
    decl = conn.execute('SELECT * FROM declarations WHERE id=?', (f['declaration_id'],)).fetchone()
    if decl:
        num = gen_num('BUL', 'bulletins', 'numero_bulletin', db_conn=conn)
        conn.execute('''INSERT INTO bulletins (numero_bulletin,declaration_id,contribuable_id,commune_id,montant,mode_paiement,date_paiement,agent_id,notes)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (num, decl['id'], decl['contribuable_id'], decl['commune_id'], decl['montant_total'],
             f.get('mode_paiement','especes'), f.get('date_paiement', date.today().isoformat()),
             user['id'], f.get('notes','')))
        conn.commit()
        flash(f'Bulletin {num} créé — En attente validation régisseur ✅', 'success')
    return redirect(url_for('bulletins.paiements'))

@bp.route('/bulletins/<int:id>/valider', methods=['POST'])
@login_required
def valider_bulletin(id):
    user = get_current_user()
    if not user['peut_valider_paiement']:
        flash('Accès refusé — Réservé au Régisseur', 'danger')
        return redirect(url_for('bulletins.paiements'))
    f = request.form
    num_quittance = f.get('numero_quittance', '').strip()
    date_quittance = f.get('date_quittance', date.today().isoformat())
    if not num_quittance:
        flash('Le numéro de quittance est obligatoire', 'danger')
        return redirect(url_for('bulletins.paiements'))
    conn = get_db()
    b = conn.execute('SELECT * FROM bulletins WHERE id=?', (id,)).fetchone()
    if b:
        conn.execute("""UPDATE bulletins 
            SET statut='paye', regisseur_id=?, numero_quittance=?, date_quittance=?
            WHERE id=?""", (user['id'], num_quittance, date_quittance, id))
        conn.execute("UPDATE declarations SET statut='paye', date_paiement=? WHERE id=?",
                     (date_quittance, b['declaration_id']))
        autres = conn.execute(
            "SELECT id, declaration_id FROM bulletins WHERE numero_bulletin=? AND id!=? AND statut='en_attente'",
            (b['numero_bulletin'], id)).fetchall()
        for ab in autres:
            conn.execute("UPDATE bulletins SET statut='paye', regisseur_id=?, numero_quittance=?, date_quittance=? WHERE id=?",
                         (user['id'], num_quittance, date_quittance, ab['id']))
            conn.execute("UPDATE declarations SET statut='paye', date_paiement=? WHERE id=?",
                         (date_quittance, ab['declaration_id']))
        conn.commit()
        total_val = 1 + len(autres)
        decl_row = conn.execute('SELECT module, reference_id FROM declarations WHERE id=?',
                                (b['declaration_id'],)).fetchone()
        if decl_row and decl_row['module'] == 'FOURRIERE' and decl_row['reference_id']:
            conn.execute("UPDATE dossiers_fourriere SET statut='en_attente_sortie' WHERE id=?",
                         (decl_row['reference_id'],))
            conn.commit()
            flash('🚗 Dossier fourrière passé en "Attente sortie"', 'info')
        flash(f'✅ Paiement validé — Quittance N° {num_quittance} — {total_val} déclaration(s) soldée(s)', 'success')
    return redirect(url_for('bulletins.paiements'))

@bp.route('/bulletins/<int:id>/rejeter', methods=['POST'])
@login_required
def rejeter_bulletin(id):
    user = get_current_user()
    if not user['peut_valider_paiement']:
        flash('Accès refusé', 'danger')
        return redirect(url_for('bulletins.paiements'))
    f = request.form
    motif = f.get('motif_rejet', 'Non précisé').strip()
    conn = get_db()
    b = conn.execute('SELECT * FROM bulletins WHERE id=?', (id,)).fetchone()
    if b:
        conn.execute("UPDATE bulletins SET statut='rejete', motif_rejet=?, regisseur_id=? WHERE id=?",
                     (motif, user['id'], id))
        conn.execute("UPDATE declarations SET statut='emis' WHERE id=?", (b['declaration_id'],))
        conn.commit()
        flash(f'❌ Bulletin N° {b["numero_bulletin"]} rejeté : {motif}', 'danger')
    return redirect(url_for('bulletins.paiements'))

@bp.route('/bulletins/valider-masse', methods=['POST'])
@login_required
def valider_bulletins_masse():
    user = get_current_user()
    if not user['peut_valider_paiement']:
        flash('Accès refusé — Réservé au Régisseur', 'danger')
        return redirect(url_for('bulletins.paiements'))
    f = request.form
    num_quittance = f.get('numero_quittance', '').strip()
    date_quittance = f.get('date_quittance', date.today().isoformat())
    bulletin_ids = f.getlist('bulletin_ids')
    if not num_quittance:
        flash('Le numéro de quittance est obligatoire', 'danger')
        return redirect(url_for('bulletins.paiements'))
    if not bulletin_ids:
        flash('Aucun bulletin sélectionné', 'warning')
        return redirect(url_for('bulletins.paiements'))
    conn = get_db()
    count = 0
    for bid in bulletin_ids:
        b = conn.execute("SELECT * FROM bulletins WHERE id=? AND statut='en_attente'", (bid,)).fetchone()
        if b:
            conn.execute("""UPDATE bulletins 
                SET statut='paye', regisseur_id=?, numero_quittance=?, date_quittance=?
                WHERE id=?""", (user['id'], num_quittance, date_quittance, int(bid)))
            conn.execute("UPDATE declarations SET statut='paye', date_paiement=? WHERE id=?",
                         (date_quittance, b['declaration_id']))
            count += 1
    conn.commit()
    flash(f'✅ {count} bulletin(s) validé(s) en masse — Quittance N° {num_quittance}', 'success')
    return redirect(url_for('bulletins.paiements'))
