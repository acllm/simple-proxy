"""Test address monitoring behavior with wildcard addresses."""
import pytest
from unittest.mock import Mock, patch
import threading
import time


class TestWildcardAddressMonitoring:
    """Verify monitoring works for wildcard addresses."""

    def test_monitoring_enabled_for_ipv6_wildcard(self):
        """Test that monitoring is enabled when using :: address."""
        from main import AddressMonitor, ProxyServer

        # Create a mock server with IPv6 wildcard address
        mock_server = Mock(spec=ProxyServer)
        mock_server.address = "::"
        mock_server.port = 8080

        monitor = AddressMonitor(
            server=mock_server,
            check_interval=0.1,
            check_timeout=0.05,
            original_address="::",
        )

        # Verify wildcard flag is set
        assert monitor._is_wildcard is True

    def test_monitoring_enabled_for_ipv4_wildcard(self):
        """Test that monitoring is enabled when using 0.0.0.0 address."""
        from main import AddressMonitor, ProxyServer

        # Create a mock server with IPv4 wildcard address
        mock_server = Mock(spec=ProxyServer)
        mock_server.address = "0.0.0.0"
        mock_server.port = 8080

        monitor = AddressMonitor(
            server=mock_server,
            check_interval=0.1,
            check_timeout=0.05,
            original_address="0.0.0.0",
        )

        # Verify wildcard flag is set
        assert monitor._is_wildcard is True

    def test_monitoring_enabled_for_specific_address(self):
        """Test that monitoring works for specific addresses."""
        from main import AddressMonitor, ProxyServer

        # Create a mock server with a specific address
        mock_server = Mock(spec=ProxyServer)
        mock_server.address = "127.0.0.1"
        mock_server.port = 9999  # Use a port that's likely free

        monitor = AddressMonitor(
            server=mock_server,
            check_interval=0.1,
            check_timeout=0.05,
            original_address="127.0.0.1",
        )

        # Verify wildcard flag is not set
        assert monitor._is_wildcard is False

    @patch('main.get_all_local_addresses')
    def test_wildcard_initializes_addresses(self, mock_get_addresses):
        """Test that wildcard monitor initializes with current addresses."""
        from main import AddressMonitor, ProxyServer

        mock_get_addresses.return_value = ["127.0.0.1", "192.168.1.100"]

        mock_server = Mock(spec=ProxyServer)
        mock_server.address = "0.0.0.0"
        mock_server.port = 8080

        monitor = AddressMonitor(
            server=mock_server,
            check_interval=0.1,
            check_timeout=0.05,
            original_address="0.0.0.0",
        )

        # Start monitor to trigger initialization
        monitor._last_known_addresses = None
        monitor._check_wildcard_changes()
        
        assert monitor._last_known_addresses == ["127.0.0.1", "192.168.1.100"]

    @patch('main.get_all_local_addresses')
    @patch('main._print_listen_hints')
    def test_wildcard_detects_address_changes(self, mock_print_hints, mock_get_addresses):
        """Test that wildcard monitor detects address changes."""
        from main import AddressMonitor, ProxyServer

        # Initial addresses
        mock_get_addresses.return_value = ["127.0.0.1", "192.168.1.100"]

        mock_server = Mock(spec=ProxyServer)
        mock_server.address = "0.0.0.0"
        mock_server.port = 8080

        monitor = AddressMonitor(
            server=mock_server,
            check_interval=0.1,
            check_timeout=0.05,
            original_address="0.0.0.0",
        )

        # Initialize
        monitor._check_wildcard_changes()
        
        # Change addresses
        mock_get_addresses.return_value = ["127.0.0.1", "192.168.1.101"]
        
        # Check for changes
        changed = monitor._check_wildcard_changes()
        
        assert changed is True
        mock_print_hints.assert_called_once()
        assert monitor._last_known_addresses == ["127.0.0.1", "192.168.1.101"]


class TestAddressFunctions:
    """Test the new address utility functions."""

    def test_get_all_local_addresses_returns_loopback(self):
        """Test that get_all_local_addresses always returns loopback."""
        from main import get_all_local_addresses

        addresses = get_all_local_addresses()
        
        assert "127.0.0.1" in addresses
        assert "::1" in addresses

    def test_detect_address_changes_no_change(self):
        """Test detect_address_changes with no changes."""
        from main import detect_address_changes

        old = ["127.0.0.1", "192.168.1.100"]
        new = ["127.0.0.1", "192.168.1.100"]

        added, removed = detect_address_changes(old, new)
        
        assert added == []
        assert removed == []

    def test_detect_address_changes_added(self):
        """Test detect_address_changes with added address."""
        from main import detect_address_changes

        old = ["127.0.0.1"]
        new = ["127.0.0.1", "192.168.1.100"]

        added, removed = detect_address_changes(old, new)
        
        assert "192.168.1.100" in added
        assert removed == []

    def test_detect_address_changes_removed(self):
        """Test detect_address_changes with removed address."""
        from main import detect_address_changes

        old = ["127.0.0.1", "192.168.1.100"]
        new = ["127.0.0.1"]

        added, removed = detect_address_changes(old, new)
        
        assert added == []
        assert "192.168.1.100" in removed

    def test_detect_address_changes_both(self):
        """Test detect_address_changes with both added and removed."""
        from main import detect_address_changes

        old = ["127.0.0.1", "192.168.1.100"]
        new = ["127.0.0.1", "10.0.0.1"]

        added, removed = detect_address_changes(old, new)
        
        assert "10.0.0.1" in added
        assert "192.168.1.100" in removed
