#!/usr/bin/env python3
"""
VA48 for Quest 3S — arm64 5.10.x port
=====================================

目标：用户态 VA48（T0SZ=16，4 级页表），内核映射保持 VA39 的地址布局。
内核也使用四级页表，因此 T1SZ 必须为 16；PAGE_OFFSET/VMEMMAP 不变。
默认 mmap、栈和 PIE 仍放在低 39 位，高地址通过 mmap hint 或固定映射使用。

与 H2Omeow/patch_va48.py (6.1) 的关键差异
-----------------------------------------
6.1 版把 VA_BITS_MIN 钉到 39。5.10 不能这么做：head.S:317 用
VA_BITS_MIN 初始化运行期变量 vabits_actual，而 TASK_SIZE_64 =
(1UL << vabits_actual)。钉成 39 会让用户态静默退回 39 位。

5.10 的做法：VA_BITS_MIN 保持 48（= VA_BITS），只把内核侧的
PAGE_OFFSET / PAGE_END / VMEMMAP_SIZE / KASAN_SHADOW_END 指向新引入的
KERNEL_VA_BITS；DEFAULT_MAP_WINDOW_64 单独保持 39 位，proc.S 中的
TCR_TxSZ(VA_BITS) 则保留 48 位，以匹配实际四级页表。

用法：
    python3 patch_va48_510.py <kernel_root> --check    # 只校验
    python3 patch_va48_510.py <kernel_root>            # 校验并写入
"""

import argparse
import re
import sys

KERNEL_VA_BITS = 39

MEMORY_H = "arch/arm64/include/asm/memory.h"
PROCESSOR_H = "arch/arm64/include/asm/processor.h"
PROC_S   = "arch/arm64/mm/proc.S"
MM_INIT  = "arch/arm64/mm/init.c"
MMU_C    = "arch/arm64/mm/mmu.c"
MM_UTIL  = "mm/util.c"
KCONFIG  = "arch/arm64/Kconfig"
KASLR_C  = "arch/arm64/kernel/kaslr.c"


class Plan:
    def __init__(self, root):
        self.root = root
        self.edits = []        # (relpath, label, old, new)
        self.requires = []     # (relpath, anchor, desc)
        self.errors = []

    def require(self, relpath, anchor, desc):
        self.requires.append((relpath, anchor, desc))

    def edit(self, relpath, label, old, new):
        self.edits.append((relpath, label, old, new))

    def preflight(self):
        cache = {}
        def read(relpath):
            if relpath not in cache:
                try:
                    with open(f"{self.root}/{relpath}") as source:
                        cache[relpath] = source.read()
                except OSError as e:
                    self.errors.append(f"{relpath}: 无法读取（{e}）")
                    cache[relpath] = None
            return cache[relpath]

        for relpath, anchor, desc in self.requires:
            source = read(relpath)
            if source is None:
                continue
            n = source.count(anchor)
            if n != 1:
                self.errors.append(
                    f"{relpath}: 前提锚点 {desc!r} 出现 {n} 次（需恰好 1 次）")
        for relpath, label, old, new in self.edits:
            source = read(relpath)
            if source is None:
                continue
            n = source.count(old)
            if n != 1:
                self.errors.append(
                    f"{relpath}: 编辑 {label!r} 的锚点出现 {n} 次（需恰好 1 次）")
        return cache


