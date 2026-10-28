# Quest 3S VA48 Kernel

This branch adds an experimental Linux 5.10.246 target kernel for Quest 3S,
including CPU and KGSL GPU VA48, NTSync, BakaSU, and the standard-mode kernel
prerequisites for Droidspaces.

Build instructions, configuration details, artifact fingerprints, module
checks, and remaining validation are documented in
[`tools/quest3s/README.md`](tools/quest3s/README.md). The full configuration is
[`arch/arm64/configs/vendor/quest3s_va48_defconfig`](arch/arm64/configs/vendor/quest3s_va48_defconfig).

## Validation boundary

The kernel Image and 257 modules built successfully on the host. Static checks
confirm the 4 KiB four-level VA48 layout, embedded configuration, CFI metadata,
and module symbol CRCs. This establishes that the source builds coherently; it
does not establish that the kernel boots on a headset. The target is based on
the public 5.10.246 source, while the reported device currently runs
`5.10.240-g9cb2f620a9a8`.

The separate [EL1 handoff loader](https://github.com/H2Omeow/quest3s-el1-kexec)
does not require stock `CONFIG_KEXEC`, but still needs exact stock module ABI
artifacts and device memory/DT information. It currently refuses execution
when the relevant TEE drivers are bound: secure-world ownership transfer and
draining in-flight SCM calls have not been implemented. No headset boot or
handoff has been performed, and these checks do not support a numerical boot
success probability.

See [`tools/quest3s/FEATURE_STATUS.md`](tools/quest3s/FEATURE_STATUS.md) for
feature limits and [`tools/quest3s/BUILD_ARTIFACTS.md`](tools/quest3s/BUILD_ARTIFACTS.md)
for the host build evidence.
