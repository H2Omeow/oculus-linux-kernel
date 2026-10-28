#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Port the GPU TTBR0 VA48 concept from the SM8650 reference tree to the
Quest 3S (anorak / Gen7.6.0 / Adreno 740v3) 5.10 tree.

Differences from the reference patch, all of them forced by this tree:

  * The reference gates on adreno_is_gen7_2_0(); this tree has no such
    helper and the target is Gen7.6.0, so the gate is adreno_is_gen7_6_0().
  * The reference also patches a va_hint fast path in kgsl_as.c.  This tree
    has no va_hint at all, so that hunk has no equivalent and is dropped
    rather than invented.
  * This tree already reports the actual pagetable VA range through its
    existing query. No new userspace ABI is introduced.
  * Explicit SVM high hints can use the CPU's full window, while automatic
    SVM placement retains its original range. The shared locked reservation
    tree arbitrates overlap with non-SVM allocations.

Everything else is the same idea: leave the SMMU's own TTBR1 cfg alone, copy
it, raise only the copy's IAS to 48, and refuse to proceed if the allocator
returns something other than 48.

Usage:
    python3 -I patch_gpu_va48_quest.py --check  <tree>
    python3 -I patch_gpu_va48_quest.py --apply  <tree>
    python3 -I patch_gpu_va48_quest.py --revert <tree>
"""
import argparse
import difflib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

MARKER = "CONFIG_QCOM_KGSL_GPU_VA48"


class Plan:
    def __init__(self, root):
        self.root = root
        self.edits = []

    def edit(self, relpath, old, new, note):
        self.edits.append((relpath, old, new, note))

    def stage(self, reverse=False):
        """Validate every edit in memory before any source file is written."""
        original, changed = {}, {}
        edits = reversed(self.edits) if reverse else self.edits
        for relpath, old, new, note in edits:
            path = Path(self.root, relpath)
            if relpath not in original:
                original[relpath] = path.read_text(encoding="utf-8")
                changed[relpath] = original[relpath]
            before, after = (new, old) if reverse else (old, new)
            count = changed[relpath].count(before)
            if count != 1:
                raise ValueError("%s: anchor for %r matched %d times"
                                 % (relpath, note, count))
            changed[relpath] = changed[relpath].replace(before, after, 1)
        return original, changed

    def already_applied(self):
        path = os.path.join(self.root, "drivers/gpu/msm/kgsl_iommu.h")
        if not os.path.isfile(path):
            return False
        return MARKER in open(path, encoding="utf-8").read()

    def apply(self, original, changed):
        for relpath, text in original.items():
            if Path(self.root, relpath).read_text(encoding="utf-8") != text:
                raise ValueError("source changed after preflight: " + relpath)
        for relpath, text in changed.items():
            Path(self.root, relpath).write_text(text, encoding="utf-8")


def build(root):
    p = Plan(root)

    # ---- Kconfig switch -------------------------------------------------
    p.edit("drivers/gpu/msm/Kconfig",
           """config DEVFREQ_GOV_QCOM_ADRENO_TZ
""",
           """config QCOM_KGSL_GPU_VA48
	bool "Experimental 48-bit GPU TTBR0 virtual addresses"
	depends on ARM64 && 64BIT
	depends on QCOM_KGSL
	default n
	help
	  Extend only the non-secure GPU TTBR0 page tables past 39 bits,
	  after checking the powered SMMU IDR2 register for 48-bit support
	  and 4K translation granule support. The CPU address space, TTBR1
	  mappings, secure contexts and compat (32-bit) mappings keep their
	  existing layout.

	  This is experimental. A matching reconstructed KGSL module and
	  on-device validation are both required. If unsure, say N.

config DEVFREQ_GOV_QCOM_ADRENO_TZ
""",
           "KGSL VA48 Kconfig switch")

    # ---- header: ranges and per-iommu flag ------------------------------
    p.edit("drivers/gpu/msm/kgsl_iommu.h",
           """#define KGSL_IOMMU_VA_BASE64		0x4000000000ULL
#define KGSL_IOMMU_VA_END64		0x8000000000ULL
""",
           """#define KGSL_IOMMU_VA_BASE64		0x4000000000ULL
#define KGSL_IOMMU_VA_END64		0x8000000000ULL

/*
 * Experimental GPU-only TTBR0 ranges, used when CONFIG_QCOM_KGSL_GPU_VA48 is
 * enabled and the SMMU reports 48-bit support. All end addresses are
 * exclusive. These describe GPU virtual addresses only; nothing here changes
 * the CPU page tables.
 */
