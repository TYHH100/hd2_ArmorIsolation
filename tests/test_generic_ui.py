from pathlib import Path
import sys
import tkinter as tk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from armor_isolation_gui import ArmorIsolationApp


class StubBackend:
    @staticmethod
    def discover_defaults():
        return {"game": "game", "reader_tools": "reader", "output": "output", "kits": "kits.json", "names": ""}


class GenericUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = ArmorIsolationApp(self.root, StubBackend(), "source.patch_0")
        self.app.candidates = {
            "00000001": {"id": "00000001", "name": "Armor", "type": 0, "unit_matched": 2,
                         "unit_total": 2, "supported": True},
            "00000002": {"id": "00000002", "name": "Helmet", "type": 1, "unit_matched": 1,
                         "unit_total": 1, "supported": True},
            "00000003": {"id": "00000003", "name": "Partial", "type": 0, "unit_matched": 1,
                         "unit_total": 2, "supported": False, "reasons": ["partial coverage"]},
        }
        self.app._render_candidates()

    def tearDown(self):
        self.root.destroy()

    def test_selection_is_explicit_and_unsupported_target_cannot_be_selected(self):
        self.assertEqual(self.app.selected, set())
        self.app._toggle_candidate("00000003")
        self.assertEqual(self.app.selected, set())
        self.app._toggle_candidate("00000002")
        self.assertEqual(self.app.selected, {"00000002"})
        self.assertIn("头盔 1", self.app.selection_summary.get())

    def test_parameter_change_invalidates_candidates_selection_and_previous_output(self):
        self.app._toggle_candidate("00000001")
        self.app.package = Path("previous-package")
        self.app.values["source"].set("different.patch_0")
        self.assertEqual(self.app.selected, set())
        self.assertEqual(self.app.candidates, {})
        self.assertIsNone(self.app.package)
        self.assertTrue(self.app.generate_button.instate(["disabled"]))

    def test_search_preserves_explicit_selection_and_busy_state_blocks_changes(self):
        self.app._toggle_candidate("00000001")
        self.app.search.set("Helmet")
        self.assertEqual(self.app.table.get_children(), ("00000002",))
        self.assertEqual(self.app.selected, {"00000001"})
        self.app._set_busy(True, "busy")
        self.app._toggle_candidate("00000002")
        self.assertEqual(self.app.selected, {"00000001"})
        self.assertTrue(self.app.generate_button.instate(["disabled"]))
        self.app._set_busy(False, "done")
        self.assertTrue(self.app.generate_button.instate(["!disabled"]))


if __name__ == "__main__":
    unittest.main()
