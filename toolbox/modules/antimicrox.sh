#!/bin/bash
# AntiMicroX opt-in per-game configuration. Profiles live outside archives.
AMX_OVERRIDES="$WT_HOME/config/antimicrox-games.tsv"
amx_binary() {
  # Menus and game hooks must use the same controlled runtime.
  if [ -x "$WT_HOME/tools/antimicrox/antimicrox" ]; then printf '%s\n' "$WT_HOME/tools/antimicrox/antimicrox"
  else return 1; fi
}
amx_install() {
  yesno AntiMicroX "$(amx_txt 'Télécharger et installer AntiMicroX 3.6.1 pour continuer ?' 'Download and install AntiMicroX 3.6.1 to continue?')" || return 1
  if ! WT_HOME="$WT_HOME" bash "$WT_ROOT/helpers/install-antimicrox.sh" > /tmp/uwt-amx-install.log 2>&1; then
    msgbox AntiMicroX "$(amx_txt 'Échec de l’installation. Journal : /tmp/uwt-amx-install.log' 'Installation failed. Log: /tmp/uwt-amx-install.log')"
    return 1
  fi
  amx_binary >/dev/null || {
    msgbox AntiMicroX "$(amx_txt 'Installation incomplète. Journal : /tmp/uwt-amx-install.log' 'Installation incomplete. Log: /tmp/uwt-amx-install.log')"
    return 1
  }
}
amx_ensure_installed() {
  amx_binary >/dev/null 2>&1 || amx_install
}
amx_running() {
  pgrep -x antimicrox >/dev/null 2>&1 ||
    pgrep -f "^$WT_HOME/tools/antimicrox/squashfs-root/(AppRun|usr/bin/antimicrox)([[:space:]]|$)" >/dev/null 2>&1
}
amx_txt() {
  if [ "$WT_LANGUAGE" = fr ]; then printf '%s' "$1"; else printf '%s' "$2"; fi
}
amx_set_profile() (
  local rom="$1" profile="$2" tmp output
  case "$rom$profile" in *$'\t'*|*$'\n'*) return 1 ;; esac
  if [ -f "${WT_ROOT:-}/helpers/antimicrox_pad2key.py" ]; then
    if ! output="$(amx_pad2key_cmd assign "$rom" "$profile" 2>&1)"; then
      case "$output" in
        *'Pad2Key changed while suspended'*)
          output="$(amx_txt 'Le Pad2Key a été remplacé ou modifié depuis son activation. Pour conserver vos modifications, reconvertissez le fichier .keys actuel de ce jeu, puis activez le nouveau profil. L’ancienne sauvegarde est conservée.' 'The Pad2Key was replaced or edited after activation. To keep your edits, reconvert this game’s current .keys file, then enable the new profile. The previous backup is retained.')" ;;
      esac
      msgbox AntiMicroX "$(amx_txt 'Association impossible :' 'Could not change assignment:')\n$output"
      return 1
    fi
    [ -z "$output" ] || msgbox AntiMicroX "$output"
    return 0
  fi
  mkdir -p "$(dirname "$AMX_OVERRIDES")"
  exec 8>"$(dirname "$AMX_OVERRIDES")/antimicrox-games.lock"
  flock -x 8 || return 1
  tmp="$(mktemp "$(dirname "$AMX_OVERRIDES")/.amx.XXXXXX")" || return 1
  if [ -f "$AMX_OVERRIDES" ]; then
    awk -F '\t' -v r="$rom" '$1!=r' "$AMX_OVERRIDES" > "$tmp"
  fi
  [ -z "$profile" ] || printf '%s\t%s\n' "$rom" "$profile" >> "$tmp"
  mv -f -- "$tmp" "$AMX_OVERRIDES"
)
amx_choose_game() {
  local -a options=()
  local -a games=()
  local rom selected id
  while IFS= read -r rom; do
    [ -n "$rom" ] || continue
    case "${rom,,}" in *.wine|*.pc|*.wsquashfs) ;; *) continue ;; esac
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
  amx_ensure_installed || return 1
  bin="$(amx_binary)" || return 1
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
amx_browse_profile() {
  local current="${1:-}" directory="$WT_HOME/config/antimicrox-profiles" start
  mkdir -p "$directory"
  start="$directory/"
  case "$current" in "$directory/"*) [ ! -f "$current" ] || start="$current" ;; esac
  if command -v yad >/dev/null 2>&1; then
    DISPLAY="${DISPLAY:-:0}" yad --file --title="AntiMicroX — .amgp" \
      --filename="$start" --file-filter='AntiMicroX | *.amgp' 2>/dev/null
  else
    input_text AntiMicroX "$(amx_txt 'Chemin absolu du profil .amgp sous /userdata :' 'Absolute .amgp profile path under /userdata:')" "$start"
  fi
}
# Select saved profiles directly; manual browsing remains available in the same menu.
amx_profile_file() {
  local current="${1:-}" rows profile selected label
  local -a profiles=() items=()
  rows="$(amx_profiles_cmd list 2>&1)" || { msgbox AntiMicroX "$rows"; return 1; }
  while IFS= read -r profile; do
    [ -n "$profile" ] || continue
    profiles+=("$profile")
    label="${profile##*/}"
    [ "$profile" != "$current" ] || label+=" — $(amx_txt 'actuel' 'current')"
    items+=("${#profiles[@]}" "$label")
  done <<< "$rows"
  selected="$(menu_select AntiMicroX "$(amx_txt 'Choisir un profil enregistré' 'Choose a saved profile')" "${items[@]}" \
    manual "$(amx_txt 'Parcourir les fichiers .amgp…' 'Browse .amgp files…')" back "$(i18n back)")" || return 1
  case "$selected" in
    manual) amx_browse_profile "$current" ;;
    back|'') return 1 ;;
    *) [[ "$selected" =~ ^[0-9]+$ ]] || return 1
       [ "$selected" -ge 1 ] && [ "$selected" -le "${#profiles[@]}" ] || return 1
       printf '%s\n' "${profiles[$((selected-1))]}" ;;
  esac
}
amx_game_for_profile() {
  local profile="$1" preferred selected
  preferred="$(community_cmd suggest-game antimicrox "$profile" 2>/dev/null)" || preferred=""
  selected="$(community_pick_game AntiMicroX "$preferred")" || return 1
  printf '%s\n' "${selected%%$'\t'*}"
}
amx_assign_existing() {
  local profile rom
  amx_ensure_installed || return 1
  profile="$(amx_profile_file)" || return 1
  profile="$(amx_validate_profile "$profile")" || return 1
  rom="$(amx_game_for_profile "$profile")" || return 1
  amx_assign_profile_for "$rom" "$profile"
}
amx_profiles_cmd() { python3 "$WT_ROOT/helpers/antimicrox_profiles.py" --home "$WT_HOME" --language "$WT_LANGUAGE" "$@"; }
amx_pad2key_cmd() { python3 "$WT_ROOT/helpers/antimicrox_pad2key.py" --home "$WT_HOME" --language "$WT_LANGUAGE" "$@"; }
amx_pad2key_source() {
  local current="${1:-/userdata/roms/windows/}"
  if command -v yad >/dev/null 2>&1; then
    DISPLAY="${DISPLAY:-:0}" yad --file --title="Pad2Key — .keys" --filename="$current" --file-filter='Pad2Key | *.keys' 2>/dev/null
  else
    input_text AntiMicroX "$(amx_txt 'Chemin du fichier Pad2Key .keys :' 'Pad2Key .keys file path:')" "$current"
  fi
}
amx_convert_pad2key() {
  local choice rom="" source preview report token profile candidates key label hotkey
  local -a hotkey_options=() hotkey_menu=()
  choice="$(menu_select AntiMicroX "$(amx_txt 'Récupérer les commandes Batocera (.keys) dans un profil AntiMicroX — joueur 1' 'Import Batocera controls (.keys) into an AntiMicroX profile — player 1')" \
    game "$(amx_txt 'Choisir un jeu Windows' 'Choose a Windows game')" \
    file "$(amx_txt 'Choisir un fichier .keys' 'Choose a .keys file')" back "$(i18n back)")" || return 0
  case "$choice" in
    game)
      rom="$(amx_choose_game)" || return 0
      case "${rom,,}" in *.wine|*.pc) source="$rom/padto.keys" ;; *) source="$rom.keys" ;; esac
      [ -f "$source" ] || source="$(amx_pad2key_source "$(dirname "$rom")/")" || return 0 ;;
    file) source="$(amx_pad2key_source)" || return 0 ;;
    *) return 0 ;;
  esac
  candidates="$(amx_pad2key_cmd hotkeys "$source" 2>&1)" || { msgbox AntiMicroX "$candidates"; return 1; }
  if [ -n "$candidates" ]; then
    while IFS=$'\t' read -r key label; do hotkey_menu+=("$key" "$label"); done <<< "$candidates"
    if [ "${#hotkey_menu[@]}" -eq 2 ]; then
      hotkey="${hotkey_menu[0]}"
    else
      hotkey="$(menu_select AntiMicroX "$(amx_txt 'Configuration Hotkey de la manette utilisée pour ce profil' 'Hotkey configuration of the controller used for this profile')" \
        "${hotkey_menu[@]}" skip "$(amx_txt 'Ne pas convertir les combinaisons Hotkey' 'Skip Hotkey chords')" back "$(i18n back)")" || return 0
      [ "$hotkey" != back ] || return 0
    fi
    [ "$hotkey" = skip ] || hotkey_options=(--hotkey "$hotkey")
  fi
  preview="$(amx_pad2key_cmd preview "$source" "${hotkey_options[@]}" 2>&1)" || { msgbox AntiMicroX "$preview"; return 1; }
  token="${preview%%$'\n'*}"
  report="$(mktemp /tmp/uwt-amx-conversion.XXXXXX)" || return 1
  printf '%s\n' "${preview#*$'\n'}" > "$report"
  if have_dialog; then
    wt_clear_tty
    dialog --clear --no-shadow --exit-label "$(i18n back)" --title AntiMicroX --textbox "$report" 24 100
    wt_clear_tty
  else
    cat "$report" >&2
  fi
  rm -f -- "$report"
  yesno AntiMicroX "$(amx_txt 'Créer le profil AntiMicroX avec les actions convertibles ?\n\nLes éventuelles actions non converties sont indiquées dans le bilan. Le Pad2Key original reste intact à cette étape.' 'Create an AntiMicroX profile with the supported actions?\n\nUnsupported actions are listed in the report. The original Pad2Key stays intact at this step.')" || return 0
  profile="$(amx_pad2key_cmd convert "$source" --expected "$token" "${hotkey_options[@]}" 2>&1)" || { msgbox AntiMicroX "$profile"; return 1; }
  while true; do
    choice="$(menu_select AntiMicroX "$(amx_txt "Profil créé :\n$profile" "Profile created:\n$profile")" \
      info "$(amx_txt 'Voir les commandes récupérées' 'View imported controls')" \
      edit "$(amx_txt 'Modifier le profil' 'Edit the profile')" \
      activate "$(amx_txt 'Utiliser ce profil pour un jeu' 'Use this profile for a game')" \
      live "$(amx_txt 'Utiliser et tester ce profil en jeu' 'Use and test this profile in game')" \
      back "$(amx_txt 'Conserver le profil sans l’activer' 'Keep profile without enabling it')")" || return 0
    case "$choice" in
      info) amx_profile_info "$profile" ;;
      edit) amx_editor "$profile" ;;
      activate|live)
        amx_ensure_installed || continue
        [ -n "$rom" ] || rom="$(amx_game_for_profile "$profile")" || continue
        if amx_running; then
          msgbox AntiMicroX "$(amx_txt 'Fermez le jeu et AntiMicroX avant d’activer la conversion.' 'Close the game and AntiMicroX before enabling the conversion.')"
          continue
        fi
        yesno AntiMicroX "$(amx_txt "Activer pour $(basename "$rom") ?\n\nLe Pad2Key du joueur 1 sera suspendu pour éviter le double mapping. Son contenu original sera sauvegardé et restauré si vous retirez l’association AntiMicroX.\n\nVérifiez les éventuelles actions non converties et les réglages de souris avant de jouer." "Enable for $(basename "$rom")?\n\nPlayer-one Pad2Key mapping will be suspended to avoid duplicate input. Its original content will be backed up and restored when the AntiMicroX assignment is removed.\n\nReview unsupported actions and mouse settings before playing.")" || continue
        amx_set_profile "$rom" "$profile" || continue
        if [ "$choice" = live ]; then
          amx_live_start_for "$rom" "$profile"
        else
          msgbox AntiMicroX "$(amx_txt 'Profil activé. Il sera chargé au prochain lancement du jeu.' 'Profile enabled. It will load on the next game launch.')"
        fi
        return 0 ;;
      *) return 0 ;;
    esac
  done
}
amx_profile_info() (
  local report
  report="$(mktemp /tmp/uwt-amx-profile.XXXXXX)" || return 1
  trap 'rm -f -- "$report"' EXIT
  amx_profiles_cmd report "$1" > "$report" 2>&1 || true
  if have_dialog; then
    wt_clear_tty
    dialog --clear --no-shadow --exit-label "$(i18n back)" --title AntiMicroX --textbox "$report" 24 100
    wt_clear_tty
  else
    cat "$report" >&2
    read -r -p "$(i18n press_enter)" _
  fi
)
amx_delete_profile_for() {
  local profile="$1" plan token output
  if amx_running; then
    msgbox AntiMicroX "$(amx_txt 'Fermez le jeu et AntiMicroX avant de supprimer un profil.' 'Close the game and AntiMicroX before deleting a profile.')"
    return 1
  fi
  plan="$(amx_profiles_cmd plan "$profile" 2>&1)" || {
    msgbox AntiMicroX "$(amx_txt 'Suppression impossible :' 'Cannot delete profile:')\n$plan"; return 1;
  }
  token="${plan%%$'\n'*}"
  if ! yesno AntiMicroX "$(amx_txt "Supprimer définitivement ce fichier profil ?\n\n${plan#*$'\n'}\n\nToutes ses associations seront également retirées." "Permanently delete this profile file?\n\n${plan#*$'\n'}\n\nAll its game assignments will also be removed.")"; then
    return 0
  fi
  if output="$(amx_profiles_cmd delete "$profile" "$token" 2>&1)"; then
    msgbox AntiMicroX "$(amx_txt 'Profil supprimé et associations retirées.' 'Profile deleted and assignments removed.')"
  else
    msgbox AntiMicroX "$(amx_txt 'Suppression impossible :' 'Could not delete profile:')\n$output"
    return 1
  fi
}
amx_delete_profiles() {
  local profile selected output
  local -a profiles=() options=()
  while true; do
    profiles=(); options=()
    output="$(amx_profiles_cmd list 2>&1)" || { msgbox AntiMicroX "$output"; return 1; }
    while IFS= read -r profile; do
      [ -n "$profile" ] || continue
      profiles+=("$profile")
      options+=("${#profiles[@]}" "$(basename "$profile") — $(dirname "$profile")")
    done <<< "$output"
    selected="$(menu_select AntiMicroX "$(amx_txt 'Choisissez le profil à supprimer. Il sera aussi retiré des jeux qui l’utilisent.' 'Choose a profile to delete. It will also be removed from games that use it.')" \
      "${options[@]}" other "$(amx_txt 'Choisir un autre fichier .amgp' 'Choose another .amgp file')" back "$(i18n back)")" || return 0
    case "$selected" in
      other) profile="$(amx_browse_profile '')" || continue ;;
      back|'') return 0 ;;
      *)
        [[ "$selected" =~ ^[0-9]+$ ]] || return 0
        [ "$selected" -ge 1 ] && [ "$selected" -le "${#profiles[@]}" ] || return 0
        profile="${profiles[$((selected-1))]}" ;;
    esac
    amx_delete_profile_for "$profile"
  done
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
  local rom="$1" current new_profile="${2:-}"
  amx_ensure_installed || return 1
  if amx_running; then
    msgbox AntiMicroX "$(amx_txt 'Fermez le jeu ou AntiMicroX avant de changer son profil.' 'Close the game or AntiMicroX before changing its profile.')"
    return 1
  fi
  current="$(amx_current_profile "$rom")"
  [ -n "$new_profile" ] || new_profile="$(amx_profile_file "$current")" || return 1
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
  local rom="$1" profile choice status shared
  while true; do
    profile="$(amx_current_profile "$rom")"
    [ -n "$profile" ] || return 0
    if [ "$(amx_launcher_cmd configured "$rom" "$profile" 2>/dev/null)" = 1 ]; then
      amx_manage_launcher_game "$rom"
      return
    fi
    status=""
    [ -e "$rom" ] || status="$(amx_txt 'Jeu introuvable : association conservée.' 'Game missing: association retained.')\n"
    [ -f "$profile" ] || status+="$(amx_txt 'Fichier profil introuvable.' 'Profile file missing.')\n"
    shared="$(amx_associations | awk -F '\t' -v p="$profile" '$2==p {n++} END{print n+0}')"
    [ "$shared" -le 1 ] || status+="$(amx_txt "Profil partagé par $shared jeux : le modifier affecte tous ces jeux." "Profile shared by $shared games: editing affects all of them.")\n"
    choice="$(menu_select AntiMicroX "$(basename "$rom")\n\n$(amx_txt 'Jeu :' 'Game:') $rom\n$(amx_txt 'Profil :' 'Profile:') $profile\n\n$status" \
      live "$(amx_txt 'Modifier les commandes et tester en jeu' 'Edit controls and test in game')" \
      edit "$(amx_txt 'Modifier le profil sans lancer le jeu' 'Edit the profile without starting the game')" \
      info "$(amx_txt 'Voir les commandes et les informations du profil' 'View profile controls and information')" \
      share "$(amx_txt 'Partager ce profil avec la communauté' 'Share this profile with the community')" \
      export "$(amx_txt 'Exporter la configuration dans un ZIP' 'Export configuration to a ZIP')" \
      replace "$(amx_txt 'Choisir un autre profil pour ce jeu' 'Choose another profile for this game')" \
      remove "$(amx_txt 'Désactiver pour ce jeu (garder le profil)' 'Disable for this game (keep the profile)')" \
      delete "$(amx_txt 'Supprimer ce profil pour tous les jeux' 'Delete this profile for all games')" \
      back "$(i18n back)")" || return
    case "$choice" in
      info) amx_profile_info "$profile" ;;
      share) community_share antimicrox AntiMicroX "$rom" "$profile" ;;
      export) community_share antimicrox AntiMicroX "$rom" "$profile" local ;;
      delete) amx_delete_profile_for "$profile" ;;
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
amx_live_cmd() { python3 "$WT_ROOT/helpers/antimicrox_live.py" --home "$WT_HOME" "$@"; }
amx_live_start_for() {
  local rom="$1" profile="${2:-}" learning="${3:-}" selected switch_label
  local -a options=()
  amx_ensure_installed || return 1
  [ -w /dev/uinput ] || {
    msgbox AntiMicroX "$(amx_txt 'Accès à /dev/uinput indisponible : AntiMicroX ne peut pas envoyer les commandes clavier/souris.' 'Access to /dev/uinput is unavailable: AntiMicroX cannot send keyboard/mouse input.')"; return 1;
  }
  command -v batocera-evmapy >/dev/null 2>&1 || {
    msgbox AntiMicroX "$(amx_txt 'batocera-evmapy est indisponible : session annulée.' 'batocera-evmapy is unavailable: session cancelled.')"; return 1;
  }
  if amx_running; then
    msgbox AntiMicroX "$(amx_txt 'Fermez l’éditeur AntiMicroX avant de lancer cette session.' 'Close the AntiMicroX editor before starting this session.')"; return 1;
  fi
  [ -z "$profile" ] || options=(--profile "$profile")
  [ "$learning" != learning ] || options+=(--launcher-learning)
  if ! selected="$(amx_live_cmd prepare "$rom" "${options[@]}" 2>/tmp/uwt-amx-live.log)"; then
    msgbox AntiMicroX "$(amx_txt 'Préparation impossible :' 'Preparation failed:')\n$(cat /tmp/uwt-amx-live.log)"
    return 1
  fi
  switch_label="$(amx_live_cmd field "switch_$WT_LANGUAGE")"
  msgbox AntiMicroX "$(amx_txt "Le jeu va démarrer avec l’éditeur ouvert.\n\nBasculer : $switch_label (activation directe des fenêtres). Appuyez puis relâchez les boutons pour basculer.\n\nModifiez puis testez vos affectations. Cliquez sur Enregistrer dans AntiMicroX AVANT de quitter le jeu.\n\nProfil : $selected\n\nLa combinaison est temporaire. Le menu AntiMicroX reviendra à la fin du jeu." "The game will start with the editor open.\n\nSwitch: $switch_label (direct window activation). Press and release the buttons to switch.\n\nEdit and test your mappings. Click Save in AntiMicroX BEFORE quitting the game.\n\nProfile: $selected\n\nThe shortcut is temporary. The AntiMicroX menu will return when the game closes.")" || {
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
amx_live_choose_standard() {
  local rom current choice profile
  local -a options=()
  amx_ensure_installed || return 1
  rom="$(amx_choose_game)" || return
  current="$(awk -F '\t' -v p="$rom" '$1==p {v=$2} END{print v}' "$AMX_OVERRIDES" 2>/dev/null)"
  [ ! -f "$current" ] || options=(current "$(amx_txt 'Modifier le profil actuel de ce jeu' 'Edit this game’s current profile')")
  choice="$(menu_select AntiMicroX "$(amx_txt 'Choisissez un profil, puis ajustez ses commandes en jouant. Vous pourrez passer du jeu à l’éditeur.' 'Choose a profile, then adjust its controls while playing. You can switch between the game and editor.')" \
    "${options[@]}" new "$(amx_txt 'Créer un nouveau profil pour ce jeu' 'Create a new profile for this game')" \
    existing "$(amx_txt 'Choisir un autre profil enregistré' 'Choose another saved profile')" \
    back "$(i18n back)")" || return
  case "$choice" in
    current) profile="$current" ;;
    new) profile="" ;;
    existing) profile="$(amx_profile_file "$current")" || return ;;
    *) return ;;
  esac
  amx_live_start_for "$rom" "$profile"
}
amx_live_choose() {
  local choice
  choice="$(menu_select AntiMicroX "$(amx_txt 'Quel type de configuration souhaitez-vous créer ou modifier ?' 'Which type of configuration do you want to create or edit?')" \
    standard "$(amx_txt 'Profil classique pour le jeu' 'Standard game profile')" \
    launcher "$(amx_txt 'Jeu avec launcher : profils et fenêtres' 'Game with a launcher: profiles and windows')" back "$(i18n back)")" || return
  case "$choice" in
    standard) amx_live_choose_standard ;;
    launcher) amx_launchers_menu ;;
  esac
}
amx_live_resume() {
  local rom profile result error choice
  [ -f "$WT_HOME/state/antimicrox-live.json" ] || return 0
  /bin/bash "$WT_ROOT/hooks/antimicrox-game-event.sh" amxStop windows '' '' live
  if ! amx_live_cmd finish --result recovered 2>/tmp/uwt-amx-live.log; then
    msgbox AntiMicroX "$(amx_txt 'Restauration du raccourci incomplète. Sauvegarde conservée dans state/antimicrox-live.json :' 'Shortcut restoration incomplete. Backup retained in state/antimicrox-live.json:')\n$(cat /tmp/uwt-amx-live.log)"
    return 1
  fi
  # A terminal close can bypass every menu action below. Acknowledge before
  # showing the result so a delayed handoff cannot enqueue another return.
  amx_live_cmd presented || return 1
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
  if [ "$(amx_live_cmd field runtime_test)" = True ]; then
    amx_launcher_test_resume "$rom" "$result" "$error"
    return
  fi
  if [ "$(amx_live_cmd field launcher_learning)" = True ]; then
    amx_live_cmd clear || return 1
    [ -z "$error" ] || msgbox AntiMicroX "$result\n$error"
    amx_launcher_setup "$rom" "$profile"
    amx_launchers_menu "$rom"
    return
  fi
  while true; do
    choice="$(menu_select AntiMicroX "$(amx_txt "Session terminée : $(basename "$rom")\nProfil : $profile\nRésultat : $result\n$error\nRaccourci temporaire retiré.\nJournal : /userdata/system/logs/ultimate-wine-toolbox/antimicrox.log" "Session finished: $(basename "$rom")\nProfile: $profile\nResult: $result\n$error\nTemporary shortcut removed.\nLog: /userdata/system/logs/ultimate-wine-toolbox/antimicrox.log")" \
      activate "$(amx_txt 'Utiliser ce profil aux prochains lancements' 'Use this profile whenever this game starts')" \
      retry "$(amx_txt 'Continuer les réglages en jeu' 'Continue adjusting controls in game')" \
      launcher "$(amx_txt 'Configurer les règles launcher / jeu (test)' 'Configure launcher / game rules (test)')" \
      back "$(i18n back)")" || choice=back
    case "$choice" in
      launcher) amx_launcher_setup "$rom" "$profile" ;;
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
amx_launcher_cmd() { python3 "$WT_ROOT/helpers/antimicrox_launcher.py" --home "$WT_HOME" "$@"; }

