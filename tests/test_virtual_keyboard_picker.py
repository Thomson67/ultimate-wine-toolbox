"""Per-game picker performs one settings read/process for the whole library."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'toolbox/helpers'))
import virtual_keyboard as policy

class PickerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)

    def test_one_settings_read_for_large_library_preserves_overrides(self):
        settings=policy.Settings(self.home)
        data={'global':True,'games':{'/games/Game 1.wine':'off','/games/Game 3.wine':'on'}}
        with patch.object(settings,'read',return_value=data) as read:
            rows=list(settings.game_states(f'/games/Game {i}.wine\n' for i in range(3000)))
        read.assert_called_once()
        self.assertEqual(len(rows),3000)
        self.assertEqual(rows[1],('off','/games/Game 1.wine'))
        self.assertEqual(rows[2],('inherit','/games/Game 2.wine'))
        self.assertEqual(rows[3],('on','/games/Game 3.wine'))

    def run_picker(self, games, choice='back', value='off', invalid=False, mode='all', overrides=None):
        settings=policy.Settings(self.home)
        settings.set('on')
        settings.set('on','/games/Other.wine')
        for rom,state in (overrides or {}).items():settings.set(state,rom)
        if invalid:settings.path.write_text('{bad config')
        before=settings.path.read_bytes()
        (self.home/'games').write_text('\n'.join(games)+'\n')
        env=dict(os.environ, WT_HOME=str(self.home), WT_ROOT=str(ROOT/'toolbox'), REAL_PYTHON=sys.executable,
                 PICK=choice, VALUE=value, MODE=mode)
        script=r'''
source "$WT_ROOT/modules/virtual-keyboard.sh"
i18n() { printf '%s' "$1"; }
python3() { printf '%s\n' "$*" >> "$WT_HOME/calls"; "$REAL_PYTHON" "$@"; }
have_dialog() { return 0; }
wt_clear_tty() { :; }
dialog() { printf 'loading\n' >> "$WT_HOME/order"; }
mangohud_list_games() { printf 'enumeration\n' >> "$WT_HOME/order"; cat "$WT_HOME/games"; }
msgbox() { printf '%s\n' "$*" >> "$WT_HOME/messages"; }
menu_select() {
  if [ "$1" = osk_game ] || [ "$1" = osk_configured ]; then
    printf '%s\n' "$@" > "$WT_HOME/options"
    printf '%s' "$PICK"
  else
    printf '%s\n' "$@" > "$WT_HOME/game-menu"
    printf '%s' "$VALUE"
  fi
}
osk_game_menu "$MODE"
'''
        result=subprocess.run(['bash','-uc',script],env=env,capture_output=True,text=True,timeout=15)
        self.assertIn(result.returncode,(0,1) if choice=='back' else (0,),result.stderr)
        return settings,before

    def test_large_picker_uses_one_process_and_shows_loading_before_scan(self):
        settings,before=self.run_picker([f'/games/Game {i} [runner].wsquashfs' for i in range(2500)])
        self.assertEqual(len((self.home/'calls').read_text().splitlines()),1)
        self.assertIn('game-states',(self.home/'calls').read_text())
        self.assertEqual((self.home/'order').read_text().splitlines(),['loading','enumeration'])
        self.assertIn('Game 2499 [runner].wsquashfs — osk_inherit',(self.home/'options').read_text())
        self.assertEqual(settings.path.read_bytes(),before)

    def test_selection_updates_only_exact_game_with_spaces_and_brackets(self):
        game='/games/Beyond Good and Evil[L].wsquashfs'
        settings,_=self.run_picker(['/games/First.wine',game],choice='2',value='off')
        self.assertEqual(settings.read(),{'global':True,'games':{'/games/Other.wine':'on',game:'off'}})
        self.assertEqual((self.home/'game-menu').read_text().splitlines()[0],'Beyond Good and Evil[L].wsquashfs')

    def test_configured_rules_are_sorted_and_independent_of_global_activation(self):
        settings=policy.Settings(self.home)
        for global_on in (False,True):
            data={'global':global_on,'games':{'/games/Zelda.wine':'off','/games/Alpha [runner].wsquashfs':'on'}}
            with patch.object(settings,'read',return_value=data) as read:
                self.assertEqual(list(settings.configured_game_states()),[
                    ('on','/games/Alpha [runner].wsquashfs'),('off','/games/Zelda.wine')])
            read.assert_called_once()

    def test_configured_picker_does_not_scan_roms_and_can_remove_an_override(self):
        game='/games/Beyond Good and Evil[L].wsquashfs'
        settings,_=self.run_picker([],choice='1',value='inherit',mode='configured',overrides={game:'on'})
        self.assertEqual(settings.read(),{'global':True,'games':{'/games/Other.wine':'on'}})
        self.assertFalse((self.home/'order').exists(),'Configured manager must not enumerate the ROM library')
        self.assertIn('configured-games',(self.home/'calls').read_text())
        self.assertIn('Beyond Good and Evil[L].wsquashfs — enabled',(self.home/'options').read_text())

    def test_configured_picker_can_disable_and_preserve_the_entry(self):
        settings,_=self.run_picker([],choice='1',value='off',mode='configured')
        self.assertEqual(settings.read()['games'],{'/games/Other.wine':'off'})
        self.assertEqual(list(settings.configured_game_states()),[('off','/games/Other.wine')])

    def test_preview_uses_ten_seconds_without_typing(self):
        import types
        from unittest.mock import Mock
        import virtual_keyboard_runtime as runtime
        gtk=types.SimpleNamespace(main=Mock(),main_quit=Mock())
        glib=types.SimpleNamespace(timeout_add_seconds=Mock())
        overlay=Mock()
        with patch.object(runtime,'gtk_dependencies',return_value=(gtk,None,glib,None)), \
                patch.object(runtime,'Overlay',return_value=overlay), patch.object(runtime,'KeySender') as sender:
            runtime.preview(self.home)
        self.assertEqual(glib.timeout_add_seconds.call_args.args[0],10)
        callback=glib.timeout_add_seconds.call_args.args[1]
        self.assertFalse(callback())
        gtk.main_quit.assert_called_once()
        overlay.show.assert_called_once(); overlay.close.assert_called_once()
        sender.assert_not_called()

    def test_keyboard_menu_keeps_only_activation_game_picker_and_preview(self):
        script=r'''
source "$WT_ROOT/modules/virtual-keyboard.sh"
i18n() { printf '%s' "$1"; }
osk_cmd() { printf off; }
menu_select() { printf '%s\n' "$@" > "$WT_HOME/menu"; printf back; }
virtual_keyboard_menu
'''
        result=subprocess.run(['bash','-uc',script],env=dict(os.environ,WT_ROOT=str(ROOT/'toolbox'),WT_HOME=str(self.home)),
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        menu=(self.home/'menu').read_text().splitlines()
        self.assertIn('games',menu);self.assertIn('preview',menu);self.assertIn('configured',menu)
        self.assertNotIn('diagnose',menu);self.assertNotIn('help',menu)
        self.assertNotIn('osk_diagnose',menu)

    def test_empty_list_displays_no_games(self):
        settings,before=self.run_picker([])
        self.assertIn('mangohud_no_games',(self.home/'messages').read_text())
        self.assertFalse((self.home/'options').exists())
        self.assertEqual(settings.path.read_bytes(),before)

    def test_invalid_settings_display_error_and_preserve_file(self):
        settings,before=self.run_picker(['/games/Game.wine'],invalid=True)
        self.assertIn('osk_config_error',(self.home/'messages').read_text())
        self.assertFalse((self.home/'options').exists())
        self.assertEqual(settings.path.read_bytes(),before)

if __name__=='__main__':unittest.main()