#define KGSL_IOMMU_SVM_END48		(1ULL << 48)
#define KGSL_IOMMU_VA_BASE48		(1ULL << 47)
#define KGSL_IOMMU_VA_END48		(1ULL << 48)
""",
           "VA48 range constants")

    p.edit("drivers/gpu/msm/kgsl_iommu.h",
           """	/** @cx_gdsc: CX GDSC handle in case the IOMMU needs it */
	struct regulator *cx_gdsc;
};
""",
           """	/** @cx_gdsc: CX GDSC handle in case the IOMMU needs it */
	struct regulator *cx_gdsc;
	/** @gpu_va48: TTBR0-only 48-bit addressing, set after a powered probe */
	bool gpu_va48;
};
""",
           "gpu_va48 flag in struct kgsl_iommu")

    # ---- SMMU IDR2 definitions -----------------------------------------
    p.edit("drivers/gpu/msm/kgsl_iommu.c",
           "#include <linux/bitfield.h>\n",
           "#include <asm/processor.h>\n\n#include <linux/bitfield.h>\n",
           "explicit TASK_SIZE include")

    p.edit("drivers/gpu/msm/kgsl_iommu.c",
           """#define KGSL_IOMMU_IDR1_OFFSET 0x24
#define IDR1_NUMPAGENDXB GENMASK(30, 28)
#define IDR1_PAGESIZE BIT(31)
""",
           """#define KGSL_IOMMU_IDR1_OFFSET 0x24
#define IDR1_NUMPAGENDXB GENMASK(30, 28)
#define IDR1_PAGESIZE BIT(31)

#define KGSL_IOMMU_IDR2_OFFSET 0x28
#define IDR2_UBS GENMASK(11, 8)
#define IDR2_PTFS_4K BIT(12)
""",
           "SMMU IDR2 field definitions")

    # ---- allocator: raise only the copied TTBR0 cfg ---------------------
    p.edit("drivers/gpu/msm/kgsl_iommu.c",
           """	struct adreno_smmu_priv *adreno_smmu = dev_get_drvdata(&ctx->pdev->dev);
	const struct io_pgtable_cfg *cfg = NULL;
	void *domain = (void *)adreno_smmu->cookie;

	if (adreno_smmu->cookie)
		cfg = adreno_smmu->get_ttbr1_cfg(adreno_smmu->cookie);
	if (!cfg)
		return -ENODEV;

	pt->info = adreno_smmu->pgtbl_info;
	pt->info.cfg = *cfg;
	pt->info.cfg.quirks &= ~IO_PGTABLE_QUIRK_ARM_TTBR1;
	pt->info.cfg.tlb = &kgsl_iopgtbl_tlb_ops;
	pt->pgtbl_ops = qcom_alloc_io_pgtable_ops(QCOM_ARM_64_LPAE_S1, &pt->info, domain);

	if (!pt->pgtbl_ops)
		return -ENOMEM;

	pt->ttbr0 = pt->info.cfg.arm_lpae_s1_cfg.ttbr;
""",
           """	struct adreno_smmu_priv *adreno_smmu = dev_get_drvdata(&ctx->pdev->dev);
	const struct io_pgtable_cfg *cfg = NULL;
	struct kgsl_iommu *iommu = KGSL_IOMMU(ctx->kgsldev);
	void *domain = (void *)adreno_smmu->cookie;

	if (adreno_smmu->cookie)
		cfg = adreno_smmu->get_ttbr1_cfg(adreno_smmu->cookie);
	if (!cfg)
		return -ENODEV;

	pt->info = adreno_smmu->pgtbl_info;
	pt->info.cfg = *cfg;
	pt->info.cfg.quirks &= ~IO_PGTABLE_QUIRK_ARM_TTBR1;

	/*
	 * Only this copied configuration changes. The SMMU's own TTBR1
	 * configuration, and every other domain, are left exactly as they
	 * were programmed by arm-smmu.
	 */
	if (iommu->gpu_va48)
		pt->info.cfg.ias = 48;

	pt->info.cfg.tlb = &kgsl_iopgtbl_tlb_ops;
	pt->pgtbl_ops = qcom_alloc_io_pgtable_ops(QCOM_ARM_64_LPAE_S1, &pt->info, domain);

	if (!pt->pgtbl_ops)
		return -ENOMEM;

	/*
	 * The allocator may clamp IAS to what it can actually walk. If it did,
	 * the VA range advertised below would describe addresses the SMMU
	 * cannot translate, so fail instead of running with a mismatch.
	 */
	if (iommu->gpu_va48 && pt->info.cfg.ias != 48) {
		dev_err(&ctx->pdev->dev,
			"GPU VA48: TTBR0 allocator returned IAS=%u, refusing an inconsistent VA range\\n",
			pt->info.cfg.ias);
		qcom_free_io_pgtable_ops(pt->pgtbl_ops);
		pt->pgtbl_ops = NULL;
		return -ERANGE;
	}

	pt->ttbr0 = pt->info.cfg.arm_lpae_s1_cfg.ttbr;
