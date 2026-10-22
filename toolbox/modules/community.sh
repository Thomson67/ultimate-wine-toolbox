#!/bin/bash
# Shared implementation; each tool keeps its own menu and file type.
community_txt() { if [ "${WT_LANGUAGE:-fr}" = fr ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }
community_cmd() { python3 "$WT_ROOT/helpers/community_profiles.py" --home "$WT_HOME" --language "$WT_LANGUAGE" "$@"; }
community_service_cmd() { python3 "$WT_ROOT/helpers/community_service.py" --home "$WT_HOME" --language "$WT_LANGUAGE" "$@"; }
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
  local kind="$1" path="$2" title="$3" rom="${4:-}" choice output details selected
  while true; do
    if [ "$kind" = antimicrox ]; then
      choice="$(menu_select "$title" "$(community_txt "Profil téléchargé :
$path

Vérifiez la Hotkey dans l’éditeur avant activation. Le Pad2Key du jeu sera sauvegardé et suspendu lors de l’association." "Profile downloaded:
$path

Check the Hotkey in the editor before enabling. The game’s Pad2Key will be backed up and suspended on assignment.")" \
        info "$(community_txt 'Voir les commandes de la manette' 'View controller mappings')" \
        edit "$(community_txt 'Modifier le profil sans lancer de jeu' 'Edit the profile without starting a game')" \
        assign "$(community_txt 'Utiliser ce profil pour un jeu' 'Use this profile for a game')" \
        live "$(community_txt 'Modifier les commandes et tester en jeu' 'Edit controls and test in game')" back "$(i18n back)")" || return 0
      case "$choice" in
        info) amx_profile_info "$path" ;;
        edit) amx_editor "$path" ;;
        assign|live)
          amx_ensure_installed || continue
          if amx_running; then msgbox "$title" "$(community_txt 'Fermez AntiMicroX et le jeu avant l’association.' 'Close AntiMicroX and the game before assigning.')"; continue; fi
          if [ -z "$rom" ]; then
            local preferred
            preferred="$(community_cmd suggest-game antimicrox "$path" 2>/dev/null)" || preferred=""
            selected="$(community_pick_game "$title" "$preferred")" || continue
            rom="${selected%%$'\t'*}"
          fi
          yesno "$title" "$(community_txt "Associer ce profil à $(basename "$rom") ?
Vérifiez ses prérequis et sa Hotkey. Le Pad2Key sera sauvegardé et suspendu." "Assign this profile to $(basename "$rom")?
Check its requirements and Hotkey. Pad2Key will be backed up and suspended.")" || continue
          amx_set_profile "$rom" "$path" || continue
          if [ "$choice" = live ]; then amx_live_start_for "$rom" "$path"; else msgbox "$title" "$(community_txt 'Profil associé.' 'Profile assigned.')"; fi
          return 0 ;;
        *) return 0 ;;
      esac
    else
      choice="$(menu_select "$title" "$(community_txt "Preset téléchargé :
$path

Choisissez le jeu cible. Si nécessaire, l’assistant proposera de configurer ReShade et ses effets avant l’application." "Preset downloaded:
$path

Choose the target game. If necessary, the wizard will offer to configure ReShade and its effects before applying the preset.")" \
        info "$(community_txt 'Voir les effets et les réglages' 'View effects and settings')" \
        apply "$(community_txt 'Appliquer ce preset à un jeu' 'Apply this preset to a game')" back "$(i18n back)")" || return 0
      case "$choice" in
        info) output="$(community_cmd preset-info "$path" 2>&1)"; community_report "$title" "$output"; continue ;;
        apply) : ;;
        *) return 0 ;;
      esac
      if [ -z "$rom" ]; then
        local preferred
        preferred="$(community_cmd suggest-game reshade "$path" 2>/dev/null)" || preferred=""
        selected="$(community_pick_game "$title" "$preferred")" || continue
        rom="${selected%%$'\t'*}"
      fi
      details="$(resh_cmd status "$rom")" || continue
      if [ "$details" = missing ]; then
        local integrated
        integrated="$(resh_cmd external-info "$rom" 2>&1)" || { msgbox "$title" "$integrated"; continue; }
        case "${integrated%%$'\n'*}" in
          external-*)
            community_apply_existing_reshade "$path" "$title" "$rom" "$integrated" && return 0
            continue ;;
          *)
            yesno "$title" "$(community_txt "ReShade n’est pas encore configuré par la Toolbox pour $(basename "$rom"). Un preset contient les réglages des effets, sans leur injecteur ni leurs shaders.

