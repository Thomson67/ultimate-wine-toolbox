# Clavier virtuel à la manette — premier test

Cette branche ajoute un clavier facultatif pour les jeux Windows dans Ultimate Wine Toolbox. La version stable reste inchangée. Le raccourci retenu après vérification de la configuration utilisateur est **Hotkey + Select**, soit **PS + Create** avec cette DualSense.

## Installer la branche de test

Fermer les jeux et la Toolbox, puis lancer sur Batocera :

```bash
curl -fL https://github.com/Thomson67/ultimate-wine-toolbox/archive/refs/heads/feature/virtual-keyboard.zip -o /tmp/uwt-keyboard-test.zip &&
unzip -oq /tmp/uwt-keyboard-test.zip -d /tmp/uwt-keyboard-test &&
bash /tmp/uwt-keyboard-test/ultimate-wine-toolbox-feature-virtual-keyboard/package-install.sh
```

L'installateur conserve les réglages et sauvegarde la précédente Toolbox. Aucun jeu, runner ni fichier Pad2Key n'est modifié par la fonction clavier.

## Premier essai

1. Ouvrir **Ports > Ultimate Wine Toolbox > Paramètres > Clavier virtuel à la manette (test)**. La même entrée est accessible dans les outils.
2. Lancer **Vérifier les composants et la manette**. En cas d'erreur, fournir le texte du diagnostic avant de tenter un jeu.
3. Utiliser **Aperçu sans saisie** pour vérifier le rendu. Il ne capte pas la manette et se ferme après 20 secondes ; ses touches ne sont pas envoyées au système.
4. Laisser le global désactivé. Dans **Régler un jeu**, sélectionner un jeu permettant de saisir un nom et choisir **Activé**.
5. Lancer ce jeu depuis EmulationStation et sélectionner son champ de saisie.
6. Appuyer sur **PS + Create**, puis relâcher. Utiliser le stick gauche ou la croix directionnelle pour déplacer la sélection, puis Croix pour saisir.
7. Rond masque le clavier ; Carré efface, Triangle ajoute un espace, L1 change la casse et R1 affiche les chiffres/signes. Start envoie Entrée et masque le clavier.
8. Vérifier le retour normal des commandes au jeu, puis quitter et relancer. Vérifier également **PS + Start** lorsque le clavier est visible.

Après validation d'un jeu, l'activation globale peut être utilisée. Les exceptions par jeu ont priorité : **Suivre le global / Activé / Désactivé**.

## Limites à vérifier sur Batocera

- Première cible : fenêtres Wine X11/XWayland, avec runners classiques ou UMU. Pas de prise en charge des fenêtres Wine Wayland natives à ce stade.
- Le clavier ne prend pas le focus au jeu. Il utilise GTK, GtkLayerShell sur Wayland, python-evdev, uinput et la disposition XKB du bureau. Le diagnostic annonce un composant manquant sans modifier le système.
- Les codes Linux de la manette doivent être présents dans la configuration EmulationStation ; Hotkey et Select doivent être deux boutons distincts.
- Une affectation concurrente de Select ou de Hotkey seul dans Pad2Key/AntiMicroX est refusée. Le repli Select de l'éditeur AntiMicroX est réservé lorsque le clavier est activé pour ce jeu.
- La capture temporaire des événements manette n'empêche pas nécessairement une lecture HIDRAW directe par le jeu. Vérifier qu'aucune action indésirable ne se produit pendant la saisie. Le jeu n'est pas mis en pause.
- Le texte saisi n'est ni enregistré ni copié dans le presse-papiers.

Journal : `/userdata/system/logs/ultimate-wine-toolbox/virtual-keyboard.log`.

## Désactiver ou revenir à la stable

Pour désactiver : mettre le global sur Désactivé et les jeux explicitement activés sur Suivre le global ou Désactivé. Fermer le jeu pour appliquer.

Pour retirer complètement le test, fermer jeux et Toolbox, puis :

```bash
python3 /userdata/system/ultimate-wine-toolbox/toolbox/helpers/virtual_keyboard.py stop &&
rm -f /userdata/system/scripts/ultimate-wine-toolbox-virtual-keyboard.sh &&
curl -fsSL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/main/install.sh | bash
```

Les réglages du clavier restent conservés sans être utilisés par la stable. Les sauvegardes de jeux sont indépendantes.
