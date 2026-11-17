#!/usr/bin/env python3
"""Launch concurrent native Batocera Wine sessions in nested Gamescope windows."""
import argparse
import ctypes as C
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote_to_bytes


ROM_TYPES = {".wine", ".pc", ".wsquashfs"}
GAMEPADS = "ID_INPUT_JOYSTICK"
KEYBOARDS = "ID_INPUT_KEYBOARD"
MICE = "ID_INPUT_MOUSE"
WRITABLE = {
    "/userdata/system/wine-bottles/windows": "bottles",
    "/userdata/saves/windows": "saves",
    "/var/run/wine": "wine-run",
    "/userdata/system/cache": "cache",
}
UMU_HOME = Path("/userdata/system/umu")
UMU_LOGS = Path("/userdata/system/logs/umu-runner")
UMU_SESSION_STATE = Path("/run/umu-batocera")
UMU_PRIVATE = ("compatdata", "materialized-prefixes", "merged-prefixes",
               "gameviews", "exports")
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
MOUNT_CAPS = ["--cap-add", "CAP_SYS_ADMIN", "--cap-add", "CAP_MKNOD"]


@dataclass(frozen=True)
class Device:
    node: Path
    category: str
    identity: str
    sysfs: Path

    @property
    def joystick_nodes(self):
        return [Path("/dev/input") / p.name for p in self.sysfs.glob("js*")
                if (Path("/dev/input") / p.name).exists()]


def read_input_devices(dev=Path("/dev/input"), sys_input=Path("/sys/class/input"),
                       database=Path("/run/udev/data")):
    stable = {}
    for directory in (dev / "by-path", dev / "by-id"):
        for link in sorted(directory.glob("*-event-*")):
            stable[link.resolve()] = str(link)
    devices = []
    for node in dev.glob("event[0-9]*"):
        n = node.stat().st_rdev
        path = database / f"c{os.major(n)}:{os.minor(n)}"
        try:
            tags = set(path.read_text().splitlines())
        except FileNotFoundError:
            continue
        category = next((kind for kind in (GAMEPADS, KEYBOARDS, MICE)
                         if f"E:{kind}=1" in tags), None)
        if category:
            sysfs = (sys_input / node.name / "device").resolve()
            devices.append(Device(node, category, stable.get(node, ""), sysfs))
    return sorted(devices, key=lambda dev: (not dev.identity, dev.identity,
                                            int(dev.node.name[5:])))


def assign_players(devices, count, input_mode):
    pads = [d for d in devices if d.category == GAMEPADS]
    keyboard_mouse = [next((d for d in devices if d.category == kind), None)
                      for kind in (KEYBOARDS, MICE)]
    available = all(keyboard_mouse)
    if count == "auto":
        count = max(1, min(4, len(pads) + (input_mode != "auto")))
        if input_mode == "clavier-j2":
            count = max(2, count)
    count = int(count)
    use_keyboard = input_mode != "auto" or len(pads) < count
    keyboard_index = 0 if input_mode == "clavier-j1" else (
        1 if input_mode == "clavier-j2" else count - 1)
    if use_keyboard and (not available or keyboard_index >= count or len(pads) < count - 1):
        raise ValueError("Périphériques insuffisants pour la configuration demandée.")
    return [keyboard_mouse if use_keyboard and i == keyboard_index else [pads.pop(0)]
            for i in range(count)]


def layout(monitor, count, split):
    x, y, width, height = monitor
    columns = 2 if count > 2 or (count == 2 and split == "vertical") else 1
    rows = 2 if count > 2 or (count == 2 and split == "horizontal") else 1
    rectangles = []
    for index in range(count):
        row, column = divmod(index, columns)
        left, right = width * column // columns, width * (column + 1) // columns
        top, bottom = height * row // rows, height * (row + 1) // rows
        rectangles.append((x + left, y + top, right - left, bottom - top))
    return rectangles


