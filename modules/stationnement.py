"""modules/stationnement.py — Blueprint Stationnement TPV & Taxe TPV
═══════════════════════════════════════════════════════════════════
Paiement TRIMESTRIEL — Deux taxes combinées par véhicule :
  • Taxe Transport Public des Voyageurs (TPV) → tarif fixe/4 + pénalités de retard + majoration
  • Droit de Stationnement               → tarif fixe/4 + PAS de pénalités
Les deux tarifs sont configurés dans l'arrêté fiscal (tables tarifs).
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime, date
from database import get_db
from modules.helpers import (login_required, get_current_user,
                              get_tarifs_module, get_param, calculer_penalites, get_next_seq_num, permission_required)

bp = Blueprint('sta', __name__)

# ── Trimestres ────────────────────────────────────────────────────────────────
TRIMESTRES   = {1: 'T1 (Jan–Mar)', 2: 'T2 (Avr–Jun)',
                3: 'T3 (Jul–Sép)', 4: 'T4 (Oct–Déc)'}
# Date limite = 1er du mois suivant la fin de chaque trimestre
# T1 fin Mars  → 1er Avril
# T2 fin Juin  → 1er Juillet
# T3 fin Sept  → 1er Octobre
# T4 fin Déc   → 1er Janvier (n+1)
DEADLINE_TRIM = {1: (4, 1), 2: (7, 1), 3: (10, 1), 4: (1, 1)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def trimestres_non_payes_sta(vehicule_id: int, debut: int = 2020) -> list[dict]:
    """Retourne les trimestres non payés (module STATIONNEMENT) depuis debut."""
    conn = get_db()
    payes = {(r['annee'], r['trimestre']) for r in conn.execute(
        "SELECT annee, trimestre FROM declarations "
        "WHERE module='STATIONNEMENT' AND reference_id=? AND statut NOT IN ('annule')",
        (vehicule_id,)).fetchall()}
    conn.close()
    today = date.today()
    result = []
    for y in range(debut, today.year + 1):
        for t in range(1, 5):
            if (y, t) in payes:
                continue
            mois, jour = DEADLINE_TRIM[t]
            # T4 : mois=1 → 1er Janvier de l'année SUIVANTE
            ech_year = y + 1 if t == 4 else y
            try:
                ech = date(ech_year, mois, jour)
            except ValueError:
                ech = date(ech_year, mois, 28)
            if ech > today:
                continue   # pas encore échu
            result.append({
                'annee': y, 'trimestre': t,
                'label': TRIMESTRES[t],
                'echeance': ech.isoformat(),
                'en_retard': today.isoformat() > ech.isoformat()
            })
    return result


def _tarif_pour_type(type_vehicule: str, tarifs: list) -> float:
    """Cherche le tarif annuel correspondant au type du véhicule (insensible à la casse)."""
    tv = type_vehicule.strip().lower()
    for t in tarifs:
        if t['libelle'].strip().lower() == tv:
            return float(t['valeur'])
    # Fallback : premier tarif
    return float(tarifs[0]['valeur']) if tarifs else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# LISTE
# ═══════════════════════════════════════════════════════════════════════════════
@bp.route('/stationnement')
@login_required
def sta_liste():
    user = get_current_user()
    conn = get_db()
    q = request.args.get('q', '')
    sql = '''SELECT v.*, c.nom, c.prenom, c.raison_sociale, c.numero as ctb_num, c.cin
             FROM vehicules v JOIN contribuables c ON v.contribuable_id=c.id
             WHERE v.actif=1'''
    params = []
    if q:
        sql += ' AND (v.immatriculation LIKE ? OR c.nom LIKE ? OR v.numero LIKE ? OR c.cin LIKE ?)'
        params = [f'%{q}%'] * 4
    items_raw = conn.execute(sql + ' ORDER BY v.date_creation DESC', params).fetchall()
    items = []
    for veh in items_raw:
        item = dict(veh)
        non_payes = trimestres_non_payes_sta(veh['id'], 2020)
        item['nb_non_paye']      = len(non_payes)
        item['annees_non_payees'] = sorted({t['annee'] for t in non_payes})
        items.append(item)
    contribuables = conn.execute(
        'SELECT id,numero,nom,prenom,raison_sociale,cin,rc,telephone FROM contribuables WHERE actif=1'
    ).fetchall()
    tarifs_sta = get_tarifs_module('STATIONNEMENT')
    next_numero = get_next_seq_num('vehicules', 'numero', conn)
    conn.close()
    return render_template('stationnement/sta_liste.html', user=user, items=items,
                           contribuables=contribuables, tarifs=tarifs_sta, q=q, next_numero=next_numero)


# ═══════════════════════════════════════════════════════════════════════════════
# AJOUTER
# ═══════════════════════════════════════════════════════════════════════════════
@bp.route('/stationnement/ajouter', methods=['POST'])
@login_required
@permission_required('ajouter', 'sta')
def sta_ajouter():
    f = request.form
    conn = get_db()
    num = f.get('numero', '').strip() or get_next_seq_num('vehicules', 'numero', conn)
    conn.execute(
        '''INSERT INTO vehicules
           (numero,contribuable_id,commune_id,immatriculation,type_vehicule,
            num_autorisation,date_autorisation,nombre_sieges)
           VALUES (?,?,?,?,?,?,?,?)''',
        (num, f['contribuable_id'], f.get('commune_id', 1),
         f.get('immatriculation', ''), f.get('type_vehicule', 'taxi'),
         f.get('num_autorisation', ''), f.get('date_autorisation', ''),
         f.get('nombre_sieges', 0)))
    conn.commit(); conn.close()
    flash(f'Véhicule N° {num} enregistré ✅', 'success')
    return redirect(url_for('sta.sta_liste'))


# ═══════════════════════════════════════════════════════════════════════════════
# DETAIL
# ═══════════════════════════════════════════════════════════════════════════════
@bp.route('/stationnement/<int:id>')
@login_required
def sta_detail(id):
    user = get_current_user()
    conn = get_db()
    veh = conn.execute(
        '''SELECT v.*, c.nom, c.prenom, c.raison_sociale, c.cin, c.telephone,
                  c.id as ctb_id, c.numero as ctb_num
           FROM vehicules v JOIN contribuables c ON v.contribuable_id=c.id
           WHERE v.id=?''', (id,)).fetchone()
    declarations = conn.execute(
        '''SELECT d.*, b.statut as bull_statut, b.numero_bulletin,
                  b.numero_quittance, b.date_quittance
           FROM declarations d LEFT JOIN bulletins b ON b.declaration_id=d.id
           WHERE d.module='STATIONNEMENT' AND d.reference_id=?
           ORDER BY d.annee DESC, d.trimestre DESC''', (id,)).fetchall()
    tarifs_sta = get_tarifs_module('STATIONNEMENT')
    non_payes  = trimestres_non_payes_sta(id, 2020)
    conn.close()
    return render_template('stationnement/sta_detail.html', user=user, vehicule=veh,
                           declarations=declarations,
                           annees_manquantes=sorted({t['annee'] for t in non_payes}),
                           tarifs=tarifs_sta, today=date.today().isoformat(),
                           TRIMESTRES=TRIMESTRES)


# ═══════════════════════════════════════════════════════════════════════════════
# MODIFIER
# ═══════════════════════════════════════════════════════════════════════════════
@bp.route('/stationnement/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('modifier', 'sta')
def sta_modifier(id):
    f = request.form
    conn = get_db()
    conn.execute(
        '''UPDATE vehicules
           SET immatriculation=?,type_vehicule=?,num_autorisation=?,
               nombre_sieges=?,statut=?
           WHERE id=?''',
        (f.get('immatriculation'), f.get('type_vehicule'),
         f.get('num_autorisation'), f.get('nombre_sieges', 0),
         f.get('statut', 'actif'), id))
    conn.commit(); conn.close()
    flash('Véhicule modifié ✅', 'success')
    return redirect(url_for('sta.sta_detail', id=id))


# ═══════════════════════════════════════════════════════════════════════════════
# PAIEMENT — affichage
# ═══════════════════════════════════════════════════════════════════════════════
@bp.route('/stationnement/<int:id>/paiement')
@login_required
def sta_paiement(id):
    user = get_current_user()
    conn = get_db()
    veh = conn.execute(
        '''SELECT v.*, c.nom, c.prenom, c.raison_sociale, c.id as ctb_id,
                  c.adresse as ctb_adresse, c.cin, c.rc, c.telephone, c.email
           FROM vehicules v JOIN contribuables c ON v.contribuable_id=c.id
           WHERE v.id=?''', (id,)).fetchone()
    if not veh:
        flash('Véhicule introuvable', 'danger')
        return redirect(url_for('sta.sta_liste'))

    declarations = conn.execute(
        '''SELECT d.*, b.statut as bull_statut, b.id as bull_id,
                  b.numero_bulletin,
                  b.numero_quittance as bull_quittance,
                  b.date_quittance  as bull_date_quittance
           FROM declarations d LEFT JOIN bulletins b ON b.declaration_id=d.id
           WHERE d.module='STATIONNEMENT' AND d.reference_id=?
           ORDER BY d.annee DESC, d.trimestre DESC''', (id,)).fetchall()

    tarifs_sta = get_tarifs_module('STATIONNEMENT')
    tarifs_tpv = get_tarifs_module('TRANSPORT_VOYAGEURS')

    # Tarifs TRIMESTRIELS directs depuis l'arrêté fiscal (déjà en DH/trimestre)
    tarif_sta_trim = round(_tarif_pour_type(veh['type_vehicule'], tarifs_sta), 2)
    tarif_tpv_trim = round(_tarif_pour_type(veh['type_vehicule'], tarifs_tpv), 2)
    tarif_sta_an   = round(tarif_sta_trim * 4, 2)  # affiché uniquement
    tarif_tpv_an   = round(tarif_tpv_trim * 4, 2)  # affiché uniquement

    non_payes = trimestres_non_payes_sta(id, 2020)

    # Grouper par année
    from collections import defaultdict
    by_year: dict = defaultdict(list)
    for t in non_payes:
        by_year[t['annee']].append(t)
    non_payes_by_year = dict(sorted(by_year.items()))

    commune_row = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    conn.close()

    return render_template('stationnement/sta_paiement.html',
                           user=user, vehicule=veh,
                           declarations=declarations,
                           non_payes_by_year=non_payes_by_year,
                           tarifs_sta=tarifs_sta, tarifs_tpv=tarifs_tpv,
                           tarif_sta_trim=tarif_sta_trim,
                           tarif_tpv_trim=tarif_tpv_trim,
                           tarif_sta_an=tarif_sta_an,
                           tarif_tpv_an=tarif_tpv_an,
                           today=date.today().isoformat(),
                           commune=commune_row['nom'] if commune_row else '',
                           TRIMESTRES=TRIMESTRES)


# ═══════════════════════════════════════════════════════════════════════════════
# SOUMETTRE PAIEMENT TRIMESTRIEL
# ═══════════════════════════════════════════════════════════════════════════════
@bp.route('/stationnement/<int:id>/payer', methods=['POST'])
@login_required
@permission_required('creer_bulletin')
def sta_payer(id):
    user = get_current_user()
    f    = request.form
    conn = get_db()

    veh = conn.execute('SELECT * FROM vehicules WHERE id=?', (id,)).fetchone()
    if not veh:
        conn.close()
        return redirect(url_for('sta.sta_liste'))

    contrib_id  = veh['contribuable_id']
    date_paie   = f.get('date_paiement', date.today().isoformat())
    num_bulletin = f.get('numero_bulletin', '').strip()

    tarifs_sta = get_tarifs_module('STATIONNEMENT')
    tarifs_tpv = get_tarifs_module('TRANSPORT_VOYAGEURS')
    # Tarifs déjà en DH/trimestre dans l'arrêté fiscal
    tarif_sta_trim = round(_tarif_pour_type(veh['type_vehicule'], tarifs_sta), 2)
    tarif_tpv_trim = round(_tarif_pour_type(veh['type_vehicule'], tarifs_tpv), 2)

    # Tri chronologique : anciens trimestres d'abord
    trims_selectionnes = sorted(f.getlist('trims'))

    n_dcl = conn.execute("SELECT COUNT(*) as c FROM declarations").fetchone()['c'] + 1
    decls_creees   = 0
    total_global   = 0.0
    bulletins_crees = []

    for trim_key in trims_selectionnes:
        try:
            annee_str, trim_str = trim_key.split('_')
            annee = int(annee_str); trim = int(trim_str)
        except ValueError:
            continue

        # Doublon ?
        existing = conn.execute(
            'SELECT id FROM declarations '
            'WHERE module="STATIONNEMENT" AND reference_id=? AND annee=? AND trimestre=? AND statut!="annule"',
            (id, annee, trim)).fetchone()
        if existing:
            flash(f'⚠️ T{trim}-{annee} déjà enregistré — ignoré', 'warn')
            continue

        mois, jour = DEADLINE_TRIM[trim]
        # T4 : mois=1 → 1er Janvier de l'année SUIVANTE
        ech_year = annee + 1 if trim == 4 else annee
        try:
            ech = date(ech_year, mois, jour).isoformat()
        except ValueError:
            ech = date(ech_year, mois, 28).isoformat()

        # ── Taxe TPV : avec pénalités de retard + majoration ──────────────
        pen_tpv, maj_tpv = 0.0, 0.0
        if tarif_tpv_trim > 0 and date_paie > ech:
            pen_tpv, maj_tpv = calculer_penalites(
                tarif_tpv_trim, ech, date_paie, 'TRANSPORT_VOYAGEURS')

        # ── Droit de Stationnement : AUCUNE pénalité ──────────────────────
        # (tarif_sta_trim sans modification)

        # ── Totaux ────────────────────────────────────────────────────────
        principal = round(tarif_tpv_trim + tarif_sta_trim, 2)
        total     = round(principal + pen_tpv + maj_tpv, 2)
        total_global += total
        statut_decl   = 'sous_seuil' if total < 200 else 'emis'
        num           = f"DCL-STA{datetime.now().year}{n_dcl:05d}"
        n_dcl        += 1

        # Stockage :
        #   base_calcul  = tarif TPV trimestriel
        #   taux         = tarif STA trimestriel  (champ repurposé, valeur numérique)
        #   montant_principal = STA + TPV (base combinée)
        #   penalite_retard   = pénalité sur TPV seulement
        #   majoration        = majoration sur TPV seulement
        #   amende_non_declaration = 0 (aucune amende pour ce module)
        cur = conn.execute(
            '''INSERT INTO declarations
               (numero,module,reference_id,contribuable_id,commune_id,annee,trimestre,
                base_calcul,taux,montant_principal,
                penalite_retard,majoration,amende_non_declaration,
                montant_total,statut,date_declaration,date_echeance,agent_id)
               VALUES (?,?,?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?)''',
            (num, 'STATIONNEMENT', id, contrib_id, 1, annee, trim,
             tarif_tpv_trim, tarif_sta_trim, principal,
             pen_tpv, maj_tpv, 0,
             total, statut_decl, date_paie, ech, user['id']))
        decl_id     = cur.lastrowid
        decls_creees += 1

        # Bulletin BV
        if num_bulletin and statut_decl == 'emis':
            try:
                conn.execute(
                    '''INSERT INTO bulletins
                       (numero_bulletin,declaration_id,contribuable_id,
                        commune_id,montant,mode_paiement,date_paiement,agent_id,statut)
                       VALUES (?,?,?,?,?,?,?,?,?)''',
                    (num_bulletin, decl_id, contrib_id, 1, total,
                     'bulletin_manuel', date_paie, user['id'], 'en_attente'))
                bulletins_crees.append(trim_key)
            except Exception as e:
                flash(f'⚠️ Bulletin T{trim}/{annee} non créé : {e}', 'warn')

    if num_bulletin and decls_creees > 0 and not bulletins_crees:
        flash('ℹ️ Total inférieur à 200 DH — aucun bulletin créé (sous seuil)', 'info')

    conn.commit(); conn.close()
    flash(
        f'✅ {decls_creees} trimestre(s) enregistré(s) — Total : {total_global:.2f} DH'
        + (f' — {len(bulletins_crees)} bulletin(s) en attente.' if bulletins_crees else '.'),
        'success')
    return redirect(url_for('sta.sta_paiement', id=id))


# ═══════════════════════════════════════════════════════════════════════════════
# AVIS DE NON-PAIEMENT
# ═══════════════════════════════════════════════════════════════════════════════
@bp.route('/stationnement/<int:id>/avis-non-paiement')
@login_required
def sta_avis(id):
    conn = get_db()
    veh = conn.execute(
        '''SELECT v.*, c.nom, c.prenom, c.raison_sociale, c.cin, c.rc,
                  c.adresse as ctb_adresse, c.telephone, c.email
           FROM vehicules v JOIN contribuables c ON v.contribuable_id=c.id
           WHERE v.id=?''', (id,)).fetchone()
    commune_row = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    tarifs_sta  = get_tarifs_module('STATIONNEMENT')
    tarifs_tpv  = get_tarifs_module('TRANSPORT_VOYAGEURS')
    conn.close()

    non_payes      = trimestres_non_payes_sta(id, 2020)
    tarif_sta_trim = round(_tarif_pour_type(veh['type_vehicule'], tarifs_sta) / 4, 2)
    tarif_tpv_trim = round(_tarif_pour_type(veh['type_vehicule'], tarifs_tpv) / 4, 2)
    commune_dict = dict(commune_row) if commune_row else {}
    commune  = commune_dict.get('nom', '')
    province = commune_dict.get('province', '')
    n_avis   = f"{id:03d}/{date.today().year}"

    return render_template('stationnement/sta_avis.html',
                           vehicule=veh, non_payes=non_payes,
                           tarif_sta_trim=tarif_sta_trim,
                           tarif_tpv_trim=tarif_tpv_trim,
                           commune=commune, province=province,
                           commune_ar=commune_dict.get('nom_ar', ''),
                           province_ar=commune_dict.get('province_ar', ''),
                           region_ar=commune_dict.get('region_ar', ''),
                           today=date.today().isoformat(), n_avis=n_avis,
                           TRIMESTRES=TRIMESTRES)


# ═══════════════════════════════════════════════════════════
# SUPPRIMER UN VÉHICULE (archivage logique)
# ═══════════════════════════════════════════════════════════
@bp.route('/stationnement/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('supprimer', 'sta')
def sta_supprimer(id):
    user = get_current_user()
    if not user['peut_supprimer']:
        flash('❌ Droits insuffisants pour supprimer un dossier.', 'danger')
        return redirect(url_for('sta.sta_detail', id=id))
    conn = get_db()
    nb_payes = conn.execute(
        "SELECT COUNT(*) as c FROM declarations WHERE module='STATIONNEMENT' AND reference_id=? AND statut='paye'",
        (id,)
    ).fetchone()['c']
    if nb_payes > 0:
        flash(f'⚠️ Impossible de supprimer : {nb_payes} déclaration(s) payée(s) liée(s) à ce véhicule.', 'warning')
        conn.close()
        return redirect(url_for('sta.sta_detail', id=id))
    conn.execute('UPDATE vehicules SET actif=0 WHERE id=?', (id,))
    conn.commit(); conn.close()
    flash('✅ Véhicule archivé et retiré de la liste.', 'success')
    return redirect(url_for('sta.sta_liste'))
