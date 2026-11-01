# 5.10.240-va48-H2O 构建产物

- workflow：Handoff target build
- run：41292654740
- commit：c8092688d333d0492e0585cb054aca3bf985ceba
- artifact：quest3s-va48-target，id 13078212080，48,963,433 B
- kernel.release：5.10.240-va48-H2O
- Image：36,438,068 B，SHA256 4e6f4a98172c7bf702d507d5f3fdecc0e0cdfa68512f9920ff74b485cacfddcd
- Image.el1：34,804,224 B，SHA256 ff317fb1a97fb5b163f014e24fb32d0f423a795a5d7eba1cf543a34d0a4aec28
- Module.symvers：1,003,261 B，SHA256 1b2ab5f26a01431bcef7b0810476697e2536b9a248b83a3023ce229d457f3314
- System.map：9,658,792 B，SHA256 f318d9b699184518f0bef3c94e1892658e8bbd31ee939a0d3c395d61e819b33f
- config-used.txt：198,460 B，SHA256 7fee3c9fe579865f4e62d98ccd7302f616b0a67daa298875fb528266719d8c7f
- 模块：265 个
- Image.el1 头：text_offset 0，image_size 36,438,016，flags 0xa
- RPMh：CONFIG_QCOM_COMMAND_DB=y、CONFIG_QCOM_RPMH=y；CONFIG_COMMON_CLK_QCOM=m、CONFIG_QCOM_CLK_RPMH=m、CONFIG_REGULATOR_RPMH=m、CONFIG_INTERCONNECT_QCOM=m、CONFIG_INTERCONNECT_QCOM_RPMH=m、CONFIG_INTERCONNECT_QCOM_BCM_VOTER=m
- missing-modules.txt：cmd_db、kernelsu、qcom_rpmh（内建到 Image）、quest_el1_kexec（加载器模块，不是 target 模块）

构建修复：qcacld-3.0 的 /tmp 软链路径改为直接 srctree 路径；target workflow 加 set -o pipefail，避免 make 失败被 tail 掩盖。

RPMh 修复：rpmh_rsc_probe 在申请 IRQ 前清理上一内核遗留的 TCS/IRQ 状态；tcs_is_free 同时检查 RSC_DRV_STATUS。详见 RPMH_WARM_HANDOFF.md。

未验证：真机启动、pstore、Android 用户态、TEE、Droidspaces 运行时、RPMh 21 秒复位是否消失。
