# Quest 3S 扩展功能状态

2026-10-28。以下功能已集成到 `va48-quest3s` 目标源码及专用 `vendor/quest3s_va48_defconfig`。构建证据及指纹见 [BUILD_ARTIFACTS.md](BUILD_ARTIFACTS.md)；尚无 Quest 3S 实机启动或功能运行结果。

| 功能 | 源码与配置 | 运行边界 |
| --- | --- | --- |
| CPU 用户空间 VA48 | 4 KiB、四级页表、PA48；用户上限 2^48，默认 mmap/栈/PIE 保持低 39 位窗口 | 需要运行 `va48test`；旧内核虚拟地址布局不保证原厂二进制模块 ABI |
| GPU VA48 | `QCOM_KGSL=m`、`QCOM_KGSL_GPU_VA48=y`；Gen7.6.0 上通电读取 SMMU IDR2，核对 48 位及 4K 支持后扩展非安全 TTBR0 | 保留 TTBR1、secure/compat 和自动 SVM 原窗口；高 hint 可使用扩展范围。硬件能力不满足时保留旧范围，尚无 GPU 高 VA 实测 |
| NTSync | `NTSYNC=y`，移植实现及 UAPI 随源码分发 | 尚无设备 Wine/Proton 或同步对象测试 |
| Droidspaces 标准模式前置项 | namespaces、binderfs、cgroups、overlay、bridge/veth/tun、iptables/NAT；补 DEVTMPFS、xt ADDRTYPE/LOG/RECENT | 只包含内核前置条件；Droidspaces 用户态、容器镜像、SELinux 策略及挂载仍需配置；不包含扩展模式 EVDI/虚拟 HCI |
| BakaSU | 固定上游 `d5e9e025b8b49155f8014684d64c91742b465f65`，`KSU=y`、`KSU_TRACEPOINT_HOOK=y`，版本码 35252 | 内置内核组件；配套 manager/ksud 另行匹配。tracepoint 路径仍有 syscall-table 数据指针替换，尚无权限、隐藏或 CFI 运行验证 |

GPU 移植脚本的自测从实际 KGSL C 函数提取 allocator/probe，结合 UBSan 检查边界与失败路径；它还验证 apply/revert 和锚点漂移拒绝。CPU 布局静态检查见 [VA48_VALIDATION.md](VA48_VALIDATION.md)。这些检查不能替代真实硬件测试。

目标内核保留 enforcing CFI、符号 CRC 失配拒绝、KASLR；没有通过全局关闭 ABI 检查来兼容原厂模块。应使用同次构建的内核和模块，见 [MODULE_COMPATIBILITY.md](MODULE_COMPATIBILITY.md)。

原厂无 kexec 时的 EL1 加载器单独发布在 [quest3s-el1-kexec](https://github.com/H2Omeow/quest3s-el1-kexec)。它仍需准确原厂 ABI 和真实 DT/内存布局；活动 TEE 所有权交接、进行中的 SCM 调用排空尚未实现，相关绑定驱动会阻断执行。目标内核功能集成不代表这些交接问题已解决。
