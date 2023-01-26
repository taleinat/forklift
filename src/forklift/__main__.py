import io
import os
import random
import shlex
import signal
import socket
import string
import sys
import time
from pathlib import Path
from typing import cast, Any, BinaryIO, Tuple, Union

from .utils import pid_exists

# TODO: Make this generic.
from black import patched_main as black_main


class _SocketWriter(io.BufferedIOBase):
    """TODO!"""

    def __init__(self, sock: socket.socket, prefix: Union[bytes, bytearray]) -> None:
        self._sock = sock
        self._prefix = prefix
        self._buff = b""

    def writable(self) -> bool:
        return True

    def write(self, b: Union[bytes, bytearray]) -> int:  # type: ignore[override]
        # TODO: Support outputs without a line ending.
        *lines, lastline = b.split(b"\n")
        if lines:
            lines[0] = self._buff + lines[0]
            self._sock.sendall(b"".join(self._prefix + line + b"\n" for line in lines))
            self._buff = lastline
        else:
            self._buff += lastline
        with memoryview(b) as view:
            return view.nbytes

    def close(self):
        if self._buff:
            self._sock.send(self._prefix + self._buff + b"\n")
        super().close()

    def fileno(self) -> Any:
        return self._sock.fileno()


def get_service_runtime_dir_path() -> Path:
    runtime_dir = os.getenv("XDG_RUNTIME_DIR")
    if runtime_dir:
        service_runtime_dir = Path(runtime_dir) / "forklift"
        service_runtime_dir.mkdir(exist_ok=True, mode=0o700)
    else:
        temp_dir_path = Path(os.getenv("TMPDIR") or "/tmp")
        service_runtime_dirs = list(
            temp_dir_path.glob(f"forklift-{os.getenv('USER')}-??????")
        )
        if service_runtime_dirs:
            if len(service_runtime_dirs) > 1:
                raise Exception("Error: Multiple service runtime dirs found.")
            service_runtime_dir = service_runtime_dirs[0]
        else:
            # TODO: Fix race condition here.
            random_part = "".join(
                [random.choice(string.ascii_uppercase) for _i in range(6)]
            )
            service_runtime_dir = (
                temp_dir_path / f"forklift-{os.getenv('USER')}-{random_part}"
            )
            service_runtime_dir.mkdir(exist_ok=False, mode=0o700)

    return service_runtime_dir


def get_pid_and_port_files() -> Tuple[Path, Path]:
    service_runtime_dir_path = get_service_runtime_dir_path()
    pid_file_path = service_runtime_dir_path / "black.pid"
    port_file_path = service_runtime_dir_path / "black.port"
    return pid_file_path, port_file_path


def remove_pid_and_port_files():
    for file_path in get_pid_and_port_files():
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass


def start(daemonize: bool = False) -> None:
    pid_file_path, port_file_path = get_pid_and_port_files()

    if pid_file_path.exists():
        file_pid = int(pid_file_path.read_text())
        if pid_exists(file_pid):
            raise Exception("Forklift process already exists.")

    if daemonize:
        # Do the double-fork dance to daemonize.
        # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")

        pid = os.fork()
        if pid > 0:
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

    start_time = time.monotonic()
    sys.argv[1:] = shlex.split(rfile.readline().strip().decode())
    try:
        # TODO: Make this generic.
        sys.argv[0] = "black"
        black_main()
    except SystemExit as exc:
        end_time = time.monotonic()
        print(f"Time: {end_time - start_time}", file=sys.__stdout__)
        exit_code = exc.code
        print(f"{exit_code=}", file=sys.__stdout__)
        conn.sendall(f"rc={exit_code}\n".encode())
        print("Goodbye!", file=sys.__stdout__)
    finally:
        try:
            rfile.close()
        except Exception:
            pass
        sys.stdout.close()
        sys.stderr.close()
        conn.shutdown(socket.SHUT_WR)


def stop() -> None:
    try:
        pid_file_path, _port_file_path = get_pid_and_port_files()
        if not pid_file_path.exists():
            print("Forklift daemon process not found.")
            sys.exit(1)

        file_pid = int(pid_file_path.read_text())
        if not pid_exists(file_pid):
            print("Forklift daemon process not found.")
            sys.exit(1)

        os.kill(file_pid, signal.SIGTERM)
        for _i in range(20):
            time.sleep(0.05)
            if not pid_exists(file_pid):
                break
        else:
            os.kill(file_pid, signal.SIGKILL)

        print("Forklift daemon process stopped.")

    finally:
        remove_pid_and_port_files()


def main():
    args = sys.argv[1:]
    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} start|stop")
        sys.exit(1)
    (cmd,) = args

    if cmd == "start":
        start(daemonize=True)
    elif cmd == "stop":
        stop()
    else:
        print(f"Usage: {sys.argv[0]} start|stop")
        sys.exit(1)


if __name__ == "__main__":
    main()