""",
           "allocator IAS override")

    # ---- default pagetable VA range ------------------------------------
    p.edit("drivers/gpu/msm/kgsl_iommu.c",
           """		iommu_pt->base.va_start = KGSL_IOMMU_VA_BASE64;
		iommu_pt->base.va_end = KGSL_IOMMU_VA_END64;
""",
           """		iommu_pt->base.va_start = iommu->gpu_va48 ?
			KGSL_IOMMU_VA_BASE48 : KGSL_IOMMU_VA_BASE64;
		iommu_pt->base.va_end = iommu->gpu_va48 ?
			KGSL_IOMMU_VA_END48 : KGSL_IOMMU_VA_END64;
""",
           "default pagetable VA range")

    # ---- per-process pagetable VA range --------------------------------
    p.edit("drivers/gpu/msm/kgsl_iommu.c",
           """		pt->base.va_start = KGSL_IOMMU_VA_BASE64;
		pt->base.va_end = KGSL_IOMMU_VA_END64;

		if (is_compat_task()) {
			pt->base.svm_start = KGSL_IOMMU_SVM_BASE32(mmu);
			pt->base.svm_end = KGSL_MEMSTORE_TOKEN_ADDRESS;
		} else {
			pt->base.svm_start = KGSL_IOMMU_SVM_BASE64;
			pt->base.svm_end = KGSL_IOMMU_SVM_END64;
		}
""",
           """		pt->base.va_start = iommu->gpu_va48 ?
			KGSL_IOMMU_VA_BASE48 : KGSL_IOMMU_VA_BASE64;
		pt->base.va_end = iommu->gpu_va48 ?
			KGSL_IOMMU_VA_END48 : KGSL_IOMMU_VA_END64;

		if (is_compat_task()) {
			pt->base.svm_start = KGSL_IOMMU_SVM_BASE32(mmu);
			pt->base.svm_end = KGSL_MEMSTORE_TOKEN_ADDRESS;
		} else {
			pt->base.svm_start = KGSL_IOMMU_SVM_BASE64;
			/*
			 * SVM mirrors CPU addresses, so it must never reach
			 * past what the CPU itself can map. With CPU VA48
			 * this is the full 48-bit window; keep the min so
			 * that a future VA39 CPU build still lines up.
			 */
			pt->base.svm_end = iommu->gpu_va48 ?
				min_t(u64, KGSL_IOMMU_SVM_END48, TASK_SIZE) :
				KGSL_IOMMU_SVM_END64;
		}
""",
           "per-process VA range")

    # ---- powered capability probe --------------------------------------
    p.edit("drivers/gpu/msm/kgsl_iommu.c",
           """int kgsl_iommu_bind(struct kgsl_device *device, struct platform_device *pdev)
""",
           """/*
 * Decide whether this SMMU can translate 48-bit GPU virtual addresses.
 *
 * The register only reads back meaningfully while the SMMU is powered and
 * clocked, so both are enabled explicitly for the duration of the read and
 * released again. Any doubt leaves gpu_va48 false, which keeps the shipped
 * 39-bit behaviour.
 */
