#!/system/bin/sh
# Read-only Android diagnostics. Run manually on the headset; stdout only.
# This script does not invoke adb/su, load modules, mount, or modify files.
exec 2>&1

q3s_section() { printf '\n=== %s ===\n' "$1"; }
q3s_read() {
    printf '\n%s\n' "$1"
    if [ -r "$1" ]; then
        cat "$1" 2>&1 || printf '[读取失败]\n'
    else
        printf '[不存在或当前身份无读取权限]\n'
    fi
}
q3s_dt_text() {
    printf '\n%s (NUL 分隔文本)\n' "$1"
    if [ -r "$1" ]; then
        tr '\000' '\n' < "$1" 2>&1 || printf '[读取失败]\n'
        printf '\n'
    else
        printf '[不存在或当前身份无读取权限]\n'
    fi
}
q3s_dt_hex() {
    printf '\n%s (原始字节，DT cells 为大端；最多 256 字节)\n' "$1"
    if [ -r "$1" ]; then
        od -An -tx1 -N 256 "$1" 2>&1 || printf '[读取失败或 od 不可用]\n'
    else
        printf '[不存在或当前身份无读取权限]\n'
    fi
}

q3s_section '执行身份与运行内核'
id 2>&1
uname -a 2>&1
q3s_read /proc/version

q3s_section '设备与启动属性'
if command -v getprop >/dev/null 2>&1; then
    for q3s_key in ro.product.model ro.product.device ro.board.platform \
        ro.build.fingerprint ro.build.version.incremental ro.build.type \
        ro.boot.hardware ro.boot.slot_suffix ro.boot.verifiedbootstate \
        ro.boot.flash.locked ro.boot.vbmeta.device_state ro.boot.veritymode; do
        printf '%s=' "$q3s_key"
        getprop "$q3s_key" 2>&1
    done
else
    printf '[getprop 不可用；请在 Android 设备上手工运行]\n'
fi

q3s_section '启动 EL 与相关内核日志'
if q3s_dmesg=$(dmesg 2>&1); then
    printf '%s\n' "$q3s_dmesg" | grep -Ei \
        'started at EL|Booting Linux|Gunyah|CFI failure|module verification|version magic|disagrees about version' \
        || printf '[可读日志中未匹配；缺少 started at EL 行不能据此判断 EL]\n'
else
    printf '%s\n[无法读取 dmesg；未执行任何提权]\n' "$q3s_dmesg"
fi
unset q3s_dmesg

q3s_section '运行内核配置'
if [ -r /proc/config.gz ]; then
    if command -v zcat >/dev/null 2>&1; then
        q3s_config_text=$(zcat /proc/config.gz 2>&1)
        q3s_config_status=$?
    elif command -v gzip >/dev/null 2>&1; then
        q3s_config_text=$(gzip -dc /proc/config.gz 2>&1)
        q3s_config_status=$?
    else
        q3s_config_text='[zcat/gzip 不可用，无法解读 /proc/config.gz]'
        q3s_config_status=1
    fi
    if [ "$q3s_config_status" -eq 0 ]; then
        printf '%s\n' "$q3s_config_text" | grep -E \
            '^(# )?CONFIG_(CC_VERSION_TEXT|CLANG_VERSION|LOCALVERSION(_AUTO)?|ARM64_(VA_BITS.*|4K_PAGES|16K_PAGES|64K_PAGES|FORCE_52BIT)|PGTABLE_LEVELS|LTO.*|CFI.*|SHADOW_CALL_STACK|MODULES|MODULE_UNLOAD|MODULE_FORCE_LOAD|MODULE_SIG.*|MODVERSIONS|MODULE_REL_CRCS|KALLSYMS.*|KPROBES|KEXEC.*|PID_NS|USER_NS|NTSYNC|QCOM_KGSL.*|GUNYAH.*|IKCONFIG.*)(=| is not set)' \
            || printf '[配置可读但未匹配所需项目]\n'
    else
        printf '%s\n[内核配置读取失败]\n' "$q3s_config_text"
    fi
    unset q3s_config_text
else
    printf '[/proc/config.gz 不存在或无读取权限；这不代表相应功能未启用]\n'
fi

q3s_section '模块策略与已加载模块'
q3s_read /proc/sys/kernel/modules_disabled
q3s_read /proc/sys/kernel/tainted
q3s_read /sys/module/module/parameters/sig_enforce
q3s_read /sys/kernel/security/lockdown
q3s_read /proc/modules

