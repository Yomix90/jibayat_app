"""modules/fourriere.py — Blueprint Fourrière (refonte complète)"""
from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, send_file, jsonify)
from datetime import datetime, date
from database import get_db
from modules.helpers import login_required, get_current_user, gen_num, get_next_seq_num, permission_required
import os, uuid

bp = Blueprint('fou', __name__)

UPLOAD_DIR = os.path.join('uploads', 'fourriere')
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─── Helpers ─────────────────────────────────────────────────────────
def _nb_jours(date_str):
    """Nombre de jours depuis la mise en fourrière (+1)."""
    if not date_str:
        return 0
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        return max(1, (date.today() - d).days + 1)
    except Exception:
        return 0

def _statut_badge(statut, nb_jours):
    """Statut affiché avec flag +365."""
    plus365 = nb_jours > 365
    return statut, plus365

def _get_tarif(conn, code_type):
    """Retourne le tarif journalier pour un type de véhicule."""
    row = conn.execute('''
        SELECT t.valeur FROM tarifs t
        JOIN rubriques r ON t.rubrique_id = r.id
        WHERE r.module='FOURRIERE' AND t.libelle=? AND t.actif=1
    ''', (code_type,)).fetchone()
    return float(row['valeur']) if row else 0.0


def _enrichir_dossier(d):
    """Ajoute nb_jours, montant_du, plus365 à un dossier (dict)."""
    nb = _nb_jours(d['date_mise_fourriere'])
    tarif = float(d['tarif_journalier'] or 0)
    frais = float(d['frais_remorquage'] or 0)
    return dict(d, nb_jours=nb, montant_du=round(nb * tarif + frais, 2),
                plus365=(nb > 365))


# ════════════════════════════════════════════════════════════
#  LISTE PRINCIPALE
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere')
@login_required
def fou_liste():
    user = get_current_user()
    conn = get_db()
    q         = request.args.get('q', '')
    statut_f  = request.args.get('statut', '')
    type_f    = request.args.get('type', '')

    sql = 'SELECT * FROM dossiers_fourriere WHERE actif=1'
    params = []
    if q:
        sql += ' AND (immatriculation LIKE ? OR numero LIKE ? OR num_depot LIKE ? OR nom_proprietaire LIKE ?)'
        params += [f'%{q}%'] * 4
    if statut_f:
        sql += ' AND statut=?'
        params.append(statut_f)
    if type_f:
        sql += ' AND type_vehicule=?'
        params.append(type_f)
    sql += ' ORDER BY date_mise_fourriere DESC'

    raw = conn.execute(sql, params).fetchall()
    items = [_enrichir_dossier(r) for r in raw]

    types_vh   = conn.execute('''
        SELECT MIN(t.id) as id, t.libelle as code, t.libelle, MAX(t.valeur) as tarif_journalier FROM tarifs t
        JOIN rubriques r ON t.rubrique_id = r.id
        WHERE r.module='FOURRIERE' AND t.actif=1 AND t.libelle NOT LIKE '%remorquage%'
        GROUP BY t.libelle
        ORDER BY t.libelle
    ''').fetchall()
    deposants  = conn.execute("SELECT * FROM fou_parametres WHERE categorie='deposant' AND actif=1 ORDER BY ordre").fetchall()

    stats = {
        'total':       len(items),
        'en_fourriere': sum(1 for i in items if i['statut'] == 'en_fourriere'),
        'attente_sortie': sum(1 for i in items if i['statut'] == 'en_attente_sortie'),
        'sortie':      sum(1 for i in items if i['statut'] == 'sortie'),
        'plus365':     sum(1 for i in items if i['plus365'] and i['statut'] not in ('sortie',)),
        'total_du':    round(sum(i['montant_du'] for i in items if i['statut'] != 'sortie'), 2),
    }
    next_numero = get_next_seq_num('dossiers_fourriere', 'numero', conn)
    conn.close()
    return render_template('fourriere/fou_liste.html',
                           user=user, items=items, types_vh=types_vh,
                           deposants=deposants, stats=stats,
                           q=q, statut_f=statut_f, type_f=type_f,
                           today=date.today().isoformat(), next_numero=next_numero)


