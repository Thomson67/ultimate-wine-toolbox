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
2. Dans le choix des modèles/shaders qui suit la version, choisir **Installer
   un pack ReShade local (ZIP, add-ons et shaders)**, à côté de la recherche
   communautaire. Sélectionner l'archive
   `HM 4K textures OoT.zip`, avec `ReShade.ini`, `citra.addon` et
   `reshade-shaders` à sa racine. Choisir **Henriko_Ultra_v10.ini** pour reproduire
   le preset désigné par le ReShade.ini de l'archive ; les autres presets sont
   également proposés.
3. Confirmer l'installation des add-ons exécutables et des shaders, puis celle
   de ReShade. La compatibilité version/architecture est vérifiée avant la
   modification du jeu. Le pack fournit ses propres shaders : aucun pack de
   shaders commun supplémentaire n'est téléchargé pour ce choix. L'import
   intervient avant l'activation de ReShade.
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

Le menu du jeu conserve aussi **Pack ReShade local** pour importer après une
installation existante. **Pack ReShade local → Retirer le pack** restaure le preset et la configuration
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

## Plusieurs presets pour le même jeu

**ReShade → jeu → Presets du jeu et détails** affiche la collection du jeu,
avec le preset actif et les variantes nécessitant un autre contexte de shaders.
Le preset existant est conservé lors du premier accès. Les imports INI, y
compris communautaires, gardent les précédents presets au lieu de les écraser.

Sélectionner un preset affiche son origine, son nom à l'import, sa date de
sauvegarde, ses techniques actives et le nombre de sections de paramètres.
Les actions permettent de l'activer, de consulter tout l'INI dans une vue
défilante, de le renommer ou de retirer une variante inactive de la collection.
Les paramètres modifiés dans le jeu sont sauvegardés dans la variante active
au retour et avant de changer de preset. Un seul preset est actif à la fois.
Fermer le jeu avant une activation ou un import depuis la Toolbox. En jeu,
**Page haut** choisit le preset précédent et **Page bas** le suivant grâce aux
commandes natives de ReShade. Seules les variantes du même contexte de shaders
sont déployées dans leur dossier de sélection. Le dernier choix et les
modifications sauvegardées dans les différentes variantes sont conservés au
retour, puis repris au prochain lancement. Les raccourcis ReShade personnalisés
déjà affectés restent prioritaires ; les touches Page haut/bas sont les valeurs
par défaut lorsque ces commandes ne sont pas affectées.

Les nouveaux imports de packs ajoutent toutes leurs variantes. Pour un pack
installé avec le premier test, utiliser **Ajouter les presets du pack installé
depuis son ZIP** et sélectionner exactement la même archive : les variantes
sont ajoutées sans réinstaller les shaders ou l'add-on. Pour changer entre
elles, il suffit ensuite de les activer dans la collection.

Une variante attachée à un pack reste listée après son retrait, mais ne peut
être activée que lorsque ce même pack est installé. Les presets ordinaires
utilisent les packs de shaders configurés pour le jeu. Changer de preset ne
télécharge pas de shaders et ne change pas les add-ons : la présence des effets
référencés reste à vérifier en jeu. L'export et le partage communautaire portent
sur le preset actif ; activer la variante souhaitée avant de l'exporter.

Cette collection concerne les installations ReShade gérées par la Toolbox.
Les injecteurs intégrés gardent leur parcours existant.

Le défilement natif a été vérifié dans les sources ReShade 6.3.3 : les commandes
`KeyPreviousPreset` et `KeyNextPreset` sélectionnent les presets dans le dossier
du preset courant. La Toolbox déploie une copie modifiable de chaque variante
compatible dans un dossier géré, et récupère uniquement ces fichiers connus.
Les anciennes révisions de ce dossier restent hors du défilement et sont
retirées avec les fichiers gérés lors de la désactivation/désinstallation.
Les tests automatisés simulent le changement du PresetPath et les écritures
faites par ReShade ; les touches physiques et le rendu restent à tester en jeu.

## Préservation des réglages lors d'une sélection manuelle

La collection active désormais `[OVERLAY] AutoSavePreset=1` lors du lancement.
ReShade 6.3.3 peut abandonner les modifications non sauvegardées lorsqu'un autre
preset est choisi dans son navigateur. Les INI du pack Henriko fourni portent
`AutoSavePreset=0` ; cette préférence ne doit pas désactiver la sauvegarde de
la collection. L'utilisateur peut vérifier **Auto Save on** dans l'overlay.

Un cas d'écrasement a été reproduit dans l'ancien adaptateur : après sélection
manuelle de l'ancien miroir `ReShadePreset.ini`, une variante modifiée pouvait
être remplacée par ce miroir encore ancien lors de la récupération des fichiers.
La capture conserve maintenant les variantes séparément, distingue les fichiers
modifiés des snapshots inchangés, et garde la version précédente dans
`presets/history/<identifiant>/`. La sélection manuelle du miroir est enregistrée
comme une variante distincte si son contenu diffère. Aucun fichier arbitraire
extérieur à la collection n'est lu sur la seule base du PresetPath.

En cas de perte signalée, exécuter d'abord :

```bash
python3 /userdata/system/ultimate-wine-toolbox/toolbox/helpers/reshade_preset_recovery.py
```

Ce script autonome copie les presets/configurations, l'index et les copies
encore présentes dans les installations journalisées vers un dossier daté de
`/userdata/system/backups/ultimate-wine-toolbox/reshade-presets/`. Il ne change
aucun fichier du jeu ou de la collection. Le rapport mentionne AutoSavePreset,
PresetPath et la provenance des copies pour permettre une récupération examinée.
Les modifications jamais écrites par ReShade ne peuvent pas être reconstituées
par une sauvegarde de fichiers.
