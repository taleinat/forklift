#!/bin/bash
set -eEu -o pipefail

function usage() {
  echo "Usage: $0 command tool_name ..."
  echo
  echo "Available commands:"
  echo
  echo "start tool_name            Start a background daemon for a CLI tool."
  echo "stop tool_name             Stop a background daemon for a CLI tool."
  echo "restart tool_name          Restart a background daemon for a CLI tool."
  echo "run tool_name [arg ...]    Run a CLI tool using a background process."
  echo
}

case "${1:-}" in
-h|--help)
  usage && exit 0 ;;
start|stop|restart|version|--version)
  exec forkliftctl "$@" ;;
run)
  shift
  [[ $# -eq 0 ]] && usage && exit 1
  tool_name="$1"
  shift
  ;;
*)
  usage && exit 1 ;;
esac


# Find service runtime directory.
runtime_dir="${XDG_RUNTIME_DIR}"
if [ -n "$runtime_dir" ]; then
  service_runtime_dir="$runtime_dir/forklift"
else
  temp_dir="${TMPDIR:-/tmp}"
  shopt -s nullglob
  service_runtime_dirs=("$temp_dir/forklift-$USER"-??????)
  shopt -u nullglob
  if [[ ${#service_runtime_dirs[@]} -eq 0 ]]; then
    echo "Service not running." >&2
    exit 1
  elif [[ ${#service_runtime_dirs[@]} -gt 1 ]]; then
    echo "Error: Multiple service runtime dirs found." >&2
    exit 1
  fi
  service_runtime_dir="${service_runtime_dirs[0]}"
fi

# Calculate the isolated path for pid and port files.
isolated_root="$(dirname "$(command -v "$tool_name")")"
isolated_root_hash="$(echo -n "$isolated_root" | sha256sum - | head -c 8)"
isolated_path="$service_runtime_dir/$isolated_root_hash/"

# Read port from port file.
if [ ! -f "$isolated_path/$tool_name.port" ]; then
  echo "Service not running." >&2
  exit 1
fi
IFS= read -r port <"$isolated_path/$tool_name.port"

# Open TCP connection.
exec 3<>"/dev/tcp/127.0.0.1/$port"

# Close TCP connection upon exit.
function close_connection {
  exec 3<&-
}
trap close_connection EXIT

# Write cmdline arguments to tcp connection.
echo "$@" >&3
# TODO: Redirect stdin into tcp connection.
# Note: It seems this will require re-writing in C or some such.

# TODO: Forward signals to daemon sub-process or make part of this process group.

# Read stdout and stderr from connection, line by line, and echo them.
IFS=
while read -r line; do
  case "$line" in
    1*)
      n_newlines="${line:1}"
      for (( i=1; i <= n_newlines; i++ )); do
        read -r line <&3
        echo "$line"
      done
      read -r line <&3
      echo -n "$line"
      ;;
    2*)
      n_newlines="${line:1}"
      for (( i=1; i <= n_newlines; i++ )); do
        read -r line <&3
        echo "$line" >&2
      done
      read -r line <&3
      echo -n "$line" >&2
      ;;
    rc=*)
      rc="${line:3}"
      exit "$rc"
      ;;
    *)
      echo "Error: Unexpected output from forklift daemon." >&2
      exit 1
      ;;
  esac
done <&3
