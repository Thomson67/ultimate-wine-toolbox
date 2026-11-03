"""Verified per-entry update for ES builds rejecting /addgames XML imports."""
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET


MEDIA_SUFFIX = {'image': 'image', 'boxart': 'box', 'fanart': 'fanart',
                'marquee': 'marquee', 'thumbnail': 'thumb'}


def update_existing(request, detail_url, live, expected, entry, proposed, gamelist, equal):
    """Update live metadata, then persist only that verified XML entry.

    ES v43's JSON endpoint skips MD_PATH fields; its media endpoint updates
    those fields and writes a recovery entry. Do not assume HTTP 200 alone
    means that the live metadata changed.
    """
    ports = Path(gamelist).parent
    changes = {k: v for k, v in expected.items()
               if k not in MEDIA_SUFFIX and k != 'path' and live.get(k, '') != v}
    uploads = []
    for key, suffix in MEDIA_SUFFIX.items():
        value = expected[key]
        if equal(key, live.get(key, ''), value):
            continue
        source = Path(value) if os.path.isabs(value) else ports / value
        data = source.read_bytes()
        if data.startswith(b'\xff\xd8'):
            content_type, extension = 'image/jpeg', '.jpg'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            content_type, extension = 'image/png', '.png'
        elif data.startswith((b'GIF87a', b'GIF89a')):
            content_type, extension = 'image/gif', '.gif'
        else:
            raise RuntimeError(f'unsupported media format: {source}')
        # getSaveAsPath() in ES v43 uses ROM-stem + suffix in /images.
        # Never overwrite a different existing/custom image at that location.
        destination = ports / 'images' / (Path(live['path']).stem + '-' + suffix + extension)
        if destination.is_symlink() or (destination.exists() and destination.read_bytes() != data):
            raise RuntimeError(f'preserving conflicting existing media: {destination}')
        uploads.append((key, data, content_type))

    endpoint = detail_url.split('?', 1)[0]
    if changes:
        request(endpoint, json.dumps(changes).encode('utf-8'), 'application/json')
    for key, data, content_type in uploads:
        request(endpoint + '/media/' + urllib.parse.quote(key, safe=''), data, content_type)
    result = request(detail_url)
    if not isinstance(result, dict) or not equal('path', result.get('path', ''), live['path']):
        raise RuntimeError('per-entry ES update returned a different launcher')
    if result.get('systemName', live.get('systemName')) != live.get('systemName'):
        raise RuntimeError('per-entry ES update changed launcher ownership')
    uploaded = {key for key, _, _ in uploads}
    for key, value in expected.items():
        actual = result.get(key, '')
        if key in uploaded:
            # ES chooses its own filename. Verify its actual local bytes before
            # accepting that path, then use the path returned by ES in the XML.
            file = Path(actual) if os.path.isabs(actual) else ports / actual
            source_data = next(data for name, data, _ in uploads if name == key)
            if not actual or file.read_bytes() != source_data:
                raise RuntimeError(f'per-entry media verification failed: {key}')
            expected[key] = actual
        elif not equal(key, actual, value):
            raise RuntimeError(f'per-entry memory verification failed: {key}')

    # Keep the newest live statistics and other known metadata. API-only IDs
    # are identifiers of the HTTP route, not XML scraper IDs.
    for key, value in result.items():
        if key in ('id', 'systemName', 'path') or not isinstance(value, str):
            continue
        key = 'id' if key == 'scraperId' else key
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key):
            continue
        node = entry.find(key)
        if node is None:
            node = ET.SubElement(entry, key)
        node.text = value
    for key, value in expected.items():
        node = entry.find(key)
        if node is None:
            node = ET.SubElement(entry, key)
        node.text = value

    count = 0
    def replace(match):
        nonlocal count
        game = ET.fromstring(match.group(0))
        if not equal('path', game.findtext('path', ''), expected['path']):
            return match.group(0)
        count += 1
        return ET.tostring(entry, encoding='unicode').rstrip()
    # Read again after API calls: do not undo an ES write that occurred while
    # updating memory. If the launcher was absent on disk, use the proposed XML.
    current = Path(gamelist).read_text() if Path(gamelist).exists() else proposed
    pattern = r'<game(?:\s[^>]*)?>.*?</game>'
    text = re.sub(pattern, replace, current, flags=re.DOTALL)
    if count == 0:
        # Preserve other entries written by ES during the API calls. Append to
        # that current document rather than restoring the older proposed XML.
        root = ET.fromstring(current)
        close = re.search(r'</gameList\s*>', current)
        if root.tag != 'gameList' or close is None:
            raise RuntimeError('invalid current gamelist during per-entry update')
        text = current[:close.start()] + ET.tostring(entry, encoding='unicode') + current[close.start():]
        count = 1
    if count != 1:
        raise RuntimeError('expected one XML entry for verified per-entry update')
    ET.fromstring(text)
    fd, temporary = tempfile.mkstemp(prefix='.gamelist-scraper-', dir=ports)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(text)
        if Path(gamelist).exists():
            os.chmod(temporary, os.stat(gamelist).st_mode & 0o777)
        os.replace(temporary, gamelist)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('scraper-assets: per-entry API memory and media verified; XML saved', flush=True)
