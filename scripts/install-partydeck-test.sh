#!/usr/bin/env bash
set -euo pipefail

version='v0.8.7-e'
asset="partydeck-${version}-anylinux-x86_64.AppImage"
checksum='9a6df7a214f5320154bf5344a65431d118ded24917cc65a3d578280e82f42acd'
base='/userdata/system/partydeck-test'
release="$base/releases/$version"
appdir="$release/AppDir"
data="$base/data/partydeck"
games="$base/jeux"
launcher="$base/partydeck-test"

die() { printf 'Erreur : %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'HELP'
Usage :
  bash install-partydeck-test.sh installer
  /userdata/system/partydeck-test/partydeck-test verifier
  /userdata/system/partydeck-test/partydeck-test jouer "Dossier/Jeu.exe" [chemin-absolu-vers-Proton]

« installer » installe PartyDeck et la commande locale, même sans session graphique.
« verifier » vérifie la session Xorg ou Wayland, Gamescope, Xwayland et Bubblewrap.
« jouer » sélectionne les manettes dans PartyDeck. Placez au préalable
une copie de test autonome du jeu dans /userdata/system/partydeck-test/jeux/.
L'EXE doit pouvoir se lancer avec un préfixe Wine neuf.
HELP
}

case "${1:-verifier}" in
    -h|--help) usage; exit 0 ;;
    installer|verifier) [[ $# -le 1 ]] || die 'Argument inattendu.' ;;
    jouer) [[ $# -ge 2 && $# -le 3 ]] || { usage; exit 2; } ;;
    *) usage; exit 2 ;;
esac

command -v batocera-version >/dev/null || die 'À exécuter sur Batocera.'
[[ $(uname -m) == x86_64 ]] || die 'Cette version de PartyDeck est destinée aux PC x86_64.'
for cmd in curl sha256sum python3 flock realpath; do
    command -v "$cmd" >/dev/null || die "Commande requise : $cmd"
done

mkdir -p "$base/releases" "$base/logs" "$base/cache" "$data" "$games"
exec 9>"$base/test.lock"
flock -n 9 || die 'Un test PartyDeck est déjà en cours.'

if [[ ${1:-verifier} == installer ]]; then
    [[ -f ${BASH_SOURCE[0]} ]] ||
        die 'Téléchargez le script dans un fichier avant de lancer son installation.'
fi

if [[ ${1:-verifier} == jouer ]]; then
    executable=$(realpath -e -- "$games/$2") || die "EXE introuvable dans $games"
    [[ $executable == "$games/"* && -f $executable && ${executable,,} == *.exe ]] ||
        die "Indiquez un EXE situé dans $games."
    proton=${3:-}
    if [[ -n $proton ]]; then
        [[ $proton == /* && -x $proton/proton ]] ||
            die 'Indiquez le dossier absolu du runner qui contient le fichier exécutable proton.'
        proton=$(realpath -e -- "$proton")
    fi
fi

log=$(mktemp "$base/logs/partydeck-$(date +%Y%m%d-%H%M%S)-XXXXXX")
printf 'Journal : %s\n' "$log"
exec > >(tee -a "$log") 2>&1
printf 'Batocera %s\nPartyDeck %s\n' "$(batocera-version)" "$version"
df -h "$base"

if [[ ! -x $appdir/AppRun ]]; then
    staging=$(mktemp -d "$base/releases/.partydeck-XXXXXX")
    trap 'rm -rf -- "$staging"' EXIT
    curl --fail --show-error --location --retry 2 --connect-timeout 15 --proto '=https' \
        "https://github.com/partydeck/partydeck/releases/download/$version/$asset" \
        --output "$staging/$asset"
    (cd "$staging" && printf '%s  %s\n' "$checksum" "$asset" | sha256sum -c -)
    chmod 0755 "$staging/$asset"
    (cd "$staging" && "./$asset" --appimage-extract >/dev/null)
    [[ -x $staging/AppDir/AppRun && -x $staging/AppDir/bin/umu-run ]] ||
        die 'Le contenu extrait ne correspond pas au paquet PartyDeck attendu.'
    rm -- "$staging/squashfs-root"
    [[ ! -e $release ]] || die "Installation incomplète dans $release."
    mv -T -- "$staging" "$release"
    trap - EXIT
fi

# PartyDeck masque /tmp dans chaque instance. Son AppImage est extraite dans
# un emplacement persistant pour que le lanceur UMU reste accessible.
export APPDIR="$appdir" APPIMAGE="$release/$asset"
export XDG_DATA_HOME="$base/data" XDG_CACHE_HOME="$base/cache" USE_HOST_XDG_CACHE_HOME=1
unset ARGV0

"$appdir/AppRun" --help
if [[ ${1:-verifier} == installer ]]; then
    temporary_launcher=$(mktemp "$base/.launcher-XXXXXX")
    trap 'rm -f -- "$temporary_launcher"' EXIT
    cp -- "${BASH_SOURCE[0]}" "$temporary_launcher"
    chmod 0755 "$temporary_launcher"
    mv -fT -- "$temporary_launcher" "$launcher"
    trap - EXIT
    printf '\nPartyDeck installé. Quand EmulationStation est affiché, lancez :\n%s verifier\n' "$launcher"
    exit 0
fi

"$appdir/bin/gamescope-kbm" --help >"$base/logs/gamescope-help.log" 2>&1 ||
    die "Le Gamescope fourni ne démarre pas. Voir $base/logs/gamescope-help.log"
"$appdir/bin/umu-run" --version
"$appdir/bin/bwrap" --die-with-parent --dev-bind / / --tmpfs /tmp /bin/true ||
    die 'Bubblewrap ne peut pas créer le namespace requis sur cette build.'

# Récupère l'environnement graphique local d'EmulationStation, même en SSH.
# Lit uniquement les variables attendues, sans évaluer le contenu du processus.
for pid in $(pidof emulationstation 2>/dev/null || true); do
    [[ -r /proc/$pid/environ ]] || continue
    unset DISPLAY WAYLAND_DISPLAY XAUTHORITY
    while IFS= read -r -d '' item; do
        case "$item" in
            DISPLAY=*|WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*)
                export "$item" ;;
        esac
    done < "/proc/$pid/environ"
    break
done

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/var/run}"
wayland_socket="${WAYLAND_DISPLAY:-wayland-0}"
[[ $wayland_socket == /* ]] || wayland_socket="$XDG_RUNTIME_DIR/$wayland_socket"
if [[ -S $wayland_socket ]]; then
    export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
    session=Wayland
else
    unset WAYLAND_DISPLAY
    session=Xorg
fi

# Le backend SDL de ce PartyDeck utilise le display X11 parent, sous Xorg
# comme sous labwc. Gamescope lance aussi son propre serveur Xwayland.
[[ ${DISPLAY:-} =~ ^:[0-9]+(\.[0-9]+)?$ ]] || export DISPLAY=:0.0
printf 'Session : %s | DISPLAY=%s | WAYLAND_DISPLAY=%s | XDG_RUNTIME_DIR=%s\n' \
    "$session" "$DISPLAY" "${WAYLAND_DISPLAY:-}" "$XDG_RUNTIME_DIR"

if command -v xdpyinfo >/dev/null; then
    xdpyinfo >/dev/null || die "Display X11 local inaccessible ($DISPLAY)."
elif command -v xrandr >/dev/null; then
    xrandr --query >/dev/null || die "Display X11 local inaccessible ($DISPLAY)."
else
    display_number=${DISPLAY#:}
    [[ -S /tmp/.X11-unix/X${display_number%%.*} ]] ||
        die "Socket X11 introuvable ($DISPLAY)."
fi

if ! command -v Xwayland >/dev/null && [[ ! -x $appdir/bin/Xwayland ]]; then
    die 'Xwayland est absent. Gamescope en a besoin même lorsque la session principale utilise Xorg.'
fi

if [[ ${1:-verifier} == verifier ]]; then
    printf '\nVérifications de base OK. Dossier des jeux de test : %s\n' "$games"
    exit 0
fi

# PartyDeck enregistre sa configuration dans le dossier dédié à cet essai.
python3 - "$data/settings.json" "$proton" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
settings = json.loads(path.read_text()) if path.exists() else {}
settings.update(
    enable_kwin_script=False,
    kbm_support=True,
    proton_separate_pfxs=True,
    profile_unique_dirs=True,
    check_for_updates=False,
)
if sys.argv[2]:
    settings["proton_version"] = sys.argv[2]
temp = path.with_suffix(".tmp")
temp.write_text(json.dumps(settings, indent=2) + "\n")
temp.replace(path)
print(f"Runner Proton : {settings.get('proton_version') or 'GE-Proton (géré par UMU)'}")
PY

printf 'Lancement avec le jeu de test : %s\n' "$executable"
cd "$base"
"$appdir/AppRun" --exec "$executable"
