# Tester PartyDeck sur Batocera

Ce prototype s'installe dans `/userdata/system/partydeck-test` et se lance depuis SSH.
Il utilise PartyDeck v0.8.7-e avec Gamescope et UMU. Le placement des fenêtres
reste manuel sous Xorg et labwc. L'installation demande un PC x86-64 et un accès à GitHub.

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

Placez une copie autonome du jeu dans `/userdata/system/partydeck-test/jeux`.
Choisissez un jeu capable de démarrer dans un préfixe neuf et doté d'un mode
LAN et d'un support manette.

```bash
/userdata/system/partydeck-test/partydeck-test jouer "Mon Jeu/Jeu.exe"
```

La commande accepte un troisième paramètre après `jouer` et le chemin de l'EXE,
à savoir le chemin absolu d'un dossier Proton contenant l'exécutable `proton`.
Sans runner configuré, PartyDeck utilise GE-Proton via UMU. Le premier lancement
peut télécharger le runner et le runtime.

Dans PartyDeck, ajoutez chaque manette comme joueur distinct et sélectionnez
**Start**. Placez les fenêtres côte à côte, puis vérifiez les deux manettes
simultanément, avec le focus sur chaque fenêtre à tour de rôle. Essayez ensuite
de rejoindre la même partie LAN depuis les deux instances.

Chaque exécution affiche le chemin de son journal sous
`/userdata/system/partydeck-test/logs`. Pour confirmer la compatibilité avec
votre build, lancez le même test sous Xorg et sous Wayland.
