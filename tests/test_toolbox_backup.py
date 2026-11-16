import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolbox/helpers"))
import toolbox_backup as backup
from batocera_conf_transfer import USER_MARKER


class ToolboxBackupTests(unittest.TestCase):
    def test_backup_menu_survives_loading_batocera_configuration(self):
        modules = Path(__file__).resolve().parents[1] / "toolbox/modules"
        script = r'''
set -eu
WT_LANGUAGE=fr
source "$1/maintenance.sh"
source "$1/batocera-conf.sh"
i18n() { printf '%s' "$1"; }
menu_select() {
    shift 2
    local backup_choice=
    while [ "$#" -ge 2 ]; do
        if [ "$2" = "Sauvegarder ou restaurer la Toolbox" ]; then
            backup_choice="$1"
        fi
        shift 2
    done
    [ -n "$backup_choice" ] || return 1
    printf '%s\n' "$backup_choice"
}
maintenance_backup_menu() { printf 'backup opened\n'; exit 0; }
maintenance_menu
'''
        result = subprocess.run(
            ["bash", "-c", script, "backup-menu-test", str(modules)],
            check=True, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.stdout, "backup opened\n")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.archive = self.root / "backup.tar.gz"
        self.settings = Path(backup.HOME, "config", "language")
        self.runner = backup.RUNNERS / "GE-Proton-test-UMU"
        self.write(self.source, "batocera.conf",
                   f"{USER_MARKER}\nwindows.dxvk=0\nwindows.emulator=wine\n"
                   'windows["Game.wine"].uwt_community_antimicrox=sample\n')
        self.write(self.target, "batocera.conf",
                   f"{USER_MARKER}\nwindows.dxvk=1\nwindows.emulator=auto\nwifi.enabled=1\n")
        self.write(self.source, self.settings, "fr\n")
        self.write(self.target, self.settings, "en\n")
        self.profile = Path(backup.HOME, "reshade", "profiles", "game", "presets", "test.ini")
        self.write(self.source, self.profile, "Techniques=Sample\n")
        self.write(self.source, self.runner / "bin/wine", "runner")
        (self.source / self.runner / "bin/wine").chmod(0o755)
        (self.source / self.runner / "wine").symlink_to("bin/wine")
        self.write(self.source, Path(backup.HOME, "reshade/installations/journal.json"), "{}")

    @staticmethod
    def write(root, relative, contents):
        location = root / relative
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_text(contents)

    def test_restore_merges_only_exported_windows_settings(self):
        backup.export(self.source, self.archive, False)
        backup.restore(self.target, self.archive, False, True)
        config = (self.target / "batocera.conf").read_text()
        for entry in ("windows.dxvk=1", "windows.emulator=auto", "uwt_community_antimicrox=sample", "wifi.enabled=1"):
            self.assertIn(entry, config)
        self.assertEqual((self.target / self.settings).read_text(), "en\n")
        self.assertEqual((self.target / self.profile).read_text(), "Techniques=Sample\n")
        self.assertFalse((self.target / self.runner).exists())
        self.assertFalse((self.target / backup.HOME / "reshade/installations").exists())

    def test_restore_with_replacement_backs_up_conflicts_and_preserves_runner_links(self):
        backup.export(self.source, self.archive, True)
        metadata = json.loads((self.source / backup.BACKUP_METADATA).read_text())
        self.assertEqual(metadata["path"], str(self.archive))
        self.assertEqual(metadata["bytes"], self.archive.stat().st_size)
        self.assertTrue(metadata["runners"])
        backup.restore(self.target, self.archive, True, True)
        config = (self.target / "batocera.conf").read_text()
        self.assertIn("windows.emulator=wine", config)
        self.assertNotIn("windows.emulator=auto", config)
        self.assertEqual((self.target / self.settings).read_text(), "fr\n")
        directory = self.target / "backups/ultimate-wine-toolbox"
        self.assertEqual([p.read_text() for p in directory.glob(f"before-restore-*/{self.settings}")], ["en\n"])
        self.assertTrue((self.target / self.runner / "wine").is_symlink())
        self.assertEqual((self.target / self.runner / "wine").read_text(), "runner")
        self.assertTrue((self.target / self.runner / "bin/wine").stat().st_mode & 0o100)

    def test_rejects_archive_entries_outside_managed_directories(self):
        with tarfile.open(self.archive, "w:gz") as archive:
            info = tarfile.TarInfo("data/../untouched")
            info.size = 4
            archive.addfile(info, io.BytesIO(b"test"))
        with self.assertRaises(ValueError):
            backup.restore(self.target, self.archive, True, True)
        self.assertFalse((self.target / "untouched").exists())
