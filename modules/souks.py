"""modules/souks.py — Blueprint Affermage Souks Communaux
- Redevance MENSUELLE stockée dans redevance_mensuelle
- Renouvellement automatique avec taux_augmentation% à chaque période
- Upload de documents, avis de non-paiement, encaissement régisseur
"""
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from database import get_db
from modules.helpers import login_required, get_current_user, gen_num, get_next_seq_num, permission_required

bp = Blueprint('sou', __name__)

ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx', 'xls', 'xlsx'}


# ─────────────────────────────────────────────────────────────────
#  HELPERS MÉTIER
# ─────────────────────────────────────────────────────────────────

def _calculer_periodes_renouvellement(date_debut_str, redevance_mens_initiale,
                                      duree_contrat_ans, taux_aug_pct):
    """Calcule toutes les périodes depuis date_debut jusqu'à aujourd'hui."""
    try:
        d_debut = datetime.strptime(date_debut_str[:10], '%Y-%m-%d').date()
    except Exception:
        return []

    aujourd_hui = date.today()
    duree = max(1, int(duree_contrat_ans or 1))
    taux = float(taux_aug_pct or 5.0) / 100.0
    redevance = round(float(redevance_mens_initiale or 0), 2)

    periodes = []
    num_r = 0
    d_start = d_debut

    while d_start <= aujourd_hui:
        d_end = d_start + relativedelta(years=duree) - relativedelta(days=1)
        periodes.append({
            'renouvellement': num_r,
            'date_debut': d_start,
            'date_fin': d_end,
            'redevance_mensuelle': redevance,
        })
        d_start = d_end + relativedelta(days=1)
        redevance = round(redevance * (1 + taux), 2)
        num_r += 1

    return periodes


def _get_redevance_pour_mois(periodes, mois_date):
    """Retourne la redevance mensuelle applicable pour un mois donné."""
    for p in periodes:
        if p['date_debut'] <= mois_date <= p['date_fin']:
            return p['redevance_mensuelle']
    return periodes[-1]['redevance_mensuelle'] if periodes else 0.0


def _calculer_mois_non_payes_sou(aff_id, date_debut_str, date_fin_str,
                                  redevance_mens_initiale, duree_contrat_ans,
                                  taux_aug_pct):
    """Calcule la liste des mois non payés avec leur redevance historique."""
    try:
        date_debut = datetime.strptime(date_debut_str[:10], '%Y-%m-%d').date()
    except Exception:
        return []

    aujourd_hui = date.today()
    if date_fin_str:
        try:
            date_fin = min(datetime.strptime(date_fin_str[:10], '%Y-%m-%d').date(), aujourd_hui)
        except Exception:
            date_fin = aujourd_hui
    else:
        date_fin = aujourd_hui

    conn = get_db()
    payes_rows = conn.execute(
        "SELECT notes FROM declarations WHERE module='AFFERMAGE_SOUKS'"
        " AND reference_id=? AND statut='paye'", (aff_id,)
    ).fetchall()
    conn.close()

    import re as _re
    PATTERN = _re.compile(r'^\d{4}-\d{2}$')
    mois_payes = set()
    for row in payes_rows:
        if row['notes']:
            for m in row['notes'].split('|')[0].split(','):
                m = m.strip()
                if m and PATTERN.match(m):
                    mois_payes.add(m)

    periodes = _calculer_periodes_renouvellement(
        date_debut_str, redevance_mens_initiale, duree_contrat_ans, taux_aug_pct
    )

    MOIS_FR = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
               'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

    mois_non_payes = []
    courant = date(date_debut.year, date_debut.month, 1)
    fin_iter = date(date_fin.year, date_fin.month, 1)

    while courant <= fin_iter:
        key = courant.strftime('%Y-%m')
        if key not in mois_payes:
            rev = _get_redevance_pour_mois(periodes, courant)
            num_r = next(
                (p['renouvellement'] for p in periodes
                 if p['date_debut'] <= courant <= p['date_fin']), 0
            )
            mois_non_payes.append({
                'mois': key,
                'label': f"{MOIS_FR[courant.month - 1]} {courant.year}",
                'redevance': rev,
                'renouvellement': num_r,
            })
        courant = courant + relativedelta(months=1)

    return mois_non_payes


