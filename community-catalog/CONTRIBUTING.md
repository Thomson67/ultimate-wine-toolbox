# Proposer une contribution / Contributing

## Depuis la Toolbox

1. Fermer le jeu et l’éditeur afin d’enregistrer les dernières commandes/réglages.
2. Pour AntiMicroX, ouvrir **Télécharger ou partager des profils → Partager et
   transférer des profils**, ou **Partager ou exporter** dans le menu d’un jeu.
   Choisir le partage complet pour conserver les règles launcher et les profils
   launcher/jeu ; le partage d’un profil seul reste proposé séparément.
3. Pour ReShade, choisir **Partager mon preset ReShade** depuis son menu.
4. Confirmer le jeu identifié ou le choisir dans la liste ES, puis renseigner
   le nom du profil/preset, le pseudo public et la description. Préciser dans
   la description les versions, contrôles particuliers et prérequis utiles.
5. Lire la confirmation et envoyer. Aucun compte GitHub ni ticket manuel n’est
   nécessaire. La proposition attend l’examen d’un modérateur. Le ZIP local
   et, en cas de réussite, le reçu sont conservés sous `exports/community/`.

Le pseudo et les informations acceptées deviennent publics. Partager seulement
un contenu autorisé à la redistribution. Un export ZIP local de configurations
AntiMicroX est un transfert privé distinct ; il ne soumet rien au catalogue.

## AntiMicroX

Les profils SDL `gamecontroller` sont requis ; les anciens profils bruts
`joystick` doivent être adaptés avant partage. L’export retire les identifiants
de manette et refuse commandes externes, chargements d’autres profils et chemins
locaux. La Hotkey n’est pas réécrite automatiquement : vérifier sa disposition.

Un partage launcher complet embarque ses règles portables et ses deux rôles
s’ils sont définis. Après import, choisir le jeu cible ; les chemins locaux sont
recréés pour cette machine. Les titres/classes/exécutables doivent correspondre
à sa version/langue du jeu. La limite du service est de 64 Kio pour l’ensemble.
Voir [le format et les transferts ZIP](../docs/COMMUNITY_PROFILES.md).

## ReShade

Partager les réglages `.ini` et identifier les effets/packs supplémentaires et
l’API/version testée. Les chemins de recherche propres à une installation sont
refusés. Les paquets ne contiennent ni jeu, ni exécutable, ni DLL, shader ou texture.

## Review

Normal review uses the paired moderator interface and private submission queue.
Authors' nicknames are self-declared. Review actual mappings, Hotkey behavior,
launcher/game rules when present, game versions and shader dependencies.
Approval publishes a file and catalogue entry together. Removing a community
entry does not remove profiles already installed on players' machines.

The offline fallback accepts only `metadata.json`, `submission.txt` and the
expected `profile.amgp` or `profile.ini`. It validates metadata, member paths,
checksum and content without executing profile commands. AntiMicroX launcher
roles/rules are embedded in the `.amgp`, not extra executable ZIP members.
Batch `configurations.json` exports are local transfers, not service submissions.
Duplicate catalogue IDs are rejected; stable IDs and SHA-256 checksums are required.
A local approval does not itself commit or publish Git. Validate and review the
diff in the separate community checkout before publishing.
