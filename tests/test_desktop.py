import desktop


def test_server_command_is_loopback_only_and_does_not_use_shell():
    command = desktop.server_command(8508)
    assert "--server.address=127.0.0.1" in command
    assert "--server.port=8508" in command
    assert "--browser.gatherUsageStats=false" in command
    assert command[1:4] == ["-m", "streamlit", "run"]