def _grouper_mois_par_periode(mois_list):
    """Groupe les mois non payés par période tarifaire."""
    if not mois_list:
        return []
    groupes = []
    current = None
    for m in mois_list:
        rev = m['redevance']
        if current is None or rev != current['redevance_mensuelle']:
            if current:
                groupes.append(current)
            current = {
                'renouvellement': m['renouvellement'],
                'redevance_mensuelle': rev,
                'nb_mois': 1,
                'montant': rev,
                'mois_debut': m['mois'],
                'mois_fin': m['mois'],
                'mois': [m['mois']],
            }
        else:
            current['nb_mois'] += 1
            current['montant'] = round(current['montant'] + rev, 2)
            current['mois_fin'] = m['mois']
            current['mois'].append(m['mois'])
    if current:
        groupes.append(current)
    return groupes


def _get_total_impaye(aff_id, date_debut, date_fin, rev_mens, duree, taux):
    mois = _calculer_mois_non_payes_sou(aff_id, date_debut, date_fin, rev_mens, duree, taux)
    return round(sum(m['redevance'] for m in mois), 2), len(mois)


# ─────────────────────────────────────────────────────────────────
#  ROUTES — LISTE
# ─────────────────────────────────────────────────────────────────

@bp.route('/souks')
@login_required
def sou_liste():
    user = get_current_user()
    conn = get_db()
    items = conn.execute(
        '''SELECT a.*, c.nom, c.prenom, c.raison_sociale, c.numero as ctb_num
           FROM affermages a JOIN contribuables c ON a.contribuable_id=c.id
           WHERE a.actif=1 ORDER BY a.date_creation DESC'''
    ).fetchall()
    contribuables = conn.execute(
        'SELECT id,numero,nom,prenom,raison_sociale,cin FROM contribuables WHERE actif=1'
    ).fetchall()
    next_numero = get_next_seq_num('affermages', 'numero', conn)
    conn.close()

    # Calcul total impayé pour chaque affermage
    items_data = []
    for item in items:
        rev = float(item['redevance_mensuelle'] or float(item['redevance_annuelle'] or 0) / 12)
        total_imp, nb_imp = _get_total_impaye(
            item['id'], item['date_debut'] or '', item['date_fin'] or '',
            rev, int(item['duree_contrat'] or 1), float(item['taux_augmentation'] or 5.0)
        )
        items_data.append({
            'item': item,
            'total_impaye': total_imp,
            'nb_mois_impaye': nb_imp,
            'rev_mens': rev,
        })

    return render_template('souks/sou_liste.html',
                           user=user, items=items, items_data=items_data,
                           contribuables=contribuables, next_numero=next_numero)


# ─────────────────────────────────────────────────────────────────
#  ROUTES — CRUD
# ─────────────────────────────────────────────────────────────────

