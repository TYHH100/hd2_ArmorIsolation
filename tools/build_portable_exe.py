"""Build one Windows x64 GUI executable with the reader, data, and fixed runtime."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/portable")
    args = parser.parse_args()
    if os.name != "nt" or platform.architecture()[0] != "64bit":
        parser.error("Build with 64-bit Python on Windows")
    import armor_isolation_tool as backend
    runtime, release = backend.runtime_release()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    final_exe = output / "ArmorIsolation.exe"
    if final_exe.exists():
        raise FileExistsError(f"Output already exists: {final_exe}; select a new --output directory")
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="portable-build-", dir=build_root) as temporary:
        work = Path(temporary)
        licenses = work / "licenses"
        licenses.mkdir()
        shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python.LICENSE.txt")
        for name, filename in (("lz4", "python-lz4.LICENSE.txt"), ("pyinstaller", "PyInstaller.COPYING.txt")):
            package = importlib.metadata.distribution(name)
            entry = next(path for path in package.files if path.name in {"LICENSE", "COPYING.txt"})
            shutil.copy2(package.locate_file(entry), licenses / filename)
        tk_license = Path(sys.base_prefix) / "tcl/tk8.6/license.terms"
        if tk_license.is_file():
            shutil.copy2(tk_license, licenses / "Tk.LICENSE.txt")
        data = [(ROOT / "docs/armor-isolation-live-kits.json", "docs"),
                (ROOT / "docs/portable-exe.md", "docs"),
                (ROOT / "assets", "assets"), (licenses, "assets/licenses"),
                (ROOT / "tools/game_data/archive.py", "tools/game_data")]
        for name in ("runtime-release.json", "ArmorIsolation.ini", "ArmorIsolation.addon64", "validate_runtime_profile.exe"):
            data.append((runtime / name, "dist/armor-isolation-runtime"))
        data.append((runtime / "licenses", "dist/armor-isolation-runtime/licenses"))
        for path, _ in data:
            if not path.exists():
                raise FileNotFoundError(path)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
                   "--windowed", "--noupx", "--name", "ArmorIsolation", "--optimize", "0",
                   "--paths", str(ROOT / "tools"), "--distpath", str(work / "dist"),
                   "--workpath", str(work / "work"), "--specpath", str(work)]
        for name in ("build_generic_isolated", "build_modular_isolated", "lz4.block", "lz4._version"):
            command.extend(["--hidden-import", name])
        for path, destination in data:
            command.extend(["--add-data", f"{path}:{destination}"])
        command.append(str(ROOT / "tools/armor_isolation_app.py"))
        environment = {**os.environ, "PYTHONUTF8": "1", "PYINSTALLER_CONFIG_DIR": str(work / "cache")}
        with (output / "build.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=environment, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        executable = work / "dist/ArmorIsolation.exe"
        smoke_log = work / "smoke.log"
        subprocess.run([str(executable), "--log-file", str(smoke_log), "--smoke-test"], cwd=work,
                       check=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
        if "GUI_SMOKE_OK" not in smoke_log.read_text(encoding="utf-8"):
            raise RuntimeError("Bundled GUI smoke test failed")
        shutil.copy2(executable, final_exe)
        manifest = {"schema": "hd2-armor-portable-release/1", "file": final_exe.name,
                    "size": final_exe.stat().st_size, "sha256": digest(final_exe),
                    "python": platform.python_version(), "platform": "Windows x64",
                    "dependencies": {name: importlib.metadata.version(name) for name in
                                     ("pyinstaller", "pyinstaller-hooks-contrib", "lz4")},
                    "game_version": "1.0.0.18930", "game_dll_sha256": release["expected_game_dll_sha256"],
                    "reader_sha256": digest(ROOT / "tools/game_data/archive.py"),
                    "runtime_files": release["files"], "gui_smoke_test": True,
                    "game_runtime_verified": False}
        (output / "release.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