amx_launcher_test_start() {
  local rom="$1" profile output
  amx_ensure_installed || return 1
  if amx_running; then
    msgbox AntiMicroX "$(amx_txt 'Fermez le jeu et AntiMicroX avant de tester les règles.' 'Close the game and AntiMicroX before testing rules.')"
    return 1
  fi
  profile="$(amx_current_profile "$rom")"
  if ! output="$(amx_launcher_cmd prepare-test "$rom" "$profile" 2>&1)"; then
    msgbox AntiMicroX "$output"; return 1
  fi
  if ! msgbox AntiMicroX "$(amx_txt 'Le jeu va être relancé avec les règles automatiques enregistrées.\n\nVérifiez le mapping dans le launcher, puis son changement ou sa désactivation en jeu. Quittez le jeu pour revenir aux options Retester / Modifier les règles. L’éditeur AntiMicroX ne sera pas ouvert.' 'The game will restart with the saved automatic rules.\n\nCheck mappings in the launcher, then switching or disabling them in game. Quit to return to Retest / Edit rules. The AntiMicroX editor will not open.')"; then
    amx_live_cmd finish --result cancelled && amx_live_cmd clear
    return 1
  fi
  if ! printf '%s\n' "$rom" > "$WT_HOME/state/launch-game.request.tmp" ||
     ! mv -f -- "$WT_HOME/state/launch-game.request.tmp" "$WT_HOME/state/launch-game.request"; then
    amx_live_cmd finish --result request_failed && amx_live_cmd clear
    return 1
  fi
  exit 0
}

