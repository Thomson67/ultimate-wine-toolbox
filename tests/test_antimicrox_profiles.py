import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
from antimicrox_profiles import Profiles, report, key_name

PROFILE = '''<gamecontroller><names><buttonname index="1">Saut</buttonname></names><sets>
<set index="1"><name>Normal</name>
<button index="1"><slots><slot><code>0x20</code><mode>keyboard</mode></slot></slots></button>
<button index="2"><slots><slot><code>0x1000021</code><mode>keyboard</mode></slot><slot><code>0x43</code><mode>keyboard</mode></slot></slots></button>
<stick index="1"><stickbutton index="1"><slots><slot><code>0x57</code><mode>keyboard</mode></slot></slots></stickbutton></stick>
<axis index="3"><axisbutton index="2"><slots><slot><code>3</code><mode>mousebutton</mode></slot></slots></axisbutton></axis>
<dpad index="1"><dpadbutton index="8"><slots><slot><code>3</code><mode>mousemovement</mode></slot></slots></dpadbutton></dpad>
<button index="3"><slots><slot><slots><slot><code>0x1000023</code><mode>keyboard</mode></slot><slot><code>0x1000030</code><mode>keyboard</mode></slot></slots><mode>mix</mode></slot></slots></button>
</set><set index="2"><button index="4"><setselect>3</setselect><setselectcondition>while-held</setselectcondition></button>
<button index="5"><slots><slot><code>300</code><mode>pause</mode></slot><slot><text>hello</text><mode>textentry</mode></slot><slot><code>17</code><mode>future</mode></slot></slots></button>
</set></sets></gamecontroller>'''


