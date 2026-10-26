# Ultimate Wine Toolbox pour Batocera

[English](README.md) | [Français](README.fr.md)

**Ultimate Wine Toolbox** est une toolbox Wine / Proton / UMU conçue pour Batocera.

Créée par **Thomsonito**.

**Version stable : [v0.7.2](https://github.com/Thomson67/ultimate-wine-toolbox/releases/tag/v0.7.2).**

## Fonctionnalités

- interface Français / Anglais
- intégration avec UMU Runner Toolbox
- Starter Pack de runners Wine, avec liste des runners installés et manquants
- gestion individuelle des runners Wine classiques
- GE-Proton classiques adaptés à Batocera, y compris 11.x (Batocera v44 conseillée)
- gestion globale et par jeu de MangoHud
- bundles DXVK / VKD3D-Proton / DXVK-NVAPI, modèles Batocera 40 à 43 / 43.1 et choix global ou par jeu
- filtrage des versions NVAPI selon la compatibilité connue avec DXVK
- ReShade par jeu : installation, activation/désactivation, presets, modèles d’effets et aide au choix de l’API
- AntiMicroX : profils manette, édition en jeu, conversion Pad2Key et gestion des associations
- catalogue communautaire : téléchargement, partage et validation de profils AntiMicroX et presets ReShade
- maintenance des Wine bottles et détection des bottles orphelines
- diagnostics des runners et de DXVK / VKD3D
- outils de squash / unsquash `.wine` / `.wsquashfs`
- création guidée de WSquashFS et mise à jour d’archives existantes, tests du jeu et reprise des opérations
- sauvegardes externalisées via `SAVEDIR` / `SAVEFILES` et composants Winetricks supplémentaires pendant la création
- suppression de jeux Windows
- analyse, nettoyage, organisation et restauration sécurisés de `batocera.conf`
- export / import additif des configurations Windows entre machines Batocera
- sauvegarde automatique avant les opérations destructives sur `batocera.conf`
- lanceur natif Batocera dans Ports avec prise en charge Pad2Key
- recherche de mises à jour au démarrage et depuis le menu de la toolbox

## Évolutions de cette branche

Les changements ci-dessous sont présents sur cette branche, après la release
stable v0.7.2 ; ils ne sont pas une annonce de nouvelle version stable.

- AntiMicroX : profil launcher seul ou profils launcher/jeu distincts, bascule
  selon le titre, la classe ou l’exécutable de la fenêtre Xorg/XWayland.
- Édition de chaque profil en jeu ou sans lancement, nouveau relevé des fenêtres
  et retest des règles depuis le menu du jeu.
- Partage communautaire complet des profils et règles ; export local d’un ou
  plusieurs jeux dans un ZIP, puis association aux jeux de la machine cible.
- Suppressions regroupées : configurations de jeux et profils sans jeu associé,
  avec protection des profils encore référencés.
- Correctif manette Moonlight/Sunshine propre à AntiMicroX et listes plus lisibles
  sans initiale rouge dans les sélections de jeux/profils.

Le parcours `.wine` → partage communautaire → réimport pour le même jeu en
`.wsquashfs`, ainsi que le mapping via Moonlight, ont été validés sur la machine
Batocera v44/labwc de test. Voir l’[index des guides](docs/README.md), le
[guide AntiMicroX](docs/ANTIMICROX.md) et le
[parcours launcher en français](docs/ANTIMICROX-LAUNCHERS-TEST.fr.md).

## Nouveautés de la v0.7.2

- Correction du lancement des jeux avec l’éditeur AntiMicroX ouvert sur Batocera v44.
- Bascule Hotkey+R1 au relâchement, sans double retour ni perte des commandes liées au mapping de R1.
- AntiMicroX accessible avec Alt+Tab ; ES retiré du sélecteur uniquement pendant la configuration en jeu.

[Notes de la v0.7.2](release-notes/v0.7.2.md)

## Nouveautés de la v0.7.1

- Affectation des profils AntiMicroX existants aux jeux locaux `.wine` et `.pc`.
- Contrôle de l’espace par disque et choix de l’emplacement de compression avec mergerfs.
- Reprise des MAJ sans l’archive originale, rapports d’erreur plus clairs et nettoyage final avant le message de réussite.

[Notes de la v0.7.1](release-notes/v0.7.1.md)

## Nouveautés de la v0.7.0

- Winetricks / Wine Mono / .NET disponibles dans Outils et compatibilité, pour les jeux `.wine`, `.pc` et `.wsquashfs`.
- Catalogue Winetricks complet, sélection multiple et composants déjà installés ignorés individuellement.
- WSquashFS : choix entre installation dans la bouteille et extraction → installation → recompression.
- Runners Batocera disponibles au choix et suggestions de jeux mieux classées lors des mises à jour.
- Correction des anciens liens graphiques cassés, dont DirectX 12 et NVAPI.
- Finalisation visible, arrêt des tâches avec la session et journaux limités à 20 par catégorie.

[Notes de la v0.7.0](release-notes/v0.7.0.md) · [Historique des releases](https://github.com/Thomson67/ultimate-wine-toolbox/releases)

## Installation

À exécuter en `root` sur Batocera :

Installation rapide :

```bash
curl -fsSL https://bit.ly/ultimate-wine-toolbox | bash
```

Lien direct GitHub :

```bash
curl -fsSL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/main/install.sh | bash
```

Les fichiers de la Toolbox sont installés dans :

```text
/userdata/system/ultimate-wine-toolbox
```

La Toolbox est ensuite accessible depuis :

```text
Ports -> Ultimate Wine Toolbox
```

La version stable peut être mise à jour depuis la toolbox ou avec la commande d’installation ci-dessus.

## Sécurité

Ultimate Wine Toolbox adopte volontairement un comportement conservateur lorsqu'elle modifie les données Batocera :

- les runners existants ne sont pas écrasés automatiquement
- les opérations destructives nécessitent une confirmation
- `batocera.conf` est sauvegardé avant toute modification
- les réglages Batocera `windows.dxvk` et `windows.dxvk_hud` sont protégés
- les installations DXVK externes ou personnalisées ne sont pas supprimées automatiquement
- les liens symboliques ne sont pas suivis lors de la suppression de jeux
- la migration des anciennes versions de développement préserve d'abord les données utilisateur avant de supprimer les anciens chemins

## Transfert des configurations Windows

Les exports de configuration Windows sont enregistrés dans :

```text
/userdata/system/ultimate-wine-toolbox/exports/windows-config
```

Les imports sont additifs : les réglages Windows déjà présents sur la machine cible sont conservés. Si une clé importée existe déjà localement, la valeur locale reste prioritaire.

Les réglages Batocera `windows.dxvk` et `windows.dxvk_hud` sont volontairement exclus des exports et imports.

## Logs

Log de lancement depuis Ports :

```bash
cat /userdata/system/logs/ultimate-wine-toolbox/port-launch.log
```

Dernier log de session de la Toolbox :

```bash
cat /userdata/system/logs/ultimate-wine-toolbox/latest.log
```

## Releases

Les versions stables sont publiées dans la section **Releases** du dépôt GitHub :

https://github.com/Thomson67/ultimate-wine-toolbox/releases

## Migration depuis les anciennes versions de développement

L'installation d'Ultimate Wine Toolbox par-dessus une ancienne version de développement migre automatiquement les données utiles vers les nouveaux chemins.

Les anciens lanceurs, hooks et répertoires runtime ne sont supprimés qu'après une migration réussie.

Les runners Wine/UMU, les jeux, les sauvegardes et les Wine bottles sont conservés.

## Documentation dans la Toolbox

Le menu principal **Documentation** regroupe les guides de création et de mise à jour WSquashFS, les modèles de préfixes Wine, MangoHud, DXVK/VKD3D, ReShade, Winetricks/Wine Mono/.NET et AntiMicroX (launchers, partage et transferts compris). Les textes sont disponibles hors ligne, en français et en anglais, dans un lecteur avec défilement. Le guide des modèles précise leur rôle, leur emplacement et le format attendu.

## Créer un WSquashFS

Le workflow guidé prépare un préfixe Wine, demande l’exécutable **avant le premier lancement**, puis permet de tester le jeu, les manettes et les sauvegardes. Au retour, **Vérifier / modifier le choix de l’exécutable du jeu** permet de corriger le lancement. Après un échec, **Installer des Winetricks supplémentaires** ajoute des composants dans le préfixe de travail, avec le runner choisi, avant de retester.

Pour les sauvegardes, choisir un dossier (`SAVEDIR`), des fichiers individuels dans le dossier du jeu (`SAVEFILES`) ou la sauvegarde du registre. Créer une vraie sauvegarde pendant le test aide la détection. Les fichiers créés/modifiés sont proposés mais décochés par défaut : des logs ou réglages peuvent aussi apparaître. Une sélection `SAVEFILES` concerne un seul dossier ; les fichiers choisis sont copiés dans les sauvegardes Batocera et retirés du préfixe avant compression. Batocera recrée leurs liens au lancement, sans déplacer le dossier du jeu.

La compression, les contrôles d’intégrité et la reprise des opérations en attente font partie du workflow. Après compression, le contrôle rapide final peut être lancé ou ignoré ; Annuler conserve le préfixe et ne remplace pas l’archive existante. La prise en charge native de `SAVEDIR` nécessite **Batocera v42 ou supérieure** ; un correctif expérimental optionnel est disponible pour v41 ; le contrôle complet nécessite le support `-pf` d’unsquashfs. Création basée sur le script de **DreamerCG**.

## Mettre à jour un WSquashFS

Dans Gestion des WSquashFS, l’option suit immédiatement la création. Sélectionnez une archive contenant un préfixe Wine, ou un `.wine` existant avec `system.reg` et `autorun.cmd`, puis un dossier contenant directement les fichiers de la nouvelle version du jeu. Un `.wine` est réutilisé sur place ; une archive est extraite dans un préfixe de test distinct. Le dossier source est déplacé dans le dossier du jeu identifié par `autorun.cmd` (souvent `drive_c/game`) du préfixe de travail. Les archives de type `.pc` sans préfixe Wine ne sont pas prises en charge.

Le premier test conserve le lancement défini dans l’archive ; il n’y a plus de sélection systématique de l’exécutable avant ce test. Vérifiez le lancement, la manette, le chargement de votre progression et une nouvelle sauvegarde. Au retour, **Vérifier / modifier le choix de l’exécutable du jeu** permet de le corriger et de retester. Le runner et les options du jeu sont repris ; le test utilise une copie des sauvegardes, sauf les liens vers la racine partagée décrits ci-dessous. Confirmez ensuite les règles de sauvegarde existantes ou choisissez un autre emplacement avec la détection ou l’explorateur.

Après compression, choisissez de lancer le contrôle complet ou de l’ignorer avant le remplacement. Le contrôle est proposé par défaut ; Annuler conserve le préfixe de travail et l’archive originale. À la fin, choisissez « Sauvegarder l’ancien WSquashFS puis remplacer » ou « Remplacer directement ». Les anciennes sauvegardes sont conservées en copies `.backup-…` pendant la publication. Après réussite, un choix permet de conserver ou supprimer les copies créées par cette opération ; les sauvegardes actives et l’éventuel backup de l’archive restent en place. Les anciens backups ne sont pas supprimés globalement. Les modifications de `batocera.conf` restent sauvegardées. En cas d’échec de compression, les sauvegardes originales restent en place. Une mise à jour en attente se reprend depuis le menu. La copie temporaire des sauvegardes de test est supprimée automatiquement après réussite de la mise à jour et conservée si elle échoue ou reste en attente ; la suppression du préfixe de travail est proposée à la fin.

Après remplacement réussi, les bottles associées à cette archive sont nettoyées pour que le prochain lancement reparte des fichiers et réglages mis à jour. Cela évite notamment de conserver une ancienne configuration MangoHud.

Prévoyez de la place pour l’extraction, les sauvegardes de test et la nouvelle archive. La gestion native `SAVEDIR=` nécessite Batocera v42 ou supérieur. Pour v41 uniquement, Gestion des WSquashFS propose une compatibilité expérimentale activable au démarrage, avec sauvegarde et restauration du lanceur. Voir [le protocole de test v41](docs/V41_SAVEDIR_TEST_FR.md).

La mise à jour propose d’abord le lancement défini dans `autorun.cmd`, y compris les `start.bat` originaux recopiés dans le nouveau dossier aux mêmes emplacements. Vous pouvez choisir un autre exécutable. Sans `SAVEDIR=`, les liens existants vers `/userdata/saves/windows` ou un de ses sous-dossiers sont détectés, restaurés dans le jeu mis à jour et proposés par défaut. Un lien vers la racine `/userdata/saves/windows` conserve exactement sa cible pendant le test et dans l’archive finale, sans fenêtre spéciale ni modification des références batch. Le test utilise donc directement les sauvegardes existantes dans ce cas. Vous pouvez conserver les liens ou sélectionner un autre emplacement au retour.

Avant le déplacement, l’ancien dossier du jeu est renommé en `<nom>.bak`. Le dossier mis à jour reprend le nom exact du dossier original ; le dossier source disparaît donc de son emplacement précédent. Le `.bak` est conservé jusqu’à validation du lancement, puis supprimé avant recompression. Les liens de sauvegarde contenus dans l’ancien dossier sont restaurés aux mêmes emplacements. Le déplacement ne bascule jamais vers une copie implicite. Avec mergerfs et une erreur EXDEV, la Toolbox peut déplacer les parties du dossier sur leurs branches physiques respectives ; les étapes sont consignées et un échec tente de les annuler. Le choix de conserver les règles de sauvegarde ne demande plus de confirmation supplémentaire.

Le préfixe de test reprend le nom exact de l’archive en remplaçant `.wsquashfs` par `.wine`, balises comprises. Un dossier `.wine` existant déclenche le choix : remplacer le dossier, choisir un autre nom ou quitter. Les réglages ES du `.wsquashfs` sont prioritaires ; s’il n’a aucun réglage spécifique, ceux du `.wine` existant sont repris. Les réglages de `batocera.conf` sont sauvegardés avant modification. Un dossier contenant la source de mise à jour ne peut pas être supprimé : choisissez alors un autre nom de préfixe.

## DXVK, VKD3D-Proton et NVAPI

**DXVK** traduit DirectX 9/10/11 vers Vulkan ; **VKD3D-Proton** fait de même pour DirectX 12. Un bundle permet de choisir ces composants indépendamment du runner, globalement ou pour un jeu précis. Le choix par jeu permet de garder une combinaison compatible sans imposer les mêmes versions à toute la collection.

**DXVK-NVAPI** apporte une compatibilité avec des fonctions NVIDIA utilisées par certains jeux. Les versions proposées sont filtrées selon les exigences DXVK connues et les limitations connues avec VKD3D sont signalées. Le pilote, le matériel et le runner restent déterminants ; NVAPI ne donne pas à une GTX les fonctions matérielles d’une RTX.

Une version plus récente ne garantit pas un meilleur résultat avec un ancien runner. Si un jeu cesse de fonctionner après changement de bundle, tester les composants Batocera par défaut ou une combinaison plus ancienne. **Vanilla-Proton-9.0-4 avec un VKD3D récent** a notamment provoqué des crashes sur des jeux DirectX 12 lors des tests.

### Modèles graphiques Batocera

Dans le gestionnaire DXVK / VKD3D, **Installer un modèle Batocera** propose les combinaisons officielles de Batocera 40, 41, 42 et 43 / 43.1. Les versions sont fixes, les archives sont vérifiées par SHA-256 et leur provenance est conservée dans `model.json`. Le catalogue se trouve dans `toolbox/data/batocera-dxvk-models.json`.

Après installation, choisissez le modèle globalement ou par jeu. NVAPI reste contrôlé par les options du jeu. Le modèle ne remplace pas le runner, les pilotes ou la configuration de Batocera : notamment, un VKD3D récent peut provoquer des crashes DirectX 12 avec Vanilla-Proton-9.0-4. Les modèles 40 à 42 permettent de tester des composants plus anciens.

## ReShade par jeu

Dans **Outils et compatibilité → ReShade**, choisir le jeu puis **Installer / modifier version et shaders**. Sélectionner le véritable `.exe` (par exemple `Binaries/Win64/...exe` pour certains jeux Unreal), l’API du jeu **avant** traduction par DXVK/VKD3D, la version de ReShade et les packs de shaders. L’architecture 32/64 bits est détectée dans l’exécutable. Le téléchargement se fait à la demande ; le Starter Pack ne change pas.

Lancer ensuite le jeu depuis EmulationStation et appuyer sur **Home** pour ouvrir ReShade. Les nouveaux profils passent le tutoriel et utilisent **Fin** pour activer/désactiver les effets ; les profils déjà personnalisés sont conservés. Aucun effet n’est imposé au premier démarrage : activer les effets souhaités dans l’interface ReShade. On peut importer un preset `.ini` depuis la toolbox ; ses shaders doivent être présents dans les packs choisis. ReShade utilise le runtime Windows officiel dans Wine/Proton.

- Formats proposés : `.wine`, `.pc`, `.wsquashfs` ; DirectX 9/10/11/12 et OpenGL. Vulkan natif n’est pas couvert par cette intégration.
- Pour un `.pc`, lancer le jeu une fois avec le runner choisi afin d’initialiser sa bottle avant activation.
- Pour un `.wsquashfs`, les fichiers sont préparés dans la couche modifiable de la bottle. L’archive reste intacte et l’installation est réappliquée lorsque la bottle est recréée.
- Les presets et réglages sont conservés sous `/userdata/system/ultimate-wine-toolbox/reshade/profiles`, par jeu. Le menu affiche leur dossier. Ils sont récupérés à la fermeture du jeu ; un changement de runner ne les efface pas.
- **Désactiver** restaure les fichiers remplacés. **Désinstaller pour ce jeu** retire sa configuration et conserve son preset. Fermer le jeu avant toute modification. Les installations intégrées reconnues ont un menu séparé d’activation/désactivation. Pour les remplacer par une installation toolbox, les retirer d’abord avec leur gestionnaire d’origine.
- Les fichiers des runners partagés ne sont pas modifiés. Si une DLL gérée a été changée par un autre outil, la restauration s’arrête et conserve la sauvegarde plutôt que d’écraser cette modification.
- Journaux : `/userdata/system/logs/ultimate-wine-toolbox/reshade-install-*.log` et `reshade-game-event.log`. Les bibliothèques partagées et shaders requis sont rendus accessibles à UMU sans retirer les réglages MangoHud.
- `git` et `file` ne sont pas requis sur Batocera : des adaptateurs privés téléchargent les archives GitHub des packs et lisent les en-têtes Windows lorsque ces outils sont absents. Les modifications locales des shaders sont préservées lors d'une mise à jour. L’installateur ReShade est extrait directement avec Python, même si un `7z` système est présent mais incomplet. Aucun outil système n'est ajouté.

Le moteur utilise **[ReShadeLinux 1.3.5](https://github.com/asafelobotomy/reshadelinux/tree/v1.3.5)**, par asafelobotomy, continuant le travail de kevinlekiller ; il est téléchargé sans modification depuis une révision précise, avec vérification SHA-256, et conserve sa licence GPL-2.0-or-later. **[ReShade](https://reshade.me/)** est développé par crosire et ses contributeurs. Les auteurs des packs sont affichés dans la sélection. La compatibilité graphique réelle dépend du jeu et du runner ; après un changement d’API, de runner ou de packs, vérifier le rendu et les raccourcis en jeu, notamment sous Wayland et UMU.

### Listes, presets, modèles et aide au choix de l’API

- La liste fusionnée **Jeux avec ReShade** lit directement les configurations et l’index des installations intégrées, sans parcourir toute la collection. **Tous les jeux** garde le traitement groupé rapide ; la recherche accepte une partie du nom.
- L’import et l’export utilisent **YAD**, avec un sélecteur de fichiers et confirmation avant remplacement. Sans YAD, un champ de chemin reste disponible. Fermer le jeu avant l’export ; son dernier preset est récupéré. L’export `.ini` ne contient pas les packs : installer les mêmes packs sur le jeu destinataire.
- Les modèles installent leurs packs **directement, sans checklist**. **Rétro** : ReShade, SweetFX, Legacy Effects (HQ4X), CRT-Royale, RSRetroArch, Crop and Resize, guest(r) (2D-Scaler / 2D-Scaler-level2), plus **4xBRZ**, **5xBR NoBlend** et **AnomalousPixelBlending (APB)**. Ces effets traitent l’image finale du jeu ; le réglage dépend de sa résolution d’origine et du rendu souhaité. **Sélection Thomson** : ReShade, SweetFX, Legacy Effects, Fubax, qUINT, prod80, AstrayFX et iMMERSE. **Sélection libre** ouvre la checklist ; **Reprendre les packs actuels** conserve la sélection du jeu. Les effets ne sont pas activés tous ensemble : charger un preset ou choisir les effets dans ReShade.

Le complément rétro inclut `5XBR_NoBlend.fx` et télécharge uniquement `4xBRZ.fx` et `AnomalousPixelBlending.fx`, depuis des révisions fixes vérifiées par SHA-256. Les sources et auteurs figurent dans `toolbox/data/reshade-extra-shaders.json` ; les notices des fichiers sont conservées. Le port **4xBRZ de spiderh**, issu de Libretro, est récupéré depuis son miroir GShade sans installer GShade. **APB**, par RdenBlaauwen, est téléchargé directement depuis son dépôt. Le port **5xBR NoBlend de spiderh** est livré avec son code source et sa licence GPL-2.0-or-later. HQ4X et les shaders guest(r) restent fournis par leurs packs respectifs.

Dans l’interface, chercher **xBRZ4x**, **xBR5x_NoBlend**, **HQ4X**, **TWO_D_SCALER**, **TWO_D_SCALER_LEVEL2** ou **AnomalousPixelBlending**. Pour 4xBRZ, l’auteur recommande de régler `Strength` selon la hauteur de l’image divisée par sa hauteur d’origine (par exemple 1080 / 240 = 4,5). Pour 5xBR NoBlend, le réglage initial de `Strength` est 1,5. Ces filtres constituent des alternatives à tester sur les jeux 2D ; éviter de cumuler plusieurs filtres de lissage sans comparer le résultat.
- Après sélection de l’exécutable, les imports PE et références aux DLL graphiques servent d’indices pour l’API. Pour Unity, `UnityPlayer.dll` adjacent est aussi analysé lorsque son import est trouvé. La lecture est limitée à 16 Mio par fichier, y compris dans les WSquashFS ; aucune extraction complète de l’archive. Des imports dynamiques, moteurs ou wrappers peuvent rendre le résultat incomplet. Le choix reste à confirmer.
- **PCGamingWiki** est une recherche facultative, déclenchée pour le jeu choisi : sélectionner la bonne fiche avant de lire les API possibles. Aucun accès réseau lors du chargement des listes. Le site peut bloquer les requêtes automatiques (403 observé) ; la toolbox conserve alors le choix local/manuellement renseigné et indique où consulter la fiche. Les API possibles d’une fiche ne prouvent pas l’API active lors du lancement. Vulkan natif et DirectX 8 ou antérieur restent hors de cette intégration directe.

Dans **Installer / modifier version et shaders**, après le choix de l’exécutable, le choix d’API propose **Détecter l’API en lançant le jeu**. Le lancement passe par EmulationStation ; allez jusqu’au menu ou en jeu, puis quittez normalement. Après le résultat, la toolbox reprend directement au choix d’API pour le même exécutable. Elle observe les DLL Windows (`d3d9`, `d3d11`, `d3d12`, `opengl32`, etc.) dans les processus des préfixes Wine et UMU. Cela fonctionne aussi avec les WSquashFS sans modifier l’archive, l’autorun ou les variables de lancement. Les bibliothèques Linux Vulkan ne sont pas prises comme preuve d’une API Vulkan native.

Ces observations complètent les indices de l’exécutable et restent des **indices à confirmer** : plusieurs moteurs/API, wrappers ou un ReShade déjà installé peuvent influencer le résultat. Un résultat inconnu laisse le choix manuel disponible. L’observation s’arrête au retour du jeu, ou après une heure sans fermer le jeu. Le dernier rapport est conservé par jeu : refaire le diagnostic après un changement de runner, de version du jeu ou de mode graphique. La première reprise manuelle de la toolbox peut aussi consulter une demande interrompue.

La recherche PCGamingWiki propose un nom nettoyé des mentions de runner, puis classe les résultats par similarité : le titre le plus proche apparaît en premier, sans valider automatiquement une édition ou une suite.

**Rechercher / actualiser les ReShade intégrés aux jeux** inspecte les DLL de relais usuelles et leurs métadonnées ReShade. Le premier passage peut être long ; les résultats, y compris les archives sans ReShade, sont indexés. Les archives inchangées ne sont pas relues. Ouvrir un jeu vérifie aussi son installation existante. Les listes ordinaires ne lancent aucune inspection d’archive.

Les DLL présentes uniquement dans `drive_c/ProgramData/ReShade` sont des ressources globales et ne suffisent pas à classer le jeu comme équipé. Une archive illisible est signalée avec sa raison dans `reshade-discovery.log` sans interrompre la recherche sur les autres jeux.

La désactivation d’une installation intégrée conserve les DLL originales dans un journal de restauration et retire leur chargement depuis le dossier du jeu. Dans un WSquashFS, un marqueur OverlayFS dans la bottle masque la DLL archivée ; l’archive reste inchangée. Wine/DXVK continue à charger sa bibliothèque système habituelle. La réactivation restaure exactement la DLL ou retire le marqueur ; **Rétablir la gestion d’origine** rend le contrôle au jeu. Presets, shaders et autorun ne sont pas modifiés. Le choix s’applique aussi aux prochains lancements et aux bottles recréées.

Les noms de DLL ou chargeurs non standard sont listés sans contrôle automatique. Le masquage d’un WSquashFS nécessite le lancement OverlayFS de Batocera et la création d’un marqueur sur le système de fichiers de la bottle ; en cas d’échec, le fichier existant est conservé. Une DLL modifiée par un autre outil n’est jamais écrasée pendant la restauration : le journal est conservé et une erreur est signalée. La désinstallation de la toolbox restaure les installations intégrées qu’elle contrôlait.

## Gestion .NET (expérimentale)

**Outils et compatibilité → Winetricks / Wine Mono / .NET** fonctionne aussi hors création d’archive. Choisissez un jeu `.wine`, `.pc` ou `.wsquashfs`, puis installez des composants courants ou sélectionnez-les dans le catalogue officiel complet. Sa liste déjà générée est téléchargée et mise en cache pour accélérer l’affichage ; `list-all` local reste disponible en secours. Wine Mono / .NET inclut le diagnostic et la restauration des sauvegardes. Les `.wine` sont modifiés directement ; les `.pc` utilisent la bouteille persistante du runner choisi. Pour un `.wsquashfs`, choisissez la bouteille ou **extraire → installer → recompresser** pour intégrer les composants au fichier à partager. Le mode archive part de l’archive d’origine, conserve la copie de travail pour reprise et ne remplace l’archive qu’après vérification complète ; la copie de travail est supprimée après publication réussie. Les modifications des bouteilles existantes sont conservées. Lancez d’abord les jeux `.pc` une fois avec le runner choisi. Une création d’archive en attente est préservée.

Gardez la Toolbox ouverte pendant la compression, la vérification et la finalisation. Fermer sa fenêtre interrompt les tâches liées à cette session ; le préfixe de travail et les états de reprise sont conservés. Une publication déjà engagée termine sa courte transaction avant l’arrêt. Une copie de sauvegarde explicitement demandée peut prendre du temps et reste affichée. Le renommage final ne bascule pas vers une copie implicite entre disques : si le système de fichiers refuse le renommage atomique, l’archive temporaire est conservée et l’opération signale une erreur.

Le workflow de test distingue le Wine Mono partagé de Batocera/runners des installations dans le préfixe, propose le MSI Mono stable récent vérifié ou son remplacement par .NET Framework 4.8 Microsoft, et copie le préfixe de travail avant modification. Le dossier du jeu est exclu de la copie. Les états .NET mixtes ou non identifiés sont refusés. Voir le nouveau guide .NET hors ligne ; valider l’installation puis deux lancements avant de finaliser l’archive.

Le test .NET utilise désormais une copie locale hors du dossier des ROMs, préserve les métadonnées de liens TKG et permet de restaurer une copie antérieure après un essai incomplet. Après chaque installation, vérifier le diagnostic et deux lancements du jeu avec le runner choisi ; le résultat reste dépendant du jeu et du runner.