amx_launcher_test_resume() {
  local rom="$1" result="$2" error="$3" choice profile
  while true; do
    choice="$(menu_select AntiMicroX "$(basename "$rom")\n\n$(amx_txt 'Test des règles terminé :' 'Rules test finished:') $result\n$error" \
      retry "$(amx_txt 'Retester les règles enregistrées' 'Retest saved rules')" \
      edit "$(amx_txt 'Modifier les règles puis retester' 'Edit rules and retest')" \
      learn "$(amx_txt 'Refaire l’apprentissage des fenêtres' 'Learn windows again')" back "$(i18n back)")" || choice=back
    case "$choice" in
      retry) amx_launcher_test_start "$rom" ;;
      edit)
        amx_live_cmd clear || return 1
        amx_launcher_setup "$rom"
        amx_launchers_menu "$rom"
        return ;;
      learn)
        amx_live_cmd clear || return 1
        profile="$(amx_current_profile "$rom")"
        amx_launcher_cmd learn "$rom" || return 1
        amx_live_start_for "$rom" "$profile" learning
        return ;;
      *) amx_live_cmd clear; return ;;
    esac
  done
}

# Choose recorded metadata after the game closes. No in-game dialog steals focus.
amx_launcher_rule() (
  local rom="$1" role="$2" rows selected index title class exe field match value output
  local -a items=()
  rows="$(amx_launcher_cmd observations "$rom" 2>/dev/null)" || rows=""
  while IFS=$'\t' read -r index title class exe; do
    [ -n "$index" ] || continue
    items+=("$index" "$title — $exe — $class")
  done <<< "$rows"
  selected="$(menu_select AntiMicroX "$role\n\n$(amx_txt 'Choisir une fenêtre relevée pendant le dernier apprentissage, ou saisir une règle. Le titre distingue les fenêtres d’un même exécutable.' 'Choose a window recorded during the last learning session, or enter a rule. Titles distinguish windows of the same executable.')" \
    "${items[@]}" manual "$(amx_txt 'Saisir une règle manuellement' 'Enter a rule manually')" back "$(i18n back)")" || exit 1
  [ "$selected" != back ] || exit 1
  field="$(menu_select AntiMicroX "$(amx_txt 'Reconnaître la fenêtre par :' 'Match the window using:')" \
    title "$(amx_txt 'Titre de fenêtre (conseillé)' 'Window title (recommended)')" \
    class "$(amx_txt 'Classe de fenêtre' 'Window class')" \
    exe "$(amx_txt 'Nom de l’exécutable Wine' 'Wine executable name')" back "$(i18n back)")" || exit 1
  case "$field" in title|class|exe) ;; *) exit 1 ;; esac
  if [ "$selected" = manual ]; then
    value="$(input_text AntiMicroX "$(amx_txt 'Valeur à reconnaître :' 'Value to match:')" '')" || exit 1
  else
    [[ "$selected" =~ ^[0-9]+$ ]] || exit 1
    output="$(amx_launcher_cmd observation-rule "$rom" "$selected" "$field" 2>/tmp/uwt-amx-launcher.log)" || {
      msgbox AntiMicroX "$(cat /tmp/uwt-amx-launcher.log)"; exit 1;
    }
    value="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["value"])' "$output")" || exit 1
  fi
  match="$(menu_select AntiMicroX "$(amx_txt 'Type de correspondance :' 'Match type:')\n$value" \
    exact "$(amx_txt 'Valeur exacte' 'Exact value')" \
    contains "$(amx_txt 'Contient une partie stable' 'Contains a stable part')" back "$(i18n back)")" || exit 1
  case "$match" in exact) ;; contains)
    value="$(input_text AntiMicroX "$(amx_txt 'Partie stable du titre ou du nom :' 'Stable part of the title or name:')" "$value")" || exit 1 ;;
    *) exit 1 ;;
  esac
  amx_launcher_cmd rule "$field" "$match" "$value"
)

