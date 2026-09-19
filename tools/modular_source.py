"""Read legacy and V1 mod directories without changing their selection semantics."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat


PATCH_NAME = re.compile(r"^[0-9a-fA-F]{16}\.patch_[0-9]+$")
LANE_SUFFIXES = (".stream", ".gpu_resources")


def _ordered(paths):
    return tuple(sorted(paths, key=lambda path: (path.as_posix().casefold(), path.as_posix())))


def _no_link(path):
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Symbolic links and reparse points are unsupported: {path}")
    return metadata


def _scan(root):
    _no_link(root)
    files, directories = [], []

    def read_error(error):
        raise error

    for current, names, filenames in os.walk(root, followlinks=False, onerror=read_error):
        current = Path(current)
        for name in names:
            path = current / name
            metadata = _no_link(path)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"Unsupported directory entry: {path}")
            directories.append(path.relative_to(root))
        for name in filenames:
            path = current / name
            metadata = _no_link(path)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"Unsupported file entry: {path}")
            files.append(path.relative_to(root))
    return _ordered(files), _ordered(directories)


def _fingerprint(path):
    before = _no_link(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    after = _no_link(path)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Source changed while reading: {path}")
    return {"size": after.st_size, "sha256": digest.hexdigest()}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest key: {key}")
        result[key] = value
    return result


def _relative_include(value):
    if not isinstance(value, str):
        raise ValueError("Include entries must be relative directory strings")
    windows = PureWindowsPath(value)
    if windows.drive or windows.root or any(part == ".." or ":" in part for part in windows.parts):
        raise ValueError(f"Include escapes the mod directory: {value!r}")
    return Path(*windows.parts)


def manifest_options(manifest):
    """Normalize selection semantics in memory; never rewrite the source manifest."""
    if not isinstance(manifest, dict):
        raise ValueError("Mod manifest must be an object")
    if "Version" in manifest and (type(manifest["Version"]) is not int or manifest["Version"] != 1):
        raise ValueError("Unsupported manifest Version; expected V1 or a legacy manifest without Version")
    options = manifest.get("Options")
    if options is None:
        return []
    if not isinstance(options, list):
        raise ValueError("Manifest Options must be an array")
    if "Version" in manifest:
        return options
    if any(not isinstance(value, str) for value in options):
        raise ValueError("Legacy Options must be a single-choice array of directory strings")
    if not options:
        return []
    return [{"Name": "Options", "SubOptions": [{"Name": value, "Include": [value]} for value in options]}]


@dataclass
class Catalog:
    root: Path
    manifest: dict
    manifest_bytes: bytes
    patch_paths: tuple
    files: tuple
    directories: tuple
    options: tuple
    patch_options: dict
    missing_includes: tuple
    inventory: dict
    patch_files: frozenset

    @property
    def passthrough_paths(self):
        return tuple(path for path in self.files if path not in self.patch_files)

    @property
    def unreferenced_patch_paths(self):
        return tuple(path for path in self.patch_paths if not self.patch_options[path])

    def serializable_inventory(self):
        return [{"path": path.as_posix(), **self.inventory[path]} for path in self.files]

    def verify_unchanged(self):
        files, directories = _scan(self.root)
        if files != self.files or directories != self.directories:
            raise ValueError("Source directory contents changed after analysis")
        for relative in files:
            if _fingerprint(self.root / relative) != self.inventory[relative]:
                raise ValueError(f"Source file changed after analysis: {relative}")

    def copy_passthrough(self, destination):
        """Copy retained content into an empty staging directory, never into the input."""
        destination = Path(destination).absolute()
        for ancestor in (destination, *destination.parents):
            if ancestor.exists() or ancestor.is_symlink():
                _no_link(ancestor)
        destination = destination.resolve()
        if destination == self.root or self.root in destination.parents or destination in self.root.parents:
            raise ValueError("Destination must be outside the source directory")
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise ValueError("Passthrough destination must be an empty directory")
        self.verify_unchanged()
        destination.mkdir(parents=True, exist_ok=True)
        for relative in self.directories:
            (destination / relative).mkdir(parents=True, exist_ok=True)
        for relative in self.passthrough_paths:
            target = destination / relative
            shutil.copy2(self.root / relative, target)
            if _fingerprint(target) != self.inventory[relative]:
                raise ValueError(f"Copied file failed validation: {relative}")
        return destination


def load_catalog(path):
    path = Path(path).absolute()
    _no_link(path)
    if path.is_file():
        if path.name != "manifest.json":
            raise ValueError("Expected a mod directory or its manifest.json")
        path = path.parent
    for ancestor in (path, *path.parents):
        _no_link(ancestor)
    root = path.resolve()
    files, directories = _scan(root)
    manifest_path = Path("manifest.json")
    if manifest_path not in files:
        raise ValueError("The mod directory must contain manifest.json")
    manifest_bytes = (root / manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"), object_pairs_hook=_object)
    effective_options = manifest_options(manifest)
    patches = tuple(relative for relative in files if PATCH_NAME.fullmatch(relative.name))
    patch_set = set(patches)
    patch_files = set(patches)
    for relative in files:
        for suffix in LANE_SUFFIXES:
            if not relative.name.endswith(suffix):
                continue
            main = relative.with_name(relative.name[:-len(suffix)])
            if not PATCH_NAME.fullmatch(main.name):
                continue
            if main in patch_set:
                patch_files.add(relative)
            elif (root / relative).stat().st_size:
                raise ValueError(f"Nonempty patch lane has no main patch: {relative}")
    inventory = {relative: _fingerprint(root / relative) for relative in files}
    if hashlib.sha256(manifest_bytes).hexdigest() != inventory[manifest_path]["sha256"]:
        raise ValueError("Manifest changed while reading")
    owners = {relative: [] for relative in patches}
    missing = []

    def read_options(values, prefix=""):
        if values is None:
            values = []
        if not isinstance(values, list):
            raise ValueError("Options and SubOptions must be arrays")
        if "/" in prefix and values:
            raise ValueError("Only one level of SubOptions is supported")
        result = []
        for index, option in enumerate(values):
            option_id = f"{prefix}/{index}" if prefix else str(index)
            if not isinstance(option, dict) or not isinstance(option.get("Name"), str):
                raise ValueError(f"Option {option_id} must have a Name string")
            includes = option.get("Include", [])
            if not isinstance(includes, list):
                raise ValueError(f"Option {option_id} Include must be an array")
            relative_includes = tuple(_relative_include(value) for value in includes)
            selected = set()
            for raw, relative in zip(includes, relative_includes):
                included = root / relative
                if not included.exists():
                    missing.append({"option": option_id, "include": raw, "path": relative.as_posix()})
                    continue
                if not included.is_dir():
                    raise ValueError(f"Include must name a directory: {raw!r}")
                selected.update(patch for patch in patches if patch.parent == relative)
            selected = _ordered(selected)
            for patch in selected:
                owners[patch].append(option_id)
            result.append({"id": option_id, "name": option["Name"],
                           "includes": tuple(relative.as_posix() for relative in relative_includes),
                           "patch_paths": tuple(path.as_posix() for path in selected),
                           "suboptions_mode": "exclusive",
                           "suboptions": read_options(option.get("SubOptions", []), option_id)})
        return tuple(result)

    options = read_options(effective_options)
    if not options:
        for relative in patches:
            if relative.parent == Path("."):
                owners[relative].append("root")
    final_files, final_directories = _scan(root)
    if files != final_files or directories != final_directories:
        raise ValueError("Source directory contents changed while reading")
    return Catalog(root, manifest, manifest_bytes, patches, files, directories, options,
                   {path: tuple(values) for path, values in owners.items()}, tuple(missing),
                   inventory, frozenset(patch_files))
