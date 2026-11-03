# Catalogue ReShade et vérification des distributions

État vérifié le 3 novembre 2026. Le catalogue comprend 62 versions officielles
standard (4.1.0 à 6.8.0), 41 versions officielles avec add-ons complets (5.0.0
à 6.8.0), et 11 distributions sans bannière réparties sur 8 versions.

## Variantes sans bannière disponibles

| Fournisseur | Versions compilées vérifiées | Particularité |
|---|---|---|
| [fienestar](https://github.com/fienestar/OverlayDisabledReShade/releases) | 6.2.0, 6.4.1 | Cache et identifiants historiques conservés |
| [ovitus](https://github.com/ovitus/OverlayDisabledReShade/releases) | 6.5.0 | Le fichier runtime_gui.cpp correspond au fichier modifié de la 6.4.1, et diffère donc plus largement de l’officielle 6.5.0 ; indication « interface 6.4.1 » dans le menu |
| [Knitby](https://github.com/Knitby/OverlayDisabledReShade/releases) | 6.5.1 | Retrait du splash dans les sources du tag |
| [AndrewGDX](https://github.com/AndrewGDX/OverlayDisabledReShade/releases) | 6.5.1, 6.6.2 | ZIP contenant l’installateur ; extraction de ce conteneur prise en charge |
| [altes21](https://github.com/altes21/OverlayDisabledReShade/releases) | 6.6.2, 6.7.1, 6.7.3 | ZIP contenant l’installateur ; add-ons complets annoncés et cohérents avec la configuration de compilation |
| [Adam-Darlow](https://github.com/Adam-Darlow/OverlayDisabledReShade/releases) | 6.8.0 | Fenêtre du splash désactivée ; autres éléments du fichier d’interface identiques au tag officiel |
| [mjd4219](https://github.com/mjd4219/reshade-no-intro/releases) | 6.2.0 | Archive binaire ; auteur indiquant que les sources modifiées ne sont plus disponibles. Le menu affiche « sources indisponibles ». Le niveau de support des add-ons n’est pas établi |

Les configurations Release des tags contrôlés dans la famille
OverlayDisabledReShade définissent RESHADE_ADDON=2 (support complet). Cela est
indiqué dans le choix de variante ; les binaires archivés de mjd4219 ne sont
pas présentés comme ayant ce support vérifié.

## Contrôles effectués

Les 30 dépôts publics retrouvés sous le nom OverlayDisabledReShade et deux
projets associés (reshade-no-banner et reshade-no-intro) ont été examinés pour
leurs releases. Les tags sans fichiers compilés ne constituent pas des builds
installables et ne sont pas ajoutés, notamment darkmysteriox-dev, sprinox,
Agr4vaile et AshZaza. Le dépôt historique FaridZelli/OverlayDisabledReShade
n’était plus accessible. Ce relevé ne prétend pas couvrir tous les projets
ReShade renommés ou non indexés sur GitHub.

Les 11 distributions sans bannière et les 41 installateurs officiels Addon
ont été téléchargés et contrôlés :

- SHA-256 du fichier téléchargé, comparé au digest GitHub quand disponible ;
- ouverture de l’archive, y compris les ZIP contenant un installateur EXE ;
- présence de DLL x86 et x64, avec architecture PE correspondante ;
- lecture des informations de version embarquées, correspondant à la version
  annoncée (le quatrième composant est un numéro de build) ;
- lecture des structures PE par objdump et vérification des exports des API
  graphiques ; aucune dépendance à un runtime CRT de débogage trouvée ;
- nouvelle extraction des 52 distributions avec le code de production de la
  Toolbox, incluant la vérification de leurs 104 DLL.

Les sommes SHA-256 des archives et DLL et leurs versions embarquées sont
conservées dans toolbox/data/reshade-versions.json et revérifiées lors de
l’installation. Chaque version, variante et fournisseur a un cache distinct.
Un changement de build conserve les presets du jeu.

Les fichiers runtime_gui.cpp disponibles aux tags ont été comparés aux tags
officiels correspondants. Les changements examinés désactivent le splash,
sans supprimer le code du menu. L’exception ovitus est indiquée dans le tableau.
Le binaire mjd4219 permet uniquement les contrôles binaires ci-dessus et la
lecture de la description de sa release ; son patch ne peut pas être audité.

Ces vérifications ne constituent ni une reproduction des builds depuis les
sources, ni une validation en jeu du menu Home, des effets ou de chaque API
sur Batocera. Un binaire PE cohérent peut encore contenir des bugs.

## Versions officielles avec add-ons complets

Le choix « Officielle avec add-ons complets » utilise les installateurs Addon
publiés sur reshade.me, séparément de la distribution officielle standard.
Il active la capacité de charger des add-ons ; il n’installe aucun add-on tiers.
Ces versions sont destinées aux jeux solo, conformément à la documentation
[officielle de ReShade 5.0](https://reshade.me/forum/releases/7749-5-0).

Le parcours reste : choisir la version, puis la variante et son fournisseur.
Les variantes sans bannière disponibles sont signalées dès la liste des
versions. Le catalogue est livré avec la Toolbox ; il ne sélectionne ni ne
met à jour automatiquement le moteur d’un jeu.
