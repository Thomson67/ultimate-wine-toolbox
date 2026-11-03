# Test : import local de packs ReShade

Branche `fix/scraper-es-sync`, sans nouvelle release stable. Ce premier test
concerne l'import local ; les échanges communautaires restent des presets `.ini`.
Aucun fichier du pack Henriko n'est livré dans le dépôt.

## Essai Henriko / Citra

Fermer le jeu avant toute modification. Dans **Outils et compatibilité → ReShade**,
choisir le jeu Windows (émulateur lancé sous Wine) et :

1. **Installer / modifier version et shaders** : choisir **6.3.3**, puis
   **Officielle avec add-ons complets**. Conserver l'API graphique réellement
   utilisée par l'émulateur. Le choix du modèle de shaders n'affecte pas les
   shaders du pack, qui seront ensuite isolés.
2. **Pack ReShade local (ZIP, add-ons et shaders)** : sélectionner l'archive
   `HM 4K textures OoT.zip`, avec `ReShade.ini`, `citra.addon` et
   `reshade-shaders` à sa racine. Choisir **Henriko_Ultra_v10.ini** pour reproduire
   le preset désigné par le ReShade.ini de l'archive ; les autres presets sont
   également proposés.
3. Confirmer l'installation des add-ons exécutables et des shaders.
4. Lancer le jeu et ouvrir ReShade avec **Home**. Dans Add-ons, vérifier que
   **citra.addon** est chargé et **Generic Depth** désactivé. Choisir le tampon
   de profondeur selon les indications du README fourni par l'auteur.
5. Vérifier **Citra.fx** en tête des effets et régler sa disposition d'écrans.
   Le mode performance reste désactivé pour permettre cette configuration.
6. Quitter normalement, relancer et contrôler que les réglages persistent.

La Toolbox ajoute `Citra@Citra.fx` au début des techniques actives et de leur
ordre : les presets fournis ne l'activent pas, alors que le README le demande.
Elle conserve les shaders modifiés du pack, notamment Glamayre, et importe
uniquement les paramètres utiles de `[ADDON]`, `[DEPTH]` et les définitions du
préprocesseur. Les raccourcis, l'interface et les chemins du PC de l'auteur ne
remplacent pas ceux de l'utilisateur. Les recherches de shaders/textures sont
redirigées vers le dossier isolé du pack pour ce jeu.

**Pack ReShade local → Retirer le pack** restaure le preset et la configuration
sauvegardés au moment de l'import, et retire les fichiers gérés. La désactivation
et la désinstallation ReShade utilisent aussi les sauvegardes des fichiers du
jeu. Retirer le pack avant de changer la version, l'API ou l'exécutable ReShade.
Un fichier binaire modifié par un autre outil bloque sa restauration automatique
plutôt que d'être écrasé.

## Périmètre et limites

- `.wine`, `.pc` et `.wsquashfs` passent par le mécanisme existant de déploiement
  et de restauration ReShade. Les assets du pack sont réinstallés si le préfixe
  temporaire est recréé.
- `citra.addon` de cette archive est un PE Windows x64, pas un module Linux pour
  les émulateurs natifs Batocera. Il importe notamment les runtimes MSVC
  `MSVCP140.dll`, `VCRUNTIME140.dll` et `VCRUNTIME140_1.dll`. S'il ne se charge pas,
  relever `ReShade.log` et vérifier les dépendances du préfixe ; le test n'ajoute
  pas automatiquement de redistribuable Visual C++.
- La recommandation 6.3.3 avec add-ons vient de l'utilisateur/auteur du pack.
  L'import exige l'identifiant officiel `6.3.3-addons` pour ce cas Citra.
  La cohérence des binaires ne garantit ni leur chargement sous Wine, ni la
  disponibilité de la profondeur, ni la compatibilité Vulkan/Azahar/TriAevum.
  Ces points nécessitent un essai en jeu.
- Le format local accepte un ZIP plat contenant `ReShade.ini`, des presets,
  des `.addon`, `.addon32` ou `.addon64`, et `reshade-shaders`. Un seul jeu
  d'architecture et un seul pack peuvent être actifs par jeu. Les fichiers
  shaders/includes et images reconnus sont importés ; EXE, DLL runtime et
  scripts ne sont pas importés. La configuration additionnelle prise en charge
  est celle de ReShade.ini ; les INI annexes propres à d'autres add-ons ne sont
  pas encore gérés.
- Les chemins ZIP dangereux, liens, doublons Windows et dépassements de taille
  sont refusés. Les fichiers installés sont inventoriés avec leur SHA-256.
  Ce contrôle ne constitue pas un audit du code exécuté par un add-on.
- Le partage communautaire de packs complets, les recettes de téléchargement
  et les règles de redistribution restent une étape suivante. Ne pas exporter
  le seul preset en supposant qu'il transporte l'add-on et les shaders modifiés.

## Vérifications automatisées

Tests de cycle import/lancement/modification/désactivation/réactivation/retrait,
restauration d'un add-on préexistant, recréation du dossier de jeu, mauvais
runtime/architecture, rollback d'un import échoué, modifications externes et
archives invalides. L'archive fournie a également été importée puis retirée dans
un préfixe de test simulé : 332 assets déployés, configuration précédente
restaurée. Aucun add-on ni shader n'a été exécuté dans ces tests.
