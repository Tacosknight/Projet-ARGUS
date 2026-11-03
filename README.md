# Facture-Checker 📑🔍 & Rapprochement Prothèses Auditives (S/N)

Application locale, modulaire et déterministe (sans LLM) d'audit, d'extraction OCR et de validation financière et légale de factures photographiées par smartphone.

**Spécificité Audioprothèse :** Rapprochement automatique des dépenses d'achats fabricants (Phonak, Oticon, Signia, Widex...) et des factures de vente patients via le **Numéro de Série unique (S/N)** de chaque aide auditive pour garantir l'équilibre financier et éliminer les oublis de refacturation.

---

## 🏗️ Architecture du Projet

```text
facture-checker/
│
├── core/
│   ├── __init__.py
│   ├── preprocessor.py       # Détection contours + homographie 4 points + binarisation adaptative
│   ├── ocr_engine.py         # Wrapper PaddleOCR (texte + coordonnées spatiales)
│   ├── parser.py             # Extraction champs + S/N aides auditives + détection Achat/Vente
│   ├── validator.py          # Contrôles d'intégrité (Luhn, TVA, équation fiscale, doublons)
│   └── reconciliation.py     # Moteur de réconciliation Achats Fabricants ↔ Ventes Patients par S/N
│
├── storage/
│   ├── __init__.py
│   ├── database.py           # Schéma et opérations CRUD SQLite (avec indexation S/N & type)
│   └── export_excel.py       # Génération dynamique du classeur Excel (3 onglets: KPI, S/N, Détails)
│
├── web/                      # Interface Web Mobile-First (FastAPI + HTML5 Caméra)
│   ├── app.py
│   └── templates/index.html
│
├── input_photos/             # Dossier source des photos de factures
├── requirements.txt          # Dépendances Python testées et épinglées
├── main.py                   # Point d'entrée CLI et orchestration batch
├── server.py                 # Serveur mobile avec affichage de QR Code dans le terminal
├── lancer_serveur_linux.sh   # Lanceur 1-clic pour Linux / macOS
└── lancer_serveur_windows.bat# Lanceur 1-clic pour Windows
```

---

## 🚀 Lancement Rapide (1-Clic)

### 🐧 Sous Linux / macOS
Double-cliquez ou lancez dans le terminal :
```bash
./lancer_serveur_linux.sh
```

### 🪟 Sous Windows
Double-cliquez simplement sur :
```cmd
lancer_serveur_windows.bat
```
*Le script configure automatiquement l'environnement virtuel Python, installe les dépendances si nécessaire et démarre le serveur web avec affichage d'un QR code pour votre smartphone.*

---

## 📱 Mode Mobile (Utilisation depuis Smartphone)

Vous pouvez utiliser votre smartphone comme scanner avec l'appareil photo intégré grâce à l'interface Web mobile locale :

```bash
# Lancer le serveur mobile
python server.py
# ou : python main.py --web
```

1. Le terminal affiche automatiquement l'adresse IP locale et **un QR Code**.
2. **Visez le QR Code avec l'appareil photo de votre smartphone** (connecté au même réseau Wi-Fi).
3. L'application mobile s'ouvre dans votre navigateur :
   - Cliquez sur **"Prendre la facture en photo"** (déclenche directement la caméra de votre smartphone).
   - Cliquez sur **"Lancer la vérification"** : le PC effectue le redressement, l'OCR et la validation.
   - Les montants, le statut d'audit et les éventuelles anomalies s'affichent instantanément sur votre écran.
   - Un bouton vous permet de **télécharger le classeur Excel récapitulatif directement sur votre smartphone**.

---

## 💻 Utilisation Classique en Ligne de Commande (Batch)
Pour tester immédiatement l'ensemble des cas d'audit (facture valide, erreur arithmétique, SIRET invalide, déformation perspective smartphone, doublon) :
```bash
python generate_test_samples.py
```

### 2. Exécution du pipeline complet
Placez vos photos de factures dans le dossier `input_photos/`, puis lancez :
```bash
python main.py
```

