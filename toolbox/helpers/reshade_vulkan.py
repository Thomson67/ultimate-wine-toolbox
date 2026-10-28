"""Windows Vulkan loader provisioning and scoped Wine registry values."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

VERSION = "1.4.341.0"
URL = "https://sdk.lunarg.com/sdk/download/1.4.341.0/windows/VulkanRT-X64-1.4.341.0-Components.zip"
ARCHIVE_HASH = "20571dcc8292b80a47d68bbbfa4094d87044041f50f4e2e1f326a01e3732b226"
LAYER_SECTION = r"Software\Khronos\Vulkan\ImplicitLayers"
REG_VALUE = re.compile(r'(?m)^("(?:[^"\\\n]|\\.)*")=([^\n]*)$')


def value_name(quoted):
    # Wine may rewrite non-ASCII names using \\xhhhh after a game exits.
    text = quoted[1:-1]
    out, i = [], 0
    while i < len(text):
        if text[i] != "\\":
            out.append(text[i]); i += 1; continue
        i += 1
        if i >= len(text):
            raise ValueError("invalid quoted registry name")
        if text[i] == 'x' and re.fullmatch(r'[0-9a-fA-F]{4}', text[i+1:i+5]):
            out.append(chr(int(text[i+1:i+5], 16))); i += 5
        else:
            out.append({'n': '\n', 'r': '\r', 't': '\t'}.get(text[i], text[i])); i += 1
    return ''.join(out)


def equivalent_value(left, right):
    if left is None or right is None:
        return left is right
    a, b = REG_VALUE.fullmatch(left), REG_VALUE.fullmatch(right)
    return bool(a and b and value_name(a[1]).casefold() == value_name(b[1]).casefold()
                and a[2].strip().casefold() == b[2].strip().casefold())


def windows_path(path):
    return "Z:" + str(Path(path).absolute()).replace("/", "\\")


def loader(home, arch):
    from reshade_manager import atomic_bytes, pe_arch, read_json, save_json, fingerprint
    cache = home / "reshade/runtime/vulkan-loader" / VERSION
    dll = cache / str(arch) / "vulkan-1.dll"
    record = read_json(cache / "provenance.json")
    if (dll.is_file() and fingerprint(dll) == {"sha256": record.get(str(arch))}
            and record.get("archive_sha256") == ARCHIVE_HASH):
        return dll
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".loader-", dir=cache) as directory:
        archive = Path(directory) / "components.zip"
        subprocess.run(["curl", "-fsSL", "--retry", "3", "--connect-timeout", "15", "--max-time", "300",
                        URL, "-o", str(archive)], check=True)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_HASH:
            raise ValueError("VulkanRT checksum mismatch; no game file changed")
        with zipfile.ZipFile(archive) as source:
            root = "VulkanRT-X64-" + VERSION + "-Components/"
            payloads = {}
            for bits, folder in ((32, "x86"), (64, "x64")):
                info = source.getinfo(root + folder + "/vulkan-1.dll")
                if info.file_size > 32 * 1024 * 1024:
                    raise ValueError("unexpected Vulkan loader size")
                data = source.read(info)
                if pe_arch(data) != bits:
                    raise ValueError("wrong Vulkan loader architecture")
                payloads[bits] = data
            license_data = source.read(root + "VulkanRT-License.txt")
        for bits, data in payloads.items():
            atomic_bytes(cache / str(bits) / "vulkan-1.dll", data)
        atomic_bytes(cache / "VulkanRT-License.txt", license_data)
        save_json(cache / "provenance.json", dict(
            source=URL, version=VERSION, archive_sha256=ARCHIVE_HASH,
            **{str(bits): hashlib.sha256(data).hexdigest() for bits, data in payloads.items()}))
    return dll


def manifest(arch):
    return (json.dumps({"file_format_version": "1.0.0", "layer": {
        "name": "VK_LAYER_reshade", "type": "GLOBAL",
        "library_path": ".\\ReShade" + str(arch) + ".dll",
        "api_version": "1.3.268", "implementation_version": "1",
        "description": "ReShade (Ultimate Wine Toolbox, experimental)",
        "device_extensions": [{"name": "VK_EXT_tooling_info", "spec_version": "1",
                               "entrypoints": ["vkGetPhysicalDeviceToolPropertiesEXT"]}],
        "disable_environment": {"DISABLE_VK_LAYER_reshade_1": "1"}}}, indent=2) + "\n").encode()


def section_span(text, section):
    wanted = section.replace("\\", "\\\\").casefold()
    headers = list(re.finditer(r"(?m)^\[([^\n]+)\][^\n]*$", text))
    found = [(h.end(), headers[i+1].start() if i+1 < len(headers) else len(text))
             for i, h in enumerate(headers) if h[1].casefold() == wanted]
    if len(found) > 1:
        raise ValueError("duplicate Wine registry section; no Vulkan changes applied")
    return found[0] if found else None


def value_line(text, section, name):
    span = section_span(text, section)
    if span is None:
        return None
    matches = [m for m in REG_VALUE.finditer(text, *span) if value_name(m[1]).casefold() == name.casefold()]
    if len(matches) > 1:
        raise ValueError("duplicate Wine registry value; no Vulkan changes applied")
    return matches[0][0] if matches else None


def set_value(text, section, name, line):
    span = section_span(text, section)
    if span is None:
        if line is None:
            return text
        return text.rstrip() + "\n\n[" + section.replace("\\", "\\\\") + "]\n" + line + "\n"
    start, end = span
    body = text[start:end]
    body = REG_VALUE.sub(lambda m: '' if value_name(m[1]).casefold() == name.casefold() else m[0], body)
    if line is not None:
        body = "\n" + line + "\n" + body.lstrip("\n")
    return text[:start] + body + text[end:]


def registry_plan(prefix, manifest_path, arch, win32, prior=None, baseline=None):
    registry = prefix / "system.reg"
    if registry.is_symlink() or (not registry.is_file() and baseline is None):
        raise ValueError("Vulkan requires an initialized prefix with a regular system.reg; launch the game once first")
    missing = not registry.exists()
    text = baseline if missing else registry.read_text(encoding="utf-8", errors="surrogateescape")
    if not text.startswith("WINE REGISTRY Version 2"):
        raise ValueError("unrecognized Wine registry format")
    section = LAYER_SECTION if arch == 64 or win32 else LAYER_SECTION.replace("Software\\", "Software\\Wow6432Node\\", 1)
    name = windows_path(manifest_path)
    original = value_line(text, section, name)
    installed = json.dumps(name, ensure_ascii=False) + "=dword:00000000"
    if prior:
        if (prior["section"], prior["name"], prior["path"]) != (section, name, str(registry)):
            raise ValueError("disable ReShade before changing its Vulkan layer")
        if not any(equivalent_value(original, allowed) for allowed in (prior["installed"], prior["original"], None)):
            raise ValueError("managed Vulkan registry value changed; disable/repair it before continuing")
        original = prior["original"]
    # Another active ReShade layer can conflict with the managed one.
    span = section_span(text, section)
    if span:
        for entry in text[span[0]:span[1]].splitlines():
            if ("reshade" in entry.casefold() and entry.casefold().endswith("=dword:00000000")
                    and entry != value_line(text, section, name)):
                raise ValueError("another enabled ReShade Vulkan layer exists in this prefix")
    record = {"path": str(registry), "section": section, "name": name,
              "original": original, "installed": installed, "originally_missing": missing}
    return record, set_value(text, section, name, installed)


def registry_restore(record):
    from reshade_manager import atomic_bytes
    path = Path(record["path"])
    if not path.exists() and not path.is_symlink() and record.get('originally_missing'):
        return
    if path.is_symlink() or not path.is_file():
        raise ValueError("Vulkan registry is missing or linked; restore stopped")
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    current = value_line(text, record["section"], record["name"])
    if not any(equivalent_value(current, allowed) for allowed in (record["installed"], record["original"], None)):
        raise ValueError("managed Vulkan registry value changed; restore stopped")
    result = set_value(text, record["section"], record["name"], record["original"])
    atomic_bytes(path, result.encode("utf-8", "surrogateescape"))
