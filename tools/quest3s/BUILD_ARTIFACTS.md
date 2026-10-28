# Quest 3S VA48 构建产物核验

核验日期：2026-10-28。以下为公开目标源码上的本地 ThinLTO 构建，**不是设备启动结果，也不是设备原厂构建或模块兼容证明**。

- 源码基线：`043e6bcc61899eaa759a3f1b76606a190c8bb918`，公开内核 fork 分支 [`va48-quest3s`](https://github.com/H2Omeow/oculus-linux-kernel/tree/va48-quest3s)，基线原生版本 5.10.246；目标 `UTS_RELEASE=5.10.246-quest3s-va48`。分支包含专用 defconfig、VA48/NTSync/GPU VA48/BakaSU/Droidspaces 前置项及编译兼容修复。
- 最终配置 SHA256：`06950a982e93852964c9b29939a1c85d35e6fe7f15f63b447d74ee3ce586a640`。启用 4K、VA48、四级页表、ThinLTO、enforcing CFI、NTSync、GPU VA48、BakaSU、标准 Droidspaces 内核前置项；关闭 Full LTO、PGO、DEBUG_INFO/BTF。
- 最终完整构建记录：`final-20261028-145900`，`make Image modules` 和构建 runner 均退出 0，35.029 秒；`-j8`、ThinLTO link jobs=2，未删除 ThinLTO cache。构建脚本/配置/源码快照及工具版本留在本机审计目录，不随仓库发布。
- Kbuild 为 IKCONFIG ThinLTO cache 增加配置内容 SHA256 输入，避免汇编 `.incbin` 隐藏的数据变化被旧缓存误认为相同。最终 `scripts/extract-ikconfig arch/arm64/boot/Image` 与 `.config` 逐字一致，二者 SHA256 均为上述配置指纹。

## 主要产物

| 产物 | 大小 | SHA256 |
| --- | ---: | --- |
| `arch/arm64/boot/Image` | 36,054,540 bytes | `a9f579891b20a9758e8632906d9c0af88e9e78e6a21e2aa21f202a0021579f14` |
| `vmlinux` | 48,837,192 bytes | `a1cca10ab3dd0ceed38bb6c35240eccca882f6a53f2045fd71d7145116e8501c` |
| `Module.symvers` | 998,355 bytes | `b2e8d60f9bd009a2738f98acbc80c2af3484b35603e107d1269855704a41b682` |
| `drivers/gpu/msm/msm_kgsl.ko` | 2,493,296 bytes | `39e10a6ccfe37ba1af91e2f5b23c33acaeb74951296fff047f3b01ce31062d97` |
| `Image.el1` | 34,208,256 bytes | `f7aa14c33cf72312789ac12f2be3063b409f929321576a92ab209f0b9bbf7454` |

`Image.el1` 由 [prepare-image.py](https://github.com/H2Omeow/quest3s-el1-kexec/blob/main/scripts/prepare-image.py) 从该 `vmlinux` 单独导出；保留所有运行时 alloc sections，仅排除 `_end` 之后的顶层 `.eh_frame`。脚本逐字节比较其他 25 个 alloc sections、检查 ARM64 启动头和 `_text.._end`。原 `Image` 未修改。

最终模块清单与 `modules.order` 一致，共 257 个 `.ko`。257 个都含 `__cfi_check`；228 个定义 `init_module` 的模块含 `__cfi_jt_init_module`；213 个定义 `cleanup_module` 的模块含相应 CFI 跳转表。全部 vermagic 为：

```text
5.10.246-quest3s-va48 SMP preempt mod_unload modversions aarch64
```

最终 ELF 检查确认 `idmap_pg_dir..idmap_pg_end` 为 3 页、`init_pg_dir..init_pg_end` 为 5 页；`idmap_t0sz=16`，启动汇编设置 `vabits_actual=48`，与 4K 四级页表匹配。`msm_kgsl.ko` 是 AArch64 relocatable ELF，含 `__cfi_check` 及 init CFI 跳转表。完整 feature 边界见 [FEATURE_STATUS.md](FEATURE_STATUS.md)，模块 ABI 风险见 [MODULE_COMPATIBILITY.md](MODULE_COMPATIBILITY.md)。

## 源码一致性与限制

最终构建前后 tracked diff、所有非生成未跟踪文件内容哈希和 `.config` 均相同。Kbuild 确认的 linker scripts、`regdb.c`、`cc-wrapper`、BakaSU syscall 号头/host 工具及 IKCONFIG 哈希头为生成物并从源码漂移清单排除。独立重链后 IKCONFIG 内容复核通过。

设备实际运行的是用户报告的 `5.10.240-g9cb2f620a9a8`；本目标是公开 5.10.246 分支。两者是不同内核，不应混淆。当前没有真实 DTB/启动参数/RAM 保留区布局，也没有设备上的冷启动、热切换、模块或功能运行数据。不能据此给出有统计意义的热切换成功率。
