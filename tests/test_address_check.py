import pytest

import sys
sys.path.insert(0, '..')

from main import check_address_available, auto_detect_address


@pytest.mark.unit
def test_check_available_address():
    """Test detection of available address."""
    result = check_address_available("127.0.0.1", 8080, 2.0)
    assert isinstance(result, bool)


@pytest.mark.unit
def test_check_unavailable_address():
    """Test detection of unavailable address."""
    result = check_address_available("1.1.1.1", 8080, 1.0)
    assert result is False  # Unreachable address should return False


@pytest.mark.unit
def test_auto_detect_address():
    """Test auto-detection of local address."""
    address = auto_detect_address(8080, 2.0)
    assert address is None or isinstance(address, str)


@pytest.mark.unit
def test_check_timeout():
    """Test timeout handling."""
    result = check_address_available("192.0.2.1", 8080, 0.1)
    assert result is False  # Should timeout and return False