Installer/configurer ReShade et les packs requis maintenant, puis appliquer le preset téléchargé ?" "ReShade is not configured by the Toolbox for $(basename "$rom"). A preset contains effect settings, without the injector or shaders.

Install/configure ReShade and the required packs now, then apply the downloaded preset?")" || continue ;;
        esac
        resh_install_game "$rom" "" "$path" || continue
        details="$(resh_cmd status "$rom")" || continue
        case "$details" in enabled|disabled) : ;; *) msgbox "$title" "$(community_txt 'Configuration ReShade non terminée. Le preset téléchargé est conservé.' 'ReShade configuration is incomplete. The downloaded preset is retained.')"; continue ;; esac
      fi
      yesno "$title" "$(community_txt "Appliquer à $(basename "$rom") et activer ReShade ?
Le preset actuel sera exporté dans les sauvegardes communautaires avant remplacement. Les packs de shaders doivent être installés." "Apply to $(basename "$rom") and enable ReShade?
The current preset will be exported to the community backups before replacement. Shader packs must be installed.")" || continue
      local backup_dir="$WT_HOME/exports/community-backups" backup
      mkdir -p "$backup_dir"
      backup="$(mktemp "$backup_dir/reshade-XXXXXX.ini")" || return 1
      if ! output="$(resh_cmd export "$rom" "$backup" overwrite 2>&1)"; then
        rm -f -- "$backup"; msgbox "$title" "$output"; continue
      fi
      if output="$(resh_cmd preset "$rom" "$path" 2>&1)"; then
        if [ "$details" = disabled ] && ! output="$(resh_cmd enable "$rom" 2>&1)"; then
          msgbox "$title" "$(community_txt "Preset importé mais activation de ReShade impossible.
Sauvegarde : $backup
$output" "Preset imported but ReShade could not be enabled.
Backup: $backup
$output")"; return 1
        fi
        msgbox "$title" "$(community_txt "Preset appliqué.
Sauvegarde : $backup" "Preset applied.
Backup: $backup")"; return 0
      else
        msgbox "$title" "$(community_txt "Échec de l’application. Sauvegarde conservée :
$backup
$output" "Apply failed. Backup retained:
$backup
$output")"
      fi
    fi
  done
}

community_apply_existing_reshade() {
  local path="$1" title="$2" rom="$3" details="$4" folders folder choice output
  local -a items=()
  folders="$(resh_cmd existing-targets "$rom" 2>&1)" || { msgbox "$title" "$folders"; return 1; }
  while IFS= read -r folder; do [ -z "$folder" ] || items+=("$folder" "$folder"); done <<< "$folders"
  [ "${#items[@]}" -gt 0 ] || return 1
  if [ "${#items[@]}" -eq 2 ]; then folder="${items[0]}";
  else folder="$(menu_select "$title" "$(community_txt 'Choisir le dossier de l’injecteur ReShade existant' 'Choose the existing ReShade injector folder')" "${items[@]}" back "$(i18n back)")" || return 1; fi
  [ "$folder" != back ] || return 1
  yesno "$title" "$(community_txt "Appliquer le preset à $(basename "$rom") en conservant son ReShade existant ?

Seuls le preset et son chemin dans ReShade.ini seront gérés par la Toolbox, avec sauvegarde des fichiers remplacés. Les DLL et packs d’effets sont conservés. Les effets requis doivent être présents.
Une archive .wsquashfs reste inchangée ; les réglages sont appliqués dans ses préfixes Wine." "Apply the preset to $(basename "$rom") using its existing ReShade?

The Toolbox will manage only the preset and its path in ReShade.ini, backing up replaced files. DLLs and shader packs are retained. Required effects must already be present.
A .wsquashfs archive is unchanged; settings are applied in its Wine prefixes.")" || return 1
  output="$(resh_cmd existing-import "$rom" "$folder" "$path" 2>&1)" || { msgbox "$title" "$output"; return 1; }
  case "${details%%$'\n'*}" in
    external-disabled)
      if ! resh_cmd external-enable "$rom"; then msgbox "$title" "$(community_txt 'Preset importé ; réactivez ReShade depuis le menu du jeu.' 'Preset imported; re-enable ReShade from the game menu.')"; return 0; fi ;;
  esac
  msgbox "$title" "$(community_txt "Preset appliqué au ReShade existant.
