# Compatibilité UMU : chemin direct

Option facultative dans autorun.cmd : `ENV=UMU_DIRECT_GAME=1`.
Si ENV existe déjà, ajouter UMU_DIRECT_GAME=1 sur cette ligne.
Le mode standard reste la valeur par défaut ; supprimer la variable pour revenir au comportement standard.

UMU Runner Toolbox 0.13.7 et Ultimate Wine Toolbox 0.5.4 ou plus sont nécessaires pour le workflow. Après installation de UMU Runner Toolbox, lancer Maintenance > Réparer / mettre à niveau l’intégration UMU afin de mettre à jour les wrappers des runners sains et leurs manifests. Ne pas remplacer directement bin/wine dans un runner protégé.

Dans Ultimate Wine Toolbox : création WSquashFS > premier essai > options par jeu > Compatibilité UMU : lancement direct, puis relancer. Le choix est conservé dans l’archive finale et peut aussi être retiré dans ce menu.

Le mode direct conserve le préfixe matérialisé, sa persistance, la protection des runners et le Steam Runtime. Pour .wine, il utilise le répertoire original. Pour .wsquashfs/.wtgz, il utilise le montage merged-prefixes existant (OverlayFS complet et inscriptible) sans monter de gameviews supplémentaire. Aucune extraction du jeu au lancement.

## Contrôles après installation

1. Azimuth .wine + GE-Proton11-7-UMU, option activée : launcher, jeu, arrêt et relancement.
2. Azimuth .wsquashfs, même runner : launcher, jeu, écritures/sauvegardes et relancement.
3. Un jeu connu sans option : lancement, sauvegardes et relancement identiques.
4. Désactiver l’option : vérifier le retour au mode standard.

Les logs doivent indiquer umu_direct_game=1, runtime_gameview_bypassed=1 et runtime_gameview_bind=0. Pour les archives, runtime_game_source doit rester sous merged-prefixes, jamais le lowerdir SquashFS seul.

Validation utilisateur obtenue sur Batocera avec GE-Proton11-7-UMU : lancement, sauvegarde et reprise de progression en .wine et .wsquashfs.

## Sauvegardes refusant les liens et points de montage

Quand UMU_DIRECT_GAME=1 est actif, le wrapper remplace temporairement le lien du SAVEDIR déclaré dans autorun.cmd par un vrai dossier contenant une copie de sa cible sous /userdata/saves/windows. Aucun montage bind n’est utilisé pour ce dossier de sauvegardes : Wine peut signaler un changement de système de fichiers comme point de réanalyse, refusé par certains jeux. Ce traitement est limité aux sauvegardes à l’intérieur du répertoire du jeu ; les dossiers réels et les sauvegardes hors du jeu ne sont pas convertis.

À la fermeture, une copie complète des sauvegardes du jeu est préparée à côté de la cible persistante, avant de remplacer celle-ci. L’état précédent est conservé temporairement sous <cible>.umu-direct-previous jusqu’à la synchronisation et la restauration du lien, puis déplacé dans <cible>/.umu-direct-previous. Une seule génération est conservée. Ce sous-dossier réservé est exclu de la copie au lancement et de la synchronisation afin de ne pas accumuler des sauvegardes imbriquées. Les suppressions de fichiers effectuées par le jeu sont ainsi répercutées. Le lien original, conservé sous <dossier>.umu-direct-link pendant la session, est restauré seulement après synchronisation réussie. Sans UMU_DIRECT_GAME=1, aucun de ces traitements ne s’exécute.

Logs attendus : direct_save_copy=1, direct_save_path=..., direct_save_source=..., puis direct_save_sync=ok et direct_save_link_restored=... à la fermeture.

En cas d’échec de la copie initiale, le lien et les sauvegardes persistantes restent inchangés et le lancement est refusé. En cas d’échec de synchronisation, le vrai dossier de jeu et son lien de secours restent présents pour récupération ; le lancement suivant est refusé afin de ne pas les écraser. Un arrêt forcé du wrapper (SIGKILL, coupure) peut nécessiter une récupération manuelle. Ne pas supprimer ces dossiers ou refaire le packaging avant récupération. Le mode copie nécessite de l’espace libre sur les systèmes de fichiers du jeu et des sauvegardes et ajoute un délai proportionnel à leur taille.

Validation Batocera : relancer Azimuth .wine avec SAVEDIR et vérifier jeu, sauvegarde, fermeture, restauration du lien et relancement ; vérifier ensuite le même comportement en .wsquashfs.