# ════════════════════════════════════════════════════════════
#  AJOUTER VÉHICULE
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/ajouter', methods=['POST'])
@login_required
@permission_required('ajouter', 'fou')
def fou_ajouter():
    user = get_current_user()
    f = request.form
    conn = get_db()

    type_vh = f.get('type_vehicule', '')
    tarif   = _get_tarif(conn, type_vh)
    num = f.get('numero', '').strip() or get_next_seq_num('dossiers_fourriere', 'numero', conn)

    conn.execute('''INSERT INTO dossiers_fourriere
        (numero, commune_id, num_depot, type_vehicule, immatriculation,
         date_mise_fourriere, deposant, motif, frais_remorquage, tarif_journalier,
         statut, notes, actif)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)''',
        (num, 1,
         f.get('num_depot', ''),
         type_vh,
         f.get('immatriculation', ''),
         f.get('date_mise_fourriere', date.today().isoformat()),
         f.get('deposant', ''),
         f.get('motif', ''),
         float(f.get('frais_remorquage', 0) or 0),
         tarif,
         'en_fourriere',
         f.get('notes', '')))
    conn.commit()
    conn.close()
    flash(f'Véhicule N° {num} mis en fourrière ✅', 'success')
    return redirect(url_for('fou.fou_liste'))


# ════════════════════════════════════════════════════════════
#  DÉTAIL DOSSIER
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/<int:id>')
@login_required
def fou_detail(id):
    user = get_current_user()
    conn = get_db()
    raw = conn.execute('SELECT * FROM dossiers_fourriere WHERE id=?', (id,)).fetchone()
    if not raw:
        flash('Dossier introuvable', 'danger')
        return redirect(url_for('fou.fou_liste'))
    dossier = _enrichir_dossier(raw)

    types_vh   = conn.execute('''
        SELECT MIN(t.id) as id, t.libelle as code, t.libelle, MAX(t.valeur) as tarif_journalier FROM tarifs t
        JOIN rubriques r ON t.rubrique_id = r.id
        WHERE r.module='FOURRIERE' AND t.actif=1 AND t.libelle NOT LIKE '%remorquage%'
        GROUP BY t.libelle
        ORDER BY t.libelle
    ''').fetchall()
    deposants  = conn.execute("SELECT * FROM fou_parametres WHERE categorie='deposant' AND actif=1 ORDER BY ordre").fetchall()
    motifs     = conn.execute("SELECT * FROM fou_parametres WHERE categorie='motif' AND actif=1 ORDER BY ordre").fetchall()

    # Historique bulletins
    bulletins  = conn.execute(
        "SELECT * FROM bulletins WHERE notes LIKE ? ORDER BY date_creation DESC",
        (f'%FOU%{raw["numero"]}%',)
    ).fetchall()

    conn.close()
    return render_template('fourriere/fou_detail.html',
                           user=user, dossier=dossier,
                           types_vh=types_vh, deposants=deposants, motifs=motifs,
                           bulletins=bulletins,
                           today=date.today().isoformat())


# ════════════════════════════════════════════════════════════
#  MODIFIER DOSSIER
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('modifier', 'fou')
def fou_modifier(id):
    f = request.form
    conn = get_db()
    type_vh = f.get('type_vehicule', '')
    tarif = _get_tarif(conn, type_vh)
    conn.execute('''UPDATE dossiers_fourriere SET
        num_depot=?, type_vehicule=?, immatriculation=?,
        date_mise_fourriere=?, deposant=?, motif=?,
        frais_remorquage=?, tarif_journalier=?, notes=? WHERE id=?''',
        (f.get('num_depot',''), type_vh, f.get('immatriculation',''),
         f.get('date_mise_fourriere',''),
         f.get('deposant',''), f.get('motif',''),
         float(f.get('frais_remorquage', 0) or 0), tarif,
         f.get('notes',''), id))
    conn.commit(); conn.close()
    flash('Dossier modifié ✅', 'success')
    return redirect(url_for('fou.fou_detail', id=id))


