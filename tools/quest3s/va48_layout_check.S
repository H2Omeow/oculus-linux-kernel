/* Offline constants only: vabits_actual is modeled as head.S VA_BITS_MIN. */
#include <asm/memory.h>
#include <asm/pgtable-hwdef.h>
#define vabits_actual VA_BITS_MIN
#define DEFAULT_MAP_WINDOW_64	(UL(1) << KERNEL_VA_BITS)
#define TASK_SIZE_64		(UL(1) << vabits_actual)
.if (VA_BITS) != (48)
.error "wrong VA_BITS"
.endif
.if (VA_BITS_MIN) != (48)
.error "wrong VA_BITS_MIN"
.endif
.if (KERNEL_VA_BITS) != (39)
.error "wrong KERNEL_VA_BITS"
.endif
.if (PAGE_SHIFT) != (12)
.error "wrong PAGE_SHIFT"
.endif
.if (PGDIR_SHIFT) != (39)
.error "wrong PGDIR_SHIFT"
.endif
.if (PTRS_PER_PGD) != (512)
.error "wrong PTRS_PER_PGD"
.endif
.if (TCR_TxSZ(VA_BITS)) != (1048592)
.error "wrong TCR_TxSZ(VA_BITS)"
.endif
.if (PAGE_OFFSET) != (-549755813888)
.error "wrong PAGE_OFFSET"
.endif
.if (MODULES_VADDR) != (-274877906944)
.error "wrong MODULES_VADDR"
.endif
.if (DEFAULT_MAP_WINDOW_64) != (549755813888)
.error "wrong DEFAULT_MAP_WINDOW_64"
.endif
.if (TASK_SIZE_64) != (281474976710656)
.error "wrong TASK_SIZE_64"
.endif
