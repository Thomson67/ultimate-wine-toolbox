# Test de synchronisation du scrap avec EmulationStation

Cette branche conserve les ajouts ReShade et les thèmes de la branche
`feat/reshade-version-catalog`, et corrige l'installation des métadonnées Ports.

## Changements

- Les archives sources et les releases contiennent les JPG optimisés ; aucune
  conversion ni dépendance d'imagerie supplémentaire n'est nécessaire sur Batocera.
- Quand ES tourne, l'installateur importe l'entrée via son API locale. Il conserve
  les statistiques et les personnalisations en mémoire et vérifie les champs
  sur disque ainsi que dans ES. Il n'envoie aucun rechargement global des jeux.
- Quand ES est arrêté, la modification du XML reste atomique et sauvegardée.
- Quand ES tourne mais que son API est indisponible, l'installation de la Toolbox
  continue avec un avertissement pour le scrap. Le XML n'est pas modifié par une
  méthode susceptible d'être écrasée. Réinstaller une fois l'API accessible.
- Le journal persistant est dans
  `/userdata/system/logs/ultimate-wine-toolbox/scraper-install.log`.
  Le manifeste SHA-256 reste uniquement la preuve de la copie des médias.
- La commande inexistante `batocera-es-swissknife --update-gamelists` est retirée.

L'API `/addgames` et la lecture des métadonnées avec `localpaths=true` ont été
vérifiées dans les sources d'ES utilisées par Batocera 43, commit
`68f45afb03cdad1209633fc553143238714f3592`, et dans les sources actuelles.

## Validation sur Batocera

1. Fermer la Toolbox, puis installer cette branche depuis SSH, ES restant ouvert.
2. Vérifier le scrap de l'entrée Ultimate dans Ports, puis lancer et fermer la
   Toolbox. Vérifier à nouveau après un redémarrage normal d'ES.
3. Consulter `scraper-install.log`. Le chemin en ligne doit indiquer
   `mode=api; memory and gamelist verified`.
4. Vérifier la conservation des statistiques, du scrap UMU et, le cas échéant,
   des médias personnalisés.

Avant chaque import modifiant une gamelist existante, une copie est conservée
sous `/userdata/system/backups/ultimate-wine-toolbox/scraper/`.

Les tests automatisés reproduisent la réécriture depuis les métadonnées en
mémoire, sans constituer une validation visuelle dans ES sur une machine réelle.
La cause historique exacte de l'installation du 21 octobre n'est pas établie.
