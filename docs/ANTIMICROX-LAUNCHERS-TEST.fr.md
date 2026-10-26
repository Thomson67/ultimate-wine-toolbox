# Test AntiMicroX : jeux avec launcher

Base : Ultimate Wine Toolbox v0.7.2. Aucun changement des archives de jeux,
des scripts Windows ou de Sunshine. Les launchers embarquant déjà AntiMicroX
Windows ne sont pas migrés : choisir pour le premier essai un préfixe/jeu
utilisant seulement l'instance native gérée par la Toolbox.

## Installer

Fermer le jeu, AntiMicroX et la Toolbox. Lancer l'installateur de cette branche
avec `--ref` suivi du SHA complet du commit à tester. Il vérifie la v0.7.2 et
les fichiers d'origine, télécharge et valide les fichiers avant de remplacer
les composants concernés, les copies du hook, le lanceur Ports et le wrapper
AntiMicroX déjà installé. Les aides intégrées FR/EN sont également actualisées.
Les fichiers exacts des versions de test précédentes connues sont acceptés ;
une modification manuelle du code reste refusée. Une version déjà installée
ne crée pas de nouvelle sauvegarde. L’installateur imprime sa commande de
restauration, conservée avec la sauvegarde sous `state/backups`.

## Premier essai

1. Toolbox → AntiMicroX → **Créer ou modifier un profil en jeu** →
   **Jeu avec launcher : profils et fenêtres**.
2. Choisir le jeu, puis **Apprendre les fenêtres et configurer le mapping en jeu**.
3. Créer un profil ou choisir un profil existant. La configuration en direct
   utilise toujours un profil manuel, sans bascule automatique. Hotkey+R1,
   Alt+Tab et l'exclusion temporaire d'ES restent ceux de la v0.7.2.
4. Afficher le launcher, enregistrer son mapping dans AntiMicroX. Afficher
   ensuite le jeu quelques secondes, puis quitter le jeu normalement.
5. Au retour, la configuration des fenêtres et des règles s’ouvre directement, sans étape « Activer / Réessayer ».
6. Pour commencer, choisir **Launcher uniquement** puis le titre exact de la
   fenêtre du launcher dans la liste enregistrée. La classe ou l'exécutable
   peuvent servir lorsque leur identité est plus stable. Un titre partiel
   peut exclure des versions ou compteurs variables. Les fenêtres sont classées
   par première observation, pas par date exacte de création : le launcher
   n’est pas automatiquement la première entrée ni la bonne fenêtre.
7. Enregistrer puis choisir **Tester maintenant les fenêtres choisies** : le jeu
   est relancé avec les règles automatiques, sans ouvrir l'éditeur. Le profil
   launcher doit s'activer sur la fenêtre reconnue et devenir vide en jeu.
8. Quitter le jeu pour revenir au menu **Retester / Modifier les règles /
   Refaire l'apprentissage**. La liste des fenêtres relevées reste disponible.

Le menu de gestion du launcher propose également **Retester les règles
enregistrées**, sans refaire l'apprentissage. Les tests utilisent le même
cycle de lancement différé et de retour à la Toolbox que l'édition en direct,
mais sans ouvrir l'éditeur, ajouter Hotkey+R1 ou masquer ES dans Alt+Tab.
Un jeu peut aussi être lancé directement depuis ES pour vérifier les règles.

Le mode **Profils distincts** permet ensuite de choisir un profil jeu existant
et sa propre règle. L'option conseillée limite ce profil à une fenêtre de jeu
identifiée ; l'autre option l'applique à toute autre fenêtre Wine reconnue de
la même session. Il n'y a pas de mode « même profil pour toute la session » dans
les règles launcher : cela correspond à l'association classique d'un profil.

## Retrouver et modifier un jeu déjà configuré

Dans **Mes jeux et leurs profils**, sélectionner un jeu ayant des règles
launcher actives ouvre directement son menu spécifique : retester la bascule,
modifier les fenêtres/mode/profils associés, éditer les commandes du launcher
ou du profil jeu lorsqu'il existe, et refaire l'apprentissage en jeu.

Dans **Désactiver ou supprimer un profil / une configuration**, **Désactiver
les règles launcher (garder le profil actif)** revient au menu classique du même
jeu. **Retirer la configuration de ce jeu (garder les profils)** retire règles
et association sans supprimer les fichiers. Modifier les commandes du profil
jeu ne le réaffecte pas à la place du profil launcher.

Le menu de test permet aussi de consulter ou désactiver les règles. Aucun
nom de jeu ou suffixe `[L]` n'active cette fonctionnalité automatiquement.

