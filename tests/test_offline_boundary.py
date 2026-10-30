import socket

import pytest


def test_outbound_calls_are_blocked_before_any_network_io(offline_network):
    with socket.socket() as connection:
        with pytest.raises(RuntimeError, match="network_disabled"):
            connection.connect(("192.0.2.1", 443))
    assert offline_network == [True]
    offline_network.clear()  # This case deliberately verifies the guard itself.
