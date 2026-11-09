# ARGUS — distribution Windows

## Utilisation côté client (sans PowerShell)

Le client reçoit une archive ZIP contenant le dossier portable `ARGUS`. **PowerShell n'est pas nécessaire pour utiliser le logiciel** : il est utilisé uniquement par le responsable qui construit la release sur un poste Windows de confiance.

1. Télécharger le ZIP de livraison et l'extraire entièrement, par exemple dans `Documents\ARGUS`.
2. Conserver la structure complète du dossier : `ARGUS.exe`, `_internal`, `models` et les fichiers voisins doivent rester ensemble. Ne pas lancer l'EXE depuis la visionneuse ZIP et ne pas envoyer/coller `ARGUS.exe` seul.
3. Double-cliquer sur `ARGUS.exe` pour le mode local. `lancer_serveur_windows.bat` est une alternative qui appelle le même EXE via `cmd.exe`, sans Python ni PowerShell.
4. Utiliser `lancer_scanner_mobile_windows.bat` uniquement pour le scanner mobile : ce mode écoute sur le réseau local et peut demander l'accord du pare-feu d'entreprise.

Aucun Python, pip, installation ni privilège administrateur n'est requis au lancement. En mode normal, l'interface écoute uniquement sur `127.0.0.1` et ouvre le navigateur local.

Les données utilisateur ne sont pas dans le dossier portable : elles sont conservées dans `%LOCALAPPDATA%\ARGUS` (base SQLite, imports, exports, cache OCR et journaux). Pour une mise à jour, remplacer le dossier du programme par la nouvelle version **sans supprimer** ce dossier de données. En cas de problème, récupérer `%LOCALAPPDATA%\ARGUS\logs\argus.log` et vérifier que le port 8000 est disponible.

SmartScreen, l'antivirus ou les règles de contrôle des applications de l'organisation peuvent bloquer un EXE non signé. Le responsable de release doit valider ces règles avant diffusion et signer le package si la politique interne l'impose.

## Construction de la release (responsable de build)

## Checklist de release

Avant la diffusion :

1. Vérifier la provenance et l'empreinte des modèles OCR.
2. Construire le dossier `dist/ARGUS` sur Windows x64 avec le script ci-dessous.
3. Tester l'artefact exact avec `python -I packaging\smoke_windows.py dist\ARGUS\ARGUS.exe`.
4. Tester le dossier complet dans une VM Windows propre, sans Python ni cache Paddle/PaddleX, idéalement hors ligne au premier lancement.
5. Compresser le dossier complet en ZIP versionné et publier/transmettre son SHA-256 via un canal de confiance.
6. Vérifier la signature et l'acceptation SmartScreen/antivirus requises par l'organisation.

## Dépendances et limites de reproductibilité

Le build cible Windows x64 avec Python 3.12 et PaddleOCR 3.7.0. Le fichier
`facture-checker/requirements-windows.lock.txt` est un **manifest direct** : il
épingle notamment PaddleX 3.7.2 et l'unique distribution OpenCV
`opencv-contrib-python==4.10.0.84`, requise par PaddleX. Il ne s'agit pas d'un
lock transitif portable produit sur Linux. Les roues, les dépendances transitives
et les DLL doivent être résolues et contrôlées dans le venv Windows propre.

Le script produit `requirements-resolved-windows.txt` dans le dossier livré, exécute
`pip check`, puis valide les modèles avant PyInstaller. Une reconstruction
utilise un staging et un venv neufs à chaque appel ; elle refuse d'écraser
`dist/ARGUS` existant.

## Modèles locaux

Fournir des modèles PaddleOCR v3 compatibles dans des dossiers séparés. Chaque
dossier doit contenir `inference.yml`, `inference.pdiparams` et
`inference.json` (ou `inference.pdmodel`). Le YAML est lu avec `yaml.safe_load`.
`Global.model_name` est obligatoire et est transmis explicitement avec le chemin
correspondant : détection, reconnaissance et, s'il est présent, orientation.
Aucun téléchargement implicite n'est autorisé dans l'exécutable compilé.

Exemple :

