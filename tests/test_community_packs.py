import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import community_packs as cp
import community_service as service
import test_reshade_pack_export as export_fixture
import test_reshade as fixture


class CommunityPackTests(unittest.TestCase):
    source = export_fixture.PackExportTests.source
    prepare = export_fixture.PackExportTests.prepare
    setUp = fixture.ReShadeTests.setUp

    def fixture(self):
        self.package = self.prepare(self.source())
        self.data = self.package.read_bytes()
        self.metadata = cp.inspect(self.package)
        self.metadata['kind'] = 'reshade-pack'
        self.calls = []
        self.client = cp.Packs(self.home, transport=self.transport)
        return self.client

    def transport(self, request):
        self.calls.append(request)
        path = request.full_url.removeprefix(self.client.api)
        if path == '/health': return {'capabilities': ['reshade-packs']}
        if path == '/v1/packs/submissions':
            self.assertEqual(request.data, self.data)
            return {'id': self.metadata['id'], 'status': 'pending'}
        if path in ('/v1/packs', '/v1/packs/pending'):
            return {'entries': [self.metadata]}
        if path.endswith(('/download', '/review-download')): return self.data
        if path.endswith('/approve'):
            self.assertEqual(json.loads(request.data)['sha256'], self.metadata['sha256'])
            return {'id': self.metadata['id'], 'status': 'approved'}
        return {'metadata': self.metadata, 'status': 'pending'}

    def session(self):
        self.client.session.parent.mkdir(parents=True, exist_ok=True)
        self.client.session.write_text(json.dumps({'api': self.client.api, 'expires': int(time.time())+300, 'token': 'a'*64}))

    def test_submit_binary_preserves_export_and_writes_receipt(self):
        client = self.fixture()
        result = client.submit_pack(self.package)
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(self.package.read_bytes(), self.data)
        self.assertEqual(json.loads(self.package.with_suffix('.receipt.json').read_text())['id'], self.metadata['id'])

    def test_old_worker_is_detected_before_upload(self):
        client = self.fixture()
        with patch.object(client, 'request', return_value={'capabilities': []}):
            with self.assertRaisesRegex(ValueError, 'Worker'):
                client.submit_pack(self.package)
        self.assertEqual(len(self.calls), 0)
        self.assertTrue(self.package.exists())

    def test_fetch_verifies_zip_and_manifest_then_reuses_download(self):
        client = self.fixture()
        path = client.fetch_pack(self.metadata['id'])
        self.assertEqual(path.read_bytes(), self.data)
        self.assertEqual(client.fetch_pack(self.metadata['id']), path)
        self.assertEqual(sum(r.full_url.endswith('/download') for r in self.calls), 1)

    def test_checksum_mismatch_never_installs_download(self):
        client = self.fixture()
        self.data += b'corrupt'
        with self.assertRaisesRegex(ValueError, 'checksum'):
            client.fetch_pack(self.metadata['id'])
        self.assertEqual(list((self.home/'config/reshade-community-packs').glob('*.zip')), [])

    def test_changed_pack_metadata_cannot_be_installed(self):
        client = self.fixture()
        self.metadata['credits'] = 'Different credits'
        with self.assertRaisesRegex(ValueError, 'metadata mismatch'):
            client.fetch_pack(self.metadata['id'])

    def test_review_download_requires_session_and_approval_revalidates_bytes(self):
        client = self.fixture()
        with self.assertRaisesRegex(ValueError, 'session expired'):
            client.fetch_pack(self.metadata['id'], review=True)
        self.session()
        self.assertEqual(client.decide('approve', self.metadata['id'], self.metadata['sha256']), 'approved')
        reviewed = [r for r in self.calls if r.full_url.endswith('/review-download')]
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(reviewed[0].get_header('Authorization'), 'Bearer '+'a'*64)

    def test_catalogue_filter_checks_ids_and_does_not_mix_legacy_catalogue(self):
        client = self.fixture()
        self.assertEqual(len(client.listing(query='my game')), 1)
        self.assertEqual(client.listing(query='unrelated'), [])
        self.metadata['id'] = '../escape'
        with self.assertRaisesRegex(ValueError, 'identifier'):
            client.listing()

    def test_tampered_member_checksum_and_oversized_zip_refused_before_submission(self):
        client = self.fixture()
        with zipfile.ZipFile(self.package) as z: files = {n: z.read(n) for n in z.namelist()}
        files['My preset.ini'] += b'\nChanged=1\n'
        with zipfile.ZipFile(self.package, 'w') as z:
            for n,d in files.items(): z.writestr(n,d)
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            client.submit_pack(self.package)
        self.assertEqual(self.calls, [])
        with patch.object(cp, 'ZIP_LIMIT', 1):
            with self.assertRaisesRegex(ValueError, 'limit'):
                cp.inspect(self.package)

    def test_wrong_moderation_hash_does_not_send_decision(self):
        client = self.fixture()
        with self.assertRaisesRegex(ValueError, 'exact pack'):
            client.decide('approve', self.metadata['id'], 'b'*64)
        self.assertEqual(self.calls, [])
