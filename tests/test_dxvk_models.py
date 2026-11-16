"""Verify pinned model choices and construction with historical NVAPI layouts."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "toolbox/data/batocera-dxvk-models.json"


class ModelTests(unittest.TestCase):
    def test_pinned_combinations_and_complete_checksums(self):
        expected = [("2.3.1", "2.12", "0.7.0"), ("2.5.1", "2.13", "0.7.1"),
                    ("2.7", "2.14.1", "0.9.0"), ("2.7.1", "3.0a", "0.9.0"),
                    ("2.7.1", "3.0a", "0.9.0")]
        models = json.loads(CATALOG.read_text())
        for model, versions in zip(models, expected):
            self.assertEqual(tuple(c["version"] for c in model["components"].values()), versions)
            for component in model["components"].values():
                self.assertRegex(component["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual([m["id"] for m in models], ["40", "41", "42", "43", "44"])
        result = subprocess.run(["python3", str(ROOT / "toolbox/helpers/dxvk_models.py"),
                                 "releases", "39"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_install_menu_accepts_batocera_44_from_catalog(self):
        script = '''source toolbox/modules/dxvk-manager.sh
i18n() { printf '%s' "$1"; }
menu_select() {
    for item in "$@"; do
        if [[ "$item" == 'Batocera 44 — DXVK 2.7.1 / VKD3D 3.0a / NVAPI 0.9.0' ]]; then
            echo 44
            return
        fi
    done
    return 1
}
dxvk_build_bundle() { printf '%s\n' "$4" "$1" "$2" "$3"; }
dxvk_install_model_menu
'''
        env = dict(os.environ, WT_ROOT=str(ROOT / "toolbox"))
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env=env,
                                check=True, capture_output=True, text=True)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "44")
        self.assertEqual([line.split("\t", 1)[0] for line in lines[1:]],
                         ["v2.7.1", "v3.0a", "v0.9.0"])

    def test_build_models_with_and_without_optical_flow_dll(self):
        for model in ("40", "42"):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                components = []
                layouts = {
                    "dxvk": [f"{arch}/{dll}" for arch in ("x32", "x64")
                             for dll in ("d3d9.dll", "d3d10core.dll", "d3d11.dll", "dxgi.dll")],
                    "vkd3d": [f"{arch}/{dll}" for arch in ("x86", "x64")
                              for dll in ("d3d12.dll", "d3d12core.dll")],
                    "nvapi": ["x32/nvapi.dll", "x64/nvapi64.dll"] +
                             (["x64/nvofapi64.dll"] if model == "42" else []),
                }
                for kind, files in layouts.items():
                    archive = folder / (kind + ".tar.gz")
                    with tarfile.open(archive, "w:gz") as tar:
                        for name in files:
                            entry = tarfile.TarInfo(name)
                            entry.size = 3
                            tar.addfile(entry, io.BytesIO(b"DLL"))
                    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                    components.append("v" + ("0.7.0" if kind == "nvapi" and model == "40" else
                                             "0.9.0" if kind == "nvapi" else "2.12") +
                                      "\t" + str(archive) + "\tsha256:" + digest)
                script = '''source toolbox/modules/dxvk-manager.sh
msgbox() { :; }
i18n() { printf '%s' "$1"; }
curl() { cp "$6" "$8"; }
dxvk_build_bundle "$A" "$B" "$C" "$MODEL"
'''
                env = dict(os.environ, WT_HOME=tmp, WT_ROOT=str(ROOT / "toolbox"),
                           A=components[0], B=components[1], C=components[2], MODEL=model)
                result = subprocess.run(["bash", "-c", script], cwd=ROOT, env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                bundles = list((folder / "dxvk/bundles").iterdir())
                self.assertEqual(len(bundles), 1)
                bundle = bundles[0]
                self.assertTrue(bundle.name.startswith("Batocera-" + model))
                self.assertTrue((bundle / "x64/nvapi64.dll").is_file())
                self.assertEqual((bundle / "x64/nvofapi64.dll").exists(), model == "42")
                self.assertEqual(json.loads((bundle / "model.json").read_text())["id"], model)


if __name__ == "__main__":
    unittest.main()