# ════════════════════════════════════════════════════════════
#  PAIEMENT — Agent saisit N° bulletin + nom propriétaire
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/<int:id>/paiement', methods=['GET'])
@login_required
def fou_paiement(id):
    user = get_current_user()
    conn = get_db()
    raw = conn.execute('SELECT * FROM dossiers_fourriere WHERE id=?', (id,)).fetchone()
    if not raw:
        flash('Dossier introuvable', 'danger')
        conn.close()
        return redirect(url_for('fou.fou_liste'))
    dossier = _enrichir_dossier(raw)
    types_vh   = conn.execute('''
        SELECT MIN(t.id) as id, t.libelle as code, t.libelle, MAX(t.valeur) as tarif_journalier FROM tarifs t
        JOIN rubriques r ON t.rubrique_id = r.id
        WHERE r.module='FOURRIERE' AND t.actif=1 AND t.libelle NOT LIKE '%remorquage%'
        GROUP BY t.libelle
        ORDER BY t.libelle
    ''').fetchall()
    conn.close()
    return render_template('fourriere/fou_paiement.html',
                           user=user, dossier=dossier, types_vh=types_vh,
                           today=date.today().isoformat())


@bp.route('/fourriere/<int:id>/payer', methods=['POST'])
@login_required
@permission_required('creer_bulletin')
def fou_payer(id):
    user = get_current_user()
    f = request.form
    conn = get_db()
    raw = conn.execute('SELECT * FROM dossiers_fourriere WHERE id=?', (id,)).fetchone()
    if not raw:
        flash('Dossier introuvable', 'danger')
        conn.close()
        return redirect(url_for('fou.fou_liste'))

    dossier = _enrichir_dossier(raw)
    nom_prop    = f.get('nom_proprietaire', '').strip()
    cin_prop    = f.get('cin_proprietaire', '').strip()
    tel_prop    = f.get('telephone_prop', '').strip()
    num_bull    = f.get('numero_bulletin', '').strip()
    mode_pmt    = f.get('mode_paiement', 'especes')
    montant     = float(f.get('montant', dossier['montant_du']) or 0)

    if not num_bull:
        flash('Le N° de bulletin est obligatoire', 'danger')
        conn.close()
        return redirect(url_for('fou.fou_paiement', id=id))

    # Vérifier unicité bulletin
    existing = conn.execute('SELECT id FROM bulletins WHERE numero_bulletin=?', (num_bull,)).fetchone()
    if existing:
        flash(f'⚠️ Bulletin n° {num_bull} existe déjà', 'danger')
        conn.close()
        return redirect(url_for('fou.fou_paiement', id=id))

    today_str = date.today().isoformat()

    # Mettre à jour le propriétaire sur le dossier
    conn.execute('''UPDATE dossiers_fourriere SET
        nom_proprietaire=?, cin_proprietaire=?, telephone_prop=?,
        numero_bulletin=? WHERE id=?''',
        (nom_prop, cin_prop, tel_prop, num_bull, id))

    # Déclaration emis
    num_decl = gen_num('FOU-DECL', 'declarations')
    conn.execute('''INSERT INTO declarations
        (numero, module, reference_id, commune_id, annee,
         base_calcul, montant_principal, montant_total, statut,
         date_declaration, date_echeance, agent_id, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (num_decl, 'FOURRIERE', id, 1, date.today().year,
         dossier['montant_du'], montant, montant,
         'emis', today_str, today_str,
         user['id'] if user else None,
         f"Fourrière {raw['numero']} — {dossier['nb_jours']} jours"))
    decl_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    # Bulletin en_attente
    conn.execute('''INSERT INTO bulletins
        (numero_bulletin, declaration_id, commune_id,
         montant, mode_paiement, date_paiement, statut, agent_id, notes)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (num_bull, decl_id, 1,
         montant, mode_pmt, today_str, 'en_attente',
         user['id'] if user else None,
         f"FOU — {raw['numero']} — {nom_prop}"))

    conn.commit(); conn.close()
    flash(f'✅ Bulletin n° {num_bull} créé — {montant:.2f} DH — En attente régisseur (/paiements)',
          'success')
    return redirect(url_for('fou.fou_detail', id=id))


# ════════════════════════════════════════════════════════════
#  VALIDER SORTIE (responsable fourrière)
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/<int:id>/sortie', methods=['POST'])
@login_required
@permission_required('modifier', 'fou')
def fou_sortie(id):
    conn = get_db()
    # Vérifier qu'un bulletin est encaissé/validé
    bull = conn.execute('''
        SELECT b.statut FROM bulletins b
        JOIN declarations d ON d.id=b.declaration_id
        WHERE d.module='FOURRIERE' AND d.reference_id=?
          AND b.statut IN ('valide','encaisse','paye')
        LIMIT 1''', (id,)).fetchone()
    if not bull:
        flash('⚠️ Impossible : aucun paiement validé par le régisseur', 'danger')
        conn.close()
        return redirect(url_for('fou.fou_detail', id=id))

    conn.execute('''UPDATE dossiers_fourriere SET
        statut='sortie', date_sortie_validee=?, date_restitution=? WHERE id=?''',
        (date.today().isoformat(), date.today().isoformat(), id))
    conn.commit(); conn.close()
    flash('✅ Sortie validée — Véhicule restitué', 'success')
    return redirect(url_for('fou.fou_detail', id=id))


