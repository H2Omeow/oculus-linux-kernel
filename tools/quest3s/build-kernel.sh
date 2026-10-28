#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: build-kernel.sh [kernel-root]

Build the Quest 3S VA48 kernel and its modules from a clean source tree.
When installed in tools/quest3s, kernel-root defaults to two levels above
this script. The output configuration is reset to vendor/quest3s_va48_defconfig
on each invocation; existing matching objects can still be reused.

Environment:
  QUEST_BUILD_OUT       Output directory (default: kernel-root/out/quest3s-va48)
                       Relative paths are resolved from the current directory.
  QUEST_BUILD_JOBS      Parallel make jobs (default: 8)
  QUEST_LLD_JOBS        Threads per relocatable LLD link (default: 2)
  QUEST_THINLTO_JOBS    ThinLTO jobs per relocatable LLD link (default: 2)

Use a clean checkout without in-tree build output. This script never cleans
the source tree, installs modules, or deploys the result to a device.
EOF
}

die() { printf 'build-kernel: %s\n' "$*" >&2; exit 1; }
positive_integer() { [[ "$2" =~ ^[1-9][0-9]*$ ]] || die "$1 must be a positive integer"; }

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi
(( $# <= 1 )) || { usage >&2; exit 2; }

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
kernel_arg=${1:-"$script_dir/../.."}
[[ -d "$kernel_arg" ]] || die "kernel source directory does not exist: $kernel_arg"
kernel_root=$(cd -- "$kernel_arg" && pwd -P)
[[ -f "$kernel_root/Makefile" && -f "$kernel_root/arch/arm64/configs/vendor/quest3s_va48_defconfig" ]] ||
    die "kernel-root must contain Makefile and arch/arm64/configs/vendor/quest3s_va48_defconfig"

jobs=${QUEST_BUILD_JOBS:-8}
lld_jobs=${QUEST_LLD_JOBS:-2}
thinlto_jobs=${QUEST_THINLTO_JOBS:-2}
positive_integer QUEST_BUILD_JOBS "$jobs"
positive_integer QUEST_LLD_JOBS "$lld_jobs"
positive_integer QUEST_THINLTO_JOBS "$thinlto_jobs"
export QUEST_LLD_JOBS="$lld_jobs" QUEST_THINLTO_JOBS="$thinlto_jobs"

for tool in make realpath clang ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip \
            aarch64-linux-gnu-gcc aarch64-linux-gnu-elfedit; do
    command -v "$tool" >/dev/null 2>&1 || die "required tool is not on PATH: $tool"
done
[[ -x "$script_dir/ld.lld-limited" ]] || die "missing executable: $script_dir/ld.lld-limited"
build_out=$(realpath -m -- "${QUEST_BUILD_OUT:-"$kernel_root/out/quest3s-va48"}")
[[ "$build_out" != "$kernel_root" ]] || die "QUEST_BUILD_OUT must differ from the source directory"

# Kbuild rejects O= when the source tree contains in-tree generated files.
# Do not run mrproper automatically: another build may still need those files.
for generated in .config include/config arch/arm64/include/generated; do
    [[ ! -e "$kernel_root/$generated" && ! -L "$kernel_root/$generated" ]] ||
        die "source tree contains $generated; use an independent clean checkout for this O= build"
done

make_args=(-C "$kernel_root" O="$build_out" -j"$jobs"
           ARCH=arm64 LLVM=1 LLVM_IAS=1 REAL_CC=clang
           CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION=
           LD="$script_dir/ld.lld-limited")
printf 'Source: %s\nOutput: %s\nParallel jobs: make=%s, LLD=%s, ThinLTO=%s\n' \
       "$kernel_root" "$build_out" "$jobs" "$lld_jobs" "$thinlto_jobs"
make "${make_args[@]}" vendor/quest3s_va48_defconfig
exec make "${make_args[@]}" Image modules
