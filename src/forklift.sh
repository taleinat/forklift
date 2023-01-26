#!/bin/bash
set -eEu -o pipefail

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

# Read port from port file.
if [ ! -f "$service_runtime_dir/black.port" ]; then
  echo "Service not running." >&2
  exit 1
fi
IFS= read -r port <"$service_runtime_dir/black.port"

# Open TCP connection.
exec 3<>"/dev/tcp/127.0.0.1/$port"

# Close TCP connection upon exit.
function close_connection {
  exec 3<&-
}
trap close_connection EXIT

# Write cmdline arguments to tcp connection.
echo "$@" >&3
# # Redirect stdin into tcp connection.
# exec 3<&0

# TODO: Forward signals to daemon sub-process or make part of this process group.

# Read stdout and stderr from connection, line by line, and echo them.
# TODO: Support outputs without a line ending.
while IFS= read -r line; do
  case "$line" in
    1*)
      echo "${line:1}" >&1
      ;;
    2*)
      echo "${line:1}" >&2
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
