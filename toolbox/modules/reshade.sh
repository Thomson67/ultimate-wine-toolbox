#!/bin/bash
RESH_HELPER="$WT_ROOT/helpers/reshade_manager.py"
RESH_BACKEND="$WT_HOME/reshade/backend/reshadelinux.sh"

resh_cmd() {
    local -a flags=()
    if ! grep -Fq 'WINE_BOTTLE_DIR}/${WINE_VERSION}/${ROMGAMENAME}.wine' /usr/bin/batocera-wine 2>/dev/null; then
        flags+=(--legacy)
    fi
    python3 "$RESH_HELPER" --home "$WT_HOME" "${flags[@]}" "$@"
}

resh_backend_ready() {
    local tool missing=""
    for tool in curl python3 sha256sum tar flock; do
        command -v "$tool" >/dev/null 2>&1 || missing+="$tool "
    done
    if [ -n "$missing" ]; then
        msgbox "$(i18n resh_title)" "$(i18n resh_missing_tools "$missing")"
        return 1
    fi
    msgbox "$(i18n resh_title)" "$(i18n resh_backend_fetch)" || return 1
    WT_HOME="$WT_HOME" bash "$WT_ROOT/helpers/install-reshade-backend.sh" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
        return 1
    }
}

resh_prepare_tools() {
    local shim="$WT_HOME/reshade/bin"
    mkdir -p "$shim"
    # Batocera does not ship Git/libmagic on every image. These private
    # adapters cover only the calls of our pinned upstream backend.
    local compatibility_tool
    for compatibility_tool in git file; do
        if ! command -v "$compatibility_tool" >/dev/null 2>&1; then
            printf '#!/bin/bash\nexec python3 %q %q "$@"\n' \
                "$WT_ROOT/helpers/reshade_compat.py" "$compatibility_tool" > "$shim/$compatibility_tool"
            chmod +x "$shim/$compatibility_tool"
        else
            printf '#!/bin/bash\nexec %q "$@"\n' "$(command -v "$compatibility_tool")" > "$shim/$compatibility_tool"
            chmod +x "$shim/$compatibility_tool"
        fi
    done
    # Official ReShade installers contain a ZIP payload. Always use Python:
    # Batocera may provide a 7z executable with a missing archive plugin.
    printf '#!/bin/bash\nexec python3 %q "$@"\n' "$WT_ROOT/helpers/reshade_extract.py" > "$shim/7z"
    chmod +x "$shim/7z"
}

resh_import_ini() {
    local rom="$1" source="$2" report output hash packs unknown file options selected job log backend_packs
    local -a choices=() selected_packs=()
    if ! report="$(resh_cmd dependency-check "$rom" "$source" 2>&1)"; then msgbox "$(i18n resh_title)" "$report"; return 1; fi
    hash="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["sha256"])' "$report")" || return 1
    packs="$(python3 -c 'import json,sys; print(",".join(json.loads(sys.argv[1])["packs"]))' "$report")" || return 1
    unknown="$(python3 -c 'import json,sys; print(", ".join(json.loads(sys.argv[1])["unknown"]))' "$report")" || return 1
    while IFS=$'\t' read -r file options; do
        [ -n "$file" ] || continue
        choices=()
        IFS=',' read -r -a selected_packs <<< "$options"
        for selected in "${selected_packs[@]}"; do choices+=("$selected" "$selected"); done
        selected="$(menu_select "$(i18n resh_title)" "$(community_txt 'Plusieurs packs proposent cet effet manquant. Choisir sa source :' 'Several packs provide this missing effect. Choose its source:') $file" "${choices[@]}" back "$(i18n back)")" || return 1
        [[ ",$options," = *",$selected,"* ]] || return 1
        packs="${packs:+$packs,}$selected"
    done < <(python3 -c 'import json,sys; print("\n".join(n+"\t"+",".join(v) for n,v in json.loads(sys.argv[1])["ambiguous"].items()))' "$report")
    if [ -n "$unknown" ]; then
        yesno_default_no "$(i18n resh_title)" "$(community_txt 'Ces effets manquants ne sont pas reconnus et ne peuvent pas être installés automatiquement :' 'These missing effects are unknown and cannot be installed automatically:')
$unknown

$(community_txt 'Continuer malgré ces dépendances non résolues ? Les effets concernés pourront rester désactivés ou en erreur.' 'Continue despite these unresolved dependencies? These effects may remain disabled or report errors.')" || return 1
    fi
    if [ -n "$packs" ]; then
        yesno_default_no "$(i18n resh_title)" "$(community_txt 'Installer les packs de shaders manquants avant d’importer le preset ?' 'Install the missing shader packs before importing the preset?')
$packs

$(community_txt 'Les packs complets et leurs dépendances seront téléchargés. La version ReShade et les presets existants seront conservés.' 'Complete packs and their dependencies will be downloaded. The ReShade version and existing presets will be retained.')" || return 1
        resh_backend_ready || return 1
        resh_prepare_tools || return 1
        job="$(resh_cmd dependency-prepare "$rom" "$source" "$packs" "$hash" 2>&1)" || { msgbox "$(i18n resh_title)" "$job"; return 1; }
        log="${WT_LOG_DIR:-/userdata/system/logs/ultimate-wine-toolbox}/reshade-shaders-$(date +%Y%m%d-%H%M%S)-$$.log"
        mkdir -p "${log%/*}"
        backend_packs="$(resh_cmd backend-packs "$packs")" || return 1
        [ "$backend_packs" != none ] || backend_packs=reshade-shaders
        msgbox "$(i18n resh_title)" "$(i18n resh_download_wait "$log")" || return 1
        if ! (
            exec 9> "$WT_HOME/reshade/runtime.lock"
            flock 9
            PATH="$WT_HOME/reshade/bin:$PATH" bash "$WT_ROOT/helpers/reshade_shader_download.sh" \
                "$WT_HOME/reshade/backend" "$job/cache" "$backend_packs"
        ) >> "$log" 2>&1; then
            msgbox "$(i18n resh_title)" "$(i18n resh_failed "$log")"; return 1
        fi
        if ! output="$(resh_cmd dependency-finish "$rom" "$job" 2>&1)"; then
            printf '%s\n' "$output" >> "$log"
            msgbox "$(i18n resh_title)" "$output"; return 1
        fi
    fi
    if ! output="$(resh_cmd preset "$rom" "$source" "$hash" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; return 1; fi
}

resh_model_packs() {
    case "$1" in
        standard) printf '%s' 'reshade-shaders,sweetfx-shaders' ;;
        retro) printf '%s' 'reshade-shaders,sweetfx-shaders,reshade-shaders-legacy,crt-royale,rsretroarch-shaders,scaling-shaders,guestrr-shaders,uwt-retro-extras' ;;
        thomson) printf '%s' 'reshade-shaders,sweetfx-shaders,reshade-shaders-legacy,fubax-shaders,quintfx,prod80-shaders,astrayfx-shaders,immerse-shaders' ;;
        manual) printf '' ;;
    esac
}

