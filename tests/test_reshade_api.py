import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resh_api', ROOT / 'toolbox/helpers/reshade_api.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def imported_pe(names, delay=False):
    data = bytearray(4096)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 134, 1)
    struct.pack_into('<H', data, 148, 240)
    optional = 152
    struct.pack_into('<H', data, optional, 0x20b)
    struct.pack_into('<IIII', data, optional+240+8, 2048, 0x1000, 2048, 512)
    struct.pack_into('<II', data, optional+112+(13 if delay else 1)*8, 0x1020, 256)
    for n, name in enumerate(names):
        off = 544+n*(32 if delay else 20)
        if delay:
            struct.pack_into('<II', data, off, 1, 0x1200+n*64)
        else:
            struct.pack_into('<I', data, off+12, 0x1200+n*64)
        raw = 1024+n*64
        data[raw:raw+len(name)+1] = name.encode()+b'\0'
    return bytes(data)


class ReShadeApiTests(unittest.TestCase):
    def test_regular_and_delayed_imports_and_multiple_apis(self):
        for delayed in [False, True]:
            data = imported_pe(['D3D11.dll', 'd3d12.dll', 'opengl32.dll', 'kernel32.dll'], delayed)
            candidates, kind, evidence = a.detect(data)
            self.assertEqual(candidates, ['dxgi', 'opengl32'])
            self.assertEqual(kind, 'imports')
            self.assertEqual(evidence, ['d3d11.dll', 'd3d12.dll', 'opengl32.dll'])

    def test_dynamic_references_are_hints_and_unknown_never_defaults_to_dxgi(self):
        self.assertEqual(a.detect(b'game\0vulkan-1.dll\0'), (['vulkan'], 'references', ['vulkan-1.dll']))
        self.assertEqual(a.detect(b'no graphics evidence')[0], [])
        self.assertEqual(a.detect(b'fake_d3d11.dll_other')[0], [])
        self.assertEqual(a.detect(imported_pe(['d3d8.dll']))[0], ['legacy'])
        self.assertEqual(a.imported_dlls(b'MZ\0\0'), [])

    def test_pcgamingwiki_supported_apis_are_not_inferred_from_notes(self):
        text='''{{API
|direct3d versions = 9, 11, 12
|direct3d notes = d3d8.dll wrapper available
|opengl versions = unknown
|vulkan versions = 1.1
}}'''
        self.assertEqual(a.wiki_apis(text)[0], ['d3d9', 'dxgi', 'vulkan'])
        self.assertEqual(a.wiki_apis('|opengl versions = 4.5')[0], ['opengl32'])
        self.assertEqual(a.wiki_apis('|direct3d versions = unknown')[0], [])
        with patch.object(a, 'wiki_request', return_value={'query': {'search': [{'title': 'Game'}, {'title': 'Game remaster'}]}}):
            self.assertEqual(a.wiki_search('Game'), ['Game', 'Game remaster'])


if __name__ == '__main__':
    unittest.main()
