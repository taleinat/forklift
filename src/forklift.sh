#!/bin/bash
set -eu -o pipefail

runtime_dir="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}"
shopt -s nullglob
service_runtime_dirs=("$runtime_dir/forklift-$USER"-??????)
shopt -u nullglob
echo "${service_runtime_dirs[@]}"
if [[ ${#service_runtime_dirs[@]} -eq 0 ]]; then
  echo "Service not running." >&2
  exit 1
elif [[ ${#service_runtime_dirs[@]} -gt 1 ]]; then
  echo "Multiple service runtime dirs, argh!" >&2
  exit 1
fi
service_runtime_dir="${service_runtime_dirs[0]}"

IFS= read -r port <"$service_runtime_dir/black.port"
exec 3<>"/dev/tcp/127.0.0.1/$port"  # open tcp connection
echo "$@" >&3
#exec 3<&0  # redirect stdin into tcp connection

while IFS= read -r line; do
#  echo "$line"
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
      exit 1
      ;;
  esac
done <&3
exec 3<&-  # close fd
