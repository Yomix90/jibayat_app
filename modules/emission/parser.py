"""
modules/emission/parser.py — Parseur de bordereaux Excel avec openpyxl pur
(Sans aucune dépendance envers pandas ou numpy pour une légèreté et compatibilité maximales)
"""
import re
import os
import openpyxl

def parse_bordereau_versement(filepath: str) -> dict:
    """
    Parse un fichier bordereau de versement Excel (.xlsx).
    Retourne:
    {
        "mois": 1,
        "annee": 2026,
        "total_general": 1000028.01,
        "lignes": [
            {"code_budgetaire": "1140201016", "nature_recette": "Taxe sur le transport...", "montant": 4478.4},
            ...
        ]
    }
    """
    result = {
        "mois": None,
        "annee": None,
        "total_general": 0.0,
        "lignes": []
    }
    
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
        sheet = wb.active
    except Exception as e:
        print(f"ERROR reading Excel {filepath}: {e}")
        return result

    # Convertir toutes les lignes de la feuille en listes de valeurs
    rows = []
    for row in sheet.iter_rows(values_only=True):
        rows.append(list(row))

    if not rows:
        return result

    start_row = -1

    # 1. Chercher Mois / Année dans les premières lignes
    for i in range(min(20, len(rows))):
        row = rows[i]
        row_str = " ".join([str(x) for x in row if x is not None]).upper()
        
        m_mois = re.search(r'MOIS\s*[:\s]\s*(\d+)', row_str)
        m_annee = re.search(r'ANN[EÉ]E\s*[:\s]\s*(\d{4})', row_str)
        
        if m_mois and not result["mois"]:
            result["mois"] = int(m_mois.group(1))
        if m_annee and not result["annee"]:
            result["annee"] = int(m_annee.group(1))

    # 2. Chercher "CODE BUDGETAIRE"
    for i in range(len(rows)):
        row = rows[i]
        for val in row:
            if val is not None and ('CODE BUDGETAIRE' in str(val).strip().upper() or 'CODE BUDGÉTAIRE' in str(val).upper() or 'BUDGETAIRE' in str(val).upper()):
                start_row = i + 1
                break
        if start_row != -1:
            break

    if start_row == -1:
        print("DEBUG: Could not find 'CODE BUDGETAIRE' header in Excel file.")
        return result

    # 3. Extraire les lignes
    for i in range(start_row, len(rows)):
        row = rows[i]
        if not row:
            continue

        first_cell = str(row[0]).strip().upper() if row[0] is not None else ""
        
        if 'TOTAL GENERAL' in first_cell or 'TOTAL GÉNÉRAL' in first_cell or 'TOTAL' in first_cell:
            for val in reversed(row):
                if val is not None:
                    try:
                        v = str(val).replace(' ', '').replace(',', '.')
                        result["total_general"] = float(v)
                        break
                    except Exception:
                        pass
            break

        code = str(row[0]).strip() if row[0] is not None else ""
        if not code or code.lower() == 'none':
            for j in range(len(row)):
                if row[j] is not None:
                    c = str(row[j]).strip()
                    if c.replace('.0', '').isdigit() and len(c) > 6:
                        code = c.replace('.0', '')
                        break

        if not code or code.lower() == 'none' or not code.isdigit():
            continue

        nature = ""
        montant = 0.0

        for j in range(1, len(row)):
            val = str(row[j]).strip() if row[j] is not None else ""
            if val and val.lower() != 'none' and not any(char.isdigit() for char in val):
                nature = val
                break

        for val in reversed(row):
            if val is not None:
                try:
                    v = str(val).replace(' ', '').replace(',', '.')
                    if '.' in v or v.isdigit():
                        montant = float(v)
                        if montant > 0:
                            break
                except Exception:
                    pass

        if code and montant > 0:
            result["lignes"].append({
                "code_budgetaire": code,
                "nature_recette": nature,
                "montant": montant
            })

    if result["total_general"] == 0.0:
        result["total_general"] = sum(l["montant"] for l in result["lignes"])

    return result