def primary_monitor():
    if shutil.which("xrandr"):
        result = subprocess.run(["xrandr", "--listactivemonitors"], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        pattern = r"^\s*\d+:\s+(\S+)\s+(\d+)/\d+x(\d+)/\d+([+-]\d+)([+-]\d+)"
        monitors = re.findall(pattern, result.stdout, re.M)
        if monitors:
            _, width, height, x, y = next((m for m in monitors if "*" in m[0]), monitors[0])
            return tuple(map(int, (x, y, width, height)))
    width, height = map(int, subprocess.check_output(["xdotool", "getdisplaygeometry"]).split())
    return 0, 0, width, height


class ClientMessage(C.Structure):
    _fields_ = [
        ("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
        ("display", C.c_void_p), ("window", C.c_ulong),
        ("message_type", C.c_ulong), ("format", C.c_int), ("data", C.c_long * 5),
    ]


class XEvent(C.Union):
    _fields_ = [("message", ClientMessage), ("pad", C.c_long * 24)]


def remove_fullscreen(window):
    x11 = C.CDLL("libX11.so.6")
    x11.XOpenDisplay.argtypes = [C.c_char_p]
    x11.XOpenDisplay.restype = C.c_void_p
    x11.XDefaultRootWindow.argtypes = [C.c_void_p]
    x11.XDefaultRootWindow.restype = C.c_ulong
    x11.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
    x11.XInternAtom.restype = C.c_ulong
    x11.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.POINTER(XEvent)]
    x11.XCloseDisplay.argtypes = [C.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Impossible d’ouvrir l’affichage X11.")
    try:
        root = x11.XDefaultRootWindow(display)
        state, full, vertical, horizontal = [
            x11.XInternAtom(display, name, 0) for name in (
                b"_NET_WM_STATE", b"_NET_WM_STATE_FULLSCREEN",
                b"_NET_WM_STATE_MAXIMIZED_VERT", b"_NET_WM_STATE_MAXIMIZED_HORZ",
            )
        ]
        for first, second in ((full, 0), (vertical, horizontal)):
            event = XEvent()
            event.message = ClientMessage(33, 0, 1, display, int(window), state, 32,
                                          (C.c_long * 5)(0, first, second, 2, 0))
            x11.XSendEvent(display, root, 0, (1 << 19) | (1 << 20), C.byref(event))
    finally:
        x11.XCloseDisplay(display)


def top_window(pid):
    result = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", str(pid)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ids = result.stdout.split()
    return ids[0] if result.returncode == 0 and len(ids) == 1 else None


def place_window(window, rectangle):
    remove_fullscreen(window)
    time.sleep(0.25)
    x, y, width, height = map(str, rectangle)
    subprocess.run(["xdotool", "windowsize", window, width, height,
                    "windowmove", window, x, y], check=True)
    time.sleep(0.15)
    geometry = subprocess.check_output(["xdotool", "getwindowgeometry", "--shell", window],
                                       text=True)
    values = dict(line.partition("=")[::2] for line in geometry.splitlines())
    return tuple(int(values[name]) for name in ("X", "Y", "WIDTH", "HEIGHT")) == rectangle


def rom_path(value, argument_parser):
    try:
        original = Path(value).absolute()
        target = original.resolve(strict=True)
        suffix = original.suffix.lower()
        if suffix not in ROM_TYPES:
            raise ValueError("Formats acceptés : .wine, .pc, .wsquashfs")
        if suffix == ".wsquashfs" and not target.is_file():
            raise ValueError("Une archive .wsquashfs doit être un fichier.")
        if suffix != ".wsquashfs" and not target.is_dir():
            raise ValueError("Un jeu .wine ou .pc doit être un répertoire.")
        if any(token in str(target) for token in (",", ":", "\\", "\n", "\r")):
            raise ValueError("Le chemin réel contient un caractère incompatible avec OverlayFS.")
        return original, target
    except (OSError, ValueError) as error:
        argument_parser.error(str(error))


def write_port(port_dir, launcher, original, count, split, input_mode):
    digest = hashlib.sha256(os.fsencode(original)).hexdigest()[:10]
    port = port_dir / f"PartyDeck - {original.stem[:90]} [{digest}].sh"
    marker = "# Entrée gérée par PartyDeck Wine"
    port_dir.mkdir(parents=True, exist_ok=True)
    if port.is_symlink() or (port.exists() and marker not in port.read_text().splitlines()[:2]):
        raise ValueError(f"Une entrée utilisateur existe déjà : {port}")
    with tempfile.NamedTemporaryFile(mode="w", prefix=".partydeck-", dir=port_dir,
                                     delete=False) as script:
        staged = Path(script.name)
        try:
            script.write(f"#!/bin/bash\n{marker}\nexec ")
            script.write(shlex.join([str(launcher), "coop", str(original), count, split, input_mode]))
            script.write("\n")
            script.flush()
            staged.chmod(0o755)
            staged.replace(port)
        finally:
            staged.unlink(missing_ok=True)
    return port


def player_paths(player):
    paths = dict(WRITABLE)
    if UMU_HOME.is_dir():
        paths[str(UMU_LOGS)] = "umu-logs"
    for destination, relative in paths.items():
        Path(destination).mkdir(parents=True, exist_ok=True)
        source = player / relative
        source.mkdir(parents=True, exist_ok=True)
        yield "--bind", str(source), destination


def bubblewrap_command(app):
    # The AppImage's bin/bwrap wrapper breaks --cap-add argument parsing.
    # Invoke its packaged binary with its own loader, including on Batocera.
    library = app / "lib"
    return [str(library / "ld-linux-x86-64.so.2"), "--library-path",
            str(library), str(app / "shared/bin/bwrap")]


def dbus_socket_mounts(address):
    # Pressure Vessel needs the filesystem socket named by the session address.
    # Abstract addresses and filesystem sockets outside /tmp are already visible.
    for value in dict.fromkeys(re.findall(r"(?:^|;)unix:(?:[^;,]+,)*path=([^;,]+)", address)):
        path = Path(os.path.normpath(os.fsdecode(unquote_to_bytes(value))))
        if path.is_relative_to("/tmp") and path.is_socket():
            yield "--ro-bind", str(path), str(path)


def sandbox_arguments(player, devices, hidraw=Path("/sys/class/hidraw")):
    args = ["--die-with-parent", "--unshare-pid", "--ro-bind", "/", "/",
            "--proc", "/proc", "--dev-bind", "/dev", "/dev",
            *MOUNT_CAPS,
            "--tmpfs", "/tmp", "--tmpfs", "/dev/input", "--unsetenv", "VK_DRIVER_FILES",
            # The Batocera UMU runner derives its runtime directory from its own HOME.
            "--unsetenv", "XDG_DATA_HOME",
            "--bind", str(player), str(player)]
    for item in dbus_socket_mounts(os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")):
        args.extend(item)
    if UMU_HOME.is_dir():
        # Session filenames include a PID, which can repeat across players'
        # PID namespaces. Keep state writable and private to each launch.
        UMU_SESSION_STATE.mkdir(parents=True, exist_ok=True)
        args.extend(["--tmpfs", str(UMU_SESSION_STATE)])
    for item in player_paths(player):
        args.extend(item)
    for device in devices:
        for node in [device.node, *device.joystick_nodes]:
            args.extend(["--dev-bind", str(node), str(node)])
    pad_paths = [device.sysfs for device in devices if device.category == GAMEPADS]
    for raw in hidraw.glob("hidraw[0-9]*"):
        node = Path("/dev") / raw.name
        parent = (raw / "device").resolve()
        if node.exists() and not any(dev.is_relative_to(parent) for dev in pad_paths):
            args.extend(["--ro-bind", "/dev/null", str(node)])
    return args


def mount_overlay(target, area):
    upper, work, view = (area / name for name in ("upper", "work", "view"))
    for path in (upper, work, view):
        path.mkdir(parents=True, exist_ok=True)
    options = f"lowerdir={target},upperdir={upper},workdir={work},redirect_dir=on"
    subprocess.run(["mount", "-t", "overlay", "-o", options, "overlay", str(view)], check=True)
    subprocess.run(["mount", "--bind", str(view), str(target)], check=True)


def run_wine(original, target, player):
    if original.suffix.lower() != ".wsquashfs":
        mount_overlay(target, player / "content")
    if UMU_HOME.is_dir():
        mount_overlay(UMU_HOME, player / "umu")
        for name in UMU_PRIVATE:
            private = player / "umu-private" / name
            private.mkdir(parents=True, exist_ok=True)
            destination = UMU_HOME / name
            destination.mkdir(parents=True, exist_ok=True)
            subprocess.run(["mount", "--bind", str(private), str(destination)], check=True)
    # Keep the original ROM name for Batocera's per-game runner/settings lookup.
    os.execvp("batocera-wine", ["batocera-wine", "windows", "play", str(original)])


def start_player(app, player, original, target, devices, rectangle):
    _, _, width, height = rectangle
    args = [str(app / "AppRun"), "gamescope-kbm", "--backend=sdl", "--borderless",
            "-W", str(width), "-H", str(height),
            "--backend-disable-keyboard", "--backend-disable-mouse"]
    kb_mouse = [str(d.node) for d in devices if d.category in {KEYBOARDS, MICE}]
    if kb_mouse:
        args.extend(["--libinput-hold-dev=" + ",".join(kb_mouse) + ",", "--grab"])
    args.extend(["--", *bubblewrap_command(app), *sandbox_arguments(player, devices),
                 "--", sys.executable, str(Path(__file__).resolve()), "_wine",
                 str(original), str(target), str(player)])
    return subprocess.Popen(args, env={**os.environ, "SDL_VIDEODRIVER": "x11"},
                            start_new_session=True)


def stop_players(processes):
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def handle_exit(signum, _frame):
    raise SystemExit(128 + signum)


def run_session(app, base, original, target, count, split, input_mode):
    for tool in ("batocera-wine", "xdotool", "mount"):
        if not shutil.which(tool):
            raise RuntimeError(f"Commande indisponible : {tool}")
    players = assign_players(read_input_devices(), count, input_mode)
    boxes = layout(primary_monitor(), len(players), split)
    probe = subprocess.run([*bubblewrap_command(app), *MOUNT_CAPS,
                            "--ro-bind", "/", "/", "--unshare-pid", "--proc", "/proc",
                            "--", "/bin/true"])
    if probe.returncode:
        raise RuntimeError("Bubblewrap ne peut pas initialiser l’espace de noms Wine.")
    print("Vérification Bubblewrap Wine OK.", flush=True)
    game_id = hashlib.sha256(os.fsencode(original)).hexdigest()[:16]
    processes = []
    for signum in SIGNALS:
        signal.signal(signum, handle_exit)
    try:
        for index, (devices, rectangle) in enumerate(zip(players, boxes), 1):
            player = base / "coop" / game_id / f"j{index}"
            player.mkdir(parents=True, exist_ok=True)
            print(f"J{index} : {', '.join(str(d.node) for d in devices)} → {rectangle}", flush=True)
            processes.append(start_player(app, player, original, target, devices, rectangle))
        pending = dict(enumerate(processes))
        attempts = dict.fromkeys(pending, 0)
        deadline = time.monotonic() + 120
        while pending and time.monotonic() < deadline:
            for index, process in list(pending.items()):
                status = process.poll()
                if status is not None:
                    print(f"J{index + 1} a quitté avant l’affichage (code {status}).", flush=True)
                    del pending[index]
                    continue
                window = top_window(process.pid)
                if window:
                    attempts[index] += 1
                    try:
                        if place_window(window, boxes[index]):
                            print(f"Fenêtre J{index + 1} placée : {window}", flush=True)
                            del pending[index]
                            continue
                    except subprocess.CalledProcessError:
                        pass  # The window can disappear during startup.
                    if attempts[index] >= 4:
                        print(f"Placement J{index + 1} non confirmé : {window}", flush=True)
                        del pending[index]
            if pending:
                time.sleep(0.5)
        if pending:
            print("Fenêtres non repérées : " + ", ".join(f"J{i + 1}" for i in pending), flush=True)
        statuses = [process.wait() for process in processes]
        return next((status for status in statuses if status), 0)
    finally:
        for signum in SIGNALS:
            signal.signal(signum, signal.SIG_IGN)
        stop_players(processes)


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "_wine":
        run_wine(*(Path(path) for path in sys.argv[2:]))
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "play"))
    parser.add_argument("app", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("ports", type=Path)
    parser.add_argument("rom")
    parser.add_argument("count", nargs="?", default="auto", choices=("auto", "1", "2", "3", "4"))
    parser.add_argument("split", nargs="?", default="horizontal", choices=("horizontal", "vertical"))
    parser.add_argument("input_mode", nargs="?", default="auto",
                        choices=("auto", "clavier-j1", "clavier-j2"))
    args = parser.parse_args()
    original, target = rom_path(args.rom, parser)
    if args.mode == "prepare":
        port = write_port(args.ports, args.base / "partydeck-test", original,
                          args.count, args.split, args.input_mode)
        print(f"Entrée enregistrée : {port}")
        print("Actualise les listes de jeux dans EmulationStation, puis ouvre Ports.")
        return 0
    return run_session(args.app, args.base, original, target, args.count,
                       args.split, args.input_mode)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"PartyDeck Wine : {exc}", file=sys.stderr)
        raise SystemExit(1)
