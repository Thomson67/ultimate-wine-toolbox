#!/bin/bash
# AntiMicroX opt-in per-game configuration. Profiles live outside archives.
AMX_OVERRIDES="$WT_HOME/config/antimicrox-games.tsv"
amx_binary() {
  # Menus and game hooks must use the same controlled runtime.
  if [ -x "$WT_HOME/tools/antimicrox/antimicrox" ]; then printf '%s\n' "$WT_HOME/tools/antimicrox/antimicrox"
  else return 1; fi
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
  local bin log rc
  bin="$(amx_binary)" || { msgbox AntiMicroX "$(amx_txt 'Installez AntiMicroX depuis son menu.' 'Install AntiMicroX from its menu.')"; return 1; }
  log="$(amx_log_path)"
  mkdir -p "$(dirname "$log")"
  # An editor must not silently replace a running game's mapping via IPC.
  if pgrep -x antimicrox >/dev/null 2>&1; then
    msgbox AntiMicroX "$(amx_txt 'Fermez le jeu ou AntiMicroX déjà actif avant d’ouvrir l’éditeur.' 'Close the game or existing AntiMicroX instance before opening the editor.')"
    return 1
  fi
  msgbox AntiMicroX "$(amx_txt 'L’éditeur va s’ouvrir. Enregistrez votre profil .amgp sous /userdata, puis fermez l’éditeur pour revenir à la Toolbox.' 'The editor will open. Save your .amgp profile under /userdata, then close the editor to return to the Toolbox.')"
  # Foreground: no success popup hiding the Qt window; no orphaned editor.
  (export XDG_CONFIG_HOME="$WT_HOME/config/antimicrox-editor"
   "$bin" --show --no-tray --eventgen uinput) > "$log" 2>&1
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
antimicrox_menu() {
  local choice rom current new_profile bin output rc
  while true; do
    bin="$(amx_binary 2>/dev/null || true)"
    choice="$(menu_select "AntiMicroX" "$(amx_txt 'Configuration native par jeu. Profils hors des préfixes Wine. Le binaire Linux doit être disponible et /dev/uinput fonctionnel.' 'Native per-game configuration. Profiles outside Wine prefixes. Linux binary and /dev/uinput required.')" \
      1 "$(amx_txt 'Associer un profil à un jeu' 'Assign a game profile')" \
      2 "$(amx_txt 'Désactiver pour un jeu' 'Disable for a game')" \
      3 "$(amx_txt 'Ouvrir l’éditeur de profils' 'Open profile editor')" \
      4 "$(amx_txt 'Lister les manettes détectées' 'List detected controllers')" \
      5 "$(amx_txt "Installer / mettre à jour AntiMicroX" "Install / update AntiMicroX")" \
      6 "$(amx_txt "Diagnostic" "Diagnostics")" \
      0 "$(i18n back)")" || return
    case "$choice" in
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
        current="$(awk -F '\t' -v p="$rom" '$1==p {v=$2} END{print v}' "$AMX_OVERRIDES" 2>/dev/null)"
        new_profile="$(amx_profile_file "$current")" || continue
        case "$new_profile" in /userdata/*.amgp) ;; *) msgbox "AntiMicroX" "$(amx_txt 'Chemin .amgp invalide.' 'Invalid .amgp path.')"; continue ;; esac
        [ -f "$new_profile" ] || { msgbox "AntiMicroX" "$(amx_txt 'Profil introuvable.' 'Profile not found.')"; continue; }
        new_profile="$(readlink -f -- "$new_profile")" || continue
        case "$new_profile" in /userdata/*) ;; *) msgbox AntiMicroX "$(amx_txt 'Le profil doit rester sous /userdata.' 'The profile must stay under /userdata.')"; continue ;; esac
        amx_set_profile "$rom" "$new_profile" || continue
        msgbox "AntiMicroX" "$(amx_txt 'Profil associé au jeu.' 'Profile assigned to game.')"
        ;;
      2) rom="$(amx_choose_game)" || continue; amx_set_profile "$rom" "";;
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