Une mise à jour reconnue conserve les profils, associations et règles déjà
enregistrés. Le suffixe `[L]` n’est pas requis. Désactiver l’AntiMicroX Windows
éventuellement lancé dans un `start.bat` évite deux mappers en parallèle.

## Limites à vérifier sur Batocera

- Cette première version observe Xorg/XWayland (`winex11.drv`), pas les fenêtres
  Wine utilisant un pilote Wayland natif.
- Elle vérifie la session ES et le préfixe Wine des nouveaux processus.
  Une fenêtre sans `WINEPREFIX` identifiable est ignorée plutôt qu'assimilée
  à tort au jeu. Si aucune fenêtre n'est relevée, fournir le journal.
- Un profil vide désactive les touches/souris émulées ; il ne masque pas la
  manette physique au jeu et ne remplace pas son support natif.
- Le changement de profil utilise l'IPC de l'instance AntiMicroX déjà gérée.
  Le relâchement des touches/boutons maintenus lors du changement doit être
  vérifié en conditions réelles.
- Journal : `/userdata/system/logs/ultimate-wine-toolbox/antimicrox.log`, lignes
  contenant `AntiMicroX launcher`.

## Validation obtenue et cas restant à vérifier

Sur la machine Batocera v44/labwc de l’utilisateur :

- Profil launcher et profil jeu distincts, avec bascule sur un `.wine` : validé.
- Partage communautaire complet, puis téléchargement/réimport pour le même jeu
  en `.wsquashfs` : les deux profils et les règles correctes ont été retrouvés.
- Mapping natif via Moonlight avec la manette virtuelle Sunshine : validé après
  le correctif HIDAPI, avec reproduction du défaut sans ce réglage.

Ces résultats ne valident pas toutes les combinaisons de jeux/runners/manettes.
Pour les autres cas, vérifier notamment :

- Launcher séparé, puis jeu avec commandes natives.
- Même PID et même fenêtre dont le titre change.
- Retour du jeu au launcher et changement de profil dans les deux sens.
- Profils distincts, perte de focus, fermeture normale et Hotkey+Start.
- Règles sans effet sur la configuration en direct et sur les autres jeux.
- Manettes Sony et XInput ; vérifier touches, clics et sticks maintenus au
  moment des transitions.

Les tests automatisés simulent les fenêtres et l'IPC ; ils ne remplacent pas
ces vérifications sur le compositeur et AntiMicroX réels.

## Partage et transfert entre machines

Le partage d’un jeu avec launcher contient maintenant ses règles de fenêtres,
son profil launcher et, en mode deux profils, son profil jeu. Les identifiants
de manette et les chemins locaux ne sont pas transmis. La limite du service
reste de 64 Kio pour l’ensemble de la configuration. Le ZIP local accepte jusqu’à 1 000 configurations (2 Mio par configuration,
62 Mio de profils au total) et ne dépend pas de cette limite du service.

Dans **Mes jeux et leurs profils**, choisir le jeu puis **Partager ou exporter** :

- **Partager la configuration complète avec la communauté** : envoi pour validation.
- **Exporter la configuration complète dans un ZIP** : création locale sans publication.

Dans **Télécharger ou partager des profils > Partager et transférer des profils**,
l’action **Exporter des configurations
dans un ZIP** affiche une liste à cocher limitée aux jeux ayant un profil associé
disponible. Cochez un ou plusieurs jeux puis validez : un seul ZIP est créé dans
`exports/antimicrox/`. Les noms sont déduits automatiquement, sans question sur
le jeu, le pseudo ou la description. La mention **[Launcher]** repère les jeux
avec des règles configurées. Depuis le menu d’un jeu, l’export est immédiat et
contient uniquement sa configuration.

Sur l’autre machine, installer cette version de test ou une version ultérieure
compatible, puis télécharger le partage ou ouvrir **Télécharger ou partager des
profils > Partager et transférer des profils > Importer un paquet ZIP**. Pour un export groupé, toutes les configurations
sont importées et une liste permet de choisir celles à associer aux jeux de
la nouvelle machine. Choisir ensuite le jeu cible et l’option
**Utiliser ce profil pour un jeu** : les règles sont associées à ce jeu et les deux
profils sont conservés dans ses dossiers de configuration locaux. Aucun nouvel
apprentissage des fenêtres n’est nécessaire si les titres/classes/exécutables
correspondent à la même version du jeu. La langue ou une autre version du launcher
peut nécessiter d’ajuster une règle.

Les anciens partages sans règles restent utilisables. Les ZIP groupés demandent
une Toolbox compatible avec cet export. Les anciennes Toolbox qui téléchargent
un partage launcher `.amgp` voient un profil vide, pour éviter d’activer les
commandes du launcher pendant toute la partie.

