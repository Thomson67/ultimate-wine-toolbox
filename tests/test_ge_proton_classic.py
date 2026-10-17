"""Classic GE-Proton listing and archive layout without network or Batocera paths."""
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GEProtonClassicTests(unittest.TestCase):
    def run_shell(self, base, code, language='fr'):
        prefix = '''WT_HOME="$TEST_HOME"
WT_ROOT="$ROOT/toolbox"
BATOCERA_CUSTOM_WINE="$TEST_HOME/runners"
source "$WT_ROOT/lang/$WT_LANGUAGE.sh"
source "$WT_ROOT/modules/runners.sh"
source "$WT_ROOT/modules/ge-proton-legacy.sh"
i18n() { local key="$1"; shift; printf "${I18N[$key]:-$key}" "$@"; }
msgbox() { printf '%s\\n' "$2" >> "$WT_HOME/messages"; }
'''
        return subprocess.run(['bash', '-c', prefix + code], capture_output=True, text=True, timeout=8,
            env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(base), WT_LANGUAGE=language))

    def test_list_keeps_ge_11_and_older_but_excludes_unpublished_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            releases=[]
            for tag, extra in [('GE-Proton11-7', {}), ('GE-Proton10-25', {}),
                               ('GE-Proton11-8', {'draft': True}), ('GE-Proton11-9', {'prerelease': True})]:
                name=tag+'.tar.gz'
                releases.append(dict(tag_name=tag, assets=[dict(name=name, browser_download_url='https://example.test/'+name, size=100)], **extra))
            (base/'releases').write_text('\n'.join(json.dumps(item) for item in releases))
            result=self.run_shell(base, '''runner_fetch_all_releases() { cp "$WT_HOME/releases" "$2"; }
runner_release_rows_ge
''')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual([line.split('\t')[0] for line in result.stdout.splitlines()], ['GE-Proton11-7','GE-Proton10-25'])

    def test_x86_archives_and_matching_checksums_for_legacy_and_current_names(self):
        # Official 11-1/11-3 have ARM first and an unsuffixed x86_64 archive;
        # 11-4 onward explicitly names both architectures.
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); releases=[]
            cases=[('GE-Proton11-1',['GE-Proton11-1-aarch64.tar.gz','GE-Proton11-1.tar.gz']),
                   ('GE-Proton11-2',['GE-Proton11-2.tar.gz']),
                   ('GE-Proton11-3',['GE-Proton11-3-aarch64.tar.gz','GE-Proton11-3.tar.gz']),
                   ('GE-Proton11-4',['GE-Proton11-4-aarch64.tar.gz','GE-Proton11-4-x86_64.tar.gz']),
                   ('GE-Proton11-5',['GE-Proton11-5-aarch64.tar.gz','GE-Proton11-5-arm64.tar.gz']),
                   ('GE-Proton11-6',['GE-Proton11-6.tar.gz','GE-Proton11-6-x86_64.tar.gz'])]
            for tag, names in cases:
                assets=[]
                for name in names:
                    checksum=name.removesuffix('.tar.gz')+'.sha512sum'
                    for filename in (name,checksum):
                        assets.append(dict(name=filename,browser_download_url='https://example.test/'+filename,size=100))
                releases.append(dict(tag_name=tag,assets=assets))
            (base/'releases').write_text('\n'.join(json.dumps(item) for item in releases))
            for definition in ('base','classic'):
                with self.subTest(definition=definition):
                    code=('source "$WT_ROOT/modules/runners.sh"\n' if definition=='base' else '')+"""runner_fetch_all_releases() { cp "$WT_HOME/releases" "$2"; }
runner_release_rows_ge
"""
                    result=self.run_shell(base,code)
                    self.assertEqual(result.returncode,0,result.stderr)
                    rows={parts[0]:parts for parts in (line.split('\t') for line in result.stdout.splitlines())}
                    self.assertNotIn('GE-Proton11-5',rows)
                    for tag,expected in [('GE-Proton11-1','GE-Proton11-1.tar.gz'),('GE-Proton11-2','GE-Proton11-2.tar.gz'),
                                         ('GE-Proton11-3','GE-Proton11-3.tar.gz'),('GE-Proton11-4','GE-Proton11-4-x86_64.tar.gz'),
                                         ('GE-Proton11-6','GE-Proton11-6-x86_64.tar.gz')]:
                        self.assertEqual(rows[tag][1],expected)
                        self.assertEqual(rows[tag][4],'https://example.test/'+expected.removesuffix('.tar.gz')+'.sha512sum')

    def test_archive_suffixed_checksum_naming_is_also_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);tag='GE-Proton10-25';name=tag+'.tar.gz'
            (base/'releases').write_text(json.dumps(dict(tag_name=tag,assets=[
                dict(name=name,browser_download_url='archive',size=100),
                dict(name=name+'.sha512sum',browser_download_url='checksum')]))+'\n')
            result=self.run_shell(base,"""runner_fetch_all_releases() { cp "$WT_HOME/releases" "$2"; }
runner_release_rows_ge
""")
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip().split('\t')[4],'checksum')

    def test_version_note_only_marks_ge_11_in_both_languages(self):
        for language in ('fr','en'):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as folder:
                base=Path(folder)
                result=self.run_shell(base, r'''runner_release_rows_ge() {
 printf 'GE-Proton11-7\tGE-Proton11-7.tar.gz\thttps://example.test/11\t100\t\n'
 printf 'GE-Proton10-25\tGE-Proton10-25.tar.gz\thttps://example.test/10\t100\t\n'
}
menu_select() { printf '%s\0' "$@" > "$WT_HOME/menu"; echo 1; }
runner_choose_release ge-proton GE "$(i18n runner_ge_v44)"
''',language)
                self.assertEqual(result.returncode,0,result.stderr)
                fields=(base/'menu').read_bytes().decode().split('\0')
                self.assertIn('v44',fields[3]);self.assertNotIn('v44',fields[5])
                self.assertTrue(result.stdout.startswith('GE-Proton11-7\t'))

    def test_ge_11_archive_flattens_files_and_does_not_replace_existing_runner(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); source=base/'source/GE-Proton11-7'
            binary=source/'files/bin/wine';binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o755)
            (binary.parent/'wine64').symlink_to('wine')
            (source/'files/.hidden').write_text('retained')
            (source/'proton').write_text('launcher')
            with tarfile.open(base/'runner.tar.gz','w:gz') as archive: archive.add(source,arcname=source.name)
            result=self.run_shell(base, '''free_bytes_userdata() { echo 999999999999; }
download_file() { cp "$WT_HOME/runner.tar.gz" "$2"; }
runner_install_ge_archive GE GE-Proton11-7.tar.gz https://example.test/runner 100 '' || exit 1
runner_install_ge_archive GE GE-Proton11-7.tar.gz https://example.test/runner 100 '' && exit 2
exit 0
''')
            self.assertEqual(result.returncode,0,result.stderr)
            target=base/'runners/GE-Proton-11-7'
            self.assertTrue(os.access(target/'bin/wine',os.X_OK))
            self.assertEqual(os.readlink(target/'bin/wine64'),'wine')
            self.assertEqual((target/'.hidden').read_text(),'retained')
            self.assertEqual((target/'proton').read_text(),'launcher')
            self.assertFalse((target/'files').exists())
