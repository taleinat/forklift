#!/bin/bash
set -eu -o pipefail
hostname="$1"
shift
port="$1"
shift

exec 3<>"/dev/tcp/$hostname/$port"  # open tcp connection
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