Sauvegardes : $output

Le menu ReShade du jeu permet de restaurer les réglages précédents." "Preset applied to existing ReShade.
Backups: $output

Use the game’s ReShade menu to restore previous settings.")"
}

# Return a validated downloaded INI path for use by the standard installation wizard.
community_choose_reshade_preset() {
  local title="$1" query="" rows id label choice info path
  local -a items=()
  while true; do
    rows="$(community_cmd list reshade --query "$query" 2>&1)" || { msgbox "$title" "$rows"; return 1; }
    items=()
    while IFS=$'\t' read -r id label; do [ -z "$id" ] || items+=("$id" "$label"); done <<< "$rows"
    choice="$(menu_select "$title" "$(community_txt 'Choisir un preset communautaire ReShade' 'Choose a community ReShade preset')" \
      search "$(community_txt 'Rechercher un jeu ou un auteur' 'Search for a game or author')" \
      refresh "$(community_txt 'Mettre à jour la liste' 'Refresh the list')" "${items[@]}" back "$(i18n back)")" || return 1
    case "$choice" in
      back|'') return 1 ;;
      search) query="$(input_text "$title" "$(community_txt 'Jeu, nom du preset ou auteur' 'Game, preset title or author')" "$query")" || return 1; continue ;;
      refresh) info="$(community_cmd refresh --kind reshade 2>&1)" || msgbox "$title" "$info"; continue ;;
    esac
    info="$(community_cmd show reshade "$choice" 2>&1)" || { msgbox "$title" "$info"; continue; }
    yesno "$title" "$info"$'\n\n'"$(community_txt 'Utiliser ce preset pour cette installation ? Les packs d’effets seront identifiés à partir du preset.' 'Use this preset for this installation? Shader packs will be identified from the preset.')" || continue
    path="$(community_cmd fetch reshade "$choice" 2>&1)" || { msgbox "$title" "$path"; continue; }
    printf '%s' "$path"; return 0
  done
}

