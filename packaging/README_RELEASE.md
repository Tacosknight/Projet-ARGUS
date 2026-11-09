# Préparer une version téléchargeable

Le workflow GitHub Actions **Préparer une release ARGUS** fabrique un ZIP portable Windows (avec test OCR) et une archive Linux contenant les sources et les modèles OCR. L'archive Linux n'est pas autonome : son lanceur installe les dépendances si nécessaire et peut demander les droits administrateur. Les plateformes et architectures prises en charge doivent être vérifiées avant diffusion.

1. Intégrer les modifications souhaitées dans la branche à publier, notamment ce workflow. Dans GitHub, ouvrir **Actions → Préparer une release ARGUS → Run workflow** et sélectionner cette branche.
2. Indiquer une nouvelle version, par exemple `v1.3.0`, le tag de la release de modèles et l'empreinte SHA-256 de `argus-ocr-models.zip` obtenue auprès d'une source de confiance. Ne pas réutiliser un tag existant.
3. Attendre la fin des deux constructions. Le workflow crée une **release brouillon** avec les archives et leurs empreintes ; il ne publie pas automatiquement la release. En cas d'échec, consulter les journaux Actions. Un échec de publication nécessite de vérifier si un brouillon ou un tag a déjà été créé avant de réessayer.
4. Tester les archives téléchargées sur des machines Windows et Linux propres : démarrage, OCR image et PDF, exports et absence de fuite de données. Vérifier les empreintes. Pour Windows, suivre également `README_WINDOWS.md`, notamment la recette hors ligne. Pour Linux, vérifier l'installation des dépendances sur les distributions visées ; le paquet nécessite Internet lors de leur installation.
5. Vérifier le contenu, les licences et les droits de redistribution des modèles et dépendances avant diffusion. Les modèles sont inclus dans les deux archives. Un dépôt privé limite l'accès aux personnes autorisées ; ne pas rendre le dépôt ou la release publics sans validation.
6. Dans **Releases**, ouvrir le brouillon, compléter les notes et cliquer sur **Publish release** après validation. La publication rend les fichiers accessibles aux personnes ayant accès au dépôt.

Le job de publication seul dispose de `contents: write`. Les archives intermédiaires Actions expirent après sept jours ; les fichiers de la release publiée sont distincts de ces artefacts. Les SHA-256 servent à détecter une corruption ; leur authenticité dépend d'une diffusion de l'empreinte par une source de confiance.
