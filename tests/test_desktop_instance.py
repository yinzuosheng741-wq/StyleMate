import subprocess
import sys
from pathlib import Path

from stylemate.desktop.instance import acquire_instance_lock


def test_concurrent_process_is_rejected_and_next_launch_works_after_unlock(tmp_path):
    lock = acquire_instance_lock(tmp_path)
    assert lock is not None
    script = ("from pathlib import Path; from stylemate.desktop.instance import acquire_instance_lock; "
              "import sys; lock=acquire_instance_lock(Path(sys.argv[1])); sys.exit(0 if lock else 2)")
    def launch():
        return subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                              cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15).returncode
    try:
        assert launch() == 2
    finally:
        lock.unlock()
    assert launch() == 0