community_pick_game() {
  local title="$1" preferred="${2:-}" query="" rows path name choice
  local -a games=() items=()
  while true; do
    if ! rows="$(community_cmd games --query "$query" --prefer "$preferred" 2>&1)"; then
      msgbox "$title" "$(community_txt 'Impossible de lire la liste des jeux Windows. Vérifiez leur présence dans /userdata/roms/windows.' 'Unable to read the Windows game list. Check the games under /userdata/roms/windows.')
$rows"; return 1
    fi
    games=(); items=()
    while IFS=$'\t' read -r path name; do
      [ -n "$path" ] || continue
      games+=("$path"$'\t'"$name")
      items+=("${#games[@]}" "$name — ${path##*/}")
    done <<< "$rows"
    choice="$(menu_select "$title" "$(community_txt 'Choisir le jeu Windows (.wine, .pc ou .wsquashfs)' 'Choose a Windows game (.wine, .pc or .wsquashfs)')" \
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

community_pick_reshade_game() {
  local title="$1" mode="${2:-share}" query="" rows path name state choice selected log output
  local -a filter=()
  [ "$mode" != managed ] || filter=(--managed-only)
  local -a games=() items=()
  while true; do
    rows="$(community_cmd reshade-games --query "$query" "${filter[@]}" 2>&1)" || { msgbox "$title" "$rows"; return 1; }
    games=(); items=()
    while IFS=$'\t' read -r path name state; do
      [ -n "$path" ] || continue
      games+=("$path"$'\t'"$name")
      case "$state" in
        enabled) state="$(community_txt 'ReShade Toolbox activé' 'Toolbox ReShade enabled')" ;;
        disabled) state="$(community_txt 'ReShade Toolbox désactivé' 'Toolbox ReShade disabled')" ;;
        external-disabled) state="$(community_txt 'ReShade intégré désactivé' 'Integrated ReShade disabled')" ;;
        *) state="$(community_txt 'ReShade intégré au jeu' 'ReShade bundled with the game')" ;;
      esac
      items+=("${#games[@]}" "$name — $state")
    done <<< "$rows"
    if [ "${#games[@]}" -eq 0 ]; then
      msgbox "$title" "$(community_txt 'Aucun jeu ReShade trouvé pour cette recherche. Lancez la détection ci-dessous ou partagez directement un fichier preset .ini. Vous pouvez appliquer un preset téléchargé à un autre jeu depuis le catalogue communautaire.' 'No ReShade game matches this search. Run detection below or share a preset .ini file directly. You can apply a downloaded preset to another game from the community catalogue.')"
    fi
    choice="$(menu_select "$title" "$(community_txt 'Choisir un jeu configuré avec ReShade' 'Choose a game configured with ReShade')" \
      scan "$(community_txt 'Détecter les ReShade intégrés aux jeux (.wine, .pc, .wsquashfs)' 'Detect bundled ReShade (.wine, .pc, .wsquashfs)')" \
      search "$(community_txt 'Rechercher un jeu ReShade' 'Search for a ReShade game')" "${items[@]}" back "$(i18n back)")" || return 1
    case "$choice" in
      scan)
        log="$(mktemp /tmp/uwt-reshade-discovery.XXXXXX)" || return 1
        # This selector is captured: keep terminal rendering out of its returned path.
        if have_dialog; then wt_clear_tty; dialog --no-shadow --title "$title" --infobox "$(community_txt 'Détection des ReShade intégrés… La première analyse peut prendre du temps.' 'Detecting bundled ReShade… The first scan may take some time.')" 12 96 >&2 || true; fi
        if output="$(community_cmd reshade-scan 2>"$log")"; then
          msgbox "$title" "$(community_txt "Analyse terminée (total / traités / erreurs) : $output" "Scan complete (total / processed / errors): $output")"
        else msgbox "$title" "$(cat "$log")"; fi
        rm -f -- "$log"; continue ;;
      search) query="$(input_text "$title" "$(community_txt 'Nom du jeu ReShade à rechercher' 'ReShade game name to search for')" "$query")" || return 1 ;;
      ''|back|*[!0-9]*) return 1 ;;
      *) [ "$choice" -ge 1 ] && [ "$choice" -le "${#games[@]}" ] || return 1
         printf '%s' "${games[$((choice-1))]}"; return 0 ;;
    esac
  done
}

