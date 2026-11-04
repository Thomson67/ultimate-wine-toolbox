# Packs locaux et gestion des presets ReShade

Disponible depuis la version stable **v0.11.0**. Les packs ZIP s’importent
localement ; les échanges communautaires restent des presets `.ini`.
Aucun fichier du pack Henriko n'est livré dans le dépôt.

## Import depuis un dossier (branche de test)

Après **Pack ReShade local (ZIP ou dossier, add-ons et shaders)**, choisir
**Archive ZIP** ou **Dossier**. Ce choix est également disponible pendant
l’installation initiale et pour l’ajout des variantes d’un pack déjà installé.
Sélectionner le dossier contenant directement `ReShade.ini`, les presets `.ini`
et `reshade-shaders/Shaders`, avec les add-ons éventuels à cette même racine.
Un dossier parent contenant plusieurs packs n’est pas détecté automatiquement.

Tous les presets sont importés et la configuration du pack choisit le preset
initial, comme pour un ZIP. Les fichiers nécessaires sont copiés dans le profil
du jeu : le dossier source n’est pas modifié et peut ensuite être déplacé ou
supprimé. Les limites restent 4 096 entrées, 32 Mio par fichier et 256 Mio au total.
Les liens symboliques et fichiers spéciaux sont refusés. Pour ajouter plus tard
les variantes d’un pack installé depuis un dossier, sélectionner un dossier au
contenu importable identique ; les dates et le nom du dossier n’affectent pas
son identité. Les packs précédemment installés depuis un ZIP conservent leur
identité ZIP et utilisent leur archive d’origine pour cet ajout.

## Essai Henriko / Citra

Fermer le jeu avant toute modification. Dans **Outils et compatibilité → ReShade**,
choisir le jeu Windows (émulateur lancé sous Wine) et :

1. **Installer / modifier version et shaders** : choisir **6.3.3**, puis
   **Officielle avec add-ons complets**. Conserver l'API graphique réellement
   utilisée par l'émulateur. Le choix du modèle de shaders n'affecte pas les
   shaders du pack, qui seront ensuite isolés.
2. Dans le choix des modèles/shaders qui suit la version, choisir **Installer
   un pack ReShade local (ZIP ou dossier, add-ons et shaders)**, à côté de la recherche
   communautaire. Sélectionner l'archive
   `HM 4K textures OoT.zip`, avec `ReShade.ini`, `citra.addon` et
   `reshade-shaders` à sa racine. Tous les presets sont importés, sans étape
   de sélection. **Henriko_Ultra_v10.ini**, désigné par le ReShade.ini de
   l'archive, devient automatiquement le preset initial.
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
- Le format local accepte un ZIP plat ou un dossier contenant `ReShade.ini`, des presets,
  des `.addon`, `.addon32` ou `.addon64`, et `reshade-shaders`. Un seul jeu
  d'architecture et un seul pack peuvent être actifs par jeu. Les fichiers
  shaders/includes et images reconnus sont importés ; EXE, DLL runtime et
  scripts ne sont pas importés. La configuration additionnelle prise en charge
  est celle de ReShade.ini ; les INI annexes propres à d'autres add-ons ne sont
  pas encore gérés.
- Les chemins dangereux, liens, fichiers spéciaux, doublons Windows et dépassements de taille
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
depuis un ZIP ou dossier** et sélectionner la même source que lors de l’installation : les variantes
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

## Gestionnaire global des presets

Le menu principal **ReShade → Gérer les presets installés** liste les collections
conservées, y compris lorsque le jeu est absent, déplacé ou que ReShade a été
désinstallé. La recherche et le filtre des associations orphelines permettent
de retrouver les anciens jeux. Les nouveaux index conservent leur chemin de
jeu ; pour les anciens, le gestionnaire recherche l'association dans la
configuration, les journaux et l'espace de préparation. Une collection sans
chemin retrouvé reste consultable sous son identifiant.

Après sélection d'une collection et d'un preset, on peut afficher les détails
et tous les paramètres INI, renommer, dupliquer, exporter ou supprimer ce preset.
L'export porte sur le preset sélectionné, même s'il est inactif. Pour un jeu
présent et géré, l'activation et la gestion complète du jeu (imports INI/ZIP)
restent accessibles depuis ce gestionnaire. Le preset actif d'un jeu présent
reste protégé contre la suppression.

Pour une association orpheline, le dernier preset actif peut être supprimé,
et **Supprimer toute la collection et son association** retire aussi les
réglages conservés et l'ancienne configuration du jeu. Les presets/métadonnées
sont d'abord archivés dans `reshade/deleted-presets/` sous le dossier de la
Toolbox ; les fichiers gérés restant dans un préfixe sont restaurés avant
nettoyage. Un préfixe encore actif bloque cette opération. Les caches communs
ReShade, les shaders partagés et les autres jeux sont conservés.

