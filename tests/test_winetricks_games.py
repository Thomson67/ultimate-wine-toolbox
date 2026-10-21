"""Standalone component selection must not consume a pending build session."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import winetricks_games as games


class StandaloneWinetricksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefix = self.root / 'Game with spaces.wine'
        (self.prefix / 'drive_c/windows').mkdir(parents=True)
        (self.prefix / 'system.reg').write_text('registry')
        (self.prefix / 'autorun.cmd').write_text('DIR=drive_c/game')

    def test_list_includes_game_formats_and_ignores_invalid_prefixes_and_aliases(self):
        (self.root / 'Game.wsquashfs').write_bytes(b'archive')
        (self.root / 'Alias.wine').symlink_to(self.prefix)
        (self.root / 'Incomplete.wine').mkdir()
        (self.root / '.hidden.wine').symlink_to(self.prefix)
        pc = self.root / 'Another.pc'; pc.mkdir()
        self.assertEqual(games.prefixes(self.root), [pc, self.prefix, self.root / 'Game.wsquashfs'])
        self.assertEqual(games.prefixes(self.root / 'missing'), [])
        windows = self.prefix / 'drive_c/windows'
        windows.rmdir()
        windows.symlink_to(self.root)
        self.assertFalse(games.valid_prefix(self.prefix))

    def test_runner_uses_game_then_system_configuration_without_writing_it(self):
        conf = self.root / 'batocera.conf'
        self.assertEqual(games.configured_runner(self.prefix, conf), '__SYSTEM__')
        text = ('windows.wine-runner=Global\n'
                '# windows.wine-runner=Ignored\n'
                'windows["Other.wine"].wine-runner=Other\n')
        conf.write_text(text)
        self.assertEqual(games.configured_runner(self.prefix, conf), 'Global')
        text += 'windows["Game with spaces.wine"].wine-runner=Selected\n'
        conf.write_text(text)
        self.assertEqual(games.configured_runner(self.prefix, conf), 'Selected')
        self.assertEqual(conf.read_text(), text)

    def test_menu_routes_components_and_dotnet_without_touching_creation_state(self):
        (self.root / 'batocera.conf').write_text('windows.wine-runner=Configured\n')
        state = self.root / 'wsquashfs-builder.json'
        state.write_text('{"phase":"configuring","prefix":"pending.wine"}')
        script = r'''
source "$WT_ROOT/modules/winetricks.sh"
WSQ_WINDOWS_DIR="$TEST_ROOT"
WSQ_CONF="$TEST_ROOT/batocera.conf"
prefix=original-prefix
runner=original-runner
menu_select() {
    local step=0
    [ ! -f "$TEST_ROOT/step" ] || read -r step < "$TEST_ROOT/step"
    echo "$((step+1))" > "$TEST_ROOT/step"
    case "$step" in
        0) echo 1 ;; 1|4) echo components ;; 2) echo dotnet ;;
        3) echo runner ;; *) echo back ;;
    esac
}
i18n() { printf '%s' "$1"; }
msgbox() { :; }
wsq_select_runner() { echo Changed; }
wsq_install_extra_winetricks() { printf '%s|%s|%s\n' "$prefix" "$runner" "$1" >> "$TEST_ROOT/calls"; }
wsq_dotnet_menu() { printf 'dotnet|%s|%s\n' "$prefix" "$runner" >> "$TEST_ROOT/calls"; }
winetricks_game_menu
[ "$prefix" = original-prefix ] && [ "$runner" = original-runner ]
'''
        result = subprocess.run(['bash', '-uc', script], capture_output=True, text=True,
                                env=dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'), TEST_ROOT=str(self.root)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'calls').read_text().splitlines(), [
            f'{self.prefix}|Configured|standalone',
            f'dotnet|{self.prefix}|Configured',
            f'{self.prefix}|Changed|standalone'])
        self.assertEqual(state.read_text(), '{"phase":"configuring","prefix":"pending.wine"}')
        self.assertEqual((self.root / 'batocera.conf').read_text(), 'windows.wine-runner=Configured\n')

    def test_back_before_selection_does_not_call_an_installer(self):
        script = '''source "$WT_ROOT/modules/winetricks.sh"
WSQ_WINDOWS_DIR="$TEST_ROOT"
i18n() { echo "$1"; }
menu_select() { return 1; }
wsq_install_extra_winetricks() { exit 99; }
wsq_dotnet_menu() { exit 98; }
winetricks_game_menu
'''
        result = subprocess.run(['bash', '-uc', script], capture_output=True, text=True,
                                env=dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'), TEST_ROOT=str(self.root)))
        self.assertEqual(result.returncode, 0, result.stderr)
