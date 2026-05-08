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



import socket
import json
import os

class TestSendCommand(unittest.TestCase):
    @patch('forcefocus_cli.os.path.exists')
    @patch('forcefocus_cli.out.print_error')
    def test_daemon_not_found(self, mock_print_error, mock_exists):
        mock_exists.return_value = False
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "DAEMON_NOT_FOUND")

    @patch('forcefocus_cli.os.path.exists')
    @patch('forcefocus_cli.socket.socket')
    @patch('forcefocus_cli.out.print_error')
    def test_connection_refused(self, mock_print_error, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst
        mock_sock_inst.connect.side_effect = ConnectionRefusedError()
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "CONNECTION_REFUSED")

    @patch('forcefocus_cli.os.path.exists')
    @patch('forcefocus_cli.socket.socket')
    @patch('forcefocus_cli.out.print_error')
    def test_timeout(self, mock_print_error, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst
        mock_sock_inst.connect.side_effect = socket.timeout()
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "TIMEOUT")

    @patch('forcefocus_cli.os.path.exists')
    @patch('forcefocus_cli.socket.socket')
    @patch('forcefocus_cli.out.print_error')
    def test_socket_error(self, mock_print_error, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst
        mock_sock_inst.connect.side_effect = Exception("Some error")
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "SOCKET_ERROR")

    @patch('forcefocus_cli.os.path.exists')
    @patch('forcefocus_cli.socket.socket')
    @patch('forcefocus_cli.out.print_error')
    def test_empty_response(self, mock_print_error, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst

        mock_sock_inst.recv.side_effect = [b""]
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "EMPTY_RESPONSE")

    @patch('forcefocus_cli.os.path.exists')
    @patch('forcefocus_cli.socket.socket')
    def test_success(self, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst

        response_data = {"status": "ok", "message": "success"}
        mock_sock_inst.recv.side_effect = [json.dumps(response_data).encode("utf-8"), b""]

        result = forcefocus_cli.send_command({"cmd": "status"})

        self.assertEqual(result, response_data)
        mock_sock_inst.connect.assert_called_once_with(forcefocus_cli.SOCK_PATH)
        mock_sock_inst.sendall.assert_called_once_with(json.dumps({"cmd": "status"}).encode("utf-8"))

if __name__ == '__main__':
    unittest.main()