Les modifications de nom et les duplications d'un preset lié à un pack gardent
son contexte de shaders ; l'activation exige toujours ce même contexte. Le
gestionnaire n'essaie pas de deviner le nouvel emplacement d'un jeu déplacé.

## Supprimer tous les presets d'un jeu

L'action **Supprimer tous les presets pour ce jeu** est disponible dans la
collection du gestionnaire global et dans **Presets du jeu et détails**.
Elle accepte aussi un jeu présent : après confirmation, tous les presets de
sa collection, y compris l'actif, sont sauvegardés puis retirés. Un jeu géré
repart avec un unique **Preset vide**, sans effet activé, prêt pour un nouvel
import. ReShade conserve son état activé/désactivé, sa version, ses shaders et
ses add-ons. Un jeu absent n'est pas réactivé par cette opération.

La sauvegarde ZIP est indiquée à la fin. Le préfixe doit être inactif. Les
anciennes copies déployées sont retirées par le mécanisme de restauration avant
la réinitialisation ; le retrait ultérieur d'un pack ne réintroduit pas les
presets supprimés. Si la réinstallation du preset vide échoue, la collection
précédente est restaurée. Cette action conserve l'association du jeu ; pour
retirer aussi une association orpheline, utiliser l'action dédiée du gestionnaire.

## Vérifier les shaders lors de l'import d'un INI

Pour une installation gérée par la Toolbox, les imports INI locaux et
communautaires vérifient les effets de `Techniques` contre les fichiers `.fx`
réellement disponibles. Les effets désactivés conservés dans `TechniqueSorting`
ou les anciennes sections de paramètres ne provoquent pas de téléchargement.
Les effets personnalisés déjà présents sont reconnus comme disponibles.

Si un effet manque, l'index local propose son pack connu. Une ambiguïté entre
plusieurs sources demande un choix ; les effets inconnus sont signalés avant
application, avec possibilité d'annuler. Si l'utilisateur accepte le
téléchargement, les packs complets et leurs dépendances sont préparés avant
l'import du preset. Une annulation ou un téléchargement incomplet laisse le
preset précédent en place. Le jeu doit être fermé.

