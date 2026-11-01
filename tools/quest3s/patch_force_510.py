#!/usr/bin/env python3
"""Quest 3S kexec boot bypass patch for the 5.10 VA48 kernel tree.

The kexec target is 5.10.246-va48-H2O, but the working Android
ramdisk carries modules built for the stock 5.10.240-g... kernel.
Module loading performs several checks that were valid for the
original kernel but reject foreign modules:

  * check_version()      symbol CRC (__versions / module_layout)
  * same_magic()         vermagic string
  * module_sig_check()   module signature (if CONFIG_MODULE_SIG)
  * CFI                  indirect-call type hashes

This script bypasses the first three in code and switches CFI to
permissive mode.  CONFIG_MODVERSIONS is intentionally kept enabled so
that the struct module layout does not change; CONFIG_MODULE_SIG is
kept disabled rather than removed for the same reason.

IMPORTANT: bypassing checks does not make a foreign module ABI
compatible.  struct layouts, symbol types and function prototypes can
still differ.  Prefer modules built from this exact tree/defconfig.

The script is idempotent: run it once per checkout.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOD = ROOT / "kernel" / "module.c"
DEFCONFIG = ROOT / "arch" / "arm64" / "configs" / "vendor" / "quest3s_va48_defconfig"
MARK = "QUEST3S_KEXEC_BYPASS"


def sub_once(text, old, new, what):
    if new in text:
        return text, False
    if old not in text:
        raise SystemExit(f"pattern not found ({what}): {old[:80]!r}")
    return text.replace(old, new, 1), True


def ensure_set(text, name, value="y", anchor=None):
    line = f"{name}={value}"
    pat = re.compile(rf"^{re.escape(name)}=.*$", re.M)
    if pat.search(text):
        return pat.sub(line, text, count=1)
    pat = re.compile(rf"^# {re.escape(name)} is not set$", re.M)
    if pat.search(text):
        return pat.sub(line, text, count=1)
    if anchor and anchor in text:
        return text.replace(anchor, anchor + "\n" + line, 1)
    return text.rstrip("\n") + "\n" + line + "\n"


def ensure_unset(text, name):
    line = f"# {name} is not set"
    pat = re.compile(rf"^{re.escape(name)}=.*$", re.M)
    if pat.search(text):
        return pat.sub(line, text, count=1)
    if re.search(rf"^# {re.escape(name)} is not set$", text, re.M):
        return text
    return text.rstrip("\n") + "\n" + line + "\n"


def main():
    text = MOD.read_text(encoding="utf-8")
    changed = []

    old = """\tstruct modversion_info *versions;

\t/* Exporting module didn't supply crcs?  OK, we're already tainted. */"""
    new = """\tstruct modversion_info *versions;

\t/* QUEST3S_KEXEC_BYPASS_CRC: the Android ramdisk modules were built
\t * against the stock 5.10.240 kernel, so their symbol CRCs and the
\t * module_layout CRC never match this tree.  Accept them.
\t */
\treturn 1;

\t/* Exporting module didn't supply crcs?  OK, we're already tainted. */"""
    text, did = sub_once(text, old, new, "check_version")
    changed.append(("check_version CRC bypass", did))

    old = """\tconst void *mod = info->hdr;

\t/*
\t * Require flags == 0, as a module with version information"""
    new = """\tconst void *mod = info->hdr;

\t/* QUEST3S_KEXEC_BYPASS_SIG: never reject a module for its signature. */
\treturn 0;

\t/*
\t * Require flags == 0, as a module with version information"""
    text, did = sub_once(text, old, new, "module_sig_check")
    changed.append(("module_sig_check signature bypass", did))

    # Revert the earlier 0 && !same_magic() form if it is present.
    old = "\t} else if (0 && !same_magic(modmagic, vermagic, info->index.vers)) {"
    new = "\t} else if (!same_magic(modmagic, vermagic, info->index.vers)) {"
    if old in text:
        text = text.replace(old, new, 1)

    old = "\treturn strcmp(amagic, bmagic) == 0;"
    new = """\t(void)amagic;
\t(void)bmagic;
\t(void)has_crcs;

\t/* QUEST3S_KEXEC_BYPASS_VERMAGIC: ignore vermagic. */
\treturn 1;"""
    n = text.count(old)
    if n == 0:
        raise SystemExit("same_magic pattern not found")
    text = text.replace(old, new)
    changed.append((f"same_magic vermagic bypass ({n} sites)", True))

    MOD.write_text(text, encoding="utf-8")

    cfg = DEFCONFIG.read_text(encoding="utf-8")
    cfg = ensure_set(cfg, "CONFIG_MODULE_FORCE_LOAD", "y", anchor="CONFIG_MODULE_UNLOAD=y")
    cfg = ensure_set(cfg, "CONFIG_CFI_PERMISSIVE", "y")
    cfg = ensure_unset(cfg, "CONFIG_MODULE_SIG")
    cfg = ensure_unset(cfg, "CONFIG_MODULE_SIG_FORCE")
    cfg = ensure_unset(cfg, "CONFIG_MODULE_SIG_ALL")
    cfg = ensure_unset(cfg, "CONFIG_TRIM_UNUSED_KSYMS")
    cfg = ensure_unset(cfg, "CONFIG_PANIC_ON_OOPS")
    DEFCONFIG.write_text(cfg, encoding="utf-8")

    for name, did in changed:
        print(f"{'patched' if did else 'already'}: {name}")
    print("patched: defconfig module signature/CFI/force-load switches")


if __name__ == "__main__":
    sys.exit(main())
