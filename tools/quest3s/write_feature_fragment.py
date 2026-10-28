#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Write the resolved feature/build fragment after final olddefconfig."""
import argparse
from pathlib import Path

from complete_droidspaces_config import EXISTING_REQUIREMENTS, read_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    values = read_config(args.config)
    requested = dict.fromkeys(EXISTING_REQUIREMENTS, "y")
    requested.update(read_config(Path(__file__).with_name("droidspaces.config")))
    requested.update(dict.fromkeys("""
        ARM64_4K_PAGES ARM64_VA_BITS_48 QCOM_KGSL_GPU_VA48 KSU
        KSU_TRACEPOINT_HOOK TRACEPOINTS LTO_CLANG_THIN CFI_CLANG
    """.split(), "y"))
    requested["QCOM_KGSL"] = "m"
    requested["LOCALVERSION"] = '"-quest3s-va48"'
    mismatches = [f"CONFIG_{key}: expected {value}, found {values.get(key, 'n')}"
                  for key, value in sorted(requested.items())
                  if values.get(key) != value]
    if mismatches:
        parser.exit(1, "\n".join(mismatches) + "\n")
    disabled = """
        ARM64_16K_PAGES ARM64_64K_PAGES ARM64_VA_BITS_39 LTO_CLANG_FULL
        CFI_PERMISSIVE DEBUG_INFO DEBUG_INFO_BTF META_SAMPLE_PGO
        LOCALVERSION_AUTO
    """.split()
    if any(values.get(key, "n") != "n" for key in disabled):
        parser.exit(1, "Unexpected page-size/VA/LTO/debug/PGO option is enabled\n")
    lines = ["# Resolved Quest 3S feature and local build settings.",
             "# Merge after vendor/oculus_anorak_defconfig, then run olddefconfig."]
    lines.extend(f"CONFIG_{key}={value}" for key, value in sorted(requested.items()))
    lines.extend(f"# CONFIG_{key} is not set" for key in sorted(disabled))
    args.output.write_text("\n".join(lines) + "\n")
    print(f"Wrote {args.output} ({len(requested)} enabled/module settings)")


if __name__ == "__main__":
    main()
