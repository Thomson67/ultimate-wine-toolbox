# Ultimate Wine Toolbox pour Batocera

[English](README.md) | [Français](README.fr.md)

**Ultimate Wine Toolbox** est une toolbox Wine / Proton / UMU conçue pour Batocera.

Créée par **Thomsonito**.

## Fonctionnalités

- interface Français / Anglais
- intégration avec UMU Runner Toolbox
- Starter Pack de runners Wine, avec liste des runners installés et manquants
- gestion individuelle des runners Wine classiques
- prise en charge des anciens GE-Proton adaptés à Batocera
- gestion globale et par jeu de MangoHud
- gestion de bundles DXVK / VKD3D
- sélection globale et par jeu de DXVK
- maintenance des Wine bottles et détection des bottles orphelines
- diagnostics des runners et de DXVK / VKD3D
- outils de squash / unsquash `.wine` / `.wsquashfs`
- suppression de jeux Windows
- analyse, nettoyage, organisation et restauration sécurisés de `batocera.conf`
- export / import additif des configurations Windows entre machines Batocera
- sauvegarde automatique avant les opérations destructives sur `batocera.conf`
- lanceur natif Batocera dans Ports avec prise en charge Pad2Key

## Nouveautés de la v0.3.0

- Mise à jour d’un jeu dans un WSquashFS, disponible après la création : reprise du préfixe, de l’exécutable, des réglages et des règles de sauvegarde existants.
- Déplacement de la nouvelle version du jeu, test du lancement et des sauvegardes, puis recompression avec contrôle complet d’intégrité.
- Choix du remplacement direct ou de la sauvegarde de l’ancienne archive avant remplacement.
- Reprise ou annulation des opérations en attente, et nettoyage des sauvegardes temporaires après réussite.
- Exclusion des `autorun.cmd` de la sélection des exécutables.

Le workflow de mise à jour est sorti de bêta en v0.5.3 après validation sur plusieurs jeux. Les autres fonctionnalités gardent leur statut habituel.

[Notes de version complètes](release-notes/v0.3.0.md)

## Nouveautés de la v0.2.0

- Création guidée de WSquashFS avec sauvegardes externalisées, test du jeu et reprise automatique.
- Après un échec de lancement en création, installation de composants Winetricks dans le préfixe de travail, puis possibilité de retester le jeu.
- Sélection graphique des dossiers de sauvegarde, inspection et alternative `user.reg`.
- Sauvegarde/remplacement et renommage des archives, contrôle d’intégrité rapide ou complet et tutoriel intégré.
- Profils MangoHud minimaliste, par défaut et détaillé.
- Normalisation facultative des noms des runners, sauvegarde des références modifiées et installation multiple UMU sans interruption.

L’externalisation via `SAVEDIR=` nécessite **Batocera v42 ou supérieure**. Le contrôle d’intégrité complet nécessite le support `-pf` d’unsquashfs.

Création WSquashFS basée sur le script du Grand Maître **DreamerCG** :)

[Notes de version complètes](release-notes/v0.2.0.md)

## Installation

À exécuter en `root` sur Batocera :

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

## Mettre à jour un WSquashFS

Dans Gestion des WSquashFS, l’option suit immédiatement la création. Sélectionnez une archive contenant un préfixe Wine et un dossier contenant directement les fichiers de la nouvelle version du jeu. Le dossier source est déplacé dans le dossier du jeu identifié par `autorun.cmd` (souvent `drive_c/game`) d’un préfixe de test distinct. Les archives de type `.pc` sans préfixe Wine ne sont pas prises en charge.

Sélectionnez l’exécutable, puis testez le lancement, la manette, le chargement de votre progression et une nouvelle sauvegarde. Le runner et les options du jeu sont repris ; le test utilise une copie des sauvegardes. Au retour, confirmez les règles de sauvegarde existantes ou choisissez un autre emplacement avec la détection ou l’explorateur.

