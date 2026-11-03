# Thèmes de la Toolbox

Dans **Paramètres → Affichage → Thème de la Toolbox**, quatre palettes sont disponibles :

| Thème | Palette |
| --- | --- |
| Standard | Fenêtres claires et sélection bleue |
| Sombre | Fond noir, texte clair et sélection cyan |
| Daltonisme | Bleu et jaune, sans rouge/vert |
| Contraste élevé | Noir et blanc, sélection sur fond inversé |

La sélection reste identifiable par son fond ; les cases conservent leurs marqueurs. La palette Daltonisme vise à réduire la dépendance au rouge et au vert ; elle ne remplace pas une validation visuelle par les personnes concernées.

Le choix s’applique immédiatement pour aperçu. Confirmer pour le conserver, ou choisir Non/Échap pour rétablir le thème précédent. Le choix confirmé est enregistré dans `config/theme` et relu aux prochains lancements. Une valeur absente ou invalide revient à Standard.

Le thème s’applique aux menus, confirmations, saisies, sélecteurs de fichiers en mode texte, messages et barres de progression. Les fenêtres graphiques externes (AntiMicroX, sélecteur GTK, etc.) gardent leur propre apparence.

Les palettes utilisent les huit couleurs du terminal pour rester compatibles avec Xorg et Wayland. Les couleurs sont activées dans une copie temporaire du thème Dialog, ce qui corrige les défauts monochromes constatés sous Xorg. Les fichiers de configuration globaux de Batocera et du terminal restent inchangés.

Le clavier virtuel reste accessible dans **Outils et compatibilité**. Son entrée redondante dans Paramètres est retirée ; ses réglages sont conservés.

Pour tester : changer plusieurs fois de palette, vérifier menu/confirmation/saisie et revenir à Standard, annuler un aperçu, puis relancer la Toolbox pour vérifier le choix enregistré.
