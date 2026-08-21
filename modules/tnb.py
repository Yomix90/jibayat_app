"""modules/tnb.py — Blueprint TNB v3 — 1 Dossier par Redevable"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, session, jsonify, send_from_directory)
from datetime import datetime, date
from database import get_db
from modules.helpers import (login_required, get_current_user, annees_non_payees,
                              get_tarifs_module, get_param, calculer_penalites, gen_num,
                              majore_centimes)
import os, uuid

bp = Blueprint('tnb', __name__)

UPLOAD_FOLDER = os.path.join('uploads', 'tnb_docs')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx', 'zip'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Helpers calcul ───────────────────────────────────────────
def _calcul_exoneration(permis_list, annee):
    for p in permis_list:
        if p['type_permis'] == 'construction' and p['annee_fin_exoneration']:
            if (p['annee_debut_exoneration'] or 0) <= annee <= p['annee_fin_exoneration']:
                return True
    return False


def _get_or_create_dossier(conn, contribuable_id):
    """Retourne (dossier_id, numero_dossier) pour ce contribuable, le cree si absent."""
    row = conn.execute(
        'SELECT id, numero_dossier FROM dossiers_tnb WHERE contribuable_id=?',
        (contribuable_id,)
    ).fetchone()
    if row:
        return row['id'], row['numero_dossier']
    max_n = conn.execute(
        'SELECT COALESCE(MAX(numero_dossier),0) FROM dossiers_tnb'
    ).fetchone()[0]
    next_n = max_n + 1
    cur = conn.execute(
        'INSERT INTO dossiers_tnb (numero_dossier, contribuable_id) VALUES (?,?)',
        (next_n, contribuable_id)
    )
    conn.commit()
    return cur.lastrowid, next_n


def _check_permis_alerts(conn):
    today = date.today()
    alerts = []
    rows = conn.execute('''
        SELECT p.annee_fin_exoneration, dt.numero_dossier,
               t.id as terrain_id, t.adresse,
               c.nom, c.prenom, c.raison_sociale
        FROM permis p
        JOIN terrains t ON t.id = p.terrain_id
        JOIN contribuables c ON c.id = t.contribuable_id
        LEFT JOIN dossiers_tnb dt ON dt.contribuable_id = t.contribuable_id
        WHERE p.type_permis="construction" AND p.annee_fin_exoneration IS NOT NULL
          AND t.actif=1 AND t.archive=0
    ''').fetchall()
    for r in rows:
        fin_annee = r['annee_fin_exoneration']
        try:
            delta = (date(fin_annee, 12, 31) - today).days
            if 0 <= delta <= 60:
                alerts.append({
                    'terrain_id':     r['terrain_id'],
                    'numero_dossier': r['numero_dossier'],
                    'adresse':        r['adresse'],
                    'proprietaire':   r['nom'] + ' ' + (r['prenom'] or r['raison_sociale'] or ''),
                    'annee_fin':      fin_annee,
                    'jours_restants': delta,
                })
        except Exception:
            pass
    return alerts


def _calcul_annees_redevables(terrain_id, date_acquisition, permis_list, conn):
    current_year = datetime.now().year
    debut = 2020
    if date_acquisition:
        try:
            debut = max(2020, int(str(date_acquisition)[:4]))
        except Exception:
            pass
    all_decls = conn.execute(
        "SELECT annee FROM declarations WHERE module='TNB' AND reference_id=? AND statut='paye'",
        (terrain_id,)
    ).fetchall()
    paid_years = {d['annee'] for d in all_decls}
    return [
        y for y in range(debut, current_year + 1)
        if y not in paid_years and not _calcul_exoneration(permis_list, y)
    ]


def _compute_tarifs_annee(all_tarifs, zone, sup, annee, amende_pct, today_str=None):
    if today_str is None:
        today_str = date.today().isoformat()
    taux, principal = 0.0, 0.0
    for t in all_tarifs:
        if str(t['date_debut']) <= f"{annee}-12-31":
            if not t['date_fin'] or str(t['date_fin']) >= f"{annee}-01-01":
                s_min = float(t['surface_min'] or 0)
                s_max = float(t['surface_max']) if t['surface_max'] is not None else float('inf')
                if s_min <= sup <= s_max:
                    taux = float(t['valeur'])
                    val = taux if t['unite'] == 'DH' else sup * taux
                    principal = majore_centimes(val)
                    break
    d_ech = date(annee, 2, 28).isoformat()
    pen = maj = amende = 0.0
    if principal > 0 and today_str > d_ech:
        amende = max(majore_centimes(principal * amende_pct / 100), 500)
        pen, maj = calculer_penalites(principal, d_ech, today_str, 'TNB')
    total = majore_centimes(principal + pen + maj + amende)
    return {'taux': taux, 'principal': principal, 'penalite': pen,
            'majoration': maj, 'amende': amende,
            'total': total}


# ═══════════════════════════════════════════════════════════════
#  LISTE TNB — 1 Dossier par Redevable (via dossiers_tnb)
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb')
@login_required
def tnb_liste():
    user = get_current_user()
    conn = get_db()
    q             = request.args.get('q', '')
    statut_f      = request.args.get('statut', '')
    zone_f        = request.args.get('zone', '')
    lotissement_f = request.args.get('lotissement', '')

    # Source : dossiers_tnb (1 par contribuable)
    dossiers_raw = conn.execute('''
        SELECT dt.id as dossier_id, dt.numero_dossier,
               c.id as contribuable_id, c.numero as ctb_num,
               c.nom, c.prenom, c.raison_sociale, c.cin, c.rc,
               c.telephone, c.email, c.adresse as ctb_adresse
        FROM dossiers_tnb dt
        JOIN contribuables c ON c.id = dt.contribuable_id
        WHERE dt.archive=0 AND c.actif=1
        ORDER BY dt.numero_dossier ASC
    ''').fetchall()

    # Tous les terrains actifs
    terrains_raw = conn.execute(
        'SELECT * FROM terrains WHERE actif=1 AND archive=0 ORDER BY id ASC'
    ).fetchall()

    # Grouper par contribuable_id
    ter_by_ctb = {}
    for t in terrains_raw:
        ter_by_ctb.setdefault(t['contribuable_id'], []).append(dict(t))

    # Tarifs & permis
    all_tarifs = conn.execute(
        """SELECT t.code_tarif, t.libelle, t.valeur, t.unite, t.surface_min, t.surface_max,
                  t.date_debut, t.date_fin
           FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
           WHERE r.module='TNB' AND t.actif=1 ORDER BY t.date_debut DESC"""
    ).fetchall()
    amende_pct  = get_param('TNB', 'AMENDE_NON_DECLARATION', 15)
    all_permis  = conn.execute(
        "SELECT * FROM permis WHERE type_permis='construction' AND annee_fin_exoneration IS NOT NULL"
    ).fetchall()
    permis_map  = {}
    for p in all_permis:
        permis_map.setdefault(p['terrain_id'], []).append(p)
    today_str = date.today().isoformat()

    # Calcul impayé par terrain
    for ctb_id, ter_list in ter_by_ctb.items():
        for t in ter_list:
            plist  = permis_map.get(t['id'], [])
            annees = _calcul_annees_redevables(t['id'], t['date_acquisition'], plist, conn)
            t['nb_non_paye'] = len(annees)
            zone_t = str(t['zone'] or 'A')
            sup_t  = float(t['superficie'] or 0.0)
            tot    = 0.0
            for y in annees:
                r = _compute_tarifs_annee(all_tarifs, zone_t, sup_t, y, amende_pct, today_str)
                tot += r['total']
            t['total_non_paye'] = majore_centimes(tot)

    # Filtrage recherche textuelle
    q_low = q.lower() if q else ''

    dossiers = []
    for d_row in dossiers_raw:
        ctb_id      = d_row['contribuable_id']
        ter_list    = ter_by_ctb.get(ctb_id, [])
        total_imp   = majore_centimes(sum(t['total_non_paye'] for t in ter_list))
        nb_impaye   = sum(1 for t in ter_list if t['nb_non_paye'] > 0)

        # Filtres
        if statut_f == 'impaye' and nb_impaye == 0:
            continue
        if statut_f == 'ajour' and nb_impaye > 0:
            continue
        if zone_f and not any(t['zone'] == zone_f for t in ter_list):
            continue
        if lotissement_f and not any(
            (t.get('lotissement') or '').lower() == lotissement_f.lower() for t in ter_list
        ):
            continue
        if q_low:
            bloc = (
                (d_row['nom'] or '') + ' ' + (d_row['prenom'] or '') + ' ' +
                (d_row['raison_sociale'] or '') + ' ' + (d_row['cin'] or '') + ' ' +
                (d_row['rc'] or '') + ' ' + str(d_row['numero_dossier']) + ' ' +
                ' '.join(
                    (t.get('titre_foncier') or '') + ' ' + (t.get('num_parcelle') or '') +
                    ' ' + (t.get('lotissement') or '') + ' ' + (t.get('adresse') or '')
                    for t in ter_list
                )
            ).lower()
            if q_low not in bloc:
                continue

        dossiers.append({
            'dossier_id':      d_row['dossier_id'],
            'numero_dossier':  d_row['numero_dossier'],
            'contribuable_id': ctb_id,
            'nom':             d_row['nom'],
            'prenom':          d_row['prenom'] or '',
            'raison_sociale':  d_row['raison_sociale'] or '',
            'cin':             d_row['cin'],
            'rc':              d_row['rc'],
            'telephone':       d_row['telephone'] or '',
            'email':           d_row['email'] or '',
            'ctb_adresse':     d_row['ctb_adresse'] or '',
            'ctb_num':         d_row['ctb_num'],
            'terrains':        ter_list,
            'nb_terrains':     len(ter_list),
            'total_impaye':    total_imp,
            'nb_avec_impaye':  nb_impaye,
        })

    dossiers.sort(key=lambda d: (0 if d['nb_avec_impaye'] > 0 else 1, d['numero_dossier']))

    contribuables = conn.execute(
        'SELECT id,numero,nom,prenom,raison_sociale,cin,rc,telephone,email,adresse '
        'FROM contribuables WHERE actif=1'
    ).fetchall()
    tarifs       = get_tarifs_module('TNB')
    zones        = sorted(set(t['zone']        for t in terrains_raw if t['zone']))
    lotissements = sorted(set(t['lotissement'] for t in terrains_raw if t['lotissement']))
    alerts       = _check_permis_alerts(conn)
    conn.close()

    return render_template('tnb/tnb_liste.html',
        user=user, dossiers=dossiers, items=list(terrains_raw),
        contribuables=contribuables, tarifs=tarifs,
        q=q, zones=zones, lotissements=lotissements,
        zone_f=zone_f, statut_f=statut_f, lotissement_f=lotissement_f,
        alerts=alerts)


# ═══════════════════════════════════════════════════════════════
#  AJOUTER TERRAIN — auto-assigne au dossier du contribuable
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/ajouter', methods=['POST'])
@login_required
def tnb_ajouter():
    conn   = get_db()
    f      = request.form
    ctb_id = int(f['contribuable_id'])
    # Obtenir ou créer le dossier du contribuable
    _did, _num_dossier = _get_or_create_dossier(conn, ctb_id)
    # Numéro terrain interne unique
    n_ter = (conn.execute(
        'SELECT COUNT(*) as c FROM terrains WHERE contribuable_id=?', (ctb_id,)
    ).fetchone()['c'] or 0) + 1
    num = f"TER{datetime.now().year}{ctb_id:04d}-{n_ter:03d}"
    conn.execute('''INSERT INTO terrains
        (numero_terrain, contribuable_id, commune_id,
         adresse, adresse_ar, quartier, lotissement, arrondissement,
         superficie, zone, titre_foncier, num_parcelle, statut, date_acquisition)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (num, ctb_id, f.get('commune_id', 1),
         f.get('adresse', ''), f.get('adresse_ar', ''), f.get('quartier', ''),
         f.get('lotissement', ''), f.get('arrondissement', ''),
         f.get('superficie', 0), f.get('zone', 'B'),
         f.get('titre_foncier', ''), f.get('num_parcelle', ''),
         f.get('statut', 'non_bati'), f.get('date_acquisition', '')))
    conn.commit()
    conn.close()
    flash(f'Terrain ajouté au Dossier N°{_num_dossier}', 'success')
    return redirect(url_for('tnb.tnb_liste'))


# ═══════════════════════════════════════════════════════════════
#  DETAIL TERRAIN
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>')
@login_required
def tnb_detail(id):
    user = get_current_user()
    conn = get_db()
    terrain = conn.execute('''SELECT t.*, c.nom, c.prenom, c.raison_sociale, c.cin,
        c.rc, c.telephone, c.adresse as ctb_adresse, c.numero as ctb_num, c.id as ctb_id
        FROM terrains t JOIN contribuables c ON t.contribuable_id=c.id WHERE t.id=?''',
        (id,)).fetchone()
    if not terrain:
        flash('Terrain introuvable', 'danger')
        return redirect(url_for('tnb.tnb_liste'))

    # Dossier du contribuable
    dossier = conn.execute(
        'SELECT * FROM dossiers_tnb WHERE contribuable_id=?',
        (terrain['ctb_id'],)
    ).fetchone()
    dossier_num = dossier['numero_dossier'] if dossier else '—'

    permis        = conn.execute(
        'SELECT * FROM permis WHERE terrain_id=? ORDER BY date_creation DESC', (id,)
    ).fetchall()
    declarations  = conn.execute('''SELECT d.*, b.statut as bull_statut, b.numero_bulletin
        FROM declarations d LEFT JOIN bulletins b ON b.declaration_id=d.id
        WHERE d.module="TNB" AND d.reference_id=? ORDER BY d.annee DESC''', (id,)).fetchall()
    transferts    = conn.execute('''SELECT tr.*, c1.nom as ancien_nom, c2.nom as nouveau_nom
        FROM transferts_terrain tr
        LEFT JOIN contribuables c1 ON tr.ancien_contribuable_id=c1.id
        LEFT JOIN contribuables c2 ON tr.nouveau_contribuable_id=c2.id
        WHERE tr.terrain_id=? ORDER BY tr.date_transfert DESC''', (id,)).fetchall()
    documents     = conn.execute(
        'SELECT * FROM tnb_documents WHERE terrain_id=? ORDER BY date_upload DESC', (id,)
    ).fetchall()
    contribuables = conn.execute(
        'SELECT id,numero,nom,prenom,raison_sociale FROM contribuables WHERE actif=1'
    ).fetchall()

    # Autres terrains du même dossier (= même contribuable)
    dossiers_groupe = conn.execute('''
        SELECT t.id, t.titre_foncier, t.num_parcelle,
               t.superficie, t.zone, t.adresse, t.statut, t.lotissement
        FROM terrains t
        WHERE t.contribuable_id=? AND t.id!=? AND t.actif=1 AND t.archive=0
        ORDER BY t.id
    ''', (terrain['ctb_id'], id)).fetchall()

    tarifs          = get_tarifs_module('TNB')
    annees_man      = annees_non_payees('TNB', id)
    permis_list     = [dict(p) for p in permis]
    alert_exo       = None
    for p in permis_list:
        if p['type_permis'] == 'construction' and p.get('annee_fin_exoneration'):
            try:
                delta = (date(p['annee_fin_exoneration'], 12, 31) - date.today()).days
                if 0 <= delta <= 60:
                    alert_exo = {'annee_fin': p['annee_fin_exoneration'], 'jours': delta}
            except Exception:
                pass

    # Co-propriétaires du terrain
    coproprietaires = conn.execute('''
        SELECT cp.*, c.nom, c.prenom, c.raison_sociale, c.cin, c.numero as ctb_num, c.telephone
        FROM terrain_coproprietaires cp
        JOIN contribuables c ON c.id = cp.contribuable_id
        WHERE cp.terrain_id=?
        ORDER BY cp.part_indivision DESC
    ''', (id,)).fetchall()

    conn.close()
    return render_template('tnb/tnb_detail.html',
        user=user, terrain=terrain, dossier_num=dossier_num,
        permis=permis, declarations=declarations,
        transferts=transferts, documents=documents,
        contribuables=contribuables, tarifs=tarifs,
        annees_manquantes=annees_man, today=date.today().isoformat(),
        dossiers_groupe=dossiers_groupe, alert_exo=alert_exo,
        coproprietaires=coproprietaires)



# ═══════════════════════════════════════════════════════════════
#  MODIFIER TERRAIN
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/modifier', methods=['POST'])
@login_required
def tnb_modifier(id):
    f = request.form
    conn = get_db()
    conn.execute('''UPDATE terrains SET adresse=?, adresse_ar=?, quartier=?, lotissement=?,
        arrondissement=?, superficie=?, zone=?, titre_foncier=?, num_parcelle=?,
        statut=?, date_acquisition=? WHERE id=?''',
        (f.get('adresse'), f.get('adresse_ar', ''), f.get('quartier', ''),
         f.get('lotissement', ''), f.get('arrondissement', ''),
         f.get('superficie', 0), f.get('zone'), f.get('titre_foncier'),
         f.get('num_parcelle'), f.get('statut'), f.get('date_acquisition'), id))
    conn.commit()
    conn.close()
    flash('Terrain modifié', 'success')
    return redirect(url_for('tnb.tnb_detail', id=id))


# ═══════════════════════════════════════════════════════════════
#  ARCHIVER TERRAIN / DOSSIER
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/archiver', methods=['POST'])
@login_required
def tnb_archiver(id):
    user = get_current_user()
    if not user['peut_supprimer']:
        flash('Droits insuffisants', 'danger')
        return redirect(url_for('tnb.tnb_detail', id=id))
    conn = get_db()
    conn.execute('UPDATE terrains SET archive=1 WHERE id=?', (id,))
    conn.commit()
    conn.close()
    flash('Dossier archivé', 'success')
    return redirect(url_for('tnb.tnb_liste'))


# ═══════════════════════════════════════════════════════════════
#  PERMIS DE CONSTRUCTION / HABITER
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/permis', methods=['POST'])
@login_required
def tnb_permis(id):
    f = request.form
    conn = get_db()
    type_permis  = f['type_permis']
    annee_debut  = None
    annee_fin    = None

    if type_permis == 'construction':
        date_aut = f.get('date_autorisation', '')
        if date_aut:
            try:
                annee_debut = int(date_aut[:4])
                annee_fin   = annee_debut + 2  # 3 ans inclus
            except Exception:
                pass
        conn.execute('UPDATE terrains SET statut="en_construction" WHERE id=?', (id,))

    elif type_permis == 'habiter':
        conn.execute('UPDATE terrains SET statut="construit" WHERE id=?', (id,))

    conn.execute('''INSERT INTO permis
        (terrain_id, type_permis, numero_permis, date_autorisation,
         statut, description, annee_debut_exoneration, annee_fin_exoneration)
        VALUES (?,?,?,?,?,?,?,?)''',
        (id, type_permis, f.get('numero_permis', ''), f.get('date_autorisation', ''),
         'en_cours', f.get('description', ''), annee_debut, annee_fin))
    conn.commit()
    conn.close()
    if type_permis == 'construction':
        flash(f'Permis enregistré — Exonération TNB {annee_debut}–{annee_fin} (3 ans). Statut: En construction.', 'success')
    elif type_permis == 'habiter':
        flash("Permis d'habiter enregistré — Terrain passé en Bâti.", 'success')
    else:
        flash('Permis enregistré', 'success')
    return redirect(url_for('tnb.tnb_detail', id=id))


# ═══════════════════════════════════════════════════════════════
#  TRANSFERT — le terrain rejoint le dossier du nouveau propriétaire
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/transfert', methods=['POST'])
@login_required
def tnb_transfert(id):
    f = request.form
    conn = get_db()
    terrain = conn.execute(
        'SELECT contribuable_id FROM terrains WHERE id=?', (id,)
    ).fetchone()
    if terrain:
        nouveau_ctb_id = int(f['nouveau_contribuable_id'])
        # S'assurer que le nouveau propriétaire a un dossier (créer si absent)
        _ndid, _nnum = _get_or_create_dossier(conn, nouveau_ctb_id)
        # Enregistrer le transfert
        conn.execute('''INSERT INTO transferts_terrain
            (terrain_id, ancien_contribuable_id, nouveau_contribuable_id,
             date_transfert, motif, acte_notarie, agent_id)
            VALUES (?,?,?,?,?,?,?)''',
            (id, terrain['contribuable_id'], nouveau_ctb_id,
             f.get('date_transfert', date.today().isoformat()),
             f.get('motif', ''), f.get('acte_notarie', ''), session['user_id']))
        # Changer le propriétaire du terrain
        conn.execute('UPDATE terrains SET contribuable_id=? WHERE id=?', (nouveau_ctb_id, id))
        conn.commit()
        flash(f'Transfert effectué — Terrain ajouté au Dossier N°{_nnum}', 'success')
    conn.close()
    return redirect(url_for('tnb.tnb_detail', id=id))


# ═══════════════════════════════════════════════════════════════
#  PAIEMENT ET DECLARATIONS
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/paiement')
@login_required
def tnb_paiement(id):
    user = get_current_user()
    conn = get_db()
    terrain = conn.execute('''SELECT t.*, c.nom, c.prenom, c.raison_sociale, c.id as ctb_id,
        c.adresse as ctb_adresse, c.cin, c.telephone, c.email
        FROM terrains t JOIN contribuables c ON t.contribuable_id=c.id WHERE t.id=?''',
        (id,)).fetchone()
    if not terrain:
        return redirect(url_for('tnb.tnb_liste'))

    # Dossier
    dossier = conn.execute(
        'SELECT numero_dossier FROM dossiers_tnb WHERE contribuable_id=?',
        (terrain['ctb_id'],)
    ).fetchone()
    dossier_num = dossier['numero_dossier'] if dossier else '—'

    declarations = conn.execute('''SELECT d.*, b.statut as bull_statut, b.id as bull_id,
        b.numero_bulletin, b.numero_quittance as bull_quittance,
        b.date_quittance as bull_date_quittance
        FROM declarations d LEFT JOIN bulletins b ON b.declaration_id=d.id
        WHERE d.module="TNB" AND d.reference_id=? ORDER BY d.annee DESC''', (id,)).fetchall()

    all_tarifs = conn.execute(
        """SELECT t.code_tarif, t.libelle, t.valeur, t.unite, t.surface_min, t.surface_max,
                  t.date_debut, t.date_fin
           FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
           WHERE r.module='TNB' ORDER BY t.date_debut DESC"""
    ).fetchall()
    amende_pct = get_param('TNB', 'AMENDE_NON_DECLARATION', 15)

    permis_list = [dict(p) for p in conn.execute(
        'SELECT * FROM permis WHERE terrain_id=? AND type_permis="construction"', (id,)
    ).fetchall()]

    annees_reb = _calcul_annees_redevables(id, terrain['date_acquisition'], permis_list, conn)
    zone = str(terrain['zone'] or 'A')
    sup  = float(terrain['superficie'] or 0.0)
    today_str = date.today().isoformat()

    annees_manquantes_details = []
    for y in annees_reb:
        r = _compute_tarifs_annee(all_tarifs, zone, sup, y, amende_pct, today_str)
        r['annee'] = y
        annees_manquantes_details.append(r)

    # Années exonérées
    debut = 2020
    if terrain['date_acquisition']:
        try:
            debut = max(2020, int(str(terrain['date_acquisition'])[:4]))
        except Exception:
            pass
    annees_exonerees = [
        y for y in range(debut, datetime.now().year + 1)
        if _calcul_exoneration(permis_list, y)
    ]

    # Autres terrains du même dossier (même contribuable)
    autres_terrains = []
    rows = conn.execute('''
        SELECT t.id, t.titre_foncier, t.num_parcelle,
               t.superficie, t.zone, t.adresse, t.lotissement, t.date_acquisition,
               (SELECT COUNT(*) FROM declarations d WHERE d.module="TNB"
                AND d.reference_id=t.id AND d.statut="paye") as nb_paye
        FROM terrains t
        WHERE t.contribuable_id=? AND t.id!=? AND t.actif=1 AND t.archive=0
        ORDER BY t.id
    ''', (terrain['ctb_id'], id)).fetchall()
    for r in rows:
        r = dict(r)
        p_list = [dict(p) for p in conn.execute(
            'SELECT * FROM permis WHERE terrain_id=? AND type_permis="construction"', (r['id'],)
        ).fetchall()]
        annees_imp = _calcul_annees_redevables(r['id'], r['date_acquisition'], p_list, conn)
        r['nb_impaye']    = len(annees_imp)
        zone_r = str(r['zone'] or 'A')
        sup_r  = float(r['superficie'] or 0.0)
        total_r = 0.0
        for yr in annees_imp:
            calc = _compute_tarifs_annee(all_tarifs, zone_r, sup_r, yr, amende_pct, today_str)
            total_r += calc['total']
        r['total_impaye'] = majore_centimes(total_r)
        autres_terrains.append(r)

    params_tnb = conn.execute(
        "SELECT * FROM parametres_calcul WHERE module='TNB' ORDER BY code"
    ).fetchall()
    tarifs = get_tarifs_module('TNB')
    conn.close()
    return render_template('tnb/tnb_paiement.html',
        user=user, terrain=terrain, dossier_num=dossier_num,
        declarations=declarations,
        annees_manquantes=annees_manquantes_details,
        annees_exonerees=annees_exonerees,
        tarifs=tarifs, params=params_tnb, today=today_str,
        autres_terrains=autres_terrains, permis_list=permis_list)


# ═══════════════════════════════════════════════════════════════
#  MULTI DECLARATIONS
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/multi_declarations', methods=['POST'])
@login_required
def tnb_multi_declarations(id):
    user = get_current_user()
    f = request.form
    annees = f.getlist('annees')
    if not annees:
        flash('Aucune année sélectionnée', 'warn')
        return redirect(url_for('tnb.tnb_paiement', id=id))

    contrib_id         = int(f['contribuable_id'])
    date_decl          = f.get('date_declaration', date.today().isoformat())
    num_bulletin_manuel = f.get('numero_bulletin', '').strip()

    conn = get_db()
    terrain = conn.execute(
        'SELECT superficie, zone, date_acquisition FROM terrains WHERE id=?', (id,)
    ).fetchone()
    if not terrain:
        conn.close()
        return redirect(url_for('tnb.tnb_liste'))

    permis_list = [dict(p) for p in conn.execute(
        'SELECT * FROM permis WHERE terrain_id=? AND type_permis="construction"', (id,)
    ).fetchall()]

    base = terrain['superficie'] or 0
    zone = terrain['zone'] or 'A'
    all_tarifs = conn.execute(
        """SELECT t.code_tarif, t.libelle, t.valeur, t.unite, t.surface_min, t.surface_max,
                  t.date_debut, t.date_fin
           FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
           WHERE r.module='TNB' ORDER BY t.date_debut DESC"""
    ).fetchall()
    amende_pct = get_param('TNB', 'AMENDE_NON_DECLARATION', 15)
    n_dcl = conn.execute("SELECT COUNT(*) as c FROM declarations").fetchone()['c'] + 1
    declarations_creees = 0
    last_decl_id = None

    for annee_str in annees:
        annee = int(annee_str)
        existing = conn.execute(
            'SELECT id FROM declarations WHERE module="TNB" AND reference_id=? AND annee=? AND statut!="annule"',
            (id, annee)
        ).fetchone()
        if existing:
            continue
        if _calcul_exoneration(permis_list, annee):
            continue
        d_ech = f"{annee}-02-28"
        r = _compute_tarifs_annee(all_tarifs, zone, float(base), annee, amende_pct, date_decl)
        total    = r['total']
        statut_d = 'sous_seuil' if total < 200 else 'emis'
        num = f"DCL{datetime.now().year}{n_dcl:05d}"
        n_dcl += 1
        cur = conn.execute('''INSERT INTO declarations
            (numero, module, reference_id, contribuable_id, commune_id, annee,
             base_calcul, taux, montant_principal, penalite_retard, majoration,
             amende_non_declaration, montant_total, statut,
             date_declaration, date_echeance, agent_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (num, 'TNB', id, contrib_id, 1, annee,
             base, r['taux'], r['principal'], r['penalite'], r['majoration'],
             r['amende'], total, statut_d, date_decl, d_ech, user['id']))
        last_decl_id = cur.lastrowid
        declarations_creees += 1

    if num_bulletin_manuel and last_decl_id:
        try:
            decl_last = conn.execute(
                'SELECT id, montant_total, contribuable_id FROM declarations WHERE id=?',
                (last_decl_id,)
            ).fetchone()
            if decl_last:
                conn.execute('''INSERT INTO bulletins
                    (numero_bulletin, declaration_id, contribuable_id, commune_id,
                     montant, mode_paiement, date_paiement, agent_id, statut)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (num_bulletin_manuel, decl_last['id'], decl_last['contribuable_id'],
                     1, decl_last['montant_total'], 'bulletin_manuel',
                     date_decl, user['id'], 'en_attente'))
        except Exception as e:
            flash(f'Bulletin non créé : {e}', 'warn')

    conn.commit()
    conn.close()
    flash(f'{declarations_creees} déclaration(s) générée(s)', 'success')
    return redirect(url_for('tnb.tnb_paiement', id=id))


# ═══════════════════════════════════════════════════════════════
#  PDF DECLARATION / AVIS
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/pdf_declaration/<int:annee>')
@login_required
def tnb_pdf_declaration(id, annee):
    conn = get_db()
    terrain = conn.execute('''SELECT t.*, c.nom, c.prenom, c.raison_sociale,
        c.adresse as ctb_adresse, c.cin, c.telephone, c.email
        FROM terrains t JOIN contribuables c ON t.contribuable_id=c.id WHERE t.id=?''',
        (id,)).fetchone()
    decl = conn.execute('''SELECT * FROM declarations
        WHERE module="TNB" AND reference_id=? AND annee=? AND statut!="annule"
        ORDER BY id DESC LIMIT 1''', (id, annee)).fetchone()
    commune_row = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    conn.close()
    commune_dict = dict(commune_row) if commune_row else {}
    return render_template('tnb/tnb_declaration_pdf.html',
        terrain=terrain, decl=decl, annee=annee,
        commune=commune_dict.get('nom', ''),
        province=commune_dict.get('province', ''),
        commune_ar=commune_dict.get('nom_ar', ''),
        region_ar=commune_dict.get('region_ar', ''),
        province_ar=commune_dict.get('province_ar', ''))


@bp.route('/tnb/<int:id>/avis_non_paiement')
@login_required
def tnb_avis_non_paiement(id):
    conn = get_db()
    terrain = conn.execute('''SELECT t.*, c.nom, c.prenom, c.raison_sociale,
        c.adresse as ctb_adresse, c.cin, c.rc, c.telephone, c.email
        FROM terrains t JOIN contribuables c ON t.contribuable_id=c.id WHERE t.id=?''',
        (id,)).fetchone()
    if not terrain:
        flash('Terrain introuvable', 'danger')
        return redirect(url_for('tnb.tnb_liste'))

    dossier = conn.execute(
        'SELECT numero_dossier FROM dossiers_tnb WHERE contribuable_id=?',
        (terrain['contribuable_id'],)
    ).fetchone()
    dossier_num = dossier['numero_dossier'] if dossier else '—'

    commune_row = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    all_tarifs  = conn.execute(
        """SELECT t.code_tarif, t.libelle, t.valeur, t.unite, t.surface_min, t.surface_max,
                  t.date_debut, t.date_fin
           FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
           WHERE r.module='TNB' ORDER BY t.date_debut DESC"""
    ).fetchall()
    amende_pct = get_param('TNB', 'AMENDE_NON_DECLARATION', 15)
    permis_list = [dict(p) for p in conn.execute(
        'SELECT * FROM permis WHERE terrain_id=? AND type_permis="construction"', (id,)
    ).fetchall()]
    annees_reb = _calcul_annees_redevables(id, terrain['date_acquisition'], permis_list, conn)
    zone = str(terrain['zone'] or 'A')
    sup  = float(terrain['superficie'] or 0.0)
    today_str = date.today().isoformat()
    annees_detail = []
    total_montant = 0.0
    for y in annees_reb:
        r = _compute_tarifs_annee(all_tarifs, zone, sup, y, amende_pct, today_str)
        r['annee'] = y
        total_montant += r['total']
        annees_detail.append(r)

    n_avis    = conn.execute("SELECT COUNT(*) as c FROM declarations WHERE module='TNB'").fetchone()['c'] + 1
    avis_num  = f"{n_avis}/{date.today().year}"
    commune_dict = dict(commune_row) if commune_row else {}
    commune   = commune_dict.get('nom', '')
    conn.close()
    return render_template('tnb/tnb_avis_non_paiement.html',
        terrain=terrain, annees_detail=annees_detail,
        total_montant=round(total_montant, 2), dossier_num=dossier_num,
        commune=commune, today=today_str, avis_num=avis_num,
        date_limite=f"{date.today().year}-03-31",
        commune_ar=commune_dict.get('nom_ar', ''),
        province_ar=commune_dict.get('province_ar', ''),
        region_ar=commune_dict.get('region_ar', ''))


# ═══════════════════════════════════════════════════════════════
#  AVIS PAR LOT
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/avis_lot', methods=['POST'])
@login_required
def tnb_avis_lot():
    terrain_ids = request.form.getlist('terrain_ids')
    if not terrain_ids:
        flash('Aucun terrain sélectionné', 'warn')
        return redirect(url_for('tnb.tnb_liste'))
    return redirect(url_for('tnb.tnb_avis_multiple', ids=','.join(terrain_ids)))


@bp.route('/tnb/avis_multiple')
@login_required
def tnb_avis_multiple():
    ids_str     = request.args.get('ids', '')
    terrain_ids = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
    conn        = get_db()
    all_tarifs  = conn.execute(
        """SELECT t.code_tarif, t.libelle, t.valeur, t.unite, t.surface_min, t.surface_max,
                  t.date_debut, t.date_fin
           FROM tarifs t JOIN rubriques r ON t.rubrique_id=r.id
           WHERE r.module='TNB' ORDER BY t.date_debut DESC"""
    ).fetchall()
    amende_pct  = get_param('TNB', 'AMENDE_NON_DECLARATION', 15)
    commune_row = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    commune_dict = dict(commune_row) if commune_row else {}
    commune     = commune_dict.get('nom', '')
    today_str   = date.today().isoformat()
    avis_list   = []
    for tid in terrain_ids:
        terrain = conn.execute('''SELECT t.*, c.nom, c.prenom, c.raison_sociale,
            c.adresse as ctb_adresse, c.cin, c.rc, c.telephone, c.email
            FROM terrains t JOIN contribuables c ON t.contribuable_id=c.id WHERE t.id=?''',
            (tid,)).fetchone()
        if not terrain:
            continue
        permis_list = [dict(p) for p in conn.execute(
            'SELECT * FROM permis WHERE terrain_id=? AND type_permis="construction"', (tid,)
        ).fetchall()]
        annees_reb = _calcul_annees_redevables(tid, terrain['date_acquisition'], permis_list, conn)
        if not annees_reb:
            continue
        zone = str(terrain['zone'] or 'A')
        sup  = float(terrain['superficie'] or 0.0)
        annees_detail = []
        total_montant = 0.0
        for y in annees_reb:
            r = _compute_tarifs_annee(all_tarifs, zone, sup, y, amende_pct, today_str)
            r['annee'] = y
            total_montant += r['total']
            annees_detail.append(r)
        avis_list.append({
            'terrain': dict(terrain), 'annees_detail': annees_detail,
            'total_montant': round(total_montant, 2),
            'avis_num': f"{len(avis_list)+1}/{date.today().year}"
        })
    conn.close()
    return render_template('tnb/tnb_avis_lot.html',
        avis_list=avis_list, commune=commune, today=today_str,
        date_limite=f"{date.today().year}-03-31",
        commune_ar=commune_dict.get('nom_ar', ''),
        province_ar=commune_dict.get('province_ar', ''),
        region_ar=commune_dict.get('region_ar', ''))


# ═══════════════════════════════════════════════════════════════
#  UPLOAD DOCUMENTS
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/upload_doc', methods=['POST'])
@login_required
def tnb_upload_doc(id):
    user = get_current_user()
    if 'fichier' not in request.files:
        flash('Aucun fichier sélectionné', 'danger')
        return redirect(url_for('tnb.tnb_detail', id=id))
    file = request.files['fichier']
    if file.filename == '' or not allowed_file(file.filename):
        flash('Fichier invalide ou type non autorisé', 'danger')
        return redirect(url_for('tnb.tnb_detail', id=id))
    ext         = file.filename.rsplit('.', 1)[1].lower()
    unique_name = f"tnb_{id}_{uuid.uuid4().hex[:8]}.{ext}"
    folder      = os.path.join(UPLOAD_FOLDER, str(id))
    os.makedirs(folder, exist_ok=True)
    save_path   = os.path.join(folder, unique_name)
    file.save(save_path)
    conn = get_db()
    conn.execute('''INSERT INTO tnb_documents
        (terrain_id, type_doc, nom_fichier, chemin, taille, date_upload, agent_id, notes)
        VALUES (?,?,?,?,?,?,?,?)''',
        (id, request.form.get('type_doc', 'autre'), file.filename,
         save_path, os.path.getsize(save_path), date.today().isoformat(),
         user['id'], request.form.get('notes', '')))
    conn.commit()
    conn.close()
    flash('Document téléversé avec succès', 'success')
    return redirect(url_for('tnb.tnb_detail', id=id))


@bp.route('/tnb/docs/<int:doc_id>/telecharger')
@login_required
def tnb_telecharger_doc(doc_id):
    conn = get_db()
    doc  = conn.execute('SELECT * FROM tnb_documents WHERE id=?', (doc_id,)).fetchone()
    conn.close()
    if not doc:
        flash('Document introuvable', 'danger')
        return redirect(url_for('tnb.tnb_liste'))
    return send_from_directory(os.path.dirname(doc['chemin']),
                               os.path.basename(doc['chemin']),
                               as_attachment=True, download_name=doc['nom_fichier'])


@bp.route('/tnb/docs/<int:doc_id>/supprimer', methods=['POST'])
@login_required
def tnb_supprimer_doc(doc_id):
    conn      = get_db()
    doc       = conn.execute('SELECT * FROM tnb_documents WHERE id=?', (doc_id,)).fetchone()
    terrain_id = doc['terrain_id'] if doc else None
    if doc:
        try:
            os.remove(doc['chemin'])
        except Exception:
            pass
        conn.execute('DELETE FROM tnb_documents WHERE id=?', (doc_id,))
        conn.commit()
        flash('Document supprimé', 'success')
    conn.close()
    return redirect(url_for('tnb.tnb_detail', id=terrain_id) if terrain_id else url_for('tnb.tnb_liste'))


# ═══════════════════════════════════════════════════════════════
#  SUPPRIMER TERRAIN
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/supprimer', methods=['POST'])
@login_required
def tnb_supprimer(id):
    user = get_current_user()
    if not user['peut_supprimer']:
        flash('Droits insuffisants', 'danger')
        return redirect(url_for('tnb.tnb_detail', id=id))
    conn   = get_db()
    nb_p   = conn.execute(
        "SELECT COUNT(*) as c FROM declarations WHERE module='TNB' AND reference_id=? AND statut='paye'",
        (id,)
    ).fetchone()['c']
    if nb_p > 0:
        flash(f'Impossible : {nb_p} déclaration(s) payée(s)', 'warning')
        conn.close()
        return redirect(url_for('tnb.tnb_detail', id=id))
    conn.execute('UPDATE terrains SET actif=0 WHERE id=?', (id,))
    conn.commit()
    conn.close()
    flash('Terrain supprimé', 'success')
    return redirect(url_for('tnb.tnb_liste'))


# ═══════════════════════════════════════════════════════════════
#  API — Groupes par dossier
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/api/groupes')
@login_required
def tnb_api_groupes():
    conn = get_db()
    rows = conn.execute('''
        SELECT dt.numero_dossier, c.cin, c.rc, c.nom, c.prenom, c.raison_sociale,
               COUNT(t.id) as nb_terrains, SUM(t.superficie) as total_superficie
        FROM dossiers_tnb dt
        JOIN contribuables c ON c.id = dt.contribuable_id
        JOIN terrains t ON t.contribuable_id = dt.contribuable_id
        WHERE c.actif=1 AND t.actif=1 AND t.archive=0
        GROUP BY dt.id
        HAVING COUNT(t.id) > 1
        ORDER BY nb_terrains DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ═══════════════════════════════════════════════════════════════
#  CO-PROPRIÉTAIRES — Ajouter / Modifier / Supprimer
# ═══════════════════════════════════════════════════════════════
@bp.route('/tnb/<int:id>/coproprio/ajouter', methods=['POST'])
@login_required
def tnb_coproprio_ajouter(id):
    """Ajoute un co-propriétaire à un terrain."""
    f = request.form
    ctb_id = f.get('contribuable_id', '').strip()
    if not ctb_id:
        flash('Veuillez sélectionner un contribuable', 'danger')
        return redirect(url_for('tnb.tnb_detail', id=id))
    ctb_id = int(ctb_id)
    conn = get_db()
    # Vérifier que ce n'est pas le propriétaire principal
    terrain = conn.execute('SELECT contribuable_id FROM terrains WHERE id=?', (id,)).fetchone()
    if terrain and terrain['contribuable_id'] == ctb_id:
        flash('Ce contribuable est déjà le propriétaire principal du terrain', 'warning')
        conn.close()
        return redirect(url_for('tnb.tnb_detail', id=id))
    try:
        conn.execute('''INSERT INTO terrain_coproprietaires
            (terrain_id, contribuable_id, part_indivision, type_titre, date_entree, acte_notarie, notes)
            VALUES (?,?,?,?,?,?,?)''',
            (id, ctb_id,
             float(f.get('part_indivision') or 0),
             f.get('type_titre', 'indivision'),
             f.get('date_entree', '') or None,
             f.get('acte_notarie', '') or None,
             f.get('notes', '') or None))
        conn.commit()
        flash('Co-propriétaire ajouté avec succès', 'success')
    except Exception as e:
        flash(f'Erreur : {e}', 'danger')
    conn.close()
    return redirect(url_for('tnb.tnb_detail', id=id))


@bp.route('/tnb/<int:id>/coproprio/<int:cp_id>/supprimer', methods=['POST'])
@login_required
def tnb_coproprio_supprimer(id, cp_id):
    """Supprime un co-propriétaire d'un terrain."""
    conn = get_db()
    conn.execute('DELETE FROM terrain_coproprietaires WHERE id=? AND terrain_id=?', (cp_id, id))
    conn.commit()
    conn.close()
    flash('Co-propriétaire retiré', 'success')
    return redirect(url_for('tnb.tnb_detail', id=id))


