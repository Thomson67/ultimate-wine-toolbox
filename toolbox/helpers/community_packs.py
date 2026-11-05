#!/usr/bin/env python3
"""Moderated ReShade ZIP sharing; never execute downloaded shader/add-on code."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from community_service import Service, ServiceError, NoRedirect
from community_profiles import atomic, dump, entry_label
import reshade_pack as pack

ZIP_LIMIT = 16 * 1024 * 1024
EXPANDED_LIMIT = 64 * 1024 * 1024


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'pack-[a-f0-9]{64}', value):
        raise ValueError('Invalid community pack identifier')
    return value


def inspect(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > ZIP_LIMIT:
        raise ValueError('Community ZIP limit: 16 MiB compressed / 64 MiB expanded')
    with zipfile.ZipFile(path) as z:
        if len(z.infolist()) > 4096 or z.getinfo('uwt-pack.json').file_size > 1024*1024:
            raise ValueError('Community pack manifest/member limit exceeded')
        if sum(i.file_size for i in z.infolist()) > EXPANDED_LIMIT:
            raise ValueError('Community pack exceeds 64 MiB expanded')
        if any(i.filename not in ('uwt-pack.json', 'README.txt') and i.file_size > pack.FILE_LIMIT for i in z.infolist()):
            raise ValueError('Community pack member too large')
        manifest = json.loads(z.read('uwt-pack.json'))
        if manifest.get('schema') != 1 or manifest.get('kind') != 'uwt-reshade-pack':
            raise ValueError('Export a portable UWT pack before submitting')
        files, meta = pack.archive(path)
        if (len(z.namelist()) != len(files)+2 or set(z.namelist()) != set(files) | {'uwt-pack.json', 'README.txt'}
                or set(manifest.get('files', {})) != set(files)):
            raise ValueError('Unexpected community pack members')
        for name, data in files.items():
            if hashlib.sha256(data).hexdigest() != manifest['files'][name]:
                raise ValueError('Community pack member checksum mismatch')
    for field in ('game', 'title', 'author', 'credits'):
        value = manifest.get(field)
        maximum = 160 if field != 'credits' else 4000
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid public pack '+field)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(manifest, id='pack-'+digest, sha256=digest, bytes=path.stat().st_size,
                presets=list(meta['presets']), addons=list(meta['addons']))


def summary(value):
    lines = [f'{k}: {value.get(k, "")}' for k in ('game', 'title', 'author', 'description', 'credits', 'release', 'arch', 'tested_on')]
    for k in ('presets', 'addons'):
        lines.append(k+': '+', '.join(value.get(k, [])))
    lines.append(f'ZIP: {value.get("bytes", 0)} bytes / SHA-256 {value["sha256"]}')
    return '\n'.join(lines)


class Packs(Service):
    def ensure_enabled(self):
        health = self.request('/health', timeout=15)
        if 'reshade-packs' not in health.get('capabilities', []):
            raise ValueError('Activez les packs dans le Worker communautaire (schema.sql, liaison R2 PACKS et nouveau worker.js) / Enable community packs in the Worker first')

    def binary(self, endpoint, data=None, authenticated=False):
        headers = {'User-Agent': 'Ultimate-Wine-Toolbox', 'Accept': 'application/zip'}
        if authenticated:
            saved = json.loads(self.session.read_text()) if self.session.exists() else {}
            if saved.get('api') != self.api or saved.get('expires', 0) <= time.time() or not re.fullmatch('[a-f0-9]{64}', saved.get('token', '')):
                raise ValueError('Validator session expired; reconnect')
            headers['Authorization'] = 'Bearer '+saved['token']
        if data is not None:
            headers['Content-Type'] = 'application/zip'
        request = urllib.request.Request(self.api+endpoint, data=data, headers=headers)
        try:
            if self.transport:
                return self.transport(request)
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=180) as response:
                raw = response.read((ZIP_LIMIT if data is None else 8192)+1)
            if len(raw) > (ZIP_LIMIT if data is None else 8192):
                raise ValueError('Community pack response too large')
            return raw if data is None else json.loads(raw)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.session.unlink(missing_ok=True)
            try: message = json.loads(error.read(2048)).get('error', '')
            except (ValueError, AttributeError): message = ''
            message = ''.join(c for c in str(message) if ord(c) >= 32 and ord(c) != 127)[:300]
            raise ServiceError(f'Community pack HTTP {error.code}: {message}', error.code) from None
        except (TimeoutError, urllib.error.URLError):
            raise ValueError('Community pack service unreachable; local ZIP preserved') from None

    def submit_pack(self, path):
        metadata = inspect(path)
        self.ensure_enabled()
        result = self.binary('/v1/packs/submissions', Path(path).read_bytes())
        if result.get('id') != metadata['id'] or result.get('status') not in ('pending', 'approved', 'rejected'):
            raise ValueError('Invalid community pack receipt')
        atomic(Path(path).with_suffix('.receipt.json'), dump(dict(result, api=self.api)))
        return result

    def listing(self, pending=False, query=''):
        self.ensure_enabled()
        result = self.request('/v1/packs/pending' if pending else '/v1/packs', authenticated=pending)
        rows = result.get('entries')
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError('Invalid community pack catalogue')
        for row in rows:
            identifier(row.get('id'))
            if row.get('sha256') != row['id'][5:]:
                raise ValueError('Invalid pack catalogue checksum')
            for key in ('game', 'title', 'author'):
                if not isinstance(row.get(key), str) or len(row[key]) > 160 or any(ord(c) < 32 for c in row[key]):
                    raise ValueError('Invalid community pack text')
        return [r for r in rows if query.casefold() in ' '.join(str(r.get(k, '')) for k in ('game', 'title', 'author')).casefold()]

    def metadata(self, ident, review=False):
        value = self.request('/v1/packs/'+identifier(ident), authenticated=review)
        metadata = value.get('metadata', {})
        if metadata.get('id') != ident or metadata.get('sha256') != ident[5:]:
            raise ValueError('Invalid community pack metadata')
        return metadata

    def fetch_pack(self, ident, review=False):
        ident = identifier(ident)
        metadata = self.metadata(ident, review)
        folder = self.home/'config/reshade-community-packs'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder/(ident+'.zip')
        # Moderation always downloads the server's current immutable bytes.
        if review or path.is_symlink() or not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != ident[5:]:
            data = self.binary('/v1/packs/'+ident+('/review-download' if review else '/download'), authenticated=review)
            if len(data) > ZIP_LIMIT or hashlib.sha256(data).hexdigest() != ident[5:]:
                raise ValueError('Community ZIP checksum mismatch')
            with tempfile.TemporaryDirectory(prefix='uwt-pack-review-') as directory:
                temporary = Path(directory)/'pack.zip'; temporary.write_bytes(data)
                checked = inspect(temporary)
                for k in ('game', 'title', 'author', 'credits', 'release'):
                    if checked.get(k, '') != metadata.get(k, ''):
                        raise ValueError('Community ZIP metadata mismatch')
            atomic(path, data)
        inspect(path)
        return path

    def decide(self, action, ident, expected):
        ident = identifier(ident)
        if action not in ('approve', 'reject', 'remove') or expected != ident[5:]:
            raise ValueError('Review the exact pack before deciding')
        if action == 'approve':
            self.fetch_pack(ident, review=True)
        result = self.request('/v1/packs/'+ident+'/'+action, {'sha256': expected}, authenticated=True)
        if result.get('id') != ident or result.get('status') != ('approved' if action == 'approve' else 'rejected'):
            raise ValueError('Invalid pack moderation response')
        return result['status']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('submit'); p.add_argument('path', type=Path)
    for action in ('list', 'pending'):
        p = sub.add_parser(action); p.add_argument('--query', default=''); p.add_argument('--with-game', action='store_true')
    for action in ('show', 'fetch', 'review'):
        p = sub.add_parser(action); p.add_argument('id')
    for action in ('approve', 'reject', 'remove'):
        p = sub.add_parser(action); p.add_argument('id'); p.add_argument('sha256')
    args = parser.parse_args(); service = Packs(args.home)
    if args.command == 'submit':
        value = service.submit_pack(args.path); print(value['id']); print(value['status'])
    elif args.command in ('list', 'pending'):
        for row in service.listing(args.command == 'pending', args.query):
            print(row['id']+'\t'+entry_label(row)+('\t'+row['game'] if args.with_game else ''))
    elif args.command == 'show': print(summary(service.metadata(args.id)))
    elif args.command == 'fetch': print(service.fetch_pack(args.id))
    elif args.command == 'review':
        path = service.fetch_pack(args.id, review=True)
        print(args.id[5:]); print(summary(inspect(path)))
        with zipfile.ZipFile(path) as z:
            print('\nFiles:\n'+'\n'.join(i.filename+' — '+str(i.file_size)+' bytes' for i in z.infolist()))
    else: print(service.decide(args.command, args.id, args.sha256))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error))
