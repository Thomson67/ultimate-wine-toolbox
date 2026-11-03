#!/usr/bin/env python3
"""Install Toolbox metadata through live ES, or atomically when ES is stopped."""
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

gamelist, backup_dir, rom_name, title, desc, genre, slug = sys.argv[1:]
new_file = not os.path.exists(gamelist)
if new_file:
    text = '<?xml version="1.0"?>\n<gameList>\n</gameList>\n'
else:
    with open(gamelist, "r", encoding="utf-8") as f:
        text = f.read()

try:
    root = ET.fromstring(text)
except ET.ParseError as exc:
    print(f"scraper-assets: gamelist.xml is invalid; leaving it untouched: {exc}", file=sys.stderr)
    raise SystemExit(2)
if root.tag != "gameList":
    print("scraper-assets: gamelist.xml root is not <gameList>; leaving it untouched", file=sys.stderr)
    raise SystemExit(2)

media = {
    "image": f"./media/images/{slug}.jpg",
    "boxart": f"./media/box2d/{slug}.jpg",
    "fanart": f"./media/fanarts/{slug}.jpg",
    "marquee": f"./media/marquee/{slug}.png",
    "thumbnail": f"./media/thumbnails/{slug}.jpg",
}
fields = {
    "path": f"./{rom_name}",
    "name": title,
    "desc": desc,
    "developer": "Thomson",
    "genre": genre,
    **media,
}

def make_entry():
    return "  <game>\n" + "".join(
        f"    <{key}>{escape(value)}</{key}>\n" for key, value in fields.items()
    ) + "  </game>\n"

def set_if_empty_or_managed(body, key, value):
    """Fill blank fields; update only the old paths this installer wrote."""
    tag = re.compile(rf"(<{re.escape(key)}\b[^>]*>)(.*?)(</{re.escape(key)}\s*>)", re.DOTALL)
    self_closing = re.compile(rf"<{re.escape(key)}\b[^>]*/\s*>")
    managed_old = {
        "image": {f"./media/images/{slug}.png", f"./images/{slug}-box2d.png", f"./images/{slug}-screenshot.png"},
        "boxart": {f"./media/box2d/{slug}.png"},
        "fanart": {f"./media/fanarts/{slug}.png", f"./images/{slug}-fanart.png"},
        "marquee": {f"./images/{slug}-logo.png"},
        "thumbnail": {f"./media/thumbnails/{slug}.png", f"./images/{slug}-screenshot.png"},
    }.get(key, set())
    changed = False

    def replace_tag(match):
        nonlocal changed
        old_value = match.group(2)
        plain = re.sub(r"<[^>]+>", "", old_value).strip()
        if plain and plain not in managed_old:
            return match.group(0)
        if plain == value:
            return match.group(0)
        changed = True
        return match.group(1) + escape(value) + match.group(3)

    updated, count = tag.subn(replace_tag, body)
    if count:
        return updated, changed

    updated, count = self_closing.subn(f"<{key}>{escape(value)}</{key}>", body, count=1)
    if count:
        return updated, True

    updated = body
    if updated and not updated.endswith("\n"):
        updated += "\n"
    return updated + f"    <{key}>{escape(value)}</{key}>\n", True

changed = False
found = False
if not new_file:
    game_pattern = re.compile(r"(<game(?:\s[^>]*)?>)(.*?)(</game>)", re.DOTALL)

    def update_existing(match):
        global changed, found
        block = match.group(0)
        try:
            game = ET.fromstring(block)
        except ET.ParseError:
            return block
        path = game.findtext("path", default="").replace("\\", "/").rstrip("/")
        if os.path.basename(path) != rom_name:
            return block
        found = True
        body = match.group(2)
        block_changed = False
        for key, value in fields.items():
            body, did_change = set_if_empty_or_managed(body, key, value)
            block_changed = block_changed or did_change
        if block_changed:
            changed = True
            return match.group(1) + body + match.group(3)
        return block

    updated, _ = game_pattern.subn(update_existing, text)
    if found:
        text = updated
    else:
        close = re.search(r"</gameList\s*>", text)
        if not close:
            print("scraper-assets: gamelist.xml has no gameList closing tag; leaving it untouched", file=sys.stderr)
            raise SystemExit(2)
        before = text[:close.start()]
        if before and not before.endswith("\n"):
            before += "\n"
        text = before + make_entry() + text[close.start():]
        changed = True
else:
    close = re.search(r"</gameList\s*>", text)
    if not close:
        print("scraper-assets: gamelist.xml has no gameList closing tag; leaving it untouched", file=sys.stderr)
        raise SystemExit(2)
    text = text[:close.start()] + make_entry() + text[close.start():]
    changed = True

def backup_current():
    if os.path.exists(gamelist):
        os.makedirs(backup_dir, exist_ok=True)
        stamp = __import__("time").strftime("%Y%m%d-%H%M%S")
        backup_path = os.path.join(backup_dir, f"gamelist-scraper-{stamp}-{os.getpid()}.xml")
        shutil.copy2(gamelist, backup_path)
        print(f"scraper-assets: backup={backup_path}")

from scraper_es import synchronize
try:
    if synchronize(gamelist, text, rom_name, fields, backup_current):
        raise SystemExit(0)
except (OSError, ValueError, RuntimeError, ET.ParseError) as exc:
    print(f"scraper-assets: metadata synchronization failed: {exc}", file=sys.stderr)
    raise SystemExit(3)

if not changed:
    print(f"scraper-assets: gamelist entry already has the target metadata for {rom_name}")
    raise SystemExit(0)

backup_current()

fd, temp_path = tempfile.mkstemp(prefix=".gamelist-scraper-", dir=os.path.dirname(gamelist), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    if not new_file:
        os.chmod(temp_path, os.stat(gamelist).st_mode & 0o777)
    os.replace(temp_path, gamelist)
except Exception:
    try:
        os.unlink(temp_path)
    except OSError:
        pass
    raise
print(f"scraper-assets: updated Batocera gamelist entry for {rom_name}")
