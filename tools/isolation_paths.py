"""Source/frozen paths and read-only discovery of the installed Steam game."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys

try:
    import winreg
except ImportError:
    winreg = None


def application_dir() -> Path:
    """The persistent application location, never the one-file extraction path."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    """Bundled read-only files live in PyInstaller's extraction directory."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", application_dir())).resolve()
    return application_dir()


def default_output() -> Path:
    if getattr(sys, "frozen", False):
        return application_dir() / "ArmorIsolation-output"
    return application_dir() / "dist" / "generated"


def parse_steam_libraries(text: str) -> list[Path]:
    """Read current nested and older numbered-path libraryfolders.vdf files."""
    raw_tokens = re.findall(r'//[^\r\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+', text)
    tokens = []
    for token in raw_tokens:
        if token.startswith("//"):
            continue
        if token.startswith('"'):
            token = re.sub(r'\\([\\"])', r'\1', token[1:-1])
        tokens.append(token)
    position = 0

    def read_object(nested=False, depth=0):
        nonlocal position
        if depth > 32:
            raise ValueError("VDF nesting is too deep")
        result = {}
        while position < len(tokens):
            key = tokens[position]
            position += 1
            if key == "}":
                if nested:
                    return result
                raise ValueError("Unexpected closing brace")
            if key == "{" or position == len(tokens):
                raise ValueError("Missing VDF key or value")
            value = tokens[position]
            position += 1
            if value == "{":
                value = read_object(True, depth + 1)
            elif value == "}":
                raise ValueError("Missing VDF value")
            result[key.lower()] = value
        if nested:
            raise ValueError("Unclosed VDF object")
        return result

    try:
        libraries = read_object().get("libraryfolders", {})
    except ValueError:
        return []
    if not isinstance(libraries, dict):
        return []
    result = []
    for key, entry in libraries.items():
        if not key.isdigit():
            continue
        value = entry.get("path") if isinstance(entry, dict) else entry
        if isinstance(value, str) and value.strip():
            result.append(Path(value))
    return _unique_paths(result)


def _unique_paths(paths) -> list[Path]:
    result = []
    seen = set()
    for path in paths:
        identity = os.path.normcase(os.path.normpath(str(path)))
        if identity not in seen:
            seen.add(identity)
            result.append(path)
    return result


def _registry_steam_roots() -> list[Path]:
    if winreg is None:
        return []
    locations = [
        (winreg.HKEY_CURRENT_USER, "SteamPath", 0),
        (winreg.HKEY_LOCAL_MACHINE, "InstallPath", getattr(winreg, "KEY_WOW64_32KEY", 0)),
        (winreg.HKEY_LOCAL_MACHINE, "InstallPath", getattr(winreg, "KEY_WOW64_64KEY", 0)),
    ]
    result = []
    for hive, value_name, view in locations:
        try:
            with winreg.OpenKey(hive, r"Software\Valve\Steam", 0, winreg.KEY_READ | view) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            result.append(Path(value))
    return _unique_paths(result)


def discover_game_path() -> str:
    """Find HELLDIVERS 2 without machine-specific drive assumptions or writes."""
    roots = _registry_steam_roots()
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        if value := os.environ.get(variable):
            roots.append(Path(value) / "Steam")
    libraries = []
    for root in _unique_paths(roots):
        libraries.append(root)
        for relative in ("steamapps/libraryfolders.vdf", "config/libraryfolders.vdf"):
            try:
                document = (root / relative).read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            libraries.extend(parse_steam_libraries(document))
    for library in _unique_paths(libraries):
        game = library / "steamapps" / "common" / "Helldivers 2"
        if game.is_dir():
            return str(game.resolve())
    return ""
