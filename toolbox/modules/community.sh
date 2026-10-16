#!/bin/bash
# Shared implementation; each tool keeps its own menu and file type.
community_txt() { if [ "${WT_LANGUAGE:-fr}" = fr ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }
community_cmd() { python3 "$WT_ROOT/helpers/community_profiles.py" --home "$WT_HOME" --language "$WT_LANGUAGE" "$@"; }
community_report() {
  local title="$1" content="$2" report
  report="$(mktemp /tmp/uwt-community.XXXXXX)" || return 1
  printf '%s\n' "$content" | python3 -c 'import sys,textwrap; print("\n".join(textwrap.fill(line, 88, replace_whitespace=False) if line.strip() else "" for line in sys.stdin.read().splitlines()))' > "$report"
  if have_dialog; then
    wt_clear_tty
    dialog --no-shadow --title "$title" --exit-label "$(i18n back)" --textbox "$report" 25 100
    wt_clear_tty
  else
    msgbox "$title" "$content"
  fi
  rm -f -- "$report"
}

community_import_actions() {
  local kind="$1" path="$2" title="$3" rom="${4:-}" choice output details
  while true; do
    if [ "$kind" = antimicrox ]; then
      choice="$(menu_select "$title" "$(community_txt "Profil téléchargé :\n$path\n\nVérifiez la Hotkey dans l’éditeur avant activation. Le Pad2Key du jeu sera sauvegardé et suspendu lors de l’association." "Profile downloaded:\n$path\n\nCheck the Hotkey in the editor before enabling. The game’s Pad2Key will be backed up and suspended on assignment.")" \
        info "$(community_txt 'Afficher tous les mappages' 'Show all mappings')" \
        edit "$(community_txt 'Ouvrir dans l’éditeur' 'Open in editor')" \
        assign "$(community_txt 'Associer à un jeu' 'Assign to a game')" \
        live "$(community_txt 'Configurer et tester en jeu' 'Configure and test in game')" back "$(i18n back)")" || return 0
      case "$choice" in
        info) amx_profile_info "$path" ;;
        edit) amx_editor "$path" ;;
        assign|live)
          if amx_running; then msgbox "$title" "$(community_txt 'Fermez AntiMicroX et le jeu avant l’association.' 'Close AntiMicroX and the game before assigning.')"; continue; fi
          [ -n "$rom" ] || rom="$(amx_choose_game)" || continue
          yesno "$title" "$(community_txt "Associer ce profil à $(basename "$rom") ?\nVérifiez ses prérequis et sa Hotkey. Le Pad2Key sera sauvegardé et suspendu." "Assign this profile to $(basename "$rom")?\nCheck its requirements and Hotkey. Pad2Key will be backed up and suspended.")" || continue
          amx_set_profile "$rom" "$path" || continue
          if [ "$choice" = live ]; then amx_live_start_for "$rom" "$path"; else msgbox "$title" "$(community_txt 'Profil associé.' 'Profile assigned.')"; fi
          return 0 ;;
        *) return 0 ;;
      esac
    else
      choice="$(menu_select "$title" "$(community_txt "Preset téléchargé :\n$path\n\nInstallez d’abord ReShade et les effets indiqués pour le jeu." "Preset downloaded:\n$path\n\nInstall ReShade and the listed effects for the game first.")" \
        apply "$(community_txt 'Appliquer à un jeu configuré' 'Apply to a configured game')" back "$(i18n back)")" || return 0
      [ "$choice" = apply ] || return 0
      [ -n "$rom" ] || rom="$(amx_choose_game)" || continue
      details="$(resh_cmd status "$rom")" || continue
      if [ "$details" = missing ]; then msgbox "$title" "$(community_txt 'Installez ReShade pour ce jeu depuis son menu, puis réessayez.' 'Install ReShade for this game from its menu, then retry.')"; continue; fi
      yesno "$title" "$(community_txt "Appliquer à $(basename "$rom") ?\nLe preset actuel sera exporté dans les sauvegardes communautaires avant remplacement. Les packs de shaders doivent être installés." "Apply to $(basename "$rom")?\nThe current preset will be exported to the community backups before replacement. Shader packs must be installed.")" || continue
      local backup_dir="$WT_HOME/exports/community-backups" backup
      mkdir -p "$backup_dir"
      backup="$(mktemp "$backup_dir/reshade-XXXXXX.ini")" || return 1
      if ! output="$(resh_cmd export "$rom" "$backup" overwrite 2>&1)"; then
        rm -f -- "$backup"; msgbox "$title" "$output"; continue
      fi
      if output="$(resh_cmd preset "$rom" "$path" 2>&1)"; then
        msgbox "$title" "$(community_txt "Preset appliqué.\nSauvegarde : $backup" "Preset applied.\nBackup: $backup")"; return 0
      else
        msgbox "$title" "$(community_txt "Échec de l’application. Sauvegarde conservée :\n$backup\n$output" "Apply failed. Backup retained:\n$backup\n$output")"
      fi
    fi
  done
}