resh_preset_file() {
    local mode="$1" rom="$2" name="${2##*/}" chosen
    name="${name%.*}-ReShade.ini"
    if command -v yad >/dev/null 2>&1; then
        local -a flags=()
        [ "$mode" != export ] || flags+=(--save --confirm-overwrite)
        DISPLAY="${DISPLAY:-:0}" LANGUAGE="$WT_LANGUAGE" yad --file "${flags[@]}" \
            --filename="/userdata/$([ "$mode" != export ] || printf '%s' "$name")" \
            --title="$(i18n "resh_${mode}_title")" --file-filter='ReShade presets | *.ini *.INI' \
            --file-filter="$(i18n resh_all_files) | *" --width=1000 --height=700
    else
        chosen="$(input_text "$(i18n "resh_${mode}_title")" "$(i18n resh_preset_prompt)" "/userdata/$([ "$mode" != export ] || printf '%s' "$name")")" || return 1
        if [ "$mode" = export ] && [ -e "$chosen" ]; then
            yesno_default_no "$(i18n resh_title)" "$(i18n resh_export_overwrite "$chosen")" || return 1
        fi
        printf '%s' "$chosen"
    fi
}

resh_diagnostic() {
    local rom="$1" exe="${2:-}"
    yesno_default_no "$(i18n resh_title)" "$(i18n resh_diag_confirm)" || return 1
    python3 "$WT_ROOT/helpers/reshade_diagnostic.py" --home "$WT_HOME" --exe "$exe" request "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
        msgbox "$(i18n resh_title)" "$(i18n resh_diag_pending)"; return 1;
    }
    return 0
}

resh_resume_diagnostic() {
    local rom exe detected candidates evidence result community_preset
    rom="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["rom"])' "$WT_HOME/state/reshade-diagnostic.json" 2>/dev/null)" || return
    if [ "$(cat "$WT_HOME/state/launch-game.request" 2>/dev/null)" = "$rom" ]; then
        rm -f -- "$WT_HOME/state/launch-game.request"
    fi
    if python3 "$WT_ROOT/helpers/reshade_diagnostic.py" --home "$WT_HOME" active "$rom"; then
        msgbox "$(i18n resh_title)" "$(i18n resh_diag_active)"
        return
    fi
    exe="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("installation_exe", ""))' "$WT_HOME/state/reshade-diagnostic.json" 2>/dev/null)" || exe=""
    community_preset="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("community_preset", ""))' "$WT_HOME/state/reshade-diagnostic.json" 2>/dev/null)" || community_preset=""
    rm -f -- "$WT_HOME/state/reshade-diagnostic.json" "$WT_HOME/state/reshade-diagnostic.stop"
    detected="$(python3 "$WT_ROOT/helpers/reshade_diagnostic.py" --home "$WT_HOME" result "$rom")"
    candidates="${detected%%$'\t'*}"; evidence="${detected##*$'\t'}"
    result="$(cat "$WT_HOME/state/wsq-launch-result" 2>/dev/null)"
    msgbox "$(i18n resh_title)" "$(i18n resh_diag_result "${candidates:-?}" "${evidence:-?}" "${result:-?}")"
    if [ -n "$exe" ] && resh_install_game "$rom" "$exe" "$community_preset"; then
        if [ -n "$community_preset" ] && [ -f "$community_preset" ]; then
            community_import_actions reshade "$community_preset" "ReShade — $(community_txt 'Presets communautaires' 'Community presets')" "$rom"
        fi
    fi
    resh_game_menu "$rom"
}

resh_api_select() {
    local rom="$1" exe="$2" detected candidates kind evidence prompt choice api label query titles title idx selected
    local -a rows=() names=()
    detected="$(resh_cmd api "$rom" "$exe" 2>> "${WT_SESSION_LOG:-/dev/null}")" || detected=""
    IFS=$'\t' read -r candidates kind evidence <<< "$detected"
    # read treats tabs as whitespace; retain empty candidate fields explicitly.
    candidates="${detected%%$'\t'*}"
    local observed
    observed="$(python3 "$WT_ROOT/helpers/reshade_diagnostic.py" --home "$WT_HOME" result "$rom" 2>> "${WT_SESSION_LOG:-/dev/null}")"
    if [ -n "${observed%%$'\t'*}" ]; then
        candidates="${observed%%$'\t'*}"; evidence="${observed##*$'\t'}"
    fi
    prompt="$(i18n resh_api_prompt)\n\n$(i18n resh_api_detection "${evidence:-?}")"
    while true; do
        rows=()
        for api in d3d9 dxgi opengl32 vulkan; do
            case "$api" in d3d9) label='DirectX 9 (d3d9)' ;; dxgi) label='DirectX 10 / 11 / 12 (dxgi)' ;; opengl32) label='OpenGL (opengl32)' ;; vulkan) label="$(i18n resh_vulkan_label)" ;; esac
            if [[ ",$candidates," == *",$api,"* ]]; then
                rows+=("$api" "$label — $(i18n resh_api_suggested)")
            fi
        done
        for api in dxgi d3d9 opengl32 vulkan; do
            [[ ",$candidates," != *",$api,"* ]] || continue
            case "$api" in d3d9) label='DirectX 9 (d3d9)' ;; dxgi) label='DirectX 10 / 11 / 12 (dxgi)' ;; opengl32) label='OpenGL (opengl32)' ;; vulkan) label="$(i18n resh_vulkan_label)" ;; esac
            rows+=("$api" "$label")
        done
        if [[ ",$candidates," == *',legacy,'* ]]; then
            prompt+="\n$(i18n resh_api_unsupported)"
        fi
        choice="$(menu_select "$(i18n resh_title)" "$prompt" "${rows[@]}" diagnostic "$(i18n resh_diag_title)" wiki "$(i18n resh_api_wiki)")" || return 1
        case "$choice" in
            dxgi|d3d9|opengl32) printf '%s' "$choice"; return 0 ;;
            vulkan)
                msgbox "$(i18n resh_title)" "$(i18n resh_vulkan_help)" >&2
                printf '%s' vulkan; return 0 ;;
            diagnostic) resh_diagnostic "$rom" "$exe" && return 2; continue ;;
            wiki)
                query="$(resh_cmd wiki-title "$rom")"
                query="$(input_text "$(i18n resh_api_wiki)" "$(i18n resh_wiki_query)" "$query")" || continue
                titles="$(resh_cmd wiki-search "$query" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_wiki_unavailable)"; continue;
                }
                names=(); rows=(); idx=0
                while IFS= read -r title; do
                    [ -n "$title" ] || continue
                    names+=("$title"); idx=$((idx+1)); if [ "$idx" -eq 1 ]; then rows+=("$idx" "$title — $(i18n resh_wiki_first)"); else rows+=("$idx" "$title"); fi
                done <<< "$titles"
                [ "$idx" -gt 0 ] || { msgbox "$(i18n resh_title)" "$(i18n resh_no_match)"; continue; }
                selected="$(menu_select "$(i18n resh_api_wiki)" "$(i18n resh_wiki_choose)" "${rows[@]}")" || continue
                case "$selected" in ''|*[!0-9]*) continue ;; esac
                [ "$selected" -ge 1 ] && [ "$selected" -le "$idx" ] || continue
                title="${names[$((selected-1))]}"
                detected="$(resh_cmd wiki-page "$title" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_wiki_unavailable)"; continue;
                }
                candidates="${detected%%$'\t'*}"; evidence="${detected#*$'\t'}"
                prompt="$(i18n resh_api_prompt)\n\nPCGamingWiki : $title\n${evidence:-?}\n$(i18n resh_wiki_hint)"
                ;;
            *) return 1 ;;
        esac
    done
}

