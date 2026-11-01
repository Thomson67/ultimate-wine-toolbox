#!/usr/bin/env python3
"""Scoped return-focus test; preserve other installed Toolbox changes."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

HELPER = '"""Activate only the returning Toolbox terminal, during a bounded startup window."""\nimport argparse\nfrom pathlib import Path\nimport time\n\nfrom antimicrox_focus import XWindows, process_start\n\n\ndef is_es(pid):\n    try:\n        return Path(f\'/proc/{pid}/comm\').read_text().strip().startswith(\'emulationstat\')\n    except OSError:\n        return False\n\n\ndef activate_return(pid, owner, windows, identity=process_start, es=is_es,\n                    clock=time.monotonic, sleep=time.sleep, timeout=8, log=print):\n    stamp, owner_stamp = identity(pid), identity(owner)\n    if not stamp or not owner_stamp:\n        return False\n    deadline = clock() + timeout\n    stable_since = None\n    attempts = 0\n    next_attempt = 0\n    while clock() < deadline:\n        if identity(pid) != stamp or identity(owner) != owner_stamp:\n            log(\'Toolbox focus: session ended; stopping\')\n            return False\n        target = windows.editor_window(pid)\n        active = windows.cardinal(windows.root, \'_NET_ACTIVE_WINDOW\')\n        if target and active == target:\n            if stable_since is None:\n                stable_since = clock()\n            if clock() - stable_since >= .75:\n                log(f\'Toolbox focus: confirmed window={target} attempts={attempts}\')\n                return True\n        else:\n            stable_since = None\n            active_pid = windows.cardinal(active, \'_NET_WM_PID\') if active else 0\n            if active and active_pid and not es(active_pid):\n                log(\'Toolbox focus: another application is active; stopping\')\n                return False\n            if target and clock() >= next_attempt and attempts < 3:\n                # Recheck identity immediately before requesting activation.\n                if identity(pid) != stamp or identity(owner) != owner_stamp:\n                    return False\n                windows.activate(target)\n                attempts += 1\n                next_attempt = clock() + 1\n                log(f\'Toolbox focus: activation requested window={target} attempt={attempts}\')\n        sleep(.1)\n    log(\'Toolbox focus: startup activation unconfirmed; stopping\')\n    return False\n\n\ndef main():\n    parser = argparse.ArgumentParser()\n    parser.add_argument(\'--pid\', type=int, required=True)\n    parser.add_argument(\'--owner\', type=int, required=True)\n    args = parser.parse_args()\n    activate_return(args.pid, args.owner, XWindows(),\n                    log=lambda text: print(text, flush=True))\n\n\nif __name__ == \'__main__\':\n    try:\n        main()\n    except (OSError, ValueError, RuntimeError) as exc:\n        print(f\'Toolbox focus: unavailable: {exc}\', flush=True)\n'
BLOCK = '# BEGIN UWT RETURN FOCUS\n# Activate the existing terminal only for a return, without delaying the UI.\nif [ "${WT_AUTO_RESUME_WSQ:-0}" = 1 ] || \\\n   [ "${WT_AUTO_RESUME_AMX:-0}" = 1 ] || \\\n   [ "${WT_AUTO_RESUME_RESH:-0}" = 1 ]; then\n    python3 "$ROOT/helpers/toolbox_focus.py" --pid "$PPID" --owner "$$" \\\n        >> "$LOG" 2>&1 &\nfi\n# END UWT RETURN FOCUS\n\n'

def install(home):
    launcher = home / 'toolbox/launch-in-terminal.sh'
    helper = home / 'toolbox/helpers/toolbox_focus.py'
    state = home / 'state/toolbox-return-focus-test'
    text = launcher.read_text()
    anchor = 'if [ ! -s "$MAIN" ]; then'
    if '# BEGIN UWT RETURN FOCUS' in text and BLOCK not in text:
        raise RuntimeError('Bloc de focus différent : aucune modification.')
    if BLOCK not in text and text.count(anchor) != 1:
        raise RuntimeError('Lanceur incompatible : aucune modification.')
    candidate = text if BLOCK in text else text.replace(anchor, BLOCK + anchor, 1)
    subprocess.run(['bash', '-n'], input=candidate, text=True, check=True)
    compile(HELPER, str(helper), 'exec')
    if not (home / 'toolbox/helpers/antimicrox_focus.py').is_file():
        raise RuntimeError('Module de focus requis absent : aucune modification.')
    manifest = state / 'manifest.json'
    if not manifest.exists():
        if BLOCK in text:
            raise RuntimeError('Sauvegarde du test absente : aucune modification.')
        state.mkdir(parents=True, exist_ok=True)
        shutil.copy2(launcher, state / 'launch-in-terminal.sh.original')
        existed = helper.exists()
        if existed:
            shutil.copy2(helper, state / 'toolbox_focus.py.original')
        manifest.write_text(json.dumps({'helper_existed': existed}))
    elif helper.exists() and helper.read_text() != HELPER:
        raise RuntimeError('Module modifié depuis le test : installation arrêtée.')
    helper.write_text(HELPER)
    launcher.write_text(candidate)
    print('Correctif de test du retour au premier plan installé (version inchangée).')
    print('Il sera actif aux prochains retours de jeu dans la Toolbox.')
    print('Restauration : python3 ' + str(state / 'installer.py') + ' --restore --home ' + str(home))
    shutil.copy2(Path(__file__), state / 'installer.py') if Path(__file__).resolve() != (state / 'installer.py').resolve() else None


def restore(home):
    state = home / 'state/toolbox-return-focus-test'
    manifest = state / 'manifest.json'
    if not manifest.exists():
        print('Aucun test actif à retirer.')
        return
    launcher = home / 'toolbox/launch-in-terminal.sh'
    helper = home / 'toolbox/helpers/toolbox_focus.py'
    text = launcher.read_text()
    if '# BEGIN UWT RETURN FOCUS' in text and BLOCK not in text:
        raise RuntimeError('Bloc modifié depuis le test : restauration arrêtée.')
    if helper.exists() and helper.read_text() != HELPER:
        raise RuntimeError('Module modifié depuis le test : restauration arrêtée.')
    launcher.write_text(text.replace(BLOCK, '', 1))
    if json.loads(manifest.read_text())['helper_existed']:
        shutil.copy2(state / 'toolbox_focus.py.original', helper)
    else:
        helper.unlink(missing_ok=True)
    manifest.unlink()
    print('Correctif de test retiré. Les autres modifications sont conservées.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, default=Path('/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    (restore if args.restore else install)(args.home)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
