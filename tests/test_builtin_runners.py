"""Explicit stock runner choices must not inherit the global custom runner."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuiltinRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.system = self.root / 'system'
        self.custom = self.root / 'custom'
        self.system.mkdir(); self.custom.mkdir()
        self.engine(self.system / 'wine-tkg')
        self.engine(self.system / 'wine-proton')
        self.engine(self.custom / 'GE-Proton-UMU')
        self.engine(self.custom / 'Classic')
        self.conf = self.root / 'batocera.conf'
        self.conf.write_text('windows.wine-runner=GE-Proton-UMU\n')

    def engine(self, folder, relative='bin/wine'):
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/bash\nexit 0\n'); path.chmod(0o755)

    def run_shell(self, command):
        script = '''source "$WT_ROOT/modules/wsquashfs.sh"
BATOCERA_SYSTEM_WINE="$TEST_ROOT/system"
BATOCERA_CUSTOM_WINE="$TEST_ROOT/custom"
WSQ_CONF="$TEST_ROOT/batocera.conf"
prefix="$TEST_ROOT/Game.wine"
''' + command
        return subprocess.run(['bash', '-uc', script], text=True, capture_output=True,
                              env=dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'), WT_HOME=str(self.root), TEST_ROOT=str(self.root)))

    def test_candidates_include_builtins_and_keep_umu_before_other_custom_runners(self):
        result = self.run_shell('wsq_runner_candidates')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['system\t__SYSTEM__', 'builtin\twine-tkg',
                         'builtin\twine-proton', 'umu\tGE-Proton-UMU', 'custom\tClassic'])

    def test_missing_or_unusable_builtins_are_not_offered(self):
        (self.system / 'wine-proton/bin/wine').chmod(0o644)
        result = self.run_shell('wsq_runner_candidates')
        self.assertNotIn('wine-proton', result.stdout)
        self.assertIn('wine-tkg', result.stdout)
        (self.system / 'wine-tkg/bin/wine').unlink()
        result = self.run_shell('wsq_runner_candidates')
        self.assertNotIn('builtin', result.stdout)

    def test_symlinked_builtin_and_legacy_library_engine_are_supported(self):
        (self.system / 'wine-proton').rename(self.root / 'proton-engine')
        (self.system / 'wine-proton').symlink_to(self.root / 'proton-engine')
        (self.system / 'wine-tkg/bin/wine').unlink()
        self.engine(self.system / 'wine-tkg', 'lib/wine/i386-unix/wine')
        result = self.run_shell('wsq_runner_candidates')
        self.assertIn('builtin\twine-proton', result.stdout)
        self.assertIn('builtin\twine-tkg', result.stdout)

    def test_explicit_choice_is_written_per_game_and_inheritance_removes_only_override(self):
        result = self.run_shell('''
i18n() { printf '%s' "$1"; }
menu_select() { printf '%s\\n' "$@" > "$TEST_ROOT/menu"; echo 3; }
selected="$(wsq_select_runner)"
[ "$selected" = wine-proton ] || exit 80
wsq_set_runner_config Game.wine "$selected"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.conf.read_text().splitlines(), [
            'windows.wine-runner=GE-Proton-UMU', '', 'windows["Game.wine"].wine-runner=wine-proton'])
        self.assertIn('wine-proton  [Batocera]', (self.root / 'menu').read_text())
        result = self.run_shell('wsq_set_runner_config Game.wine __SYSTEM__')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('windows.wine-runner=GE-Proton-UMU', self.conf.read_text())
        self.assertNotIn('windows["Game.wine"].wine-runner=', self.conf.read_text())

    def test_runner_resolution_keeps_native_and_custom_roots_separate(self):
        result = self.run_shell('''
printf '%s\\n' "$(wsq_runner_root wine-proton)" "$(wsq_runner_root Classic)" "$(wsq_runner_root __SYSTEM__)"
wsq_runner_usable "$(wsq_runner_root wine-proton)"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(self.system / 'wine-proton'),
                         str(self.custom / 'Classic'), str(self.custom / 'GE-Proton-UMU')])

    def test_winetricks_accepts_native_engine_and_dotnet_inspects_its_real_root(self):
        binary = self.root / 'batocera-wine'; binary.write_text('#!/bin/bash\nexit 99\n'); binary.chmod(0o755)
        result = self.run_shell('''
export PATH="$TEST_ROOT:$PATH"
runner=wine-proton
i18n() { printf '%s' "$1"; }
menu_select() { echo common; }
checklist_select() { echo corefonts; }
yesno_default_no() { return 0; }
wsq_display_path() { echo "$1"; }
wt_log() { :; }
msgbox() { exit 91; }
wsq_update_run() { printf '%s\\n' "$@" > "$TEST_ROOT/install"; }
wsq_install_extra_winetricks standalone || exit 92
wsq_dotnet_command() {
    printf '%s\\n' "$@" > "$TEST_ROOT/inspect"
    echo '{"status":"absent","mono":[],"microsoft":[],"shared":[],"dotnet48_marker":false}'
}
wsq_dotnet_report
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('wine-proton', (self.root / 'install').read_text())
        self.assertEqual((self.root / 'inspect').read_text().splitlines(),
                         ['inspect', '--runner-root', str(self.system / 'wine-proton')])
