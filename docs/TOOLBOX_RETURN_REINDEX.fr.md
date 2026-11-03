# Retour dans la Toolbox sans recharger toute la collection

Ce correctif vise le cas où une première demande de retour via ES reste sans confirmation, puis une seconde aboutit dix secondes plus tard. Les journaux observés montraient ce comportement. Plusieurs tests et retours utilisateur ont validé le correctif sans nouvelle occurrence du problème ; ils ne permettent pas d’isoler une cause unique pour tous les retards possibles.

Le lanceur technique de retour est vérifié et réutilisé s’il est inchangé et déjà enregistré dans ES. Une actualisation est conservée si ce lanceur est absent, si sa définition change ou si ses entrées masquées doivent être réparées. Les statistiques ES sont conservées. Les fichiers identiques ne sont plus réécrits inutilement.

Le retour reste lancé par EmulationStation pour conserver son fonctionnement natif et les commandes manette. La confirmation du retour, le verrou entre workflows et les contrôles de propriété sont maintenus. Si le lanceur est déjà en cours de démarrage, une seconde demande n’est pas envoyée pendant cette tentative. Aucun jeu tiers n’est arrêté.

## Installation stable

Le correctif est inclus dans la version 0.10.2. Fermer les jeux et la Toolbox puis utiliser la mise à jour habituelle. Les réglages sont conservés.

## Vérifier

Faire plusieurs retours après un test de jeu, avec la méthode habituelle de fermeture. Comparer les retours successifs, y compris après un redémarrage de Batocera. Si le lanceur doit être créé ou actualisé, le premier retour peut encore déclencher une mise à jour de l’index.

Le journal `/userdata/system/logs/ultimate-wine-toolbox/port-launch.log` indique maintenant le temps écoulé, la réponse HTTP à la demande, la durée des appels et les changements d’état d’ES.

```bash
grep 'Toolbox return:' /userdata/system/logs/ultimate-wine-toolbox/port-launch.log | tail -n 70
```

Pour un lanceur réutilisé, chercher `Reusing indexed Toolbox return entry; no ES reload`, puis `attempt=1` et `confirmed`. Si le problème persiste, fournir ces lignes avec le nom du jeu et la façon de quitter.
