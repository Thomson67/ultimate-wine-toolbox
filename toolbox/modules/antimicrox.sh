#!/bin/bash
# AntiMicroX opt-in per-game configuration. Profiles live outside archives.
AMX_OVERRIDES="$WT_HOME/config/antimicrox-games.tsv"
amx_binary() {
  if command -v antimicrox >/dev/null 2>&1; then command -v antimicrox
  elif [ -x "$WT_HOME/tools/antimicrox/antimicrox" ]; then printf '%s\n' "$WT_HOME/tools/antimicrox/antimicrox"
  else return 1; fi
}
amx_txt() {
  if [ "$WT_LANGUAGE" = fr ]; then printf '%s' "$1"; else printf '%s' "$2"; fi
}
amx_set_profile() {
  local rom="$1" profile="$2" tmp
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
antimicrox_menu() {
  local choice rom current new_profile bin
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
            msgbox "AntiMicroX" "$(amx_txt "Installation terminée. Vérifiez la détection des manettes." "Installation finished. Verify gamepad detection.")"
          else
            msgbox "AntiMicroX" "$(amx_txt "Échec de l’installation. Consultez /tmp/uwt-amx-install.log" "Installation failed. Check /tmp/uwt-amx-install.log")"
          fi
        fi
        ;;
      6)
        msgbox "AntiMicroX" "$(amx_txt "Binaire : ${bin:-absent}\n/dev/uinput : $([ -w /dev/uinput ] && echo OK || echo indisponible)\nSession : $([ -e "$WT_HOME/state/antimicrox/session" ] && echo active || echo inactive)" "Binary: ${bin:-missing}\n/dev/uinput: $([ -w /dev/uinput ] && echo OK || echo unavailable)\nSession: $([ -e "$WT_HOME/state/antimicrox/session" ] && echo active || echo inactive)")"
        ;;
      1)
        rom="$(amx_choose_game)" || continue
        current="$(awk -F '\t' -v p="$rom" '$1==p {v=$2} END{print v}' "$AMX_OVERRIDES" 2>/dev/null)"
        new_profile="$(input_text "AntiMicroX" "$(amx_txt 'Chemin absolu du profil .amgp dans /userdata :' 'Absolute .amgp profile path under /userdata:')" "$current")" || continue
        case "$new_profile" in /userdata/*.amgp) ;; *) msgbox "AntiMicroX" "$(amx_txt 'Chemin .amgp invalide.' 'Invalid .amgp path.')"; continue ;; esac
        [ -f "$new_profile" ] || { msgbox "AntiMicroX" "$(amx_txt 'Profil introuvable.' 'Profile not found.')"; continue; }
        amx_set_profile "$rom" "$new_profile"
        msgbox "AntiMicroX" "$(amx_txt 'Profil associé au jeu.' 'Profile assigned to game.')"
        ;;
      2) rom="$(amx_choose_game)" || continue; amx_set_profile "$rom" "";;
      3)
        [ -n "$bin" ] || { msgbox "AntiMicroX" "$(amx_txt 'Binaire absent.' 'Binary missing.')"; continue; }
        "$bin" --eventgen uinput >/dev/null 2>&1 &
        msgbox "AntiMicroX" "$(amx_txt 'Éditeur lancé. Enregistrez un profil .amgp sous /userdata.' 'Editor launched. Save an .amgp profile under /userdata.')"
        ;;
      4)
        [ -n "$bin" ] || { msgbox "AntiMicroX" "$(amx_txt 'Binaire absent.' 'Binary missing.')"; continue; }
        msgbox "AntiMicroX" "$("$bin" --list 2>&1)"
        ;;
      0|'') return ;;
    esac
  done
}
