"""An isolated ES child of Ports preserves controller configuration and grouping."""
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import es_return_proxy as proxy


class ReturnProxyTests(unittest.TestCase):
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
