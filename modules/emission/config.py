COMMUNE_CONFIG = {
    "nom": "Commune Ait Amira",
    "nom_ar": "جماعة أيت عميرة",
    "province": "Province de Ctouka Ait Baha",
    "province_ar": "إقليم شتوكة آيت باها",
    "region_ar": "جهة سوس ماسة",
    "prefecture": "Préfecture de",
    "pays": "ROYAUME DU MAROC",
    "pays_ar": "المملكة المغربية",
    "ministere": "MINISTERE DE L'INTERIEUR",
    "ministere_ar": "وزارة الداخلية",
}

MOIS_NOMS = {
    1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
    5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
    9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"
}

# Valeur initiale par défaut pour "Montant Total Des Emissions De La Collective"
# Utilisée comme référence dans la page d'émission ; peut être modifiée par import.
MONTANT_COLLECTIF_DEFAUT = 0.0

# Mapping Code Budgétaire → (nom_feuille, intitulé)
CODE_TO_RUBRIQUE = {
    "1140201016": ("Trans-Public", "Taxe sur le transport public des voyageurs"),
    "1140102027": ("Affermage", "Produit d'affermage des souks communaux"),
    "1140102026": ("Loyer", "Produit de location des locaux à usage commercial ou professionnel"),
    "1130101015": ("O-De Construction", "Taxe sur les opérations de construction"),
    "1110101011": ("Légalisation", "Taxe de légalisation des signatures et de certification des documents"),
    "1110302023": ("PVP", "Produit des ventes de plans, d'imprimés et de dossiers de concours"),
    "1110302024": ("Vente Animaux", "Produit des ventes des animaux et d'objets mis en fourrière"),
    "1110403032": ("Fourier", "Droits de fourrière"),
    "1120103034": ("RR-Eau", "Raccordement au réseau d'eau"),
    "1140103043": ("PS-Eau", "Produit de l'exploitation du service des eaux"),
    "1130101014": ("TNB", "Taxe sur les terrains urbains non bâtis"),
    "1110103031": ("Etat Civil", "Droit d'état civil"),
    "1130102022": ("ODP-Construction", "Redevance d'occupation temporaire du domaine public communal"),
    "1110401014": ("Pourcentage Ventes", "Pourcentage sur les ventes publiques effectuées par la collectivité"),
    "1140203033": ("Stationnement", "Droit de stationnement sur les véhicules affectés au transport public"),
    "1120103031": ("Ambulance", "Remboursement des frais de transport effectués par l'ambulance communale"),
    "1140101011": ("Boisson", "Taxe sur les débits de boissons"),
}
RUBRIQUE_DEFAULT = ("Recettes Imprévues", "Recettes imprévues")
