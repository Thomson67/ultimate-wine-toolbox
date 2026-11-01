# Clavier virtuel à la manette

Disponible dans Ultimate Wine Toolbox depuis la version **0.10.0**. Désactivé par défaut.

## Activer le clavier

1. Ouvrir **Ports > Ultimate Wine Toolbox > Paramètres > Clavier virtuel à la manette**. L’entrée est aussi accessible dans les réglages graphiques et outils.
2. Choisir **Régler un jeu**, sélectionner le jeu puis **Activé**. Une activation globale pour les jeux Windows est aussi possible ; les choix par jeu restent prioritaires.
3. Fermer puis relancer le jeu pour appliquer le changement. Sélectionner le champ de texte avant d’ouvrir le clavier.
4. Appuyer puis relâcher **Hotkey + Select**, selon la configuration de la manette dans Batocera. Par exemple PS + Create si PS est la Hotkey d’une DualSense. Les deux boutons doivent être distincts.

## Retrouver les jeux configurés

**Gérer les jeux configurés** liste uniquement les règles personnelles activées ou désactivées, sans analyser toute la collection. Sélectionner un jeu pour changer sa règle ou choisir **Suivre le réglage global** afin de retirer son exception. Les jeux activés uniquement par le réglage global ne figurent pas dans cette liste.

## Saisir et corriger le texte

- Croix directionnelle ou stick gauche : sélectionner une touche.
- Bouton du bas (Croix PS / A Xbox) : saisir la touche sélectionnée.
- Bouton de droite (Rond PS / B Xbox) : fermer le clavier.
- Bouton de gauche (Carré PS / X Xbox) : effacer le caractère précédent.
- Bouton du haut (Triangle PS / Y Xbox) : espace.
- L1 : majuscules ; R1 : chiffres et signes ; Start : Entrée puis fermeture.
- Touches **← ↓ ↑ →** : déplacer le curseur dans le texte. **Début**, **Fin** et **Suppr** permettent d’éditer la ligne.
- **Hotkey + Select** masque aussi le clavier ; **Hotkey + Start** conserve la sortie du jeu.

AZERTY et QWERTY suivent la langue de la Toolbox ; la disposition du bureau doit permettre les caractères choisis. Aucun texte saisi n’est enregistré.

## AntiMicroX et fenêtres compatibles

Le clavier fonctionne sur les fenêtres Wine X11/XWayland, y compris les launchers comme le Notepad de Beyond Good & Evil. Les fenêtres Wine Wayland natives ne sont pas prises en charge.

Select seul peut garder son action AntiMicroX. La Toolbox réserve Hotkey + Select dans un profil temporaire et capture les événements de la manette pendant la saisie. La fermeture libère les commandes sans recharger de profil ; les profils enregistrés restent intacts. Les conflits Pad2Key ou les profils incompatibles sont signalés.

Le jeu n’est pas mis en pause. Un jeu lisant directement HIDRAW peut encore recevoir des boutons : vérifier son comportement avant une saisie importante.

## Vérifier ou désactiver

Le menu propose un aperçu sans saisie qui se ferme après **10 secondes**.
L’aide intégrée est accessible dans **Documentation > Clavier virtuel à la manette**. Aucun composant manquant n’est installé automatiquement.

Journal : `/userdata/system/logs/ultimate-wine-toolbox/virtual-keyboard.log`.

Pour désactiver partout, couper le global et remettre les jeux explicitement activés sur **Suivre le réglage global** ou **Désactivé**, puis fermer les jeux. Pour un seul jeu, choisir **Désactivé** dans sa règle.

Validation matérielle : ouverture rapide dès le premier raccourci, priorité sur AntiMicroX, D-pad/stick, saisie, flèches et Entrée confirmés par l’utilisateur sur Batocera v44, en jeu et dans le Notepad du launcher BG&E.
