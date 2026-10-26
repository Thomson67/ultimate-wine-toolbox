# Batocera community profiles / Profils communautaires Batocera

Ce dossier est le **catalogue initial fourni avec les sources**, pas un miroir
à jour des contributions. Le catalogue public utilisé par défaut est
[Thomson67/ultimate-wine-toolbox-community, branche main](https://github.com/Thomson67/ultimate-wine-toolbox-community).
Ses mises à jour sont indépendantes des releases de la Toolbox.

## Utiliser le catalogue

Dans **AntiMicroX → Télécharger ou partager des profils** ou **ReShade → Presets
communautaires**, parcourir/rechercher, consulter les commandes ou les effets,
puis télécharger. **Mettre à jour la liste** actualise explicitement le cache.
Téléchargé et modifié distinguent les copies locales ; les fichiers personnels
modifiés sont conservés. Aucun compte n’est requis pour lire ou télécharger.

## Partager

Un compte GitHub n’est plus requis pour proposer un profil. La Toolbox envoie
la proposition au service HTTPS après confirmation ; un modérateur l’examine
avant publication. Le jeu est confirmé ou choisi dans la liste ES, puis trois
champs sont demandés : nom du profil/preset, pseudo public et description.
Les commandes externes et chargements de profils sont refusés et les
identifiants de manette sont retirés de la copie partagée.

Pour AntiMicroX, **Partager et transférer des profils** regroupe les actions.
**Partager la configuration complète d’un jeu** inclut ses règles launcher et
ses deux profils lorsqu’ils sont définis. Un jeu configuré propose aussi
**Partager ou exporter**. L’export local d’un ou plusieurs jeux dans un ZIP
ne publie rien et ne demande pas de métadonnées publiques.

Pour ReShade, partager uniquement le preset et ses prérequis : ni DLL, ni
shader, ni texture. Les utilisateurs doivent disposer des effets nécessaires.
Voir [CONTRIBUTING.md](CONTRIBUTING.md) et le
[guide complet des échanges](../docs/COMMUNITY_PROFILES.md).

## English

This source directory is a **seed**, not a live mirror. The default public
catalogue is `Thomson67/ultimate-wine-toolbox-community`, branch `main`.
Readers and contributors do not need a GitHub account. In-app submissions go
to the HTTPS service and require moderator approval before publication.

AntiMicroX complete sharing includes launcher rules and both mappings when
configured. Local ZIP transfer can contain several games without publication;
users choose each target game after import. ReShade sharing contains preset
settings and requirements, without DLLs, shader code or textures.

## Maintainers

The previous `community-presets` branch in this Toolbox repository is not the
default live catalogue. Existing custom source overrides must explicitly select
the intended catalogue and service. The supplied seed AntiMicroX examples came
from the public Pad2Key test fixtures; they do not describe the current live
catalogue's inventory. The ReShade seed may be empty even when live entries exist.

Normal moderation uses browser pairing and the private service queue. Approval
publishes the profile and catalogue entry together. Removing a published entry
also removes its manifest entry; deleting a file alone leaves a stale catalogue.

The offline maintainer fallback, from an application source checkout, is:

```bash
python3 toolbox/helpers/community_profiles.py approve submission.zip --catalog-root /path/to/community-checkout
```

It validates the package and edits the local catalogue checkout; it does not
publish Git. Review the diff and test the configuration before publishing it.
Service deployment and operator instructions belong to the
[community service repository](https://github.com/Thomson67/ultimate-wine-toolbox-community/blob/main/service/INSTALLATION_FR.md).
