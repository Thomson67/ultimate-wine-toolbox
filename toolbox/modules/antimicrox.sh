#!/bin/bash
# AntiMicroX opt-in per-game configuration. Profiles live outside archives.
AMX_OVERRIDES="$WT_HOME/config/antimicrox-games.tsv"
amx_binary() {
  # Menus and game hooks must use the same controlled runtime.
  if [ -x "$WT_HOME/tools/antimicrox/antimicrox" ]; then printf '%s\n' "$WT_HOME/tools/antimicrox/antimicrox"
  else return 1; fi
}
amx_running() {
  pgrep -x antimicrox >/dev/null 2>&1 ||
    pgrep -f "^$WT_HOME/tools/antimicrox/squashfs-root/(AppRun|usr/bin/antimicrox)([[:space:]]|$)" >/dev/null 2>&1
}
amx_txt() {
  if [ "$WT_LANGUAGE" = fr ]; then printf '%s' "$1"; else printf '%s' "$2"; fi
}
amx_set_profile() {
  local rom="$1" profile="$2" tmp
  case "$rom$profile" in *$'\t'*|*$'\n'*) return 1 ;; esac
  mkdir -p "$(dirname "$AMX_OVERRIDES")"
  tmp="$(mktemp "$(dirname "$AMX_OVERRIDES")/.amx.XXXXXX")" || return 1
  if [ -f "$AMX_OVERRIDES" ]; then
    awk -F '\t' -v r="$rom" '$1!=r' "$AMX_OVERRIDES" > "$tmp"
  fi
  [ -z "$profile" ] || printf '%s\t%s\n' "$rom" "$profile" >> "$tmp"
  mv -f -- "$tmp" "$AMX_OVERRIDES"
}
amx_choose_game() {
  local -a options=()
  local -a games=()
  local rom selected id
  while IFS= read -r rom; do
    [ -n "$rom" ] || continue
    case "$rom" in *.wine|*.pc|*.wsquashfs) ;; *) continue ;; esac
    games+=("$rom")
    options+=("${#games[@]}" "$(basename "$rom")")
  done < <(mangohud_list_games)
  [ "${#games[@]}" -gt 0 ] || {
    msgbox "AntiMicroX" "$(amx_txt 'Aucun jeu Windows trouvé.' 'No Windows games found.')"
    return 1
  }
  selected="$(menu_select "AntiMicroX" "$(amx_txt 'Choisir le jeu à configurer' 'Choose a game to configure')" "${options[@]}")" || return 1
  [[ "$selected" =~ ^[0-9]+$ ]] || return 1
  [ "$selected" -ge 1 ] && [ "$selected" -le "${#games[@]}" ] || return 1
  printf '%s\n' "${games[$((selected-1))]}"
}
amx_log_path() { printf '%s\n' /userdata/system/logs/ultimate-wine-toolbox/antimicrox-editor.log; }
amx_editor() {
  local bin log rc profile="${1:-}"
  local -a profile_args=()
  if [ -n "$profile" ]; then
    profile="$(amx_validate_profile "$profile")" || return 1
    profile_args=(--profile "$profile")
  fi
  bin="$(amx_binary)" || { msgbox AntiMicroX "$(amx_txt 'Installez AntiMicroX depuis son menu.' 'Install AntiMicroX from its menu.')"; return 1; }
  log="$(amx_log_path)"
  mkdir -p "$(dirname "$log")"
  # An editor must not silently replace a running game's mapping via IPC.
  if amx_running; then
    msgbox AntiMicroX "$(amx_txt 'Fermez le jeu ou AntiMicroX déjà actif avant d’ouvrir l’éditeur.' 'Close the game or existing AntiMicroX instance before opening the editor.')"
    return 1
  fi
  msgbox AntiMicroX "$(amx_txt 'L’éditeur va s’ouvrir. Enregistrez votre profil .amgp sous /userdata, puis fermez l’éditeur pour revenir à la Toolbox.' 'The editor will open. Save your .amgp profile under /userdata, then close the editor to return to the Toolbox.')${profile:+\n\n$profile}"
  [ ! -f "$log" ] || cp -f -- "$log" "${log%.log}.previous.log"
  # Foreground: no success popup hiding the Qt window; no orphaned editor.
  (export XDG_CONFIG_HOME="$WT_HOME/config/antimicrox-editor"
   printf '===== AntiMicroX editor %s =====\nDISPLAY=%s WAYLAND_DISPLAY=%s\n' "$(date -Iseconds)" "${DISPLAY:-:0}" "${WAYLAND_DISPLAY:-unset}"
   # Source-tree tests may only load this module; installed packages include it.
   if [ -f "${WT_ROOT:-}/helpers/antimicrox_editor.py" ]; then
     python3 "$WT_ROOT/helpers/antimicrox_editor.py" "$XDG_CONFIG_HOME" || echo 'WARNING: editor geometry preparation failed'
   fi
   # 3.6.1 unconditionally rebuilds trayIconMenu when Settings is accepted.
   # --no-tray leaves it null and causes a reproducible QMenu::clear SIGSEGV.
   "$bin" --show --eventgen uinput --log-level info "${profile_args[@]}") > "$log" 2>&1
  rc=$?
  if [ "$rc" -ne 0 ]; then
    msgbox AntiMicroX "$(amx_txt "Échec de l’éditeur (code $rc). Journal : $log" "Editor failed (code $rc). Log: $log")\n$(tail -n 12 "$log")"
  fi
  return "$rc"
}
amx_profile_file() {
  local current="$1"
  if command -v yad >/dev/null 2>&1; then
    DISPLAY="${DISPLAY:-:0}" yad --file-selection --title="AntiMicroX — .amgp" \
      --filename="${current:-/userdata/}" --file-filter='AntiMicroX | *.amgp' 2>/dev/null
  else
    input_text AntiMicroX "$(amx_txt 'Chemin absolu du profil .amgp sous /userdata :' 'Absolute .amgp profile path under /userdata:')" "$current"
  fi
}
amx_validate_profile() {
  local profile="$1"
  case "$profile" in /userdata/*.amgp) ;; *) msgbox AntiMicroX "$(amx_txt 'Chemin .amgp invalide.' 'Invalid .amgp path.')"; return 1 ;; esac
  [ -f "$profile" ] || { msgbox AntiMicroX "$(amx_txt 'Profil introuvable.' 'Profile not found.')"; return 1; }
  profile="$(readlink -f -- "$profile")" || return 1
  case "$profile" in /userdata/*) ;; *) msgbox AntiMicroX "$(amx_txt 'Le profil doit rester sous /userdata.' 'The profile must stay under /userdata.')"; return 1 ;; esac
  printf '%s\n' "$profile"
}
amx_current_profile() {
  awk -F '\t' -v p="$1" '$1==p {v=$2} END{print v}' "$AMX_OVERRIDES" 2>/dev/null
}
amx_assign_profile_for() {
  local rom="$1" current new_profile
  current="$(amx_current_profile "$rom")"
  new_profile="$(amx_profile_file "$current")" || return 1
  new_profile="$(amx_validate_profile "$new_profile")" || return 1
  amx_set_profile "$rom" "$new_profile" || return 1
  msgbox AntiMicroX "$(amx_txt 'Profil associé au jeu.' 'Profile assigned to game.')"
}
amx_associations() {
  [ -f "$AMX_OVERRIDES" ] || return 0
  # Match the hook's last-entry semantics, including games no longer on disk.
  awk -F '\t' 'NF==2 && $1!="" {p[$1]=$2} END {for(r in p) if(p[r]!="") print r "\t" p[r]}' "$AMX_OVERRIDES" | LC_ALL=C sort
}
amx_manage_game() {
  local rom="$1" profile choice status shared info
  while true; do
    profile="$(amx_current_profile "$rom")"
    [ -n "$profile" ] || return 0
    status=""
    [ -e "$rom" ] || status="$(amx_txt 'Jeu introuvable : association conservée.' 'Game missing: association retained.')\n"
    [ -f "$profile" ] || status+="$(amx_txt 'Fichier profil introuvable.' 'Profile file missing.')\n"
    shared="$(amx_associations | awk -F '\t' -v p="$profile" '$2==p {n++} END{print n+0}')"
    [ "$shared" -le 1 ] || status+="$(amx_txt "Profil partagé par $shared jeux : le modifier affecte tous ces jeux." "Profile shared by $shared games: editing affects all of them.")\n"
    choice="$(menu_select AntiMicroX "$(basename "$rom")\n\n$(amx_txt 'Jeu :' 'Game:') $rom\n$(amx_txt 'Profil :' 'Profile:') $profile\n\n$status" \
      info "$(amx_txt 'Afficher les détails du profil' 'Show profile details')" \
      edit "$(amx_txt 'Modifier le profil dans l’éditeur' 'Edit profile in the editor')" \
      live "$(amx_txt 'Modifier et tester en jeu' 'Edit and test in game')" \
      replace "$(amx_txt 'Remplacer le profil associé' 'Replace the assigned profile')" \
      remove "$(amx_txt 'Retirer l’association (conserver le profil)' 'Remove assignment (keep profile file)')" \
      back "$(i18n back)")" || return
    case "$choice" in
      info)
        info="$(python3 - "$profile" "$WT_LANGUAGE" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
try:
    path = Path(sys.argv[1])
    root = ET.parse(path).getroot()
    labels = ('Type XML', 'Actions enregistrées', 'Taille (octets)') if sys.argv[2] == 'fr' else ('XML type', 'Recorded actions', 'Size (bytes)')
    for label, value in zip(labels, (root.tag, len(root.findall('.//slot')), path.stat().st_size)):
        print(f'{label} : {value}')
except (OSError, ET.ParseError) as error:
    print(str(error))
PY
)"
        msgbox AntiMicroX "$profile\n\n$info" ;;
      edit) amx_editor "$profile" ;;
      live)
        if [ ! -e "$rom" ]; then
          msgbox AntiMicroX "$(amx_txt 'Jeu introuvable. Remettez-le à son emplacement avant de le lancer.' 'Game missing. Restore it to its location before launching.')"
        else
          amx_live_start_for "$rom" "$profile"
        fi ;;
      replace) amx_assign_profile_for "$rom" ;;
      remove)
        if yesno AntiMicroX "$(amx_txt "Retirer le profil pour $(basename "$rom") ?\n\nLe fichier .amgp est conservé. Le changement s’appliquera au prochain lancement du jeu." "Remove the profile assignment for $(basename "$rom")?\n\nThe .amgp file is kept. The change takes effect on the next game launch.")"; then
          amx_set_profile "$rom" "" && return 0
        fi ;;
      *) return ;;
    esac
  done
}
amx_manage_associations() {
  local rom profile selected label
  local -a games=() options=()
  while true; do
    games=(); options=()
    while IFS=$'\t' read -r rom profile; do
      [ -n "$rom" ] && [ -n "$profile" ] || continue
      games+=("$rom")
      label="$(basename "$rom") — $(basename "$profile")"
      [ -e "$rom" ] || label+=" $(amx_txt '[jeu absent]' '[game missing]')"
      [ -f "$profile" ] || label+=" $(amx_txt '[profil absent]' '[profile missing]')"
      options+=("${#games[@]}" "$label")
    done < <(amx_associations)
    [ "${#games[@]}" -gt 0 ] || {
      msgbox AntiMicroX "$(amx_txt 'Aucun jeu avec un profil associé.' 'No games with an assigned profile.')"
      return 0
    }
    selected="$(menu_select AntiMicroX "$(amx_txt "Jeux avec un profil associé : ${#games[@]}\nChoisissez un jeu pour consulter ou gérer son profil." "Games with an assigned profile: ${#games[@]}\nChoose a game to view or manage its profile.")" \
      "${options[@]}" back "$(i18n back)")" || return 0
    [[ "$selected" =~ ^[0-9]+$ ]] || return 0
    [ "$selected" -ge 1 ] && [ "$selected" -le "${#games[@]}" ] || return 0
    amx_manage_game "${games[$((selected-1))]}"
  done
}
amx_diagnostic() {
  local bin output rc log
  bin="$(amx_binary 2>/dev/null || true)"
  log="$(amx_log_path)"
  if [ -n "$bin" ]; then
    output="$(timeout 15 "$bin" --version 2>&1)"; rc=$?
  else
    output="$(amx_txt 'Binaire absent' 'Binary missing')"; rc=127
  fi
  msgbox AntiMicroX "$(amx_txt "Binaire : ${bin:-absent}" "Binary: ${bin:-missing}")\nQt : xcb / XWayland\nDISPLAY : ${DISPLAY:-:0}\n/dev/uinput : $([ -w /dev/uinput ] && echo OK || echo indisponible/unavailable)\nVersion (code $rc) : $output\nJournal : $log\n$(tail -n 8 "$log" 2>/dev/null)"
}
amx_live_cmd() { python3 "$WT_ROOT/helpers/antimicrox_live.py" --home "$WT_HOME" "$@"; }
amx_live_start_for() {
  local rom="$1" profile="${2:-}" selected
  local -a options=()
  [ -n "$(amx_binary 2>/dev/null)" ] && [ -w /dev/uinput ] || {
    msgbox AntiMicroX "$(amx_txt 'Installez AntiMicroX et vérifiez /dev/uinput avec le diagnostic.' 'Install AntiMicroX and check /dev/uinput in diagnostics.')"; return 1;
  }
  command -v batocera-evmapy >/dev/null 2>&1 || {
    msgbox AntiMicroX "$(amx_txt 'batocera-evmapy est indisponible : session annulée.' 'batocera-evmapy is unavailable: session cancelled.')"; return 1;
  }
  if amx_running; then
    msgbox AntiMicroX "$(amx_txt 'Fermez l’éditeur AntiMicroX avant de lancer cette session.' 'Close the AntiMicroX editor before starting this session.')"; return 1;
  fi
  [ -z "$profile" ] || options=(--profile "$profile")
  if ! selected="$(amx_live_cmd prepare "$rom" "${options[@]}" 2>/tmp/uwt-amx-live.log)"; then
    msgbox AntiMicroX "$(amx_txt 'Préparation impossible :' 'Preparation failed:')\n$(cat /tmp/uwt-amx-live.log)"
    return 1
  fi
  msgbox AntiMicroX "$(amx_txt "Le jeu va démarrer avec l’éditeur ouvert.\n\nBasculer : Alt+Tab ou Hotkey + bouton du BAS (Croix DualSense / A Xbox). Relâchez les boutons après chaque bascule.\n\nModifiez puis testez vos affectations. Cliquez sur Enregistrer dans AntiMicroX AVANT de quitter le jeu.\n\nProfil : $selected\n\nLa combinaison est temporaire. Le menu AntiMicroX reviendra à la fin du jeu." "The game will start with the editor open.\n\nSwitch: Alt+Tab or Hotkey + BOTTOM button (DualSense Cross / Xbox A). Release the buttons after each switch.\n\nEdit and test your mappings. Click Save in AntiMicroX BEFORE quitting the game.\n\nProfile: $selected\n\nThe shortcut is temporary. The AntiMicroX menu will return when the game closes.")" || {
    if amx_live_cmd finish --result cancelled; then amx_live_cmd clear; fi
    return 1
  }
  if ! printf '%s\n' "$rom" > "$WT_HOME/state/launch-game.request.tmp" ||
     ! mv -f -- "$WT_HOME/state/launch-game.request.tmp" "$WT_HOME/state/launch-game.request"; then
    if amx_live_cmd finish --result request_failed; then amx_live_cmd clear; fi
    msgbox AntiMicroX "$(amx_txt 'Échec de la demande de lancement.' 'Failed to request game launch.')"
    return 1
  fi
  exit 0
}
amx_live_choose() {
  local rom current choice profile
  local -a options=()
  rom="$(amx_choose_game)" || return
  current="$(awk -F '\t' -v p="$rom" '$1==p {v=$2} END{print v}' "$AMX_OVERRIDES" 2>/dev/null)"
  [ ! -f "$current" ] || options=(current "$(amx_txt 'Modifier le profil déjà associé' 'Edit the assigned profile')")
  choice="$(menu_select AntiMicroX "$(amx_txt 'Profil à configurer en jeu' 'Profile to configure in game')" \
    "${options[@]}" new "$(amx_txt 'Créer un profil pour ce jeu' 'Create a profile for this game')" \
    existing "$(amx_txt 'Choisir un profil existant' 'Choose an existing profile')" \
    back "$(i18n back)")" || return
  case "$choice" in
    current) profile="$current" ;;
    new) profile="" ;;
    existing) profile="$(amx_profile_file "$current")" || return ;;
    *) return ;;
  esac
  amx_live_start_for "$rom" "$profile"
}
amx_live_resume() {
  local rom profile result error choice
  [ -f "$WT_HOME/state/antimicrox-live.json" ] || return 0
  /bin/bash "$WT_ROOT/hooks/antimicrox-game-event.sh" amxStop windows '' '' live
  if ! amx_live_cmd finish --result recovered 2>/tmp/uwt-amx-live.log; then
    msgbox AntiMicroX "$(amx_txt 'Restauration du raccourci incomplète. Sauvegarde conservée dans state/antimicrox-live.json :' 'Shortcut restoration incomplete. Backup retained in state/antimicrox-live.json:')\n$(cat /tmp/uwt-amx-live.log)"
    return 1
  fi
  rom="$(amx_live_cmd field rom)"
  if [ -f "$WT_HOME/state/launch-game.request" ] &&
     [ "$(cat "$WT_HOME/state/launch-game.request")" = "$rom" ]; then
    rm -f -- "$WT_HOME/state/launch-game.request"
  fi
  profile="$(amx_live_cmd field profile)"
  result="$(amx_live_cmd field result)"
  case "$result" in
    normal|short|stopped) result="$(amx_txt 'Jeu fermé' 'Game closed')" ;;
    recovered|interrupted) result="$(amx_txt 'Session précédente récupérée' 'Previous session recovered')" ;;
    *) result="$(amx_txt 'Lancement non confirmé' 'Launch not confirmed')" ;;
  esac
  error="$(amx_live_cmd field error)"
  while true; do
    choice="$(menu_select AntiMicroX "$(amx_txt "Session terminée : $(basename "$rom")\nProfil : $profile\nRésultat : $result\n$error\nRaccourci temporaire retiré.\nJournal : /userdata/system/logs/ultimate-wine-toolbox/antimicrox.log" "Session finished: $(basename "$rom")\nProfile: $profile\nResult: $result\n$error\nTemporary shortcut removed.\nLog: /userdata/system/logs/ultimate-wine-toolbox/antimicrox.log")" \
      activate "$(amx_txt 'Activer ce profil pour ce jeu' 'Enable this profile for the game')" \
      retry "$(amx_txt 'Relancer la configuration en jeu' 'Retry in-game configuration')" \
      back "$(i18n back)")" || choice=back
    case "$choice" in
      activate)
        if [ -f "$profile" ] && amx_set_profile "$rom" "$profile"; then
          amx_live_cmd clear
          msgbox AntiMicroX "$(amx_txt 'Profil associé au jeu.' 'Profile assigned to game.')"
          return 0
        fi ;;
      retry)
        amx_live_cmd clear || return 1
        amx_live_start_for "$rom" "$profile"
        return ;;
      *) amx_live_cmd clear; return ;;
    esac
  done
}
antimicrox_menu() {
  local choice rom bin output rc
  if [ -f "$WT_HOME/state/antimicrox-live.json" ]; then
    amx_live_resume || return
  fi
  while true; do
    bin="$(amx_binary 2>/dev/null || true)"
    choice="$(menu_select "AntiMicroX" "$(amx_txt 'Configuration native par jeu. Profils hors des préfixes Wine. Le binaire Linux doit être disponible et /dev/uinput fonctionnel.' 'Native per-game configuration. Profiles outside Wine prefixes. Linux binary and /dev/uinput required.')" \
      7 "$(amx_txt 'Configurer et tester en jeu (bêta)' 'Configure and test in game (beta)')" \
      2 "$(amx_txt 'Gérer les jeux avec un profil associé' 'Manage games with assigned profiles')" \
      1 "$(amx_txt 'Associer un profil à un jeu' 'Assign a game profile')" \
      3 "$(amx_txt 'Ouvrir l’éditeur de profils' 'Open profile editor')" \
      4 "$(amx_txt 'Lister les manettes détectées' 'List detected controllers')" \
      5 "$(amx_txt "Installer / mettre à jour AntiMicroX" "Install / update AntiMicroX")" \
      6 "$(amx_txt "Diagnostic" "Diagnostics")" \
      0 "$(i18n back)")" || return
    case "$choice" in
      7) amx_live_choose ;;
      5)
        if yesno "AntiMicroX" "$(amx_txt "Télécharger AntiMicroX 3.6.1 depuis GitHub et installer dans /userdata ?" "Download AntiMicroX 3.6.1 from GitHub and install under /userdata?")"; then
          if "$WT_ROOT/helpers/install-antimicrox.sh" > /tmp/uwt-amx-install.log 2>&1; then
            msgbox "AntiMicroX" "$(amx_txt "Runtime extrait et installé. Testez maintenant l’éditeur et la détection des manettes." "Runtime extracted and installed. Now test the editor and gamepad detection.")"
          else
            msgbox "AntiMicroX" "$(amx_txt "Échec de l’installation. Consultez /tmp/uwt-amx-install.log" "Installation failed. Check /tmp/uwt-amx-install.log")"
          fi
        fi
        ;;
      6) amx_diagnostic ;;
      1)
        rom="$(amx_choose_game)" || continue
        amx_assign_profile_for "$rom"
        ;;
      2) amx_manage_associations ;;
      3) amx_editor ;;
      4)
        [ -n "$bin" ] || { msgbox "AntiMicroX" "$(amx_txt 'Binaire absent.' 'Binary missing.')"; continue; }
        output="$(timeout 15 "$bin" --list 2>&1)"; rc=$?
        msgbox "AntiMicroX" "$(amx_txt "Détection (code $rc) :" "Detection (code $rc):")\n$output"
        ;;
      0|'') return ;;
    esac
  done
}