La nouvelle archive doit passer un contrôle complet avant le remplacement. À la fin, choisissez « Sauvegarder l’ancien WSquashFS puis remplacer » ou « Remplacer directement ». Les sauvegardes originales et les modifications de `batocera.conf` restent sauvegardées. En cas d’échec de compression, les sauvegardes originales restent en place. Une mise à jour en attente se reprend depuis le menu. La copie temporaire des sauvegardes de test est supprimée automatiquement après réussite de la mise à jour et conservée si elle échoue ou reste en attente ; la suppression du préfixe de travail est proposée à la fin.

Prévoyez de la place pour l’extraction, les sauvegardes de test et la nouvelle archive. La gestion `SAVEDIR=` nécessite Batocera v42 ou supérieur.

La mise à jour propose d’abord le lancement défini dans `autorun.cmd`, y compris les `start.bat` originaux recopiés dans le nouveau dossier aux mêmes emplacements. Vous pouvez choisir un autre exécutable. Sans `SAVEDIR=`, les liens existants vers `/userdata/saves/windows` ou un de ses sous-dossiers sont détectés, restaurés dans le jeu mis à jour et proposés par défaut. Un lien vers la racine `/userdata/saves/windows` conserve exactement sa cible pendant le test et dans l’archive finale, sans fenêtre spéciale ni modification des références batch. Le test utilise donc directement les sauvegardes existantes dans ce cas. Vous pouvez conserver les liens ou sélectionner un autre emplacement au retour.

Avant le déplacement, l’ancien dossier du jeu est renommé en `<nom>.bak`. Le dossier mis à jour reprend le nom exact du dossier original ; le dossier source disparaît donc de son emplacement précédent. Le `.bak` est conservé jusqu’à validation du lancement, puis supprimé avant recompression. Les liens de sauvegarde contenus dans l’ancien dossier sont restaurés aux mêmes emplacements. Le déplacement nécessite un même système de fichiers et ne bascule jamais vers une copie implicite. Le choix de conserver les règles de sauvegarde ne demande plus de confirmation supplémentaire.

Le préfixe de test reprend le nom exact de l’archive en remplaçant `.wsquashfs` par `.wine`, balises comprises. Un dossier `.wine` existant déclenche le choix : remplacer le dossier, choisir un autre nom ou quitter. Les réglages ES du `.wsquashfs` sont prioritaires ; s’il n’a aucun réglage spécifique, ceux du `.wine` existant sont repris. Les réglages de `batocera.conf` sont sauvegardés avant modification. Un dossier contenant la source de mise à jour ne peut pas être supprimé : choisissez alors un autre nom de préfixe.

## Modèles graphiques Batocera

Dans le gestionnaire DXVK / VKD3D, **Installer un modèle Batocera** propose les combinaisons officielles de Batocera 40, 41, 42 et 43 / 43.1. Les versions sont fixes, les archives sont vérifiées par SHA-256 et leur provenance est conservée dans `model.json`. Le catalogue se trouve dans `toolbox/data/batocera-dxvk-models.json`.

Après installation, choisissez le modèle globalement ou par jeu. NVAPI reste contrôlé par les options du jeu. Le modèle ne remplace pas le runner, les pilotes ou la configuration de Batocera : notamment, un VKD3D récent peut provoquer des crashes DirectX 12 avec Vanilla-Proton-9.0-4. Les modèles 40 à 42 permettent de tester des composants plus anciens.

Dans la création WSquashFS, la sélection des sauvegardes propose aussi les fichiers individuels du dossier du jeu (`SAVEFILES`). Créez une sauvegarde pendant le test, puis choisissez les fichiers créés/modifiés ou utilisez la liste manuelle. Les fichiers sont décochés par défaut : des réglages et logs peuvent aussi apparaître. Choisissez un seul dossier par sélection ; les fichiers choisis sont copiés dans les sauvegardes Batocera et retirés du préfixe avant compression ; Batocera recrée leurs liens au lancement, sans déplacer le dossier du jeu.

## ReShade par jeu (bêta)

Dans **Réglages graphiques → ReShade (bêta)**, choisir le jeu puis **Installer / modifier version et shaders**. Sélectionner le véritable `.exe` (par exemple `Binaries/Win64/...exe` pour certains jeux Unreal), l’API du jeu **avant** traduction par DXVK/VKD3D, la version de ReShade et les packs de shaders. L’architecture 32/64 bits est détectée dans l’exécutable. Le téléchargement se fait à la demande ; le Starter Pack ne change pas.

