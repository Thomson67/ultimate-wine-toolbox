# Proposer une contribution / Contributing

1. Fermer le jeu et l'éditeur avant l'export.
2. Dans le menu communautaire d'AntiMicroX ou ReShade, préparer le partage.
3. Renseigner le jeu, le titre, son pseudo, les versions testées et les prérequis.
4. Vérifier que le fichier ne contient ni chemins personnels, ni identifiant de
   périphérique, ni commande externe. L'export AntiMicroX retire l'identité de
   la manette. Les commandes et chargements d'autres profils sont refusés.
5. Ouvrir sur son PC le lien contenu dans le fichier `.txt` et joindre le ZIP.
6. Confirmer que l'on peut partager les contenus publiquement. Un mainteneur
   examinera la proposition avant publication.

Pour AntiMicroX, indiquer la disposition de manette et le bouton Hotkey attendu.
Un profil SDL GameController est requis ; les anciens profils génériques
`joystick` doivent être recréés/adaptés avant partage. Les affectations restent
modifiables après téléchargement et la Hotkey n'est pas réécrite automatiquement.

Pour ReShade, partager le preset et ses valeurs uniquement. Lister les effets,
packs et textures supplémentaires nécessaires ainsi que l'API/version testée.
Les chemins de recherche propres à une installation sont refusés. Aucune DLL,
aucun shader ou texture n'est accepté dans le ZIP de cette première version.

## Review

Only three ZIP members are accepted: `metadata.json`, `profile.amgp` or
`profile.ini`, and `submission.txt`. The local maintainer command validates the
metadata, paths, checksum and content; it does not replace testing or review.
Duplicate IDs are rejected so updates must be reviewed as changes to the
existing entry. Catalogue entries must have stable IDs and SHA-256 checksums.

Reviewers should credit the author, distinguish tested profiles from starting
examples, confirm dependencies and avoid importing personal paths or data.
Do not include games, executables, DLLs, shader code or textures in submissions.
Use only content you are permitted to redistribute.
