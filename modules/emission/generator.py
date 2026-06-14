import os
from datetime import datetime
from database import get_db
from .config import CODE_TO_RUBRIQUE, RUBRIQUE_DEFAULT
from .pdf_exporter import export_bordereau_pdf


def _get_emission_config(conn, annee):
    """Retrieve emission config for a given year."""
    row = conn.execute(
        'SELECT * FROM emission_config WHERE annee=?', (annee,)
    ).fetchone()
    if row:
        return dict(row)
    return {
        'annee': annee,
        'premiere_partie_mode': 'auto',
        'premiere_partie_valeur': 0.0,
        'deuxieme_partie_mode': 'vide',
        'deuxieme_partie_valeur': 0.0,
    }


def get_report_anterieurs(conn, rubrique: str, annee: int, mois: int) -> float:
    if mois <= 1:
        return 0.0
        
    row = conn.execute('''
        SELECT SUM(be.montant_present) as total
        FROM bordereaux_emission be
        JOIN bordereaux_versement bv ON be.bordereau_id = bv.id
        WHERE bv.annee = ? AND bv.mois < ? AND be.rubrique = ?
    ''', (annee, mois, rubrique)).fetchone()
    
    return float(row['total'] or 0.0)


def get_report_anterieurs_global(conn, annee: int, mois: int) -> float:
    """Cumulative total of all rubriques for months prior to `mois` in `annee`."""
    if mois <= 1:
        return 0.0
        
    row = conn.execute('''
        SELECT SUM(be.montant_present) as total
        FROM bordereaux_emission be
        JOIN bordereaux_versement bv ON be.bordereau_id = bv.id
        WHERE bv.annee = ? AND bv.mois < ?
    ''', (annee, mois)).fetchone()
    
    return float(row['total'] or 0.0)


def generer_tous_bordereaux(bordereau_id: int, output_dir: str) -> list:
    conn = get_db()
    bv = conn.execute('SELECT * FROM bordereaux_versement WHERE id = ?', (bordereau_id,)).fetchone()
    if not bv:
        conn.close()
        return []

    annee = bv['annee']
    mois = bv['mois']
        
    lignes = conn.execute('SELECT * FROM lignes_recettes WHERE bordereau_id = ?', (bordereau_id,)).fetchall()
    
    generated = []
    
    conn.execute('DELETE FROM bordereaux_emission WHERE bordereau_id = ?', (bordereau_id,))
    
    max_num_row = conn.execute('''
        SELECT MAX(be.numero_bordereau) as max_n
        FROM bordereaux_emission be
        JOIN bordereaux_versement bv ON be.bordereau_id = bv.id
        WHERE bv.annee = ?
    ''', (annee,)).fetchone()
    num_bordereau = (max_num_row['max_n'] or 0) if max_num_row else 0
    
    # Load emission config
    em_config = _get_emission_config(conn, annee)

    # ── Compute global totals ──────────────────────────────────────────────
    # report_global = cumul of ALL rubriques for months before current mois
    report_global = get_report_anterieurs_global(conn, annee, mois)
    # total_present_global = total of the current month (sum of all lignes)
    total_present_global = float(bv['total_general'] or 0.0)

    # ── Resolve 1ère Partie value ──────────────────────────────────────────
    # "1ère Partie" = column for individual-rubrique cumulative (per rubrique)
    # The GLOBAL premiere_partie applies to the collective emission column
    if em_config['premiere_partie_mode'] == 'auto':
        # Auto = cumul antérieur global (all months < mois, all rubriques)
        premiere_partie_global = report_global
    else:
        premiere_partie_global = float(em_config['premiere_partie_valeur'] or 0.0)

    # ── Resolve 2ème Partie value ──────────────────────────────────────────
    if em_config['deuxieme_partie_mode'] == 'auto':
        deuxieme_partie_global = total_present_global
    elif em_config['deuxieme_partie_mode'] == 'manuel':
        deuxieme_partie_global = float(em_config['deuxieme_partie_valeur'] or 0.0)
    else:
        deuxieme_partie_global = None  # vide

    for ligne in lignes:
        code = ligne['code_budgetaire']
        rubrique_info = CODE_TO_RUBRIQUE.get(code, RUBRIQUE_DEFAULT)
        rubrique_nom = rubrique_info[0]
        intitule = rubrique_info[1]
        
        montant = ligne['montant']

        # Per-rubrique report (cumul antérieur for this specific rubrique)
        report = get_report_anterieurs(conn, rubrique_nom, annee, mois)
        total = montant + report
        
        num_bordereau += 1
        
        pdf_filename = f"BE_{annee}_{mois:02d}_{code}.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)
        
        be_data = {
            'numero_bordereau': num_bordereau,
            'annee': annee,
            'mois': mois,
            'rubrique': rubrique_nom,
            'code_budgetaire': code,
            'intitule': intitule,
            'montant_present': montant,
            'report_anterieurs': report,
            'total': total,
            # Global columns for the collective emission table
            'total_present_global': total_present_global,
            'report_global': report_global,
            # 1ère / 2ème Partie overrides from config
            'premiere_partie_global': premiere_partie_global,
            'deuxieme_partie_global': deuxieme_partie_global,
            'premiere_partie_mode': em_config['premiere_partie_mode'],
            'deuxieme_partie_mode': em_config['deuxieme_partie_mode'],
        }
        
        export_bordereau_pdf(be_data, datetime.now().strftime('%d/%m/%Y'), pdf_path)
        
        conn.execute('''
            INSERT INTO bordereaux_emission 
            (bordereau_id, numero_bordereau, rubrique, code_budgetaire, intitule, montant_present, report_anterieurs, total, chemin_pdf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (bordereau_id, num_bordereau, rubrique_nom, code, intitule, montant, report, total, pdf_path))
        
        generated.append(be_data)
        
    conn.commit()
    conn.close()
    
    return generated
