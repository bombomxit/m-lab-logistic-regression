#!/usr/bin/env sh
set -eu

storage_dir="${1:-./storage}"
backup_dir="${2:-./backups}"
timestamp="$(date +%Y%m%d-%H%M%S)"

if [ ! -d "$storage_dir" ]; then
  echo "Không tìm thấy storage directory: $storage_dir" >&2
  exit 1
fi

mkdir -p "$backup_dir"
tar -czf "$backup_dir/ml-lab-$timestamp.tar.gz" "$storage_dir"
echo "Backup created: $backup_dir/ml-lab-$timestamp.tar.gz"