community_export_reshade() {
  local rom="$1" destination="$2" title="$3" rows id label selected output
  local -a items=()
  rows="$(community_cmd reshade-presets "$rom" 2>&1)" || { msgbox "$title" "$rows"; return 1; }
  while IFS=$'\t' read -r id label; do [ -z "$id" ] || items+=("$id" "$label"); done <<< "$rows"
  if [ "${#items[@]}" -eq 0 ]; then
    msgbox "$title" "$(community_txt 'ReShade a été détecté mais aucun preset .ini n’a été trouvé près de son injecteur. Vous pouvez choisir un fichier preset .ini manuellement.' 'ReShade was detected but no preset .ini was found near its injector. You can choose a preset .ini file manually.')"; return 1
  fi
  if [ "${#items[@]}" -eq 2 ]; then selected="${items[0]}";
  else selected="$(menu_select "$title" "$(community_txt 'Choisir le preset à partager — archive du jeu ou réglages enregistrés' 'Choose a preset to share — game archive or saved settings')" "${items[@]}" back "$(i18n back)")" || return 1; fi
  [ "$selected" != back ] || return 1
  output="$(community_cmd reshade-export "$rom" "$selected" "$destination" 2>&1)" || { msgbox "$title" "$output"; return 1; }
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
  local kind="$1" title="$2" rom="${3:-}" source game="" author name description output selected temporary=""
  if [ "$kind" = antimicrox ]; then
    source="$(amx_profile_file '')" || return 0
  else
    local share_mode=game
    if [ -z "$rom" ]; then
      share_mode="$(menu_select "$title" "$(community_txt 'Choisir le preset ReShade à partager' 'Choose the ReShade preset to share')" \
        game "$(community_txt 'Preset d’un jeu avec ReShade (Toolbox ou intégré)' 'Preset from a game with ReShade (Toolbox or bundled)')" \
        file "$(community_txt 'Choisir un fichier preset .ini' 'Choose a preset .ini file')" back "$(i18n back)")" || return 0
    fi
    case "$share_mode" in
      game)
        if [ -z "$rom" ]; then
          selected="$(community_pick_reshade_game "$title")" || return 0
          rom="${selected%%$'\t'*}"; game="${selected#*$'\t'}"
        fi
        temporary="$(mktemp /tmp/uwt-community-preset.XXXXXX.ini)" || return 1
        if ! community_export_reshade "$rom" "$temporary" "$title"; then
          rm -f -- "$temporary"; return 1
        fi
        source="$temporary" ;;
      file) source="$(resh_preset_file import '')" || return 0 ;;
      *) return 0 ;;
    esac
  fi
  if [ -z "$game" ]; then
    game="$(community_share_game "$kind" "$source" "$title" "$rom")" || { [ -z "$temporary" ] || rm -f -- "$temporary"; return 0; }
  fi
  local name_prompt asset_fr asset_en
  if [ "$kind" = reshade ]; then
    asset_fr="preset ReShade"; asset_en="ReShade preset"
    name_prompt="$(community_txt 'Nom du preset ReShade' 'ReShade preset title')"
  else
    asset_fr="profil AntiMicroX"; asset_en="AntiMicroX profile"
    name_prompt="$(community_txt 'Nom du profil AntiMicroX' 'AntiMicroX profile title')"
  fi
  name="$(input_text "$title" "$name_prompt" "$game")" || { rm -f -- "$temporary"; return 0; }
  author="$(input_text "$title" "$(community_txt 'Votre pseudo public' 'Your public nickname')" '')" || { rm -f -- "$temporary"; return 0; }
  description="$(input_text "$title" "$(community_txt 'Description (commandes ou effets, conseils utiles)' 'Description (controls or effects, useful tips)')" '')" || { rm -f -- "$temporary"; return 0; }
  if ! yesno "$title" "$(community_txt "Partager « $name » pour $game, sous le pseudo $author ?

Le $asset_fr et ces informations seront envoyés au service communautaire pour validation. Ils deviendront publics après acceptation. Aucun compte GitHub nécessaire." "Share '$name' for $game, credited to $author?

The $asset_en and these details will be sent to the community service for review. They become public after approval. No GitHub account is required.")"; then
    rm -f -- "$temporary"; return 0
  fi
  output="$(community_cmd share "$kind" "$source" --game "$game" --title "$name" --author "$author" \
    --description "$description" 2>&1)"
  local status=$?
  [ -z "$temporary" ] || rm -f -- "$temporary"
  if [ "$status" -ne 0 ]; then msgbox "$title" "$output"; return 1; fi
  community_send_package "$title" "${output%%$'\n'*}" "$kind"
}