def build(plan):
    plan.require(KCONFIG, "config ARM64_4K_PAGES", "4K 页配置")
    plan.require(KCONFIG, "config ARM64_VA_BITS_48", "VA48 配置")
    plan.require(KCONFIG,
                 "\tdefault 3 if ARM64_4K_PAGES && ARM64_VA_BITS_39",
                 "VA39 三级页表")
    plan.require(KCONFIG,
                 "\tdefault 4 if !ARM64_64K_PAGES && ARM64_VA_BITS_48",
                 "VA48 四级页表")
    plan.require(MEMORY_H, "#define VA_BITS\t\t\t(CONFIG_ARM64_VA_BITS)",
                 "VA_BITS 定义")
    plan.require(MEMORY_H, "#define PAGE_OFFSET\t\t(_PAGE_OFFSET(VA_BITS))",
                 "PAGE_OFFSET 定义")
    plan.require(PROC_S, "TCR_TxSZ(VA_BITS)",
                 "TCR_TxSZ 单处设置")
    plan.require(KASLR_C, "mask = ((1UL << (VA_BITS_MIN - 2)) - 1)",
                 "KASLR 内核偏移范围")

    # ---- memory.h：引入内核侧固定位宽 ----
    plan.edit(MEMORY_H, "A1 引入 KERNEL_VA_BITS",
        "#define VA_BITS\t\t\t(CONFIG_ARM64_VA_BITS)",
        "#define VA_BITS\t\t\t(CONFIG_ARM64_VA_BITS)\n"
        "/*\n"
        " * 用户态 VA48 / 内核态 VA39。\n"
        " * 内核映射（PAGE_OFFSET/PAGE_END/vmemmap/fixmap/modules）全部固定在\n"
        " * KERNEL_VA_BITS，保持线性映射及 vmemmap 的原有地址布局；\n"
        " * 用户地址宽度仍由 CONFIG_ARM64_VA_BITS 决定。\n"
        " */\n"
        f"#define KERNEL_VA_BITS\t\t({KERNEL_VA_BITS})")

    plan.edit(MEMORY_H, "A2 固定 PAGE_OFFSET",
        "#define PAGE_OFFSET\t\t(_PAGE_OFFSET(VA_BITS))",
        "#define PAGE_OFFSET\t\t(_PAGE_OFFSET(KERNEL_VA_BITS))")

    plan.edit(MEMORY_H, "A3 固定 VMEMMAP_SIZE",
        "#define VMEMMAP_SIZE ((_PAGE_END(VA_BITS_MIN) - PAGE_OFFSET) \\",
        "#define VMEMMAP_SIZE ((_PAGE_END(KERNEL_VA_BITS) - PAGE_OFFSET) \\")

    plan.edit(MEMORY_H, "A4 固定 KASAN_SHADOW_END(非 KASAN 分支)",
        "#define KASAN_SHADOW_END\t(_PAGE_END(VA_BITS_MIN))",
        "#define KASAN_SHADOW_END\t(_PAGE_END(KERNEL_VA_BITS))")

    plan.edit(MEMORY_H, "A5 固定运行期 PAGE_END",
        "#define PAGE_END\t\t(_PAGE_END(vabits_actual))",
        "/* 运行期 vabits_actual = VA_BITS(48)，但内核映射终点固定为 VA39。 */\n"
        "#define PAGE_END\t\t(_PAGE_END(KERNEL_VA_BITS))")

    # ---- proc.S：硬件遍历级数必须匹配四级根表 ----
    plan.edit(PROC_S, "B1 保留 T0SZ=T1SZ=16 的四级表遍历",
        "\tmov_q\tx10, TCR_TxSZ(VA_BITS) | TCR_CACHE_FLAGS | TCR_SMP_FLAGS | \\",
        "\t/*\n"
        "\t * T0SZ and T1SZ both describe the hardware walk length, and the walk\n"
        "\t * length must match the compile-time page table levels. With 4K pages\n"
        "\t * and VA_BITS=48 that is four levels, so both halves get 48 bits here\n"
        "\t * even though the kernel half only ever uses the top 39.\n"
        "\t *\n"
        "\t * The 39-bit kernel layout is pinned by PAGE_OFFSET/PAGE_END in\n"
        "\t * asm/memory.h instead. Every kernel address has bits[47:39] set, so\n"
        "\t * it occupies PGD entry 511 and no other, which a four level walk\n"
        "\t * indexes correctly. Shrinking T1SZ to 25 would make the CPU start\n"
        "\t * walking at level 1 while the tables are built as level 0, which\n"
        "\t * silently mis-decodes the root table.\n"
        "\t */\n"
        "\tmov_q\tx10, TCR_TxSZ(VA_BITS) | \\\n"
        "\t\t\tTCR_CACHE_FLAGS | TCR_SMP_FLAGS | \\")

    # ---- 默认地址布局保持 VA39，高 hint 仍可使用 TASK_SIZE_64 的 VA48 ----
    plan.edit(PROCESSOR_H, "B2 默认 mmap/栈/PIE 使用低 39 位窗口",
        "#define DEFAULT_MAP_WINDOW_64\t(UL(1) << VA_BITS_MIN)",
        "/* Keep default mmap/stack/PIE below 2^39; high hints may use VA48. */\n"
        "#define DEFAULT_MAP_WINDOW_64\t(UL(1) << KERNEL_VA_BITS)")

    # ---- 线性映射大小按内核位宽 ----
    plan.edit(MM_INIT, "C1 linear_region_size 用内核位宽",
        "\tconst s64 linear_region_size = BIT(vabits_actual - 1);",
        "\t/* 线性映射大小按 KERNEL_VA_BITS 计算，不随用户态 VA48 变化。 */\n"
        "\tconst s64 linear_region_size = BIT(KERNEL_VA_BITS - 1);")

    # ---- 四级页表下 4K 页也要走 PUD 复用路径 ----
    plan.edit(MMU_C, "D1 early_fixmap_init 放开 16K 限制",
        "\t\tBUG_ON(!IS_ENABLED(CONFIG_ARM64_16K_PAGES));\n"
        "\t\tbm_pgdp = pgd_offset_pgd(pgdp, FIXADDR_START);",
        "\t\t/* VA48/VA39 的 4K 四级页表同样复用该 PUD。 */\n"
        "\t\tbm_pgdp = pgd_offset_pgd(pgdp, FIXADDR_START);")

    plan.edit(MMU_C, "E1 map_kernel fixmap 放开 16K 限制",
        "\t\tBUG_ON(!IS_ENABLED(CONFIG_ARM64_16K_PAGES));\n"
        "\t\tpudp = pud_offset_kimg(p4dp, addr);",
        "\t\t/* VA48/VA39 的 4K 四级页表同样进入共享 PUD 路径。 */\n"
        "\t\tpudp = pud_offset_kimg(p4dp, addr);")

    # ---- 热插拔线性区起点 ----
    plan.edit(MMU_C, "F1 inside_linear_region 用固定 PAGE_OFFSET",
        "\tu64 start_linear_pa = __pa(_PAGE_OFFSET(vabits_actual));",
        "\t/* 线性映射起点按固定后的 VA39 PAGE_OFFSET 计算。 */\n"
        "\tu64 start_linear_pa = __pa(PAGE_OFFSET);")

    # ---- mmap 布局 ----
    plan.edit(MM_UTIL, "G1 mmap_base 下溢钳位",
        "\t\tmm->mmap_base = mmap_base(random_factor, rlim_stack);",
        "\t\tmm->mmap_base = mmap_base(random_factor, rlim_stack);\n"
        "\t\t/*\n"
        "\t\t * 默认 mmap 窗口仍按 VA39 的 STACK_TOP 布置；若随机偏移\n"
        "\t\t * 使 mmap_base 越过 STACK_TOP，回落到一个安全值。\n"
        "\t\t */\n"
        "\t\tif (mm->mmap_base >= STACK_TOP)\n"
        "\t\t\tmm->mmap_base = STACK_TOP - (STACK_TOP >> 3);")

    plan.edit(KCONFIG, "H1 把 VA48 的随机化上限压回 VA39 的值",
        "       default 33 if ARM64_VA_BITS=48",
        "# 默认 mmap 窗口保留 VA39，随机偏移上限也必须保留 24 位。\n"
        "       default 24 if ARM64_VA_BITS=48")

    # ---- KASLR：内核镜像必须仍落在 VA39 窗口内 ----
    plan.edit(KASLR_C, "J1 KASLR 偏移范围用内核位宽",
        "\tmask = ((1UL << (VA_BITS_MIN - 2)) - 1) & ~(SZ_2M - 1);\n"
        "\toffset = BIT(VA_BITS_MIN - 3) + (seed & mask);",
        "\t/*\n"
        "\t * 内核映射固定在 KERNEL_VA_BITS(39)，随机化范围不能按\n"
        "\t * VA_BITS_MIN(48) 计算，否则镜像会被放到 VA39 窗口之外。\n"
        "\t */\n"
        "\tmask = ((1UL << (KERNEL_VA_BITS - 2)) - 1) & ~(SZ_2M - 1);\n"
        "\toffset = BIT(KERNEL_VA_BITS - 3) + (seed & mask);")

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tree_root", nargs="?", default=".")
    ap.add_argument("--check", action="store_true", help="只检查，不写文件")
    args = ap.parse_args(argv)

    plan = Plan(args.tree_root)
    build(plan)
    cache = plan.preflight()

    if plan.errors:
        print("✗ 前提检查失败，未修改任何文件：")
        for e in plan.errors:
            print("   -", e)
        return 1

    if args.check:
        print(f"✓ 全部 {len(plan.edits)} 处锚点校验通过（未写入）")
        for relpath, label, _, _ in plan.edits:
            print(f"   {relpath:34s} {label}")
        return 0

    for relpath, label, old, new in plan.edits:
        cache[relpath] = cache[relpath].replace(old, new, 1)
        print(f"   OK  {relpath:34s} {label}")

    for relpath in {e[0] for e in plan.edits}:
        open(f"{plan.root}/{relpath}", "w").write(cache[relpath])

    print(f"\n✓ 已应用 {len(plan.edits)} 处编辑")
    print("  接下来需要在 gki_defconfig 中设置：")
    print("    CONFIG_ARM64_VA_BITS_48=y   (PGTABLE_LEVELS 自动为 4)")
    print("    # 确认没有 CONFIG_ARM64_VA_BITS_39=y")
    return 0


if __name__ == "__main__":
    sys.exit(main())
