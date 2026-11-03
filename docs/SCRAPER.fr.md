# Intégration du scrap dans Ports

L’installation ajoute les médias de la Toolbox et complète les métadonnées
manquantes de son entrée Ports. Les images sont livrées en JPG optimisé et
le logo conserve son format PNG transparent, dans les archives sources comme
dans les releases. Aucune conversion n’est nécessaire sur Batocera.

## Synchronisation avec EmulationStation

Quand ES tourne, l’installateur synchronise les métadonnées en mémoire et la
gamelist, puis vérifie les deux. Un système Ports natif peut aussi être un
groupe : le propriétaire de l’entrée est vérifié pour éviter de modifier les
entrées des sous-systèmes, notamment le lanceur technique de retour Toolbox.

Si l’import XML renvoie HTTP 204 pour une entrée existante, les API dédiées
aux métadonnées et aux médias prennent le relais. Le contenu des fichiers et
les chemins choisis par ES sont vérifiés avant l’enregistrement du XML.
Les statistiques et les médias personnalisés sont conservés. Aucun
rechargement global d’ES n’est demandé.

Quand ES est arrêté, le XML est modifié de manière atomique. Quand ES tourne
mais que son API est indisponible, le scrap est signalé comme incomplet sans
écriture directe susceptible d’être écrasée. Réinstaller lorsque l’API est
accessible permet de terminer cette étape.

## Sauvegardes et journal

Une gamelist existante est sauvegardée avant modification dans :

`/userdata/system/backups/ultimate-wine-toolbox/scraper/`

Le journal conserve le résultat et les erreurs utiles dans :

`/userdata/system/logs/ultimate-wine-toolbox/scraper-install.log`

Il n’inclut pas de copie complète du XML envoyé. Une réussite en ligne est
signalée par `mode=api; memory and gamelist verified`. Un fichier personnalisé
différent déjà présent à la destination des médias d’ES est conservé et le
conflit est signalé dans ce journal.