community_send_package() {
  local title="$1" package="$2" kind="${3:-}" output status
  local -a filter=()
  [ -z "$kind" ] || filter=(--kind "$kind")
  while true; do
    if output="$(community_service_cmd submit "$package" "${filter[@]}" 2>&1)"; then
      status="${output##*$'\n'}"
      case "$status" in
        rejected) output="$(community_txt 'Ce partage a été refusé. Vous pouvez le corriger et proposer un nouveau partage.' 'This submission was rejected. You can make changes and submit it again.')" ;;
        publishing) output="$(community_txt 'Ce partage est validé ; sa publication est en cours. Mettez la liste à jour dans quelques instants.' 'This submission is approved and being published. Refresh the list shortly.')" ;;
        approved) output="$(community_txt 'Ce partage est déjà publié. Mettez à jour la liste pour le retrouver.' 'This submission is already published. Refresh the list to find it.')" ;;
        *) output="$(community_txt 'Partage envoyé ! Un modérateur doit maintenant le valider. Il apparaîtra ensuite dans la liste après actualisation.' 'Submission sent! A moderator will review it. Once approved, it will appear when you refresh the list.')" ;;
      esac
      community_report "$title" "$output"
      return 0
    fi
    msgbox "$title" "$(community_txt "Envoi non confirmé. Le paquet est conservé :
$package

$output" "Submission not confirmed. The package is retained:
$package

$output")"
    yesno "$title" "$(community_txt 'Réessayer le même envoi maintenant ?' 'Retry the same submission now?')" || return 0
  done
}

community_review_pending() {
  local kind="$1" title="$2" rows selected output review checksum choice
  local -a items=()
  while true; do
    if ! rows="$(community_service_cmd pending "$kind" 2>&1)"; then msgbox "$title" "$rows"; return 0; fi
    [ -n "$rows" ] || { msgbox "$title" "$(community_txt 'Aucune proposition en attente.' 'No pending contributions.')"; return 0; }
    items=()
    while IFS=$'\t' read -r selected output; do items+=("$selected" "$output"); done <<< "$rows"
    selected="$(menu_select "$title" "$(community_txt 'Propositions à valider — pseudo non vérifié' 'Contributions for review — unverified nickname')" "${items[@]}" back "$(i18n back)")" || return 0
    [ "$selected" != back ] || return 0
    review="$(community_service_cmd review "$kind" "$selected" 2>&1)" || { msgbox "$title" "$review"; continue; }
    checksum="${review%%$'\n'*}"
    community_report "$title" "${review#*$'\n'}"
    choice="$(menu_select "$title" "$(community_txt 'Décision pour cette contribution' 'Decision for this contribution')" \
      approve "$(community_txt 'Accepter et publier' 'Approve and publish')" \
      reject "$(community_txt 'Refuser' 'Reject')" back "$(i18n back)")" || continue
    case "$choice" in approve|reject) : ;; *) continue ;; esac
    if [ "$choice" = approve ]; then
      yesno "$title" "$(community_txt 'Publier ce partage dans la liste communautaire ? Il deviendra accessible à tous les joueurs.' 'Publish this submission in the community catalogue? It will become available to all players.')" || continue
    else yesno "$title" "$(community_txt 'Refuser ce partage ? Il ne sera pas publié.' 'Reject this submission? It will not be published.')" || continue; fi
    if output="$(community_service_cmd "$choice" "$kind" "$selected" "$checksum" 2>&1)"; then
      msgbox "$title" "$(community_txt "Décision enregistrée : $output" "Decision saved: $output")"
    else msgbox "$title" "$output"; fi
  done
}

community_remove_published() {
  local kind="$1" title="$2" rows selected label output review checksum
  local -a items=()
  while true; do
    rows="$(community_service_cmd published "$kind" 2>&1)" || { msgbox "$title" "$rows"; return 0; }
    [ -n "$rows" ] || { msgbox "$title" "$(community_txt 'Aucun partage publié pour cet outil.' 'No published submissions for this tool.')"; return 0; }
    items=()
    while IFS=$'\t' read -r selected label; do items+=("$selected" "$label"); done <<< "$rows"
    selected="$(menu_select "$title" "$(community_txt 'Choisir le partage à retirer de la liste communautaire' 'Choose a submission to remove from the community catalogue')" "${items[@]}" back "$(i18n back)")" || return 0
    case "$selected" in ''|back) return 0 ;; esac
    review="$(community_service_cmd published-review "$kind" "$selected" 2>&1)" || { msgbox "$title" "$review"; continue; }
    checksum="${review%%$'\n'*}"
    if ! yesno_default_no "$title" "${review#*$'\n'}"$'\n\n'"$(community_txt 'Retirer ce partage du catalogue ?