# ════════════════════════════════════════════════════════════
#  ENCHÈRES — LISTE DES VÉHICULES +365 JOURS
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/encheres')
@login_required
def fou_encheres():
    user = get_current_user()
    conn = get_db()

    # Véhicules +365 jours encore en fourrière
    raw = conn.execute(
        "SELECT * FROM dossiers_fourriere WHERE actif=1 AND statut NOT IN ('sortie')"
        " ORDER BY date_mise_fourriere ASC"
    ).fetchall()
    veh_plus365 = [_enrichir_dossier(r) for r in raw if _nb_jours(r['date_mise_fourriere']) > 365]

    # IDs déjà dans un groupe
    already_grouped = set(
        r['dossier_id'] for r in
        conn.execute('SELECT dossier_id FROM fou_vehicules_enchere').fetchall()
    )

    groupes = conn.execute(
        'SELECT * FROM fou_groupes_enchere ORDER BY date_creation DESC'
    ).fetchall()

    # Enrichir groupes avec leurs véhicules
    groupes_detail = []
    for g in groupes:
        vehs = conn.execute('''
            SELECT ve.*, d.immatriculation, d.type_vehicule, d.num_depot,
                   d.date_mise_fourriere
            FROM fou_vehicules_enchere ve
            JOIN dossiers_fourriere d ON d.id=ve.dossier_id
            WHERE ve.groupe_id=?
            ORDER BY ve.ordre''', (g['id'],)).fetchall()
        vehs_list = [dict(v) for v in vehs]
        groupes_detail.append({**dict(g), 'vehicules': vehs_list, 'nb_veh': len(vehs_list)})

    types_vh   = conn.execute('''
        SELECT MIN(t.id) as id, t.libelle as code, t.libelle, MAX(t.valeur) as tarif_journalier FROM tarifs t
        JOIN rubriques r ON t.rubrique_id = r.id
        WHERE r.module='FOURRIERE' AND t.actif=1 AND t.libelle NOT LIKE '%remorquage%'
        GROUP BY t.libelle
        ORDER BY t.libelle
    ''').fetchall()
    etats_vh  = conn.execute("SELECT * FROM fou_parametres WHERE categorie='etat_vehicule' AND actif=1 ORDER BY ordre").fetchall()
    conn.close()

    return render_template('fourriere/fou_encheres.html',
                           user=user, veh_plus365=veh_plus365,
                           already_grouped=already_grouped,
                           groupes=groupes_detail,
                           types_vh=types_vh, etats_vh=etats_vh,
                           today=date.today().isoformat())


