# CPU VA48 静态验证

2026-10-28。目标是用户地址上限 2^48，同时保持内核原有高 39 位区域布局。默认 mmap、栈与 PIE 仍使用低 39 位窗口，显式高 hint/固定映射可使用用户 VA48。此记录只覆盖源码与构建产物，未验证设备启动。

## 源码和布局

`patch_va48_510.py` 面向官方基线 `043e6bcc61899eaa759a3f1b76606a190c8bb918`，当前发布分支已经应用，不能重复执行。脚本先在内存中核对全部 14 项编辑及前提锚点；缺文件、缺/重复锚点、重复应用都会拒绝且不写文件。历史离线验证已检查这些失败路径、正常应用及生成文件一致性；脚本不再包含 CRC 绕过。

| 参数 | 当前期望 |
| --- | --- |
| VA_BITS / VA_BITS_MIN / TASK_SIZE_64 | 48 / 48 / 2^48 |
| KERNEL_VA_BITS / DEFAULT_MAP_WINDOW_64 | 39 / 2^39 |
| PAGE_SHIFT / 页表级数 / PGDIR_SHIFT | 12 / 4 / 39 |
| TCR_T0SZ / TCR_T1SZ | 16 / 16 |
| PAGE_OFFSET / MODULES_VADDR | 0xffffff8000000000 / 0xffffffc000000000 |

`T1SZ` 必须与四级根表匹配，不能因为内核映射集中在旧区域就改成 25。KASLR、线性映射大小及内存热插拔边界分别使用固定内核位宽。fixmap 的 4K 四级配置复用已有 PUD 路径，kernel 和 fixmap 位于 PGD[511] 下不同 PUD 项。

`va48_layout_check.S` 使用实际内核头文件及从 `processor.h` 提取的地址宏做 AArch64 汇编断言。完成目标配置与 prepare 后，可从内核根目录运行（输出树构建时把 generated include 路径改到输出目录）：

```sh
clang --target=aarch64-linux-gnu -x assembler-with-cpp -D__ASSEMBLY__ \
  -include include/generated/autoconf.h \
  -Iarch/arm64/include -Iarch/arm64/include/generated \
  -Iinclude -Iinclude/generated \
  -c tools/quest3s/va48_layout_check.S -o /tmp/quest3s-va48-layout.o
```

布局检查还需结合最终 ELF：`head.o` 设置 `vabits_actual=48`，`idmap_t0sz` 初值 16，idmap 页表预留 3 页；`INIT_DIR_SIZE` 随 `_text.._end` 及 KASLR 边界余量计算。当前最终链接核验结果见 [BUILD_ARTIFACTS.md](BUILD_ARTIFACTS.md)。

## 未验证的路径

EFI stub 的 `efi_get_max_initrd_addr()` 仍按 `VA_BITS_MIN=48` 计算上限，而线性映射窗口仍按 39 位布局。EFI 实际把 initrd 放到线性窗口外时会被丢弃；当前热切换路径不经过 EFI stub，加载器另行检查 ARM64 initrd 窗口要求。该差异没有证明设备实际出现 initrd 放置问题。

设备侧仍需验证高地址读写、2^47 以上及接近 2^48 的映射、拒绝越界、fork/COW/mprotect、默认低地址布局、恢复/休眠、GPU 和所有厂商模块。`va48test/` 提供有限页面触碰的探针，不会逐页触碰巨大的稀疏预留。探针通过也只覆盖指定地址和操作，不能证明所有 48 位地址均可用或整个系统稳定。