Son fichier et sa fiche seront supprimés du dépôt communautaire. Les profils déjà installés chez les joueurs restent conservés.' 'Remove this submission from the catalogue?

Its file and catalogue entry will be deleted from the community repository. Profiles already installed by players are retained.')"; then continue; fi
    if output="$(community_service_cmd remove-published "$kind" "$selected" "$checksum" 2>&1)"; then
      # Refresh this machine immediately; other users see removal on their next refresh.
      if community_cmd refresh --kind "$kind" >/dev/null 2>&1; then
        msgbox "$title" "$(community_txt 'Partage retiré. La liste communautaire est à jour.' 'Submission removed. The community list is up to date.')"
      else msgbox "$title" "$(community_txt 'Partage retiré. Mettez la liste à jour quand la connexion sera rétablie.' 'Submission removed. Refresh the list when the connection is restored.')"; fi
    else msgbox "$title" "$(community_txt 'Suppression non confirmée. Actualisez la liste avant de réessayer.' 'Removal not confirmed. Refresh the list before retrying.')
$output"; fi
  done
}

# Subshell confines secrets and the EXIT trap; do not enable tracing here.
community_validate() (
  set +x
  local kind="$1" title="$2" output choice
  output="$(community_service_cmd connect 2>&1)"
  local result=$?
  wt_clear_tty
  [ "$result" -eq 0 ] || { msgbox "$title" "$output"; return 0; }
  trap 'community_service_cmd logout >/dev/null 2>&1 || true' EXIT
  while true; do
    choice="$(menu_select "$title" "$(community_txt 'Gestion des partages communautaires' 'Manage community submissions')" \
      pending "$(community_txt 'Examiner les partages en attente' 'Review pending submissions')" \
      published "$(community_txt 'Retirer un partage déjà publié' 'Remove a published submission')" back "$(i18n back)")" || return 0
    case "$choice" in
      pending) community_review_pending "$kind" "$title" ;;
      published) community_remove_published "$kind" "$title" ;;
      *) return 0 ;;
    esac
  done
)

community_menu() {
  local kind="$1" rom="${2:-}" title choice query="" rows id label selected details path output share_label empty_label count_label search_prompt
  local -a items=()
  local browse_label intro
  if [ "$kind" = antimicrox ]; then title="AntiMicroX — $(community_txt 'Profils communautaires' 'Community profiles')"; else title="ReShade — $(community_txt 'Presets communautaires' 'Community presets')"; fi
  if [ "$kind" = reshade ]; then
    share_label="$(community_txt 'Partager mon preset ReShade' 'Share my ReShade preset')"
    browse_label="$(community_txt 'Voir les presets disponibles' 'Browse available presets')"
    intro="$(community_txt 'Un preset contient les réglages visuels de ReShade. Téléchargez ceux d’autres joueurs ou partagez les vôtres. Un modérateur valide les partages avant publication.' 'A preset contains ReShade visual settings. Download presets from other players or share yours. A moderator reviews submissions before publication.')"
    empty_label="$(community_txt 'Aucun preset ReShade trouvé. Actualisez le catalogue ou partagez votre preset.' 'No ReShade preset found. Refresh the catalogue or share your preset.')"
    count_label="$(community_txt 'presets ReShade' 'ReShade presets')"
    search_prompt="$(community_txt 'Jeu, nom du preset ReShade ou auteur' 'Game, ReShade preset title or author')"
  else
    share_label="$(community_txt 'Partager mon profil de manette' 'Share my controller profile')"
    browse_label="$(community_txt 'Voir les profils disponibles' 'Browse available profiles')"
    intro="$(community_txt 'Un profil contient les commandes de la manette pour un jeu. Téléchargez ceux d’autres joueurs ou partagez les vôtres. Un modérateur valide les partages avant publication.' 'A profile contains controller mappings for a game. Download profiles from other players or share yours. A moderator reviews submissions before publication.')"
    empty_label="$(community_txt 'Aucun profil AntiMicroX trouvé. Actualisez le catalogue ou partagez votre profil.' 'No AntiMicroX profile found. Refresh the catalogue or share your profile.')"
    count_label="$(community_txt 'profils AntiMicroX' 'AntiMicroX profiles')"
    search_prompt="$(community_txt 'Jeu, nom du profil AntiMicroX ou auteur' 'Game, AntiMicroX profile title or author')"
  fi
  while true; do
    choice="$(menu_select "$title" "$intro" \
      browse "$browse_label" \
      search "$(community_txt 'Rechercher un jeu ou un auteur' 'Search for a game or author')" \
      refresh "$(community_txt 'Mettre à jour la liste' 'Refresh the list')" \
      share "$share_label" \
      validate "$(community_txt 'Valider les partages (modérateurs)' 'Review submissions (moderators)')" \
      forget "$(community_txt 'Retirer l’accès modérateur de ce PC' 'Remove moderator access from this PC')" back "$(i18n back)")" || return 0
    case "$choice" in
      refresh)
        if output="$(community_cmd refresh --kind "$kind" 2>&1)"; then msgbox "$title" "$(community_txt "Catalogue actualisé : $output $count_label." "Catalogue refreshed: $output $count_label.")"; else msgbox "$title" "$(community_txt 'Actualisation impossible ; le cache précédent reste disponible.' 'Refresh failed; the previous cache remains available.')
