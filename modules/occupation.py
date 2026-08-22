"""modules/occupation.py — Blueprint Occupation Domaine Public"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime, date
from database import get_db
from modules.helpers import login_required, get_current_user, annees_non_payees, get_tarifs_module, get_next_seq_num, permission_required

bp = Blueprint('odp', __name__)

@bp.route('/occupation-domaine')
@login_required
def odp_liste():
    user = get_current_user()
    conn = get_db()
    items = conn.execute('''SELECT o.*, c.nom, c.prenom, c.raison_sociale, c.numero as ctb_num
        FROM occupations o JOIN contribuables c ON o.contribuable_id=c.id WHERE o.actif=1
        ORDER BY o.date_creation DESC''').fetchall()
    contribuables = conn.execute('SELECT id,numero,nom,prenom,raison_sociale,cin FROM contribuables WHERE actif=1').fetchall()
    tarifs = get_tarifs_module('OCCUPATION_DOMAINE')
    next_numero = get_next_seq_num('occupations', 'numero', conn)
    conn.close()
    return render_template('odp/odp_liste.html', user=user, items=items,
                           contribuables=contribuables, tarifs=tarifs, next_numero=next_numero)

@bp.route('/occupation-domaine/ajouter', methods=['POST'])
@login_required
@permission_required('ajouter', 'odp')
def odp_ajouter():
    f = request.form
    conn = get_db()
    num = f.get('numero', '').strip() or get_next_seq_num('occupations', 'numero', conn)
    conn.execute('''INSERT INTO occupations (numero,contribuable_id,commune_id,type_occupation,localisation,superficie,num_autorisation,date_debut,date_fin)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (num, f['contribuable_id'], 1, f.get('type_occupation',''), f.get('localisation',''),
         f.get('superficie', 0), f.get('num_autorisation',''), f.get('date_debut',''), f.get('date_fin','')))
    conn.commit(); conn.close()
    flash(f'Occupation N° {num} enregistrée ✅', 'success')
    return redirect(url_for('odp.odp_liste'))

@bp.route('/occupation-domaine/<int:id>')
@login_required
def odp_detail(id):
    user = get_current_user()
    conn = get_db()
    occ = conn.execute('''SELECT o.*, c.nom, c.prenom, c.raison_sociale, c.telephone, c.id as ctb_id, c.numero as ctb_num
        FROM occupations o JOIN contribuables c ON o.contribuable_id=c.id WHERE o.id=?''', (id,)).fetchone()
    declarations = conn.execute('''SELECT d.*, b.numero_bulletin FROM declarations d
        LEFT JOIN bulletins b ON b.declaration_id=d.id
        WHERE d.module="OCCUPATION_DOMAINE" AND d.reference_id=? ORDER BY d.annee DESC, d.trimestre DESC''', (id,)).fetchall()
    
    payes = {(r['annee'], r['trimestre']) for r in declarations if r['statut'] != 'annule'}
    today = date.today()
    debut_annee = 2022
    if occ['date_debut']:
        try: debut_annee = int(occ['date_debut'][:4])
        except: pass
        
    annees_manquantes = set()
    for y in range(max(2022, debut_annee), today.year + 1):
        if (y, 0) not in payes:
            # Check if all quarters are paid
            if not all((y, t) in payes for t in range(1, 5)):
                annees_manquantes.add(y)
    annees_man = sorted(list(annees_manquantes))
    
    tarifs = get_tarifs_module('OCCUPATION_DOMAINE')
    conn.close()
    return render_template('odp/odp_detail.html', user=user, occ=occ, declarations=declarations,
        annees_manquantes=annees_man, tarifs=tarifs, today=today.isoformat())

@bp.route('/occupation-domaine/<int:id>/modifier', methods=['POST'])
@login_required
@permission_required('modifier', 'odp')
def odp_modifier(id):
    f = request.form
    conn = get_db()
    conn.execute('''UPDATE occupations SET type_occupation=?, localisation=?, superficie=?, 
        num_autorisation=?, date_debut=?, date_fin=?, statut=? WHERE id=?''',
        (f.get('type_occupation'), f.get('localisation'), f.get('superficie', 0),
         f.get('num_autorisation'), f.get('date_debut'), f.get('date_fin'), f.get('statut', 'actif'), id))
    conn.commit()
    conn.close()
    flash('Occupation modifiée ✅', 'success')
    return redirect(url_for('odp.odp_detail', id=id))

@bp.route('/occupation-domaine/<int:id>/supprimer', methods=['POST'])
@login_required
@permission_required('supprimer', 'odp')
def odp_supprimer(id):
    conn = get_db()
    conn.execute('UPDATE occupations SET actif=0 WHERE id=?', (id,))
    conn.commit()
    conn.close()
    flash('Occupation archivée ✅', 'info')
    return redirect(url_for('odp.odp_liste'))

@bp.route('/occupation-domaine/<int:id>/paiement')
@login_required
def odp_paiement(id):
    user = get_current_user()
    conn = get_db()
    occ = conn.execute('''SELECT o.*, c.nom, c.prenom, c.raison_sociale, c.id as ctb_id
        FROM occupations o JOIN contribuables c ON o.contribuable_id=c.id WHERE o.id=?''', (id,)).fetchone()
    declarations = conn.execute('''SELECT d.*, b.statut as bull_statut, b.id as bull_id, b.numero_bulletin, b.numero_quittance
        FROM declarations d LEFT JOIN bulletins b ON b.declaration_id=d.id
        WHERE d.module="OCCUPATION_DOMAINE" AND d.reference_id=? ORDER BY d.annee DESC, d.trimestre DESC''', (id,)).fetchall()
    tarifs = get_tarifs_module('OCCUPATION_DOMAINE')
    
    # Calculate unpaid periods
    payes = {(r['annee'], r['trimestre']) for r in declarations if r['statut'] != 'annule'}
    today = date.today()
    debut_annee = 2022
    if occ['date_debut']:
        try: debut_annee = int(occ['date_debut'][:4])
        except: pass
    
    DEADLINE_TRIM = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    TRIMESTRES = {1: 'T1 (Jan–Mar)', 2: 'T2 (Avr–Jun)', 3: 'T3 (Jul–Sep)', 4: 'T4 (Oct–Déc)'}
    
    non_payes = []
    for y in range(max(2022, debut_annee), today.year + 1):
        for t in range(1, 5):
            # If the user paid the WHOLE year (trimestre=0), it covers all quarters
            if (y, 0) in payes or (y, t) in payes:
                continue
            mois, jour = DEADLINE_TRIM[t]
            try: ech = date(y, mois, jour)
            except ValueError: ech = date(y, mois, 28)
            if ech > today: continue
            non_payes.append({'annee': y, 'trimestre': t, 'label': TRIMESTRES[t], 'echeance': ech.isoformat(), 'en_retard': today.isoformat() > ech.isoformat()})
            
    from collections import defaultdict
    by_year = defaultdict(list)
    for p in non_payes: by_year[p['annee']].append(p)
    non_payes_by_year = dict(sorted(by_year.items()))

    conn.close()
    return render_template('odp/odp_paiement.html', user=user, occ=occ,
        declarations=declarations, non_payes_by_year=non_payes_by_year,
        tarifs=tarifs, today=today.isoformat())

@bp.route('/occupation-domaine/<int:id>/declarer', methods=['POST'])
@login_required
@permission_required('creer_bulletin')
def odp_declarer(id):
    user = get_current_user()
    f = request.form
    conn = get_db()
    occ = conn.execute('SELECT * FROM occupations WHERE id=?', (id,)).fetchone()
    if not occ: return redirect(url_for('odp.odp_liste'))
    
    tarifs = get_tarifs_module('OCCUPATION_DOMAINE')
    tarif_an = float(tarifs[0]['valeur']) if tarifs else 50.0
    superficie = float(occ['superficie'] or 0)
    
    trims = f.getlist('trims')
    num_bulletin = f.get('numero_bulletin', '').strip()
    date_decl = f.get('date_declaration', date.today().isoformat())
    
    n_dcl = conn.execute("SELECT COUNT(*) as c FROM declarations").fetchone()['c'] + 1
    total_cree = 0.0
    n_crees = 0
    
    for trim_val in trims:
        if '_' not in trim_val: continue
        annee_str, trim_str = trim_val.split('_')
        annee, trim = int(annee_str), int(trim_str)
        
        # trim=0 means entire year
        principal = (superficie * tarif_an) if trim == 0 else (superficie * tarif_an / 4)
        principal = round(principal, 2)
        
        if principal <= 0: continue
        
        num = f"DCL-ODP{datetime.now().year}{n_dcl:05d}"
        statut = 'sous_seuil' if principal < 200 else 'emis'
        
        cur = conn.execute(
            '''INSERT INTO declarations (numero,module,reference_id,contribuable_id,commune_id,
               annee,trimestre,base_calcul,taux,montant_principal,montant_total,statut,date_declaration,agent_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (num, 'OCCUPATION_DOMAINE', id, occ['contribuable_id'], occ.get('commune_id', 1),
             annee, trim, superficie, tarif_an, principal, principal, statut, date_decl, user['id']))
        n_dcl += 1
        n_crees += 1
        total_cree += principal
        
        if num_bulletin and statut == 'emis':
            conn.execute('''INSERT INTO bulletins (numero_bulletin,declaration_id,contribuable_id,commune_id,
                montant,date_paiement,agent_id,statut) VALUES (?,?,?,?,?,?,?,?)''',
                (num_bulletin, cur.lastrowid, occ['contribuable_id'], occ.get('commune_id', 1), principal, date_decl, user['id'], 'en_attente'))
                
    conn.commit()
    conn.close()
    flash(f'✅ {n_crees} déclaration(s) créée(s) pour un total de {total_cree:.2f} DH.', 'success')
    return redirect(url_for('odp.odp_paiement', id=id))

@bp.route('/occupation-domaine/<int:id>/renouveler', methods=['POST'])
@login_required
@permission_required('modifier', 'odp')
def odp_renouveler(id):
    duree = request.form.get('duree')
    conn = get_db()
    occ = conn.execute('SELECT date_fin FROM occupations WHERE id=?', (id,)).fetchone()
    if not occ: return redirect(url_for('odp.odp_liste'))
    
    # Base calculation logic:
    base_date = date.today()
    if occ['date_fin']:
        try: base_date = datetime.strptime(occ['date_fin'], '%Y-%m-%d').date()
        except: pass
    
    from dateutil.relativedelta import relativedelta
    if duree == '1_trimestre': new_date = base_date + relativedelta(months=3)
    elif duree == '2_trimestres': new_date = base_date + relativedelta(months=6)
    else: new_date = base_date + relativedelta(years=1)
    
    conn.execute('UPDATE occupations SET date_fin=? WHERE id=?', (new_date.isoformat(), id))
    conn.commit()
    conn.close()
    flash(f'🔄 Occupation renouvelée jusqu\'au {new_date.isoformat()}', 'info')
    return redirect(url_for('odp.odp_paiement', id=id))

@bp.route('/occupation-domaine/<int:id>/avis-non-paiement')
@login_required
def odp_avis(id):
    conn = get_db()
    occ = conn.execute(
        '''SELECT o.*, c.nom, c.prenom, c.raison_sociale, c.cin, c.rc, c.adresse
           FROM occupations o JOIN contribuables c ON o.contribuable_id=c.id WHERE o.id=?''',
        (id,)).fetchone()
    commune_row = conn.execute('SELECT * FROM communes LIMIT 1').fetchone()
    commune_dict = dict(commune_row) if commune_row else {}
    
    # Calculate non payes
    declarations = conn.execute('''SELECT annee, trimestre FROM declarations 
        WHERE module="OCCUPATION_DOMAINE" AND reference_id=? AND statut!="annule"''', (id,)).fetchall()
    payes = {(r['annee'], r['trimestre']) for r in declarations}
    
    DEADLINE_TRIM = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    TRIMESTRES = {1: 'T1 (Jan–Mar)', 2: 'T2 (Avr–Jun)', 3: 'T3 (Jul–Sep)', 4: 'T4 (Oct–Déc)'}
    
    debut_annee = 2022
    if occ['date_debut']:
        try: debut_annee = int(occ['date_debut'][:4])
        except: pass
    today = date.today()
    non_payes = []
    for y in range(max(2022, debut_annee), today.year + 1):
        if (y, 0) in payes: continue
        for t in range(1, 5):
            if (y, t) in payes: continue
            mois, jour = DEADLINE_TRIM[t]
            try: ech = date(y, mois, jour)
            except: ech = date(y, mois, 28)
            if ech > today: continue
            non_payes.append({'annee': y, 'label': TRIMESTRES[t], 'echeance': ech.isoformat(), 'en_retard': today.isoformat() > ech.isoformat()})
            
    conn.close()
    commune = commune_dict.get('nom', '')
    province = commune_dict.get('province', '')
    return render_template('odp/odp_avis.html', occ=occ, non_payes=non_payes,
                           commune=commune, province=province,
                           commune_ar=commune_dict.get('nom_ar', ''),
                           province_ar=commune_dict.get('province_ar', ''),
                           region_ar=commune_dict.get('region_ar', ''),
                           today=today.isoformat(), n_avis=f"{id:03d}/{today.year}")
