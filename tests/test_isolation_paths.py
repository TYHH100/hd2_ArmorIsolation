from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import isolation_paths as paths


class IsolationPathTests(unittest.TestCase):
    def test_source_paths_are_project_relative(self):
        with patch.object(paths.sys, "frozen", False, create=True):
            root = Path(paths.__file__).resolve().parents[1]
            self.assertEqual(paths.application_dir(), root)
            self.assertEqual(paths.resource_root(), root)
            self.assertEqual(paths.default_output(), root / "dist/generated")

    def test_frozen_output_stays_beside_executable_not_meipass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "app/ArmorIsolation.exe"
            extraction = root / "temp/_MEI12345"
            with patch.object(paths.sys, "frozen", True, create=True), \
                    patch.object(paths.sys, "executable", str(executable)), \
                    patch.object(paths.sys, "_MEIPASS", str(extraction), create=True):
                self.assertEqual(paths.resource_root(), extraction)
                self.assertEqual(paths.application_dir(), executable.parent)
                self.assertEqual(paths.default_output(), executable.parent / "ArmorIsolation-output")
                self.assertFalse(paths.default_output().is_relative_to(extraction))
                self.assertFalse(paths.default_output().exists())

    def test_modern_vdf_only_reads_library_paths_not_nested_app_ids(self):
        document = r'''"libraryfolders" {
            "0" { "path" "C:\\Steam" "apps" { "553850" "12345" } }
            // Another library on a different disk.
            "1" { "path" "D:\\Games\\SteamLibrary" "label" "Games" }
        }'''
        self.assertEqual(paths.parse_steam_libraries(document),
                         [Path(r"C:\Steam"), Path(r"D:\Games\SteamLibrary")])

    def test_legacy_vdf_ignores_metadata_and_deduplicates(self):
        document = r'''"LibraryFolders" {
            "TimeNextStatsReport" "12345"
            "1" "D:\\SteamLibrary"
            "2" "D:\\SteamLibrary"
        }'''
        self.assertEqual(paths.parse_steam_libraries(document), [Path(r"D:\SteamLibrary")])
        self.assertEqual(paths.parse_steam_libraries('"libraryfolders" { "0" {'), [])

    def test_discovers_secondary_library_from_registry_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            steam = root / "Steam"
            library = root / "另一个库"
            game = library / "steamapps/common/Helldivers 2"
            game.mkdir(parents=True)
            (steam / "steamapps").mkdir(parents=True)
            escaped = str(library).replace("\\", "\\\\")
            (steam / "steamapps/libraryfolders.vdf").write_text(
                f'"libraryfolders" {{ "1" {{ "path" "{escaped}" }} }}', encoding="utf-8-sig")
            with patch.object(paths, "_registry_steam_roots", return_value=[steam]), \
                    patch.dict(paths.os.environ, {}, clear=True):
                self.assertEqual(paths.discover_game_path(), str(game.resolve()))

    def test_program_files_default_and_not_found(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(paths, "_registry_steam_roots", return_value=[]), \
                    patch.dict(paths.os.environ, {"ProgramFiles(x86)": str(root)}, clear=True):
                self.assertEqual(paths.discover_game_path(), "")
                game = root / "Steam/steamapps/common/Helldivers 2"
                game.mkdir(parents=True)
                self.assertEqual(paths.discover_game_path(), str(game.resolve()))

    def test_registry_reads_user_and_both_machine_views(self):
        fake = types.SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2,
                                     KEY_READ=8, KEY_WOW64_32KEY=16, KEY_WOW64_64KEY=32)
        context = MagicMock()
        fake.OpenKey = MagicMock(return_value=context)
        fake.QueryValueEx = MagicMock(side_effect=[(r"C:\Steam", 1), OSError(), (r"D:\Steam", 1)])
        with patch.object(paths, "winreg", fake):
            self.assertEqual(paths._registry_steam_roots(), [Path(r"C:\Steam"), Path(r"D:\Steam")])
        self.assertEqual([call.args[1] for call in fake.QueryValueEx.call_args_list],
                         ["SteamPath", "InstallPath", "InstallPath"])
        self.assertEqual([call.args[3] for call in fake.OpenKey.call_args_list], [8, 24, 40])


if __name__ == "__main__":
    unittest.main()
