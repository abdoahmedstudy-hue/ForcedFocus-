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


class TestForceFocusCLISetKey(unittest.TestCase):
    @patch('forcefocus_cli.os.geteuid')
    @patch('forcefocus_cli.sys.exit')
    @patch('forcefocus_cli.out.print_error')
    def test_set_key_non_root(self, mock_print_error, mock_exit, mock_geteuid):
        """Test set-key command when not run as root."""
        mock_geteuid.return_value = 1000 # non-root user
        mock_print_error.side_effect = SystemExit(1)
        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_set_key(None)

        # Verify it errors out correctly
        mock_print_error.assert_called_with("Must run as root to set the kill-switch passphrase.", code="PERM_DENIED", suggestion="Use: sudo forcefocus set-key")

    @patch('forcefocus_cli.os.geteuid')
    @patch('forcefocus_cli.getpass.getpass')
    @patch('forcefocus_cli.out.print_error')
    def test_set_key_empty_passphrase(self, mock_print_error, mock_getpass, mock_geteuid):
        """Test set-key command when an empty passphrase is provided."""
        mock_geteuid.return_value = 0 # root user

        # Empty string on first prompt
        mock_getpass.side_effect = ["", ""]
        mock_print_error.side_effect = SystemExit(1)
        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_set_key(None)

        mock_print_error.assert_called_with("Passphrase cannot be empty.", code="INVALID_INPUT")

    @patch('forcefocus_cli.os.geteuid')
    @patch('forcefocus_cli.getpass.getpass')
    @patch('forcefocus_cli.out.print_error')
    def test_set_key_mismatched_passphrases(self, mock_print_error, mock_getpass, mock_geteuid):
        """Test set-key command when passphrases do not match."""
        mock_geteuid.return_value = 0 # root user

        # Different strings
        mock_getpass.side_effect = ["password123", "different123"]
        mock_print_error.side_effect = SystemExit(1)
        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_set_key(None)

        mock_print_error.assert_called_with("Passphrases do not match.", code="MISMATCH")

    @patch('forcefocus_cli.os.geteuid')
    @patch('forcefocus_cli.getpass.getpass')
    @patch('forcefocus_cli.os.urandom')
    @patch('forcefocus_cli.json.dump')
    @patch('forcefocus_cli.os.chmod')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('forcefocus_cli.out.print_data')
    @patch('pathlib.Path.mkdir')
    def test_set_key_success(self, mock_mkdir, mock_print_data, mock_open, mock_chmod, mock_json_dump, mock_urandom, mock_getpass, mock_geteuid):
        """Test successful set-key command execution."""
        mock_geteuid.return_value = 0 # root user
        mock_getpass.side_effect = ["mypassword", "mypassword"]
        mock_urandom.return_value = b'1234567890abcdef'

        forcefocus_cli.cmd_set_key(None)

        mock_mkdir.assert_called_with(parents=True, exist_ok=True)
        mock_open.assert_called_with(forcefocus_cli.KS_HASH_FILE, "w")
        mock_json_dump.assert_called_once()
        mock_chmod.assert_called_with(forcefocus_cli.KS_HASH_FILE, 0o600)
        mock_print_data.assert_called_with({"status": "ok", "message": "Passphrase set successfully."}, title="Set Key")

    @patch('forcefocus_cli.os.geteuid')
    @patch('forcefocus_cli.getpass.getpass')
    @patch('forcefocus_cli.sys.exit')
    @patch('builtins.print')
    def test_set_key_keyboard_interrupt(self, mock_print, mock_exit, mock_getpass, mock_geteuid):
        """Test set-key handles KeyboardInterrupt gracefully."""
        mock_geteuid.return_value = 0 # root user
        mock_getpass.side_effect = KeyboardInterrupt()

        forcefocus_cli.cmd_set_key(None)

        mock_print.assert_called_with("\nAborted.")
        mock_exit.assert_called_with(1)


if __name__ == '__main__':
    unittest.main()
