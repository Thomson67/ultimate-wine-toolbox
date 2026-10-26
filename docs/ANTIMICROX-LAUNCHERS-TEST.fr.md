# Test AntiMicroX : jeux avec launcher

Base : Ultimate Wine Toolbox v0.7.2. Aucun changement des archives de jeux,
des scripts Windows ou de Sunshine. Les launchers embarquant déjà AntiMicroX
Windows ne sont pas migrés : choisir pour le premier essai un préfixe/jeu
utilisant seulement l'instance native gérée par la Toolbox.

## Installer

Fermer le jeu, AntiMicroX et la Toolbox. Lancer l'installateur de cette branche
avec `--ref` suivi du SHA complet du commit à tester. Il vérifie la v0.7.2 et
les fichiers d'origine, télécharge et valide les fichiers avant de remplacer
le module, le helper et les deux copies du hook. Il imprime la commande de
restauration, conservée avec sa sauvegarde sous `state/backups`.

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
   peut exclure des versions ou compteurs variables.
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

**Désactiver les règles launcher (garder le profil)** revient au menu classique
du même jeu. **Désactiver AntiMicroX pour ce jeu** retire les règles et
l'association, sans supprimer les fichiers profils. Modifier le profil jeu ne
réaffecte pas ce profil à la place du profil launcher.

Le menu de test permet aussi de consulter ou désactiver les règles. Aucun
nom de jeu ou suffixe `[L]` n'active cette fonctionnalité automatiquement.

L'installateur accepte également les fichiers exacts des deux premiers tests
launchers pour une mise à jour sur place. Les profils et règles déjà enregistrés sont
conservés ; un fichier de code modifié manuellement est refusé.

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

## Validation avant publication

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
reste de 64 Kio pour l’ensemble de la configuration. Le transfert local par ZIP
accepte jusqu’à 2 Mio et ne dépend pas de cette limite du service.

Dans **Mes jeux et leurs profils**, choisir le jeu puis :

- **Partager la configuration complète avec la communauté** : envoi pour validation.
- **Exporter la configuration complète dans un ZIP** : création locale sans publication.

Ces deux actions sont aussi accessibles directement dans **Télécharger ou partager
des profils** : **Partager la configuration d’un jeu (profils et règles launcher)**
et **Exporter la configuration d’un jeu dans un ZIP**. Elles affichent uniquement les jeux ayant un profil associé disponible, puis
récupèrent ce profil et ses règles automatiquement. La mention **[Launcher]**
repère les jeux dont les règles launcher sont configurées.

Sur l’autre machine, installer cette version de test ou une version ultérieure
compatible, puis télécharger le partage ou ouvrir **Télécharger ou partager des
profils > Importer un paquet ZIP**. Choisir ensuite le jeu cible et l’option
**Utiliser ce profil pour un jeu** : les règles sont associées à ce jeu et les deux
profils sont conservés dans ses dossiers de configuration locaux. Aucun nouvel
apprentissage des fenêtres n’est nécessaire si les titres/classes/exécutables
correspondent à la même version du jeu. La langue ou une autre version du launcher
peut nécessiter d’ajuster une règle.

Les anciens partages sans règles restent utilisables. Les anciennes Toolbox
ne savent pas importer ce nouveau paquet : elles voient un profil vide, pour
éviter d’activer les commandes du launcher pendant toute la partie.

Le ZIP reste dans `exports/community/antimicrox/`. Les profils source ne sont pas
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