q3s_section '模块文件元数据样本：每个目录最多 12 个'
for q3s_moddir in /vendor/lib/modules /vendor_dlkm/lib/modules \
    /odm/lib/modules /odm_dlkm/lib/modules /system/lib/modules \
    /system_dlkm/lib/modules /lib/modules; do
    [ -d "$q3s_moddir" ] || continue
    printf '\n目录 %s\n' "$q3s_moddir"
    find "$q3s_moddir" -type f \( -name '*.ko' -o -name '*.ko.xz' \
        -o -name '*.ko.gz' -o -name '*.ko.zst' \) -print 2>&1 | head -n 12 |
    while IFS= read -r q3s_modfile; do
        printf '\n%s\n' "$q3s_modfile"
        if [ ! -r "$q3s_modfile" ]; then
            printf '[枚举信息或文件不可读]\n'
            continue
        fi
        if command -v modinfo >/dev/null 2>&1; then
            if q3s_modinfo=$(modinfo "$q3s_modfile" 2>&1); then
                printf '%s\n' "$q3s_modinfo" | grep -E \
                    '^(name|vermagic|srcversion|depends|signer|sig_id|sig_key|sig_hashalgo):' \
                    || printf '[modinfo 未提供所需字段]\n'
            else
                printf '%s\n[modinfo 无法解读此文件]\n' "$q3s_modinfo"
            fi
        else
            printf '[modinfo 不可用]\n'
        fi
        case "$q3s_modfile" in
            *.ko)
                if command -v strings >/dev/null 2>&1; then
                    strings "$q3s_modfile" 2>&1 | grep -E \
                        '^(vermagic=|__cfi_check$|__cfi_jt_(init|cleanup)_module$)|Module signature appended' \
                        || printf '[未找到可读 CFI/vermagic/签名标记；不能据此证明未启用]\n'
                else
                    printf '[strings 不可用，未检查 CFI/签名标记]\n'
                fi
                ;;
            *) printf '[压缩模块未做 strings 检查；不解压或写入文件]\n' ;;
        esac
    done
done

q3s_section '物理内存布局（非特权身份可能只看到零地址）'
q3s_read /proc/iomem

q3s_section '实际设备树'
q3s_dtroot=
for q3s_candidate in /sys/firmware/devicetree/base /proc/device-tree; do
    if [ -d "$q3s_candidate" ]; then
        q3s_dtroot=$q3s_candidate
        break
    fi
done
if [ -n "$q3s_dtroot" ]; then
    q3s_dt_text "$q3s_dtroot/model"
    q3s_dt_text "$q3s_dtroot/compatible"
    for q3s_prop in '#address-cells' '#size-cells' qcom,msm-id qcom,board-id; do
        q3s_dt_hex "$q3s_dtroot/$q3s_prop"
    done

    q3s_section 'chosen 启动参数与 splash/framebuffer 属性'
    q3s_dt_text "$q3s_dtroot/chosen/bootargs"
    for q3s_prop in "$q3s_dtroot/chosen"/*; do
        [ -f "$q3s_prop" ] || continue
        case "$q3s_prop" in
            *splash*|*framebuffer*|*display*|*linux,initrd*) q3s_dt_hex "$q3s_prop" ;;
            *stdout*) q3s_dt_text "$q3s_prop" ;;
        esac
    done

    q3s_section 'reserved-memory 节点与范围'
    if [ -d "$q3s_dtroot/reserved-memory" ]; then
        for q3s_prop in '#address-cells' '#size-cells'; do
            q3s_dt_hex "$q3s_dtroot/reserved-memory/$q3s_prop"
        done
        for q3s_node in "$q3s_dtroot/reserved-memory"/*; do
            [ -d "$q3s_node" ] || continue
            printf '\n节点 %s\n' "$q3s_node"
            for q3s_prop in reg size alignment alloc-ranges phandle linux,phandle; do
                [ -e "$q3s_node/$q3s_prop" ] && q3s_dt_hex "$q3s_node/$q3s_prop"
            done
            for q3s_prop in compatible status; do
                [ -e "$q3s_node/$q3s_prop" ] && q3s_dt_text "$q3s_node/$q3s_prop"
            done
            for q3s_prop in no-map reusable linux,cma-default linux,dma-default; do
                [ -e "$q3s_node/$q3s_prop" ] && printf '标记 %s\n' "$q3s_prop"
            done
        done
    else
        printf '[reserved-memory 不存在或不可访问]\n'
    fi

    q3s_section 'DT splash 与 memory-region 引用路径'
    find "$q3s_dtroot" -type f \( -name '*splash*' -o -name 'memory-region' \
        -o -name 'memory-region-names' \) -print 2>&1 |
    while IFS= read -r q3s_prop; do
        if [ ! -f "$q3s_prop" ]; then
            printf '%s\n' "$q3s_prop"
            continue
        fi
        case "$q3s_prop" in
            *memory-region-names) q3s_dt_text "$q3s_prop" ;;
            *) q3s_dt_hex "$q3s_prop" ;;
        esac
    done
else
    printf '[设备树路径不存在或不可访问]\n'
fi

printf '\n采集结束。缺权限或缺命令的项目已注明；未执行提权、模块加载或切换。\n'
exit 0
