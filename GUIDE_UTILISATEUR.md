# Guide utilisateur ARGUS 2.4.0

**Pour les assistants et assistantes en audioprothèse — utilisation sur Windows**

ARGUS aide à lire les factures et à retrouver les appareils achetés et vendus. Ce guide présente les gestes du quotidien, de l’installation à la sauvegarde.

> **Important :** ARGUS est une aide au contrôle. Même si un résultat paraît conforme, vérifiez les noms, les montants et les numéros de série sur les documents d’origine. Une correspondance « probable » doit être vérifiée : elle n’est pas une confirmation.
>
> Ce guide décrit la version **2.4.0**, actuellement préparée en brouillon. Demandez l’archive au responsable de votre centre ou de l’informatique.

## Sommaire

1. [Installer ARGUS sur Windows](#1-installer-argus-sur-windows)
2. [Démarrer et fermer ARGUS](#2-démarrer-et-fermer-argus)
3. [Se repérer dans les menus](#3-se-repérer-dans-les-menus)
4. [Comparer une facture fournisseur et une facture patient](#4-comparer-une-facture-fournisseur-et-une-facture-patient)
5. [Contrôler une facture seule](#5-contrôler-une-facture-seule)
6. [Retrouver et corriger une facture](#6-retrouver-et-corriger-une-facture)
7. [Consulter l’audit des prothèses](#7-consulter-laudit-des-prothèses)
8. [Utiliser un téléphone pour photographier une facture](#8-utiliser-un-téléphone-pour-photographier-une-facture)
9. [Vérifier l’installation, sauvegarder et restaurer](#9-vérifier-linstallation-sauvegarder-et-restaurer)
10. [Questions fréquentes et dépannage](#10-questions-fréquentes-et-dépannage)

## 1. Installer ARGUS sur Windows

L’installation consiste à extraire le dossier du programme : il n’est pas nécessaire d’installer Python.

1. Obtenez l’archive Windows `ARGUS-v2.4.0-Windows.zip` auprès de votre responsable.
2. Dans l’Explorateur Windows, faites un clic droit sur le fichier ZIP et choisissez **Extraire tout**.
3. Choisissez un emplacement facile à retrouver, par exemple le dossier **Documents**, puis confirmez l’extraction.
4. Ouvrez le dossier extrait jusqu’à voir `ARGUS.exe`.
5. Conservez ensemble tous les fichiers et dossiers livrés, notamment `ARGUS.exe`, `_internal` et `models`.

**Ne lancez pas ARGUS depuis le fichier ZIP et ne déplacez pas `ARGUS.exe` tout seul** : il a besoin des autres fichiers du dossier.

Si Windows ou l’antivirus bloque le programme, contactez votre responsable informatique. Ne contournez pas les protections de votre établissement.

### Où sont mes données ?

Les factures et données de travail sont conservées séparément du dossier du programme, dans `%LOCALAPPDATA%\ARGUS`. Pour y accéder, vous pouvez copier ce chemin dans la barre d’adresse de l’Explorateur Windows.

Pour une mise à jour, faites d’abord une [sauvegarde](#sauvegarder-mes-données), puis suivez les indications du responsable informatique. **Ne supprimez pas le dossier de données** en remplaçant le dossier du programme.

## 2. Démarrer et fermer ARGUS

### Démarrer

1. Ouvrez le dossier ARGUS extrait.
2. Double-cliquez sur **`ARGUS.exe`**.
3. Patientez : ARGUS ouvre normalement votre navigateur Internet sur son interface locale. Le premier démarrage peut prendre un moment.
4. Si le navigateur ne s’ouvre pas, essayez de saisir **`http://127.0.0.1:8000`** dans sa barre d’adresse. Si cela ne fonctionne pas, consultez le [dépannage](#10-questions-fréquentes-et-dépannage).

En mode normal, ARGUS fonctionne sur le poste local. Gardez l’application en fonctionnement pendant votre travail.

### Fermer

Fermer l’onglet du navigateur ne garantit pas l’arrêt du programme ARGUS, qui peut continuer à fonctionner en arrière-plan. Si vous devez l’arrêter, demandez au responsable informatique d’utiliser la procédure de votre établissement ; sous Windows, il peut être nécessaire de fermer le processus **ARGUS** dans le Gestionnaire des tâches. Assurez-vous auparavant qu’aucun traitement ni aucune sauvegarde ne sont en cours.

## 3. Se repérer dans les menus

| Onglet | À quoi sert-il ? |
|---|---|
| **Rapprochement bilatéral** | Comparer une facture fournisseur et une facture patient, ou contrôler une seule facture. |
| **Registre des factures** | Retrouver, consulter, corriger ou supprimer les factures enregistrées. |
| **Audit des prothèses (S/N)** | Rechercher les appareils et examiner leurs correspondances par numéro de série. |
| **Diagnostic** | Vérifier l’installation, sauvegarder ou restaurer les données. |

**S/N** signifie *numéro de série* : c’est le numéro qui permet d’identifier un appareil.

## 4. Comparer une facture fournisseur et une facture patient

Utilisez ce mode quand vous disposez de la facture d’achat et de la facture de vente patient.

1. Ouvrez **Rapprochement bilatéral**. Le mode de comparaison est activé par défaut.
2. Dans **Facture fournisseur (achat)**, cliquez sur **Importer**, puis sélectionnez le PDF ou l’image de la facture fournisseur. Vous pouvez aussi déposer le fichier dans la zone prévue.
3. Dans **Facture client (vente patient)**, importez la facture patient de la même façon.
4. Si une facture comporte plusieurs fichiers, utilisez **+ Fichier / PDF** ou **+ Photo** pour ajouter ses autres pages dans la même zone. Retirez une sélection incorrecte à l’aide de la croix de son aperçu.
5. Cliquez sur **Rapprocher les deux pièces justificatives** et patientez pendant le traitement.
6. Examinez les informations et comparez-les aux deux originaux, notamment les noms, les appareils, les montants et les S/N.
7. Si nécessaire, cliquez sur **Télécharger Synthèse Excel (.xlsx)** ou ouvrez **Gérer les factures** pour retrouver les pièces dans le registre.

> **Attention aux pages :** les fichiers ajoutés ensemble dans une zone sont traités comme les pages d’une même facture. Ne regroupez pas des factures différentes.

### Comprendre le résultat

- **Conforme / identique** : les informations comparées semblent correspondre. Relisez quand même les originaux.
- **Tolérance / équivalent** : ARGUS propose une correspondance proche ; une vérification est nécessaire.
- **Anomalie / divergent** : une différence a été détectée ; consultez le détail et les originaux.

La **marge brute TTC** affichée est un indicateur calculé à partir des montants disponibles : elle ne remplace pas un calcul comptable vérifié.

Les factures traitées sont enregistrées automatiquement. Si la seconde facture ne peut pas être traitée, la première peut déjà avoir été enregistrée : vérifiez le registre avant de recommencer. **Nouveau Comparatif** remet la sélection à zéro, mais ne supprime pas les factures enregistrées.

## 5. Contrôler une facture seule

1. Dans **Rapprochement bilatéral**, désactivez le commutateur **Rapprochement automatique bilatéral**.
2. Choisissez **Détection automatique**, **Facture fournisseur** ou **Facture patient**.
3. Cliquez sur **Importer un fichier (mono ou multi-pages, PDF)**, prenez une photo avec **Numériser par caméra**, ou déposez un fichier dans la zone prévue.
4. Ajoutez au besoin les autres fichiers de la **même facture**, puis cliquez sur **Auditer la facture**.
5. Vérifiez le résultat et les éventuelles anomalies. La facture est enregistrée dans le registre.

Le nombre indiqué avant l’envoi correspond aux fichiers sélectionnés : un PDF de plusieurs pages peut compter comme un seul fichier à cette étape.

### Que signifient les statuts ?

- **Facture conforme (valide)** : les contrôles automatiques n’ont pas relevé certaines anomalies ; cela ne garantit pas que chaque champ lu est exact.
- **Erreur arithmétique** : vérifiez les montants HT, TVA et TTC sur l’original.
- **Doublon détecté** : une facture semblable existe peut-être déjà. Cherchez-la dans le registre avant d’agir.
- **À vérifier** : une information manque ou demande une vérification.

ARGUS peut lire directement le texte d’une page PDF ou utiliser une reconnaissance d’image, appelée **OCR**. La méthode utilisée est indiquée dans le résultat. Dans les deux cas, contrôlez les informations importantes sur l’original : même un PDF contenant du texte peut être incomplet ou mal lu.

## 6. Retrouver et corriger une facture

### Rechercher et consulter

1. Ouvrez **Registre des factures**.
2. Saisissez un **numéro de facture** et/ou un **fournisseur** dans les zones de recherche. Effacez les critères pour retrouver toute la liste.
3. Utilisez le bouton d’actualisation si nécessaire.
4. Sur la facture souhaitée, cliquez sur **Voir le document** si ce lien est disponible.

### Vérifier et corriger les noms et les S/N

1. Sur la facture, cliquez sur **Vérifier et corriger**.
2. Comparez les champs avec le document affiché. Si plusieurs documents sont disponibles, sélectionnez celui à consulter. Si l’aperçu ne s’affiche pas, essayez le lien pour l’ouvrir dans un nouvel onglet.
3. Modifiez le nom du **fournisseur**, du **client/patient** ou un **numéro de série déjà enregistré**.
4. Si un numéro est lié à plusieurs lignes d’appareil, cochez les lignes auxquelles votre correction doit s’appliquer. Vérifiez les noms et références des appareils avant de choisir.
5. Cliquez sur **Vérifier les modifications**, relisez le récapitulatif et confirmez.
6. Lisez le résultat affiché après l’enregistrement : la valeur sauvegardée peut être légèrement normalisée, par exemple lorsque des espaces sont retirés. Vérifiez aussi les éventuelles anomalies et le rapprochement actualisé.

**Limites de cette version :** l’assistant ne propose pas d’ajouter ou de supprimer un numéro de série. Après une sauvegarde, fermez puis rouvrez l’assistant pour effectuer une autre correction. Si une autre personne ou opération a modifié la facture entre-temps, rouvrez-la avant de recommencer. Sans original disponible, une correction reste possible, mais vérifiez alors les informations à partir de votre propre exemplaire.

### Édition complète et avoirs

Le bouton **Modifier**, ou **Ouvrir l’édition complète** depuis l’assistant, donne accès à d’autres champs : type de facture, numéro, date, montants, modèles et lignes de produits. Vous pouvez aussi indiquer **Avoir / rectification** et choisir la facture d’origine si elle est connue.

Relisez toujours les montants avant d’enregistrer. Si seul le HT est saisi, l’interface peut proposer automatiquement un calcul avec une TVA de **5,5 %** : vérifiez que ce taux correspond bien à votre facture et corrigez-le si nécessaire. Pour modifier un S/N lié à une ligne d’appareil, privilégiez **Vérifier et corriger**.

### Exporter ou supprimer

- **Excel** télécharge une synthèse des factures enregistrées.
- **Supprimer** retire la facture sélectionnée après confirmation. Vérifiez votre choix avant de confirmer.
- **Vider le registre** concerne **toutes les factures enregistrées**, et pas seulement celles affichées par votre recherche. Faites une sauvegarde avant cette opération.

## 7. Consulter l’audit des prothèses

Ouvrez **Audit des prothèses (S/N)** pour rechercher les appareils parmi l’ensemble des factures enregistrées.

- Dans **Recherche globale**, saisissez par exemple un S/N, un nom de patient, un produit ou un numéro de facture.
- Utilisez **Fournisseur** pour limiter la liste affichée et **Tri** pour changer son ordre.
- Lisez la méthode de rapprochement et le diagnostic présentés pour chaque élément.

| Statut | Signification pratique |
|---|---|
| **Rapproché — numéro exact** | Le même S/N a été détecté côté achat et côté vente. Vérifiez si nécessaire sur les originaux. |
| **Correspondance probable — à confirmer** | ARGUS a trouvé une piste, mais la correspondance n’est pas certaine. Vérifiez les documents. |
| **Achat en attente de vente** | Aucune vente correspondante n’a été trouvée parmi les documents importés. Cela ne signifie pas forcément une perte. |
| **À vérifier** | Une information ou une correspondance demande votre attention. |

**Télécharger l’audit complet (.xlsx)** exporte l’ensemble des données : les filtres d’affichage ne limitent ni cet export ni les indicateurs. **Purger les données** supprime toutes les factures enregistrées après confirmation ; ce bouton ne supprime pas seulement les résultats filtrés.

## 8. Utiliser un téléphone pour photographier une facture

Le scanner mobile permet d’accéder à ARGUS depuis un téléphone sur le réseau local, puis d’utiliser les boutons **Photo** ou **Numériser par caméra** si le navigateur et le téléphone le permettent.

> **Sécurité :** ce mode rend ARGUS accessible sur le réseau local **sans connexion par mot de passe ni chiffrement du transport**. Ne l’utilisez que sur un réseau de confiance autorisé par votre établissement. Ne l’exposez pas sur Internet. Pour un accès partagé ou distant, une sécurisation supplémentaire est nécessaire.

1. Demandez au responsable informatique de vérifier que le réseau et le pare-feu autorisent cet usage en toute sécurité.
2. Sur le PC, lancez **`lancer_scanner_mobile_windows.bat`** depuis le dossier ARGUS lorsque le scanner mobile est nécessaire.
3. Suivez les indications du responsable informatique pour accéder au PC depuis le téléphone. Autorisez l’accès à la caméra si votre navigateur le demande et si la politique de l’établissement le permet.
4. Prenez une photo nette, bien éclairée, avec toute la page visible, puis contrôlez le résultat sur l’original.

La disponibilité de la caméra et de l’aperçu PDF dépend du navigateur et du téléphone. Le mode mobile doit être arrêté lorsqu’il n’est plus nécessaire, selon la procédure de votre établissement.

## 9. Vérifier l’installation, sauvegarder et restaurer

### Vérifier mon installation

Dans **Diagnostic**, cliquez sur **Vérifier mon installation**. ARGUS contrôle notamment l’accès à ses données, la lecture des PDF, la présence des fichiers de modèles et l’espace disque disponible. Si un contrôle échoue, transmettez son message au responsable informatique.

### Sauvegarder mes données

1. Ouvrez **Diagnostic**.
2. Cliquez sur **Sauvegarder mes données**.
3. Enregistrez le fichier ZIP téléchargé dans l’emplacement protégé prévu par votre établissement.

La sauvegarde peut contenir des factures et des données de patients : ne l’envoyez pas par un canal non autorisé. Effectuez des sauvegardes régulièrement, et avant toute purge, restauration ou mise à jour.

### Restaurer une sauvegarde

> **Avant de commencer :** téléchargez et conservez une sauvegarde de l’état actuel. La restauration remplace la base de données active ; elle fusionne les documents de la sauvegarde avec les documents déjà importés, et peut remplacer des fichiers portant le même nom.

1. Dans **Diagnostic**, cliquez sur **Restaurer une sauvegarde**.
2. Choisissez le ZIP de sauvegarde ARGUS voulu.
3. Lisez le message de confirmation, puis confirmez uniquement si vous souhaitez remplacer les données actives.
4. Attendez la fin du traitement et vérifiez le registre.

En cas d’échec, suivez le message affiché et contactez le support. Si un dossier de récupération `.restore-*` est indiqué, ne le supprimez pas.

## 10. Questions fréquentes et dépannage

| Situation | Que faire ? |
|---|---|
| ARGUS ne démarre pas | Vérifiez que le ZIP a été entièrement extrait et que tous les fichiers sont restés ensemble. Contactez le support si le problème persiste. |
| Le navigateur ne s’ouvre pas | Essayez `http://127.0.0.1:8000`. Si la page reste inaccessible, demandez au support de vérifier le programme et le port 8000. |
| Une facture est mal lue | Utilisez un PDF lisible ou reprenez une photo nette. Vérifiez ensuite les noms, montants et S/N sur l’original ; corrigez les données dans le registre. |
| Un original ne s’affiche pas | Essayez de l’ouvrir dans un nouvel onglet. S’il est indisponible, retrouvez votre exemplaire d’origine pour vérifier les données. |
| Un doublon est signalé | Recherchez la facture dans le registre et comparez les pièces avant de supprimer ou de réimporter quoi que ce soit. |
| Excel est verrouillé | Fermez le classeur ouvert dans Excel, puis réessayez l’export. Si ARGUS indique que les données ont été enregistrées mais que l’export a échoué, ne répétez pas automatiquement la saisie. |
| Une correspondance est « probable » | Comparez les numéros de série et les appareils sur les deux factures. Ce statut n’est pas une confirmation. |
| Un problème persiste | Contactez le responsable informatique. Il pourra consulter le journal `%LOCALAPPDATA%\ARGUS\logs\argus.log`, selon les règles de confidentialité de l’établissement. |