### Options de la ligne de commande (CLI)
```text
options:
  -h, --help            Affiche l'aide
  --input-dir CHEMIN    Dossier source des images (défaut : input_photos)
  --db-path CHEMIN      Chemin de la base SQLite (défaut : invoices.db)
  --output-excel CHEMIN Chemin du rapport Excel généré (défaut : factures_synthese.xlsx)
  --save-debug          Sauvegarde les images redressées pour inspection visuelle
```

Exemple avec paramètres personnalisés :
```bash
python main.py --input-dir /chemin/vers/photos --output-excel rapport_audit.xlsx --save-debug
```

---

## ⚙️ Spécifications Fonctionnelles & Modules

### 1. `core/preprocessor.py` (Vision par ordinateur)
- **Redimensionnement à 1600 px de hauteur** pour normaliser l'échelle tout en préservant le ratio d'aspect.
- **Détection des contours du document** : Flou gaussien, filtre de Canny, fermeture morphologique et approximation polygonale `approxPolyDP` à 4 sommets convexes.
- **Transformation de perspective (Homographie 4 points)** : Redressement géométrique à plat de la feuille (vue orthogonale zénithale). Conserve l'image si celle-ci est déjà un document scanné plein cadre.
- **Filtre adaptatif `cv2.adaptiveThreshold`** : Supprime les ombrages obliques causés par l'éclairage ambiant lors de la prise de vue smartphone et maximise le contraste texte/fond.

### 2. `core/ocr_engine.py` (Moteur OCR)
- Wrapper autour de **PaddleOCR** (`lang='fr'`, `use_angle_cls=True`).
- Extraction du texte et des coordonnées cartésiennes des boîtes englobantes (`box: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]`) et indices de confiance.
- Compatible avec PaddleOCR v2.x et v3.x.

### 3. `core/parser.py` (Extraction & Proximité Spatiale)
- **Regex strictes** :
  - SIRET (14 chiffres) et SIREN (9 chiffres).
  - Numéro de facture (`FAC-...`, `INV-...`, motifs préfixés).
  - Date d'émission (formats `DD/MM/YYYY`, `DD-MM-YYYY`, `DD mois YYYY`).
  - Détection et nettoyage des montants (`clean_amount`).
- **Analyse Spatiale 2D & Recherche Floue (`thefuzz`)** :
  - Détection des ancres textuelles ("Total TTC", "Net à payer", "Total HT", "TVA") tolérant les coquilles OCR.
  - Recherche prioritaire de la valeur numérique située **immédiatement à droite** (sur la même ligne) ou **en dessous** (sur la même colonne).

### 4. `core/validator.py` (Contrôles d'Intégrité)
Exécute 4 contrôles indépendants :
1. **Légal** :
   - Vérification du SIRET/SIREN via la somme de contrôle de l'**algorithme de Luhn**.
   - Vérification de la clé du numéro de TVA intracommunautaire français : $[12 + 3 \times (\text{SIREN} \pmod{97})] \pmod{97}$.
2. **Arithmétique** :
   - Vérification de l'équation fiscale : $|\text{HT} + \text{TVA} - \text{TTC}| \le 0.02\text{ €}$.
3. **Chronologique** :
   - Vérification que la date d'émission $\le$ date courante.
4. **Unicité** :
   - Calcul de l'empreinte composite **SHA-256** (`fournisseur_siret + date + num_facture + montant_ttc`) pour bloquer les doublons.
- **Statuts retournés** : `VALIDE`, `ERREUR_CALCUL`, `SIRET_INVALIDE`, `DOUBLON`, `A_VERIFIER`.

### 5. `storage/database.py` (Persistance SQLite)
- Table `invoices` avec indexation sur `unique_hash`, `siret` et `status`.
- Traçabilité complète des métadonnées, anomalies, hash d'intégrité et texte brut OCR.

### 6. `storage/export_excel.py` (Classeur Dynamique Excel)
- **Onglet "Détail Factures"** : Lignes formatées avec mise en forme conditionnelle :
  - 🟢 **Vert** : `VALIDE`
  - 🔴 **Rouge** : `ERREUR_CALCUL` ou `SIRET_INVALIDE`
  - 🟡 **Orange** : `DOUBLON` ou `A_VERIFIER`
- **Onglet "Tableau de Bord"** : Synthèse d'audit managériale avec calcul automatique des KPIs (volume validé, taux de conformité, répartition des anomalies).