```powershell
.\packaging\build_windows.ps1 `
  -DetectionModel 'C:\modeles\PP-OCRv5_server_det' `
  -RecognitionModel 'C:\modeles\PP-OCRv5_server_rec'
```

## Contrôles à effectuer sur Windows

Le build est à exécuter sur Windows ; aucun build EXE ni contrôle de DLL n'a
été déclaré depuis Linux. Sur l'artefact exact, dans une VM Windows propre,
sans Python ni cache Paddle, couper Internet avant le premier lancement puis
vérifier :

- démarrage sans console et journal `%LOCALAPPDATA%\ARGUS\logs\argus.log` ;
- OCR réel d'image et de PDF multipage hors ligne ;
- chemins avec espaces et accents, redémarrage et port 8000 occupé ;
- édition, suppression, export avec Excel ouvert, sauvegarde et restauration ;
- modèle absent/incomplet et message d'erreur exploitable ;
- antivirus et signature selon la politique de l'organisation.

Le journal est tournant (2 MiB, trois sauvegardes) et ne doit pas contenir de
texte de facture ni de données patient. Le mode local écoute sur
`127.0.0.1`; `--mobile` expose le serveur et doit être testé séparément avec
les règles réseau réelles.

## Livraison et données

Distribuer **tout `dist/ARGUS`**, dont `_internal`, les modèles et les lanceurs :
`ARGUS.exe` seul ne suffit pas. Le dossier livré n'exige ni Python, ni pip,
ni Microsoft Excel pour produire les exports. Les données sont dans
`%LOCALAPPDATA%\ARGUS`, séparées du programme.

SQLite est la source de vérité. Si Excel verrouille le classeur, une opération
métier réussie reste réussie et l'interface affiche un avertissement ; fermer
Excel puis relancer l'export. La restauration fusionne les documents de l'archive
avec les imports existants ; les fichiers homonymes sont remplacés. En cas
d'erreur d'E/S, elle tente de revenir à l'état précédent. Si cette récupération
échoue, conserver le dossier `.restore-*` indiqué et contacter le support.
Cette récupération n'est pas une garantie de transaction multifichier en cas
de coupure électrique.

## CI du paquet Windows (déclenchement manuel)

Le workflow **Linux and Windows validation** propose un job manuel de build et
recette du paquet. Dans ce dépôt GitHub privé, il lit l’archive de modèles depuis
une release du **même dépôt** avec le jeton éphémère du runner (`contents: read`) :
il ne faut ni rendre les modèles publics ni fournir de jeton personnel. Les
paramètres sont le tag de release (`ocr-models-v1` par défaut), le nom de l’asset
ZIP (`argus-ocr-models.zip`) et son SHA-256 obtenu indépendamment. L’archive doit
contenir uniquement `text_detection/inference.*`, `text_recognition/inference.*`
et éventuellement `textline_orientation/inference.*` (YAML, paramètres et graphe
attendus), à la racine ou sous le préfixe `models/`. Aucun script d'une archive
n'est exécuté.

Ce job utilise un venv Windows neuf, construit le dossier, lance `ARGUS.exe
--no-browser`, vérifie l'interface complète, un OCR réel sur une image synthétique
et un export Excel, puis conserve le candidat comme artefact. Le runner possède
Python et son réseau **n'est pas bloqué** : ce test ne remplace donc pas la VM
propre hors ligne et ne prouve pas à lui seul l'autonomie. Aucun de ces jobs n'a
été exécuté depuis cette session Linux.

## Tests source exécutables sous Linux

Les tests unitaires peuvent être lancés avec le Python du venv du projet :

```bash
ARGUS_DATA_DIR="$(mktemp -d)" PYTHONPATH=facture-checker \
  venv/bin/python -m unittest discover -s facture-checker/tests
```

Ils vérifient la validation YAML sans PaddleOCR, les chemins explicites des
modèles, la levée de `OCRInferenceError` sur panne d'inférence et le démarrage
sans flux console. Ils ne certifient ni les DLL Windows, ni PyInstaller, ni un
OCR hors ligne sur l'exécutable final.
