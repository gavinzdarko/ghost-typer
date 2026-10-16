"""A losing launcher must leave the running instance's PID intact."""
import fcntl
import subprocess
import sys
from pathlib import Path


def test_losing_launcher_preserves_locked_pid(tmp_path):
    pid_file = tmp_path / "instance.pid"
    with pid_file.open("w+") as owner:
        owner.write("123456789")
        owner.flush()
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code = ("import run; from pathlib import Path; "
                "run.LOCK_FILE = Path(__import__('sys').argv[1]); "
                "run._check_single_instance()")
        result = subprocess.run([sys.executable, "-c", code, str(pid_file)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True)
        assert result.returncode == 1
        assert pid_file.read_text() == "123456789"


def test_successful_launcher_replaces_old_pid(tmp_path, monkeypatch):
    import run
    pid_file = tmp_path / "instance.pid"
    pid_file.write_text("123456789012345678901234567890")
    monkeypatch.setattr(run, "LOCK_FILE", pid_file)
    run._check_single_instance()
    try:
        import os
        assert pid_file.read_text() == str(os.getpid())
    finally:
        run._lock_fh.close()
        run._lock_fh = None
