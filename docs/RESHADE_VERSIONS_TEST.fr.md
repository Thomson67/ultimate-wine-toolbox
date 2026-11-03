# Test du choix des versions ReShade

Branche : `feat/reshade-version-catalog`. La version stable reste inchangée.

Dans **Outils et compatibilité → ReShade → jeu → Installer / modifier version et shaders**, choisir l’exécutable, l’API, puis une version dans la liste. En 6.4.1, un second écran propose la variante officielle ou **Sans bannière de démarrage**, provenant de fienestar/OverlayDisabledReShade. Retour depuis cet écran revient aux versions.

Versions officielles proposées : 6.8.0, 6.7.3, 6.7.2, 6.7.1, 6.7.0, 6.6.2 et 6.4.1. La seule variante sans bannière proposée est la 6.4.1 publiée par son auteur. Le menu Home reste disponible ; certains shaders récents peuvent demander une version plus récente.

Les jeux `.wine`, `.pc` et `.wsquashfs` restent pris en charge. Les installations ReShade déjà intégrées aux jeux conservent leur gestion distincte. Les presets et réglages existants sont conservés lors des changements de version.

Le catalogue est livré avec la Toolbox. Il ne met pas automatiquement à niveau les jeux. Chaque build possède un cache séparé et un journal de provenance ; le SHA-256 de l’installateur et l’architecture des deux DLL sont vérifiés avant publication dans ce cache.

Le backend ReShade Linux est actualisé vers 1.4.1, avec source épinglée et vérifiée. L’appel sans interaction évite une attente de saisie dans le terminal. L’adaptateur des Batocera sans Git prend en charge les commits de shaders épinglés par cette version.

Pour les builds 6.4.1 absents du catalogue interne du backend, celui-ci prépare les shaders et le compilateur avec son moteur 6.8.0 vérifié ; la Toolbox sélectionne ensuite la DLL 6.4.1 exacte, officielle ou sans bannière. Le cache officiel du backend reste séparé de ces variantes.

Validation automatisée : choix/retour/annulation du sélecteur, isolement des variantes, refus des téléchargements invalides, réparation du cache corrompu, conservation du preset lors du changement de build, protection des modifications locales des shaders. Installation complète vérifiée avec le backend réel 1.4.1, les deux installateurs réels 6.4.1 et les packs Standard, en utilisant l’adaptateur sans Git.

À vérifier sur Batocera : installation d’une version officielle, passage à la 6.4.1 sans bannière, lancement sans bandeau, ouverture du menu Home, conservation du preset, retour vers une version officielle. Le rendu nécessite une vérification en jeu sur le matériel.

Journaux : `/userdata/system/logs/ultimate-wine-toolbox/reshade-install-*.log` et `reshade-game-event.log`.

Pour revenir au code stable, fermer la Toolbox puis utiliser la commande d’installation stable habituelle. Cela conserve les données de configuration. Pour remettre un jeu sur une version officielle, la sélectionner avant de revenir au code stable.