community_pick_game() {
  local title="$1" query="" rows path name choice
  local -a games=() items=()
  while true; do
    if ! rows="$(community_cmd games --query "$query" 2>&1)"; then
      msgbox "$title" "$(community_txt 'Impossible de lire la liste des jeux Windows d’ES. Vérifiez que le jeu est référencé dans ES.' 'Unable to read the ES Windows game list. Check that ES has indexed the game.')\n$rows"; return 1
    fi
    games=(); items=()
    while IFS=$'\t' read -r path name; do
      [ -n "$path" ] || continue
      games+=("$path"$'\t'"$name")
      items+=("${#games[@]}" "$name — ${path##*/}")
    done <<< "$rows"
    choice="$(menu_select "$title" "$(community_txt 'Choisir le jeu dans la liste d’EmulationStation' 'Choose the game from the EmulationStation list')" \
      search "$(community_txt 'Rechercher un jeu' 'Search for a game')" "${items[@]}" back "$(i18n back)")" || return 1
    case "$choice" in
      search) query="$(input_text "$title" "$(community_txt 'Nom du jeu à rechercher' 'Game name to search for')" "$query")" || return 1 ;;
      ''|back) return 1 ;;
      *[!0-9]*) return 1 ;;
      *) [ "$choice" -ge 1 ] && [ "$choice" -le "${#games[@]}" ] || return 1
         printf '%s' "${games[$((choice-1))]}"; return 0 ;;
    esac
  done
}

community_share_game() {
  local kind="$1" source="$2" title="$3" rom="${4:-}" suggested choice selected
  local -a context=()
  [ -z "$rom" ] || context=(--rom "$rom")
  suggested="$(community_cmd suggest-game "$kind" "$source" "${context[@]}" 2>/dev/null)" || suggested=""
  if [ -n "$suggested" ]; then
    choice="$(menu_select "$title" "$(community_txt "Jeu identifié : $suggested" "Detected game: $suggested")" \
      use "$(community_txt 'Utiliser ce nom de jeu' 'Use this game name')" \
      select "$(community_txt 'Choisir dans la liste des jeux ES' 'Choose from the ES game list')" back "$(i18n back)")" || return 1
    case "$choice" in use) printf '%s' "$suggested"; return 0 ;; select) : ;; *) return 1 ;; esac
  fi
  selected="$(community_pick_game "$title")" || return 1
  printf '%s' "${selected#*$'\t'}"
}

community_share() {
  local kind="$1" title="$2" rom="${3:-}" source game="" author name description tested notes requirement output selected temporary=""
  if [ "$kind" = antimicrox ]; then
    source="$(amx_profile_file '')" || return 0
  else
    if [ -z "$rom" ]; then
      selected="$(community_pick_game "$title")" || return 0
      rom="${selected%%$'\t'*}"; game="${selected#*$'\t'}"
    fi
    temporary="$(mktemp /tmp/uwt-community-preset.XXXXXX.ini)" || return 1
    if ! output="$(resh_cmd export "$rom" "$temporary" overwrite 2>&1)"; then
      rm -f -- "$temporary"; msgbox "$title" "$output"; return 1
    fi
    source="$temporary"
  fi
  if [ -z "$game" ]; then
    game="$(community_share_game "$kind" "$source" "$title" "$rom")" || { [ -z "$temporary" ] || rm -f -- "$temporary"; return 0; }
  fi
  name="$(input_text "$title" "$(community_txt 'Nom du profil / preset' 'Profile / preset title')" "$game")" || { rm -f -- "$temporary"; return 0; }
  author="$(input_text "$title" "$(community_txt 'Votre pseudo public' 'Your public nickname')" '')" || { rm -f -- "$temporary"; return 0; }
  description="$(input_text "$title" "$(community_txt 'Description courte' 'Short description')" '')" || { rm -f -- "$temporary"; return 0; }
  tested="$(input_text "$title" "$(community_txt 'Versions testées : jeu, Batocera, runner, AntiMicroX/ReShade' 'Tested versions: game, Batocera, runner, AntiMicroX/ReShade')" '')" || { rm -f -- "$temporary"; return 0; }
  requirement="$(input_text "$title" "$(community_txt 'Prérequis : manette/Hotkey ou packs de shaders, effets et textures' 'Requirements: controller/Hotkey or shader packs, effects and textures')" '')" || { rm -f -- "$temporary"; return 0; }
  notes="$(input_text "$title" "$(community_txt 'Remarques de compatibilité (facultatif)' 'Compatibility notes (optional)')" '')" || { rm -f -- "$temporary"; return 0; }
  if ! yesno "$title" "$(community_txt "Préparer le partage public de « $name » pour $game, sous le pseudo $author ?\n\nUn ZIP sera créé avec le profil et ces informations. Vous pourrez le joindre à une proposition GitHub depuis votre PC ; un compte GitHub est nécessaire pour soumettre. Rien n’est publié automatiquement." "Prepare public sharing of '$name' for $game, credited to $author?\n\nA ZIP will contain the profile and these details. Attach it to a GitHub proposal from your PC; submitting requires a GitHub account. Nothing is published automatically.")"; then
    rm -f -- "$temporary"; return 0
  fi
  local -a requirements=()
  [ -z "$requirement" ] || requirements=(--requirement "$requirement")
  output="$(community_cmd share "$kind" "$source" --game "$game" --title "$name" --author "$author" \
    --description "$description" --tested-on "$tested" --notes "$notes" "${requirements[@]}" 2>&1)"
  local status=$?
  [ -z "$temporary" ] || rm -f -- "$temporary"
  if [ "$status" -ne 0 ]; then msgbox "$title" "$output"; return 1; fi
  community_report "$title" "$(community_txt "Paquet prêt :\n$output\n\nLe même lien est enregistré dans le fichier .txt à côté du ZIP. Depuis votre PC, ouvrez ce lien et joignez le ZIP. Après validation, il rejoindra le catalogue." "Package ready:\n$output\n\nThe same link is saved in the .txt next to the ZIP. On your PC, open it and attach the ZIP. Once reviewed, it can enter the catalogue.")"
}

