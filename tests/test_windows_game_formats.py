"""Directory games remain selectable when ES lists only archive games."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import community_profiles as community
from antimicrox_pad2key import convert
from antimicrox_pad2key_state import Pad2KeyStore


class WindowsGameFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.roms = self.root / 'windows'; self.roms.mkdir()
        self.games = [self.roms / 'Game.wine', self.roms / 'Game.pc', self.roms / 'Archive.wsquashfs']
        for game in self.games[:2]:
            game.mkdir()
        self.games[2].touch()
        (self.games[0] / 'embedded.pc').mkdir()
        (self.roms / '.uwt-components-work/Extracted.wine').mkdir(parents=True)
        (self.roms / 'Not a directory.wine').touch()
        (self.roms / 'Not a file.wsquashfs').mkdir()
        (self.roms / 'Linked.pc').symlink_to(self.games[1], target_is_directory=True)
        (self.roms / 'Unsafe\tName.pc').mkdir()

    def response(self, values):
        response = MagicMock(); response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = json.dumps(values).encode()
        return response

    def test_merge_includes_wine_pc_and_archive_and_keeps_es_display_names(self):
        values = [{'path': str(self.games[2]), 'name': 'Name from ES'},
                  {'path': str(self.games[0]), 'name': 'Wine title from ES'}]
        with patch.object(community, 'WINDOWS_ROMS', self.roms):
            with patch.object(community.urllib.request, 'urlopen', return_value=self.response(values)):
                rows = dict(community.es_games())
        self.assertEqual(set(rows), {str(game) for game in self.games})
        self.assertEqual(rows[str(self.games[0])], 'Wine title from ES')
        self.assertEqual(rows[str(self.games[2])], 'Name from ES')

    def test_unavailable_es_still_allows_existing_game_assignment(self):
        with patch.object(community, 'WINDOWS_ROMS', self.roms):
            with patch.object(community.urllib.request, 'urlopen', side_effect=urllib.error.URLError('offline')):
                self.assertEqual(set(dict(community.es_games())), {str(game) for game in self.games})

    def test_hidden_or_traversal_paths_from_es_are_not_added(self):
        values = [{'path': str(self.roms / '.uwt-components-work/Extracted.wine'), 'name': 'Working copy'},
                  {'path': str(self.roms / '../Elsewhere.pc'), 'name': 'Outside'}]
        with patch.object(community, 'WINDOWS_ROMS', self.roms):
            with patch.object(community.urllib.request, 'urlopen', return_value=self.response(values)):
                self.assertEqual(set(dict(community.es_games())), {str(game) for game in self.games})

    def test_existing_profile_picker_routes_all_three_formats_to_assignment(self):
        shim = self.root / 'catalog.py'
        shim.write_text('''import os, sys, urllib.error
from pathlib import Path
sys.path.insert(0, os.environ['HELPERS'])
import community_profiles as c
c.WINDOWS_ROMS = Path(os.environ['ROMS'])
def offline(*a, **kw): raise urllib.error.URLError('offline')
c.urllib.request.urlopen = offline
c.main()
''')
        home = self.root / 'home'; home.mkdir()
        for game in self.games:
            with self.subTest(format=game.suffix):
                env = dict(os.environ, ROOT=str(ROOT), HELPERS=str(ROOT / 'toolbox/helpers'),
                           ROMS=str(self.roms), WT_HOME=str(home), WT_LANGUAGE='fr',
                           SHIM=str(shim), GAME_NAME=game.name)
                script = '''
source "$ROOT/toolbox/modules/community.sh"
source "$ROOT/toolbox/modules/antimicrox.sh"
community_cmd() { python3 "$SHIM" --home "$WT_HOME" "$@"; }
amx_ensure_installed() { :; }
amx_profile_file() { echo /userdata/Existing.amgp; }
amx_validate_profile() { echo "$1"; }
amx_assign_profile_for() { printf '%s\\n' "$@" > "$WT_HOME/assigned"; }
msgbox() { return 1; }; i18n() { echo Back; }
menu_select() {
 shift 2
 while [ "$#" -ge 2 ]; do
  case "$2" in *"$GAME_NAME"*) echo "$1"; return 0;; esac
  shift 2
 done
 return 1
}
amx_assign_existing
'''
                result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((home / 'assigned').read_text().splitlines(), [str(game), '/userdata/Existing.amgp'])

    def test_profile_assignment_and_pad2key_restoration_work_for_each_format(self):
        home = self.root / 'home'
        store = Pad2KeyStore(home, self.root)
        content = b'{"actions_player1":[{"trigger":"b","type":"key","target":"KEY_ENTER"}]}'
        for game in self.games:
            with self.subTest(format=game.suffix):
                keys = store.keys_path(str(game))
                keys.write_bytes(content); keys.chmod(0o640)
                profile = convert(keys, home, userdata=self.root)
                store.assign(str(game), str(profile))
                self.assertIn(str(game) + '\t' + str(profile), store.cfg.read_text())
                self.assertNotEqual(keys.read_bytes(), content)
                store.assign(str(game), '')
                self.assertEqual(keys.read_bytes(), content)
                self.assertEqual(keys.stat().st_mode & 0o777, 0o640)
                self.assertTrue(profile.exists())

    def test_local_antimicrox_picker_accepts_uppercase_directory_extensions(self):
        for name in ('Upper.WINE', 'Upper.PC'):
            with self.subTest(name=name):
                env = dict(os.environ, WT_HOME=str(self.root), WT_LANGUAGE='fr', ROOT=str(ROOT), NAME=name)
                script = '''source "$ROOT/toolbox/modules/antimicrox.sh"
mangohud_list_games() { printf '/userdata/roms/windows/%s\\n' "$NAME"; }
menu_select() { echo 1; }; msgbox() { return 1; }
amx_choose_game
'''
                result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '/userdata/roms/windows/' + name)
