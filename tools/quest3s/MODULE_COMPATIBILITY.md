# 原厂加载器 ABI 与目标模块

用户提供的运行版本是：

```text
Linux localhost 5.10.240-g9cb2f620a9a8 #1 SMP PREEMPT Thu Jul 2 23:18:32 PDT 2026 aarch64 Toybox
```

公开 stock 源码提交为 [`729ec6c4b2086454e0157cbc810f5a460789cc67`](https://github.com/facebookincubator/oculus-linux-kernel/tree/729ec6c4b2086454e0157cbc810f5a460789cc67)，Makefile 为 5.10.240。发布日期接近设备编译日期，不能证明与设备配置、工具链及 ABI 一致。EL1 当前是源码推断的适配假设，需由运行时检查确认；`uname` 不含启动 EL 信息。

VA48 自定义目标基于官方 [`043e6bcc61899eaa759a3f1b76606a190c8bb918`](https://github.com/facebookincubator/oculus-linux-kernel/tree/043e6bcc61899eaa759a3f1b76606a190c8bb918)，原生版本是 **5.10.246**，当前使用 `5.10.246-quest3s-va48`。没有改写版本号伪装为设备的原厂构建。

## 两套构建

1. **原厂中的 EL1 加载器模块**必须按正在运行的 5.10.240 内核构建，需准确源码、完整 `.config`、生成头文件、工具链和 `Module.symvers`。公开源码和手工合并的候选配置只用于 C/汇编/LTO 检查；缺少原厂符号表时不能证明导入符号或 CRC 正确，也不产生可宣称设备兼容的 `.ko`。
2. **VA48 目标内核及厂商模块**应来自同一次 5.10.246 目标构建。KGSL、WLAN、camera、display 等重编模块与目标 `Module.symvers` 配套使用；initrd/rootfs 中的模块路径与加载清单还需相应调整。原厂二进制模块须逐个检查，不能先假定可复用。

4K VA39 到 VA48 会把页表从三级变成四级。保持 `PAGE_OFFSET`、vmemmap、指针大小及默认 mmap 位置不能保证内联页表代码、类型、结构布局和 CFI 一致。`vermagic` 也不编码所有差异。

本分支恢复 `kernel/module.c::check_version()` 在 CRC 失配时返回失败；之前忽略 CRC 的改动已撤销。目标使用 clang 23.1.4、ThinLTO、enforcing CFI；CFI 检查器和跳转表存在只说明生成了对应机制，不能证明与其他工具链构建的模块可交互。

## 设备资料缺口

目前没有设备完整 `.config`、准确 stock `Module.symvers`、工具链资料、运行时 DTB、RAM/保留区布局、已加载模块元数据、模块签名策略或实际启动 EL。仓库中的 `collect_device_info.sh` 可在设备本地只读采集部分资料，不执行提权或切换。没有权限或读不到某项不能据此判定对应功能不存在。

EL1 加载器的动态调用仅在必要包装处使用 `__nocfi`；没有全局关闭 CFI。原厂模块签名和加载策略仍须满足。加载器、SCM/watchdog 策略与未解决的 TEE 交接问题详见 [加载器文档](https://github.com/H2Omeow/quest3s-el1-kexec) 和 [TEE_HANDOFF.md](https://github.com/H2Omeow/quest3s-el1-kexec/blob/main/TEE_HANDOFF.md)。

最终目标构建证据见 [BUILD_ARTIFACTS.md](BUILD_ARTIFACTS.md)，功能范围见 [FEATURE_STATUS.md](FEATURE_STATUS.md)。编译和静态审查无法给出可靠的真实热切换成功百分比。