@bp.route('/tnb/<int:id>/coproprio/<int:cp_id>/modifier', methods=['POST'])
@login_required
def tnb_coproprio_modifier(cp_id, id):
    """Met à jour la part d'un co-propriétaire."""
    f = request.form
    conn = get_db()
    conn.execute('''UPDATE terrain_coproprietaires
        SET part_indivision=?, type_titre=?, date_entree=?, acte_notarie=?, notes=?
        WHERE id=? AND terrain_id=?''',
        (float(f.get('part_indivision') or 0),
         f.get('type_titre', 'indivision'),
         f.get('date_entree', '') or None,
         f.get('acte_notarie', '') or None,
         f.get('notes', '') or None,
         cp_id, id))
    conn.commit()
    conn.close()
    flash('Part modifiée', 'success')
    return redirect(url_for('tnb.tnb_detail', id=id))


# ═══════════════════════════════════════════════════════════════
#  RECENSEMENT TNB — Terrains sans dossier officiel
# ═══════════════════════════════════════════════════════════════

@bp.route('/tnb/recensement')
@login_required
def tnb_recensement():
    """Liste de recensement : terrains marqués recensement=1 (sans dossier officiel)."""
    user = get_current_user()
    conn = get_db()
    q = request.args.get('q', '')

    rows = conn.execute('''
        SELECT t.*, c.nom, c.prenom, c.raison_sociale, c.cin, c.rc,
               c.telephone, c.email, c.adresse as ctb_adresse,
               c.numero as ctb_num, c.id as ctb_id
        FROM terrains t
        JOIN contribuables c ON c.id = t.contribuable_id
        WHERE t.recensement = 1 AND t.actif = 1
        ORDER BY t.date_creation DESC
    ''').fetchall()

    # Filtre recherche
    if q:
        q_low = q.lower()
        rows = [r for r in rows if q_low in (
            (r['nom'] or '') + ' ' + (r['prenom'] or '') + ' ' +
            (r['raison_sociale'] or '') + ' ' + (r['cin'] or '') + ' ' +
            (r['rc'] or '') + ' ' + (r['adresse'] or '') + ' ' +
            (r['titre_foncier'] or '') + ' ' + (r['num_parcelle'] or '')
        ).lower()]

    contribuables = conn.execute(
        'SELECT id,numero,nom,prenom,raison_sociale,cin,rc,telephone,adresse '
        'FROM contribuables WHERE actif=1 ORDER BY nom'
    ).fetchall()
    tarifs = get_tarifs_module('TNB')
    conn.close()

    return render_template('tnb/tnb_recensement.html',
        user=user, terrains=rows, contribuables=contribuables,
        tarifs=tarifs, q=q, total=len(rows))