@bp.route('/fourriere/encheres/groupe/ajouter', methods=['POST'])
@login_required
@permission_required('modifier', 'fou')
def fou_groupe_ajouter():
    user = get_current_user()
    f = request.form
    conn = get_db()
    n = conn.execute('SELECT COUNT(*) as c FROM fou_groupes_enchere').fetchone()['c'] + 1
    num = f"GE{date.today().year}{n:04d}"
    conn.execute('''INSERT INTO fou_groupes_enchere
        (numero, libelle, date_creation, date_enchere, lieu, type_vehicule, prix_ouverture, notes, agent_id)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (num, f.get('libelle',''), date.today().isoformat(),
         f.get('date_enchere',''), f.get('lieu',''),
         f.get('type_vehicule',''), float(f.get('prix_ouverture', 0) or 0),
         f.get('notes',''), user['id'] if user else None))
    conn.commit(); conn.close()
    flash(f'Groupe {num} créé ✅', 'success')
    return redirect(url_for('fou.fou_encheres'))


@bp.route('/fourriere/encheres/groupe/<int:gid>/ajouter-vehicule', methods=['POST'])
@login_required
@permission_required('modifier', 'fou')
def fou_groupe_ajout_vh(gid):
    f = request.form
    conn = get_db()
    dossier_id = int(f.get('dossier_id', 0))
    etat       = f.get('etat_vehicule', 'moyen')
    notes      = f.get('notes', '')
    # Vérifier pas déjà dans un groupe
    existing = conn.execute(
        'SELECT id FROM fou_vehicules_enchere WHERE dossier_id=?', (dossier_id,)
    ).fetchone()
    if existing:
        flash('Ce véhicule est déjà dans un groupe', 'warning')
    else:
        n = conn.execute('SELECT COUNT(*) as c FROM fou_vehicules_enchere WHERE groupe_id=?', (gid,)).fetchone()['c']
        conn.execute('''INSERT INTO fou_vehicules_enchere
            (groupe_id, dossier_id, etat_vehicule, ordre, notes) VALUES (?,?,?,?,?)''',
            (gid, dossier_id, etat, n+1, notes))
        conn.commit()
        flash('Véhicule ajouté au groupe ✅', 'success')
    conn.close()
    return redirect(url_for('fou.fou_encheres'))


@bp.route('/fourriere/encheres/groupe/<int:gid>/retirer/<int:vid>', methods=['POST'])
@login_required
@permission_required('modifier', 'fou')
def fou_groupe_retirer(gid, vid):
    conn = get_db()
    conn.execute('DELETE FROM fou_vehicules_enchere WHERE id=? AND groupe_id=?', (vid, gid))
    conn.commit(); conn.close()
    flash('Véhicule retiré du groupe', 'info')
    return redirect(url_for('fou.fou_encheres'))


@bp.route('/fourriere/encheres/groupe/<int:gid>/prix', methods=['POST'])
@login_required
@permission_required('modifier', 'fou')
def fou_groupe_prix(gid):
    conn = get_db()
    conn.execute('UPDATE fou_groupes_enchere SET prix_ouverture=?, date_enchere=?, lieu=? WHERE id=?',
        (float(request.form.get('prix_ouverture', 0) or 0),
         request.form.get('date_enchere',''),
         request.form.get('lieu',''), gid))
    conn.commit(); conn.close()
    flash('Groupe mis à jour ✅', 'success')
    return redirect(url_for('fou.fou_encheres'))


# ════════════════════════════════════════════════════════════
#  IMPRESSION LISTE GROUPE
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/encheres/groupe/<int:gid>/imprimer')
@login_required
def fou_groupe_imprimer(gid):
    conn = get_db()
    groupe = conn.execute('SELECT * FROM fou_groupes_enchere WHERE id=?', (gid,)).fetchone()
    if not groupe:
        flash('Groupe introuvable', 'danger')
        conn.close()
        return redirect(url_for('fou.fou_encheres'))
    vehs = conn.execute('''
        SELECT ve.*, d.immatriculation, d.type_vehicule, d.num_depot,
               d.date_mise_fourriere, d.marque, d.couleur, d.numero as dos_num
        FROM fou_vehicules_enchere ve
        JOIN dossiers_fourriere d ON d.id=ve.dossier_id
        WHERE ve.groupe_id=? ORDER BY ve.ordre''', (gid,)).fetchall()
    commune_row = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    conn.close()
    commune_dict = dict(commune_row) if commune_row else {}
    return render_template('fourriere/fou_groupe_impression.html',
                           groupe=groupe, vehicules=vehs,
                           commune=commune_dict.get('nom', ''),
                           province=commune_dict.get('province', ''),
                           commune_ar=commune_dict.get('nom_ar', ''),
                           province_ar=commune_dict.get('province_ar', ''),
                           region_ar=commune_dict.get('region_ar', ''),
                           today=date.today().isoformat())


# ════════════════════════════════════════════════════════════
#  VALIDATION VENTE ENCHÈRE
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/encheres/groupe/<int:gid>/vente', methods=['POST'])
@login_required
@permission_required('modifier', 'fou')
def fou_vente_valider(gid):
    user = get_current_user()
    f = request.form
    conn = get_db()

    pv_chemin = None
    pv_nom = None
    pv_file = request.files.get('pv_vente')
    if pv_file and pv_file.filename:
        ext = os.path.splitext(pv_file.filename)[1].lower()
        fname = f"pv_{uuid.uuid4().hex}{ext}"
        pv_chemin = os.path.join(UPLOAD_DIR, fname)
        pv_file.save(pv_chemin)
        pv_nom = pv_file.filename

    dossier_id = int(f.get('dossier_id', 0))
    conn.execute('''INSERT INTO fou_ventes
        (groupe_id, dossier_id, nom_acheteur, cin_acheteur, telephone_acheteur,
         prix_adjudication, numero_quittance, date_vente, pv_chemin, pv_nom, agent_id, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (gid, dossier_id, f.get('nom_acheteur',''), f.get('cin_acheteur',''),
         f.get('telephone_acheteur',''), float(f.get('prix_adjudication', 0) or 0),
         f.get('numero_quittance',''), date.today().isoformat(),
         pv_chemin, pv_nom, user['id'] if user else None, f.get('notes','')))

    # Marquer le véhicule comme sorti
    if dossier_id:
        conn.execute('''UPDATE dossiers_fourriere SET
            statut='sortie', date_sortie_validee=? WHERE id=?''',
            (date.today().isoformat(), dossier_id))
    # Marquer le groupe vendu si tous vendus
    nb_total = conn.execute('SELECT COUNT(*) as c FROM fou_vehicules_enchere WHERE groupe_id=?', (gid,)).fetchone()['c']
    nb_vendus = conn.execute('SELECT COUNT(*) as c FROM fou_ventes WHERE groupe_id=?', (gid,)).fetchone()['c']
    if nb_vendus >= nb_total:
        conn.execute("UPDATE fou_groupes_enchere SET statut='vendu' WHERE id=?", (gid,))

    conn.commit(); conn.close()
    flash('✅ Vente enregistrée — Véhicule sorti', 'success')
    return redirect(url_for('fou.fou_encheres'))


# ════════════════════════════════════════════════════════════
#  PARAMÈTRES MODULE
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/parametres', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def fou_parametres():
    user = get_current_user()
    conn = get_db()
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'add_param':
            cat  = request.form.get('categorie','')
            code = request.form.get('code','').strip().upper()
            lib  = request.form.get('libelle','').strip()
            if cat and code and lib:
                conn.execute('INSERT OR IGNORE INTO fou_parametres(categorie,code,libelle,ordre) VALUES(?,?,?,?)',
                             (cat, code, lib,
                              conn.execute('SELECT COUNT(*) as c FROM fou_parametres WHERE categorie=?',(cat,)).fetchone()['c']+1))
                conn.commit()
                flash('Paramètre ajouté ✅', 'success')

        conn.close()
        return redirect(url_for('fou.fou_parametres'))

    types_vh = conn.execute('''
        SELECT MIN(t.id) as id, t.libelle as code, t.libelle, MAX(t.valeur) as tarif_journalier FROM tarifs t
        JOIN rubriques r ON t.rubrique_id = r.id
        WHERE r.module='FOURRIERE' AND t.actif=1 AND t.libelle NOT LIKE '%remorquage%'
        GROUP BY t.libelle
        ORDER BY t.libelle
    ''').fetchall()
    deposants = conn.execute("SELECT * FROM fou_parametres WHERE categorie='deposant' ORDER BY ordre").fetchall()
    etats_vh  = conn.execute("SELECT * FROM fou_parametres WHERE categorie='etat_vehicule' ORDER BY ordre").fetchall()
    motifs    = conn.execute("SELECT * FROM fou_parametres WHERE categorie='motif' ORDER BY ordre").fetchall()
    conn.close()
    return render_template('fourriere/fou_parametres.html',
                           user=user, types_vh=types_vh,
                           deposants=deposants, etats_vh=etats_vh, motifs=motifs)


# ════════════════════════════════════════════════════════════
#  API — Tarif par type (pour le formulaire d'ajout)
# ════════════════════════════════════════════════════════════
@bp.route('/fourriere/api/tarif/<code>')
@login_required
def fou_api_tarif(code):
    conn = get_db()
    row = conn.execute('''
        SELECT t.valeur as tarif_journalier, t.libelle FROM tarifs t
        JOIN rubriques r ON t.rubrique_id = r.id
        WHERE r.module='FOURRIERE' AND t.libelle=? AND t.actif=1
    ''', (code,)).fetchone()
    conn.close()
    if row:
        return jsonify({'tarif': row['tarif_journalier'], 'libelle': row['libelle']})
    return jsonify({'tarif': 0, 'libelle': ''})
