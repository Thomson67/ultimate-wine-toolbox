# Test : retour dans la Toolbox sans recharger toute la collection

Ce correctif vise le cas où une première demande de retour via ES reste sans confirmation, puis une seconde aboutit dix secondes plus tard. Les journaux observés montrent ce comportement ; le rechargement systématique des jeux est une cause possible, pas encore prouvée sur matériel.

Le lanceur technique de retour est vérifié et réutilisé s’il est inchangé et déjà enregistré dans ES. Une actualisation est conservée si ce lanceur est absent, si sa définition change ou si ses entrées masquées doivent être réparées. Les statistiques ES sont conservées. Les fichiers identiques ne sont plus réécrits inutilement.

Le retour reste lancé par EmulationStation pour conserver son fonctionnement natif et les commandes manette. La confirmation du retour, le verrou entre workflows et les contrôles de propriété sont maintenus. Si le lanceur est déjà en cours de démarrage, une seconde demande n’est pas envoyée pendant cette tentative. Aucun jeu tiers n’est arrêté.

## Installer

Fermer les jeux et la Toolbox, puis installer l’archive de la branche `fix/toolbox-return-reindex` avec son `package-install.sh`. La version affichée reste 0.10.1 pendant ce test ; la release stable n’est pas modifiée. Les réglages sont conservés.

## Vérifier

Faire plusieurs retours après un test de jeu, avec la méthode habituelle de fermeture. Comparer les retours successifs, y compris après un redémarrage de Batocera. Si le lanceur doit être créé ou actualisé, le premier retour peut encore déclencher une mise à jour de l’index.

Le journal `/userdata/system/logs/ultimate-wine-toolbox/port-launch.log` indique maintenant le temps écoulé, la réponse HTTP à la demande, la durée des appels et les changements d’état d’ES.

```bash
grep 'Toolbox return:' /userdata/system/logs/ultimate-wine-toolbox/port-launch.log | tail -n 70
```

Pour un lanceur réutilisé, chercher `Reusing indexed Toolbox return entry; no ES reload`, puis `attempt=1` et `confirmed`. Si le problème persiste, fournir ces lignes avec le nom du jeu et la façon de quitter.

## Revenir à la stable

Fermer les jeux et la Toolbox puis réinstaller la release avec la commande normale :

```bash
curl -fsSL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/main/install.sh | bash
```
