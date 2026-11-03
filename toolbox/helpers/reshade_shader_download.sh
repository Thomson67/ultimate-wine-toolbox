#!/bin/bash
# Use only shader functions from the checksum-pinned backend. No DLL install.
set -eo pipefail
SCRIPT_DIR="$1"
MAIN_PATH="$2"
selection="$3"
[[ "$selection" =~ ^[a-z0-9_-]+(,[a-z0-9_-]+)*$ ]] || exit 1
export MAIN_PATH UI_BACKEND=cli NO_COLOR=1 PROGRESS_UI=0 UPDATE_RESHADE=0
unset SHADER_REPOS SHADER_REPO_PINS SHADER_REPOS_TRACK_HEAD SHADER_CORE_REPOS
for module in logging ui ui_yad ui_auto utils cli integrity reshade_pins shader_pins config state shader_registry shader_layout shader_build shaders; do
    source "$SCRIPT_DIR/lib/$module.sh" || exit 1
done
parseCliArgs --cli --no-input
init_runtime_config || exit 1
mkdir -p "$MAIN_PATH"
ensureSelectedShaderRepos "$selection" || exit 1
buildGameShaderDir preset "$selection" || exit 1
test -d "$MAIN_PATH/game-shaders/preset/Merged/Shaders"