@bp.route('/tnb/recensement/ajouter', methods=['POST'])
@login_required
def tnb_recensement_ajouter():
    """Ajoute un terrain en liste de recensement (recensement=1, pas de dossier)."""
    conn = get_db()
    f   = request.form
    ctb_id = int(f['contribuable_id'])
    n_ter = (conn.execute(
        'SELECT COUNT(*) as c FROM terrains WHERE contribuable_id=?', (ctb_id,)
    ).fetchone()['c'] or 0) + 1
    num = f"REC{datetime.now().year}{ctb_id:04d}-{n_ter:03d}"
    conn.execute('''INSERT INTO terrains
        (numero_terrain, contribuable_id, commune_id,
         adresse, adresse_ar, quartier, lotissement, arrondissement,
         superficie, zone, titre_foncier, num_parcelle, statut,
         date_acquisition, recensement)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)''',
        (num, ctb_id, f.get('commune_id', 1),
         f.get('adresse', ''), f.get('adresse_ar', ''), f.get('quartier', ''),
         f.get('lotissement', ''), f.get('arrondissement', ''),
         f.get('superficie', 0), f.get('zone', 'B'),
         f.get('titre_foncier', ''), f.get('num_parcelle', ''),
         f.get('statut', 'non_bati'), f.get('date_acquisition', '')))
    conn.commit()
    conn.close()
    flash('Terrain ajouté au recensement', 'success')
    return redirect(url_for('tnb.tnb_recensement'))


