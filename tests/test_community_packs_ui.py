import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CommunityPackUITests(unittest.TestCase):
    def shell(self, code):
        with tempfile.TemporaryDirectory() as folder:
            script = 'source "$SOURCE"\ni18n() { echo "$1"; }\nmsgbox() { printf "%s\\n" "$2" >> "$WT_HOME/messages"; }\n'+code
            result = subprocess.run(['bash', '-c', script], env=dict(os.environ, SOURCE=str(ROOT/'toolbox/modules/community.sh'), WT_HOME=folder, WT_LANGUAGE='fr'), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return {p.name: p.read_text() for p in Path(folder).iterdir() if p.is_file()}

    def test_binary_submission_uses_pack_service_and_keeps_normal_receipt_ui(self):
        files = self.shell('''
community_packs_cmd() { printf '%s\\n' "$*" > "$WT_HOME/calls"; printf 'pack-id\\npending\\n'; }
community_service_cmd() { echo 'wrong text endpoint' >&2; return 99; }
community_report() { printf '%s\\n' "$2" > "$WT_HOME/report"; }
community_send_package Community '/tmp/My bundle.zip' reshade-pack
''')
        self.assertEqual(files['calls'].strip(), 'submit /tmp/My bundle.zip')
        self.assertIn('modérateur', files['report'])

    def test_browse_passes_zip_to_existing_import_or_install_wizard(self):
        for status, expected in [('enabled', 'pack'), ('missing', 'install')]:
            with self.subTest(status=status):
                files = self.shell('''
community_choose_reshade_pack() { printf '/tmp/My bundle.zip\\n'; }
resh_cmd() { echo STATUS; }
resh_pack_menu() { printf '%s\\n' pack "$1" "$2" "$3" > "$WT_HOME/apply"; }
resh_install_game() { printf '%s\\n' install "$1" "$2" "$3" "$4" > "$WT_HOME/apply"; }
community_browse_reshade_packs Community '/roms/My game.wine'
'''.replace('STATUS', status))
                lines = files['apply'].splitlines()
                self.assertEqual(lines[0], expected)
                self.assertEqual(lines[1], '/roms/My game.wine')
                self.assertEqual(lines[-1], '/tmp/My bundle.zip')

    def test_moderation_passes_exact_review_hash_after_confirmation(self):
        files = self.shell('''
community_packs_cmd() {
 printf '%s\\n' "$*" >> "$WT_HOME/calls"
 case "$1" in pending) if [ ! -f "$WT_HOME/done" ]; then printf 'pack-id\\tMy custom pack\\n'; fi;;
 review) printf 'expected-hash\\nCredits and member list\\n';;
 approve) touch "$WT_HOME/done"; echo approved;; *) return 99;; esac
}
community_report() { printf '%s\\n' "$2" > "$WT_HOME/review"; }
menu_select() { if [ "$3" = approve ]; then echo approve; else echo pack-id; fi; }
yesno_default_no() { echo yes > "$WT_HOME/confirmed"; }
community_review_reshade_packs Community pending
''')
        self.assertIn('approve pack-id expected-hash', files['calls'])
        self.assertIn('member list', files['review'])
        self.assertIn('confirmed', files)