class ProfileTests(unittest.TestCase):
    def fixture(self, folder):
        userdata = Path(folder)/'userdata'; home = userdata/'system/toolbox'
        (home/'config/antimicrox-profiles').mkdir(parents=True)
        profile = home/'config/antimicrox-profiles/Game [GE].amgp'
        profile.write_text(PROFILE)
        cfg = home/'config/antimicrox-games.tsv'
        cfg.write_text(f'/games/First [GE].wine\t{profile}\n/games/Second.wsquashfs\t{profile}\n/games/Other.wine\t{userdata}/other.amgp\n')
        return Profiles(home, userdata, active=lambda: False), profile, cfg

    def test_report_covers_all_sets_inputs_combos_and_advanced_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            _, profile, _ = self.fixture(folder)
            result = report(profile)
            for expected in ['A / Croix [bouton 1] (Saut) : Espace', 'B / Rond [bouton 2] : Ctrl + C',
                             'Stick gauche (LS) ↑ : W', 'Axe 3 + : clic droit', 'Croix directionnelle ← : Souris ←',
                             '(Alt + F1)', 'Ensemble 2', 'setselect=3', 'Pause 300 ms',
                             'Texte : "hello"', 'future [code=17]']:
                self.assertIn(expected, result)
            self.assertTrue(all(len(line) <= 88 for line in result.splitlines()))
            self.assertIn('A / Cross [button 1] (Saut) : Space', report(profile, 'en'))
            self.assertEqual(key_name('0x60000100'), 'Key code 0x60000100')

    def test_delete_removes_shared_references_but_keeps_other_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, cfg = self.fixture(folder)
            unrelated = service.userdata/'other.amgp'; unrelated.write_text('<joystick/>')
            alias = service.userdata/'alias.amgp'; alias.symlink_to(profile)
            with cfg.open('a') as stream:
                stream.write(f'/games/Alias.wine\t{alias}\n')
            token = service.plan(profile)[-1]
            self.assertEqual(len(service.delete(profile, token)), 3)
            self.assertFalse(profile.exists())
            self.assertTrue(unrelated.is_file())
            self.assertEqual(cfg.read_text(), f'/games/Other.wine\t{unrelated}\n')

    def test_changed_assignments_or_profile_refuse_old_confirmation(self):
        for change in ('cfg', 'profile'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                service, profile, cfg = self.fixture(folder)
                token = service.plan(profile)[-1]
                target = cfg if change == 'cfg' else profile
                with target.open('a') as stream: stream.write('\n')
                before = cfg.read_bytes()
                with self.assertRaisesRegex(ValueError, 'changed'):
                    service.delete(profile, token)
                self.assertTrue(profile.exists())
                self.assertEqual(cfg.read_bytes(), before)

    def test_running_mapper_blocks_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, cfg = self.fixture(folder)
            token, before = service.plan(profile)[-1], cfg.read_bytes()
            service.active = lambda: True
            with self.assertRaisesRegex(ValueError, 'Close'):
                service.delete(profile, token)
            self.assertTrue(profile.exists())
            self.assertEqual(cfg.read_bytes(), before)

    def test_failed_tsv_write_restores_file_and_assignments(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, cfg = self.fixture(folder)
            token, before = service.plan(profile)[-1], cfg.read_bytes()
            with patch('antimicrox_profiles.atomic', side_effect=OSError('write failed')):
                with self.assertRaises(OSError): service.delete(profile, token)
            self.assertTrue(profile.exists())
            self.assertEqual(cfg.read_bytes(), before)
            self.assertEqual(list(profile.parent.glob('.uwt-amx-delete-*')), [])

    def test_failed_restore_keeps_staged_profile_recoverable(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, cfg = self.fixture(folder)
            token, before = service.plan(profile)[-1], cfg.read_bytes()
            replace = os.replace
            def fail_restore(source, destination):
                if Path(source).parent.name.startswith('.uwt-amx-delete-'):
                    raise OSError('restore failed')
                return replace(source, destination)
            with patch('antimicrox_profiles.atomic', side_effect=OSError('write failed')), \
                 patch('antimicrox_profiles.os.replace', side_effect=fail_restore):
                with self.assertRaises(OSError): service.delete(profile, token)
            staged = list(profile.parent.glob('.uwt-amx-delete-*/*.amgp'))
            self.assertEqual(len(staged), 1)
            self.assertEqual(staged[0].read_text(), PROFILE)
            self.assertEqual(cfg.read_bytes(), before)

    def test_reporting_execute_slot_only_displays_command(self):
        with tempfile.TemporaryDirectory() as folder:
            _, profile, _ = self.fixture(folder)
            profile.write_text('''<joystick><sets><set index="1"><button index="1"><slots>
<slot><path>/never/run</path><arguments>--test</arguments><mode>execute</mode></slot>
</slots></button></set></sets></joystick>''')
            with patch('antimicrox_profiles.subprocess.run', side_effect=AssertionError('must not execute')):
                self.assertIn('/never/run --test', report(profile))

    def test_standard_controller_button_labels_follow_sdl_not_raw_pad_order(self):
        with tempfile.TemporaryDirectory() as folder:
            _, profile, _ = self.fixture(folder)
            controls = ''.join(f'<button index="{index}"><slots><slot><code>0x41</code><mode>keyboard</mode></slot></slots></button>' for index in range(1, 23))
            profile.write_text('<gamecontroller><sets><set index="1">'+controls+'</set></sets></gamecontroller>')
            text = report(profile)
            for name, index in [('A / Croix', 1), ('B / Rond', 2), ('X / Carré', 3),
                                ('Y / Triangle', 4), ('Xbox / PS', 6), ('Menu / Options', 7),
                                ('Clic LS / L3', 8), ('Clic RS / R3', 9),
                                ('LB / L1', 10), ('RB / R1', 11), ('D-pad ↑', 12),
                                ('Pavé tactile (clic, PS)', 21)]:
                self.assertIn(f'{name} [bouton {index}] : A', text)
            self.assertIn('Bouton 22 : A', text)

    def test_stick_direction_numbers_differ_from_dpad_and_triggers_have_aliases(self):
        with tempfile.TemporaryDirectory() as folder:
            _, profile, _ = self.fixture(folder)
            def direction(tag, index):
                return f'<{tag} index="{index}"><slots><slot><code>0x41</code><mode>keyboard</mode></slot></slots></{tag}>'
            profile.write_text('<gamecontroller><sets><set index="1">'+
                '<stick index="1">'+''.join(direction('stickbutton', n) for n in (1, 3, 5, 7))+'</stick>'+
                '<stick index="2">'+direction('stickbutton', 2)+'</stick>'+
                '<dpad index="1">'+direction('dpadbutton', 3)+'</dpad>'+
                ''.join(f'<trigger index="{n}">'+direction('triggerbutton', 2)+'</trigger>' for n in (1, 2, 5, 6))+
                '</set></sets></gamecontroller>')
            text = report(profile)
            for arrow in ('↑', '→', '↓', '←'):
                self.assertIn(f'Stick gauche (LS) {arrow} : A', text)
            self.assertIn('Stick droit (RS) ↗ : A', text)
            self.assertIn('Croix directionnelle ↗ : A', text)
            self.assertEqual(text.count('LT / L2 + : A'), 2)
            self.assertEqual(text.count('RT / R2 + : A'), 2)

    def test_raw_joystick_profiles_keep_numbers_without_guessing_console_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            _, profile, _ = self.fixture(folder)
            profile.write_text(PROFILE.replace('gamecontroller', 'joystick'))
            text = report(profile)
            self.assertIn('Bouton 1 (Saut) : Espace', text)
            self.assertNotIn('A / Croix', text)
            self.assertIn('Stick 1 ↑ : W', text)

    def test_profile_list_includes_unassigned_and_external_assigned_files(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, _ = self.fixture(folder)
            external = service.userdata/'other.amgp'; external.write_text('<joystick/>')
            orphan = profile.parent/'Unassigned.amgp'; orphan.write_text('<joystick/>')
            self.assertEqual(set(service.list()), {profile, external, orphan})
            outside = Path(folder)/'outside.amgp'; outside.write_text('<joystick/>')
            link = profile.parent/'link.amgp'; link.symlink_to(outside)
            with self.assertRaises(ValueError): service.validate(link)
            with self.assertRaises(ValueError): service.validate(outside)

    def test_yad_starts_in_managed_directory_and_preselects_existing_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, _ = self.fixture(folder)
            commands = Path(folder)/'bin'; commands.mkdir()
            yad = commands/'yad'
            yad.write_text('#!/bin/sh\n[ "$1" = --file ] || exit 255\nprintf "%s\\n" "$@" > "$WT_HOME/yad-args"\n')
            yad.chmod(0o755)
            env = dict(os.environ, WT_HOME=str(service.home), WT_LANGUAGE='fr',
                       PATH=str(commands)+os.pathsep+os.environ['PATH'], PROFILE=str(profile))
            module = ROOT/'toolbox/modules/antimicrox.sh'
            for value, expected in [('', str(profile.parent)+'/'), ('"$PROFILE"', str(profile))]:
                command = f'source "{module}"\namx_browse_profile {value}'
                result = subprocess.run(['bash', '-c', command], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--filename='+expected, (service.home/'yad-args').read_text())
