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
coop_helper="$base/partydeck-batocera-coop.py"
xwayland_dir="$base/releases/xwayland-24.1.15-1"
ports_dir='/userdata/roms/ports'

die() { printf 'Erreur : %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'HELP'
Usage :
  bash install-partydeck-test.sh installer
  /userdata/system/partydeck-test/partydeck-test verifier
  /userdata/system/partydeck-test/partydeck-test preparer-port "Dossier/Jeu.exe" [chemin-absolu-vers-Proton]
  /userdata/system/partydeck-test/partydeck-test jouer "Dossier/Jeu.exe" [chemin-absolu-vers-Proton]
  /userdata/system/partydeck-test/partydeck-test preparer-coop "/chemin/Jeu.wine" [auto|1|2|3|4] [horizontal|vertical] [auto|clavier-j1|clavier-j2]

« installer » installe PartyDeck et la commande locale, même sans session graphique.
« verifier » vérifie la session Xorg ou Wayland, Gamescope, Xwayland et Bubblewrap.
« preparer-port » crée l'entrée de test dans Ports pour lancer depuis EmulationStation.
« preparer-coop » crée une entrée Ports à lancement direct pour un .wine, .pc ou .wsquashfs.
« jouer » sélectionne les manettes dans PartyDeck. Placez au préalable
une copie de test autonome du jeu dans /userdata/system/partydeck-test/jeux/.
L'EXE doit pouvoir se lancer avec un préfixe Wine neuf.
HELP
}

