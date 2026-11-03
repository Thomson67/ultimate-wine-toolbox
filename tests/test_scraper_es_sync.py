"""Regression tests for ES overwriting externally edited Toolbox metadata."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import subprocess
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / 'toolbox/helpers/install-scraper-assets.sh'
SLUG = 'ultimate-wine-toolbox'
ROM = 'Ultimate Wine Toolbox.sh'
MEDIA = ('image', 'thumbnail', 'boxart', 'marquee', 'fanart')


class ScraperSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ports = self.base / 'ports'
        self.ports.mkdir()
        self.xml = self.ports / 'gamelist.xml'
        self.xml.write_text('<gameList><game><path>./Other.sh</path><name>Other</name>'
            '<image>./custom.jpg</image><playcount>33</playcount></game>'
            '<game><path>./Ultimate Wine Toolbox.sh</path><name>Ultimate Wine Toolbox</name>'
            '<playcount>69</playcount><gametime>28625</gametime></game></gameList>')
        self.before = self.xml.read_bytes()
        self.live = {'id': 'opaque-api-id', 'path': str(self.ports / ROM),
                     'name': 'Ultimate Wine Toolbox', 'playcount': '70',
                     'gametime': '29000', 'lastplayed': '20261103T120000',
                     'favorite': 'true', 'scraperId': 'original-scraper-id'}
        self.posts = []
        self.imported_paths = []
        self.force_no_content = False
        self.entry_update = False
        self.ignore_media_update = False
        self.ignore_post = False
        self.fail_post = False
        self.grouped = False
        self.native_group = False
        self.group_alias = False

    def save_live(self):
        # ES replaces a dirty entry from memory when saving/reloading.
        root = ET.parse(self.xml).getroot()
        for g in list(root):
            if g.findtext('path') in ('./' + ROM, str(self.ports / ROM)):
                root.remove(g)
        g = ET.SubElement(root, 'game')
        for key, value in self.live.items():
            if key in ('id', 'systemName'):
                continue
            ET.SubElement(g, 'id' if key == 'scraperId' else key).text = value
        ET.ElementTree(root).write(self.xml, encoding='utf-8')

    @contextmanager
    def api(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, data, code=200):
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                name = 'windowsports' if owner.grouped else 'ports'
                if self.path == '/systems':
                    systems = [{'name': name, 'group': 'ports', 'gamesystem': 'true',
                                'groupsystem': 'true' if owner.native_group else 'false'}]
                    if owner.grouped:
                        systems.insert(0, {'name': 'ports', 'groupsystem': 'true',
                                           'gamesystem': 'true' if owner.group_alias else 'false'})
                    return self.send(systems)
                if self.path == f'/systems/{name}/games':
                    games = [owner.live] if owner.live else []
                    if owner.native_group:
                        games = games + [{'path': str(owner.ports / 'UMU Runner Toolbox.sh'),
                                          'systemName': 'ports', 'id': 'umu-id', 'playcount': '33'},
                                         {'path': '/userdata/system/ultimate-wine-toolbox/runtime/es-return-proxy/Ultimate Wine Toolbox Return.sh',
                                          'systemName': 'uwt_return', 'id': 'return-id'}]
                    return self.send(games)
                if owner.group_alias and self.path == '/systems/ports/games':
                    return self.send([dict(owner.live, systemName=name)])
                if self.path.startswith(f'/systems/{name}/games/opaque-api-id?'):
                    if 'localpaths=true' not in self.path:
                        return self.send({}, 400)
                    return self.send(owner.live)
                return self.send({}, 404)

            def do_POST(self):
                owner.posts.append(self.path)
                if owner.fail_post:
                    return self.send({}, 500)
                payload = self.rfile.read(int(self.headers['Content-Length']))
                name = 'windowsports' if owner.grouped else 'ports'
                endpoint = f'/systems/{name}/games/opaque-api-id'
                if self.path == endpoint or self.path.startswith(endpoint + '/media/'):
                    if not owner.entry_update:
                        return self.send({}, 404)
                    if self.path == endpoint:
                        updates = json.loads(payload)
                        # Like ES v43: only non-path metadata is writable here.
                        for key, value in updates.items():
                            if key not in MEDIA and key != 'path':
                                owner.live[key] = value
                    elif not owner.ignore_media_update:
                        key = self.path.rsplit('/', 1)[1]
                        suffix = {'image': 'image', 'boxart': 'box', 'thumbnail': 'thumb',
                                  'fanart': 'fanart', 'marquee': 'marquee'}[key]
                        ext = '.jpg' if self.headers['Content-Type'] == 'image/jpeg' else '.png'
                        dest = owner.ports / 'images' / (Path(ROM).stem + '-' + suffix + ext)
                        dest.parent.mkdir(exist_ok=True)
                        dest.write_bytes(payload)
                        owner.live[key] = str(dest)
                    # These APIs update memory/recovery, not gamelist.xml.
                    return self.send('OK')
                if self.path != '/addgames/' + name:
                    return self.send({}, 404)
                g = ET.fromstring(payload).find('game')
                import_path = g.findtext('path', '')
                owner.imported_paths.append(import_path)
                # ES imports by exact fileMap key after resolving the root;
                # require the API's absolute spelling here, including aliases.
                expected_path = owner.live.get('path', str(owner.ports / ROM))
                if owner.force_no_content or import_path != expected_path:
                    return self.send('No game added / updated', 204)
                if not owner.ignore_post:
                    owner.live = {c.tag: c.text or '' for c in g}
                    if 'id' in owner.live:
                        owner.live['scraperId'] = owner.live.pop('id')
                    owner.live['id'] = 'opaque-api-id'
                    owner.live['path'] = str(owner.ports / ROM)
                    owner.save_live()
                return self.send('OK')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def run_install(self, url='http://127.0.0.1:1', running='0', source=None):
        args = ['bash', str(HELPER), str(source or ROOT / 'toolbox/scraper-assets'),
                SLUG, ROM, 'Ultimate Wine Toolbox', 'Description FR', 'Description EN',
                str(self.base / 'state'), str(self.base / 'backups')]
        return subprocess.run(args, capture_output=True, text=True,
            env=dict(os.environ, SCRAPER_PORTS_DIR=str(self.ports), SCRAPER_ES_URL=url,
                     SCRAPER_ES_RUNNING=running, SCRAPER_LOG_FILE=str(self.base / 'scraper.log')))

    def test_live_sync_survives_later_es_save_and_preserves_live_stats(self):
        with self.api() as url:
            result = self.run_install(url, '1')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.save_live()  # subsequent ES save/exit must retain the imported fields
            g = ET.parse(self.xml).getroot().findall('game')[1]
            for key in MEDIA:
                self.assertTrue(g.findtext(key), key)
            self.assertEqual(g.findtext('playcount'), '70')
            self.assertEqual(g.findtext('gametime'), '29000')
            self.assertEqual(g.findtext('favorite'), 'true')
            self.assertEqual(g.findtext('id'), 'original-scraper-id')
            self.assertEqual(ET.parse(self.xml).getroot()[0].findtext('image'), './custom.jpg')
            backups = list((self.base / 'backups').glob('*.xml'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), self.before)
            again = self.run_install(url, '1')
            self.assertEqual(again.returncode, 0, again.stdout)
            self.assertEqual(self.posts, ['/addgames/ports'])
            self.assertIn('memory and gamelist verified', (self.base / 'scraper.log').read_text())

    def test_disk_only_write_is_lost_when_dirty_es_entry_is_saved(self):
        self.assertEqual(self.run_install().returncode, 0)
        self.save_live()
        self.assertFalse(ET.parse(self.xml).getroot()[1].findtext('image'))

    def test_import_uses_literal_api_path_with_symlink_spelling(self):
        alias = self.base / 'ports-alias'
        alias.symlink_to(self.ports, target_is_directory=True)
        api_path = str(alias / ROM)
        self.live['path'] = api_path
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.imported_paths, [api_path])
        self.assertNotIn('import XML=', (self.base / 'scraper.log').read_text())

    def test_http_204_keeps_failure_without_dumping_xml(self):
        self.force_no_content = True
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), self.before)
        self.assertIn('HTTP 204', result.stdout + result.stderr)
        log = (self.base / 'scraper.log').read_text()
        self.assertNotIn('<gameList>', log)
        self.assertNotIn('memory and gamelist verified', log)

    def test_204_fallback_updates_existing_native_ports_without_reload(self):
        self.force_no_content = True
        self.entry_update = True
        self.native_group = True
        self.live['systemName'] = 'ports'
        before_other = ET.tostring(ET.parse(self.xml).getroot()[0])
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        root = ET.parse(self.xml).getroot()
        self.assertEqual(ET.tostring(root[0]), before_other)
        self.assertEqual(root[1].findtext('playcount'), '70')
        self.assertEqual(root[1].findtext('gametime'), '29000')
        for key in MEDIA:
            file = Path(root[1].findtext(key))
            self.assertTrue(file.is_file(), key)
            self.assertEqual(root[1].findtext(key), self.live[key])
        self.save_live()
        self.assertTrue(ET.parse(self.xml).getroot()[1].findtext('image'))
        self.assertEqual(len([p for p in self.posts if '/media/' in p]), 5)
        self.assertIn('mode=api; memory and gamelist verified', result.stdout)
        self.assertFalse(any('uwt_return' in p or 'reload' in p for p in self.posts))

    def test_204_fallback_verifies_media_memory_before_writing_xml(self):
        self.force_no_content = True
        self.entry_update = True
        self.ignore_media_update = True
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), self.before)
        self.assertNotIn('memory and gamelist verified', result.stdout)

    def test_204_fallback_preserves_conflicting_existing_media(self):
        self.force_no_content = True
        self.entry_update = True
        custom = self.ports / 'images' / (Path(ROM).stem + '-image.jpg')
        custom.parent.mkdir()
        custom.write_bytes(b'custom-art-do-not-overwrite')
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(custom.read_bytes(), b'custom-art-do-not-overwrite')
        self.assertEqual(self.xml.read_bytes(), self.before)
        self.assertEqual(self.posts, ['/addgames/ports'])

    def test_grouped_ports_imports_only_into_owning_real_system(self):
        self.grouped = True
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.posts, ['/addgames/windowsports'])

    def test_native_ports_also_marked_as_group_owns_its_toolbox(self):
        # User's ES v43.1 response: Ports is a group AND owns Toolbox entries;
        # other listed games, such as uwt_return, belong to child systems.
        self.native_group = True
        self.live['systemName'] = 'ports'
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.posts, ['/addgames/ports'])
        self.save_live()
        self.assertTrue(ET.parse(self.xml).getroot()[1].findtext('image'))
        self.assertEqual(ET.parse(self.xml).getroot()[0].findtext('playcount'), '33')

    def test_group_alias_does_not_count_as_second_owner(self):
        self.grouped = True
        self.group_alias = True
        self.live['systemName'] = 'windowsports'
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.posts, ['/addgames/windowsports'])

    def test_native_group_does_not_adopt_a_child_with_same_path(self):
        self.native_group = True
        self.live['systemName'] = 'uwt_return'
        # A child alias must not be mistaken for a fresh native launcher.
        self.ignore_post = True
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), self.before)
        self.assertEqual(self.posts, [])

    def test_live_custom_media_and_name_are_preserved(self):
        self.live.update(image=str(self.ports / 'my-art.jpg'), name='My Toolbox')
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertEqual(result.returncode, 0, result.stdout)
        g = ET.parse(self.xml).getroot()[1]
        self.assertEqual(g.findtext('image'), str(self.ports / 'my-art.jpg'))
        self.assertEqual(g.findtext('name'), 'My Toolbox')

    def test_running_es_without_api_does_not_claim_success_or_write_xml(self):
        result = self.run_install(running='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), self.before)
        self.assertIn('API is unavailable', (self.base / 'scraper.log').read_text())
        self.assertNotIn('corrected missing', result.stdout)

    def test_failed_sync_keeps_legacy_media_and_manifest(self):
        import hashlib
        legacy = self.ports / 'media/images/ultimate-wine-toolbox.png'
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b'old-managed-media')
        state = self.base / 'state'
        state.mkdir()
        manifest = state / 'scraper-assets.sha256'
        before = hashlib.sha256(legacy.read_bytes()).hexdigest() + ' media/images/ultimate-wine-toolbox.png\n'
        manifest.write_text(before)
        result = self.run_install(running='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(legacy.exists())
        self.assertEqual(manifest.read_text(), before)
        self.assertFalse(list(state.glob('.scraper-assets.sha256.*')))

    def test_success_response_without_import_fails_verification(self):
        self.ignore_post = True
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), self.before)
        self.assertIn('verification failed', result.stdout + result.stderr)

    def test_failed_import_does_not_fall_back_to_unsafe_disk_write(self):
        self.fail_post = True
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), self.before)

    def test_invalid_xml_is_preserved(self):
        self.xml.write_text('<broken')
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_text(), '<broken')

    def test_source_archive_ships_jpegs_without_runtime_conversion(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for folder in ('images', 'box2d', 'thumbnails', 'fanarts'):
            data = (self.ports / 'media' / folder / (SLUG + '.jpg')).read_bytes()
            self.assertTrue(data.startswith(b'\xff\xd8'))

    def test_fresh_install_imports_launcher_before_es_scan(self):
        self.live = {}
        with self.api() as url:
            result = self.run_install(url, '1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.posts, ['/addgames/ports'])


if __name__ == '__main__':
    unittest.main()
