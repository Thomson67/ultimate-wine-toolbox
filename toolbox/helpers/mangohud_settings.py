"""Validated global/per-game MangoHud controls and reversible ENV overrides."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import tempfile

CHOICES = {
    "display": ("default", "minimal", "detailed", "hidden"),
    "vulkan": ("off", "mailbox", "on", "adaptive"),
    "opengl": ("off", "on"),
    "method": ("early", "late"),
}
PROFILES = {
    "default": "",
    "minimal": "fps_only=1,frametime=0,frame_timing=0",
    "detailed": "fps,cpu_stats,gpu_stats,cpu_temp,gpu_temp,ram,vram,frametime,frame_timing,present_mode",
    "hidden": "no_display",
}
BACKUP = "UWT_MANGOHUD_CONFIG_BACKUP"
# Match complete shell assignment values, retaining their original quoting.
VALUE = r'''(?:[^\s'\"]+|'[^']*'|"(?:\\.|[^"\\])*")*'''
CONFIG_RE = re.compile(r"(?<!\S)MANGOHUD_CONFIG=" + VALUE + r"(?=\s|$)")
BACKUP_RE = re.compile(r"(?<!\S)" + BACKUP + r"=([A-Za-z0-9_=-]+)(?=\s|$)")


def valid(key, value):
    if key == "fps":
        return isinstance(value, str) and value.isascii() and value.isdecimal() and 0 <= int(value) <= 1000
    return key in CHOICES and value in CHOICES[key]


def load(directory):
    path = Path(directory) / "mangohud-settings.json"
    if not path.exists():
        return {"global": {}, "games": {}}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("global", {}), dict) or not isinstance(data.get("games", {}), dict):
        raise ValueError("Invalid MangoHud settings file")
    def clean(values):
        return {k: v for k, v in values.items() if valid(k, v)} if isinstance(values, dict) else {}
    return {"global": clean(data.get("global", {})),
            "games": {k: clean(v) for k, v in data.get("games", {}).items()}}


def settings(directory, game="", effective=True):
    data = load(directory)
    if not effective:
        return data["games"].get(game, {}) if game else data["global"]
    profile = Path(directory) / "mangohud-profile"
    legacy = profile.read_text().strip() if profile.exists() else "default"
    result = {"display": legacy if legacy in PROFILES else "default"}
    result.update(data["global"])
    result.update(data["games"].get(game, {}))
    return result


def save_setting(directory, game, key, value):
    if key not in (*CHOICES, "fps") or (value != "inherit" and not valid(key, value)):
        raise ValueError("Invalid MangoHud setting")
    data = load(directory)
    target = data["games"].setdefault(game, {}) if game else data["global"]
    if value == "inherit":
        target.pop(key, None)
    else:
        target[key] = str(int(value)) if key == "fps" else value
    if game and not target:
        data["games"].pop(game, None)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".mangohud-settings-", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, directory / "mangohud-settings.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def config_options(values):
    result = []
    display = values.get("display", "default")
    if PROFILES[display]:
        result.extend(PROFILES[display].split(","))
    if "fps" in values:
        result.append("fps_limit=" + values["fps"])
    if "method" in values:
        result.append("fps_limit_method=" + values["method"])
    if "vulkan" in values:
        # Use the named option supported by the Toolbox's MangoHud 0.8.4.
        result.append("vulkan_present_mode=" + {"off": "immediate", "on": "fifo", "adaptive": "fifo_relaxed", "mailbox": "mailbox"}[values["vulkan"]])
    if "opengl" in values:
        result.append("gl_vsync=" + ("1" if values["opengl"] == "on" else "0"))
    return result


def restore_config(payload):
    marker = BACKUP_RE.search(payload)
    if not marker:
        return payload
    original = json.loads(base64.urlsafe_b64decode(marker[1]).decode())
    if not isinstance(original, list) or any(not isinstance(v, str) or not CONFIG_RE.fullmatch(v) for v in original):
        raise ValueError("Invalid MangoHud ENV backup")
    payload = CONFIG_RE.sub("", payload)
    payload = BACKUP_RE.sub("", payload)
    return payload.rstrip() + (" " + " ".join(original) if original else "")


def apply_config(payload, values):
    """Called only after restoring the previous run's settings."""
    options = config_options(values)
    if not options:
        return payload
    originals = CONFIG_RE.findall(payload)
    current = shlex.split(originals[-1])[0].split("=", 1)[1] if originals else ""
    # Filter keys managed by this selection; keep unrelated custom settings.
    controlled = {option.split("=", 1)[0] for option in options}
    if "vulkan" in values:
        controlled.add("vsync")
    if values.get("display") in ("minimal", "detailed", "hidden"):
        controlled.update({"fps_only", "no_display", "preset"})
    kept = [v for v in current.split(",") if v and v.split("=", 1)[0] not in controlled]
    if not originals and values.get("display", "default") == "default":
        kept.insert(0, "read_cfg")
    config = ",".join(kept + options)
    backup = base64.urlsafe_b64encode(json.dumps(originals).encode()).decode()
    payload = CONFIG_RE.sub("", payload).rstrip()
    return payload + " " + BACKUP + "=" + backup + " MANGOHUD_CONFIG=" + shlex.quote(config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("get", "set"))
    parser.add_argument("directory")
    parser.add_argument("key", choices=(*CHOICES, "fps"))
    parser.add_argument("value", nargs="?")
    parser.add_argument("--game", default="")
    parser.add_argument("--effective", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "get":
            print(settings(args.directory, args.game, args.effective).get(args.key, "inherit"))
        else:
            save_setting(args.directory, args.game, args.key, args.value)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
