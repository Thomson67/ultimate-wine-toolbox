import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import community_profiles as profiles
import community_service as service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)/'home'
        self.requests = []
        self.responses = []
        def transport(request):
            self.requests.append(request)
            value = self.responses.pop(0)
            if isinstance(value, BaseException): raise value
            return value
        self.service = service.Service(self.home, transport)

    def pack(self, kind='antimicrox'):
        path = Path(self.temp.name)/('test.amgp' if kind == 'antimicrox' else 'test.ini')
        path.write_bytes(b'<gamecontroller><sets/></gamecontroller>' if kind == 'antimicrox' else b'Techniques=CAS@CAS.fx\n[CAS.fx]\nSharpness=0.5\n')
        package, _ = profiles.Community(self.home).share(kind, path, 'Game', 'Title', 'Tester')
        return package, service.package_data(package)

    def login(self):
        self.responses.append({'token': 'ab'*32, 'expires': 9999999999})
        self.service.login('cd'*32)

    def test_key_only_goes_in_https_body_and_session_is_private(self):
        self.login(); request = self.requests[-1]
        self.assertEqual(request.full_url, service.API+'/v1/login')
        self.assertNotIn('cd'*32, request.full_url)
        self.assertEqual(json.loads(request.data), {'key': 'cd'*32})
        self.assertEqual(self.service.session.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('cd'*32, self.service.session.read_text())

    def test_submit_both_types_and_retry_reuses_identifier_with_receipt(self):
        for kind in ('antimicrox', 'reshade'):
            package, payload = self.pack(kind)
            before = package.read_bytes()
            for _ in range(2):
                self.responses.append({'id': payload['metadata']['id'], 'status': 'pending'})
                self.assertEqual(self.service.submit(package)['status'], 'pending')
                self.assertEqual(json.loads(self.requests[-1].data), payload)
                self.assertIsNone(self.requests[-1].get_header('Authorization'))
            self.assertEqual(package.read_bytes(), before)
            self.assertTrue(package.with_suffix('.receipt.json').exists())

    def test_submit_failure_keeps_package_without_claiming_success(self):
        package, _ = self.pack(); self.responses.append(TimeoutError())
        with self.assertRaisesRegex(ValueError, 'preserved'): self.service.submit(package)
        self.assertTrue(package.exists()); self.assertFalse(package.with_suffix('.receipt.json').exists())

    def test_review_checks_kind_hash_and_includes_full_profile(self):
        self.login(); _, payload = self.pack()
        self.responses.append(payload)
        metadata, data = self.service.review('antimicrox', payload['metadata']['id'])
        self.assertEqual(hashlib.sha256(data).hexdigest(), metadata['sha256'])
        self.responses.append(payload)
        with self.assertRaisesRegex(ValueError, 'Unexpected'): self.service.review('reshade', metadata['id'])
        self.responses.append(dict(payload, profile='modified'))
        with self.assertRaisesRegex(ValueError, 'payload'): self.service.review('antimicrox', metadata['id'])

    def test_decision_rechecks_review_checksum_before_post(self):
        self.login(); _, payload = self.pack(); m = payload['metadata']
        self.responses.append(payload)
        with self.assertRaisesRegex(ValueError, 'changed'): self.service.decide('antimicrox', m['id'], 'approve', '0'*64)
        self.responses.extend([payload, {'status': 'approved'}])
        self.assertEqual(self.service.decide('antimicrox', m['id'], 'approve', m['sha256'])['status'], 'approved')
        self.assertEqual(self.requests[-1].full_url, service.API+'/v1/submissions/'+m['id']+'/approve')
        self.assertEqual(self.requests[-1].get_header('Authorization'), 'Bearer '+'ab'*32)

    def test_expired_login_or_wrong_service_does_not_send_bearer(self):
        self.login(); value = json.loads(self.service.session.read_text()); value['api'] = 'https://other.example'
        self.service.session.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'expired'): self.service.pending('antimicrox')
        self.assertFalse(self.service.session.exists()); self.assertEqual(len(self.requests), 1)

    def test_logout_removes_local_session_even_if_server_fails(self):
        self.login(); self.responses.append(OSError('offline'))
        with self.assertRaises(OSError): self.service.logout()
        self.assertFalse(self.service.session.exists())

    def test_redirects_never_forward_credentials(self):
        with self.assertRaisesRegex(ValueError, 'redirects'): service.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example')

    def test_custom_api_requires_https_and_custom_repo_requires_explicit_api(self):
        config = self.home/'config/community-source.json'; config.parent.mkdir(parents=True)
        for value in ({'api': 'http://localhost'}, {'api': 'https://user:password@example.com'}, {'api': 'https://example.com/path'}, {'repository': 'Other/Catalogue'}):
            config.write_text(json.dumps(value))
            with self.assertRaises(ValueError): service.Service(self.home)

    def test_sharing_ui_submits_created_package_and_retains_detected_game(self):
        script = r'''
set -u
WT_HOME="$TEST_HOME"; WT_LANGUAGE=fr
source "$ROOT/toolbox/modules/community.sh"
amx_profile_file() { echo /userdata/profiles/Game.amgp; }
community_cmd() { case "$1" in suggest-game) echo 'Detected Game';; share) printf '/userdata/package.zip\nhttps://example.com\n';; esac; }
community_service_cmd() { printf '%s\n' "$@" > "$WT_HOME/sent"; printf 'my-id\npending\n'; }
menu_select() { echo use; }
input_text() { if [ "$2" = 'Votre pseudo public' ]; then echo Tester; else printf '%s' "$3"; fi; }
yesno() { return 0; }
community_report() { :; }; msgbox() { :; }; i18n() { echo Back; }
community_share antimicrox Community
'''
        self.home.mkdir(parents=True)
        r = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(self.home)), timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.home/'sent').read_text().splitlines(), ['submit', '/userdata/package.zip'])

    def test_validator_ui_hides_secret_and_logs_out_after_review(self):
        script = r'''
set -u
WT_HOME="$TEST_HOME"; WT_LANGUAGE=fr
source "$ROOT/toolbox/modules/community.sh"
have_dialog() { return 1; }
community_service_cmd() {
 printf '%s\n' "$1" >> "$WT_HOME/calls"
 case "$1" in login) IFS= read -r key; [ "$key" = "$TEST_KEY" ];; pending) :;; esac
}
msgbox() { :; }
community_validate antimicrox Community
'''
        self.home.mkdir(parents=True); key = 'cd'*32
        r = subprocess.run(['bash', '-x', '-c', script], input=key+'\n', capture_output=True, text=True, env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(self.home), TEST_KEY=key), timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(key, r.stdout+r.stderr)
        self.assertEqual((self.home/'calls').read_text().splitlines(), ['login', 'pending', 'logout'])


if __name__ == '__main__': unittest.main()
