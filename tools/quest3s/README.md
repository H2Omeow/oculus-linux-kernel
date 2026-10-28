# Quest 3S VA48 kernel tools

This directory accompanies the `va48-quest3s` branch of
[H2Omeow/oculus-linux-kernel](https://github.com/H2Omeow/oculus-linux-kernel/tree/va48-quest3s).
The target is based on Meta's official **Linux 5.10.246** source baseline
[`043e6bcc61899eaa759a3f1b76606a190c8bb918`](https://github.com/facebookincubator/oculus-linux-kernel/tree/043e6bcc61899eaa759a3f1b76606a190c8bb918).
It uses the complete
[`vendor/quest3s_va48_defconfig`](../../arch/arm64/configs/vendor/quest3s_va48_defconfig)
and identifies itself as `5.10.246-quest3s-va48`.

CPU and KGSL GPU VA48, NTSync, Droidspaces standard-mode kernel prerequisites,
and the pinned BakaSU kernel component are integrated. See
[FEATURE_STATUS.md](FEATURE_STATUS.md) for their configuration and runtime
limits, [VA48_VALIDATION.md](VA48_VALIDATION.md) for address-layout checks,
[MODULE_COMPATIBILITY.md](MODULE_COMPATIBILITY.md) for module ABI requirements,
and [BUILD_ARTIFACTS.md](BUILD_ARTIFACTS.md) for the recorded build evidence.
There is no Quest 3S device boot or feature-runtime result yet.

## Build the target kernel

Use a Linux host with Bash, GNU make/coreutils, a host C/C++ compiler, and
Clang/LLD/LLVM **23.1.4** on `PATH`. The recorded configuration uses that LLVM
version; other toolchains require new validation. Also install the AArch64 GNU
cross toolchain (`aarch64-linux-gnu-*`), bison, flex, bc, Perl, Python 3,
OpenSSL development headers, libelf development headers, pkg-config, rsync,
cpio, gzip, and xz. Package names vary by distribution. The GNU cross tools are
still required by this vendor Kbuild even with LLVM and its integrated
assembler. BTF is disabled in this configuration; enabling it adds a matching
`pahole` dependency.

Start with an independent clean checkout. The script uses `O=` and refuses
source trees containing in-tree generated configuration or ARM64 headers; it
does not remove an existing build's files.

```sh
git clone --branch va48-quest3s https://github.com/H2Omeow/oculus-linux-kernel.git
cd oculus-linux-kernel
tools/quest3s/build-kernel.sh
```

The script infers the source root from its `tools/quest3s` location. A source
root can also be supplied as its sole argument. It first loads the complete
`vendor/quest3s_va48_defconfig`, then builds `Image modules` with:

```text
ARCH=arm64 LLVM=1 LLVM_IAS=1 REAL_CC=clang
CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION=
```

`REAL_CC=clang` is required by the vendor Makefile. `LOCALVERSION=` preserves
the configuration's `-quest3s-va48` suffix while suppressing an extra automatic
SCM suffix. The output defaults to `out/quest3s-va48` under the source root.
Every invocation resets that output's configuration to the checked-in
defconfig; matching previously built objects can still be reused.

```sh
QUEST_BUILD_JOBS=8 QUEST_LLD_JOBS=2 QUEST_THINLTO_JOBS=2 \
  QUEST_BUILD_OUT="$PWD/out/quest3s-va48" tools/quest3s/build-kernel.sh
```

All three job counts must be positive integers. `QUEST_BUILD_OUT` may point
outside the checkout; a relative value is resolved from the caller's current
directory. The default make parallelism is 8. The bundled `ld.lld-limited`
wrapper finds `ld.lld` through `PATH` and bounds each relocatable link to 2
LLD threads, 2 ThinLTO jobs, and one LTO partition. The two thread/job limits
can be adjusted independently using the variables above. These are build
defaults, not a fixed memory limit; increase them to suit the available RAM
and other concurrent work.

The main outputs are `arch/arm64/boot/Image`, `vmlinux`, `.config`,
`Module.symvers`, and the modules throughout the output directory. Keep the
target `Image`, modules, configuration, and symbol versions from the same
build. Module installation, ramdisk/rootfs assembly, device-tree selection,
and deployment are separate steps; this script only builds the kernel.
If the resulting `Image` has allocatable data past the ARM64 boot header's
`image_size`, use the validated export procedure documented in
[BUILD_ARTIFACTS.md](BUILD_ARTIFACTS.md), rather than truncating it manually.

These are repeatable build instructions, not a claim of bit-for-bit
reproducibility. Matching artifact hashes also requires fixing the source
commit, full toolchain and host dependencies, build paths, timestamps, and
`KBUILD_BUILD_*` identity variables.

## EL1 hot handoff is a separate build

The stock-kernel loader lives in
[quest3s-el1-kexec](https://github.com/H2Omeow/quest3s-el1-kexec). The reported
device runs `5.10.240-g9cb2f620a9a8`; that is the loader's ABI target, not the
version of this custom kernel. Build the loader against the exact running
stock kernel's source/configuration, generated headers, toolchain, and
`Module.symvers`, and satisfy its module-signing policy. Neither the public
5.10.240 source alone nor this 5.10.246 target build proves that ABI match.

EL1 handoff does not restart the secure world. Active TEE ownership transfer
and draining in-flight SCM calls remain unresolved; the loader rejects
execution with the relevant bound drivers. See its
[TEE_HANDOFF.md](https://github.com/H2Omeow/quest3s-el1-kexec/blob/main/TEE_HANDOFF.md)
for the source audit and execution gates. Static checks and successful builds
cannot establish a numerical probability of successful device boot.

## Supporting tools and remaining validation

- `collect_device_info.sh` collects read-only device diagnostics when manually
  run on Android. It does not elevate privileges or perform a handoff.
- `patch_va48_510.py` and `patch_gpu_va48_quest.py` record the source ports;
  their changes are already applied to this branch. Do not reapply them to a
  patched checkout. `va48_layout_check.S` and `va48test/` support static and
  later device-side CPU address checks.
- `quest3s-features.config`, `droidspaces.config`, and their helper scripts
  record configuration integration. The complete target defconfig already
  includes these settings; the build script does not re-merge fragments.

The camera `cam_isp_context.o` and EVA `cvp_hfi.o` builds locally raise
`-Wframe-larger-than` to 8192 for the newer compiler. This only raises the
warning threshold: it does not reduce their stack frames or establish runtime
stack safety. Those paths still need measured stack usage and device stress
testing. The target also needs actual boot, vendor-module, camera/display,
GPU high-address, suspend/resume, container, NTSync, and BakaSU validation.
