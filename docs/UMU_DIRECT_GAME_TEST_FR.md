# Test de compatibilité UMU : chemin direct

Option facultative dans autorun.cmd : `ENV=UMU_DIRECT_GAME=1`.
Si ENV existe déjà, ajouter UMU_DIRECT_GAME=1 sur cette ligne.
Le mode standard reste la valeur par défaut ; supprimer la variable pour revenir au comportement standard.

La version test des deux toolboxes est nécessaire pour le workflow. Après installation de UMU Runner Toolbox, lancer Maintenance > Réparer / mettre à niveau l’intégration UMU afin de mettre à jour les wrappers des runners sains et leurs manifests. Ne pas remplacer directement bin/wine dans un runner protégé.

Dans Ultimate Wine Toolbox : création WSquashFS > premier essai > options par jeu > Compatibilité UMU : lancement direct (expérimental), puis relancer. Le choix est conservé dans l’archive finale et peut aussi être retiré dans ce menu.

Le mode direct conserve le préfixe matérialisé, sa persistance, la protection des runners et le Steam Runtime. Pour .wine, il utilise le répertoire original. Pour .wsquashfs/.wtgz, il utilise le montage merged-prefixes existant (OverlayFS complet et inscriptible) sans monter de gameviews supplémentaire. Aucune extraction du jeu au lancement.

## Validation Batocera encore nécessaire

1. Azimuth .wine + GE-Proton11-7-UMU, option activée : launcher, jeu, arrêt et relancement.
2. Azimuth .wsquashfs, même runner : launcher, jeu, écritures/sauvegardes et relancement.
3. Un jeu connu sans option : lancement, sauvegardes et relancement identiques.
4. Désactiver l’option : vérifier le retour au mode standard.

Les logs doivent indiquer umu_direct_game=1, runtime_gameview_bypassed=1 et runtime_gameview_bind=0. Pour les archives, runtime_game_source doit rester sous merged-prefixes, jamais le lowerdir SquashFS seul.

Les tests statiques et simulés ne valident pas le comportement d’Azimuth dans pressure-vessel : le montage compressed doit être testé sur Batocera avant toute release.
