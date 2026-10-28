# Test des réglages MangoHud

Ce test ciblé s’applique à la **Toolbox 0.8.1**. Il ajoute les réglages globaux
et par jeu de présentation Vulkan, VSync OpenGL, limite de FPS personnalisée,
méthode du limiteur et affichage masqué. Aucun plafond ni mode de
synchronisation n’est forcé par défaut.

Fermer les jeux Windows et la Toolbox, puis lancer en SSH sur Batocera :

```bash
curl -fL https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/feat/mangohud-controls/scripts/install-mangohud-controls-test.py -o /tmp/uwt-mangohud-test.py && python3 /tmp/uwt-mangohud-test.py
```

L’installateur vérifie les fichiers de la base 0.8.1 et refuse une version
différente avant de remplacer quoi que ce soit. Il sauvegarde les fichiers
concernés et la configuration de ces nouveaux réglages, puis actualise aussi le
hook de lancement déjà installé dans `/userdata/system/scripts`. Il ne change
pas la version stable, les runners, les jeux ni les sauvegardes.

## Essai Azahar

1. Ouvrir **Ports → Ultimate Wine Toolbox → Outils et compatibilité → MangoHud**.
2. Activer MangoHud pour Azahar, puis ouvrir **Réglages par jeu** et choisir Azahar.
3. Choisir **Affichage : Masqué**, **VSync Vulkan : Mailbox**.
4. Laisser la limite de FPS sur **Hériter du global**, sans plafond global MangoHud.
5. Désactiver la VSync dans Azahar et conserver la vitesse d’émulation à 100 %.
6. Relancer Azahar et comparer la même scène avec et sans Mailbox.

Le profil Détaillé affiche le mode de présentation pour le diagnostic.
Mailbox nécessite la prise en charge du pilote ; une baisse de latence n’est
pas garantie. Le runtime MangoHud 0.8.4 de la Toolbox doit être installé.

Pour essayer le limiteur personnalisé sur un jeu PC, désactiver le limiteur
Batocera de ce jeu, puis sélectionner un plafond MangoHud tel que 90, 120 ou
144 FPS. Cela ne débloque pas les jeux limités en interne à 30 ou 60 FPS.

## Restauration

Fermer les jeux Windows et la Toolbox, puis :

```bash
python3 /tmp/uwt-mangohud-test.py --restore
```

Après un redémarrage, le fichier `/tmp` peut avoir disparu : réutiliser la
commande de restauration hors ligne affichée à l’installation. Une copie de
l’installateur est conservée dans le dossier de sauvegarde. La restauration
refuse d’écraser des fichiers de code modifiés depuis l’installation du test.

## Validation

Tests automatisés : héritage et exceptions par jeu, limites au-delà de 60 FPS,
conservation/restauration de l’environnement personnalisé, coexistence ReShade,
installation depuis les sources 0.8.1, réinstallation, hook copié et restauration
hors ligne. Les résultats de latence et de compatibilité GPU restent à vérifier
sur le matériel Batocera.
