# Test du classement des dossiers contenant des fichiers INI

Les indices `sav`, `slot` et `user` dans les noms de fichiers donnent déjà un bonus important, indépendant de la casse, même pour des fichiers texte ou sans extension. Les `.ini` sont désormais exclus de ce bonus de nom. Un dossier contenant uniquement des `.ini` utiles perd 10 points mais reste candidat dans un emplacement normal. Les journaux temporaires sont ignorés pour cette comparaison. Un `.ini` à côté d’une vraie sauvegarde ne pénalise pas le dossier et ne gonfle pas le bonus.

Le classement reste une heuristique : vérifier le contenu et le chargement de la progression. Les chemins de dossiers et les extensions continuent à contribuer au score.

Installation SSH (version inchangée, seule la fonction de calcul du score est remplacée) :

```bash
curl -fL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/fix/save-ini-ranking/scripts/install-save-ini-ranking-test.py -o /tmp/uwt-save-ini-test.py && python3 /tmp/uwt-save-ini-test.py
```

Reprendre la recherche des sauvegardes pour recalculer les scores. Le correctif ne modifie ni les fichiers du jeu ni les sauvegardes. Il peut coexister avec le test du retour au premier plan.

Retrait hors ligne :

```bash
python3 /userdata/system/ultimate-wine-toolbox/state/save-ini-ranking-test/installer.py --restore
```

L’installation et le retrait préservent les autres modifications du helper. Une fonction de score différente de la version attendue provoque un arrêt explicite sans modification.

Tests ciblés : maintien des dossiers INI dans les candidats, casse `.INI`, plusieurs INI sans cumul de bonus, dossier mixte sans pénalité, classement `UserSettings.ini` dans Documents sous `slot01.dat`, ainsi que les régressions existantes sav/slot/user, fichiers texte/sans extension et caches. Installation répétée et restauration hors ligne vérifiées avec des modifications locales avant et après installation. Validation du classement réel de Ninja Gaiden 4 à effectuer par l’utilisateur.
