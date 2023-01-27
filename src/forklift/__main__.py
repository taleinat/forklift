import hashlib
import io
import os
import random
import shlex
import signal
import socket
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, BinaryIO, Tuple, Union, cast

from vendor.filelock import FileLock

from .__version__ import __version__
from .tools import ToolExceptionBase, get_tool_runner
from .utils import pid_exists


class _SocketWriter(io.BufferedIOBase):
    """TODO!"""

    def __init__(self, sock: socket.socket, prefix: Union[bytes, bytearray]) -> None:
        self._sock = sock
        self._prefix = prefix

    def writable(self) -> bool:
        return True

    def write(self, b: Union[bytes, bytearray]) -> int:  # type: ignore[override]
        n_newlines = b.count(10)
        # print(b"%b%d\n%b\n" % (self._prefix, n_newlines, b), file=sys.__stderr__)
        self._sock.sendall(b"%b%d\n%b\n" % (self._prefix, n_newlines, b))
        # print("DONE WRITING", file=sys.__stderr__)
        with memoryview(b) as view:
            return view.nbytes

    def fileno(self) -> Any:
        return self._sock.fileno()


def get_service_runtime_dir_path() -> Path:
    runtime_dir = os.getenv("XDG_RUNTIME_DIR")
    if runtime_dir:
        service_runtime_dir = Path(runtime_dir) / "forklift"
        service_runtime_dir.mkdir(exist_ok=True, mode=0o700)
        return service_runtime_dir

    temp_dir_path = Path(tempfile.gettempdir())
    service_runtime_dirs = list(
        temp_dir_path.glob(f"forklift-{os.getenv('USER')}-??????")
    )
    if service_runtime_dirs:
        if len(service_runtime_dirs) > 1:
            raise Exception("Error: Multiple service runtime dirs found.")
        return service_runtime_dirs[0]

    lock = FileLock(temp_dir_path / f"forklift-{os.getenv('USER')}.lock")
    with lock:
        service_runtime_dirs = list(
            temp_dir_path.glob(f"forklift-{os.getenv('USER')}-??????")
        )
        if service_runtime_dirs:
            return service_runtime_dirs[0]

        random_part = "".join(
            [random.choice(string.ascii_letters) for _i in range(6)]
        )
        service_runtime_dir = (
                temp_dir_path / f"forklift-{os.getenv('USER')}-{random_part}"
        )
        service_runtime_dir.mkdir(exist_ok=False, mode=0o700)
        return service_runtime_dir


def get_isolated_service_runtime_dir_path(tool_name) -> Path:
    service_runtime_dir = get_service_runtime_dir_path()

    tool_executable_path: bytes = subprocess.run(f"command -v {shlex.quote(tool_name)}", shell=True, check=True, capture_output=True).stdout.strip()
    tool_executable_dir_path: bytes = os.path.dirname(tool_executable_path)
    tool_executable_dir_path_hash: str = hashlib.sha256(tool_executable_dir_path).hexdigest()[:8]
    isolated_path: Path = service_runtime_dir / tool_executable_dir_path_hash

    isolated_path.mkdir(exist_ok=True, mode=0o700)
    return isolated_path


def get_pid_and_port_file_paths(tool_name: str) -> Tuple[Path, Path]:
    service_runtime_dir_path = get_isolated_service_runtime_dir_path(tool_name)
    pid_file_path = service_runtime_dir_path / f"{tool_name}.pid"
    port_file_path = service_runtime_dir_path / f"{tool_name}.port"
    return pid_file_path, port_file_path


def remove_pid_and_port_files(tool_name: str):
    for file_path in get_pid_and_port_file_paths(tool_name):
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass


def start(tool_name: str, daemonize: bool = True) -> None:
    tool_runner = get_tool_runner(tool_name)

    pid_file_path, port_file_path = get_pid_and_port_file_paths(tool_name)

    if pid_file_path.exists():
        file_pid = int(pid_file_path.read_text())
        if pid_exists(file_pid):
            raise Exception("Forklift process already exists.")

    if daemonize:
        # Do the double-fork dance to daemonize.
        # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")

        pid = os.fork()
        if pid > 0:
            print(f'"forklift {tool_name}" daemon process starting...')
            sys.exit(0)

        # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")

        os.setsid()

        # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")

        pid = os.fork()
        if pid > 0:
            sys.exit(0)

        # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")

        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        stdin = open("/dev/null", "rb")
        stdout = open("/dev/null", "ab")
        stderr = open("/dev/null", "ab")
        os.dup2(stdin.fileno(), sys.stdin.fileno())
        os.dup2(stdout.fileno(), sys.stdout.fileno())
        os.dup2(stderr.fileno(), sys.stderr.fileno())

    # Write pid file.
    pid = os.getpid()
    pid_file_path.write_bytes(b"%d\n" % pid)

    # Open socket.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    port_file_path.write_bytes(b"%d\n" % port)

    # Listen for connections.
    try:
        sock.listen()
        print(f"Listening on {host}:{port} (pid={pid}) ...")
        while True:
            conn, address = sock.accept()
            print(f"Got connection from: {address}")
            if os.fork() == 0:
                break
    except:
        # Cleanup upon daemon shutdown.
        sock.close()
        if pid_file_path.exists():
            file_pid = int(pid_file_path.read_text())
            if file_pid == pid:
                pid_file_path.unlink(missing_ok=True)
                port_file_path.unlink(missing_ok=True)
        raise

    # TODO: Need to do something like the double-fork dance to decouple from the parent process?
    # See:
    # * https://stackoverflow.com/a/5386753
    # * https://www.win.tue.nl/~aeb/linux/lk/lk-10.html

    rfile = conn.makefile("rb", 0)
    stdin2 = open("/dev/null", "rb")
    os.dup2(stdin2.fileno(), sys.stdin.fileno())
    sys.stdout = io.TextIOWrapper(
        cast(BinaryIO, _SocketWriter(conn, b"1")), write_through=True
    )
    sys.stderr = io.TextIOWrapper(
        cast(BinaryIO, _SocketWriter(conn, b"2")), write_through=True
    )

    # start_time = time.monotonic()
    sys.argv[1:] = shlex.split(rfile.readline().strip().decode())
    try:
        sys.argv[0] = tool_name
        tool_runner()
    except SystemExit as exc:
        # end_time = time.monotonic()
        # print(f"Time: {end_time - start_time}", file=sys.__stdout__)
        exit_code = exc.code
        # print("EXCEPTION", str(exc), file=sys.__stderr__)
        # print(f"{exit_code=}", file=sys.__stdout__)
        if isinstance(exit_code, bool):
            exit_code = int(exit_code)
        elif not isinstance(exit_code, int):
            exit_code = 1
        conn.sendall(f"rc={exit_code}\n".encode())
        # print("Goodbye!", file=sys.__stdout__)
    finally:
        try:
            rfile.close()
        except Exception:
            pass
        sys.stdout.close()
        sys.stderr.close()
        conn.shutdown(socket.SHUT_WR)


def stop(tool_name: str) -> None:
    try:
        pid_file_path, _port_file_path = get_pid_and_port_file_paths(tool_name)
        if not pid_file_path.exists():
            print(f'"forklift {tool_name}" daemon process not found.')
            sys.exit(1)

        file_pid = int(pid_file_path.read_text())
        if not pid_exists(file_pid):
            print(f'"forklift {tool_name}" daemon process not found.')
            sys.exit(1)

        os.kill(file_pid, signal.SIGTERM)
        for _i in range(20):
            time.sleep(0.05)
            if not pid_exists(file_pid):
                break
        else:
            os.kill(file_pid, signal.SIGKILL)

        print(f'"forklift {tool_name}" daemon process stopped.')

    finally:
        remove_pid_and_port_files(tool_name)


def print_usage() -> None:
    print(f"Usage: {sys.argv[0]} start|stop tool_name")


def main() -> None:
    args = sys.argv[1:]

    if len(args) == 1:
        (cmd,) = args
        if cmd == "-h" or cmd == "--help":
            print_usage()
            sys.exit(0)
        elif cmd == "version" or cmd == "--version":
            print(f"forklift v{__version__}")
            sys.exit(0)
    elif len(args) == 2:
        (cmd, tool_name) = args
        tool_name = tool_name.strip().lower()
        try:
            if cmd == "start":
                start(tool_name)
                sys.exit(0)
            elif cmd == "stop":
                stop(tool_name)
                sys.exit(0)
            elif cmd == "restart":
                stop(tool_name)
                start(tool_name)
                sys.exit(0)
        except ToolExceptionBase as exc:
            print(str(exc))
            sys.exit(1)

    print_usage()
    sys.exit(1)


if __name__ == "__main__":
    main()