Les ZIP de partage restent dans `exports/community/antimicrox/`, les exports
locaux dans `exports/antimicrox/`. Les profils source ne sont pas
modifiés et aucun jeu, préfixe Wine ou exécutable n’est ajouté au paquet.

## Lisibilité des menus

Les options des menus utilisent une écriture noire normale, les titres restent
en gras, la sélection reste en couleur et les menus utilisent la largeur du terminal et masquent les identifiants internes
des actions. **Texte complet** affiche l’intitulé sélectionné avec retour
à la ligne dans une fenêtre défilante, sans déclencher son action. Fermer cette
fenêtre ramène sur la même entrée. **[Launcher]** apparaît au début des lignes
dans la liste des jeux à partager ou exporter.

Les lettres rouges restent réservées aux menus d’actions. Les listes de jeux,
profils, fichiers, versions et sélections multiples ne colorent plus leur
initiale ; la navigation au clavier reste disponible. Lorsqu’une ligne ajoute
un profil, un état ou un auteur après le jeu, seul le nom du jeu est en gras.
Les listes de noms seuls restent en écriture normale.

Le lanceur du terminal conserve la couleur noire des noms en gras : le gras
ne transforme plus le noir en gris clair. Ce réglage s’applique au prochain
lancement complet de la Toolbox, y compris après le retour d’un jeu.

## Modifier séparément les deux profils

Dans **Mes jeux et leurs profils**, choisir le jeu puis **Modifier les commandes
du profil launcher** ou **Modifier les commandes du profil jeu**. Chacune de ces
actions propose **Modifier le profil en jeu** et **Modifier le profil sans lancer
le jeu**. Le profil sélectionné reste chargé durant l’édition en jeu. À la fin,
la Toolbox revient au menu du jeu sans remplacer l’association launcher par le
profil jeu. Les règles de bascule et l’autre profil sont conservés.

Dans **Modifier les fenêtres, le mode ou les profils associés**, deux choix
sont regroupés : modifier les règles avec le relevé existant, ou relancer le jeu
pour refaire le relevé. Il n’y a plus d’entrée de relevé séparée dans le menu
principal du jeu. L’action **Refaire le relevé des fenêtres** est réservée à la détection. Elle
réutilise le profil launcher associé, sans demander de créer ou choisir un
autre profil. Les modifications de commandes passent par les deux sous-menus
launcher/jeu décrits ci-dessus.

## Partage regroupé

Dans le menu d’un jeu, **Partager ou exporter** contient le partage communautaire
et l’export ZIP. Dans **Télécharger ou partager des profils**, **Partager et
transférer des profils** regroupe le partage complet d’un jeu, le partage d’un
profil seul, l’export groupé, l’import ZIP et les actions de modération.

## Désactiver ou supprimer

Les menus des jeux regroupent ces actions dans **Désactiver ou supprimer un profil / une configuration**.
Pour un launcher, trois choix sont proposés : retirer uniquement les règles
en conservant le profil actif, retirer toute la configuration en gardant les
fichiers profils, ou supprimer la configuration et ses profils non partagés.
La confirmation indique les fichiers à supprimer et ceux conservés parce
qu’ils sont référencés ailleurs, y compris comme profil jeu d’un autre launcher.
Le Pad2Key d’origine est restauré s’il avait été suspendu. Un échec annule
l’opération et conserve les données précédentes.

L’entrée principale propose **Jeux et leurs configurations** pour désactiver
ou supprimer une configuration, avec ou sans ses profils. **Profils sans jeu
associé** permet uniquement de nettoyer les fichiers inutilisés. Les profils
référencés par un jeu, dans l’un des deux rôles launcher/jeu ou comme dépendance
d’un paquet importé, restent protégés. Une association ajoutée après l’affichage
de la liste empêche également la suppression.


## Manette via Moonlight / Sunshine

Une manette virtuelle Sunshine peut être visible dans AntiMicroX sans que les
boutons réagissent. Le lanceur natif détecte les périphériques Sunshine présents
dans sysfs et définit `SDL_JOYSTICK_HIDAPI=0` uniquement pour AntiMicroX, afin
d’utiliser la réception evdev validée avec Sunshine/libvirtualhid. Ce choix
concerne tous les contrôleurs de cette instance AntiMicroX, pas les réglages
HIDRAW de Wine. Sans manette Sunshine, les réglages SDL existants sont conservés. Cette adaptation couvre
l’éditeur, les sessions en jeu et les changements de profil launcher/jeu.

Connecter Moonlight avant de lancer AntiMicroX ou le jeu. Si la manette virtuelle
apparaît alors qu’AntiMicroX était déjà ouvert, fermer puis relancer AntiMicroX
(ou le jeu qui le gère) pour appliquer cette détection au démarrage.