static void kgsl_iommu_probe_gpu_va48(struct kgsl_device *device)
{
	struct kgsl_iommu *iommu = KGSL_IOMMU(device);
	struct kgsl_mmu *mmu = &device->mmu;
	u32 id2, ubs;
	int ret;

	iommu->gpu_va48 = false;

	if (!IS_ENABLED(CONFIG_QCOM_KGSL_GPU_VA48))
		return;

	if (PAGE_SIZE != SZ_4K ||
		!test_bit(KGSL_MMU_64BIT, &mmu->features) ||
		!test_bit(KGSL_MMU_IOPGTABLE, &mmu->features) ||
		!adreno_support_64bit(ADRENO_DEVICE(device)) ||
		!adreno_is_gen7_6_0(ADRENO_DEVICE(device))) {
		dev_warn(&device->pdev->dev,
			"GPU VA48: needs Gen7.6.0, 4K pages and a 64-bit iopgtable; keeping legacy VA\\n");
		return;
	}

	if (!iommu->regbase || iommu->num_clks <= 0 ||
		IS_ERR_OR_NULL(iommu->cx_gdsc)) {
		dev_warn(&device->pdev->dev,
			"GPU VA48: SMMU registers, clocks or CX unavailable; keeping legacy VA\\n");
		return;
	}

	ret = regulator_enable(iommu->cx_gdsc);
	if (ret) {
		dev_warn(&device->pdev->dev,
			"GPU VA48: CX regulator enable failed (%d); keeping legacy VA\\n", ret);
		return;
	}

	ret = clk_bulk_prepare_enable(iommu->num_clks, iommu->clks);
	if (ret) {
		dev_warn(&device->pdev->dev,
			"GPU VA48: SMMU clock enable failed (%d); keeping legacy VA\\n", ret);
		goto out_disable_regulator;
	}

	id2 = readl_relaxed(iommu->regbase + KGSL_IOMMU_IDR2_OFFSET);

	clk_bulk_disable_unprepare(iommu->num_clks, iommu->clks);

	ubs = FIELD_GET(IDR2_UBS, id2);
	if (ubs == 5 && (id2 & IDR2_PTFS_4K)) {
		iommu->gpu_va48 = true;
		dev_info(&device->pdev->dev,
			"GPU VA48: SMMU IDR2=%#08x reports 48-bit/4K support; enabling experimental TTBR0 VA48\\n",
			id2);
	} else {
		dev_warn(&device->pdev->dev,
			"GPU VA48: SMMU IDR2=%#08x lacks 48-bit or 4K support; keeping legacy VA\\n",
			id2);
	}

out_disable_regulator:
	ret = regulator_disable(iommu->cx_gdsc);
	if (ret) {
		iommu->gpu_va48 = false;
		dev_warn(&device->pdev->dev,
			"GPU VA48: CX regulator disable failed (%d); keeping legacy VA\\n", ret);
	}
}

int kgsl_iommu_bind(struct kgsl_device *device, struct platform_device *pdev)
""",
           "VA48 capability probe")

    p.edit("drivers/gpu/msm/kgsl_iommu.c",
           """	/* Peek at the phandle to set up configuration */
	kgsl_iommu_check_config(mmu, node);
""",
           """	/* Peek at the phandle to set up configuration */
	kgsl_iommu_check_config(mmu, node);

	/* Decide whether this SMMU may use 48-bit TTBR0 addressing */
	kgsl_iommu_probe_gpu_va48(device);
