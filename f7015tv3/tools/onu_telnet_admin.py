#!/usr/bin/env python3
"""F7015TV3 Telnet 运维小工具（只读优先）：登录 / dump TelnetCfg / 改 Telnet 密码。

凭据不落盘。试密码走 `--try`（可多次），改密码走 `--set`。

依赖第三方仓库的 telnet 登录封装：
    git clone https://github.com/qiudz/zte-f7015tv3-telnet-solidify
    export ZTE_SOLIDIFY_SCRIPTS=/path/to/zte-f7015tv3-telnet-solidify/scripts

用法：
    # 只读：试密码 + dump TelnetCfg
    python onu_telnet_admin.py --try 'xxxxxx'

    # 改密码
    python onu_telnet_admin.py --try 'xxxxxx' --set '<new-password>'

注意：`--set` 会写 `TelnetCfg.TS_UPwd` / `TSLan_UPwd` 并 `DB save`，
      属于持久化修改，改完请立刻记下新密码。
"""
import argparse
import os
import sys

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-H", "--host", default=os.environ.get("F7_HOST", "192.168.1.1"))
    ap.add_argument("--user", default=os.environ.get("F7_USER", "root"))
    ap.add_argument("--try", dest="tries", action="append", default=[],
                    help="候选密码，可多次指定")
    ap.add_argument("--set", dest="newpass", default=None,
                    help="成功后把 Telnet 密码改为该值")
    a = ap.parse_args()

    if not a.tries:
        sys.exit("[X] 至少给一个 --try <候选密码>")

    telnet_login = load_lib()
    t = None
    for p in a.tries:
        print(f"[*] 尝试 {a.user} / {'*' * len(p)}")
        try:
            tt = telnet_login(a.host, a.user, p)
            tt.send("id")
            out = tt.drain(1.5).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"[-] 连接/登录异常: {e}")
            continue
        if "uid=" in out.lower():
            print("[+] 登录成功")
            print(f"[*] id -> {out.strip().splitlines()[0][:160]}")
            t = tt
            break
        print("[-] 未见 shell 提示，换下一个")
        tt.close()

    if t is None:
        print("[X] 候选密码全部失败")
        sys.exit(1)

    print("\n=== 当前 TelnetCfg ===")
    t.send("sendcmd 1 DB p TelnetCfg")
    print(t.drain(2.5).decode("utf-8", errors="replace"))

    if a.newpass:
        print("[*] 改写 Telnet 密码（TS_UPwd / TSLan_UPwd）")
        for field in ("TS_UPwd", "TSLan_UPwd"):
            t.send(f'sendcmd 1 DB set TelnetCfg 0 {field} "{a.newpass}"')
            t.drain(0.8)
        t.send("sendcmd 1 DB save")
        print("=== DB save ===")
        print(t.drain(2.5).decode("utf-8", errors="replace"))

        print("=== 回读 TelnetCfg ===")
        t.send("sendcmd 1 DB p TelnetCfg")
        print(t.drain(2.5).decode("utf-8", errors="replace"))

    t.close()


if __name__ == "__main__":
    main()
