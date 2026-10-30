import json
from pathlib import Path

import pytest

import desktop
from scripts.build_portable import selected_files
from scripts.lock_runtime import read_requirements, resolve_installed


def test_native_readiness_does_not_start_a_server(capsys):
    assert desktop.main(["--check"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["native_window"]
    assert report["interface"] == "native-qt"
    assert report["http_server_required"] is False


@pytest.mark.parametrize("args", [["--browser"], ["--port", "8508"], ["--shutdown-after", "-1"]])
def test_obsolete_or_invalid_launcher_options_are_rejected(args):
    with pytest.raises(SystemExit) as error:
        desktop.main(args)
    assert error.value.code == 2


def test_distribution_contains_the_native_runtime_and_no_web_app():
    root = Path(__file__).resolve().parents[1]
    selected = {path.relative_to(root).as_posix() for path in selected_files(root)}
    assert {"desktop.py", "stylemate/desktop/application.py", "stylemate/services/context.py"} <= selected
    assert not {"app.py", "desktop_web.py", ".streamlit/config.toml"} & selected
    dependencies = resolve_installed(read_requirements(root / "requirements.txt"))
    assert "pyside6" in dependencies
    assert "streamlit" not in dependencies