amx_launcher_setup() {
  local rom="$1" profile="${2:-}" mode game_profile="" launcher_rule game_rule="" choice output old
  local -a options=()
  if amx_running; then
    msgbox AntiMicroX "$(amx_txt 'Fermez le jeu et AntiMicroX avant d’enregistrer les règles.' 'Close the game and AntiMicroX before saving rules.')"
    return 1
  fi
  mode="$(menu_select AntiMicroX "$(basename "$rom")\n\n$(amx_txt 'Comportement du mapping aux prochains lancements :' 'Mapping behavior for future launches:')" \
    launcher "$(amx_txt 'Launcher uniquement, puis commandes natives du jeu' 'Launcher only, then native game controls')" \
    profiles "$(amx_txt 'Un profil launcher et un profil jeu distinct' 'Separate launcher and game profiles')" back "$(i18n back)")" || return
  case "$mode" in launcher|profiles) ;; *) return ;; esac
  [ -n "$profile" ] || profile="$(amx_profile_file "$(amx_current_profile "$rom")")" || return
  profile="$(amx_validate_profile "$profile")" || return
  launcher_rule="$(amx_launcher_rule "$rom" "$(amx_txt 'Fenêtre du launcher' 'Launcher window')")" || return
  if [ "$mode" = profiles ]; then
    msgbox AntiMicroX "$(amx_txt 'Choisissez maintenant le profil à appliquer dans le jeu.' 'Now choose the profile to apply in the game.')"
    game_profile="$(amx_profile_file)" || return
    game_profile="$(amx_validate_profile "$game_profile")" || return
    choice="$(menu_select AntiMicroX "$(amx_txt 'Quand activer le profil jeu ?' 'When should the game profile activate?')" \
      specific "$(amx_txt 'Seulement sur une fenêtre de jeu identifiée (conseillé)' 'Only on an identified game window (recommended)')" \
      other "$(amx_txt 'Sur toute autre fenêtre Wine de cette session' 'On any other Wine window in this session')" back "$(i18n back)")" || return
    case "$choice" in
      specific) game_rule="$(amx_launcher_rule "$rom" "$(amx_txt 'Fenêtre du jeu' 'Game window')")" || return ;;
      other) ;; *) return ;;
    esac
    options=(--game-profile "$game_profile")
    [ -z "$game_rule" ] || options+=(--game-rule "$game_rule")
  fi
  yesno AntiMicroX "$(amx_txt 'Enregistrer et activer ces règles ?\n\nLe profil launcher sera actif uniquement sur la fenêtre reconnue. Hors des fenêtres reconnues, le mapping sera vide. Le mode de configuration en jeu reste manuel et ignore ces règles.\n\nLes jeux embarquant déjà AntiMicroX Windows doivent être testés sans cette seconde instance.' 'Save and enable these rules?\n\nThe launcher profile is active only on its matching window. Outside recognized windows, mappings are empty. Live editing remains manual and ignores these rules.\n\nGames bundling Windows AntiMicroX must be tested without that second instance.')\n\n$launcher_rule${game_rule:+\n$game_rule}" || return
  # Backend validates every path and rule before any association change.
  if ! output="$(amx_launcher_cmd save "$rom" "$mode" "$profile" "$launcher_rule" "${options[@]}" --check 2>&1)"; then
    msgbox AntiMicroX "$output"; return 1
  fi
  old="$(amx_current_profile "$rom")"
  amx_set_profile "$rom" "$profile" || return 1
  if ! output="$(amx_launcher_cmd save "$rom" "$mode" "$profile" "$launcher_rule" "${options[@]}" 2>&1)"; then
    amx_set_profile "$rom" "$old" || true
    msgbox AntiMicroX "$output"
    return 1
  fi
  choice="$(menu_select AntiMicroX "$(amx_txt 'Règles enregistrées. Vous pouvez relancer le jeu immédiatement pour les tester.' 'Rules saved. You can restart the game immediately to test them.')" \
    test "$(amx_txt 'Tester maintenant les fenêtres choisies' 'Test the selected windows now')" \
    back "$(amx_txt 'Conserver les règles et revenir' 'Keep rules and return')")" || return
  [ "$choice" != test ] || amx_launcher_test_start "$rom"
}

