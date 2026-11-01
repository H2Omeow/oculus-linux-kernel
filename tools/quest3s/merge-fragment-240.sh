#!/bin/sh
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
out=1
if [ -z "$out" ]; then out=$root/out; fi
mkdir -p "$out"
cp "$root/tools/quest3s/device-5.10.240.config" "$out/.config"
"$root/scripts/kconfig/merge_config.sh" -m -O "$out" "$out/.config" "$root/tools/quest3s/handoff-240.fragment"
make -C "$root" O="$out" ARCH=arm64 olddefconfig
