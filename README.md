# Batocera community profiles / Profils communautaires Batocera

Catalogue commun aux menus **AntiMicroX → Profils communautaires** et
**ReShade → Presets communautaires** d'Ultimate Wine Toolbox.

Le catalogue public se trouve sur la branche `community-presets` du dépôt
[Thomson67/ultimate-wine-toolbox](https://github.com/Thomson67/ultimate-wine-toolbox/tree/community-presets).
Les mises à jour du catalogue sont indépendantes des versions de la Toolbox.
Aucun compte n'est nécessaire pour consulter ou télécharger. Un compte GitHub
est nécessaire pour proposer une contribution, qui sera examinée avant ajout.

Les premiers profils AntiMicroX sont des **exemples de départ** issus des deux
Pad2Key de Thomson déjà présents dans les tests publics du projet. Ils ne
comprennent pas les ajouts Hotkey réalisés ensuite. Aucun preset ReShade de jeu
n'est inventé : cette catégorie attend ses premières contributions.

## Utilisation

Actualisez le catalogue depuis le menu de l'outil, recherchez le jeu, lisez les
prérequis, puis téléchargez. Les fichiers personnels ne sont pas écrasés.
Vérifiez la Hotkey du profil AntiMicroX et les packs/effets ReShade nécessaires.
Les dépendances et les différences entre versions de jeu peuvent affecter le
résultat. Les presets ReShade ne contiennent ni DLL, ni shaders, ni textures.

## Partager

Utilisez **Préparer le partage de mon profil / preset** dans le menu de l'outil.
La Toolbox crée un ZIP et un fichier texte dans son dossier `exports/community`.
Depuis un PC, ouvrez le lien GitHub du fichier texte et joignez le ZIP à la
proposition. Le profil, le pseudo et les renseignements seront publics si la
contribution est acceptée. Partagez uniquement des contenus que vous êtes
autorisé à redistribuer. Voir [CONTRIBUTING.md](CONTRIBUTING.md).

## English

This public catalogue serves two separate tool menus in Ultimate Wine Toolbox:
**AntiMicroX → Community profiles** and **ReShade → Community presets**.
Downloading requires no account. Submission uses the ZIP prepared by the
Toolbox and a GitHub issue; review is required before catalogue publication.
The initial AntiMicroX files are starting examples converted from Thomson's
two Pad2Key fixtures, without subsequent personal Hotkey additions. The ReShade
section starts empty until real game presets are contributed.

Check controller Hotkeys, shader requirements and tested versions before use.
Executables, DLLs, shader code and textures are not distributed here.

## Maintainers

The `community-presets` branch is the live catalogue. The `community-catalog/`
directory on the development branch contains the initial seed, not an automatic
mirror of future contributions. Maintain catalogue updates on the catalogue
branch. A reviewed package can be added locally with:

```bash
python3 tools/community_profiles.py approve submission.zip --catalog-root .
```

On the application source branch, the equivalent tool is
`toolbox/helpers/community_profiles.py`. Review the resulting diff, verify the
game and dependencies, then commit to the catalogue branch. No submission is
automatically published, and the tool never executes profile commands.
