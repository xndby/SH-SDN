#!/usr/bin/env python3
"""F7015TV3 光功率采样（只读）。

多次采样 `opticaltst -getpara`，按 SFF-8472 DDM 口径换算成 dBm / ℃ / mA / V。

换算口径（别和 `ponstat` 的 ADC 路径混用，两者 Tx 能差 3 dB）：
    Tx/Rx : 原始值 × 0.1 µW  → mW → dBm
    temp  : 原始值 / 256
    bias  : 原始值 × 2 µA
    V     : 原始值 / 10000

凭据不落盘，用参数或环境变量传入：
    F7_HOST / F7_USER / F7_PASS

依赖第三方仓库的 telnet 登录封装：
    git clone https://github.com/qiudz/zte-f7015tv3-telnet-solidify
    export ZTE_SOLIDIFY_SCRIPTS=/path/to/zte-f7015tv3-telnet-solidify/scripts

用法：
    python read_optical.py -p 'root-password' -n 5
"""
import argparse
import math
import os
import re
import sys
import time

DEFAULT_LIB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "zte-f7015tv3-telnet-solidify", "scripts",
)


def load_lib():
    lib = os.environ.get("ZTE_SOLIDIFY_SCRIPTS") or os.path.normpath(DEFAULT_LIB)
    if not os.path.isdir(lib):
        sys.exit(
            "[X] 找不到 zte_webfac_v3 所在目录。\n"
            "    git clone https://github.com/qiudz/zte-f7015tv3-telnet-solidify\n"
            "    export ZTE_SOLIDIFY_SCRIPTS=/path/to/zte-f7015tv3-telnet-solidify/scripts"
        )
    sys.path.insert(0, lib)
    from zte_webfac_v3 import telnet_login  # noqa: E402
    return telnet_login


def run(t, cmd, wait=2.0):
    t.send(cmd)
    out = t.drain(wait).decode("utf-8", errors="replace").replace(cmd, "")
    return re.sub(r"[#\$>]\s*$", "", out.strip())


def uw_to_dbm(uw):
    return 10 * math.log10(uw) if uw > 0 else float("-inf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-H", "--host", default=os.environ.get("F7_HOST", "192.168.1.1"))
    ap.add_argument("-u", "--user", default=os.environ.get("F7_USER", "root"))
    ap.add_argument("-p", "--password", default=os.environ.get("F7_PASS"),
                    help="Telnet 密码（也可用环境变量 F7_PASS）")
    ap.add_argument("-n", "--count", type=int, default=5, help="采样次数")
    ap.add_argument("-i", "--interval", type=float, default=3.0, help="采样间隔秒")
    a = ap.parse_args()

    if not a.password:
        sys.exit("[X] 需要 Telnet 密码：-p <pw> 或环境变量 F7_PASS")

    telnet_login = load_lib()
    t = telnet_login(a.host, a.user, a.password)
    try:
        t.send("")
        time.sleep(0.4)
        print("--- usage ---")
        print(run(t, "opticaltst", 2.0)[:800])
        print(f"--- samples ({a.count}x, {a.interval:g}s apart) ---")
        for i in range(a.count):
            r = run(t, "opticaltst -getpara", 1.6)
            d = dict(re.findall(r"(optical\s+\w+)=(-?\d+)", r))
            tx = int(d.get("optical TXPower", 0)) * 0.1 / 1000.0
            rx = int(d.get("optical RXPower", 0)) * 0.1 / 1000.0
            temp = int(d.get("optical temp", 0)) / 256.0
            bias = int(d.get("optical TXBiasCurrent", 0)) * 0.002
            volt = int(d.get("optical SupplyVoltage", 0)) / 10000.0
            print(f"#{i + 1} raw TX={d.get('optical TXPower')} RX={d.get('optical RXPower')} "
                  f"-> Tx {uw_to_dbm(tx):+.2f} dBm  Rx {uw_to_dbm(rx):+.2f} dBm  "
                  f"Temp {temp:.1f}C  Bias {bias:.2f}mA  V {volt:.2f}V")
            if i + 1 < a.count:
                time.sleep(a.interval)
    finally:
        t.close()


if __name__ == "__main__":
    main()
