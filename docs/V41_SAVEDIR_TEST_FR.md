# SAVEDIR sur Batocera 41 — essai expérimental

Ce correctif concerne uniquement Batocera 41 et les lancements `.wine` et `.wsquashfs` par `batocera-wine`. Il n’installe aucun runner et ne change pas la gestion des versions 40 ou 42+.

Dans **Gestion des WSquashFS → Compatibilité SAVEDIR — Batocera 41**, choisir **Activer maintenant et à chaque démarrage**. Le lanceur original est conservé dans `/userdata/system/ultimate-wine-toolbox/v41-savedir/original.sh`. Deux appels sont ajoutés, juste avant les lancements Wine et WSquashFS, après préparation du préfixe/overlay.

Le service utilisateur `uwt_v41_savedir` réapplique le correctif à chaque démarrage de v41. Il est activé/désactivé via la Toolbox et enregistré par `batocera-services`, sans remplacer les autres services. Un passage en v42 ou supérieure rend le service inactif sans modifier le nouveau lanceur. Ne pas lancer `batocera-save-overlay` pour cet essai. Le bouton de retrait et la désinstallation de la Toolbox restaurent le script original seulement si son empreinte est reconnue. Une modification concurrente du lanceur bloque la restauration automatique.

## Sauvegardes

- `SAVEDIR=drive_c/game/save/` redirige le dossier vers `/userdata/saves/windows/<nom sans extension>`.
- `SAVEDIR=.` et `SAVEFILES=user.reg` redirigent uniquement le registre ; les autres fichiers du préfixe restent en place.
- Plusieurs fichiers sont séparés par `;`. Les motifs de noms simples peuvent sélectionner les fichiers présents dans le dossier local ou externe.
- Les fichiers externes existants sont prioritaires. Les fichiers locaux absents du dossier externe y sont copiés. Avant de remplacer des données locales par des liens, une copie est conservée dans `.uwt-v41-backups`, sous les sauvegardes du jeu.
- Les chemins hors préfixe, racines générales de profils, liens de sauvegarde vers une autre destination et liens imbriqués inattendus sont refusés. Une erreur empêche le lancement, plutôt que lancer avec une mauvaise redirection.
- Aucun code n’est injecté dans l’archive : l’original WSquashFS reste intact. Les liens créés pour le lancement sont dans sa couche écrivable.

## Validation sur machine

1. Activer sur une v41 et confirmer qu’un jeu sans SAVEDIR démarre normalement.
2. Tester un `.wine` avec SAVEDIR : sauvegarder, quitter, relancer, retrouver la progression.
3. Tester son équivalent WSquashFS : sauvegarder, quitter, relancer. Vérifier que l’archive n’a pas changé.
4. Faire un essai avec une sauvegarde externe plus récente que celle du préfixe : elle doit être conservée.
5. Tester un jeu utilisant `SAVEFILES=user.reg`, puis un jeu utilisant plusieurs fichiers.
6. Redémarrer sans réactiver manuellement le correctif, puis retrouver la progression. Le journal de démarrage est `/userdata/system/logs/ultimate-wine-toolbox/v41-savedir-boot.log`.
7. Désactiver dans la Toolbox : comparer le lanceur au fichier original, puis redémarrer et confirmer que le correctif ne revient pas. Les sauvegardes et leurs copies sont conservées ; leur redirection n’est pas annulée dans les préfixes déjà utilisés.

Les tests automatisés vérifient la redirection, la priorité externe, les copies de sécurité, les refus de chemins et l’installation/retrait du patch. Ils ne remplacent pas les essais sur Batocera 41, notamment avec ses montages OverlayFS et les runners UMU.
