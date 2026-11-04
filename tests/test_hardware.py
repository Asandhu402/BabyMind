"""Tests for offline hardware detection and model sizing."""
from __future__ import annotations

import unittest

from babymind import hardware


class HardwareTests(unittest.TestCase):
    def test_report_has_the_fields_the_ui_needs(self) -> None:
        report = hardware.hardware_report()
        for key in ("cpu", "logical_cores", "ram_gb", "recommended", "llama_cpp_flags", "gpu", "disclaimer"):
            self.assertIn(key, report)
        self.assertGreaterEqual(report["logical_cores"], 1)
        self.assertIn("--ctx-size", report["llama_cpp_flags"])
        flags = report["llama_cpp_flags"]
        self.assertEqual(flags[flags.index("--n-gpu-layers") + 1], "0")  # CPU inference by default

    def test_recommendation_scales_with_memory(self) -> None:
        small = hardware._recommend(4)
        medium = hardware._recommend(24)
        large = hardware._recommend(64)
        self.assertEqual(small["parameter_class"], "1B–2B")
        self.assertEqual(medium["parameter_class"], "4B–7B")
        self.assertEqual(large["parameter_class"], "7B–8B")
        self.assertLessEqual(small["context_size"], medium["context_size"])

    def test_unknown_memory_uses_the_smallest_setting(self) -> None:
        report = hardware._recommend(None)
        self.assertEqual(report["context_size"], 4096)
        self.assertIn("could not be measured", report["note"])

    def test_threads_leave_room_for_the_ui(self) -> None:
        report = hardware.hardware_report()
        self.assertLessEqual(report["recommended_threads"], max(1, report["logical_cores"] - 1))
        self.assertGreaterEqual(report["recommended_threads"], 1)


if __name__ == "__main__":
    unittest.main()
