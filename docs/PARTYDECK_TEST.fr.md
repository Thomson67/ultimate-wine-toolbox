# Tester PartyDeck sur Batocera

Ce prototype s'installe dans `/userdata/system/partydeck-test` et se configure depuis SSH.
Il utilise PartyDeck v0.8.7-e avec Gamescope et UMU. L'installation demande un
PC x86-64 et un accès à GitHub.
L'UMU embarqué passe par le pont d'UMU Runner Toolbox lorsque la session
Batocera tourne en root. Le pont est installé dans le dossier de test.

## Installer

```bash
(
  fichier=$(mktemp /tmp/partydeck-install.XXXXXX) || exit 1
  trap 'rm -f -- "$fichier"' EXIT
  curl -fsSL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/feature/partydeck-batocera/scripts/install-partydeck-test.sh -o "$fichier" &&
    bash "$fichier" installer
)
```

## Vérifier et jouer

Avec EmulationStation affiché, lancez le diagnostic depuis SSH.

```bash
/userdata/system/partydeck-test/partydeck-test verifier
```

Le journal indique le type de session et l'état des dépendances. Gamescope a
besoin de Xwayland pour ses fenêtres internes, y compris quand Batocera utilise
Xorg comme session principale. Si Batocera fournit Xwayland, le script l'utilise.
Sinon, la première vérification télécharge une version portable dont les paquets
sont vérifiés par SHA-256. Elle est rangée dans
`/userdata/system/partydeck-test/releases` et utilisée uniquement par le test
PartyDeck.

## Jeux Wine et écran partagé automatique

Préparez une entrée pour un jeu Batocera existant. Les formats acceptés sont
`.wine`, `.pc` et `.wsquashfs`.

```bash
/userdata/system/partydeck-test/partydeck-test preparer-coop \
  "/userdata/roms/windows/Mon Jeu.wsquashfs" 2 horizontal clavier-j2
```

Actualisez les listes dans EmulationStation, puis ouvrez le jeu dans **Ports**.
Le jeu démarre directement avec le runner et l'`autorun.cmd` lus par
`batocera-wine`. Les sauvegardes et écritures du test sont isolées pour chaque
joueur dans `/userdata/system/partydeck-test/coop`. Le test démarre avec ses
propres sauvegardes. OverlayFS est nécessaire pour les écritures du jeu.

- Choisissez `1`, `2`, `3`, `4` ou `auto`. `auto` adapte le nombre de joueurs
  aux manettes détectées au lancement, avec un maximum de quatre.
- `horizontal` place deux fenêtres l'une au-dessus de l'autre. `vertical`
  les place côte à côte. À trois ou quatre joueurs, le lanceur utilise une
  grille 2 × 2. Le placement vise l'écran principal.
- Le choix d'entrées `auto` privilégie les manettes. S'il en manque une, le
  dernier joueur peut utiliser le clavier et la souris. `clavier-j1` et
  `clavier-j2` permettent de réserver ce duo à un joueur. Les manettes
  utilisent un ordre stable par périphérique lorsqu'udev fournit un chemin.

Lancez d'abord depuis **Ports** sur Xorg pour valider sur la machine le
placement automatique, le runner sélectionné et les entrées. Sous
Wayland/labwc, le placement des fenêtres Xwayland reste à valider.
Le jeu doit permettre à chaque instance de rejoindre une même partie.

Pour un jeu UMU, chaque joueur a ses journaux dans `coop/<jeu>/jN/umu-logs`
et, avec Proton, dans `coop/<jeu>/jN/proton-logs` sous le dossier PartyDeck.
Le journal principal indique l'affichage Xwayland attribué à chaque instance
et le code de sortie de `batocera-wine`.

## Essai manuel avec un exécutable autonome

Placez une copie autonome du jeu dans `/userdata/system/partydeck-test/jeux`.
Choisissez un jeu capable de démarrer dans un préfixe neuf et doté d'un mode
LAN et d'un support manette.

```bash
/userdata/system/partydeck-test/partydeck-test preparer-port "Mon Jeu/Jeu.exe"
```

Actualisez les listes de jeux dans EmulationStation, puis ouvrez **Ports →
PartyDeck - Test**. EmulationStation libère les manettes pendant le lancement
d'un port. Relancez `preparer-port` pour changer de jeu dans cette entrée.
Pour les essais directs depuis SSH, la commande `jouer` reste disponible.

Le chemin de l'EXE peut être suivi d'un paramètre optionnel,
à savoir le chemin absolu d'un dossier Proton contenant l'exécutable `proton`.
Sans runner configuré, PartyDeck utilise GE-Proton via UMU. Le premier lancement
peut télécharger le runner et le runtime.

Dans PartyDeck, ajoutez chaque manette comme joueur distinct et sélectionnez
**Start**. Placez les fenêtres côte à côte, puis vérifiez les deux manettes
simultanément, avec le focus sur chaque fenêtre à tour de rôle. Essayez ensuite
de rejoindre la même partie LAN depuis les deux instances.

Sous Xorg, le lanceur demande à Batocera d'afficher le pointeur pendant
la session PartyDeck et le masque à sa fermeture, si `unclutter-remote` est
disponible.

Chaque exécution affiche le chemin de son journal sous
`/userdata/system/partydeck-test/logs`. Pour confirmer la compatibilité avec
votre build, lancez le même test sous Xorg et sous Wayland.
