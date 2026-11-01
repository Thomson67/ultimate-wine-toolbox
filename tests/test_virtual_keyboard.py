"""Policy, controller state, conflict handling and owned OSK lifecycle tests."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import virtual_keyboard as policy
import virtual_keyboard_runtime as runtime
import antimicrox_live as live


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.rom = self.home/'Forza Horizon 2.wine'; self.rom.mkdir()
        self.settings = policy.Settings(self.home)

    def test_opt_in_precedence_and_reset_preserve_other_games(self):
        second = self.home/'Other.wsquashfs'
        self.assertFalse(self.settings.enabled(self.rom))
        self.settings.set('on', self.rom)
        self.assertTrue(self.settings.enabled(self.rom)); self.assertFalse(self.settings.enabled(second))
        self.settings.set('on'); self.settings.set('off', self.rom)
        self.assertFalse(self.settings.enabled(self.rom)); self.assertTrue(self.settings.enabled(second))
        self.settings.set('inherit', self.rom)
        self.assertTrue(self.settings.enabled(self.rom))
        self.settings.set('off')
        self.assertFalse(self.settings.enabled(self.rom))

    def test_invalid_config_or_paths_are_not_replaced(self):
        self.settings.path.parent.mkdir()
        original = b'{"global":"false","games":{}}'
        self.settings.path.write_bytes(original)
        with self.assertRaises(ValueError): self.settings.set('on')
        self.assertEqual(self.settings.path.read_bytes(), original)
        for bad in ('relative.wine', '/userdata/../bad.wine', '/userdata/game\nname.wine'):
            with self.assertRaises(ValueError): policy.rom_key(bad)

    def conflict(self):
        return policy.conflict(self.home, self.rom, self.home/'global.keys', self.home/'system.keys')

    def test_global_and_game_chords_are_checked_without_modification(self):
        path = self.home/'global.keys'
        for trigger in (['hotkey','select'], 'select', 'hotkey'):
            path.write_text(json.dumps({'actions_player1':[{'trigger':trigger,'target':['KEY_TAB']}]}))
            before = path.read_bytes()
            self.assertIn(str(path), self.conflict())
            self.assertEqual(path.read_bytes(),before)
        path.unlink()
        keys = self.rom/'padto.keys'
        keys.write_text('{"actions_player1":[{"trigger":["hotkey","start"],"target":["KEY_F4"]}]}')
        self.assertFalse(self.conflict())
        keys.write_text('{"actions_player1":[{"trigger":["hotkey","select"],"target":"existing-command"}]}')
        self.assertIn('padto.keys',self.conflict())

    def test_anti_microx_profiles_and_launcher_alternate_sets(self):
        profile = self.home/'profile.amgp'
        profile.write_text('<gamecontroller><sets><set index="2"><button index="5"><slots><slot><code>0x45</code></slot></slots></button></set></sets></gamecontroller>')
        (self.home/'config').mkdir()
        association = self.home/'config/antimicrox-games.tsv'
        association.write_text(f'{self.rom}\t{profile}\n')
        with patch('virtual_keyboard_antimicrox.active_modifiers', return_value=[6]):
            self.assertFalse(self.conflict())
        association.unlink()
        rules = self.home/'config/antimicrox-launchers'; rules.mkdir()
        rule = rules/(hashlib.sha256(str(self.rom).encode()).hexdigest()+'.json')
        rule.write_text(json.dumps({'rom':str(self.rom),'game_profile':str(profile)}))
        with patch('virtual_keyboard_antimicrox.active_modifiers', return_value=[6]):
            self.assertFalse(self.conflict())

    def test_live_editor_never_uses_select_reserved_by_keyboard(self):
        profile = self.home/'empty.amgp'
        profile.write_text('<gamecontroller><sets/></gamecontroller>')
        self.settings.set('on',self.rom)
        with patch.object(live,'hotkey_choices',return_value=[]):
            action,_,_ = live.switch_for(profile,self.home,(),self.rom)
            self.assertEqual(action['trigger'],['hotkey','pagedown'])
            action,_,_ = live.switch_for(profile,self.home,[{'trigger':['hotkey','pagedown'],'target':['KEY_TAB']}],self.rom)
            self.assertIsNone(action)
            self.settings.set('off',self.rom)
            action,_,_ = live.switch_for(profile,self.home,[{'trigger':['hotkey','pagedown'],'target':['KEY_TAB']}],self.rom)
            self.assertEqual(action['trigger'],['hotkey','select'])

    def test_stale_pid_and_other_rom_stop_never_signal_processes(self):
        state = self.home/'state/virtual-keyboard'; state.mkdir(parents=True)
        path = state/'session.json'
        path.write_text(json.dumps({'rom':str(self.rom),'pid':123,'token':'old-boot:123'}))
        with patch.object(policy,'process_identity',return_value='new-boot:123'),patch.object(policy.os,'kill') as kill:
            policy.stop(self.home,str(self.home/'different.wine'))
            self.assertTrue(path.exists())
            policy.stop(self.home,str(self.rom)); kill.assert_not_called()
        self.assertFalse(path.exists())

    def test_detached_spawn_closes_inherited_fds_and_records_owner(self):
        self.settings.set('on',self.rom)
        with patch.object(policy,'conflict',return_value=''),patch.object(policy,'stop'),patch.object(policy,'process_identity',return_value='boot:45'),patch.object(policy.subprocess,'Popen') as spawn:
            spawn.return_value.pid=123
            policy.start(self.home,self.rom,self.home/'log')
            self.assertTrue(spawn.call_args.kwargs['close_fds'])
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertIs(spawn.call_args.kwargs['stdin'],subprocess.DEVNULL)
            data=json.loads((self.home/'state/virtual-keyboard/session.json').read_text())
            self.assertEqual(data,{'pid':123,'token':'boot:45','rom':str(self.rom)})

    def test_disabled_start_does_not_spawn_or_touch_game(self):
        with patch.object(policy.subprocess,'Popen') as spawn:
            policy.start(self.home,self.rom,self.home/'log'); spawn.assert_not_called()
        self.assertFalse((self.home/'state').exists())
        self.assertEqual(list(self.rom.iterdir()),[])


class FakeDevice:
    def __init__(self):
        self.keys=set(); self.events=[]; self.grabbed=False; self.closed=False
    def active_keys(self): return self.keys
    def absinfo(self,code): return types.SimpleNamespace(min=-32768,max=32767,value=0)
    def read(self):
        # evdev.read is a generator: empty reads may raise during iteration.
        if not self.events: raise BlockingIOError()
        events,self.events=self.events,[]
        yield from events
    def grab(self): self.grabbed=True
    def ungrab(self): self.grabbed=False
    def close(self): self.closed=True
    def event(self,code,value,kind=1):
        if kind==1:
            if value:self.keys.add(code)
            else:self.keys.discard(code)
        self.events.append(types.SimpleNamespace(type=kind,code=code,value=value))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.e=types.SimpleNamespace(EV_KEY=1,EV_ABS=3,EV_SYN=0,SYN_DROPPED=3,SYN_REPORT=0)
        self.device=FakeDevice()
        self.mapping={'hotkey':('button',316,1),'select':('button',314,1),
                      'start':('button',315,1),'b':('button',304,1),'a':('button',305,1),
                      'left':('axis',0,-1),'right':('axis',0,1)}
        self.controller=runtime.Controller(self.device,self.mapping,self.e)

    def test_shortcut_only_on_edge_and_ordinary_select_is_not_shortcut(self):
        self.device.event(314,1);self.assertEqual(self.controller.poll(),[])
        self.device.event(316,1);self.assertEqual(self.controller.poll(),['toggle'])
        self.device.event(316,2);self.assertEqual(self.controller.poll(),[])
        self.device.event(314,0);self.device.event(316,0);self.controller.poll()
        self.assertTrue(self.controller.released())

    def test_startup_held_buttons_require_release(self):
        self.device.keys={316,314}
        controller=runtime.Controller(self.device,self.mapping,self.e)
        self.device.event(314,2);self.assertEqual(controller.poll(),[])
        self.device.event(314,0);self.device.event(316,0);controller.poll()
        self.device.event(316,1);self.device.event(314,1)
        self.assertEqual(controller.poll(),['toggle'])

    def test_navigation_is_inactive_until_keyboard_has_grabbed_device(self):
        self.device.event(304,1);self.assertEqual(self.controller.poll(),[])
        self.device.event(304,0);self.controller.poll();self.controller.grab()
        self.device.event(304,1);self.assertEqual(self.controller.poll(),['b'])
        self.controller.close()
        self.assertFalse(self.device.grabbed);self.assertTrue(self.device.closed)

    def test_hotkey_start_remains_exit_during_capture(self):
        self.controller.grab()
        self.device.event(316,1);self.controller.poll()
        self.device.event(315,1);self.assertEqual(self.controller.poll(),['exit'])

    def test_lost_events_resynchronise_without_closing_or_typing_stale_input(self):
        self.assertEqual(self.controller.poll(),[])
        self.controller.grab()
        self.device.event(304,1)
        self.device.event(3,0,kind=0)
        self.device.event(305,1)
        self.assertEqual(self.controller.poll(),[])
        self.assertTrue(self.controller.syncing)
        self.assertFalse(self.controller.released())
        self.assertTrue(self.device.grabbed)
        self.device.keys.clear()
        self.device.event(0,0,kind=0)
        self.assertEqual(self.controller.poll(),[])
        self.assertFalse(self.controller.syncing)
        self.assertTrue(self.controller.armed)
        self.device.event(304,1)
        self.assertEqual(self.controller.poll(),['b'])

    def test_resync_held_shortcut_waits_for_release_and_new_press(self):
        self.device.event(3,0,kind=0)
        self.device.event(316,1); self.device.event(314,1)
        self.device.event(0,0,kind=0)
        self.assertEqual(self.controller.poll(),[])
        self.device.event(314,2)
        self.assertEqual(self.controller.poll(),[])
        self.device.event(314,0); self.device.event(316,0)
        self.controller.poll()
        self.device.event(316,1); self.device.event(314,1)
        self.assertEqual(self.controller.poll(),['toggle'])

    def test_sensor_backlog_drained_across_multiple_batches(self):
        from unittest.mock import Mock
        events = [types.SimpleNamespace(type=1,code=316,value=1),
                  types.SimpleNamespace(type=1,code=314,value=1)]
        self.device.read = Mock(side_effect=[[events[0]], [events[1]], BlockingIOError()])
        self.assertEqual(self.controller.poll(),['toggle'])
        self.assertEqual(self.device.read.call_count,3)

    def test_continuous_sensor_events_do_not_starve_the_gui(self):
        from unittest.mock import Mock
        sensor = types.SimpleNamespace(type=3,code=10,value=1)
        self.device.read = Mock(return_value=[sensor])
        self.assertEqual(self.controller.poll(),[])
        self.assertEqual(self.device.read.call_count,64)

    def test_bindings_use_recorded_codes_and_reject_select_as_hotkey(self):
        xml='<inputConfig>'+''.join(f'<input name="{name}" type="button" code="{code}" value="1"/>' for name,code in [('hotkey',316),('select',314),('b',304),('a',305),('start',315)])+'<input name="joystick1left" type="axis" code="0" value="-1"/></inputConfig>'
        mapping=runtime.bindings(ET.fromstring(xml))
        self.assertEqual(mapping['left'],('axis',0,-1));self.assertEqual(mapping['right'],('axis',0,1))
        with self.assertRaises(ValueError):runtime.bindings(ET.fromstring(xml.replace('code="316"','code="314"')))
        with self.assertRaises(ValueError):runtime.bindings(ET.fromstring(xml.replace('code="316"','id="12"')))

    def test_shortcut_follows_user_remapping_instead_of_fixed_ps_buttons(self):
        xml='<inputConfig>'+''.join(f'<input name="{name}" type="button" code="{code}" value="1"/>' for name,code in [('hotkey',310),('select',318),('b',304),('a',305),('start',315)])+'</inputConfig>'
        mapping=runtime.bindings(ET.fromstring(xml))
        device=FakeDevice()
        controller=runtime.Controller(device,mapping,self.e)
        # The usual Sony PS/Create codes must not activate this remapped pad.
        device.event(316,1);device.event(314,1)
        self.assertEqual(controller.poll(),[])
        device.event(316,0);device.event(314,0);controller.poll()
        # Only the two event codes saved by the user in ES activate it.
        device.event(310,1);device.event(318,1)
        self.assertEqual(controller.poll(),['toggle'])

    def test_sdl_hardware_identity_ignores_name_crc_and_driver_marker(self):
        self.assertEqual(runtime.guid_identity('050000004c050000e60c000000010000'), (5, 0x054c, 0x0ce6, 0x0100))
        self.assertEqual(runtime.guid_identity('0500abcd4c050000e60c000000016800'), (5, 0x054c, 0x0ce6, 0x0100))
        self.assertIsNone(runtime.guid_identity(None))
        self.assertIsNone(runtime.guid_identity('invalid'))

    def test_controller_matches_hardware_when_sdl_and_kernel_names_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'es_input.cfg'
            path.write_text('<inputList><inputConfig type="joystick" deviceName="DualSense Wireless Controller" deviceGUID="050000004c050000e60c000000010000">'+''.join(f'<input name="{name}" type="button" code="{code}" value="1"/>' for name,code in [('hotkey',316),('select',314),('b',304),('a',305),('start',315)])+'</inputConfig></inputList>')
            device=FakeDevice();device.name='Wireless Controller'
            device.info=types.SimpleNamespace(bustype=5,vendor=0x054c,product=0x0ce6,version=0x0100)
            device.capabilities=lambda **kwargs:{1:[316,314,304,305,315],3:[]}
            fake=types.SimpleNamespace(ecodes=self.e,list_devices=lambda:['physical'],InputDevice=lambda _:device)
            with patch.dict(sys.modules,{'evdev':fake}):
                result=runtime.controllers([path])
            self.assertEqual(len(result),1)
            result[0].close();self.assertTrue(device.closed)

    def test_real_evdev_absolute_capabilities_use_codes_not_absinfo_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'es_input.cfg'
            buttons = [('hotkey',316),('select',314),('b',304),('a',305),('start',315)]
            path.write_text('<inputList><inputConfig type="joystick" deviceName="Pad">'+
                ''.join(f'<input name="{name}" type="button" id="{i}" code="{code}" value="1"/>'
                        for i,(name,code) in enumerate(buttons))+
                '<input name="joystick1left" type="axis" code="0" value="-1"/>'+
                '<input name="joystick1up" type="axis" code="1" value="-1"/>'+
                '</inputConfig></inputList>')
            device = FakeDevice(); device.name = 'Pad'
            device.info = types.SimpleNamespace(bustype=3,vendor=1,product=2,version=1)
            calls = []
            def capabilities(absinfo=True):
                calls.append(absinfo)
                return {1:[c for _,c in buttons],3:[(0,object()),(1,object())] if absinfo else [0,1]}
            device.capabilities = capabilities
            fake = types.SimpleNamespace(ecodes=self.e,list_devices=lambda:['pad'],InputDevice=lambda _:device)
            with patch.dict(sys.modules,{'evdev':fake}):
                result = runtime.controllers([path])
            self.assertEqual(calls,[False])
            self.assertEqual(len(result),1)
            self.assertEqual(result[0].amx_hotkey,'guide')
            self.assertEqual(result[0].mapping['left'],('axis',0,-1))
            result[0].close()


class KeyboardTests(unittest.TestCase):
    def test_layout_navigation_case_symbols_and_actions(self):
        for french in (True,False):
            model=runtime.KeyboardModel(french)
            for _ in range(90):
                model.move('right');model.move('down');self.assertTrue(model.selected())
            self.assertIsNone(model.activate('shift'));self.assertTrue(model.upper)
            self.assertIsNone(model.activate('symbols'));self.assertIn('1',model.rows()[0])
            for action in ('close','enter','space','backspace'):
                self.assertEqual(model.activate(action),action)

    def test_key_events_release_modifiers_on_write_failure(self):
        sender=runtime.KeySender.__new__(runtime.KeySender)
        sender.e=types.SimpleNamespace(EV_KEY=1)
        sender.characters={'A':(30,(42,))}
        events=[]
        class UI:
            def write(self,kind,code,value):
                if code==30 and value==1: raise OSError('device disappeared')
                events.append((code,value))
            def syn(self): pass
        sender.ui=UI()
        with self.assertRaises(OSError):sender.send('A')
        self.assertEqual(events,[(42,1),(42,0)])
        with self.assertRaises(ValueError):sender.send('☃')




class LifecycleTests(unittest.TestCase):
    def test_real_detached_worker_and_stop_only_matching_rom(self):
        """Exercise the actual start/stop CLI with a headless daemon backend."""
        import shutil
        probe = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(3)'])
        try:
            try:
                actual = Path(f'/proc/{probe.pid}/cmdline').read_bytes()
            except OSError:
                actual = b''
            if b'import time;time.sleep(3)' not in actual:
                self.skipTest('Host virtualizes /proc child process identities')
        finally:
            probe.terminate(); probe.wait()
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            helpers=home/'toolbox/helpers';helpers.mkdir(parents=True)
            for name in ('virtual_keyboard.py','virtual_keyboard_antimicrox.py'):
                shutil.copy2(ROOT/'toolbox/helpers'/name,helpers/name)
            (helpers/'antimicrox_live.py').write_text('from pathlib import Path\ndef atomic(path,data):\n Path(path).parent.mkdir(parents=True,exist_ok=True)\n Path(path).write_bytes(data)\n')
            (helpers/'virtual_keyboard_runtime.py').write_text('''
import os,time,signal
from pathlib import Path
from virtual_keyboard import lifecycle_lock,process_identity
import json
def diagnose(home): pass
def preview(home): pass
def run(home,rom):
 with lifecycle_lock(home) as state:
  data=json.loads((state/'session.json').read_text())
  assert data=={'rom':rom,'pid':os.getpid(),'token':process_identity(os.getpid())}
 signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(SystemExit()))
 (Path(home)/'ready').write_text(str(os.getpid()))
 try:
  while True:time.sleep(.02)
 finally:(Path(home)/'closed').touch()
''')
            rom=home/'Game.wine';rom.mkdir()
            policy.Settings(home).set('on',rom)
            helper=helpers/'virtual_keyboard.py'
            cmd=[sys.executable,str(helper),'--home',str(home)]
            # Keep logs local; use the actual start implementation with its
            # log argument instead of the CLI's Batocera log default.
            launch='import sys;sys.path.insert(0,sys.argv[1]);import virtual_keyboard as v;v.start(sys.argv[2],sys.argv[3],sys.argv[4])'
            subprocess.run([sys.executable,'-c',launch,str(helpers),str(home),str(rom),str(home/'log')],check=True)
            deadline=time.monotonic()+4
            while not (home/'ready').exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue((home/'ready').exists(),(home/'log').read_text())
            try:
                subprocess.run(cmd+['stop','--rom',str(home/'Other.wine')],check=True)
                self.assertFalse((home/'closed').exists())
            finally:
                subprocess.run(cmd+['stop','--rom',str(rom)],check=True)
            self.assertTrue((home/'closed').exists())
            self.assertFalse((home/'state/virtual-keyboard/session.json').exists())




class RuntimeIntegrationTests(unittest.TestCase):
    def exercise(self, grab_failure=False, managed_amx=False):
        import antimicrox_focus
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);rom=str(home/'Game.wine')
            policy.Settings(home).set('on',rom)
            state=home/'state/virtual-keyboard';state.mkdir(parents=True)
            (state/'session.json').write_text(json.dumps({'rom':rom,'pid':os.getpid(),'token':'test-token'}))
            clock=[0.];timers=[];typed=[];shown=[];errors=[]
            device=FakeDevice()
            if grab_failure:
                def fail(): raise OSError('already grabbed')
                device.grab=fail
            mapping={'hotkey':('button',316,1),'select':('button',314,1),'start':('button',315,1),
                     'b':('button',304,1),'a':('button',305,1)}
            controller=runtime.Controller(device,mapping,types.SimpleNamespace(EV_KEY=1,EV_ABS=3,EV_SYN=0,SYN_DROPPED=3,SYN_REPORT=0))
            class Gtk:
                quit=False
                @classmethod
                def main_quit(cls):cls.quit=True
                @classmethod
                def main(cls):
                    steps={0:[(316,1),(314,1)],1:[(314,0),(316,0)],
                           4:[(304,1)],5:[(304,0)],6:[(316,1),(314,1)],7:[(314,0),(316,0)]}
                    for index in range(25):
                        clock[0]=index*.2
                        for code,value in steps.get(index,[]):device.event(code,value)
                        for timer in timers:
                            if not timer(): cls.quit=True
                        if cls.quit:break
                    self.assertTrue(cls.quit,'watcher must stop after the game exits')
            class GLib:
                PRIORITY_DEFAULT=0
                @staticmethod
                def timeout_add(delay,callback):timers.append(callback)
                @staticmethod
                def unix_signal_add(*args):pass
            class Overlay:
                def __init__(self,deps,action,french):
                    self.model=runtime.KeyboardModel(True);self.action=action;self.open=False
                    self.message=types.SimpleNamespace(set_text=errors.append)
                def visible(self):return self.open
                def show(self):self.open=True;shown.append(clock[0])
                def hide(self):self.open=False
                def render(self):pass
                def close(self):self.open=False
            class Sender:
                def send(self,key):typed.append(key)
                def close(self):pass
            windows=types.SimpleNamespace(current=lambda _:('game',1),close=lambda:None)
            with patch.object(runtime,'gtk_dependencies',return_value=(Gtk,None,GLib,None)), \
                 patch.object(runtime,'controllers',return_value=[controller]), \
                 patch.object(runtime,'KeySender',return_value=Sender()), \
                 patch.object(runtime,'Overlay',Overlay), \
                 patch.object(runtime,'process_identity',return_value='test-token'), \
                 patch.object(runtime,'conflict',return_value=''), \
                 patch.object(policy,'conflict',return_value=''), \
                 patch.object(runtime.time,'monotonic',side_effect=lambda:clock[0]), \
                 patch.object(runtime,'running_game',side_effect=lambda:rom if clock[0]<3 else ''), \
                 patch('virtual_keyboard_antimicrox.evdev_session',return_value=managed_amx), \
                 patch('virtual_keyboard_antimicrox.subprocess.run') as profile_ipc, \
                 patch.object(antimicrox_focus,'XWindows',return_value=windows):
                runtime.run(home,rom)
                if managed_amx: profile_ipc.assert_not_called()
            self.assertFalse(device.grabbed)
            self.assertTrue(device.closed)
            self.assertFalse((state/'session.json').exists())
            return typed,shown

    def test_real_runtime_opens_after_release_types_and_hides_before_game_end(self):
        typed,shown=self.exercise()
        self.assertEqual(typed,['a'])
        self.assertEqual(len(shown),1)
        self.assertGreaterEqual(shown[0],.3)

    def test_managed_amx_opens_on_first_chord_without_profile_reload(self):
        typed, shown = self.exercise(managed_amx=True)
        self.assertEqual(typed,['a'])
        self.assertEqual(len(shown),1)
        # First chord at t=0, release at t=.2; it must be visible well before
        # the second chord at t=1.2, which closes it rather than opening it.
        self.assertLess(shown[0],.7)

    def test_failed_exclusive_grab_never_opens_overlay_and_cleans_up(self):
        typed,shown=self.exercise(True)
        self.assertEqual(typed,[]);self.assertEqual(shown,[])


class GtkStartupTests(unittest.TestCase):
    def test_wayland_display_is_initialized_before_layer_support_is_queried(self):
        initialized=[]
        gtk=types.SimpleNamespace(init_check=lambda:(initialized.append(True) or True, []))
        def supported():
            self.assertTrue(initialized, 'GTK must connect to the display before querying layer-shell')
            return True
        layer=types.SimpleNamespace(is_supported=supported)
        gi=types.SimpleNamespace(require_version=lambda *args:None)
        repository=types.SimpleNamespace(Gtk=gtk,Gdk=object(),GLib=object(),GtkLayerShell=layer)
        with patch.dict(sys.modules,{'gi':gi,'gi.repository':repository}), \
             patch.dict(os.environ,{'WAYLAND_DISPLAY':'wayland-0'}):
            dependencies=runtime.gtk_dependencies()
        self.assertIs(dependencies[3],layer)


if __name__=='__main__':unittest.main()
