// SPDX-License-Identifier: GPL-2.0-only
/*
 * quest_handoff - bring-up aids for a kernel started by the EL1 hot handoff
 * (quest3s-el1-kexec) instead of by the bootloader.
 *
 * A handed-off kernel has no UART and no bootloader console on this device.
 * The only log that survives is the ramoops console zone, and it can only be
 * read after the machine returns to the stock kernel.  Two things are needed
 * for that to work on the first attempt:
 *
 *   1. a reliable way back to the stock kernel even when userspace never
 *      runs, so that the log is actually recoverable;
 *   2. a warm reset, because a PMIC/cold reset loses the DDR contents that
 *      hold the ramoops zone.
 *
 * deadman=<seconds> arms a timer early in boot; when it expires the kernel
 * restarts itself through the normal restart path, which with reboot=w on the
 * command line issues PSCI SYSTEM_RESET2 (warm).  Userspace disarms or
 * re-arms it by writing to
 *   /sys/module/quest_handoff/parameters/deadman
 * so a successful boot can keep the machine alive, and a test script can give
 * itself a bounded extension while it works.
 *
 * banner=1 prints the execution state the handoff produced (exception level,
 * translation control, MMU state) as the first thing in the log.
 */

#include <linux/init.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/moduleparam.h>
#include <linux/printk.h>
#include <linux/reboot.h>
#include <linux/timer.h>

#ifdef CONFIG_ARM64
#include <asm/cputype.h>
#include <asm/memory.h>
#include <asm/sysreg.h>
#endif

#define QH_DEADMAN_MAX 3600u

static unsigned int deadman_secs;
static bool banner = true;
static struct timer_list deadman_timer;
static bool deadman_ready;

static void quest_deadman_fire(struct timer_list *unused)
{
	pr_emerg("quest_handoff: deadman expired after %us, restarting\n",
		 deadman_secs);
	/*
	 * Console drivers (including ramoops) are written synchronously by
	 * printk, so the line above is already in the persistent zone.
	 */
	emergency_restart();
}

static void quest_deadman_apply(void)
{
	if (!deadman_ready)
		return;
	if (deadman_secs)
		mod_timer(&deadman_timer,
			  jiffies + msecs_to_jiffies(deadman_secs * 1000u));
	else
		del_timer_sync(&deadman_timer);
}

static int quest_deadman_set(const char *val, const struct kernel_param *kp)
{
	unsigned int secs;
	int ret;

	ret = kstrtouint(val, 0, &secs);
	if (ret)
		return ret;
	if (secs > QH_DEADMAN_MAX)
		return -ERANGE;
	deadman_secs = secs;
	quest_deadman_apply();
	pr_info("quest_handoff: deadman %s (%us)\n",
		secs ? "armed" : "disarmed", secs);
	return 0;
}

static const struct kernel_param_ops quest_deadman_ops = {
	.set = quest_deadman_set,
	.get = param_get_uint,
};

module_param_cb(deadman, &quest_deadman_ops, &deadman_secs, 0644);
MODULE_PARM_DESC(deadman, "seconds before an automatic restart (0 disables)");

module_param(banner, bool, 0444);
MODULE_PARM_DESC(banner, "print the exception/translation state at boot");

#ifdef CONFIG_ARM64
static void quest_print_banner(void)
{
	u64 el = read_sysreg(CurrentEL) >> 2;
	u64 sctlr = read_sysreg(sctlr_el1);
	u64 tcr = read_sysreg(tcr_el1);

	pr_info("quest_handoff: EL%llu sctlr_el1=0x%016llx mmu=%s tcr_el1=0x%016llx t0sz=%llu t1sz=%llu\n",
		el, sctlr, (sctlr & 1) ? "on" : "off", tcr,
		tcr & 0x3f, (tcr >> 16) & 0x3f);
	pr_info("quest_handoff: va_bits=%d page_shift=%d pgtable_levels=%d midr=0x%08x\n",
		VA_BITS, PAGE_SHIFT, CONFIG_PGTABLE_LEVELS,
		(unsigned int)read_cpuid_id());
}
#else
static void quest_print_banner(void) { }
#endif

static int __init quest_handoff_init(void)
{
	if (banner)
		quest_print_banner();
	timer_setup(&deadman_timer, quest_deadman_fire, 0);
	deadman_ready = true;
	if (deadman_secs) {
		pr_info("quest_handoff: deadman armed (%us); write 0 to /sys/module/quest_handoff/parameters/deadman to cancel\n",
			deadman_secs);
		quest_deadman_apply();
	}
	return 0;
}
/*
 * early_initcall so the timer covers the whole driver bring-up, which is
 * where a handed-off kernel is most likely to stop.
 */
early_initcall(quest_handoff_init);

MODULE_DESCRIPTION("Quest 3S EL1 handoff bring-up aids");
MODULE_LICENSE("GPL v2");