resh_version_select() {
    local rom="$1" api="${2:-dxgi}" helper="$WT_ROOT/helpers/reshade_versions.py" listing version current no_banner choice index identity variant provider label notes note
    local -a versions options identities
    while true; do
        listing="$(python3 "$helper" --home "$WT_HOME" versions --rom "$rom" --api "$api" 2>>"${WT_SESSION_LOG:-/dev/null}")" || return 1
        versions=(); options=()
        while IFS=$'\t' read -r version current no_banner; do
            [ -n "$version" ] || continue
            versions+=("$version"); label="$version"
            [ "$no_banner" != 1 ] || label+=" — $(i18n resh_no_banner_available)"
            [ "$current" != 1 ] || label+=" — $(i18n resh_release_installed)"
            options+=("${#versions[@]}" "$label")
        done <<<"$listing"
        [ "${#versions[@]}" -gt 0 ] || return 1
        choice="$(menu_select "$(i18n resh_title)" "$(i18n resh_versions_prompt)" \
            "${options[@]}" back "$(i18n back)")" || return 1
        [ "$choice" != back ] || return 1
        version=""
        for index in "${!versions[@]}"; do
            [ "$choice" != "$((index+1))" ] || { version="${versions[$index]}"; break; }
        done
        [ -n "$version" ] || return 1
        listing="$(python3 "$helper" --home "$WT_HOME" variants "$version" --rom "$rom" 2>>"${WT_SESSION_LOG:-/dev/null}")" || return 1
        identities=(); options=()
        while IFS=$'\t' read -r identity variant provider current notes; do
            [ -n "$identity" ] || continue
            case "$variant" in
                standard) label="$(i18n resh_variant_standard)" ;;
                standard-addons) label="$(i18n resh_variant_addons)" ;;
                no-startup-banner) label="$(i18n resh_variant_no_banner) — ${provider%%/*}" ;;
                *) return 1 ;;
            esac
            for note in ${notes//,/ }; do
                case "$note" in
                    full-addons) label+=" — $(i18n resh_full_addons)" ;;
                    binary-archive) label+=" — $(i18n resh_binary_archive)" ;;
                    older-gui) label+=" — $(i18n resh_older_gui)" ;;
                esac
            done
            [ "$current" != 1 ] || label+=" — $(i18n resh_release_installed)"
            identities+=("$identity"); options+=("${#identities[@]}" "$label")
        done <<<"$listing"
        if [ "${#identities[@]}" -eq 1 ]; then printf '%s' "${identities[0]}"; return; fi
        [ "${#identities[@]}" -gt 0 ] || return 1
        choice="$(menu_select "$(i18n resh_title) — $version" "$(i18n resh_variants_prompt)" \
            "${options[@]}" back "$(i18n back)")" || return 1
        [ "$choice" != back ] || continue
        for index in "${!identities[@]}"; do
            if [ "$choice" = "$((index+1))" ]; then printf '%s' "${identities[$index]}"; return; fi
        done
        return 1
    done
}

