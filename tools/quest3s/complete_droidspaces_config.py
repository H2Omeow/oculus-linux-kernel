#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Check or apply the missing standard Droidspaces prerequisites.

This uses scripts/config only; it never runs make or olddefconfig. The build
owner must subsequently resolve Kconfig and rerun this check against the final
configuration. DEVTMPFS_MOUNT is unnecessary for container mounts and does not
affect initramfs boots. The reference's extended-mode EVDI and virtual HCI are
outside this standard-mode fragment. TMPFS_XATTR/POSIX_ACL belong to the
reference's separate Mountify integration; they are not standard-mode additions.
"""

import argparse
from pathlib import Path
import re
import subprocess


EXISTING_REQUIREMENTS = """
NAMESPACES UTS_NS IPC_NS USER_NS PID_NS NET_NS SYSVIPC POSIX_MQUEUE NTSYNC
CGROUPS CGROUP_SCHED CGROUP_PIDS CGROUP_FREEZER CGROUP_DEVICE CGROUP_CPUACCT
MEMCG BLK_CGROUP CPUSETS CFS_BANDWIDTH
NET INET IPV6 NETFILTER NETFILTER_ADVANCED NETFILTER_XTABLES
IP_NF_IPTABLES IP_NF_NAT NF_NAT BRIDGE VETH TUN
OVERLAY_FS TMPFS PROC_FS SYSFS INOTIFY_USER SECCOMP SECCOMP_FILTER
""".split()


def read_config(path):
    return dict(re.findall(r"^CONFIG_(\w+)=(.*)$", path.read_text(), re.MULTILINE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    parser.add_argument("--config", type=Path, help="defaults to KERNEL/.config")
    parser.add_argument("--apply", action="store_true", help="update via scripts/config")
    args = parser.parse_args()
    config = args.config or args.kernel / ".config"
    fragment = Path(__file__).with_name("droidspaces.config")
    additions = read_config(fragment)
    values = read_config(config)

    missing = [name for name in EXISTING_REQUIREMENTS if values.get(name) != "y"]
    if missing:
        parser.exit(1, "Existing container prerequisites need review: "
                    + ", ".join(missing) + "\n")

    pending = [name for name, value in additions.items() if values.get(name) != value]
    for name in pending:
        print(f"CONFIG_{name}: {values.get(name, 'n')} -> {additions[name]}")
    if args.apply and pending:
        command = [str(args.kernel.resolve() / "scripts/config"),
                   "--file", str(config.resolve())]
        for name in pending:
            command.extend(["--enable", name])
        subprocess.run(command, check=True)
        values = read_config(config)
        if any(values.get(name) != value for name, value in additions.items()):
            parser.exit(1, "scripts/config did not preserve the requested values\n")
        print("Applied fragment; resolve Kconfig in the final build, then rerun this check.")
    elif pending:
        parser.exit(1, f"{len(pending)} standard Droidspaces prerequisites missing\n")
    else:
        print("Standard Droidspaces prerequisites and existing container requirements are enabled.")


if __name__ == "__main__":
    main()
