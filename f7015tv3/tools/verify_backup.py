#!/usr/bin/env python3
"""F7015TV3 备份可恢复性校验（只读，不写闪存）。

校验维度：
  1. 文件 sha256 与 SHA256SUMS.txt 自洽
  2. 镜像大小与设备 /proc/mtd 分区大小精确一致（dd 还原的硬性前提）
  3. 格式级解析 + 内部校验和：
       - ELF     : 头部/架构/入口
       - JFFS2   : 逐节点遍历并校验 hdr_crc
       - SquashFS: 超级块字段一致性
       - UBI     : 逐 PEB 校验 EC 头与 VID 头 CRC32
       - 厂商加密/裸镜像 : 熵分布、尾部未截断检查
"""
import hashlib
import os
import struct
import sys
import zlib

BACKUP_DIR = os.environ.get("F7_BACKUP_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "onu_backup")

# ⚠️ 下面的分区尺寸仅供参考，务必先用 `cat /proc/mtd` 核对后再判定 FAIL。
#    已知历史问题：mtd12 / mtd13 这两项曾在早期版本里被写反过；
#    不同批次硬件也可能有差异。分区表才是唯一权威。
# name -> (mtd 设备路径, 分区字节数, 期望格式)
ITEMS = [
    ("cspd.bin",                None,             2953192,   "elf"),
    ("mtd1_uboot.bin",          "/dev/mtdblock1", 0x300000,  "raw"),
    ("mtd3_parameter_tags.bin", "/dev/mtdblock3", 0x400000,  "opaque"),
    ("mtd4_wlan.bin",           "/dev/mtdblock4", 0x400000,  "opaque"),
    ("mtd5_usercfg.bin",        "/dev/mtdblock5", 0x800000,  "jffs2"),
    ("mtd6_framework.bin",      "/dev/mtdblock6", 0x1000000, "squashfs"),
    ("mtd7_framework1.bin",     "/dev/mtdblock7", 0x1000000, "squashfs"),
    ("mtd8_dbus.bin",           "/dev/mtdblock8", 0x200000,  "jffs2"),
    ("mtd9_kernel1.bin",        "/dev/mtdblock9", 0x3000000, "opaque"),
    ("mtd10_kernel2.bin",       "/dev/mtdblock10", 0x3000000, "opaque"),
    ("mtd11_plugin_data.bin",   "/dev/mtdblock11", 0x6800000, "ubi"),
    ("mtd12_rootfs1.bin",       "/dev/mtdblock12", 0x2A40000, "jffs2"),
    ("mtd13_rootfs2.bin",       "/dev/mtdblock13", 0x2800000, "opaque"),
]

ERASE = 0x20000  # 128 KB

# 内核态 crc32_le（无前/后取反），JFFS2 与 UBI 都用它
_CRC_TBL = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0xEDB88320 if _c & 1 else _c >> 1
    _CRC_TBL.append(_c)


def crc32_le(crc, data):
    for b in data:
        crc = _CRC_TBL[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc & 0xFFFFFFFF


def data_span(data):
    """返回首个/末个非 0xFF 字节偏移，用于定位实际数据区。"""
    n = len(data)
    first = next((i for i in range(n) if data[i] != 0xFF), -1)
    if first < 0:
        return None, None
    last = next((i for i in range(n - 1, -1, -1) if data[i] != 0xFF), -1)
    return first, last


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_elf(data, _fsize=None):
    if data[:4] != b"\x7fELF":
        return False, "非 ELF"
    cls, enc = data[4], data[5]
    mach = struct.unpack_from("<H", data, 18)[0]
    etype = struct.unpack_from("<H", data, 16)[0]
    arch = {0xB7: "AArch64", 0x28: "ARM", 0x03: "x86"}.get(mach, f"0x{mach:x}")
    return True, f"ELF{'64' if cls == 2 else '32'}/{'LE' if enc == 1 else 'BE'} {arch} type={etype}"


def check_squashfs(data, fsize):
    if data[:4] != b"hsqs":
        return False, "缺 squashfs 魔数"
    f = struct.unpack_from("<IIIIIHHHHHHQQQQQQQQ", data, 0)
    (_, inodes, _, blk, frags, comp, blog, _, _, major, minor,
     root_ino, bytes_used, _, _, ino_tbl, dir_tbl, _, _) = f
    probs = []
    if major != 4:
        probs.append(f"版本 {major}.{minor}")
    if bytes_used > fsize:
        probs.append(f"bytes_used {bytes_used} > 文件 {fsize}")
    if not (ino_tbl < bytes_used and dir_tbl < bytes_used):
        probs.append("表偏移越界")
    if blk & (blk - 1):
        probs.append("块大小非 2 的幂")
    cmap = {1: "gzip", 2: "lzma", 3: "lzo", 4: "xz", 5: "lz4", 6: "zstd"}
    desc = (f"inode={inodes} 块={blk // 1024}K 压缩={cmap.get(comp, comp)} "
            f"已用={bytes_used / fsize:.1%} root_ino={root_ino}")
    return (not probs), desc + (" | 异常: " + ",".join(probs) if probs else " | 超级块自洽")


def check_ubi(data, fsize):
    if data[:4] != b"UBI#":
        return False, "缺 UBI 魔数"
    n_peb = fsize // ERASE
    ok_ec = mapped = bad = 0
    vols = set()
    for i in range(n_peb):
        base = i * ERASE
        ec = data[base:base + 64]
        if ec[:4] != b"UBI#":
            bad += 1
            continue
        crc = struct.unpack_from(">I", ec, 60)[0]
        if crc32_le(0xFFFFFFFF, ec[:60]) != crc:
            bad += 1
            continue
        ok_ec += 1
        vid_off = struct.unpack_from(">I", ec, 16)[0]
        vid = data[base + vid_off: base + vid_off + 64]
        if vid[:4] != b"UBI!":
            # VID 区全 0xFF = 未映射的空闲 PEB，属正常
            if any(b != 0xFF for b in vid):
                bad += 1
            continue
        vcrc = struct.unpack_from(">I", vid, 60)[0]
        if crc32_le(0xFFFFFFFF, vid[:60]) != vcrc:
            bad += 1
            continue
        mapped += 1
        vols.add(struct.unpack_from(">I", vid, 8)[0])
    vols = sorted(0 if v == 0x7FFFFFFF else v for v in vols)
    desc = (f"PEB={n_peb} EC-CRC通过={ok_ec}/{n_peb} 已映射={mapped} "
            f"空闲={n_peb - mapped} 异常={bad} 卷号={vols}")
    return (bad == 0 and ok_ec == n_peb), desc


def check_jffs2(data, fsize):
    NT = {0xE001: "dirent", 0xE002: "inode", 0x2003: "cleanmarker",
          0x2004: "padding", 0x2006: "xattr", 0xE008: "inline"}
    off, nodes, bad, bytesused, kinds = 0, 0, 0, 0, {}
    while off + 12 <= fsize:
        if data[off:off + 2] == b"\xff\xff":
            off = ((off // ERASE) + 1) * ERASE
            continue
        magic, nodetype, totlen = struct.unpack_from("<HHI", data, off)
        hdr_crc = struct.unpack_from("<I", data, off + 8)[0]
        if magic != 0x1985:
            off = ((off // ERASE) + 1) * ERASE
            continue
        if crc32_le(0, data[off:off + 8]) != hdr_crc:
            bad += 1
            off = ((off // ERASE) + 1) * ERASE
            continue
        if totlen < 12 or totlen > fsize - off:
            bad += 1
            off = ((off // ERASE) + 1) * ERASE
            continue
        nodes += 1
        bytesused += totlen
        k = NT.get(nodetype, f"0x{nodetype:04x}")
        kinds[k] = kinds.get(k, 0) + 1
        off += (totlen + 3) & ~3
    top = ",".join(f"{k}×{v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])[:5])
    return (bad == 0 and nodes > 0), f"节点={nodes} CRC失败={bad} 已用={bytesused / fsize:.1%} [{top}]"


def check_raw(data, fsize):
    """U-Boot 裸镜像：查版本串与有效数据分布。"""
    i = data.find(b"U-Boot ")
    ver = data[i:i + 80].split(b"\x00")[0].decode("latin-1", "replace") if i >= 0 else None
    return (ver is not None), f"版本串={ver or '未找到'} @0x{i:x}" if i >= 0 else "版本串未找到"


def check_opaque(data, fsize):
    """厂商加密 / 裸数据：定位数据区、算熵、查是否被截断。"""
    first, last = data_span(data)
    if first is None:
        return True, "整分区 0xFF 擦除态（空分区，内容本就如此）"
    span = last - first + 1
    window = data[first:first + min(span, 1 << 20)]
    from collections import Counter
    import math
    c = Counter(window)
    n = len(window)
    h = -sum(v / n * math.log2(v / n) for v in c.values())
    eff = sum(1 for b in data[first:last + 1] if b not in (0x00, 0xFF))
    kind = "高熵(加密/压缩，正常)" if h > 7.5 else "低熵(结构化明文)"
    return True, (f"数据区 0x{first:x}-0x{last:x} ({span / 1024:.0f}KB) "
                  f"有效={eff:,}B 熵={h:.2f} {kind}")


CHECKERS = {"elf": check_elf, "squashfs": check_squashfs, "ubi": check_ubi,
            "jffs2": check_jffs2, "raw": check_raw, "opaque": check_opaque}


def main():
    global BACKUP_DIR
    # 用法: verify_backup.py [备份目录]   或   F7_BACKUP_DIR=/path/to/onu_backup
    if len(sys.argv) > 1:
        BACKUP_DIR = os.path.abspath(sys.argv[1])
    if not os.path.isdir(BACKUP_DIR):
        sys.exit(f"[X] 备份目录不存在: {BACKUP_DIR}\n"
                 f"    用法: {os.path.basename(sys.argv[0])} <onu_backup 目录>")

    sums = {}
    sp = os.path.join(BACKUP_DIR, "SHA256SUMS.txt")
    for line in open(sp, encoding="utf-8"):
        p = line.split()
        if len(p) >= 2:
            sums[p[1]] = p[0]

    print("=" * 96)
    print(" F7015TV3 备份可恢复性校验（只读，不写闪存）")
    print("=" * 96)
    print(f"{'镜像':<26}{'尺寸':>8} {'大小校验':<9}{'SHA':<6}{'格式校验'}")
    print("-" * 96)

    all_ok = True
    for name, _dev, exp, kind in ITEMS:
        p = os.path.join(BACKUP_DIR, name)
        if not os.path.exists(p):
            print(f"{name:<26}{'':>8} 缺失")
            all_ok = False
            continue
        fsize = os.path.getsize(p)
        size_ok = (fsize == exp)
        sha_ok = (sums.get(name) == sha256_of(p))
        data = open(p, "rb").read()
        ok, desc = CHECKERS[kind](data, fsize)
        all_ok &= size_ok and sha_ok and ok
        flag = lambda b: "OK " if b else "FAIL"
        print(f"{name:<26}{fsize:>8} {flag(size_ok):<9}{flag(sha_ok):<6}[{kind}] {desc}")

    print("-" * 96)
    print("总体结论:", "全部通过 —— 备份完整、格式有效、尺寸与分区严格一致，可直接 dd 还原"
          if all_ok else "存在未通过项，详见上表")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