resh_install_game() {
    local rom="$1" exe selected dll backend_dll version packs backend_packs state workspace name label model defaults current
    local current_pack
    current_pack="$(resh_cmd pack-status "$rom" 2>>"${WT_SESSION_LOG:-/dev/null}")" || current_pack=""
    if [ -n "$current_pack" ] && [ "$current_pack" != '{}' ]; then
        msgbox "$(i18n resh_title)" "$(community_txt 'Retirez le pack local avant de changer la version, les shaders ou l’exécutable ReShade.' 'Remove the local bundle before changing the ReShade version, shaders or executable.')"
        return 1
    fi
    local resume_exe="${2:-}" community_preset="${3:-}" resumed=0 index apply_community=0
    local local_pack="" local_pack_preset="" pack_selection pack_error
    local -a exes=() items=() shaders=()
    local listing
    listing="$(resh_cmd exes "$rom" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
        return 1
    }
    while IFS= read -r exe; do
        [ -n "$exe" ] || continue
        exes+=("$exe")
        items+=("${#exes[@]}" "$exe")
    done <<< "$listing"
    [ "${#exes[@]}" -gt 0 ] || { msgbox "$(i18n resh_title)" "$(i18n resh_no_exe)"; return 1; }
    for index in "${!exes[@]}"; do
        if [ "${exes[$index]}" = "$resume_exe" ]; then
            exe="$resume_exe"; resumed=1; break
        fi
    done
    if [ "$resumed" -eq 0 ] && [ "${#exes[@]}" -eq 1 ]; then
        exe="${exes[0]}"
    elif [ "$resumed" -eq 0 ]; then
        selected="$(WT_MENU_LIST=1 menu_select "$(i18n resh_title)" "$(i18n resh_exe_prompt)" "${items[@]}")" || return 1
        case "$selected" in ''|*[!0-9]*) return 1 ;; esac
        [ "$selected" -ge 1 ] && [ "$selected" -le "${#exes[@]}" ] || return 1
        exe="${exes[$((selected-1))]}"
    fi
    dll="$(resh_api_select "$rom" "$exe")" || {
        if [ -f "$WT_HOME/state/reshade-diagnostic.json" ]; then
            if [ -n "$community_preset" ]; then
                python3 - "$WT_HOME/state/reshade-diagnostic.json" "$community_preset" <<'PY_PENDING'
import json, os, sys, tempfile
from pathlib import Path
path = Path(sys.argv[1]); data = json.loads(path.read_text())
data['community_preset'] = sys.argv[2]
fd, name = tempfile.mkstemp(dir=path.parent, prefix='.reshade-pending-')
try:
    with os.fdopen(fd, 'w') as stream: json.dump(data, stream, ensure_ascii=False)
    os.replace(name, path)
finally:
    if os.path.exists(name): os.unlink(name)
PY_PENDING
            fi
            exit 0
        fi
        return 1
    }
    case "$dll" in dxgi|d3d9|opengl32|vulkan) ;; *) return 1 ;; esac
    backend_dll="$dll"
    [ "$dll" != vulkan ] || backend_dll=dxgi
    local release_id variant backend_version selection_info version_label
    release_id="$(resh_version_select "$rom" "$dll")" || return 1
    selection_info="$(python3 "$WT_ROOT/helpers/reshade_versions.py" info "$release_id" 2>>"${WT_SESSION_LOG:-/dev/null}")" || return 1
    IFS=$'\t' read -r version variant backend_version <<<"$selection_info"
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && [[ "$backend_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
        msgbox "$(i18n resh_title)" "$(i18n resh_version_invalid)"
        return 1
    }
    case "$variant" in
        standard) version_label="$version — $(i18n resh_variant_standard)" ;;
        standard-addons) version_label="$version — $(i18n resh_variant_addons)" ;;
        no-startup-banner) version_label="$version — $(i18n resh_variant_no_banner)" ;;
        *) return 1 ;;
    esac
    resh_backend_ready || return 1
    if [ -n "$community_preset" ]; then
        model=community-preset; defaults=""
    else
        items=(standard "$(i18n resh_model_standard)" retro "$(i18n resh_model_retro)" thomson "$(i18n resh_model_thomson)" manual "$(i18n resh_model_manual)")
        current="$(resh_cmd details "$rom")"
        [ -z "$current" ] || items+=(current "$(i18n resh_model_current)")
        items+=(community "$(community_txt 'Rechercher un preset dans la base communautaire' 'Find a preset in the community catalogue')")
        items+=(local-pack "$(community_txt 'Installer un pack ReShade local (ZIP ou dossier, add-ons et shaders)' 'Install a local ReShade bundle (ZIP or directory, add-ons and shaders)')")
        model="$(WT_MENU_LIST=1 menu_select "$(i18n resh_title)" "$(i18n resh_model_prompt)" "${items[@]}")" || return 1
        case "$model" in
            standard|retro|thomson|manual) defaults="$(resh_model_packs "$model")" ;;
            community) community_preset="$(community_choose_reshade_preset "$(i18n resh_title)")" || return 1; model=community-preset; defaults=""; apply_community=1 ;;
            local-pack)
                pack_selection="$(resh_pack_menu "$rom" select)" || return 1
                local_pack="${pack_selection%%$'\n'*}"
                local_pack_preset="${pack_selection#*$'\n'}"
                if ! pack_error="$(resh_cmd pack-check "$rom" "$local_pack" "$local_pack_preset" "$release_id" "$exe" 2>&1)"; then
                    msgbox "$(i18n resh_title)" "$pack_error"
                    return 1
                fi
                defaults=none ;;
            current) defaults="${current##*$'\t'}" ;;
            *) return 1 ;;
        esac
    fi
    if [ "$model" = community-preset ]; then
        local analysis review
        analysis="$(community_cmd preset-packs "$community_preset" 2>&1)" || { msgbox "$(i18n resh_title)" "$analysis"; return 1; }
        defaults="${analysis%%$'\n'*}"; analysis="${analysis#*$'\n'}"
        review="${analysis%%$'\n'*}"; analysis="${analysis#*$'\n'}"
        msgbox "$(i18n resh_title)" "$analysis" || return 1
        if [ "$review" = review ]; then model=manual; fi
    fi
    if [ "$model" = manual ]; then
        items=()
        while IFS=$'\t' read -r name label; do
            name="${name#  }"
            [[ "$name" =~ ^[a-z0-9_-]+$ ]] && [ -n "$label" ] || continue
            state=off
            [[ ",$defaults," != *",$name,"* ]] || state=on
            items+=("$name" "$label" "$state")
        done < <(MAIN_PATH="$WT_HOME/reshade/runtime" UI_BACKEND=cli NO_COLOR=1 \
            bash "$RESH_BACKEND" --cli --list-shader-repos 2>> "${WT_SESSION_LOG:-/dev/null}")
        [ "${#items[@]}" -gt 0 ] || return 1
        selected="$(checklist_select "$(i18n resh_title)" "$(i18n resh_shaders_prompt)" "${items[@]}")" || return 1
        while IFS= read -r name; do
            [ -z "$name" ] || shaders+=("$name")
        done <<< "$selected"
        packs="$(IFS=','; printf '%s' "${shaders[*]}")"
        packs="${packs:-none}"
    else
        packs="$defaults"
    fi
    backend_packs="$(resh_cmd backend-packs "$packs")" || return 1
    yesno_default_no "$(i18n resh_title)" "$(i18n resh_install_confirm "$(basename "$rom")" "$exe" "$dll" "$version_label" "$packs")" || return 1
    # Reconfiguration starts from restored originals; the saved preset survives.
    state="$(resh_cmd status "$rom")"
    if [ "$state" != missing ]; then
        resh_cmd disable "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
            msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
            return 1
        }
    fi
    # Restore any integrated-injector masks before a managed installation takes over.
    # This runs only after the final installation confirmation, never on cancellation.
    if [ "$state" = missing ]; then
        resh_cmd external-release "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
            msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
            return 1
        }
    fi
    workspace="$(resh_cmd prepare "$rom" "$exe" "$dll" "$version" "$packs" "$release_id" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
        return 1
    }
    local log="${WT_LOG_DIR:-/userdata/system/logs/ultimate-wine-toolbox}/reshade-install-$(date +%Y%m%d-%H%M%S)-$$.log"
    mkdir -p "$(dirname "$log")"
    ls -1t "$(dirname "$log")"/reshade-install-*.log 2>/dev/null | tail -n +20 | while IFS= read -r oldlog; do
        [ -z "$oldlog" ] || rm -f -- "$oldlog"
    done
    msgbox "$(i18n resh_title)" "$(i18n resh_download_wait "$log")" || return 1
    local shim="$WT_HOME/reshade/bin"
    resh_prepare_tools || return 1
    (
        exec 9> "$WT_HOME/reshade/runtime.lock"
        flock 9
        MAIN_PATH="$WT_HOME/reshade/runtime" WINEPREFIX="" UI_BACKEND=cli \
            RESHADE_VERSION="$backend_version" RESHADE_ADDON_SUPPORT=0 NO_COLOR=1 PROGRESS_UI=0 \
            RESHADE_ALLOW_UNPINNED=0 RESHADE_SETUP_SHA256="" \
            PATH="$shim:$PATH" bash "$RESH_BACKEND" --no-input --game-path="$workspace" \
            --dll-override="$backend_dll" --shader-repos="$backend_packs"
    ) >> "$log" 2>&1 && resh_cmd finish "$rom" >> "$log" 2>&1 || {
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "$log")"
        return 1
    }
    if [ -n "$local_pack" ]; then
        if ! pack_error="$(resh_cmd pack-import "$rom" "$local_pack" "$local_pack_preset" 2>&1)"; then
            printf '%s\n' "$pack_error" >> "$log"
            msgbox "$(i18n resh_title)" "$pack_error"
            return 1
        fi
    fi
    if ! resh_cmd enable "$rom" >> "$log" 2>&1; then
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "$log")"
        return 1
    fi
    msgbox "$(i18n resh_title)" "$(i18n resh_installed "$log")"
    if [ -n "$local_pack" ]; then resh_pack_setup_info; fi
    if [ "$apply_community" -eq 1 ]; then
        community_import_actions reshade "$community_preset" "$(i18n resh_title)" "$rom"
    fi
}

