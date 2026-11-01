# RPMh warm-handoff handling (5.10.240-va48-H2O)

## Symptom

After an EL1 kexec handoff, the target kernel can boot its own image, but as
soon as the Android ramdisk loads the RPMh stack the device resets after about
21 seconds.  This document records the code-level failure hypothesis and the
mitigation in the 5.10.240 target.

## Why the RSC is not in a clean state

The kexec path does not reset the RPMh Resource State Controller (RSC).  A
warm handoff therefore inherits:

* the previous kernel's `TCS_AMC_MODE_ENABLE` / `TCS_AMC_MODE_TRIGGER` bits;
* `RSC_DRV_CMD_ENABLE` and `RSC_DRV_CMD_WAIT_FOR_CMPL` for an in-flight TCS;
* pending bits in `RSC_DRV_IRQ_STATUS`.

The new kernel starts with `drv->tcs_in_use` zeroed.  Upstream
`tcs_is_free()` only checked that bitmap, so `find_free_tcs()` could select a
TCS that the old kernel had left busy.  `__tcs_buffer_write()` also ORs the new
command mask into the old `RSC_DRV_CMD_ENABLE` value.  If the old completion
was already consumed by the old kernel, the new request has no completion to
wait for.

The first active request after the Android ramdisk starts is commonly the BCM
voter (`drivers/interconnect/qcom/bcm-voter.c`, `rpmh_write_batch()` with
`RPMH_ACTIVE_ONLY_STATE`).  `RPMH_TIMEOUT_MS` in `drivers/soc/qcom/rpmh.c`
is 10 seconds; a timeout in `rpmh_write_batch()` reaches
`BUG_ON(1)`/`rpmh_rsc_debug()`'s `BUG_ON(busy)`.  The panic plus the
external reset/watchdog path is consistent with the observed ~21 s, but this
has not yet been confirmed with a target-side pstore or console log.

## Mitigation in this tree

`drivers/soc/qcom/rpmh-rsc.c`:

* `rpmh_rsc_clear_stale_state()` (called from `rpmh_rsc_probe()` after
  `bitmap_zero(drv->tcs_in_use, MAX_TCS_NR)` and before
  `platform_get_irq()`):
  * disables the RSC IRQ;
  * clears `RSC_DRV_IRQ_STATUS`;
  * for every TCS, drops the AMC trigger/enable bits and clears
    `RSC_DRV_CMD_ENABLE` / `RSC_DRV_CMD_WAIT_FOR_CMPL`;
  * clears a final completion status; the probe then requests the IRQ and
    enables it.
* `tcs_is_free()` now also reads `RSC_DRV_STATUS`; a TCS that is still
  hardware-busy is not claimed even when its software bit is clear.  The
  register is documented in-tree as "zero if tcs is busy".
* `rpmh_write_batch()` and `rpmh_rsc_debug()` keep their `BUG_ON()`
  semantics: a late completion can still refer to a request that was already
  timed out, so returning early would risk a use-after-free.

The cleanup is a no-op on a cold boot apart from the temporary IRQ disable.

## Configuration

The patched driver is only used when the target's own RPMh core runs.  If
the Android vendor ramdisk loads the stock `qcom_rpmh.ko`, that module has
none of the cleanup code.  The target fragment therefore builds the core in:

```
CONFIG_QCOM_COMMAND_DB=y
CONFIG_QCOM_RPMH=y
```

The clock, regulator and interconnect providers stay modules.  Building the
whole provider set in (`COMMON_CLK_QCOM`, `QCOM_CLK_RPMH`,
`REGULATOR_RPMH`, `INTERCONNECT_QCOM*`) fails at the vmlinux link because
those vendor objects reference `regulator_proxy_consumer_sync_state`,
`gdsc_debug_print_regs`, `devm_regulator_proxy_consumer_register` and
`socinfo_get_part_info`, which are only provided by other modules.  The
stock provider modules call the exported `rpmh_write()` /
`rpmh_write_batch()` API of the built-in core, so they can still drive the
resources after the core has cleaned the inherited RSC state.

`CONFIG_REGULATOR_QCOM_RPMH` and `CONFIG_QCOM_RPMHPD` are **not** needed on
this device.  Quest's regulator nodes use `qcom,rpmh-vrm-regulator` /
`qcom,rpmh-arc-regulator` and bind to the generic
`drivers/regulator/rpmh-regulator.c` (`CONFIG_REGULATOR_RPMH`).  The
`CLUSTER_PD` power domain is the PSCI cluster domain, not an RPMh power
domain.

## Build and test status

* Base: 5.10.240 vendor tree `729ec6c4b2086454e0157cbc810f5a460789cc67`
* Branch: `handoff/240-H2O`
* Branch head with this change: `c8092688d333d0492e0585cb054aca3bf985ceba`
  (the RPMh driver change itself is `657f264d15962882ff0a697c67f33b5a25ef4e52`)
* Target build run: `41292654740`, artifact `13078212080`
* `Image.el1`: 34,804,224 B, SHA256
  `ff317fb1a97fb5b163f014e24fb32d0f423a795a5d7eba1cf543a34d0a4aec28`;
  `Image`: 36,438,068 B, SHA256
  `4e6f4a98172c7bf702d507d5f3fdecc0e0cdfa68512f9920ff74b485cacfddcd`
* 265 modules.  `config-used.txt` confirms `CONFIG_QCOM_COMMAND_DB=y`,
  `CONFIG_QCOM_RPMH=y`, `CONFIG_COMMON_CLK_QCOM=m`,
  `CONFIG_QCOM_CLK_RPMH=m`, `CONFIG_REGULATOR_RPMH=m`,
  `CONFIG_INTERCONNECT_QCOM=m`, `CONFIG_INTERCONNECT_QCOM_RPMH=m`,
  `CONFIG_INTERCONNECT_QCOM_BCM_VOTER=m`.
* `missing-modules.txt` lists `cmd_db`, `kernelsu`, `qcom_rpmh` and
  `quest_el1_kexec`: the first three are built into the Image, and the last
  is the loader module, not a target module.
* No headset run has confirmed the fix yet.

To test with a stock Android ramdisk, keep qseecom enabled
(`DISABLE_QSEECOM=0` in `bringup.sh`) and make sure the initrd does not
overlap the DTB; the 18 MB stock initrd cannot use the default
`INITRD_ADDR=0xaca00000` with `DTB_ADDR=0xacc00000`.  Capture pstore and the
target console before drawing conclusions.
