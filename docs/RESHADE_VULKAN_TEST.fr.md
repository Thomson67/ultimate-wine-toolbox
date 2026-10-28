# Test ReShade Vulkan dans la Toolbox 0.8.1

Ce test étend l’intégration ReShade existante. Les packs, presets, exports,
modèles et menus habituels sont conservés. Le test MangoHud peut rester installé.
Vulkan sous Wine reste expérimental : les vérifications automatisées ne
prouvent pas le fonctionnement du rendu avec chaque runner Wine/Proton.

Fermer les jeux Windows et la Toolbox. En SSH sur Batocera :

```bash
curl -fL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/feat/reshade-vulkan/scripts/install-reshade-vulkan-test.py -o /tmp/uwt-reshade-vulkan-test.py && python3 /tmp/uwt-reshade-vulkan-test.py
```

L’installateur accepte les fichiers de la base 0.8.1, avec ou sans le test
MangoHud. Il refuse les fichiers inconnus avant modification et conserve une
sauvegarde ainsi qu’un installateur de restauration hors ligne. Il ne modifie
pas la version stable et ne télécharge le chargeur Vulkan qu’au moment de
préparer une installation ReShade Vulkan depuis le menu.

## Essai Azahar

1. Lancer Azahar une fois avec son runner, puis le fermer.
2. Ouvrir **Ports → Ultimate Wine Toolbox → Outils et compatibilité → ReShade**.
3. Choisir Azahar puis **Installer / modifier version et shaders**.
4. Sélectionner `azahar.exe`, puis **Vulkan natif sous Wine (expérimental)**.
5. Choisir une version ReShade récente (`latest`), puis les packs souhaités.
   Les presets déjà conservés par la Toolbox restent disponibles.
6. Relancer Azahar en conservant son rendu Vulkan. **Home** doit ouvrir ReShade.
7. Vérifier à nouveau **MAILBOX** avec le profil Détaillé de MangoHud, puis
   comparer le rendu et la fluidité avec un effet simple activé/désactivé.

Le premier téléchargement ajoute le chargeur Windows VulkanRT 1.4.341.0
officiel de LunarG, avec SHA-256 fixé dans le code. La Toolbox ajoute une
valeur de couche au registre du seul préfixe du jeu. Les DLL originales sont
sauvegardées ; les archives WSquashFS restent inchangées. Un autre ReShade
Vulkan déjà actif dans le préfixe provoque un refus.

## Retour arrière

Pour retirer ReShade du jeu : fermer Azahar puis utiliser **Désactiver ReShade**
dans le menu du jeu. Le chargeur, la couche et ses réglages de lancement sont
restaurés/retirés avec conservation du preset et des autres valeurs du registre.

Pour retirer le test de la Toolbox : fermer les jeux et la Toolbox, puis :

```bash
python3 /tmp/uwt-reshade-vulkan-test.py --restore
```

Cette commande désactive d’abord les installations ReShade Vulkan gérées,
conserve leurs presets, puis restaure les fichiers de la Toolbox antérieurs.
Le test MangoHud reste dans l’état où il était avant l’installation de ce test.
Après redémarrage, utiliser la commande hors ligne affichée par l’installateur
ou télécharger de nouveau le même installateur avant `--restore`.

## Diagnostic

En cas de problème, relever le runner et sa version puis fournir :

- `/userdata/system/logs/ultimate-wine-toolbox/reshade-install-*.log` ;
- `/userdata/system/logs/ultimate-wine-toolbox/reshade-game-event.log` ;
- `ReShade.log` près de `azahar.exe`, s’il est créé.

Une installation réussie signifie que les fichiers et le registre sont prêts.
Le bandeau ReShade et l’ouverture du menu en jeu confirment le chargement réel.