resh_external_menu() {
    local rom="$1" details="$2" state="${2%%$'\n'*}" choice label
    while true; do
        case "$state" in
            external-enabled) label="$(i18n resh_external_enabled)" ;;
            external-disabled) label="$(i18n resh_external_disabled)" ;;
            *) label="$(i18n resh_external_unknown)" ;;
        esac
        choice="$(menu_select "$(i18n resh_title) — ${rom##*/}" "$(i18n resh_external_info "$label"$'\n'"${details#*$'\n'}")" \
            enable "$(i18n resh_enable)" disable "$(i18n resh_disable)" \
            release "$(i18n resh_external_release)" diagnostic "$(i18n resh_diag_title)" \
            community "$(i18n resh_community)" \
            restore-preset "$(community_txt 'Restaurer les réglages précédant le preset communautaire' 'Restore settings before the community preset')" back "$(i18n back)")" || return
        case "$choice" in
            restore-preset)
                yesno_default_no "$(i18n resh_title)" "$(community_txt 'Restaurer les réglages ReShade précédents ?' 'Restore the previous ReShade settings?')" || continue
                local output
                if output="$(resh_cmd existing-restore "$rom" 2>&1)"; then msgbox "$(i18n resh_title)" "$(community_txt 'Réglages précédents restaurés.' 'Previous settings restored.')";
                else msgbox "$(i18n resh_title)" "$output"; fi ;;
            community) community_menu reshade "$rom"; continue ;;
            enable|disable)
                if [ "$state" = external-unsupported ]; then
                    msgbox "$(i18n resh_title)" "$(i18n resh_external_unsupported)"; continue
                fi
                resh_cmd "external-$choice" "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 && {
                    msgbox "$(i18n resh_title)" "$(i18n resh_external_done)"
                } || msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")" ;;
            release)
                local output
                output="$(resh_cmd existing-restore "$rom" 2>&1)" || { msgbox "$(i18n resh_title)" "$output"; continue; }
                resh_cmd external-release "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"; continue;
                }
                return ;;
            diagnostic) resh_diagnostic "$rom" && exit 0 ;;
            *) return ;;
        esac
        details="$(resh_cmd external-info "$rom")"; state="${details%%$'\n'*}"
    done
}

resh_pack_zip_file() {
    local archive
    if command -v yad >/dev/null 2>&1; then
        archive="$(DISPLAY="${DISPLAY:-:0}" LANGUAGE="$WT_LANGUAGE" yad --file --filename=/userdata/ \
            --title="$(community_txt 'Importer un pack ReShade local' 'Import local ReShade bundle')" \
            --file-filter='ReShade ZIP | *.zip *.ZIP' --width=1000 --height=700)" || return
    else
        archive="$(input_text "$(i18n resh_title)" "$(community_txt 'Chemin du pack ReShade ZIP' 'ReShade ZIP bundle path')" /userdata/)" || return
    fi
    printf '%s' "$archive"
}

resh_pack_source() {
    local kind folder
    kind="$(menu_select "$(i18n resh_title)" "$(community_txt 'Source du pack ReShade local' 'Local ReShade bundle source')" \
        zip "$(community_txt 'Archive ZIP' 'ZIP archive')" directory "$(community_txt 'Dossier' 'Directory')" back "$(i18n back)")" || return 1
    case "$kind" in
        zip) resh_pack_zip_file ;;
        directory)
            if command -v yad >/dev/null 2>&1; then
                folder="$(DISPLAY="${DISPLAY:-:0}" LANGUAGE="$WT_LANGUAGE" yad --file --directory --filename=/userdata/ \
                    --title="$(community_txt 'Dossier contenant ReShade.ini et reshade-shaders' 'Directory containing ReShade.ini and reshade-shaders')" \
                    --width=1000 --height=700)" || return 1
            else
                folder="$(input_text "$(i18n resh_title)" "$(community_txt 'Dossier contenant ReShade.ini et reshade-shaders' 'Directory containing ReShade.ini and reshade-shaders')" /userdata/)" || return 1
            fi
            [ -n "$folder" ] || return 1
            printf '%s' "$folder" ;;
        *) return 1 ;;
    esac
}

resh_pack_menu() {
    local rom="$1" choice archive info summary preset output
    local mode="${2:-apply}"
    info="$(resh_cmd pack-status "$rom" 2>>"${WT_SESSION_LOG:-/dev/null}")" || return 1
    if [ "$info" != '{}' ]; then
        summary="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("selected", ""))' "$info")"
        choice="$(menu_select "$(i18n resh_title)" "$(community_txt 'Pack local installé' 'Installed local bundle'): $summary" \
            remove "$(community_txt 'Retirer le pack et restaurer les réglages précédents' 'Remove bundle and restore previous settings')" back "$(i18n back)")" || return
        [ "$choice" = remove ] || return
        yesno_default_no "$(i18n resh_title)" "$(community_txt 'Retirer ce pack et restaurer le preset et la configuration précédents ?' 'Remove this bundle and restore the previous preset and configuration?')" || return
        if output="$(resh_cmd pack-remove "$rom" 2>&1)"; then
            msgbox "$(i18n resh_title)" "$(community_txt 'Pack retiré. Réglages précédents restaurés.' 'Bundle removed. Previous settings restored.')"
        else msgbox "$(i18n resh_title)" "$output"; fi
        return
    fi
    archive="$(resh_pack_source)" || return 1
    if ! info="$(resh_cmd pack-info "$archive" 2>&1)"; then msgbox "$(i18n resh_title)" "$info"; return 1; fi
    summary="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print("ReShade: "+(d["required_release"] or "full add-on support")); print("Add-ons: "+", ".join(n+" ("+str(a)+" bits)" for n,a in d["addons"].items())); print("Presets ("+str(len(d["presets"]))+"): "+", ".join(d["presets"])); print(str(d["files"])+" files / "+str(round(d["bytes"]/1048576,1))+" MiB")' "$info")" || return
    preset="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["preferred"])' "$info")" || return 1
    yesno_default_no "$(i18n resh_title)" "$summary

$(community_txt 'Preset initial :' 'Initial preset:') $preset
$(community_txt 'Tous les presets détectés seront importés.' 'All detected presets will be imported.')
$(community_txt 'Installer pour ce jeu les add-ons exécutables et les shaders de ce pack ? Les réglages actuels seront sauvegardés. Le pack Citra nécessite ReShade 6.3.3 avec add-ons.' 'Install the executable add-ons and shaders from this bundle for this game? Current settings will be backed up. The Citra bundle requires ReShade 6.3.3 with add-ons.')" || return 1
    if [ "$mode" = select ]; then
        printf '%s\n%s\n' "$archive" "$preset"
        return 0
    fi
    if output="$(resh_cmd pack-import "$rom" "$archive" "$preset" 2>&1)"; then
        resh_pack_setup_info
    else msgbox "$(i18n resh_title)" "$output"; return 1; fi
}