Seules les fonctions de shaders du backend ReShadeLinux épinglé sont utilisées,
sans installation de DLL ni changement de version ReShade. Les nouveaux packs
sont téléchargés dans un cache séparé et une vue propre au jeu combine les
fichiers existants et les ajouts. Les versions existantes (notamment les shaders
modifiés d'un pack custom) gardent la priorité sur les homonymes des nouveaux
packs. Les textures et includes sont conservés avec les effets. Les chemins
sont appliqués au prochain lancement via le hook existant.

Le preset et la configuration sont revérifiés après téléchargement : une
modification concurrente interrompt la validation. La configuration n'est
changée qu'une fois les effets reconnus trouvés dans la nouvelle vue. Le
contrôle confirme la présence des fichiers, pas leur compilation ni leur rendu
sur chaque version ReShade, GPU ou API. Certains presets privés/modifiés
nécessitent toujours leur archive d'origine : un INI seul ne permet pas de
retrouver automatiquement une variante privée portant le même nom qu'un effet
public.

Pour un injecteur intégré qui n'est pas géré par la Toolbox, le parcours existant
conserve ses DLL et shaders et demande que les effets requis soient présents ;
il ne prend pas automatiquement en charge son installation de shaders.

Tests : détection réelle des fichiers, effets personnalisés, sources ambiguës,
import après téléchargement, annulation/échec, changement du preset ou de la
configuration pendant le téléchargement, conservation des DLL et des shaders
modifiés, et restauration de la vue de shaders précédente après retrait d'un
pack custom. Les fonctions du backend épinglé ont aussi été exécutées avec des
clones locaux simulés pour vérifier le chemin de téléchargement/fusion seul.

## Préparer un pack personnalisé pour partage (branche de test)

Dans **ReShade → Presets communautaires → Préparer un pack ReShade pour partage
(ZIP)**, choisir un jeu géré par la Toolbox ou un ZIP/dossier personnalisé.
Fermer le jeu avant d’exporter ses réglages. Le preset actif est seul coché par
défaut ; s’il est incomplet, le premier preset valide est proposé. Les presets
incomplets restent visibles et marqués, avec le nom du fichier manquant ou les
candidats ambigus. Ils ne bloquent pas l’export des autres presets. Un preset
incomplet explicitement sélectionné provoque toujours un refus : ses effets
ne sont pas supprimés silencieusement. Cocher les presets à partager, puis
uniquement les add-ons indispensables : aucun add-on n’est coché par défaut,
les modules désactivés sont exclus et l’utilisation d’un add-on ne peut pas être
déduite d’un preset. Le couple Citra.fx/citra.addon connu est contrôlé.

L’export part exclusivement de `Techniques=` des presets choisis, jamais de
`TechniqueSorting=` ni des sections d’effets désactivés. Il inclut leurs `.fx`,
les inclusions littérales récursives et les textures déclarées par ces shaders.
Les autres effets, textures, presets et add-ons installés ne sont pas exportés.
Les bibliothèques de shaders du jeu sont indexées sans charger les fichiers
inutilisés. Les copies de shaders personnalisées du contexte du jeu sont
conservées telles quelles. Pour partager des fichiers retouchés dans un dossier
externe, choisir ce dossier comme source.

Une technique sans fichier explicite doit avoir une définition unique. Une
inclusion ou texture dynamique, une dépendance absente ou ambiguë provoque un
refus détaillé : il faut résoudre cette dépendance dans les sources puis
recommencer. Les dépendances conditionnelles littérales du shader utilisé sont
incluses de manière conservatrice ; ce contrôle statique n’est pas une trace
GPU des ressources effectivement lues pendant une partie. Les ressources
annexes spécifiques à un add-on, non référencées par les shaders, ne peuvent pas
être découvertes automatiquement et leurs formats ne sont pas encore pris en
charge. Un essai de réimport et en jeu reste nécessaire.

Renseigner le jeu, le titre, le pseudo, une description des prérequis et les
crédits/provenances/licences autorisant la redistribution des fichiers choisis.
Le ZIP conserve les paramètres des presets et la configuration ReShade portable
prise en charge ; il exclut les DLL du moteur, exécutables, caches, chemins
locaux et raccourcis personnels. Le manifeste `uwt-pack.json` contient les noms,
la version/API/architecture connues, les add-ons sélectionnés et les SHA-256.
Depuis un ZIP/dossier, préciser dans la description les prérequis qui ne peuvent
pas être déduits. Les crédits sont déclarés par l’auteur, pas vérifiés par UWT.

Le ZIP et son fichier `.sha256` sont créés dans
`exports/community/reshade-packs/`. Le ZIP se réimporte par **Pack ReShade local
→ Archive ZIP** après installation de la version et de l’API indiquées.
L’export ne modifie pas les sources. Le service communautaire en ligne actuel
accepte uniquement les petits profils texte : cette préparation n’envoie aucun
pack au catalogue. Le partage manuel du ZIP est disponible ; la réception,
le stockage et la modération des packs binaires restent à ajouter au service.

## Compléter les shaders de tous les presets à l’import

Après l’import d’un ZIP ou dossier, y compris depuis l’installation initiale,
UWT contrôle les effets actifs de **toutes les variantes importées**, sans les
activer successivement ni modifier le choix courant. Les packs de shaders
manquants reconnus sont proposés au téléchargement. Les sources ambiguës
nécessitent un choix ; les effets non reconnus restent signalés et une
confirmation explicite est nécessaire pour continuer avec ces manques.

Les ajouts utilisent le backend de shaders déjà vérifié, sans changer la DLL,
la version de ReShade ou les paramètres des presets. La vue combinée conserve
la priorité des shaders/includes/textures personnalisés du pack. Les copies
supplémentaires sont propres au jeu. Le contrôle porte sur les fichiers FX des
effets actifs ; il ne prouve pas leur compilation GPU ni le fonctionnement
d’un add-on. Une dépendance privée ou absente du catalogue n’est pas téléchargée
au hasard. L’export continue de vérifier ses dépendances statiques plus fines.

Pour un pack déjà installé, choisir **Pack ReShade local → Vérifier / compléter
les shaders de tous les presets**. Une annulation ou un échec laisse le pack
installé, signale que le complément n’est pas terminé et permet de réessayer.
Les réglages et le preset actif sont conservés ; les téléchargements achevés
sont vérifiés avant publication de la nouvelle vue. Retirer le pack restaure
le contexte de shaders antérieur.

Dans l’archive Henriko utilisée pour les essais, `ReShadePreset.ini` référence
notamment `FastFourierTransform.fx`, absent du ZIP et de notre index de packs.
Les trois variantes Henriko N64, Ultra et Vibrant ont leurs dépendances dans le
ZIP. L’import ne supprime pas les références du preset générique incomplet et
ne présente pas son téléchargement comme résolu automatiquement.
