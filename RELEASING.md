RELEASING
========

But
----
Procédure rapide pour tagger, publier l'image Docker via GitHub Actions et bonnes pratiques de versioning.

Tagging et push
----------------

Créer le tag annoté localement et le pousser :

```bash
# créer un tag annoté
git tag -a v0.6.0 -m "Release v0.6.0"
# pousser le tag vers l'origine
git push origin v0.6.0
```

Le push du tag déclenchera le workflow `Build and publish Docker image` qui :
- détermine la version (étiquette sans le préfixe `v`),
- construit l'image via `docker/build-push-action`,
- pousse `ghcr.io/<OWNER>/rm-manager:<version>` et `...:latest`.

Keeping `VERSION`
------------------

- Le fichier `VERSION` existe pour usage local. Le workflow se base sur le tag Git.
- Optionnel : mettre à jour `VERSION` avant de tagger pour cohérence :

```bash
echo "0.6.0" > VERSION
git add VERSION
git commit -m "Bump VERSION to 0.6.0"
git tag -a v0.6.0 -m "Release v0.6.0"
git push origin main --follow-tags
```

Publier des notes de release
---------------------------

- Après push du tag, créez une Release sur GitHub (UI) ou via `gh` pour ajouter des notes/CHANGELOG.

Règles de publication recommandées
---------------------------------

- Utiliser SemVer (`vMAJOR.MINOR.PATCH`).
- Publier des images Docker uniquement pour des tags de release (`v*`).
- Laisser `latest` pointer vers la dernière release stable.
- Pour builds fréquents (CI/main) ajouter un workflow distinct qui construit mais n'upload pas, ou qui publie des images `snapshot`/`nightly` avec un tag daté (`snapshot-YYYYMMDD`).

Dépannage rapide
-----------------

- Vérifier Actions → Runs pour voir les logs du workflow.
- Vérifier que `packages: write` est autorisé (workflow permissions) et que l'organisation autorise Actions à publier des packages.
- Si push vers GHCR échoue, envisager un PAT temporaire (`write:packages`) pour isoler le problème.

Questions fréquentes
-------------------

- Q: "Dois‑je mettre `VERSION` à jour ?" — Non strictement nécessaire si vous taggez, mais c'est utile pour cohérence locale.
- Q: "Puis‑je builder depuis `main` ?" — Oui, mais séparez builds nightly et releases (tag → publish).

Versioning & CHANGELOG
----------------------

- **SemVer** : respectez `MAJOR.MINOR.PATCH`.
  - **MAJOR** : breaking changes.
  - **MINOR** : nouvelles fonctionnalités rétro‑compatibles.
  - **PATCH** : corrections et petits fixes.

- **Pré‑releases** : utilisez des suffixes `-rc.N`, `-beta.N` (ex: `v1.2.0-rc.1`). Décidez si vous publiez des images pour ces tags.

- **CHANGELOG** : maintenez `CHANGELOG.md` ou générez automatiquement via :
  - `Release Drafter` (prépare notes de release depuis PRs),
  - `semantic-release` (génère changelog et publie automatiquement, basé sur Conventional Commits),
  - scripts maison (collecte PR titles/labels).

- **Procédure recommandée** :
  1. Mettre à jour `CHANGELOG.md` et `VERSION` (optionnel).
  2. Commit + tag annoté : `git tag -a vX.Y.Z -m "Release vX.Y.Z"`.
  3. `git push origin vX.Y.Z` → Actions publie l'image.

- **Politique de publication** :
  - Publier seulement pour tags officiels.
  - Ne pas réécrire des tags publics (préférer une nouvelle version).
  - Pour tests, utiliser tags `snapshot-YYYYMMDD` plutôt que réutiliser `latest`.

- **Automatisation** :
  - Intégrer `Release Drafter` pour draft automatique des Releases.
  - Option : `semantic-release` pour automatiser bump/versioning/changelog (impose des conventions sur les messages de commit).

Exemples de commandes
---------------------

```bash
# Bump VERSION, commit, tag and push
echo "1.2.3" > VERSION
git add VERSION CHANGELOG.md
git commit -m "Release: bump to 1.2.3"
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3
```

Fin.