resh_pack_setup_info() {
    msgbox "$(i18n resh_title)" "$(community_txt 'Pack installé. Pour Citra : ouvrez ReShade avec Home, vérifiez citra.addon et choisissez le tampon de profondeur. Réglez la disposition des écrans dans Citra.fx, placé en tête des effets. Le mode performance reste désactivé pour ces réglages. La compatibilité en jeu, notamment Vulkan, reste à vérifier.' 'Bundle installed. For Citra: open ReShade with Home, check citra.addon and select the depth buffer. Set the screen layout in Citra.fx, first in the effect order. Performance mode stays off for setup. In-game compatibility, including Vulkan, still needs testing.')"
}

resh_clear_all_presets() {
    local target="$1" mode="${2:-global}" output command=presets-global-clear
    [ "$mode" != game ] || command=presets-clear
    yesno_default_no "$(i18n resh_title)" "$(community_txt 'Supprimer tous les presets conservés pour ce jeu, y compris le preset actif ? Une sauvegarde sera créée. Un jeu géré repartira avec un preset vide ; ReShade, les shaders et les add-ons resteront installés. Fermez le jeu avant de continuer.' 'Delete all saved presets for this game, including the active preset? A backup will be created. A managed game will restart with an empty preset; ReShade, shaders and add-ons stay installed. Close the game before continuing.')" || return 1
    if output="$(resh_cmd "$command" "$target" 2>&1)"; then
        msgbox "$(i18n resh_title)" "$(community_txt 'Presets supprimés. Sauvegarde :' 'Presets removed. Backup:') $output"
    else
        msgbox "$(i18n resh_title)" "$output"
        return 1
    fi
}

resh_presets_menu() {
    local rom="$1" listing identity label choice action output name source
    local -a items=()
    while true; do
        if ! listing="$(resh_cmd presets-list "$rom" 2>&1)"; then
            msgbox "$(i18n resh_title)" "$listing"; return 1
        fi
        items=()
        while IFS=$'\t' read -r identity label; do
            [ -n "$identity" ] || continue
            items+=("$identity" "$label")
        done < <(python3 -c 'import json,sys; rows=json.loads(sys.argv[1]); active=sys.argv[2]; other=sys.argv[3]; print("\n".join(r["id"]+"\t"+r["name"]+(" — "+active if r["active"] else "")+(" — "+other if not r["compatible"] else "") for r in rows))' "$listing" "$(community_txt 'actif' 'active')" "$(community_txt 'autre contexte de shaders' 'different shader context')")
        choice="$(menu_select "$(community_txt 'Presets du jeu' 'Game presets') — ${rom##*/}" \
            "$(community_txt 'Sélectionnez un preset pour afficher ses détails. Fermez le jeu avant de changer de preset.' 'Select a preset to see its details. Close the game before changing presets.')" \
            "${items[@]}" import "$(community_txt 'Importer et activer un preset INI' 'Import and activate an INI preset')" \
            pack-presets "$(community_txt 'Ajouter les presets du pack installé depuis un ZIP ou dossier' 'Add presets from the installed bundle ZIP or directory')" \
            clear-all "$(community_txt 'Supprimer tous les presets pour ce jeu' 'Delete all presets for this game')" back "$(i18n back)")" || return
        case "$choice" in
            back|'') return ;;
            clear-all) resh_clear_all_presets "$rom" game; continue ;;
            import)
                source="$(resh_preset_file import "$rom")" || continue
                resh_import_ini "$rom" "$source" || continue
                continue ;;
            pack-presets)
                source="$(resh_pack_source)" || continue
                if ! output="$(resh_cmd presets-pack "$rom" "$source" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; fi
                continue ;;
        esac
        identity="$choice"
        while true; do
            if ! output="$(resh_cmd presets-info "$rom" "$identity" "$WT_LANGUAGE" 2>&1)"; then
                msgbox "$(i18n resh_title)" "$output"; break
            fi
            action="$(menu_select "$(community_txt 'Détails du preset' 'Preset details')" "$output" \
                select "$(community_txt 'Activer ce preset' 'Activate this preset')" \
                full "$(community_txt 'Afficher tous les paramètres INI' 'Show all INI settings')" \
                rename "$(community_txt 'Renommer' 'Rename')" delete "$(community_txt 'Supprimer de la liste' 'Delete from collection')" back "$(i18n back)")" || break
            case "$action" in
                select)
                    if ! output="$(resh_cmd presets-select "$rom" "$identity" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; fi
                    break ;;
                full)
                    if output="$(resh_cmd presets-info "$rom" "$identity" "$WT_LANGUAGE" full 2>&1)"; then community_report "$(community_txt 'Paramètres du preset' 'Preset settings')" "$output";
                    else msgbox "$(i18n resh_title)" "$output"; fi ;;
                rename)
                    name="$(input_text "$(i18n resh_title)" "$(community_txt 'Nom du preset' 'Preset name')" '')" || continue
                    if ! output="$(resh_cmd presets-rename "$rom" "$identity" "$name" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; fi ;;
                delete)
                    yesno_default_no "$(i18n resh_title)" "$(community_txt 'Supprimer ce preset de la collection du jeu ? Le preset actif doit être conservé.' 'Delete this preset from the game collection? The active preset must be kept.')" || continue
                    if ! output="$(resh_cmd presets-delete "$rom" "$identity" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; fi
                    break ;;
                *) break ;;
            esac
        done
    done
}