Lancer ensuite le jeu depuis EmulationStation et appuyer sur **Home** pour ouvrir ReShade. Aucun effet n’est imposé au premier démarrage : activer les effets souhaités dans l’interface ReShade. On peut importer un preset `.ini` depuis la toolbox ; ses shaders doivent être présents dans les packs choisis. ReShade reste le runtime Windows officiel exécuté dans Wine/Proton, pas une couche native Linux comme vkBasalt.

- Formats proposés : `.wine`, `.pc`, `.wsquashfs` ; DirectX 9/10/11/12 et OpenGL. Vulkan natif n’est pas couvert par cette intégration.
- Pour un `.pc`, lancer le jeu une fois avec le runner choisi afin d’initialiser sa bottle avant activation.
- Pour un `.wsquashfs`, les fichiers sont préparés dans la couche modifiable de la bottle. L’archive reste intacte et l’installation est réappliquée lorsque la bottle est recréée.
- Les presets et réglages sont conservés sous `/userdata/system/ultimate-wine-toolbox/reshade/profiles`, par jeu. Le menu affiche leur dossier. Ils sont récupérés à la fermeture du jeu ; un changement de runner ne les efface pas.
- **Désactiver** restaure les fichiers remplacés. **Désinstaller pour ce jeu** retire sa configuration et conserve son preset. Fermer le jeu avant toute modification. Les installations intégrées reconnues ont un menu séparé d’activation/désactivation. Pour les remplacer par une installation toolbox, les retirer d’abord avec leur gestionnaire d’origine.
- Les fichiers des runners partagés ne sont pas modifiés. Si une DLL gérée a été changée par un autre outil, la restauration s’arrête et conserve la sauvegarde plutôt que d’écraser cette modification.
- Journaux : `/userdata/system/logs/ultimate-wine-toolbox/reshade-install-*.log` et `reshade-game-event.log`. Les bibliothèques partagées et shaders requis sont rendus accessibles à UMU sans retirer les réglages MangoHud.
- `git` et `file` ne sont pas requis sur Batocera : des adaptateurs privés téléchargent les archives GitHub des packs et lisent les en-têtes Windows lorsque ces outils sont absents. Les modifications locales des shaders sont préservées lors d'une mise à jour. L’installateur ReShade est extrait directement avec Python, même si un `7z` système est présent mais incomplet. Aucun outil système n'est ajouté.

