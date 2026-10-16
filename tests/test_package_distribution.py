"""Exercise the installed wheel, independently of the source directory."""
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import build


def test_wheel_contains_runnable_package_and_resources(tmp_path):
    root = Path(__file__).resolve().parents[1]
    wheel = Path(build.ProjectBuilder(root).build('wheel', str(tmp_path / 'wheel')))
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        assert 'ghost_typer/run.py' in names
        assert 'ghost_typer/src/orchestrator.py' in names
        assert 'ghost_typer/icons/ghost_off.png' in names
        metadata = archive.read('ghost_typer-1.0.0.dist-info/METADATA').decode()
        assert 'Requires-Dist: anthropic' in metadata
        assert 'Requires-Dist: python-dotenv' in metadata
    target = tmp_path / 'installed'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-compile',
                    '--target', str(target), str(wheel)], check=True, capture_output=True)
    code = ('import sys; sys.path.insert(0, sys.argv[1]); '
            'sys.modules["tkinter"] = None; '
            'import ghost_typer.run, ghost_typer.src.models, ghost_typer.src.orchestrator; '
            'from importlib.metadata import distribution; '
            'assert any(e.name == "ghost-typer" and e.value == "ghost_typer.run:main" '
            'for e in distribution("ghost-typer").entry_points)')
    subprocess.run([sys.executable, '-I', '-c', code, str(target)],
                   cwd=tmp_path, check=True, capture_output=True)