resh_preset_catalog_collection() {
    local collection="$1" listing rom orphan usable selected action output name destination identity label prompt
    local -a items=() extra=()
    while true; do
        if ! listing="$(resh_cmd presets-global-items "$collection" 2>&1)"; then msgbox "$(i18n resh_title)" "$listing"; return; fi
        rom="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["rom"])' "$listing")"
        orphan="$(python3 -c 'import json,sys; print(int(json.loads(sys.argv[1])["orphan"]))' "$listing")"
        usable=0; [ "$orphan" != 0 ] || usable=1
        items=(); extra=(clear-all "$(community_txt 'Supprimer tous les presets pour ce jeu' 'Delete all presets for this game')")
        while IFS=$'\t' read -r identity label; do
            [ -n "$identity" ] || continue
            items+=("$identity" "$label")
        done < <(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print("\n".join(v["id"]+"\t"+v["name"]+(" — "+sys.argv[2] if v["active"] else "") for v in d["items"]))' "$listing" "$(community_txt 'actif' 'active')")
        if [ "$usable" = 1 ]; then
            extra+=(game "$(community_txt 'Ouvrir la gestion complète des presets de ce jeu' 'Open full preset management for this game')")
        else
            extra+=(forget "$(community_txt 'Supprimer toute la collection et son association' 'Delete the entire collection and its association')")
        fi
        prompt="${rom:-$(community_txt 'Collection sans association connue' 'Collection with no known association')}"
        selected="$(menu_select "$(community_txt 'Gestionnaire de presets' 'Preset manager')" "$prompt" "${items[@]}" "${extra[@]}" back "$(i18n back)")" || return
        case "$selected" in
            back|'') return ;;
            clear-all) resh_clear_all_presets "$collection"; continue ;;
            game) resh_presets_menu "$rom"; continue ;;
            forget)
                yesno_default_no "$(i18n resh_title)" "$(community_txt 'Supprimer les presets conservés et leur association orpheline ? Les presets et métadonnées seront sauvegardés avant suppression.' 'Delete the retained presets and their orphan association? Presets and metadata will be backed up before deletion.')" || continue
                if output="$(resh_cmd presets-global-forget "$collection" 2>&1)"; then
                    msgbox "$(i18n resh_title)" "$(community_txt 'Collection supprimée. Sauvegarde :' 'Collection removed. Backup:') $output"; return
                else msgbox "$(i18n resh_title)" "$output"; fi
                continue ;;
        esac
        identity="$selected"
        while true; do
            if ! output="$(resh_cmd presets-global-info "$collection" "$identity" "$WT_LANGUAGE" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; break; fi
            extra=()
            [ "$usable" != 1 ] || extra+=(select "$(community_txt 'Activer pour ce jeu' 'Activate for this game')")
            action="$(menu_select "$(community_txt 'Détails du preset' 'Preset details')" "$output" "${extra[@]}" \
                full "$(community_txt 'Afficher tous les paramètres INI' 'Show all INI settings')" \
                rename "$(community_txt 'Renommer' 'Rename')" copy "$(community_txt 'Dupliquer' 'Duplicate')" \
                export "$(community_txt 'Exporter ce preset' 'Export this preset')" \
                delete "$(community_txt 'Supprimer ce preset' 'Delete this preset')" back "$(i18n back)")" || break
            case "$action" in
                select)
                    if ! output="$(resh_cmd presets-select "$rom" "$identity" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; fi
                    break ;;
                full)
                    if output="$(resh_cmd presets-global-info "$collection" "$identity" "$WT_LANGUAGE" full 2>&1)"; then community_report "$(i18n resh_title)" "$output";
                    else msgbox "$(i18n resh_title)" "$output"; fi ;;
                rename|copy)
                    name="$(input_text "$(i18n resh_title)" "$(community_txt 'Nom du preset' 'Preset name')" '')" || continue
                    if ! output="$(resh_cmd "presets-global-$action" "$collection" "$identity" "$name" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; fi ;;
                export)
                    destination="$(resh_preset_file export "${rom:-preset.ini}")" || continue
                    if output="$(resh_cmd presets-global-export "$collection" "$identity" "$destination" overwrite 2>&1)"; then msgbox "$(i18n resh_title)" "$(i18n resh_export_done "$destination")";
                    else msgbox "$(i18n resh_title)" "$output"; fi ;;
                delete)
                    yesno_default_no "$(i18n resh_title)" "$(community_txt 'Supprimer ce preset ? Pour un jeu encore installé, le preset actif doit être conservé.' 'Delete this preset? For an installed game, the active preset must be retained.')" || continue
                    if ! output="$(resh_cmd presets-global-delete "$collection" "$identity" 2>&1)"; then msgbox "$(i18n resh_title)" "$output"; fi
                    break ;;
                *) break ;;
            esac
        done
    done
}

resh_preset_catalog_menu() {
    local listing identity label choice query="" filter=all
    local -a items=()
    while true; do
        if ! listing="$(resh_cmd presets-catalog 2>&1)"; then msgbox "$(i18n resh_title)" "$listing"; return; fi
        if [ "$listing" = '[]' ]; then msgbox "$(i18n resh_title)" "$(community_txt 'Aucun preset conservé.' 'No saved presets.')"; return; fi
        items=()
        while IFS=$'\t' read -r identity label; do
            [ -n "$identity" ] || continue
            items+=("$identity" "$label")
        done < <(python3 -c 'import json,sys; rows=json.loads(sys.argv[1]); fr=sys.argv[2]=="fr"; query=sys.argv[3].casefold(); mode=sys.argv[4]; labels={"present":("jeu présent","game present"),"missing":("jeu absent/déplacé","game missing/moved"),"uninstalled":("ReShade désinstallé","ReShade uninstalled"),"unknown":("association inconnue","unknown association")}; print("\n".join(v["id"]+"\t"+v["name"]+" — "+str(v["count"])+" preset(s) — "+labels[v["status"]][0 if fr else 1] for v in rows if query in (v["name"]+v["rom"]).casefold() and (mode=="all" or v["orphan"])))' "$listing" "$WT_LANGUAGE" "$query" "$filter")
        choice="$(menu_select "$(community_txt 'Gestionnaire de presets installés' 'Installed preset manager')" \
            "$(community_txt 'Collections conservées, y compris pour les jeux supprimés ou déplacés.' 'Retained collections, including deleted or moved games.')" "${items[@]}" \
            search "$(community_txt 'Rechercher un jeu' 'Find a game')" filter "$(community_txt 'Basculer entre toutes les collections et les associations orphelines' 'Toggle all collections / orphan associations')" back "$(i18n back)")" || return
        case "$choice" in
            back|'') return ;;
            search) query="$(input_text "$(i18n resh_title)" "$(i18n resh_search_prompt)" "$query")" || query="" ;;
            filter) if [ "$filter" = all ]; then filter=orphan; else filter=all; fi ;;
            *) resh_preset_catalog_collection "$choice" ;;
        esac
    done
}

