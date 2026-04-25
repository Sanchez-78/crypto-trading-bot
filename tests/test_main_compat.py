import importlib.util
import io
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch


_MAIN_PATH = os.path.join(os.path.dirname(__file__), "..", "main.py")
_SPEC = importlib.util.spec_from_file_location("compat_main", _MAIN_PATH)
compat_main = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(compat_main)


class TestMainCompat(unittest.TestCase):
    def test_default_command_starts_bot(self):
        with patch.object(compat_main, "run_bot", return_value=0) as mock_run_bot:
            result = compat_main.main([])
        self.assertEqual(result, 0)
        mock_run_bot.assert_called_once_with()

    def test_start_alias_starts_bot(self):
        with patch.object(compat_main, "run_bot", return_value=0) as mock_run_bot:
            result = compat_main.main(["start"])
        self.assertEqual(result, 0)
        mock_run_bot.assert_called_once_with()

    def test_signals_command_without_symbol(self):
        with patch.object(compat_main, "run_signals", return_value=0) as mock_run_signals:
            result = compat_main.main(["signals"])
        self.assertEqual(result, 0)
        mock_run_signals.assert_called_once_with(symbol=None)

    def test_signals_command_with_symbol(self):
        with patch.object(compat_main, "run_signals", return_value=0) as mock_run_signals:
            result = compat_main.main(["signals", "BTCUSDT"])
        self.assertEqual(result, 0)
        mock_run_signals.assert_called_once_with(symbol="BTCUSDT")

    def test_unknown_command_returns_error(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            result = compat_main.main(["unknown"])
        self.assertEqual(result, 2)
        self.assertIn("Unknown command: unknown", stderr.getvalue())


class TestProcfile(unittest.TestCase):
    def test_procfile_points_to_start(self):
        procfile_path = os.path.join(os.path.dirname(__file__), "..", "procfile")
        with open(procfile_path, encoding="utf-8") as fh:
            content = fh.read().strip()
        self.assertEqual(content, "worker: python start.py")


if __name__ == "__main__":
    unittest.main()
