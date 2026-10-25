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

1. Toolbox → AntiMicroX → **10. Configurer un jeu avec launcher (test)**.
2. Choisir le jeu, puis **Apprendre les fenêtres et configurer le mapping en jeu**.
3. Créer un profil ou choisir un profil existant. La configuration en direct
   utilise toujours un profil manuel, sans bascule automatique. Hotkey+R1,
   Alt+Tab et l'exclusion temporaire d'ES restent ceux de la v0.7.2.
4. Afficher le launcher, enregistrer son mapping dans AntiMicroX. Afficher
   ensuite le jeu quelques secondes, puis quitter le jeu normalement.
5. Au retour, choisir **Configurer les règles launcher / jeu (test)**.
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
la même session. **Même profil pour toute la session** revient au comportement
classique en retirant les règles de ce jeu.

Le menu de test permet aussi de consulter ou désactiver les règles. Aucun
nom de jeu ou suffixe `[L]` n'active cette fonctionnalité automatiquement.

L'installateur accepte également les fichiers exacts du premier test launchers
pour une mise à jour sur place. Les profils et règles déjà enregistrés sont
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
