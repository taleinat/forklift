import io
import os
import random
import shlex
import socket
import string
import sys
import time
from pathlib import Path
from typing import cast, Any, BinaryIO, Union

from .utils import pid_exists

# TODO: Make this generic.
from black import patched_main as main


class _SocketWriter(io.BufferedIOBase):
    """TODO!"""

    def __init__(self, sock: socket.socket, prefix: Union[bytes, bytearray]) -> None:
        self._sock = sock
        self._prefix = prefix
        self._buff = b""

    def writable(self) -> bool:
        return True

    def write(self, b: Union[bytes, bytearray]) -> int:  # type: ignore[override]
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
    runtime_dir_path = Path(
        os.getenv("XDG_RUNTIME_DIR") or os.getenv("TMPDIR") or "/tmp"
    )
    service_runtime_dirs = list(
        runtime_dir_path.glob(f"forklift-{os.getenv('USER')}-??????")
    )
    if service_runtime_dirs:
        if len(service_runtime_dirs) > 1:
            raise Exception("TODO")
        service_runtime_dir = service_runtime_dirs[0]
    else:
        random_part = "".join(
            [random.choice(string.ascii_uppercase) for _i in range(6)]
        )
        service_runtime_dir = (
            runtime_dir_path / f"forklift-{os.getenv('USER')}-{random_part}"
        )
        service_runtime_dir.mkdir(exist_ok=False, mode=0o700)

    return service_runtime_dir


if __name__ == "__main__":
    # # Do the double-fork dance to daemonize.
    # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")
    #
    # pid = os.fork()
    # if pid > 0:
    #     sys.exit(0)
    #
    # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")
    #
    # os.setsid()
    #
    # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")
    #
    # pid = os.fork()
    # if pid > 0:
    #     sys.exit(0)
    #
    # print(f"{os.getpid()=}, {os.getpgid(0)=}, {os.getsid(0)=}")

    service_runtime_dir_path = get_service_runtime_dir_path()
    pid_file_path = service_runtime_dir_path / "black.pid"
    port_file_path = service_runtime_dir_path / "black.port"

    # Set up pid file.
    if pid_file_path.exists():
        file_pid = int(pid_file_path.read_text())
        if pid_exists(file_pid):
            raise Exception("Forklift process already exists.")
    pid = os.getpid()
    pid_file_path.write_text(f"{pid}\n")

    # Open socket.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    port_file_path.write_text(f"{port}\n")

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
    sys.stdout = io.TextIOWrapper(
        cast(BinaryIO, _SocketWriter(conn, b"1")), write_through=True
    )
    sys.stderr = io.TextIOWrapper(
        cast(BinaryIO, _SocketWriter(conn, b"2")), write_through=True
    )

    pid = os.fork()
    if pid == 0:
        print(f"child proc started", file=sys.__stdout__)
        start = time.monotonic()
        sys.argv[1:] = shlex.split(rfile.readline().strip().decode())
        try:
            # TODO: Make this generic.
            main()
        finally:
            print("child proc ended", file=sys.__stdout__)
            print(f"Time: {time.monotonic() - start:.3f}", file=sys.__stdout__)
    else:
        try:
            _pid, wait_status = os.waitpid(pid, 0)
            print("done waiting for child proc", file=sys.__stdout__)
            exit_code = os.waitstatus_to_exitcode(wait_status)
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