$output"; fi
        continue ;;
      share) community_share "$kind" "$title" "$rom"; continue ;;
      validate) community_validate "$kind" "$title"; continue ;;
      forget)
        if yesno "$title" "$(community_txt 'Révoquer l’autorisation mémorisée et déconnecter ce Batocera ?' 'Revoke the remembered authorization and sign this Batocera out?')"; then
          if output="$(community_service_cmd forget 2>&1)"; then msgbox "$title" "$(community_txt 'Accès local oublié et autorisation révoquée.' 'Local access forgotten and authorization revoked.')";
          else msgbox "$title" "$(community_txt 'Accès local oublié. Si la révocation distante a échoué, révoquez aussi l’appareil depuis la page d’appairage.' 'Local access forgotten. If remote revocation failed, also revoke the device on the pairing page.')
$output"; fi
        fi
        continue ;;
      search) query="$(input_text "$title" "$search_prompt" '')" || continue ;;
      browse) query="" ;;
      *) return 0 ;;
    esac
    if ! rows="$(community_cmd list "$kind" --query "$query" 2>&1)"; then msgbox "$title" "$rows"; continue; fi
    if [ -z "$rows" ]; then msgbox "$title" "$empty_label"; continue; fi
    items=()
    while IFS=$'\t' read -r id label; do items+=("$id" "$label"); done <<< "$rows"
    selected="$(menu_select "$title" "$(community_txt 'Choisir un profil ou un preset' 'Choose a profile or preset')" "${items[@]}" back "$(i18n back)")" || continue
    [ "$selected" != back ] || continue
    details="$(community_cmd show "$kind" "$selected" 2>&1)" || { msgbox "$title" "$details"; continue; }
    path="$(community_cmd local "$kind" "$selected" 2>/dev/null)" || path=""
    if [ -n "$path" ]; then
      yesno "$title" "$details"$'\n\n'"$(community_txt 'Ce fichier est déjà téléchargé. Utiliser votre copie locale ?' 'This file is already downloaded. Use your local copy?')" || continue
      community_import_actions "$kind" "$path" "$title" "$rom"
      continue
    fi
    yesno "$title" "$details"$'\n\n'"$(community_txt 'Télécharger ce fichier ? Vous pourrez ensuite l’utiliser pour un jeu.' 'Download this file? You can then use it for a game.')" || continue
    if path="$(community_cmd fetch "$kind" "$selected" 2>&1)"; then community_import_actions "$kind" "$path" "$title" "$rom"; else msgbox "$title" "$path"; fi
  done
}
