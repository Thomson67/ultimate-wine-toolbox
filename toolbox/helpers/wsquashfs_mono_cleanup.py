#!/usr/bin/env python3
"""Fix Mono removal in a private Winetricks copy used by the .NET workflow."""
from pathlib import Path
import re
import sys


def patched(source):
    start = source.find('load_remove_mono()\n{')
    if start < 0:
        raise ValueError('Unsupported Winetricks Mono removal function')
    end = source.find('\n}\n', start)
    if end < 0:
        raise ValueError('Incomplete Winetricks Mono removal function')
    body = source[start:end]
    # Multiple Mono Windows Support versions produce multiple GUID lines.
    # Passing the complete string as one --remove argument cannot remove them.
    call = '            "${WINE_ARCH}" uninstaller --remove "${mono_uuid}"'
    if body.count(call) != 1:
        raise ValueError('Unsupported Winetricks Mono uninstaller invocation')
    body = body.replace(call, '''            while IFS= read -r uwt_mono_uuid; do
                [ -n "${uwt_mono_uuid}" ] || continue
                "${WINE_ARCH}" uninstaller --remove "${uwt_mono_uuid}"
            done <<UWT_MONO_GUIDS
${mono_uuid}
UWT_MONO_GUIDS''')
    # GE-Proton #278: the unqualified delete only affects one registry view.
    # Retain Winetricks' mono_install_found guard; never clear real .NET here.
    count = 0
    def views(match):
        nonlocal count
        count += 1
        line = match.group(0)
        return line.replace(' /f || true', ' /f /reg:32 || true') + '\n' + line.replace(' /f || true', ' /f /reg:64 || true')
    body = re.sub(r'^        "\$\{WINE_ARCH\}" reg delete "HKLM\\\\Software\\\\Microsoft\\\\NET Framework Setup\\\\NDP\\\\v(?:3\.5|4)" /f \|\| true$', views, body, flags=re.M)
    if count != 2:
        raise ValueError('Unsupported Winetricks Mono registry cleanup')
    return source[:start] + body + source[end:]


def main():
    try:
        source, target = map(Path, sys.argv[1:])
        target.write_text(patched(source.read_text()))
        target.chmod(0o700)
        print('dotnet_mono_cleanup=individual_guids registry_views=32,64', flush=True)
        return 0
    except (OSError, ValueError) as error:
        print(f'Mono cleanup: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