amx_manage_launcher_game() {
  local rom="$1" profile game_profile choice output
  local -a items=()
  while true; do
    profile="$(amx_current_profile "$rom")"
    [ -n "$profile" ] || return
    game_profile="$(amx_launcher_cmd game-profile "$rom" "$profile" 2>/dev/null)" || game_profile=""
    items=(test "$(amx_txt 'Retester la bascule launcher / jeu' 'Retest launcher / game switching')"
      rules "$(amx_txt 'Modifier les fenêtres, le mode ou les profils associés' 'Edit windows, mode or assigned profiles')"
      edit_launcher "$(amx_txt 'Modifier les commandes du profil launcher' 'Edit launcher profile controls')")
    [ -z "$game_profile" ] || items+=(edit_game "$(amx_txt 'Modifier les commandes du profil jeu' 'Edit game profile controls')")
    items+=(export "$(amx_txt 'Exporter la configuration complète dans un ZIP' 'Export the complete configuration to a ZIP')"
      share "$(amx_txt 'Partager la configuration complète avec la communauté' 'Share the complete configuration with the community')"
      learn "$(amx_txt 'Configurer en jeu et refaire le relevé des fenêtres' 'Configure in game and record windows again')"
      info "$(amx_txt 'Voir les règles et les profils' 'View rules and profiles')"
      classic "$(amx_txt 'Désactiver les règles launcher (garder le profil)' 'Disable launcher rules (keep the profile)')"
      remove "$(amx_txt 'Désactiver AntiMicroX pour ce jeu (garder les profils)' 'Disable AntiMicroX for this game (keep profiles)')"
      back "$(i18n back)")
    choice="$(menu_select AntiMicroX "$(basename "$rom")\n\n$(amx_txt 'Jeu avec launcher' 'Game with a launcher')\n$(amx_txt 'Profil launcher :' 'Launcher profile:') $profile${game_profile:+\n$(amx_txt 'Profil jeu :' 'Game profile:') $game_profile}" "${items[@]}")" || return
    case "$choice" in
      share) community_share antimicrox AntiMicroX "$rom" "$profile" ;;
      export) community_share antimicrox AntiMicroX "$rom" "$profile" local ;;
      test) amx_launcher_test_start "$rom" ;;
      rules) amx_launcher_setup "$rom" ;;
      edit_launcher) amx_editor "$profile" ;;
      edit_game) [ -z "$game_profile" ] || amx_editor "$game_profile" ;;
      learn) amx_launcher_learn_for "$rom"; return ;;
      info)
        output="$(amx_launcher_cmd show "$rom" 2>&1)"
        msgbox AntiMicroX "$output"
        amx_profile_info "$profile"
        [ -z "$game_profile" ] || amx_profile_info "$game_profile" ;;
      classic)
        if amx_running; then msgbox AntiMicroX "$(amx_txt 'Fermez le jeu et AntiMicroX.' 'Close the game and AntiMicroX.')"; continue; fi
        if yesno AntiMicroX "$(amx_txt 'Désactiver les règles launcher et conserver le profil classique pour ce jeu ?' 'Disable launcher rules and keep the standard profile for this game?')"; then
          amx_launcher_cmd disable "$rom" || continue
          amx_manage_game "$rom"
          return
        fi ;;
      remove)
        if amx_running; then msgbox AntiMicroX "$(amx_txt 'Fermez le jeu et AntiMicroX.' 'Close the game and AntiMicroX.')"; continue; fi
        if yesno AntiMicroX "$(amx_txt 'Retirer les règles et l’association de ce jeu ? Les fichiers profils seront conservés.' 'Remove rules and this game assignment? Profile files will be kept.')"; then
          amx_launcher_cmd disable "$rom" || continue
          amx_set_profile "$rom" "" && return
        fi ;;
      *) return ;;
    esac
  done
}

