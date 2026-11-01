# 5.10.240-va48-H2O 构建产物

- workflow：Handoff target build
- run：41286406725
- commit：33dc76559f24f34ca3bfbd9134d7e588aa0ff195
- artifact：quest3s-va48-target，id 13075128174，48,959,228 B
- kernel.release：5.10.240-va48-H2O
- Image：36,438,068 B，SHA256 cb488601d3172028b6e4a5f2de756a0b43ff2dc3aedafa82544a6097e6d8658b
- Image.el1：34,802,176 B，SHA256 71de77c7007b29f6964c2f5d0cc0187c7985e085cd0080f3195341fd32260b74
- Module.symvers：1,003,493 B，SHA256 8538ccd298bd833ba6aef23c5c6e0932172c622bf09a814fab6470590c0adbcb
- 模块：267 个
- Image.el1 头：text_offset 0，image_size 36,438,016，flags 0xa
- missing-modules.txt：kernelsu（内建）、quest_el1_kexec（加载器模块，不是 target 模块）

构建修复：qcacld-3.0 的 /tmp 软链路径改为直接 srctree 路径；target workflow 加 set -o pipefail，避免 make 失败被 tail 掩盖。

未验证：真机启动、pstore、Android 用户态、TEE、Droidspaces 运行时。