@bp.route('/souks/ajouter', methods=['POST'])
@login_required
@permission_required('ajouter', 'sou')
def sou_ajouter():
    f = request.form
    conn = get_db()
    num = f.get('numero', '').strip() or get_next_seq_num('affermages', 'numero', conn)

    duree = int(f.get('duree_contrat', 1) or 1)
    rev_mens = round(float(f.get('redevance_mensuelle', 0) or 0), 2)
    taux_aug = round(float(f.get('taux_augmentation', 5.0) or 5.0), 2)
    date_debut_str = f.get('date_debut', '')

    date_fin_str = None
    if date_debut_str:
        try:
            d = datetime.strptime(date_debut_str[:10], '%Y-%m-%d').date()
            date_fin_str = (d + relativedelta(years=duree) - relativedelta(days=1)).isoformat()
        except Exception:
            pass

    conn.execute(
        '''INSERT INTO affermages
           (numero, contribuable_id, commune_id, nom_souk, num_emplacement,
            type_activite, redevance_mensuelle, redevance_annuelle,
            date_debut, date_fin, duree_contrat, taux_augmentation)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (num, f['contribuable_id'], 1,
         f.get('nom_souk', ''), f.get('num_emplacement', ''),
         f.get('type_activite', ''),
         rev_mens, round(rev_mens * 12, 2),
         date_debut_str, date_fin_str, duree, taux_aug)
    )
    conn.commit()
    conn.close()
    flash(f'Affermage N° {num} ajouté ✅', 'success')
    return redirect(url_for('sou.sou_liste'))


@bp.route('/souks/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('modifier', 'sou')
def sou_modifier(id):
    f = request.form
    duree = int(f.get('duree_contrat', 1) or 1)
    rev_mens = round(float(f.get('redevance_mensuelle', 0) or 0), 2)
    taux_aug = round(float(f.get('taux_augmentation', 5.0) or 5.0), 2)
    date_debut_str = f.get('date_debut', '')
    date_fin_str = f.get('date_fin', '') or None
    if date_debut_str and not date_fin_str:
        try:
            d = datetime.strptime(date_debut_str[:10], '%Y-%m-%d').date()
            date_fin_str = (d + relativedelta(years=duree) - relativedelta(days=1)).isoformat()
        except Exception:
            pass
    conn = get_db()
    conn.execute(
        '''UPDATE affermages SET
           nom_souk=?, num_emplacement=?, type_activite=?,
           redevance_mensuelle=?, redevance_annuelle=?,
           date_debut=?, date_fin=?, duree_contrat=?, taux_augmentation=?, statut=?
           WHERE id=?''',
        (f.get('nom_souk', ''), f.get('num_emplacement', ''), f.get('type_activite', ''),
         rev_mens, round(rev_mens * 12, 2),
         date_debut_str, date_fin_str, duree, taux_aug,
         f.get('statut', 'actif'), id)
    )
    conn.commit()
    conn.close()
    flash('Affermage modifié ✅', 'success')
    redirect_to = request.form.get('redirect_to', 'paiement')
    if redirect_to == 'detail':
        return redirect(url_for('sou.sou_detail', id=id))
    return redirect(url_for('sou.sou_paiement', id=id))


@bp.route('/souks/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('supprimer', 'sou')
def sou_supprimer(id):
    conn = get_db()
    conn.execute("UPDATE affermages SET actif=0 WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash('Affermage archivé ✅', 'success')
    return redirect(url_for('sou.sou_liste'))


# ─────────────────────────────────────────────────────────────────
#  ROUTES — CONTRAT (renouveler / terminer)
# ─────────────────────────────────────────────────────────────────

@bp.route('/souks/<int:id>/renouveler', methods=['POST'])
@login_required
@permission_required('modifier', 'sou')
def sou_renouveler(id):
    conn = get_db()
    aff = conn.execute('SELECT * FROM affermages WHERE id=?', (id,)).fetchone()
    if not aff:
        flash('Affermage introuvable', 'danger')
        conn.close()
        return redirect(url_for('sou.sou_liste'))

    taux = float(aff['taux_augmentation'] or 5.0) / 100.0
    duree = int(aff['duree_contrat'] or 1)
    rev_mens = float(aff['redevance_mensuelle'] or 0)

    periodes = _calculer_periodes_renouvellement(aff['date_debut'] or '', rev_mens, duree, aff['taux_augmentation'] or 5.0)
    if periodes:
        derniere = periodes[-1]
        nouvelle_rev = round(derniere['redevance_mensuelle'] * (1 + taux), 2)
        nouvelle_date_debut = derniere['date_fin'] + relativedelta(days=1)
    else:
        nouvelle_rev = round(rev_mens * (1 + taux), 2)
        nouvelle_date_debut = date.today()

    nouvelle_date_fin = nouvelle_date_debut + relativedelta(years=duree) - relativedelta(days=1)

    conn.execute(
        "UPDATE affermages SET redevance_mensuelle=?, redevance_annuelle=?, date_debut=?, date_fin=?, statut='actif' WHERE id=?",
        (nouvelle_rev, round(nouvelle_rev * 12, 2),
         nouvelle_date_debut.isoformat(), nouvelle_date_fin.isoformat(), id)
    )
    conn.commit()
    conn.close()
    flash(
        f'✅ Contrat renouvelé — {nouvelle_date_debut} → {nouvelle_date_fin}'
        f' — Redevance : {nouvelle_rev:.2f} DH/mois (+{aff["taux_augmentation"]}%)',
        'success'
    )
    return redirect(url_for('sou.sou_paiement', id=id))


@bp.route('/souks/<int:id>/terminer', methods=['POST'])
@login_required
@permission_required('modifier', 'sou')
def sou_terminer(id):
    date_resil = request.form.get('date_resiliation', date.today().isoformat())
    motif = request.form.get('motif_resiliation', '')
    conn = get_db()
    conn.execute("UPDATE affermages SET statut='resilie', date_fin=? WHERE id=?", (date_resil, id))
    conn.commit()
    conn.close()
    flash(f'Contrat résilié le {date_resil}. {motif}', 'warning')
    return redirect(url_for('sou.sou_paiement', id=id))


# ─────────────────────────────────────────────────────────────────
#  ROUTES — DOCUMENTS
# ─────────────────────────────────────────────────────────────────

@bp.route('/souks/<int:id>/upload-doc', methods=['POST'])
@login_required
@permission_required('modifier', 'sou')
def sou_upload_doc(id):
    user = get_current_user()
    f = request.files.get('fichier')
    type_doc = request.form.get('type_doc', 'contrat')
    if not f or not f.filename:
        flash('Aucun fichier sélectionné', 'warning')
        return redirect(url_for('sou.sou_detail', id=id))
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        flash(f'Type .{ext} non autorisé. Acceptés : {", ".join(ALLOWED_EXTENSIONS)}', 'danger')
        return redirect(url_for('sou.sou_detail', id=id))
    upload_dir = os.path.join('uploads', 'souks', str(id))
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(f"{type_doc}_{date.today().isoformat()}_{f.filename}")
    filepath = os.path.join(upload_dir, filename)
    f.save(filepath)
    conn = get_db()
    conn.execute(
        'INSERT INTO affermage_docs (affermage_id, nom_fichier, chemin, type_doc, agent_id) VALUES (?,?,?,?,?)',
        (id, f.filename, filepath, type_doc, user['id'] if user else None)
    )
    conn.commit()
    conn.close()
    flash(f'Document "{f.filename}" uploadé ✅', 'success')
    return redirect(url_for('sou.sou_detail', id=id))


@bp.route('/souks/<int:id>/telecharger-doc/<int:doc_id>')
@login_required
def sou_telecharger_doc(id, doc_id):
    conn = get_db()
    doc = conn.execute('SELECT * FROM affermage_docs WHERE id=?', (doc_id,)).fetchone()
    conn.close()
    if not doc or not os.path.exists(doc['chemin']):
        flash('Fichier introuvable', 'danger')
        return redirect(url_for('sou.sou_detail', id=id))
    return send_file(doc['chemin'], as_attachment=True, download_name=doc['nom_fichier'])


@bp.route('/souks/<int:id>/supprimer-doc/<int:doc_id>', methods=['POST'])
@login_required
@permission_required('modifier', 'sou')
def sou_supprimer_doc(id, doc_id):
    conn = get_db()
    doc = conn.execute('SELECT * FROM affermage_docs WHERE id=?', (doc_id,)).fetchone()
    if doc:
        try:
            if os.path.exists(doc['chemin']):
                os.remove(doc['chemin'])
        except Exception:
            pass
        conn.execute('DELETE FROM affermage_docs WHERE id=?', (doc_id,))
        conn.commit()
        flash('Document supprimé', 'success')
    conn.close()
    return redirect(url_for('sou.sou_detail', id=id))


# ─────────────────────────────────────────────────────────────────
#  ROUTES — AVIS DE NON-PAIEMENT
# ─────────────────────────────────────────────────────────────────

@bp.route('/souks/<int:id>/creer-avis', methods=['POST'])
@login_required
@permission_required('creer_bulletin')
def sou_creer_avis(id):
    conn = get_db()
    aff = conn.execute(
        'SELECT a.*, c.id as ctb_id FROM affermages a JOIN contribuables c ON a.contribuable_id=c.id WHERE a.id=?',
        (id,)
    ).fetchone()
    if not aff:
        conn.close()
        flash('Affermage introuvable', 'danger')
        return redirect(url_for('sou.sou_liste'))

    rev_mens = float(aff['redevance_mensuelle'] or 0)
    duree = int(aff['duree_contrat'] or 1)
    taux = float(aff['taux_augmentation'] or 5.0)
    mois_non_payes = _calculer_mois_non_payes_sou(
        id, aff['date_debut'] or '', aff['date_fin'] or '', rev_mens, duree, taux
    )
    total = round(sum(m['redevance'] for m in mois_non_payes), 2)

    if total == 0:
        flash('Aucun montant impayé — avis non créé', 'info')
        conn.close()
        return redirect(url_for('sou.sou_detail', id=id))

    annee = date.today().year
    today_str = date.today().isoformat()
    mois_str = ', '.join(m['mois'] for m in mois_non_payes)

    num_decl = gen_num('SOU-AV', 'declarations')
    conn.execute(
        '''INSERT INTO declarations
           (numero, module, reference_id, contribuable_id, commune_id,
            annee, base_calcul, taux, montant_principal, penalite_retard,
            majoration, amende_non_declaration, montant_total,
            statut, date_declaration, date_echeance, notes)
           VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?)''',
        (num_decl, 'AFFERMAGE_SOUKS', id, aff['ctb_id'], 1,
         annee, rev_mens, 0, total, 0, 0, 0, total,
         'emis', today_str,
         (date.today() + relativedelta(days=30)).isoformat(),
         mois_str)
    )
    decl_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    num_avis = gen_num('AV-SOU', 'avis_non_paiement')
    conn.execute(
        '''INSERT INTO avis_non_paiement
           (numero_avis, declaration_id, contribuable_id, commune_id,
            montant_du, date_emission, delai_jours, statut)
           VALUES (?,?,?,?,?,?,?,?)''',
        (num_avis, decl_id, aff['ctb_id'], 1, total, today_str, 30, 'emis')
    )
    conn.commit()
    conn.close()
    flash(f'Avis {num_avis} créé ✅ — Montant dû : {total:.2f} DH', 'success')
    return redirect(url_for('sou.sou_detail', id=id))


# ─────────────────────────────────────────────────────────────────
#  ROUTES — PAIEMENT
# ─────────────────────────────────────────────────────────────────

@bp.route('/souks/<int:id>/paiement', methods=['GET'])
@login_required
def sou_paiement(id):
    user = get_current_user()
    conn = get_db()
    aff = conn.execute(
        '''SELECT a.*, c.nom, c.prenom, c.raison_sociale,
                  c.id as ctb_id, c.numero as ctb_num
           FROM affermages a JOIN contribuables c ON a.contribuable_id=c.id
           WHERE a.id=?''', (id,)
    ).fetchone()
    if not aff:
        flash('Affermage introuvable', 'danger')
        return redirect(url_for('sou.sou_liste'))

    historique = conn.execute(
        '''SELECT d.*, b.numero_bulletin, b.statut as bull_statut
           FROM declarations d LEFT JOIN bulletins b ON b.declaration_id=d.id
           WHERE d.module='AFFERMAGE_SOUKS' AND d.reference_id=?
           ORDER BY d.date_creation DESC''', (id,)
    ).fetchall()

    avis_list = conn.execute(
        '''SELECT a.id, a.numero_avis, a.montant_du, a.date_emission, a.statut, d.annee
           FROM avis_non_paiement a JOIN declarations d ON a.declaration_id=d.id
           WHERE d.module='AFFERMAGE_SOUKS' AND d.reference_id=?
           ORDER BY a.date_emission DESC''', (id,)
    ).fetchall()

    params = conn.execute(
        "SELECT * FROM parametres_calcul WHERE module='AFFERMAGE_SOUKS' ORDER BY code"
    ).fetchall()
    conn.close()

    rev_mens_initiale = float(aff['redevance_mensuelle'] or float(aff['redevance_annuelle'] or 0) / 12)
    duree_contrat = int(aff['duree_contrat'] or 1)
    taux_aug = float(aff['taux_augmentation'] or 5.0)

    periodes = _calculer_periodes_renouvellement(aff['date_debut'] or '', rev_mens_initiale, duree_contrat, taux_aug)
    mois_non_payes = _calculer_mois_non_payes_sou(
        id, aff['date_debut'] or '', aff['date_fin'] or '', rev_mens_initiale, duree_contrat, taux_aug
    )
    nb_mois = len(mois_non_payes)
    total_du = round(sum(m['redevance'] for m in mois_non_payes), 2)
    groupes = _grouper_mois_par_periode(mois_non_payes)

    redevance_actuelle = _get_redevance_pour_mois(
        periodes, date(date.today().year, date.today().month, 1)
    ) if periodes else rev_mens_initiale

    date_fin_theorique = None
    if aff['date_debut']:
        try:
            d = datetime.strptime(aff['date_debut'][:10], '%Y-%m-%d').date()
            date_fin_theorique = (d + relativedelta(years=duree_contrat) - relativedelta(days=1)).isoformat()
        except Exception:
            pass

    prochaine_periode = None
    if periodes:
        derniere = periodes[-1]
        next_rev = round(derniere['redevance_mensuelle'] * (1 + taux_aug / 100), 2)
        next_debut = derniere['date_fin'] + relativedelta(days=1)
        next_fin = next_debut + relativedelta(years=duree_contrat) - relativedelta(days=1)
        prochaine_periode = {'redevance_mensuelle': next_rev, 'date_debut': next_debut, 'date_fin': next_fin}

    return render_template(
        'souks/sou_paiement.html',
        user=user, aff=aff, ref_id=id,
        rev_mens_initiale=rev_mens_initiale,
        redevance_actuelle=redevance_actuelle,
        duree_contrat=duree_contrat,
        taux_aug=taux_aug,
        periodes=periodes,
        prochaine_periode=prochaine_periode,
        mois_non_payes=mois_non_payes,
        nb_mois=nb_mois,
        total_du=total_du,
        groupes=groupes,
        historique=historique,
        avis_list=avis_list,
        params=params,
        date_fin_theorique=date_fin_theorique,
        today=date.today().isoformat()
    )


@bp.route('/souks/<int:id>/payer', methods=['POST'])
@login_required
@permission_required('creer_bulletin')
def sou_payer(id):
    """Enregistre une déclaration en 'emis' et un bulletin 'en_attente'.
    L'agent saisit le numéro de bulletin de versement; le régisseur valide dans /paiements."""
    user = get_current_user()
    f = request.form
    conn = get_db()
    aff = conn.execute(
        'SELECT a.*, c.id as ctb_id FROM affermages a JOIN contribuables c ON a.contribuable_id=c.id WHERE a.id=?',
        (id,)
    ).fetchone()
    if not aff:
        flash('Affermage introuvable', 'danger')
        conn.close()
        return redirect(url_for('sou.sou_liste'))

    mois_selectionnes = f.getlist('mois_selectionnes')
    mode_paiement = f.get('mode_paiement', 'especes')
    numero_bulletin = f.get('numero_bulletin', '').strip()
    numero_versement = f.get('numero_versement', '').strip()
    notes_extra = f.get('notes', '')

    if not mois_selectionnes:
        flash('Veuillez sélectionner au moins un mois', 'warning')
        conn.close()
        return redirect(url_for('sou.sou_paiement', id=id))

    if not numero_bulletin:
        flash('Le N° de bulletin est obligatoire', 'danger')
        conn.close()
        return redirect(url_for('sou.sou_paiement', id=id))

    # Vérification : bulletin unique
    existing_bull = conn.execute('SELECT id FROM bulletins WHERE numero_bulletin=?', (numero_bulletin,)).fetchone()
    if existing_bull:
        flash(f'⚠️ Le bulletin n° {numero_bulletin} existe déjà. Utilisez un autre numéro.', 'danger')
        conn.close()
        return redirect(url_for('sou.sou_paiement', id=id))

    rev_mens = float(aff['redevance_mensuelle'] or float(aff['redevance_annuelle'] or 0) / 12)
    duree_contrat = int(aff['duree_contrat'] or 1)
    taux_aug = float(aff['taux_augmentation'] or 5.0)
    periodes = _calculer_periodes_renouvellement(aff['date_debut'] or '', rev_mens, duree_contrat, taux_aug)
    mois_non_payes = _calculer_mois_non_payes_sou(
        id, aff['date_debut'] or '', aff['date_fin'] or '', rev_mens, duree_contrat, taux_aug
    )
    # Vérification côté serveur : ordre chronologique obligatoire
    keys_non_payes = [m['mois'] for m in mois_non_payes]
    selectionnes_tries = sorted(mois_selectionnes)
    expected_prefix = keys_non_payes[:len(selectionnes_tries)]
    if selectionnes_tries != expected_prefix:
        flash(
            "⚠️ Vous devez payer les mois dans l'ordre chronologique. "
            f"Commencez par : {expected_prefix[0] if expected_prefix else ''}",
            'danger'
        )
        conn.close()
        return redirect(url_for('sou.sou_paiement', id=id))

    rev_mens = float(aff['redevance_mensuelle'] or float(aff['redevance_annuelle'] or 0) / 12)
    duree_contrat = int(aff['duree_contrat'] or 1)
    taux_aug = float(aff['taux_augmentation'] or 5.0)
    periodes = _calculer_periodes_renouvellement(aff['date_debut'] or '', rev_mens, duree_contrat, taux_aug)

    montant_total = 0.0
    for mois_key in mois_selectionnes:
        try:
            mois_date = datetime.strptime(mois_key + '-01', '%Y-%m-%d').date()
        except Exception:
            continue
        montant_total += _get_redevance_pour_mois(periodes, mois_date)
    montant_total = round(montant_total, 2)

    nb_mois = len(mois_selectionnes)
    mois_str = ', '.join(sorted(mois_selectionnes))
    annee = int(sorted(mois_selectionnes)[-1][:4])
    today_str = date.today().isoformat()

    # Déclaration en statut 'emis'
    numero_decl = gen_num('SOU-DECL', 'declarations')
    conn.execute(
        '''INSERT INTO declarations
           (numero, module, reference_id, contribuable_id, commune_id,
            annee, base_calcul, taux, montant_principal, penalite_retard,
            majoration, amende_non_declaration, montant_total,
            statut, date_declaration, date_echeance, agent_id, notes)
           VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?,?)''',
        (numero_decl, 'AFFERMAGE_SOUKS', id, aff['ctb_id'], 1,
         annee, rev_mens, 0, montant_total, 0, 0, 0, montant_total,
         'emis', today_str, today_str, user['id'] if user else None,
         mois_str + (f' | {notes_extra}' if notes_extra else ''))
    )
    decl_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    # Bulletin avec le numéro saisi manuellement par l'agent
    conn.execute(
        '''INSERT INTO bulletins
           (numero_bulletin, declaration_id, contribuable_id, commune_id,
            montant, mode_paiement, date_paiement, statut, agent_id,
            numero_versement, notes)
           VALUES (?,?,?,?, ?,?,?,?,?, ?,?)''',
        (numero_bulletin, decl_id, aff['ctb_id'], 1,
         montant_total, mode_paiement, today_str, 'en_attente',
         user['id'] if user else None,
         numero_versement or None,
         f"Souk {aff['nom_souk']} — {nb_mois} mois: {mois_str}")
    )
    conn.commit()
    conn.close()
    flash(
        f'✅ Bulletin n° {numero_bulletin} créé — {nb_mois} mois — {montant_total:.2f} DH'
        f' — En attente de validation régisseur (/paiements)',
        'success'
    )
    return redirect(url_for('sou.sou_paiement', id=id))


@bp.route('/souks/bulletin/<int:bull_id>/encaisser', methods=['POST'])
@login_required
@permission_required('valider_paiement')
def sou_encaisser(bull_id):
    """Le régisseur encaisse le bulletin avec numéro de versement."""
    user = get_current_user()
    num_versement = request.form.get('numero_versement', '').strip()
    ref_id = request.form.get('ref_id', '0')
    if not num_versement:
        flash('Numéro de versement obligatoire', 'warning')
        return redirect(url_for('sou.sou_detail', id=ref_id))
    conn = get_db()
    conn.execute(
        "UPDATE bulletins SET statut='encaisse', numero_versement=?, date_encaissement=?, regisseur_id=? WHERE id=?",
        (num_versement, date.today().isoformat(), user['id'] if user else None, bull_id)
    )
    conn.commit()
    conn.close()
    flash(f'Bulletin encaissé ✅ — Versement n° {num_versement}', 'success')
    return redirect(url_for('sou.sou_detail', id=ref_id))


# ─────────────────────────────────────────────────────────────────
#  ROUTE — DETAIL
# ─────────────────────────────────────────────────────────────────

@bp.route('/souks/<int:id>/detail')
@login_required
def sou_detail(id):
    user = get_current_user()
    conn = get_db()
    item = conn.execute(
        '''SELECT a.*, c.nom, c.prenom, c.raison_sociale, c.telephone,
                  c.id as ctb_id, c.numero as ctb_num, c.adresse, c.cin, c.ice
           FROM affermages a JOIN contribuables c ON a.contribuable_id=c.id
           WHERE a.id=?''', (id,)
    ).fetchone()
    if not item:
        flash('Affermage introuvable', 'danger')
        conn.close()
        return redirect(url_for('sou.sou_liste'))

    historique_paiements = conn.execute(
        '''SELECT d.*, b.id as bull_id, b.numero_bulletin, b.statut as bull_statut,
                  b.numero_versement, b.date_encaissement, b.date_creation as bull_date, b.montant as bull_montant
           FROM declarations d
           LEFT JOIN bulletins b ON b.declaration_id=d.id
           WHERE d.module='AFFERMAGE_SOUKS' AND d.reference_id=?
           ORDER BY d.date_creation DESC''', (id,)
    ).fetchall()

    documents = conn.execute(
        'SELECT * FROM affermage_docs WHERE affermage_id=? ORDER BY date_upload DESC', (id,)
    ).fetchall()

    avis_list = conn.execute(
        '''SELECT an.*, d.annee FROM avis_non_paiement an
           JOIN declarations d ON an.declaration_id=d.id
           WHERE d.module='AFFERMAGE_SOUKS' AND d.reference_id=?
           ORDER BY an.date_emission DESC''', (id,)
    ).fetchall()
    conn.close()

    rev_mens = float(item['redevance_mensuelle'] or float(item['redevance_annuelle'] or 0) / 12)
    duree_contrat = int(item['duree_contrat'] or 1)
    taux_aug = float(item['taux_augmentation'] or 5.0)
    periodes = _calculer_periodes_renouvellement(item['date_debut'] or '', rev_mens, duree_contrat, taux_aug)
    mois_non_payes = _calculer_mois_non_payes_sou(
        id, item['date_debut'] or '', item['date_fin'] or '', rev_mens, duree_contrat, taux_aug
    )
    total_impaye = round(sum(m['redevance'] for m in mois_non_payes), 2)
    nb_mois_impaye = len(mois_non_payes)
    redevance_actuelle = _get_redevance_pour_mois(
        periodes, date(date.today().year, date.today().month, 1)
    ) if periodes else rev_mens
    groupes_impaye = _grouper_mois_par_periode(mois_non_payes)

    # Totaux paiements
    total_encaisse = sum(
        float(h['bull_montant'] or 0)
        for h in historique_paiements
        if h['bull_statut'] in ('valide', 'encaisse')
    )

    return render_template(
        'souks/sou_detail.html',
        user=user, item=item, ref_id=id,
        rev_mens=rev_mens,
        redevance_actuelle=redevance_actuelle,
        periodes=periodes,
        nb_mois_impaye=nb_mois_impaye,
        total_impaye=total_impaye,
        groupes_impaye=groupes_impaye,
        total_encaisse=total_encaisse,
        historique_paiements=historique_paiements,
        documents=documents,
        avis_list=avis_list,
        today=date.today().isoformat()
    )


# ─────────────────────────────────────────────────────────────────
#  AVIS DE NON-PAIEMENT — Page imprimable officielle (style TNB)
# ─────────────────────────────────────────────────────────────────

@bp.route('/souks/<int:id>/avis-non-paiement')
@login_required
def sou_avis_non_paiement(id):
    conn = get_db()
    aff = conn.execute(
        """SELECT a.*, c.nom, c.prenom, c.raison_sociale, c.cin,
                  c.telephone, c.adresse as ctb_adresse, c.rc,
                  c.id as ctb_id, c.numero as ctb_num
           FROM affermages a JOIN contribuables c ON a.contribuable_id=c.id
           WHERE a.id=?""", (id,)
    ).fetchone()
    if not aff:
        flash('Affermage introuvable', 'danger')
        conn.close()
        return redirect(url_for('sou.sou_liste'))
    commune_row = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    conn.close()
    commune_dict = dict(commune_row) if commune_row else {}
    commune = commune_dict.get('nom', '')
    province = commune_dict.get('province', '')
    rev_mens = float(aff['redevance_mensuelle'] or float(aff['redevance_annuelle'] or 0) / 12)
    duree = int(aff['duree_contrat'] or 1)
    taux = float(aff['taux_augmentation'] or 5.0)
    periodes = _calculer_periodes_renouvellement(aff['date_debut'] or '', rev_mens, duree, taux)
    mois_non_payes = _calculer_mois_non_payes_sou(
        id, aff['date_debut'] or '', aff['date_fin'] or '', rev_mens, duree, taux
    )
    total_montant = round(sum(m['redevance'] for m in mois_non_payes), 2)
    groupes = _grouper_mois_par_periode(mois_non_payes)
    today_str = date.today().isoformat()
    conn2 = get_db()
    n_avis = conn2.execute("SELECT COUNT(*) as c FROM avis_non_paiement").fetchone()['c'] + 1
    conn2.close()
    avis_num = f"{n_avis}/{date.today().year}"
    return render_template(
        'souks/sou_avis_non_paiement.html',
        aff=aff, groupes=groupes, mois_non_payes=mois_non_payes,
        total_montant=total_montant,
        commune=commune, province=province,
        commune_ar=commune_dict.get('nom_ar', ''),
        province_ar=commune_dict.get('province_ar', ''),
        region_ar=commune_dict.get('region_ar', ''),
        today=today_str, avis_num=avis_num,
        date_limite=f"{date.today().year}-12-31",
        periodes=periodes
    )