amx_launcher_learn_for() {
  local rom="$1" profile choice
  if amx_running; then
    msgbox AntiMicroX "$(amx_txt 'Fermez le jeu et AntiMicroX avant l’apprentissage.' 'Close the game and AntiMicroX before learning.')"; return
  fi
  profile="$(amx_current_profile "$rom")"
  if [ -n "$profile" ]; then
    choice="$(menu_select AntiMicroX "$(amx_txt 'Profil pour configurer le launcher :' 'Profile for configuring the launcher:')" \
      current "$(amx_txt 'Modifier le profil actuel' 'Edit the current profile')" \
      new "$(amx_txt 'Créer un nouveau profil' 'Create a new profile')" \
      existing "$(amx_txt 'Choisir un profil enregistré' 'Choose a saved profile')" back "$(i18n back)")" || return
  else
    choice="$(menu_select AntiMicroX "$(amx_txt 'Profil pour configurer le launcher :' 'Profile for configuring the launcher:')" \
      new "$(amx_txt 'Créer un nouveau profil' 'Create a new profile')" \
      existing "$(amx_txt 'Choisir un profil enregistré' 'Choose a saved profile')" back "$(i18n back)")" || return
  fi
  case "$choice" in current) ;; new) profile="" ;; existing) profile="$(amx_profile_file)" || return ;; *) return ;; esac
  amx_launcher_cmd learn "$rom" || return
  msgbox AntiMicroX "$(amx_txt 'Le relevé démarre avec le jeu.\n\nAffichez le launcher, configurez et enregistrez son mapping dans AntiMicroX, puis passez dans le jeu quelques secondes. Quittez normalement. Au retour, la sélection des fenêtres et des règles s’ouvrira directement.\n\nHotkey+R1 et Alt+Tab gardent leur fonctionnement habituel.' 'Recording starts with the game.\n\nShow the launcher, configure and save its mapping in AntiMicroX, then enter the game for a few seconds. Quit normally. Window and rule selection will open directly on return.\n\nHotkey+R1 and Alt+Tab keep their usual behavior.')"
  amx_live_start_for "$rom" "$profile" learning
}

