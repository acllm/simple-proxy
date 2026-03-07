import pytest
import threading
import time

import sys
sys.path.insert(0, '..')

from main import ProxyServer, AddressMonitor, check_address_available


@pytest.mark.integration
def test_server_start_stop():
    """Test basic server start/stop cycle."""
    from main import make_proxy_handler, _ProxyConfig

    config = _ProxyConfig(
        listen="127.0.0.1",
        port=8888,
        timeout=60.0,
        auth_userpass=None,
        max_body=32 * 1024 * 1024,
        verbose=False,
    )
    handler_class = make_proxy_handler(config)
    server = ProxyServer(handler_class, "127.0.0.1", 8888)

    server.start()
    assert server.is_running()

    server.stop()
    assert not server.is_running()


@pytest.mark.integration
def test_server_restart():
    """Test server restart with new address."""
    from main import make_proxy_handler, _ProxyConfig

    config = _ProxyConfig(
        listen="127.0.0.1",
        port=8889,
        timeout=60.0,
        auth_userpass=None,
        max_body=32 * 1024 * 1024,
        verbose=False,
    )
    handler_class = make_proxy_handler(config)
    server = ProxyServer(handler_class, "127.0.0.1", 8889)

    server.start()
    assert server.is_running()

    # Restart with same address
    server.restart("127.0.0.1")
    assert server.is_running()

    server.stop()


@pytest.mark.integration
def test_monitor_creates_and_stops():
    """Test monitor lifecycle."""
    from main import make_proxy_handler, _ProxyConfig

    config = _ProxyConfig(
        listen="127.0.0.1",
        port=8890,
        timeout=60.0,
        auth_userpass=None,
        max_body=32 * 1024 * 1024,
        verbose=False,
    )
    handler_class = make_proxy_handler(config)
    server = ProxyServer(handler_class, "127.0.0.1", 8890)

    monitor = AddressMonitor(
        server=server,
        check_interval=0.5,  # Fast for testing
        check_timeout=1.0,
        original_address="127.0.0.1",
    )

    # Run monitor briefly
    thread = threading.Thread(target=monitor.run, daemon=True)
    thread.start()

    time.sleep(1.0)  # Let monitor run

    monitor.stop()
    thread.join(timeout=2.0)
