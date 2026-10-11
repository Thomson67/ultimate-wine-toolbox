#!/usr/bin/env python3
"""Bounded PE import hints and optional PCGamingWiki lookup (no game execution)."""
import json
import re
import struct
import subprocess
from urllib.parse import urlencode

DLL_APIS = {'d3d9.dll': 'd3d9', 'd3d10.dll': 'dxgi', 'd3d10_1.dll': 'dxgi',
            'd3d11.dll': 'dxgi', 'd3d12.dll': 'dxgi', 'dxgi.dll': 'dxgi',
            'opengl32.dll': 'opengl32', 'vulkan-1.dll': 'vulkan',
            'd3d8.dll': 'legacy', 'ddraw.dll': 'legacy'}


def imported_dlls(data):
    try:
        if data[:2] != b'MZ':
            return []
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        if data[pe:pe+4] != b'PE\0\0':
            return []
        count = struct.unpack_from('<H', data, pe+6)[0]
        size = struct.unpack_from('<H', data, pe+20)[0]
        optional = pe+24
        magic = struct.unpack_from('<H', data, optional)[0]
        if magic not in (0x10b, 0x20b):
            return []
        directory = optional + (96 if magic == 0x10b else 112)
        sections = []
        for i in range(min(count, 96)):
            off = optional + size + i*40
            virtual_size, rva, raw_size, raw = struct.unpack_from('<IIII', data, off+8)
            sections.append((rva, max(virtual_size, raw_size), raw, raw_size))
        def offset(rva):
            for start, length, raw, raw_size in sections:
                if start <= rva < start+length and rva-start < raw_size:
                    off = raw + rva-start
                    return off if off < len(data) else None
            return rva if rva < min(len(data), optional+size) else None
        result = set()
        def name(rva):
            off = offset(rva)
            if off is not None:
                end = data.find(b'\0', off, min(len(data), off+256))
                if end >= 0:
                    result.add(data[off:end].decode('ascii', errors='ignore').lower())
        for index, stride in [(1, 20), (13, 32)]:
            table_rva = struct.unpack_from('<I', data, directory+index*8)[0]
            if not table_rva:
                continue
            off = offset(table_rva)
            if off is None:
                continue
            for i in range(512):
                entry = off+i*stride
                descriptor = data[entry:entry+stride]
                if len(descriptor) != stride or not any(descriptor):
                    break
                if index == 1:
                    name(struct.unpack_from('<I', descriptor, 12)[0])
                elif struct.unpack_from('<I', descriptor)[0] & 1:
                    name(struct.unpack_from('<I', descriptor, 4)[0])
        return sorted(result)
    except (struct.error, ValueError):
        return []


def detect(data):
    imports = imported_dlls(data)
    evidence = [dll for dll in imports if dll in DLL_APIS]
    kind = 'imports'
    if not evidence:
        # Dynamic loading often leaves DLL names outside the import table.
        # These are hints only: they do not establish the renderer used at launch.
        evidence = sorted(set(m.decode().lower() for m in re.findall(
            rb'(?i)(?<![a-z0-9_])(d3d9\.dll|d3d10(?:_1)?\.dll|d3d11\.dll|d3d12\.dll|dxgi\.dll|opengl32\.dll|vulkan-1\.dll|d3d8\.dll|ddraw\.dll)(?![a-z0-9_])', data)))
        kind = 'references'
    return sorted(set(DLL_APIS[d] for d in evidence)), kind, evidence


def wiki_request(parameters):
    url = 'https://www.pcgamingwiki.com/w/api.php?' + urlencode(dict(parameters, format='json'))
    result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '5', '--max-time', '12',
        '-A', 'UltimateWineToolbox/0.5 (https://github.com/Thomson67/ultimate-wine-toolbox)', url],
        capture_output=True, check=True)
    if len(result.stdout) > 4*1024*1024:
        raise ValueError('PCGamingWiki response too large')
    return json.loads(result.stdout)


def wiki_search(title):
    data = wiki_request(dict(action='query', list='search', srsearch=title, srnamespace=0, srlimit=8))
    return [r['title'] for r in data.get('query', {}).get('search', [])]


def wiki_apis(text):
    evidence = []
    candidates = set()
    for field, value in re.findall(r'\|\s*(direct3d versions|opengl versions|vulkan versions)\s*=\s*([^|\n}]+)', text, re.I):
        value = value.strip()
        if not value or value.lower() in ('unknown', 'n/a', 'none', 'false'):
            continue
        field = field.lower()
        if field == 'direct3d versions':
            versions = re.findall(r'\b(?:12|11|10(?:\.1)?|9(?:\.0[abc])?|8|7)\b', value)
            for version in versions:
                candidates.add('dxgi' if version.startswith(('10', '11', '12')) else 'd3d9' if version.startswith('9') else 'legacy')
            if versions:
                evidence.append('Direct3D: '+value)
        elif re.search(r'\d|true', value, re.I):
            candidates.add('opengl32' if field == 'opengl versions' else 'vulkan')
            evidence.append(('OpenGL: ' if field == 'opengl versions' else 'Vulkan: ')+value)
    return sorted(candidates), evidence


def wiki_page(title):
    data = wiki_request(dict(action='parse', page=title, prop='wikitext', redirects=1))
    text = data.get('parse', {}).get('wikitext', {}).get('*', '')
    return wiki_apis(text)
