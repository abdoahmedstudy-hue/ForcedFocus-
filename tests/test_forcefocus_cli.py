import unittest
import argparse
import sys
from unittest.mock import patch, MagicMock

# Create a more robust mock package for 'rich'
import types

rich_mock = types.ModuleType('rich')
sys.modules['rich'] = rich_mock

for sub_module in ['console', 'panel', 'table', 'text', 'box', 'prompt', 'layout', 'live', 'spinner', 'progress', 'theme']:
    sys.modules[f'rich.{sub_module}'] = MagicMock()

import forcefocus_cli

class TestForceFocusCLIParser(unittest.TestCase):
    def setUp(self):
        self.parser = forcefocus_cli.build_parser()

    def test_build_parser_returns_argument_parser(self):
        """Verify that build_parser returns an ArgumentParser instance."""
        self.assertIsInstance(self.parser, argparse.ArgumentParser)

    def test_global_flags(self):
        """Test global flags."""
        args = self.parser.parse_args(["--human", "--agent", "--brief"])
        self.assertTrue(args.human)
        self.assertTrue(args.agent)
        self.assertTrue(args.brief)

        args_empty = self.parser.parse_args([])
        self.assertFalse(args_empty.human)
        self.assertFalse(args_empty.agent)
        self.assertFalse(args_empty.brief)

    def test_start_subcommand(self):
        """Test 'start' subcommand arguments."""
        args = self.parser.parse_args(["start", "--duration", "60", "--mode", "whitelist"])
        self.assertEqual(args.command, "start")
        self.assertEqual(args.duration, 60)
        self.assertEqual(args.mode, "whitelist")
        self.assertEqual(args.func, forcefocus_cli.cmd_start)

        # Test defaults
        args_default = self.parser.parse_args(["start"])
        self.assertEqual(args_default.duration, 120)
        self.assertEqual(args_default.mode, "blacklist")
        self.assertEqual(args_default.session_type, "standard")

    def test_stop_subcommand(self):
        """Test 'stop' subcommand arguments."""
        args = self.parser.parse_args(["stop", "--key", "mysecret"])
        self.assertEqual(args.command, "stop")
        self.assertEqual(args.key, "mysecret")
        self.assertEqual(args.func, forcefocus_cli.cmd_stop)

    def test_status_subcommand(self):
        """Test 'status' subcommand arguments."""
        args = self.parser.parse_args(["status"])
        self.assertEqual(args.command, "status")
        self.assertEqual(args.func, forcefocus_cli.cmd_status)

    def test_set_key_subcommand(self):
        """Test 'set-key' subcommand arguments."""
        args = self.parser.parse_args(["set-key"])
        self.assertEqual(args.command, "set-key")
        self.assertEqual(args.func, forcefocus_cli.cmd_set_key)

    def test_web_subcommand(self):
        """Test 'web' subcommand arguments."""
        args = self.parser.parse_args(["web", "stop"])
        self.assertEqual(args.command, "web")
        self.assertEqual(args.action, "stop")
        self.assertEqual(args.func, forcefocus_cli.cmd_web)

        # Test default action
        args_default = self.parser.parse_args(["web"])
        self.assertEqual(args_default.action, "start")

    def test_groups_subcommand(self):
        """Test 'groups' subcommand arguments."""
        args = self.parser.parse_args(["groups", "add", "mygroup", "domain.com", "domain.org"])
        self.assertEqual(args.command, "groups")
        self.assertEqual(args.action, "add")
        self.assertEqual(args.name, "mygroup")
        self.assertEqual(args.domains, ["domain.com", "domain.org"])
        self.assertEqual(args.func, forcefocus_cli.cmd_groups)



class TestCmdStart(unittest.TestCase):
    def setUp(self):
        self.args = MagicMock()
        self.args.mode = "blacklist"
        self.args.session_type = "standard"
        self.args.duration = 60
        self.args.focus = 25
        self.args.break_time = 5
        self.args.cycles = 4
        self.args.schedule_in = None
        self.args.schedule_at = None
        self.args.groups = None

        self.patch_send = patch('forcefocus_cli.send_command')
        self.patch_error = patch('forcefocus_cli.out.print_error')
        self.patch_data = patch('forcefocus_cli.out.print_data')
        self.patch_status = patch('forcefocus_cli.console.status')

        self.mock_send = self.patch_send.start()
        self.mock_error = self.patch_error.start()
        self.mock_data = self.patch_data.start()
        self.mock_status = self.patch_status.start()

        self.mock_send.return_value = {"status": "ok", "message": "Started"}

        # Start with agent mode (is_human=False) for simpler tests
        self.original_is_human = forcefocus_cli.out.is_human
        forcefocus_cli.out.is_human = False

    def tearDown(self):
        self.patch_send.stop()
        self.patch_error.stop()
        self.patch_data.stop()
        self.patch_status.stop()
        forcefocus_cli.out.is_human = self.original_is_human

    def test_standard_session(self):
        forcefocus_cli.cmd_start(self.args)

        expected_payload = {
            "action": "start",
            "duration_minutes": 60,
            "mode": "blacklist",
            "session_type": "standard",
            "focus_minutes": 25,
            "break_minutes": 5,
            "cycles": 4
        }

        self.mock_send.assert_called_once_with(expected_payload)
        self.mock_data.assert_called_once_with({"status": "ok", "message": "Started"}, title="Start Session")

    def test_pomodoro_session(self):
        self.args.session_type = "pomodoro"

        forcefocus_cli.cmd_start(self.args)

        expected_payload = {
            "action": "start",
            "duration_minutes": (25 + 5) * 4, # 120
            "mode": "blacklist",
            "session_type": "pomodoro",
            "focus_minutes": 25,
            "break_minutes": 5,
            "cycles": 4
        }

        self.mock_send.assert_called_once_with(expected_payload)

    def test_invalid_duration(self):
        self.args.duration = 0

        forcefocus_cli.cmd_start(self.args)

        self.mock_error.assert_called_once_with("Duration must be a positive number of minutes.", code="INVALID_DURATION")

    def test_schedule_in(self):
        self.args.schedule_in = 30

        forcefocus_cli.cmd_start(self.args)

        payload = self.mock_send.call_args[0][0]
        self.assertEqual(payload["schedule_in_minutes"], 30)
        self.assertNotIn("schedule_at_time", payload)

    def test_schedule_at(self):
        self.args.schedule_at = "14:30"

        forcefocus_cli.cmd_start(self.args)

        payload = self.mock_send.call_args[0][0]
        self.assertEqual(payload["schedule_at_time"], "14:30")
        self.assertNotIn("schedule_in_minutes", payload)

    def test_groups(self):
        self.args.groups = ["work", "study"]

        forcefocus_cli.cmd_start(self.args)

        payload = self.mock_send.call_args[0][0]
        self.assertEqual(payload["groups"], ["work", "study"])

    def test_human_output(self):
        forcefocus_cli.out.is_human = True

        # Setup the context manager mock manually for status
        mock_ctx = MagicMock()
        self.mock_status.return_value.__enter__.return_value = mock_ctx

        forcefocus_cli.cmd_start(self.args)

        self.mock_status.assert_called_once()
        self.mock_send.assert_called_once()

if __name__ == '__main__':
    unittest.main()