amx_launchers_menu() {
  local rom="${1:-}" choice profile output
  amx_ensure_installed || return
  [ -n "$rom" ] || rom="$(amx_choose_game)" || return
  while true; do
    choice="$(menu_select AntiMicroX "$(basename "$rom")\n\n$(amx_txt 'Jeu avec launcher\n\nConfigurez les commandes et relevez les fenêtres, puis choisissez quand chaque profil doit être actif.' 'Game with a launcher\n\nConfigure controls and record windows, then choose when each profile should be active.')" \
      learn "$(amx_txt 'Apprendre les fenêtres et configurer le mapping en jeu' 'Learn windows and configure mappings in game')" \
      setup "$(amx_txt 'Configurer les profils et les règles' 'Configure profiles and rules')" \
      test "$(amx_txt 'Retester les règles enregistrées' 'Retest saved rules')" \
      show "$(amx_txt 'Voir les règles enregistrées' 'View saved rules')" \
      disable "$(amx_txt 'Désactiver les règles (garder le profil associé)' 'Disable rules (keep the assigned profile)')" back "$(i18n back)")" || return
    case "$choice" in
      learn) amx_launcher_learn_for "$rom"; return ;;
      setup) amx_launcher_setup "$rom" ;;
      test) amx_launcher_test_start "$rom" ;;
      show)
        output="$(amx_launcher_cmd show "$rom" 2>&1)"
        msgbox AntiMicroX "$output" ;;
      disable)
        if amx_running; then msgbox AntiMicroX "$(amx_txt 'Fermez le jeu et AntiMicroX.' 'Close the game and AntiMicroX.')"; continue; fi
        amx_launcher_cmd disable "$rom" ;;
      *) return ;;
    esac
  done
}