install_portable_xwayland() {
    local staging checksum path package
    staging=$(mktemp -d "$base/releases/.xwayland-XXXXXX")
    trap 'rm -rf -- "$staging"' EXIT
    printf 'Installation de Xwayland portable dans le dossier PartyDeck.\n'

    # Debian upstream packages, pinned by SHA-256 from the amd64 package indexes.
    # PartyDeck's pinned AppImage provides glibc, Mesa and the Wayland libraries.
    while read -r checksum path; do
        package="${path##*/}"
        curl --fail --silent --show-error --location --retry 2 --connect-timeout 15 \
            --proto '=https' "https://deb.debian.org/debian/$path" --output "$staging/$package" ||
            die "Téléchargement de $package impossible."
        (cd "$staging" && printf '%s  %s\n' "$checksum" "$package" | sha256sum -c -) ||
            die "Somme SHA-256 incorrecte pour $package."
    done <<'PACKAGES'
bd43e020b8fed399db3eebf098111f10fba4c436fff99ccad72cc7e27c9764ec pool/main/e/e2fsprogs/libcom-err2_1.47.2-3+b12_amd64.deb
e4947f3291528f03d574f2b01d5c5fc45c58c47480f32888a5cdf0f231ab584e pool/main/f/freetype/libfreetype6_2.13.3+dfsg-1+deb13u1_amd64.deb
0b11ad17be0300b63ad4eeb4c6450fed24d34b7b740f23e5363dcb29ee6d5eba pool/main/k/keyutils/libkeyutils1_1.6.3-6_amd64.deb
30847c1fde4240567d7ed3aeab4f655dd591203758b857e85e824045aae70299 pool/main/k/krb5/libgssapi-krb5-2_1.21.3-5+deb13u1_amd64.deb
7da07ee674b47f1f0be7cc89317c25310086a1f1761217d0f72e6ae2c5a69b84 pool/main/k/krb5/libk5crypto3_1.21.3-5+deb13u1_amd64.deb
47d71d6a7f2e59b9bae5f89602397594805113b95889ad18fa703cd53abafc97 pool/main/k/krb5/libkrb5-3_1.21.3-5+deb13u1_amd64.deb
3a0acd8b37955c0e102c756b52c97df2a31f67b96453c35dab70df218d309117 pool/main/k/krb5/libkrb5support0_1.21.3-5+deb13u1_amd64.deb
de3e735f2ecf97cdcd51251ec5c1f84d5ff0ce9f8f822dd7b345dc293af446f0 pool/main/libe/libei/libei1_1.3.901-1_amd64.deb
d61d40a3dfc0b7030854237c5445f6b9b469c6c3b53a2ff1f98dfa0ae0c7b3f1 pool/main/libe/libei/liboeffis1_1.3.901-1_amd64.deb
4c4c8024f2175086de65bca9fdc3fbb967f2863ebf249d489c66d0c8103dd3a3 pool/main/libe/libepoxy/libepoxy0_1.5.10-2_amd64.deb
49f7330e1bbe3f48946fee5c07870df660374f9f77b378840d6edf1a3b3444cd pool/main/libf/libfontenc/libfontenc1_1.1.8-1+b2_amd64.deb
e2736abceb853d036da0eb0e9f93992dcd31636fe667ef3372d203f53fe30d9c pool/main/libg/libgcrypt20/libgcrypt20_1.12.4-2_amd64.deb
ef307016953fca2d257786cb323ad7c3b8b84fe9e17a64c9adeaae5d5a434d30 pool/main/libg/libgpg-error/libgpg-error0_1.61-5_amd64.deb
2465b4e9fa85cff54dc10a6da3e64074d8d9292c86e4a8f989b809d6b158e97e pool/main/libp/libpng1.6/libpng16-16t64_1.6.48-1+deb13u5_amd64.deb
ef4536c09bf5063554310e22d586ae90990100ba66d2fe7c35660e9e658913b6 pool/main/libt/libtirpc/libtirpc3t64_1.3.6+ds-1_amd64.deb
0faccb95f5d306fc30c8b128572b92ff97bf59c547f1f8a46b57e0b4c6dd045b pool/main/libx/libxcvt/libxcvt0_0.1.3-1_amd64.deb
79a7f56e4a0c7b1defa706c7b1f3076f7d80aaeea9de253b2a87406253319681 pool/main/libx/libxfont/libxfont2_2.0.6-1+deb13u1_amd64.deb
312acac8172454463645ebaf574eb586b2a04a93d6c62349df7bf46ee3daf78d pool/main/x/xwayland/xwayland_24.1.15-1_amd64.deb
PACKAGES

    python3 - "$staging" <<'PYTHON'
import io
from pathlib import Path
import sys
import tarfile

destination = Path(sys.argv[1])
for deb in destination.glob("*.deb"):
    with deb.open("rb") as archive:
        if archive.read(8) != b"!<arch>\n":
            raise ValueError(f"Invalid Debian archive: {deb.name}")
        while header := archive.read(60):
            size = int(header[48:58])
            if header[:16].strip().rstrip(b"/") == b"data.tar.xz":
                payload = archive.read(size)
                with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as data:
                    members = (
                        entry for entry in data
                        if entry.name.removeprefix("./") == "usr/bin/Xwayland"
                        or entry.name.removeprefix("./").startswith("usr/lib/x86_64-linux-gnu/")
                    )
                    data.extractall(destination, members=members, filter="data")
                break
            archive.seek(size + size % 2, io.SEEK_CUR)
        else:
            raise ValueError(f"Missing data.tar.xz in {deb.name}")
    deb.unlink()
PYTHON

    cat > "$staging/Xwayland" <<'WRAPPER'
#!/bin/sh
runtime=${0%/*}
partydeck_lib="$PARTYDECK_XWAYLAND_APPDIR/lib"
exec "$partydeck_lib/ld-linux-x86-64.so.2" \
    --library-path "$runtime/usr/lib/x86_64-linux-gnu:$partydeck_lib" \
    "$runtime/usr/bin/Xwayland" "$@"
WRAPPER
    chmod 0755 "$staging/Xwayland"
    "$staging/Xwayland" -version || die 'Le Xwayland portable ne démarre pas.'
    mv -T -- "$staging" "$xwayland_dir"
    trap - EXIT
}

prepare_batocera_umu() {
    local bin="$appdir/bin"
    local bridge_revision="2c541f40f62f40a8c8c58d6430cd5c1731711ce7"
    local bridge_checksum="12d6c194bea55b0ee723a45e9379e1551cd8f9d07a1ea84263613074b60f6239"
    local upstream_checksum="d0005a58602041229cc467dab03dc0c0b9e8cce09a8145b16b7683244cf17804"
    local bridge_url="https://raw.githubusercontent.com/Thomson67/umu-runner-toolbox/$bridge_revision/toolbox/overlay/umu-batocera/umu-root-runner.py"
    local marker='# PartyDeck Batocera UMU bridge'
    local staging original="$bin/umu-run.upstream"

    if [[ -x $original && -f $bin/umu-root-runner.py ]] &&
       grep -qxF -- "$marker" "$bin/umu-run"; then
        return
    fi

    staging=$(mktemp -d "$bin/.umu-batocera-XXXXXX")
    trap 'rm -rf -- "$staging"' EXIT
    curl --fail --silent --show-error --location --retry 2 --connect-timeout 15 \
        --proto '=https' "$bridge_url" --output "$staging/umu-root-runner.py" ||
        die 'Téléchargement du pont UMU pour Batocera impossible.'
    (cd "$staging" && printf '%s  %s\n' "$bridge_checksum" umu-root-runner.py | sha256sum -c -) ||
        die 'Somme SHA-256 incorrecte pour le pont UMU.'

    if [[ ! -x $original ]]; then
        (cd "$bin" && printf '%s  %s\n' "$upstream_checksum" umu-run | sha256sum -c -) ||
            die 'Le binaire UMU ne correspond pas à celui de l’AppImage PartyDeck.'
        cp -p -- "$bin/umu-run" "$staging/umu-run.upstream"
        mv -fT -- "$staging/umu-run.upstream" "$original"
    fi

    cat > "$staging/umu-run" <<'WRAPPER'
#!/bin/sh
# PartyDeck Batocera UMU bridge
bin=${0%/*}
if [ "$(id -u)" = 0 ]; then
    exec python3 "$bin/umu-root-runner.py" "$bin/umu-run.upstream" "$@"
fi
exec "$bin/umu-run.upstream" "$@"
WRAPPER
    chmod 0755 "$staging/umu-run"
    mv -fT -- "$staging/umu-root-runner.py" "$bin/umu-root-runner.py"
    mv -fT -- "$staging/umu-run" "$bin/umu-run"
    rm -rf -- "$staging"
    trap - EXIT
}

case "${1:-verifier}" in
    -h|--help) usage; exit 0 ;;
    installer|verifier) [[ $# -le 1 ]] || die 'Argument inattendu.' ;;
    jouer|preparer-port) [[ $# -ge 2 && $# -le 3 ]] || { usage; exit 2; } ;;
    coop|preparer-coop) [[ $# -ge 2 && $# -le 5 ]] || { usage; exit 2; } ;;
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

if [[ ${1:-verifier} == preparer-coop ]]; then
    [[ -x $launcher && -f $coop_helper ]] || die 'Installez cette version de PartyDeck avant de préparer un port coop.'
    shift
    python3 "$coop_helper" prepare "$appdir" "$base" "$ports_dir" "$@"
    exit 0
fi

if [[ ${1:-verifier} == installer ]]; then
    [[ -f ${BASH_SOURCE[0]} ]] ||
        die 'Téléchargez le script dans un fichier avant de lancer son installation.'
fi

if [[ ${1:-verifier} == jouer || ${1:-verifier} == preparer-port ]]; then
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

if [[ ${1:-verifier} == preparer-port ]]; then
    [[ -x $launcher ]] || die 'Installez le lanceur PartyDeck avant de créer l’entrée Ports.'
    port="$ports_dir/PartyDeck - Test.sh"
    marker='# Entrée gérée par partydeck-test'
    mkdir -p -- "$ports_dir"
    if [[ -L $port ]] || { [[ -e $port ]] && ! grep -qxF -- "$marker" "$port"; }; then
        die "Un fichier existe déjà à cet emplacement : $port"
    fi

    temporary_port=$(mktemp "$ports_dir/.partydeck-XXXXXX")
    trap 'rm -f -- "$temporary_port"' EXIT
    {
        printf '#!/bin/bash\n%s\n' "$marker"
        printf 'exec %q jouer %q %q\n' "$launcher" "$2" "$proton"
    } > "$temporary_port"
    chmod 0755 "$temporary_port"
    mv -fT -- "$temporary_port" "$port"
    trap - EXIT
    printf 'Entrée enregistrée : %s\n' "$port"
    printf 'Actualisez les listes de jeux dans EmulationStation, puis lancez Ports → PartyDeck - Test.\n'
    exit 0
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

prepare_batocera_umu

# PartyDeck masque /tmp dans chaque instance. Son AppImage est extraite dans
# un emplacement persistant pour que le lanceur UMU reste accessible.
export APPDIR="$appdir" APPIMAGE="$release/$asset"
export XDG_DATA_HOME="$base/data" XDG_CACHE_HOME="$base/cache" USE_HOST_XDG_CACHE_HOME=1
unset ARGV0

"$appdir/AppRun" --help
if [[ ${1:-verifier} == installer ]]; then
    staging=$(mktemp -d "$base/.coop-XXXXXX")
    trap 'rm -rf -- "$staging"' EXIT
    curl --fail --silent --show-error --location --retry 2 --connect-timeout 15 --proto '=https' \
        'https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/49a6f6eaab15ac3a961c24eed019c73ca6f57ace/scripts/partydeck-batocera-coop.py' \
        --output "$staging/partydeck-batocera-coop.py"
    (cd "$staging" && printf '%s  %s\n' '6eca4d19195588d3eda9a25b9a9dd3b522d18d819e10b332eba1d0c60a49f907' partydeck-batocera-coop.py | sha256sum -c -)
    mv -fT -- "$staging/partydeck-batocera-coop.py" "$coop_helper"
    rmdir -- "$staging"
    trap - EXIT

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

# Even on Xorg, Gamescope uses its own Xwayland server. Recent wlroots
# builds use a compiled-in path unless WLR_XWAYLAND is set explicitly.
if native_xwayland=$(command -v Xwayland); then
    export WLR_XWAYLAND="$native_xwayland"
else
    export PARTYDECK_XWAYLAND_APPDIR="$appdir"
    if [[ ! -x $xwayland_dir/Xwayland ]]; then
        install_portable_xwayland
    fi
    export WLR_XWAYLAND="$xwayland_dir/Xwayland"
fi
printf 'Xwayland utilisé par Gamescope : %s\n' "$WLR_XWAYLAND"
"$WLR_XWAYLAND" -version || die 'Le Xwayland sélectionné ne démarre pas.'

if [[ ${1:-verifier} == verifier ]]; then
    printf '\nVérifications de base OK. Dossier des jeux de test : %s\n' "$games"
    exit 0
fi

if [[ ${1:-verifier} == coop ]]; then
    [[ -f $coop_helper ]] || die 'Réinstallez le lanceur pour restaurer le module coop.'
    shift
    python3 "$coop_helper" play "$appdir" "$base" "$ports_dir" "$@"
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
if [[ $session == Xorg ]] && command -v unclutter-remote >/dev/null; then
    if unclutter-remote -s; then
        trap 'unclutter-remote -h || true' EXIT
        printf 'Curseur Xorg affiché pendant la session PartyDeck.\n'
    else
        printf 'Impossible de réafficher le curseur Xorg via unclutter-remote.\n' >&2
    fi
fi
"$appdir/AppRun" --exec "$executable"
