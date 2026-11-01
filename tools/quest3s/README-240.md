# Quest 3S 5.10.240-va48-H2O target

本分支 handoff/240-H2O 直接基于 5.10.240 vendor commit 729ec6c4b2086454e0157cbc810f5a460789cc67，而不是 5.10.246 源码改 Makefile。

构建 run：41286406725，commit 33dc76559f24f34ca3bfbd9134d7e588aa0ff195，artifact 13075128174。
产物：kernel.release 5.10.240-va48-H2O；Image 36,438,068 B；Image.el1 34,802,176 B；267 个模块。

## 功能

- CPU：内核仍用 VA39 布局（PAGE_OFFSET 0xFFFFFF8000000000，KIMAGE_VADDR 0xFFFFFFC800000000），用户态 VA48，4K 页、4 级页表、PA48。
- GPU：QCOM_KGSL=m，QCOM_KGSL_GPU_VA48=y，只扩展 non-secure TTBR0。
- NTSync：CONFIG_NTSYNC=y。
- Quest handoff：CONFIG_QUEST_HANDOFF=y，early initcall 自检和 deadman。
- BakaSU：vendored 35259，KSU_VERSION 35259，KSU_COMMIT_SHA 6c13db63，配套 manager 35259。
- Droidspaces：非 GKI 内核前置项，详见 DROIDSPACES.md。
- 模块加载：check_version 返回 1，same_magic 返回 1，module_sig_check 返回 0，CFI_PERMISSIVE=y，MODULE_FORCE_LOAD=y。绕过校验不等于 ABI 兼容，优先使用本构建的 267 个模块。

## 构建注意

- 必须用 Android clang r450784e（clang 14.0.7），不要用上游 LLVM 23。
- target-build.yml 先合并 device-5.10.240-g9cb2f620a9a8.config 和 handoff-target.fragment，再 olddefconfig，然后 make Image modules。
- qcacld-3.0/Kbuild 原来通过 /tmp/qcacld-3.0 软链访问源码；CI 上该路径可能已是目录，导致 configs/qca6490_defconfig 找不到。现改为直接用 srctree 路径。
- Build Image and modules 步骤已加 set -o pipefail，make 失败不会再被 tail 掩盖。
- Image.el1 由加载器仓库的 scripts/prepare-image.py 导出；Image 头的 text_offset 必须为 0，image_size 与内容一致。

## 贡献者

- [H2Omeow](https://github.com/H2Omeow) — 项目维护
- [XiaoMeow-1145](https://github.com/XiaoMeow-1145) — 贡献者

完整名单见根目录 [CONTRIBUTORS.md](../../CONTRIBUTORS.md)。