Le moteur utilise **[ReShadeLinux 1.3.5](https://github.com/asafelobotomy/reshadelinux/tree/v1.3.5)**, par asafelobotomy, continuant le travail de kevinlekiller ; il est téléchargé sans modification depuis une révision précise, avec vérification SHA-256, et conserve sa licence GPL-2.0-or-later. **[ReShade](https://reshade.me/)** est développé par crosire et ses contributeurs. Les auteurs des packs sont affichés dans la sélection. La compatibilité graphique réelle dépend du jeu et du runner ; les premiers essais Batocera/Wayland et UMU restent nécessaires.

### Listes, presets, modèles et aide au choix de l’API

- La liste fusionnée **Jeux avec ReShade** lit directement les configurations et l’index des installations intégrées, sans parcourir toute la collection. **Tous les jeux** garde le traitement groupé rapide ; la recherche accepte une partie du nom.
- L’import et l’export utilisent **YAD**, avec un sélecteur de fichiers et confirmation avant remplacement. Sans YAD, un champ de chemin reste disponible. Fermer le jeu avant l’export ; son dernier preset est récupéré. L’export `.ini` ne contient pas les packs : installer les mêmes packs sur le jeu destinataire.
- Les modèles installent leurs packs **directement, sans checklist**. **Rétro** : ReShade, SweetFX, Legacy Effects (HQ4X), CRT-Royale, RSRetroArch, Crop and Resize et guest(r) (2D-Scaler / 2D-Scaler-level2). Ce modèle vise les filtres 2D et CRT ; les effets traitent l’image finale du jeu et ne sont pas des copies des filtres xBRZ / ScaleFX de RetroArch. **Sélection Thomson** : ReShade, SweetFX, Legacy Effects, Fubax, qUINT, prod80, AstrayFX et iMMERSE. **Sélection libre** ouvre la checklist ; **Reprendre les packs actuels** conserve la sélection du jeu. Ces modèles ne forcent pas des effets incompatibles avec le jeu : charger un preset ou activer les effets dans ReShade.
- Après sélection de l’exécutable, les imports PE et références aux DLL graphiques servent d’indices pour l’API. Pour Unity, `UnityPlayer.dll` adjacent est aussi analysé lorsque son import est trouvé. La lecture est limitée à 16 Mio par fichier, y compris dans les WSquashFS ; aucune extraction complète de l’archive. Des imports dynamiques, moteurs ou wrappers peuvent rendre le résultat incomplet. Le choix reste à confirmer.
- **PCGamingWiki** est une recherche facultative, déclenchée pour le jeu choisi : sélectionner la bonne fiche avant de lire les API possibles. Aucun accès réseau lors du chargement des listes. Le site peut bloquer les requêtes automatiques (403 observé) ; la toolbox conserve alors le choix local/manuellement renseigné et indique où consulter la fiche. Les API possibles d’une fiche ne prouvent pas l’API active lors du lancement. Vulkan natif et DirectX 8 ou antérieur restent hors de cette intégration directe.

Le menu du jeu et le choix d’API proposent **Détecter l’API en lançant le jeu**. Le lancement passe par EmulationStation ; allez jusqu’au menu ou en jeu, puis quittez normalement. La toolbox revient avec les DLL Windows observées (`d3d9`, `d3d11`, `d3d12`, `opengl32`, etc.) dans les processus de la bottle, y compris leurs processus enfants qui conservent le préfixe Wine. Cela fonctionne aussi avec les WSquashFS sans modifier l’archive, l’autorun ou les variables de lancement. Les bibliothèques Linux Vulkan ne sont pas prises comme preuve d’une API Vulkan native.

Ces observations complètent les indices de l’exécutable et restent des **indices à confirmer** : plusieurs moteurs/API, wrappers ou un ReShade déjà installé peuvent influencer le résultat. Un résultat inconnu laisse le choix manuel disponible. L’observation s’arrête au retour du jeu, ou après une heure sans fermer le jeu. Le dernier rapport est conservé par jeu : refaire le diagnostic après un changement de runner, de version du jeu ou de mode graphique. La première reprise manuelle de la toolbox peut aussi consulter une demande interrompue.

La recherche PCGamingWiki propose un nom nettoyé des mentions de runner, puis classe les résultats par similarité : le titre le plus proche apparaît en premier, sans valider automatiquement une édition ou une suite.

**Rechercher / actualiser les ReShade intégrés aux jeux** inspecte les DLL de relais usuelles et leurs métadonnées ReShade. Le premier passage peut être long ; les résultats, y compris les archives sans ReShade, sont indexés. Les archives inchangées ne sont pas relues. Ouvrir un jeu vérifie aussi son installation existante. Les listes ordinaires ne lancent aucune inspection d’archive.

La désactivation d’une installation intégrée conserve les DLL originales dans un journal de restauration et retire leur chargement depuis le dossier du jeu. Dans un WSquashFS, un marqueur OverlayFS dans la bottle masque la DLL archivée ; l’archive reste inchangée. Wine/DXVK continue à charger sa bibliothèque système habituelle. La réactivation restaure exactement la DLL ou retire le marqueur ; **Rétablir la gestion d’origine** rend le contrôle au jeu. Presets, shaders et autorun ne sont pas modifiés. Le choix s’applique aussi aux prochains lancements et aux bottles recréées.

Les noms de DLL ou chargeurs non standard sont listés sans contrôle automatique. Le masquage d’un WSquashFS nécessite le lancement OverlayFS de Batocera et la création d’un marqueur sur le système de fichiers de la bottle ; en cas d’échec, le fichier existant est conservé. Une DLL modifiée par un autre outil n’est jamais écrasée pendant la restauration : le journal est conservé et une erreur est signalée. La désinstallation de la toolbox restaure les installations intégrées qu’elle contrôlait.
