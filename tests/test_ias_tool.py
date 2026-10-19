"""Exercise the Python entry points of the native IAS handoff transaction."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import armor_isolation_tool as tool


class IasToolTests(unittest.TestCase):
    def invoke(self, output, code=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = []
            with patch.object(tool, "runtime_release", return_value=(root, {"ias_compatibility": "manifest-handoff-v1"})), \
                    patch.object(tool.subprocess, "run", return_value=SimpleNamespace(returncode=code, stdout=output)) as run:
                result = tool.prepare_ias_handoff(root / "测试 游戏", logs.append)
                self.assertEqual(run.call_args.args[0],
                                 [str(root / "validate_runtime_profile.exe"), "--ias-prepare", str(root / "测试 游戏")])
                return result, logs

    def test_native_counts_and_idempotence_are_reported_without_visual_claim(self):
        for changed in ("true", "false"):
            result, logs = self.invoke(
                f"IAS_HANDOFF_PREPARED packages=6 targets=12 declarations=12 changed={changed} game_runtime_verified=false\n")
            self.assertEqual(result, {"status": "prepared", "packages": 6, "targets": 12,
                                     "declarations": 12, "changed": changed == "true", "game_runtime_verified": False})
            self.assertEqual(len(logs), 1)

    def test_absent_ias_preserves_original_backend(self):
        result, _ = self.invoke("IAS_ABSENT: ordinary ArmorIsolation remains selected; no files changed\n")
        self.assertEqual(result, {"status": "absent", "changed": False, "game_runtime_verified": False})

    def test_running_game_and_conversion_failure_never_report_success(self):
        with self.assertRaisesRegex(RuntimeError, "正常退出游戏"):
            self.invoke("ERROR: exit Helldivers 2 normally before preparing IAS handoff", 1)
        with self.assertRaisesRegex(RuntimeError, "IAS 声明同步失败.*unknown build"):
            self.invoke("ERROR: unknown build", 1)
        with self.assertRaisesRegex(RuntimeError, "未返回可识别"):
            self.invoke("PROFILE_OK packages=6")

    def test_old_runtime_is_rejected_before_starting_native_process(self):
        with patch.object(tool, "runtime_release", return_value=(Path("runtime"), {})), \
                patch.object(tool.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "不支持 IAS 交接"):
                tool.prepare_ias_handoff(Path("game"))
            run.assert_not_called()

    def test_cli_sync_does_not_require_mod_source_or_start_generation(self):
        with patch.object(sys, "argv", ["tool", "prepare-ias", "--game", "game"]), \
                patch.object(tool, "prepare_ias_handoff", return_value={"status": "prepared"}) as prepare, \
                patch.object(tool, "generate_package") as generate, contextlib.redirect_stdout(io.StringIO()) as output:
            tool.main()
            self.assertEqual(prepare.call_args.args[0], Path("game"))
            generate.assert_not_called()
            self.assertIn('"status": "prepared"', output.getvalue())

    def test_gui_sync_uses_game_only_and_does_not_clear_current_selection(self):
        import tkinter as tk
        import armor_isolation_gui as gui

        class ImmediateThread:
            def __init__(self, *, target, **_):
                self.target = target

            def start(self):
                self.target()

        class Backend:
            discover_defaults = staticmethod(lambda: {"game": "game"})
            prepare_ias_handoff = staticmethod(lambda game, log: {
                "status": "prepared", "packages": 1, "targets": 1, "declarations": 1, "changed": True})

        root = tk.Tk()
        root.withdraw()
        try:
            app = gui.ArmorIsolationApp(root, Backend())
            app.candidates = {"12345678": {"type": 0, "supported": True}}
            app.selected = {"12345678"}
            with patch.object(gui.threading, "Thread", ImmediateThread):
                app.prepare_ias()
                self.assertTrue(app.busy)
                app._drain_events()
            self.assertFalse(app.busy)
            self.assertEqual(app.selected, {"12345678"})
            self.assertIn("1 份声明", app.ias_status.get())
            with patch.object(Backend, "prepare_ias_handoff", side_effect=RuntimeError("请先正常退出游戏")), \
                    patch.object(gui.threading, "Thread", ImmediateThread), patch.object(gui.messagebox, "showerror") as error:
                app.prepare_ias()
                app._drain_events()
                self.assertFalse(app.busy)
                self.assertIn("同步失败", app.ias_status.get())
                error.assert_called_once()
        finally:
            for callback in root.tk.call("after", "info"):
                root.after_cancel(callback)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
