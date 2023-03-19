import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def get_bin_path(project_path: Path) -> Path:
    return (
        project_path.parent / "venv" / ("Scripts" if sys.platform == "win32" else "bin")
    )


# @pytest.fixture(scope="session")
# def setup_testproj() -> Path:
#     with tempfile.TemporaryDirectory() as tmp_dir:
#         proj_dir = Path(tmp_dir) / "testproj"
#         shutil.copytree(Path(__file__).parent / "testproj", proj_dir)
#         venv_path = proj_dir / "venv"
#         subprocess.run([sys.executable, "-mvenv", str(venv_path)])
#         bin_path = get_bin_path(proj_dir)
#         subprocess.run([str(bin_path / "pip"), "install", ".", "black", "flake8", "isort"], cwd=str(Path(__file__).parents[1]), check=True)
#         yield proj_dir
#
#
# @pytest.fixture
# def testproj(setup_testproj, tmp_path) -> Path:
#     proj_dir = Path(tmp_path) / "testproj"
#     shutil.copytree(setup_testproj, proj_dir)
#     yield proj_dir


@pytest.fixture(scope="session")
def testproj() -> Path:
    with tempfile.TemporaryDirectory() as tmp_dir:
        proj_dir = Path(tmp_dir) / "testproj"
        sources_dir = Path(__file__).parent / "testproj"
        shutil.copytree(sources_dir, proj_dir)
        venv_path = Path(tmp_dir) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)])
        bin_path = get_bin_path(proj_dir)
        subprocess.run(
            [str(bin_path / "pip"), "install", ".", "black", "flake8", "isort"],
            cwd=str(Path(__file__).parents[1]),
            check=True,
        )
        yield proj_dir


@pytest.mark.parametrize(
    "tool_cmd",
    [
        ["black", "--check", "."],
        ["isort", "--check", "."],
        ["flake8"],
    ],
    ids=lambda tool_cmd: tool_cmd[0],
)
def test_forklift_start_run_stop(testproj, tool_cmd):
    without_forklift_proc = run(tool_cmd, proj_path=testproj)
    assert without_forklift_proc.returncode != 0
    run(["forklift", "start", tool_cmd[0]], proj_path=testproj, check=True)
    try:
        with_forklift_proc = run(["forklift", "run", *tool_cmd], proj_path=testproj)
    finally:
        run(["forklift", "stop", tool_cmd[0]], proj_path=testproj, check=True)

    assert with_forklift_proc.stdout == without_forklift_proc.stdout
    assert with_forklift_proc.stderr == without_forklift_proc.stderr
    assert with_forklift_proc.returncode == without_forklift_proc.returncode


def run(cmd: list[str], proj_path: Path, check: bool = False) -> subprocess.CompletedProcess[bytes]:
    pass_through_env_vars = {
        key: value
        for key, value in os.environ.items()
        if re.fullmatch(r"TMPDIR|USER|XDG_.*", key)
    }

    bin_path = get_bin_path(proj_path).resolve()
    return subprocess.run(
        cmd,
        check=check,
        cwd=str(proj_path),
        env={
            **pass_through_env_vars,
            "PATH": f"{str(bin_path)}:{os.getenv('PATH', '')}".strip(":"),
            "VIRTUAL_ENV": str(bin_path.parent),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
