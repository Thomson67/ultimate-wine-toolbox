"""An isolated ES child of Ports preserves controller configuration and grouping."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import es_return_proxy as proxy


class ReturnProxyTests(unittest.TestCase):
    def test_old_es_launching_group_then_child_opens_toolbox_only_once(self):
        request = self.home/'state/resume-wsq.request'
        request.parent.mkdir()
        trace = self.base/'opened'
        # Exercise the generated shell, with the same request consumption as
        # the installed Ports entry before its xterm opens the result screen.
        self.port.write_text('#!/bin/bash\n'
                             'cat ' + shlex.quote(str(request)) + ' >> ' + shlex.quote(str(trace)) + '\n'
                             'rm -- ' + shlex.quote(str(request)) + '\n')
        _, launcher = self.create()
        for payload in (b'antimicrox\n', b'reshade\n', b''):
            with self.subTest(payload=payload):
                trace.unlink(missing_ok=True)
                request.write_bytes(payload)
                first = subprocess.run(['bash', launcher], capture_output=True, text=True)
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertTrue(trace.exists())
                self.assertEqual(trace.read_bytes(), payload)
                self.assertFalse(request.exists())
                # ES 43.1's second queued launch runs after Alt+F4 ends the
                # first Ports launch. It must not reopen the finished screen.
                trace.unlink()
                second = subprocess.run(['bash', launcher], capture_output=True, text=True)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertIn('duplicate launch skipped', second.stderr)
                self.assertFalse(trace.exists())

    def test_proxy_without_pending_request_does_not_call_native_port(self):
        _, launcher = self.create()
        result = subprocess.run(['bash', launcher], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('no pending return', result.stderr)
        # Manual opening through Ports remains valid without a return marker.
        manual = subprocess.run(['bash', str(self.port)], capture_output=True, text=True)
        self.assertEqual(manual.stdout, 'toolbox\n')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base/'home'; self.home.mkdir()
        self.user = self.base/'user'; self.user.mkdir()
        self.system = self.base/'system'; self.system.mkdir()
        self.primary = self.system/'es_systems.cfg'
        self.primary.write_text('''<systemList><system><name>ports</name><fullname>Ports</fullname>
<path>/userdata/roms/ports</path><extension>.sh .squashfs</extension><platform>pc</platform>
<command>emulatorlauncher %CONTROLLERSCONFIG% -system %SYSTEM% -rom "%ROM%" -gameinfoxml %GAMEINFOXML%</command>
<emulators><emulator name="sh"><cores><core default="true">sh</core></cores></emulator></emulators>
</system></systemList>''')
        self.port = self.base/'ports/Ultimate Wine Toolbox.sh'; self.port.parent.mkdir()
        self.port.write_text('#!/bin/bash\necho toolbox\n')
        self.keys = Path(str(self.port)+'.keys'); self.keys.write_text('{"actions_player1": []}')
        self.settings = self.user/'es_settings.cfg'
        self.settings.write_text('<config><bool name="ports.ungroup" value="false" /></config>')

    def create(self):
        return proxy.ensure_proxy(self.home, self.user, self.system, self.port)

    def test_only_owned_config_is_added_and_native_files_remain_unchanged(self):
        settings = self.settings.read_bytes(); primary = self.primary.read_bytes()
        name, rom = self.create()
        self.assertEqual(name, 'uwt_return')
        root = ET.parse(self.user/proxy.CONFIG_NAME).getroot()
        system = root.find('system')
        self.assertEqual(system.findtext('group'), 'ports')
        self.assertEqual(system.findtext('name'), name)
        self.assertEqual(system.findtext('path'), str(Path(rom).parent))
        command = system.findtext('command')
        self.assertIn('%CONTROLLERSCONFIG%', command)
        self.assertIn('-system ports', command)
        self.assertIn('%GAMEINFOXML%', command)
        self.assertNotIn('%SYSTEM%', command)
        self.assertEqual(Path(str(rom)+'.keys').read_bytes(), self.keys.read_bytes())
        self.assertIn(str(self.port), Path(rom).read_text())
        self.assertEqual(self.settings.read_bytes(), settings)
        self.assertEqual(self.primary.read_bytes(), primary)
        self.assertTrue(Path(rom).stat().st_mode & 0o100)
        metadata = ET.parse(Path(rom).parent/'gamelist.xml').getroot()
        self.assertEqual(metadata.findtext('folder/hidden'), 'true')
        self.assertEqual(metadata.findtext('game/hidden'), 'true')

    def test_owned_proxy_can_be_updated_after_pad2key_changes(self):
        _, rom = self.create()
        self.keys.write_text('{"actions_player1": [{"trigger":"b","type":"key","target":"KEY_ENTER"}]}')
        self.create()
        self.assertEqual(Path(str(rom)+'.keys').read_bytes(), self.keys.read_bytes())

    def rewrite_as_es(self, path, count):
        root = ET.parse(path).getroot()  # Default parser drops XML comments, like ES.
        game = root.find('game')
        for tag, text in {'playcount': str(count), 'lastplayed': '20261020T170943',
                          'gametime': '53', 'hidden': 'false'}.items():
            node = game.find(tag)
            if node is None:
                node = ET.SubElement(game, tag)
            node.text = text
        ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
        self.assertNotIn(proxy.MARKER.encode(), path.read_bytes())

    def test_repeated_es_rewrites_preserve_metadata_and_restore_hidden_flags(self):
        _, rom = self.create()
        path = Path(rom).parent/'gamelist.xml'
        for count in range(1, 4):
            self.rewrite_as_es(path, count)
            self.assertEqual(self.create()[1], rom)
            root = ET.parse(path).getroot()
            self.assertEqual(root.findtext('game/playcount'), str(count))
            self.assertEqual(root.findtext('game/lastplayed'), '20261020T170943')
            self.assertEqual(root.findtext('game/gametime'), '53')
            self.assertEqual(root.findtext('game/hidden'), 'true')
            self.assertEqual(root.findtext('folder/hidden'), 'true')

    def test_legacy_install_with_comment_removed_is_migrated_automatically(self):
        _, rom = self.create()
        runtime = Path(rom).parent
        (runtime/'gamelist.owner').unlink()
        self.rewrite_as_es(runtime/'gamelist.xml', 7)
        # ES may use absolute paths and omit the root-folder entry.
        root = ET.parse(runtime/'gamelist.xml').getroot()
        root.remove(root.find('folder'))
        root.find('game/path').text = rom
        ET.ElementTree(root).write(runtime/'gamelist.xml')
        self.create()
        self.assertEqual((runtime/'gamelist.owner').read_text(), proxy.MARKER)
        self.assertEqual(ET.parse(runtime/'gamelist.xml').findtext('game/playcount'), '7')
        self.assertEqual(ET.parse(runtime/'gamelist.xml').findtext('folder/hidden'), 'true')

    def test_fresh_foreign_gamelist_cannot_gain_ownership_from_newly_created_assets(self):
        runtime = proxy.proxy_launcher(self.home).parent
        runtime.mkdir(parents=True)
        path = runtime/'gamelist.xml'
        path.write_text('<gameList><game><path>./Ultimate Wine Toolbox Return.sh</path></game></gameList>')
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'foreign'):
            self.create()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((runtime/'gamelist.owner').exists())
        self.assertFalse((self.user/proxy.CONFIG_NAME).exists())

    def test_sidecar_never_allows_foreign_entries_to_be_overwritten(self):
        _, rom = self.create()
        path = Path(rom).parent/'gamelist.xml'
        path.write_text('<gameList><game><path>../Other.sh</path></game></gameList>')
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'foreign entry'):
            self.create()
        self.assertEqual(path.read_bytes(), before)

    def test_gamelist_symlink_is_not_followed_even_with_owned_sidecar(self):
        _, rom = self.create()
        path = Path(rom).parent/'gamelist.xml'
        external = self.base/'foreign.xml'
        external.write_text('foreign')
        path.unlink()
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'foreign'):
            self.create()
        self.assertEqual(external.read_text(), 'foreign')

    def test_foreign_sidecar_is_not_overwritten(self):
        _, rom = self.create()
        owner = Path(rom).parent/'gamelist.owner'
        owner.write_text('foreign')
        with self.assertRaisesRegex(ValueError, 'foreign'):
            self.create()
        self.assertEqual(owner.read_text(), 'foreign')

    def test_foreign_config_is_never_overwritten(self):
        config = self.user/proxy.CONFIG_NAME; config.write_text('<systemList>foreign</systemList>')
        with self.assertRaisesRegex(ValueError, 'foreign'):
            self.create()
        self.assertEqual(config.read_text(), '<systemList>foreign</systemList>')
        self.assertFalse((self.home/'runtime').exists())

    def test_foreign_runtime_launcher_is_never_overwritten(self):
        runtime = self.home/'runtime/es-return-proxy'; runtime.mkdir(parents=True)
        launcher = runtime/'Ultimate Wine Toolbox Return.sh'; launcher.write_text('foreign launcher')
        with self.assertRaisesRegex(ValueError, 'foreign'):
            self.create()
        self.assertEqual(launcher.read_text(), 'foreign launcher')
        self.assertFalse((self.user/proxy.CONFIG_NAME).exists())

    def test_runtime_symlink_is_rejected(self):
        runtime = self.home/'runtime'; runtime.mkdir()
        external = self.base/'external'; external.mkdir()
        (runtime/'es-return-proxy').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'redirect'):
            self.create()
        self.assertEqual(list(external.iterdir()), [])

    def test_custom_native_ports_command_is_respected(self):
        (self.user/'es_systems_local.cfg').write_text('''<systemList><system><name>ports</name>
<command>custom-ports %CONTROLLERSCONFIG% -system %SYSTEM% -rom "%ROM%"</command>
</system></systemList>''')
        self.create()
        command = ET.parse(self.user/proxy.CONFIG_NAME).findtext('system/command')
        self.assertTrue(command.startswith('custom-ports '))
        self.assertIn('-system ports', command)


if __name__ == '__main__': unittest.main()