""",
           "probe call site")

    p.edit("drivers/gpu/msm/kgsl.c",
           """	/* Find the first gap in the iova map */
	iova = kgsl_mmu_find_svm_region(private->pagetable, start, end,
""",
           """	/*
	 * High hints and MAP_FIXED were tried above against the full SVM range.
	 * Preserve the vendor's automatic CPU/SVM placement for ordinary mmap.
	 */
	end = min_t(u64, end, KGSL_IOMMU_SVM_END64);

	/* Find the first gap in the iova map */
	iova = kgsl_mmu_find_svm_region(private->pagetable, start, end,
""",
           "legacy automatic SVM placement")

    # Both searches accept ranges from callers. Reject invalid sizes and
    # alignment arithmetic before subtraction/addition, including VA48 edges.
    for name in ("_get_unmapped_area", "_get_unmapped_area_topdown"):
        old = ("\tbottom = ALIGN(bottom, align);\n\tstart = bottom;" if
               name == "_get_unmapped_area" else
               "\t/* Make sure that the bottom is correctly aligned */\n"
               "\tbottom = ALIGN(bottom, align);\n\n"
               "\t/* Make sure the requested size will fit in the range */\n"
               "\tif (size > (top - bottom))\n\t\treturn -ENOMEM;")
        new = ("\t/* Validate %s before unsigned range arithmetic. */\n" % name
               + """	if (!size || !align || (align & (align - 1)) ||
		bottom >= top || bottom > U64_MAX - (align - 1))
		return (uint64_t) -ENOMEM;

	bottom = ALIGN(bottom, align);
	if (bottom >= top || size > top - bottom)
		return (uint64_t) -ENOMEM;""")
        if name == "_get_unmapped_area":
            new += "\n\tstart = bottom;"
        p.edit("drivers/gpu/msm/kgsl_iommu.c", old, new,
               name + " bounds validation")

    p.edit("drivers/gpu/msm/kgsl_iommu.c",
           "\tif (start + size <= top)\n\t\treturn start;",
           "\tif (start < top && size <= top - start)\n\t\treturn start;",
           "bottom-up final gap without addition overflow")

    return p


def c_function(source, name):
    match = re.search(r"(?m)^static [^\n]*\b" + re.escape(name)
                      + r"\s*\([^;]*?\)\s*\{", source)
    if not match:
        raise ValueError("C function not found: " + name)
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end] + "\n"


# The reservation/search routines are extracted from the staged driver below.
# These host shims verify interval logic and powered-probe failure paths, not
# Linux locking, hardware translation or GPU execution.
HOST_SHIM = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>
typedef uint64_t u64;
typedef uint32_t u32;
#define U64_MAX UINT64_MAX
#define ALIGN(x, a) (((x) + (a) - 1) & ~((a) - 1))
#define IS_ERR_VALUE(x) ((u64)(x) >= (u64)-4095)
static bool warn_value(bool value) { return value; }
#define WARN(x, ...) warn_value(!!(x))
#define WARN_ON(x) warn_value(!!(x))
#define GFP_ATOMIC 0
#define spin_lock(p) ((void)0)
#define spin_unlock(p) ((void)0)
struct rb_node { struct rb_node *rb_left, *rb_right, *parent; };
struct rb_root { struct rb_node *rb_node; };
struct kgsl_iommu_addr_entry { u64 base, size; struct rb_node node; };
struct kgsl_iommu {
    bool gpu_va48; unsigned char *regbase; int num_clks; void *clks, *cx_gdsc;
};
struct kgsl_mmu { struct kgsl_iommu iommu; unsigned long features; };
struct kgsl_pagetable {
    struct rb_root rbtree;
    u64 va_start, va_end, svm_start, svm_end, compat_va_start, compat_va_end;
    int lock, name;
};
struct kgsl_memdesc {
    u64 flags, size, gpuaddr; unsigned int align; bool cpu_map;
    struct kgsl_pagetable *pagetable;
};
#define KGSL_MEMFLAGS_SECURE 1
#define KGSL_MEMFLAGS_FORCE_32BIT 2
#define KGSL_MMU_SECURE_PT 1
static bool kgsl_memdesc_use_cpu_map(struct kgsl_memdesc *m) { return m->cpu_map; }
static u64 kgsl_memdesc_footprint(struct kgsl_memdesc *m) { return m->size; }
static unsigned int kgsl_get_align(struct kgsl_memdesc *m) { return m->align; }
#define rb_entry(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define kmem_cache_alloc(cache, flags) malloc(sizeof(struct kgsl_iommu_addr_entry))
#define kmem_cache_free(cache, p) free(p)
static struct rb_node *rb_first(const struct rb_root *r) {
    struct rb_node *n = r->rb_node;
    if (n) while (n->rb_left) n = n->rb_left;
    return n;
}
static struct rb_node *rb_last(const struct rb_root *r) {
    struct rb_node *n = r->rb_node;
    if (n) while (n->rb_right) n = n->rb_right;
    return n;
}
static struct rb_node *rb_next(struct rb_node *n) {
    if (n->rb_right) { n = n->rb_right; while (n->rb_left) n = n->rb_left; return n; }
    while (n->parent && n == n->parent->rb_right) n = n->parent;
    return n->parent;
}
static struct rb_node *rb_prev(struct rb_node *n) {
    if (n->rb_left) { n = n->rb_left; while (n->rb_right) n = n->rb_right; return n; }
    while (n->parent && n == n->parent->rb_left) n = n->parent;
    return n->parent;
}
static void rb_link_node(struct rb_node *n, struct rb_node *p, struct rb_node **slot) {
    n->parent = p; n->rb_left = n->rb_right = NULL; *slot = n;
}
static void rb_insert_color(struct rb_node *n, struct rb_root *r) { (void)n; (void)r; }
static void replace_node(struct rb_root *r, struct rb_node *old, struct rb_node *n) {
    if (!old->parent) r->rb_node = n;
    else if (old == old->parent->rb_left) old->parent->rb_left = n;
    else old->parent->rb_right = n;
    if (n) n->parent = old->parent;
}
static void rb_erase(struct rb_node *n, struct rb_root *r) {
    if (!n->rb_left) replace_node(r, n, n->rb_right);
    else if (!n->rb_right) replace_node(r, n, n->rb_left);
    else {
        struct rb_node *s = n->rb_right;
        while (s->rb_left) s = s->rb_left;
        if (s->parent != n) {
            replace_node(r, s, s->rb_right);
            s->rb_right = n->rb_right; s->rb_right->parent = s;
        }
        replace_node(r, n, s);
        s->rb_left = n->rb_left; s->rb_left->parent = s;
    }
}
struct platform_device { int dev; };
struct kgsl_device { struct kgsl_mmu mmu; struct platform_device *pdev; };
#define KGSL_IOMMU(d) (&(d)->mmu.iommu)
#define ADRENO_DEVICE(d) (d)
#define KGSL_MMU_64BIT 0
#define KGSL_MMU_IOPGTABLE 1
#define PAGE_SIZE 4096
#define SZ_4K 4096
#define CONFIG_QCOM_KGSL_GPU_VA48 1
#define IS_ENABLED(c) (c)
#define IS_ERR_OR_NULL(p) (!(p))
#define dev_warn(...) ((void)0)
#define dev_info(...) ((void)0)
#define KGSL_IOMMU_IDR2_OFFSET 0x28
#define IDR2_UBS 0xf00
#define IDR2_PTFS_4K (1U << 12)
#define FIELD_GET(mask, x) (((x) & (mask)) >> __builtin_ctz(mask))
static bool test_bit(unsigned int n, const unsigned long *v) { return (*v >> n) & 1; }
static int probe_gen7 = 1, probe_gpu64 = 1, reg_enable_error, reg_disable_error;
static int clk_enable_error, reg_enables, reg_disables, clk_enables, clk_disables;
static bool adreno_is_gen7_6_0(struct kgsl_device *d) { (void)d; return probe_gen7; }
static bool adreno_support_64bit(struct kgsl_device *d) { (void)d; return probe_gpu64; }
static int regulator_enable(void *p) { (void)p; reg_enables++; return reg_enable_error; }
static int regulator_disable(void *p) { (void)p; reg_disables++; return reg_disable_error; }
static int clk_bulk_prepare_enable(int n, void *p) { (void)n; (void)p; clk_enables++; return clk_enable_error; }
static void clk_bulk_disable_unprepare(int n, void *p) { (void)n; (void)p; clk_disables++; }
static u32 readl_relaxed(const unsigned char *p) { return *(const u32 *)p; }
'''


HOST_CASES = r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); return 1; } } while (0)
#define PAGE 4096ULL
#define LOW (1ULL << 47)
#define HIGH (1ULL << 48)
static void init_pt(struct kgsl_pagetable *p) {
    struct kgsl_pagetable empty = {0}; *p = empty;
    p->va_start = LOW; p->va_end = HIGH;
    p->svm_start = 1ULL << 36; p->svm_end = HIGH;
    p->compat_va_start = 0x10000000; p->compat_va_end = 0xfff00000;
}
static u64 reserve_gpu(struct kgsl_pagetable *p, u64 size, unsigned int align) {
    struct kgsl_memdesc m = {.size = size, .align = align};
    int ret = kgsl_iommu_get_gpuaddr(p, &m);
    return ret ? (u64)ret : m.gpuaddr;
}
static void clear_pt(struct kgsl_pagetable *p) {
    while (p->rbtree.rb_node) {
        struct kgsl_iommu_addr_entry *e = rb_entry(p->rbtree.rb_node, struct kgsl_iommu_addr_entry, node);
        _remove_gpuaddr(p, e->base);
    }
}
static int no_overlap(struct kgsl_pagetable *p) {
    struct rb_node *n; u64 end = 0;
    for (n = rb_first(&p->rbtree); n; n = rb_next(n)) {
        struct kgsl_iommu_addr_entry *e = rb_entry(n, struct kgsl_iommu_addr_entry, node);
        if (!e->size || e->base < end || e->size > UINT64_MAX - e->base) return 0;
        end = e->base + e->size;
    }
    return 1;
}
static int allocator_cases(void) {
    struct kgsl_pagetable p;
    struct kgsl_memdesc m;
    u64 addr, top, blocks[64]; int i;
    init_pt(&p);
    CHECK(kgsl_iommu_set_svm_region(&p, LOW - PAGE, 3 * PAGE) == 0);
    addr = reserve_gpu(&p, PAGE, PAGE);
    CHECK(addr == LOW + 2 * PAGE); CHECK(no_overlap(&p));
    CHECK(kgsl_iommu_set_svm_region(&p, addr, PAGE) == -ENOMEM);
    CHECK(_remove_gpuaddr(&p, addr) == 0);
    CHECK(kgsl_iommu_set_svm_region(&p, addr, PAGE) == 0); clear_pt(&p);
    init_pt(&p);
    addr = reserve_gpu(&p, 2 * PAGE, PAGE); CHECK(addr == LOW);
    CHECK(kgsl_iommu_set_svm_region(&p, LOW + PAGE, PAGE) == -ENOMEM);
    CHECK(kgsl_iommu_set_svm_region(&p, LOW + 2 * PAGE, PAGE) == 0);
    CHECK(_remove_gpuaddr(&p, addr) == 0);
    CHECK(kgsl_iommu_set_svm_region(&p, addr, 2 * PAGE) == 0);
    CHECK(no_overlap(&p)); clear_pt(&p);
    init_pt(&p);
    CHECK(kgsl_iommu_set_svm_region(&p, HIGH - PAGE, PAGE) == 0);
    CHECK(kgsl_iommu_set_svm_region(&p, HIGH, PAGE) == -ENOMEM);
    CHECK(kgsl_iommu_set_svm_region(&p, HIGH - PAGE, 2 * PAGE) == -ENOMEM);
    CHECK(kgsl_iommu_set_svm_region(&p, UINT64_MAX - PAGE + 1, 2 * PAGE) == -ENOMEM);
    CHECK(kgsl_iommu_set_svm_region(&p, LOW, 0) == -ENOMEM);
    top = kgsl_iommu_find_svm_region(&p, p.svm_start, p.svm_end, PAGE, PAGE);
    CHECK(top == HIGH - 2 * PAGE);
    CHECK(kgsl_iommu_set_svm_region(&p, top, PAGE) == 0);
    CHECK(no_overlap(&p)); clear_pt(&p);
    init_pt(&p);
    for (i = 0; i < 64; i++) {
        blocks[i] = LOW + (u64)i * 4 * PAGE;
        CHECK(kgsl_iommu_set_svm_region(&p, blocks[i], PAGE) == 0);
        addr = reserve_gpu(&p, PAGE, 2 * PAGE);
        CHECK(!IS_ERR_VALUE(addr)); CHECK(!(addr & (2 * PAGE - 1)));
        CHECK(no_overlap(&p));
    }
    for (i = 0; i < 64; i += 2) CHECK(_remove_gpuaddr(&p, blocks[i]) == 0);
    CHECK(reserve_gpu(&p, PAGE, PAGE) == LOW); CHECK(no_overlap(&p)); clear_pt(&p);
    init_pt(&p);
    CHECK(IS_ERR_VALUE(reserve_gpu(&p, 0, PAGE)));
    CHECK(IS_ERR_VALUE(reserve_gpu(&p, UINT64_MAX, PAGE)));
    CHECK(IS_ERR_VALUE(_get_unmapped_area(&p, UINT64_MAX - 2, UINT64_MAX, 1, PAGE)));
    CHECK(IS_ERR_VALUE(_get_unmapped_area_topdown(&p, 8, 4, 1, PAGE)));
    CHECK(IS_ERR_VALUE(_get_unmapped_area_topdown(&p, LOW, HIGH, 0, PAGE)));
    CHECK(IS_ERR_VALUE(_get_unmapped_area(&p, LOW, HIGH, PAGE, 0)));
    CHECK(IS_ERR_VALUE(_get_unmapped_area(&p, LOW, HIGH, PAGE, 3)));
    m = (struct kgsl_memdesc){.flags = KGSL_MEMFLAGS_FORCE_32BIT, .size = PAGE, .align = PAGE};
    CHECK(kgsl_iommu_get_gpuaddr(&p, &m) == 0);
    CHECK(m.gpuaddr == p.compat_va_start);
    kgsl_iommu_put_gpuaddr(&m); CHECK(!p.rbtree.rb_node);
    m.flags = KGSL_MEMFLAGS_SECURE;
    CHECK(kgsl_iommu_get_gpuaddr(&p, &m) == -EINVAL);
    puts("actual KGSL C: shared SVM/GPU reservations, VA48 boundaries, compat and bounds passed");
    return 0;
}
static int probe_cases(void) {
    struct platform_device pdev;
    u32 regs[32] = {0};
    struct kgsl_device d = {.pdev = &pdev, .mmu = {.features = 3}};
    struct kgsl_iommu *iommu = KGSL_IOMMU(&d);
    iommu->regbase = (unsigned char *)regs; iommu->num_clks = 1;
    iommu->clks = iommu; iommu->cx_gdsc = iommu;
    regs[KGSL_IOMMU_IDR2_OFFSET / 4] = (5 << 8) | IDR2_PTFS_4K;
    kgsl_iommu_probe_gpu_va48(&d);
    CHECK(iommu->gpu_va48 && reg_enables == 1 && reg_disables == 1);
    CHECK(clk_enables == 1 && clk_disables == 1);
    for (int ubs = 0; ubs < 16; ubs++) {
        regs[KGSL_IOMMU_IDR2_OFFSET / 4] = (ubs << 8) | IDR2_PTFS_4K;
        kgsl_iommu_probe_gpu_va48(&d); CHECK(iommu->gpu_va48 == (ubs == 5));
    }
    regs[KGSL_IOMMU_IDR2_OFFSET / 4] = 5 << 8;
    kgsl_iommu_probe_gpu_va48(&d); CHECK(!iommu->gpu_va48);
    regs[KGSL_IOMMU_IDR2_OFFSET / 4] |= IDR2_PTFS_4K;
    probe_gen7 = 0; int before = reg_enables;
    kgsl_iommu_probe_gpu_va48(&d); CHECK(!iommu->gpu_va48 && reg_enables == before);
    probe_gen7 = 1; probe_gpu64 = 0;
    kgsl_iommu_probe_gpu_va48(&d); CHECK(!iommu->gpu_va48 && reg_enables == before);
    probe_gpu64 = 1; reg_enable_error = -EIO; before = clk_enables;
    kgsl_iommu_probe_gpu_va48(&d); CHECK(!iommu->gpu_va48 && clk_enables == before);
    reg_enable_error = 0; clk_enable_error = -EIO;
    before = clk_disables; int reg_before = reg_disables;
    kgsl_iommu_probe_gpu_va48(&d);
    CHECK(!iommu->gpu_va48 && clk_disables == before && reg_disables == reg_before + 1);
    clk_enable_error = 0; reg_disable_error = -EIO;
    kgsl_iommu_probe_gpu_va48(&d); CHECK(!iommu->gpu_va48);
    puts("actual KGSL C: powered capability probe and failure paths passed");
    return 0;
}
int main(void) { return allocator_cases() || probe_cases(); }
'''


def self_test(plan):
    """Work only in temporary files, including round-trip and drift checks."""
    original, changed = plan.stage(reverse=plan.already_applied())
    baseline = changed if plan.already_applied() else original
    with tempfile.TemporaryDirectory(prefix="quest-gpu-va48-") as temp:
        root = Path(temp)
        for relpath, source in baseline.items():
            path = root / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        staged = build(root)
        before, after = staged.stage()
        staged.apply(before, after)
        reverse_before, reverse_after = staged.stage(reverse=True)
        if reverse_after != baseline:
            raise ValueError("apply/revert round-trip differs from original")
        staged.apply(reverse_before, reverse_after)
        # A missing final anchor must leave every earlier source untouched.
        final_path = root / "drivers/gpu/msm/kgsl_iommu.c"
        final_path.write_text(final_path.read_text().replace(
            "\tif (start + size <= top)", "\tif (start + size < top)", 1))
        drifted = {r: (root / r).read_text() for r in before}
        try:
            staged.stage()
        except ValueError:
            pass
        else:
            raise ValueError("missing final anchor was accepted")
        if drifted != {r: (root / r).read_text() for r in before}:
            raise ValueError("failed preflight wrote sources")
        driver = after["drivers/gpu/msm/kgsl_iommu.c"]
        names = ["_find_gpuaddr", "_remove_gpuaddr", "_insert_gpuaddr",
                 "_get_unmapped_area", "_get_unmapped_area_topdown",
                 "kgsl_iommu_find_svm_region", "iommu_addr_in_svm_ranges",
                 "kgsl_iommu_set_svm_region", "kgsl_iommu_get_gpuaddr",
                 "kgsl_iommu_put_gpuaddr", "kgsl_iommu_probe_gpu_va48"]
        source = HOST_SHIM + "\n".join(c_function(driver, n) for n in names) + HOST_CASES
        source_path, executable = root / "allocator.c", root / "allocator"
        source_path.write_text(source)
        compiler = shutil.which(os.environ.get("HOSTCC", "cc"))
        if not compiler:
            raise ValueError("host C compiler unavailable")
        subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=undefined", str(source_path), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
        print("Patch apply/revert and all-or-nothing preflight passed")
    if original != {r: Path(plan.root, r).read_text() for r in original}:
        raise ValueError("self-test changed the input tree")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--revert", action="store_true")
    modes.add_argument("--self-test", action="store_true")
    ap.add_argument("--patch", type=Path, help="write a reproducible forward patch")
    args = ap.parse_args()

    root = os.path.abspath(args.tree)
    if not os.path.isfile(os.path.join(root, "drivers/gpu/msm/kgsl_iommu.c")):
        sys.exit("%s does not look like the Quest kernel tree" % root)

    p = build(root)
    applied = p.already_applied()
    if args.apply and applied:
        sys.exit("refusing to apply twice")
    if args.revert and not applied:
        sys.exit("refusing to revert an unpatched tree")
    try:
        original, changed = p.stage(reverse=applied)
    except (ValueError, OSError) as exc:
        sys.exit("preflight FAILED: " + str(exc))
    print("preflight passed: %d anchors, each matched exactly once"
          % len(p.edits))
    print("already applied: %s" % applied)

    if args.patch:
        before, after = (changed, original) if applied else (original, changed)
        diff = "".join("".join(difflib.unified_diff(
            before[relpath].splitlines(keepends=True),
            after[relpath].splitlines(keepends=True),
            fromfile="a/" + relpath, tofile="b/" + relpath)) for relpath in sorted(before))
        args.patch.write_text(diff, encoding="utf-8")
        print("Wrote " + str(args.patch))

    if args.self_test:
        self_test(p)
        return
    if args.apply:
        p.apply(original, changed)
        print("applied %d edits" % len(p.edits))
    elif args.revert:
        p.apply(original, changed)
        print("reverted")


if __name__ == "__main__":
    main()