antimicrox_menu() {
  local choice rom bin output rc intro
  if [ -f "$WT_HOME/state/antimicrox-live.json" ]; then
    amx_live_resume || return
  fi
  while true; do
    bin="$(amx_binary 2>/dev/null || true)"
    intro="$(amx_txt 'Utilisez la manette dans les jeux prévus pour le clavier et la souris. Un profil enregistre les commandes de votre manette pour un jeu.\n\nCommencez par créer un profil en jeu, ou utilisez un profil déjà prêt.' 'Use your controller in games designed for keyboard and mouse. A profile stores your controller mappings for a game.\n\nStart by creating a profile in game, or use a ready-made profile.')"
    [ -n "$bin" ] || intro+="\n\n$(amx_txt 'AntiMicroX sera proposé à l’installation quand une action en a besoin.' 'You will be offered installation when an action needs AntiMicroX.')"
    choice="$(menu_select "AntiMicroX" "$intro" \
      1 "$(amx_txt 'Créer ou modifier un profil en jeu' 'Create or edit a profile in game')" \
      2 "$(amx_txt 'Mes jeux et leurs profils' 'My games and their profiles')" \
      3 "$(amx_txt 'Utiliser un profil existant pour un jeu' 'Use an existing profile for a game')" \
      4 "$(amx_txt 'Télécharger ou partager des profils' 'Download or share profiles')" \
      5 "$(amx_txt 'Convertir un Pad2Key (.keys) en profil' 'Convert a Pad2Key (.keys) file to a profile')" \
      6 "$(amx_txt 'Ouvrir l’éditeur sans lancer de jeu' 'Open the editor without starting a game')" \
      7 "$(amx_txt 'Voir les manettes détectées' 'View detected controllers')" \
      8 "$(amx_txt 'Supprimer un profil enregistré' 'Delete a saved profile')" \
      9 "$(amx_txt 'Installer ou mettre à jour AntiMicroX' 'Install or update AntiMicroX')" \
      0 "$(i18n back)")" || return
    case "$choice" in
      1) amx_live_choose ;;
      2) amx_manage_associations ;;
      3) amx_assign_existing ;;
      4|community) community_menu antimicrox ;;
      5) amx_convert_pad2key ;;
      6) amx_editor ;;
      7)
        amx_ensure_installed || continue
        bin="$(amx_binary)" || continue
        output="$(timeout 15 "$bin" --list 2>&1)"; rc=$?
        msgbox "AntiMicroX" "$(amx_txt "Manettes détectées (code $rc) :" "Detected controllers (code $rc):")\n$output" ;;
      8) amx_delete_profiles ;;
      9) amx_install && msgbox AntiMicroX "$(amx_txt 'AntiMicroX est installé.' 'AntiMicroX is installed.')" ;;
      0|'') return ;;
    esac
  done
}
