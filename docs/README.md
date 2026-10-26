# Documentation — Ultimate Wine Toolbox

Ces guides décrivent Ultimate Wine Toolbox **v0.8.0**, avec les profils
launcher/jeu, les transferts complets AntiMicroX et le choix de nettoyage des
backups de sauvegardes après MAJ WSquashFS. La mise à jour normale conserve les
configurations créées pendant les tests. Les anciennes notes de release restent
propres à leur version.

These guides describe **v0.8.0**, including launcher profiles, complete
configuration transfers and optional cleanup of update save-data backups.
Normal updates retain configurations created during testing. A successful test
on one setup does not establish compatibility with every game and runner.

## Guides disponibles / Available guides

Les huit rubriques du menu **Documentation** sont disponibles hors ligne dans
la langue choisie. Les fichiers techniques ci-dessous complètent ces guides.

| Rubrique / Topic | Aide FR | English help | Détails |
|---|---|---|---|
| Création WSquashFS / Creation | [FR](../toolbox/docs/fr/creation.txt) | [EN](../toolbox/docs/en/creation.txt) | [Présentation](../README.fr.md#créer-un-wsquashfs) |
| Modèles de préfixes / Prefix templates | [FR](../toolbox/docs/fr/templates.txt) | [EN](../toolbox/docs/en/templates.txt) | Format SquashFS `.prefix` ou `.wsquashfs` |
| Mise à jour WSquashFS / Update | [FR](../toolbox/docs/fr/update.txt) | [EN](../toolbox/docs/en/update.txt) | [Présentation](../README.fr.md#mettre-à-jour-un-wsquashfs) |
| MangoHud | [FR](../toolbox/docs/fr/mangohud.txt) | [EN](../toolbox/docs/en/mangohud.txt) | Réglages globaux et par jeu / Global and per-game settings |
| DXVK / VKD3D / NVAPI | [FR](../toolbox/docs/fr/dxvk.txt) | [EN](../toolbox/docs/en/dxvk.txt) | [Présentation](../README.fr.md#dxvk-vkd3d-proton-et-nvapi) |
| ReShade | [FR](../toolbox/docs/fr/reshade.txt) | [EN](../toolbox/docs/en/reshade.txt) | [Échanges communautaires](COMMUNITY_PROFILES.md) |
| Winetricks / Wine Mono / .NET | [FR](../toolbox/docs/fr/dotnet.txt) | [EN](../toolbox/docs/en/dotnet.txt) | Installation, copie locale et restauration / Installation, staging and recovery |
| AntiMicroX | [FR](../toolbox/docs/fr/antimicrox.txt) | [EN](../toolbox/docs/en/antimicrox.txt) | [Guide technique](ANTIMICROX.md), [parcours launcher FR](ANTIMICROX-LAUNCHERS-TEST.fr.md) |

## Partage et compatibilité / Sharing and compatibility

- [Profils, règles launcher et ZIP groupés](COMMUNITY_PROFILES.md) : format,
  import, validation, limites et modération.
- [Contribuer au catalogue](../community-catalog/CONTRIBUTING.md) : parcours
  actuel par service HTTPS, sans compte GitHub requis.
- [Catalogue initial et catalogue public](../community-catalog/README.md) : le
  dossier de sources n’est pas le miroir du catalogue vivant.
- [Compatibilité SAVEDIR v41](V41_SAVEDIR_TEST_FR.md) : correctif optionnel,
  périmètre limité à v41 et protocole de vérification.
- [Option UMU_DIRECT_GAME](UMU_DIRECT_GAME_TEST_FR.md) : protocole et dépendance
  au wrapper fourni par UMU Runner Toolbox, projet distinct.
- [Shim Qt6 AntiMicroX](../toolbox/compat/antimicrox/README.md) et
  [shader rétro livré](../toolbox/data/reshade-retro/README.md) : provenance,
  contraintes et licences.
- [Processus de release](../RELEASING.md) et [notes publiées](../release-notes/) :
  chaque release garde son propre historique.

## État des vérifications / Validation scope

Sur la machine Batocera v44/labwc de test, la bascule de deux profils
launcher/jeu sur `.wine`, le partage communautaire puis réimport sur le même
jeu en `.wsquashfs` ont été confirmés.
Les règles de fenêtres observent Xorg/XWayland ; les fenêtres Wine Wayland
natives ne sont pas couvertes. Les essais automatisés vérifient aussi les
transactions, refus de chemins, profils partagés, imports et menus, sans
remplacer les essais matériels de chaque configuration.

Les guides MangoHud, DXVK, ReShade, modèles et SAVEDIR v41 ont également été
relus ; leurs limites et instructions restent applicables. Les anciennes notes
de release sont des documents historiques, pas des guides de l’interface actuelle.
