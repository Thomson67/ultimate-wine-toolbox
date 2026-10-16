"""HTTPS submission and moderation client. Credentials never enter CLI arguments."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from community_profiles import Community, KINDS, LIMIT, atomic, details, dump, entry, profile_bytes

API = 'https://uwt-community-api.roeckel.workers.dev'
PROFILE_LIMIT = 64*1024


class ServiceError(ValueError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Community service redirects are forbidden')


def package_data(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 3 or len(set(names)) != 3 or any(info.file_size > LIMIT for info in archive.infolist()):
            raise ValueError('Invalid submission archive')
        metadata = entry(json.loads(archive.read('metadata.json')))
        filename = 'profile'+KINDS[metadata['kind']]
        if set(names) != {'metadata.json', filename, 'submission.txt'}: raise ValueError('Unexpected archive members')
        data = archive.read(filename)
    if len(data) > PROFILE_LIMIT: raise ValueError('Direct sharing accepts profiles up to 64 KiB')
    if hashlib.sha256(data).hexdigest() != metadata['sha256']: raise ValueError('Submission checksum mismatch')
    profile_bytes(metadata['kind'], data)
    return {'metadata': metadata, 'profile': data.decode('utf-8')}


class Service:
    def __init__(self, home, transport=None):
        self.home = Path(home)
        self.session = self.home/'state/community/validator-session.json'
        self.device = self.home/'state/community/validator-device.json'
        self.transport = transport
        config = self.home/'config/community-source.json'
        settings = json.loads(config.read_text()) if config.exists() else {}
        self.api = settings.get('api', API).rstrip('/')
        url = urllib.parse.urlsplit(self.api)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise ValueError('Community API must be an HTTPS origin')
        # A custom catalogue must explicitly name its own submission service.
        if settings.get('repository', Community(self.home).repository) != 'Thomson67/ultimate-wine-toolbox-community' and 'api' not in settings:
            raise ValueError('Configure a community API for this custom catalogue')

    def request(self, path, payload=None, authenticated=False, timeout=90):
        headers = {'User-Agent': 'Ultimate-Wine-Toolbox', 'Accept': 'application/json'}
        if authenticated:
            saved = json.loads(self.session.read_text()) if self.session.exists() else {}
            if saved.get('api') != self.api or saved.get('expires', 0) <= time.time():
                self.session.unlink(missing_ok=True)
                raise ValueError('Validator session expired; log in again')
            token = saved.get('token', '')
            if not re.fullmatch('[a-f0-9]{64}', token): raise ValueError('Invalid validator session')
            headers['Authorization'] = 'Bearer '+token
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        if data is not None: headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.api+path, data=data, headers=headers)
        try:
            if self.transport: return self.transport(request)
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                result = response.read(2*LIMIT+1)
            if len(result) > 2*LIMIT: raise ValueError('Community response too large')
            return json.loads(result)
        except urllib.error.HTTPError as error:
            if error.code == 401: self.session.unlink(missing_ok=True)
            try: message = json.loads(error.read(2048)).get('error', '')
            except (ValueError, AttributeError): message = ''
            message = ''.join(c for c in str(message) if ord(c) >= 32 and ord(c) != 127)[:300]
            raise ServiceError(f'Community HTTP {error.code}: {message or "service unavailable"}', error.code) from None
        except (TimeoutError, urllib.error.URLError):
            raise ValueError('Community service unreachable; your local sharing package is preserved') from None

    def login(self, key):
        if not re.fullmatch('[a-f0-9]{64}', key): raise ValueError('Enter the generated 64-character validator key')
        result = self.request('/v1/login', {'key': key})
        self.save_session(result)

    def save_session(self, result):
        if not re.fullmatch('[a-f0-9]{64}', result.get('token', '')) or not isinstance(result.get('expires'), int):
            raise ValueError('Invalid login response')
        atomic(self.session, dump(dict(result, api=self.api)))
        os.chmod(self.session, 0o600)

    def remembered_login(self):
        if not self.device.exists(): return False
        saved = json.loads(self.device.read_text())
        if saved.get('api') != self.api or saved.get('expires', 0) <= time.time() or not re.fullmatch('[a-f0-9]{64}', saved.get('token', '')):
            self.device.unlink(missing_ok=True)
            return False
        try:
            result = self.request('/v1/device/login', {'secret': saved['token']}, timeout=10)
        except ServiceError as error:
            if error.status != 401: raise
            self.device.unlink(missing_ok=True)
            return False
        self.save_session(result)
        return True

    def connect(self, language='fr', display=None, sleep=time.sleep, clock=time.monotonic):
        if self.remembered_login(): return
        secret = secrets.token_hex(32)
        name = ''.join(c for c in socket.gethostname() if c.isalnum() or c in ' ._-')[:80] or 'Batocera'
        start = self.request('/v1/pair/start', {'secret': secret, 'name': name}, timeout=10)
        if not re.fullmatch('[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}', start.get('code', '')) or not isinstance(start.get('expires'), int):
            raise ValueError('Invalid pairing response; update the Cloudflare Worker')
        remaining = min(300, start['expires']-int(time.time()))
        if remaining <= 0: raise ValueError('Pairing has expired; check the Batocera clock')
        deadline = clock()+remaining
        ui = None; completed = False
        try:
            ui = (display or show_pairing)(start['code'], self.api+'/pair', language)
            while clock() < deadline:
                if ui.poll() is not None: raise ValueError('Pairing cancelled')
                result = self.request('/v1/pair/poll', {'secret': secret}, timeout=10)
                if result.get('status') == 'approved':
                    if not isinstance(result.get('remember'), bool) or not isinstance(result.get('expires'), int) or result['expires'] <= time.time():
                        raise ValueError('Invalid pairing approval')
                    if result['remember']:
                        # Persist the grant before asking for a temporary session, so an
                        # interrupted response can be recovered on the next connection.
                        atomic(self.device, dump({'token': secret, 'expires': result['expires'], 'api': self.api}))
                        os.chmod(self.device, 0o600)
                        completed = True
                        if not self.remembered_login(): raise ValueError('Device access was revoked; reconnect')
                    else:
                        self.save_session({'token': secret, 'expires': result['expires']})
                        completed = True
                    return
                if result.get('status') != 'pending': raise ValueError('Invalid pairing status')
                sleep(5)
            raise ValueError('Pairing expired; start a new connection')
        finally:
            if ui is not None: ui.close()
            if not completed:
                try: self.request('/v1/pair/cancel', {'secret': secret}, timeout=10)
                except (OSError, ValueError): pass

    def forget(self):
        try:
            if self.device.exists():
                saved = json.loads(self.device.read_text())
                if saved.get('api') == self.api and re.fullmatch('[a-f0-9]{64}', saved.get('token', '')):
                    self.request('/v1/device/forget', {'secret': saved['token']}, timeout=10)
        finally:
            self.device.unlink(missing_ok=True)
            self.logout()

    def logout(self):
        try:
            if self.session.exists(): self.request('/v1/logout', {}, authenticated=True)
        finally: self.session.unlink(missing_ok=True)

    def submit(self, package):
        payload = package_data(package)
        result = self.request('/v1/submissions', payload)
        if result.get('id') != payload['metadata']['id'] or result.get('status') not in ('pending','publishing','approved','rejected'):
            raise ValueError('Invalid submission response')
        receipt = Path(package).with_suffix('.receipt.json')
        atomic(receipt, dump(dict(result, api=self.api)))
        return result

    def pending(self, kind):
        result = self.request('/v1/pending?'+urllib.parse.urlencode({'kind': kind}), authenticated=True)
        values = result.get('entries')
        if not isinstance(values, list) or len(values) > 200: raise ValueError('Invalid review queue')
        values = [entry(value) for value in values]
        if any(value['kind'] != kind for value in values): raise ValueError('Unexpected profile type')
        return values

    def review(self, kind, identifier):
        if not re.fullmatch('[a-z0-9][a-z0-9-]{0,79}', identifier): raise ValueError('Invalid contribution identifier')
        value = self.request('/v1/submissions/'+identifier, authenticated=True)
        metadata = entry(value['metadata'])
        if metadata['id'] != identifier or metadata['kind'] != kind: raise ValueError('Unexpected contribution')
        data = value['profile'].encode('utf-8')
        if len(data) > PROFILE_LIMIT or hashlib.sha256(data).hexdigest() != metadata['sha256']: raise ValueError('Invalid review payload')
        profile_bytes(kind, data)
        return metadata, data

    def decide(self, kind, identifier, decision, expected_sha):
        # Re-read the private submission and its checksum before an explicit decision.
        metadata, _ = self.review(kind, identifier)
        if metadata['sha256'] != expected_sha: raise ValueError('Contribution changed; review it again')
        if decision not in ('approve', 'reject'): raise ValueError('Invalid decision')
        return self.request('/v1/submissions/'+identifier+'/'+decision, {}, authenticated=True)


class PairingDisplay:
    def __init__(self, process, tty):
        self.process, self.tty = process, tty

    def poll(self):
        return self.process.poll() if self.process else None

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=2)
        self.tty.close()


def show_pairing(code, url, language):
    fr = language == 'fr'
    message = (f"Sur votre PC ou téléphone, ouvrez :\n\n{url}\n\nCode : {code}\n\nCollez votre clé validateur sur cette page, vérifiez le code et autorisez cet appareil.\n\nLa Toolbox continuera automatiquement. Code valable 5 minutes.\nVous pouvez choisir de mémoriser cet appareil pendant 30 jours sur la page." if fr else
               f"On your PC or phone, open:\n\n{url}\n\nCode: {code}\n\nPaste your validator key on that page, check the code and authorize this device.\n\nThe Toolbox will continue automatically. Code valid for 5 minutes.\nYou can choose to remember this device for 30 days on the page.")
    tty = open('/dev/tty', 'r+')
    try:
        if shutil.which('dialog'):
            process = subprocess.Popen(['dialog', '--no-shadow', '--title', 'UWT — '+('Appairage validateur' if fr else 'Validator pairing'),
                                        '--ok-label', 'Annuler' if fr else 'Cancel', '--msgbox', message, '22', '96'], stdin=tty, stdout=tty, stderr=tty)
        else:
            tty.write(message+'\nCtrl+C : '+('annuler' if fr else 'cancel')+'\n'); tty.flush(); process = None
        return PairingDisplay(process, tty)
    except BaseException:
        tty.close(); raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', default='/userdata/system/ultimate-wine-toolbox')
    parser.add_argument('--language', default='fr')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('login'); sub.add_parser('logout'); sub.add_parser('connect'); sub.add_parser('forget')
    arg = sub.add_parser('submit'); arg.add_argument('package')
    for action in ('pending', 'review', 'approve', 'reject'):
        arg = sub.add_parser(action); arg.add_argument('kind', choices=KINDS)
        if action != 'pending': arg.add_argument('identifier')
        if action in ('approve', 'reject'): arg.add_argument('checksum')
    args = parser.parse_args(); service = Service(args.home)
    if args.command == 'login': service.login(sys.stdin.readline(256).strip())
    elif args.command == 'logout': service.logout()
    elif args.command == 'connect': service.connect(args.language)
    elif args.command == 'forget': service.forget()
    elif args.command == 'submit':
        result = service.submit(args.package); print(result['id']+'\n'+result['status'])
    elif args.command == 'pending':
        for item in service.pending(args.kind): print(item['id']+'\t'+item['game']+' — '+item['title']+' — '+item['author'])
    elif args.command == 'review':
        metadata, data = service.review(args.kind, args.identifier)
        print(metadata['sha256']); print(details(metadata, args.language == 'fr'))
        print('\n'+('Pseudo déclaré, identité non vérifiée.' if args.language == 'fr' else 'Self-declared nickname; identity is unverified.'))
        if args.kind == 'antimicrox':
            from antimicrox_profiles import report
            with tempfile.TemporaryDirectory(prefix='uwt-review-') as directory:
                path = Path(directory)/'profile.amgp'; path.write_bytes(data)
                print(report(path, args.language))
        else: print('\n'+data.decode('utf-8-sig'))
    else:
        result = service.decide(args.kind, args.identifier, args.command, args.checksum)
        print(result['status'])


if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt:
        raise SystemExit('Pairing cancelled')
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error))