@bp.route('/tnb/recensement/<int:id>/transferer', methods=['POST'])
@login_required
def tnb_recensement_transferer(id):
    """Transfère un terrain du recensement vers la liste principale (crée le dossier)."""
    conn = get_db()
    terrain = conn.execute(
        'SELECT contribuable_id FROM terrains WHERE id=? AND recensement=1', (id,)
    ).fetchone()
    if not terrain:
        flash('Terrain introuvable ou déjà transféré', 'danger')
        conn.close()
        return redirect(url_for('tnb.tnb_recensement'))

    ctb_id = terrain['contribuable_id']
    # Créer ou récupérer le dossier du redevable
    _did, num_dossier = _get_or_create_dossier(conn, ctb_id)
    # Passer le terrain en liste principale
    conn.execute('UPDATE terrains SET recensement=0 WHERE id=?', (id,))
    conn.commit()
    conn.close()
    flash(f'Terrain transféré avec succès → Dossier N°{num_dossier}', 'success')
    return redirect(url_for('tnb.tnb_recensement'))


@bp.route('/tnb/recensement/<int:id>/supprimer', methods=['POST'])
@login_required
def tnb_recensement_supprimer(id):
    """Supprime définitivement un terrain du recensement."""
    conn = get_db()
    conn.execute('UPDATE terrains SET actif=0 WHERE id=? AND recensement=1', (id,))
    conn.commit()
    conn.close()
    flash('Terrain supprimé du recensement', 'success')
    return redirect(url_for('tnb.tnb_recensement'))

