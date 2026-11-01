# Quest 3S VA48 Kernel

This branch keeps the experimental Linux 5.10.246 full-feature kernel tree and its
feature/compile documentation. It is not the current bringup target.

The current headset bringup target is built from branch handoff/240-H2O, based on
the exact 5.10.240 vendor commit 729ec6c4b2086454e0157cbc810f5a460789cc67, with
the VA48 feature fragment; it produces 5.10.240-va48-H2O and 267 modules. The
bringup-2 release is built from that branch. See tools/quest3s/README-240.md on
handoff/240-H2O for the current build/artifact/validation notes.

The 5.10.246 full-defconfig path below is kept as a feature/compile regression
path, not as the release artifact.

Build instructions, configuration details, artifact fingerprints, module
checks, and remaining validation are documented in
[`tools/quest3s/README.md`](tools/quest3s/README.md). The full configuration is
[`arch/arm64/configs/vendor/quest3s_va48_defconfig`](arch/arm64/configs/vendor/quest3s_va48_defconfig).

## Validation boundary

For this 246 reference tree, the kernel Image and 257 modules built successfully on the host. Static checks
confirm the 4 KiB four-level VA48 layout, embedded configuration, CFI metadata,
and module symbol CRCs. This establishes that the source builds coherently; it
does not establish that the kernel boots on a headset. The 246 reference tree is based on
the public 5.10.246 source, while the current 240 release target is based on the
exact 5.10.240 vendor tree described above; the device runs `5.10.240-g9cb2f620a9a8`.

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