community_menu() {
  local kind="$1" rom="${2:-}" title choice query="" rows id label selected details path output
  local -a items=()
  if [ "$kind" = antimicrox ]; then title="AntiMicroX — $(community_txt 'Profils communautaires' 'Community profiles')"; else title="ReShade — $(community_txt 'Presets communautaires' 'Community presets')"; fi
  while true; do
    choice="$(menu_select "$title" "$(community_txt 'Catalogue partagé sur GitHub. Téléchargement sans compte ; contributions proposées puis validées.' 'Shared GitHub catalogue. Downloads require no account; contributions are submitted for review.')" \
      browse "$(community_txt 'Parcourir le catalogue en cache' 'Browse cached catalogue')" \
      search "$(community_txt 'Rechercher un jeu / auteur' 'Search for a game / author')" \
      refresh "$(community_txt 'Actualiser le catalogue' 'Refresh catalogue')" \
      share "$(community_txt 'Préparer le partage de mon profil / preset' 'Prepare sharing my profile / preset')" back "$(i18n back)")" || return 0
    case "$choice" in
      refresh)
        if output="$(community_cmd refresh 2>&1)"; then msgbox "$title" "$(community_txt "Catalogue actualisé : $output entrées au total." "Catalogue refreshed: $output total entries.")"; else msgbox "$title" "$(community_txt 'Actualisation impossible ; le cache précédent reste disponible.' 'Refresh failed; the previous cache remains available.')\n$output"; fi
        continue ;;
      share) community_share "$kind" "$title" "$rom"; continue ;;
      search) query="$(input_text "$title" "$(community_txt 'Jeu, titre du profil ou auteur' 'Game, profile title or author')" '')" || continue ;;
      browse) query="" ;;
      *) return 0 ;;
    esac
    if ! rows="$(community_cmd list "$kind" --query "$query" 2>&1)"; then msgbox "$title" "$rows"; continue; fi
    if [ -z "$rows" ]; then msgbox "$title" "$(community_txt 'Aucun profil trouvé pour cette recherche. Vous pouvez actualiser ou proposer le vôtre.' 'No profile found. Refresh the catalogue or contribute your own.')"; continue; fi
    items=()
    while IFS=$'\t' read -r id label; do items+=("$id" "$label"); done <<< "$rows"
    selected="$(menu_select "$title" "$(community_txt 'Choisir une contribution' 'Choose a contribution')" "${items[@]}" back "$(i18n back)")" || continue
    [ "$selected" != back ] || continue
    details="$(community_cmd show "$kind" "$selected" 2>&1)" || { msgbox "$title" "$details"; continue; }
    community_report "$title" "$details"
    yesno "$title" "$(community_txt 'Télécharger cette contribution ? Elle sera conservée dans un nouveau fichier local.' 'Download this contribution? It will be stored in a new local file.')" || continue
    if path="$(community_cmd fetch "$kind" "$selected" 2>&1)"; then community_import_actions "$kind" "$path" "$title" "$rom"; else msgbox "$title" "$path"; fi
  done
}