resh_game_menu() {
    local rom="$1" state choice preset profile details version arch dll exe packs prompt
    while true; do
        state="$(resh_cmd status "$rom")" || return
        if [ "$state" = missing ]; then
            details="$(resh_cmd external-info "$rom" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
                msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"; return;
            }
            case "${details%%$'\n'*}" in
                external-*) resh_external_menu "$rom" "$details"; return ;;
            esac
        fi
        prompt="$(i18n resh_game_status "$(i18n "resh_status_$state")")"
        if [ "$state" != missing ]; then
            details="$(resh_cmd details "$rom")" || return
            IFS=$'\t' read -r version arch dll exe packs <<< "$details"
            case "$version" in
                *-no-startup-banner) version="${version%-no-startup-banner} — $(i18n resh_variant_no_banner)" ;;
                *-addons) version="${version%-addons} — $(i18n resh_variant_addons)" ;;
            esac
            prompt+="\n\n$(i18n resh_details "$version" "$arch" "$dll" "$exe" "$packs")"
        fi
        local -a actions=(install "$(i18n resh_install)")
        if [ "$state" != missing ]; then
            if [ "$state" = disabled ]; then actions+=(enable "$(i18n resh_enable)")
            else actions+=(disable "$(i18n resh_disable)"); fi
            actions+=(presets "$(community_txt 'Presets du jeu et détails' 'Game presets and details')" pack "$(community_txt 'Pack ReShade local (ZIP ou dossier, add-ons et shaders)' 'Local ReShade bundle (ZIP or directory, add-ons and shaders)')" preset "$(i18n resh_preset)" export "$(i18n resh_export_title)" profile "$(i18n resh_profile)" uninstall "$(i18n resh_uninstall)")
        fi
        choice="$(menu_select "$(i18n resh_title) — $(basename "$rom")" "$prompt" \
            "${actions[@]}" community "$(i18n resh_community)" back "$(i18n back)")" || return
        case "$choice" in
            community) community_menu reshade "$rom" ;;
            install) resh_install_game "$rom" ;;
            pack) resh_pack_menu "$rom" ;;
            presets) resh_presets_menu "$rom" ;;
            enable|disable)
                resh_cmd "$choice" "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
                } ;;
            uninstall)
                yesno_default_no "$(i18n resh_title)" "$(i18n resh_uninstall_confirm)" || continue
                resh_cmd uninstall "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
                } ;;
            preset|export)
                if [ "$state" = missing ]; then
                    msgbox "$(i18n resh_title)" "$(i18n resh_install_first)"
                    continue
                fi
                if [ "$choice" = preset ]; then
                    preset="$(resh_preset_file import "$rom")" || continue
                    resh_import_ini "$rom" "$preset" || continue
                else
                    preset="$(resh_preset_file export "$rom")" || continue
                    resh_cmd export "$rom" "$preset" overwrite >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 && {
                        msgbox "$(i18n resh_title)" "$(i18n resh_export_done "$preset")"
                    } || msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
                fi ;;
            profile)
                profile="$(resh_cmd profile "$rom")" || continue
                msgbox "$(i18n resh_title)" "$(i18n resh_profile_path "$profile")" ;;
            back|"") return ;;
        esac
    done
}

resh_game_rows() {
    case "${1:-all}" in
        enabled|installed) python3 "$RESH_HELPER" --home "$WT_HOME" configured-list "$1" ;;
        *) mangohud_list_games | python3 "$RESH_HELPER" --home "$WT_HOME" status-list ;;
    esac
}

resh_pick_game() {
    local filter="${1:-all}" query="${2:-}" rom choice path name state label enabled_label disabled_label missing_label external_enabled external_disabled external_unsupported
    local -a games=() items=()
    local -A WT_MENU_GAME_LABELS=()
    enabled_label="$(i18n resh_status_enabled)"
    disabled_label="$(i18n resh_status_disabled)"
    missing_label="$(i18n resh_status_missing)"
    external_enabled="$(i18n resh_external_enabled)"
    external_disabled="$(i18n resh_external_disabled)"
    external_unsupported="$(i18n resh_external_unknown)"
    while IFS= read -r -d '' path && IFS= read -r -d '' state; do
        name="${path##*/}"
        [[ -z "$query" || "${name,,}" == *"${query,,}"* ]] || continue
        games+=("$path")
        case "$state" in
            enabled) label="$enabled_label" ;;
            disabled) label="$disabled_label" ;;
            external-enabled) label="$external_enabled" ;;
            external-disabled) label="$external_disabled" ;;
            external-unsupported) label="$external_unsupported" ;;
            *) label="$missing_label" ;;
        esac
        WT_MENU_GAME_LABELS["${#games[@]}"]="$name"
        items+=("${#games[@]}" "$name — $label")
    done < <(resh_game_rows "$filter" 2>> "${WT_SESSION_LOG:-/dev/null}")
    [ "${#games[@]}" -gt 0 ] || { msgbox "$(i18n resh_title)" "$(i18n resh_no_match)"; return; }
    choice="$(WT_MENU_LIST=1 menu_select "$(i18n resh_title)" "$(i18n resh_game_prompt)" "${items[@]}")" || return
    case "$choice" in ''|*[!0-9]*) return ;; esac
    [ "$choice" -ge 1 ] && [ "$choice" -le "${#games[@]}" ] || return
    rom="${games[$((choice-1))]}"
    resh_game_menu "$rom"
}

resh_menu() {
    local choice query
    msgbox "$(i18n resh_title)" "$(i18n resh_intro)" || return
    while true; do
        choice="$(menu_select "$(i18n resh_title)" "$(i18n resh_list_prompt)" \
            all "$(i18n resh_list_all)" installed "$(i18n resh_list_installed)" \
            presets "$(community_txt 'Gérer les presets installés' 'Manage installed presets')" \
            community "$(i18n resh_community)" \
            scan "$(i18n resh_external_scan)" search "$(i18n resh_list_search)" back "$(i18n back)")" || return
        case "$choice" in
            community) community_menu reshade ;;
            presets) resh_preset_catalog_menu ;;
            installed|all) resh_pick_game "$choice" ;;
            scan)
                msgbox "$(i18n resh_title)" "$(i18n resh_external_scan_wait)" || continue
                local scan_log="${WT_LOG_DIR:-/userdata/system/logs/ultimate-wine-toolbox}/reshade-discovery.log"
                mkdir -p "${scan_log%/*}"
                : > "$scan_log"
                if have_dialog; then
                    dialog --no-shadow --title "$(i18n resh_title)" --infobox "$(i18n resh_external_scan_wait)" 14 90 || true
                fi
                local summary total completed failures
                if summary="$(mangohud_list_games | resh_cmd external-scan 2>> "$scan_log")"; then
                    IFS=$'\t' read -r total completed failures <<< "$summary"
                    if [ "${failures:-0}" -gt 0 ]; then
                        msgbox "$(i18n resh_title)" "$(i18n resh_external_scan_partial "$completed" "$total" "$failures" "$scan_log")"
                    else
                        msgbox "$(i18n resh_title)" "$(i18n resh_external_scan_done)"
                    fi
                else
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "$scan_log")"
                fi
                resh_pick_game installed ;;

            search)
                query="$(input_text "$(i18n resh_title)" "$(i18n resh_search_prompt)" "")" || continue
                [ -z "$query" ] || resh_pick_game all "$query" ;;
            *) return ;;
        esac
    done
}
