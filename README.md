# 上海电信 10G-EPON 光猫研究：HG5143F-V2 与 F7015TV3

同一条家庭宽带线上，先后折腾过的两台光猫的完整记录 —— 一台是**怎么进得去**，一台是**怎么换得掉**。

> 仓库名 `SH-SDN` 沿用最初的研究对象（上海电信 SDN 网关）。后来补上了替换猫的换机手册，
> 现在是一个「同线路、两台设备」的合集。

---

## 1. 两台设备

| | 烽火 **HG5143F-V2** | 中兴 **ZXHN F7015TV3** |
|---|---|---|
| 角色 | 电信原配「智能随选网关」（SDN 版） | 自购替换，纯桥接 |
| 固件 | `FHQZ.4.0.0` / HW `V4.0.0` | `V4.3.0P1T1` |
| 主控 / 系统 | Broadcom **BCM68560** · aarch64 · Linux 4.1.52 | aarch64 · Linux 5.4.196 · BusyBox 1.17.2 |
| 上网方式 | **IPoE / DHCP**（设备内无 PPPoE 凭据） | Bridge · VLAN 0，由 RouterOS 拨 PPPoE |
| 22/23 端口 | ❌ 交换芯片层封死，软件无解 | ✅ 可开（webFac 工厂接口） |
| 本地 root | ✅ 靠 Web 命令注入，非持久 | ✅ 靠 Telnet，`/userconfig` 持久 |
| 持久化改动 | ❌ `/` 只读 squashfs，重启回滚 | ✅ 可写持久分区，但有恢复出厂风险 |
| 详细文档 | [hg5143f/](hg5143f/) | [f7015tv3/](f7015tv3/) |

**为什么会有这两台**：原猫是 SDN 版，配置所有权在云端控制器，本地既关不掉自带 WiFi，
也换不了软件栈。于是买了 F7015TV3 做纯桥接，把拨号、NAT、WiFi 全部搬到自己的 RouterOS 上。

---

## 2. 这条线路的技术底牌（两台设备互证）

下面每一项都在两台机器上分别验证过，不是从文档抄的：

| 项 | 值 | 验证方式 |
|---|---|---|
| PON 制式 | **10G-EPON**（非对称，`XEPON_ASY`） | 原猫 `ctapi pon get pon_type`；新猫插纤即注册，无需切模式 |
| 认证 | LOID `XXXXXXXXXX`（10 位数字），上海 `PONPASSWD` 为空 | 原猫 `ctapi pon get loid`；新猫 `setmac 2 2180` 回读 |
| 上网 VLAN | **0 —— 不打标签** | 原猫 ovsdb `WANConnection` 表实读；新猫 WAN 配 Bridge/VLAN 0 后拨号成功 |
| IPTV VLAN | **85 / 51** | 原猫 `iptv.85` / `iptv.51` 端口 + 硬件流表 |
| 管理 VLAN | **46** | 原猫 `dm_addr.conf` + 运行时接口 |
| 光功率 | Rx **−22 ~ −23 dBm**（良好，余量约 5 dB） | 两台机器的 DDM 读数 |
| 区域码 | **205 = 上海**，206 = 重庆（中兴 `upgradetest` 体系） | 新猫三处交叉验证，见 [f7015tv3/README.md](f7015tv3/README.md) |

> ⚠️ 各地电信的 VLAN 规划并不统一，上表只对**上海**这条线路成立。
> 换机前请用原猫实测确认，不要照抄网上的通用教程。

---

## 3. 两条技术路径

### 路径 A —— 进得去（HG5143F）

设备把 SSH/Telnet 端口在**交换芯片层面**封了，但 Web 服务里有个 root 权限的命令注入点。
由此做了三件事：

1. 把一次性注入改造成**持久化交互式 shell**（FIFO + 常驻 `sh`，`exec 9<>` 避免读端 EOF）
2. 逐层证明「22/23 端口打不开」的**真正原因**在 OVS 流表白名单 + BCM68560 硬件转发，不在 netfilter
3. dump 出完整网络架构（命名空间 / VLAN-MAC 派生 / SDN 控制器），**这份 dump 直接成了换猫的依据**

→ [hg5143f/README.md](hg5143f/README.md) · [hg5143f/network-dump.md](hg5143f/network-dump.md)

### 路径 B —— 换得掉（F7015TV3）

拿到原猫的真实参数后，按固定顺序操作新猫：开 Telnet → 全分区备份 → 改区域码 → 重开 Telnet →
写 LOID → 屏蔽 ITMS/TR-069 → 禁用语音 WAN → 插纤验证。

19 条踩坑记录，其中最关键的两条：
- **`sendcmd 1 DB set GPONCFG Loid` 是无效的**，该字段 `bSave=0` 不入库，必须用 `setmac 1 2180`
- **`sdefconf` 改区域码会恢复出厂并清掉 Telnet**，所以备份和开 Telnet 必须排在它前面

→ [f7015tv3/README.md](f7015tv3/README.md)

---

## 4. 两台设备教给我们的六件事

1. **先判断固件血统，再找教程。** 网上「HG5143F 开 telnet」的教程全部针对「天翼网关 4.0」，
   而 SDN 版是另一套软件栈（`Server: sdngw`）。版本号对不上就先停手。
2. **参数存在哪，决定了怎么改。** 三种存储，三种改法，混用必失败：
   - cspd 配置库（`sendcmd 1 DB`）—— 有 `bSave` 列，`bSave=0` 的字段改了不持久
   - flash TagParam（`setmac`）—— LOID / SN / MAC 真正落盘处，加密存储
   - ovsdb（`/usr/local/db/conf.db`）—— SDN 版专用，带 `OVSDB JSON <len> <sha1>` 头校验，且被常驻进程回写
3. **交叉验证，别信单一来源。** 「区域码生效了吗」看 `db_default_cfg.xml` 字节数（8136 vs 6872）；
   「上网 VLAN 多少」读 ovsdb 而不是看源码注释；博客说 VLAN 1，实测是 VLAN 0。
4. **负面结果比成功经验值钱。** 「22/23 打不开」「WiFi 持久化关不掉」「`vlanctl` 在本机一律报错」
   这三条结论，能帮后来者省掉几天时间。
5. **顺序即安全。** 备份在恢复出厂之前，屏蔽 ITMS 在插纤之前。顺序错了不可逆。
6. **只读先跑通，再谈改动。** 所有诊断都先在只读模式下拿到基线，改之前留快照。

---

## 5. 目录结构

```
.
├── README.md                  ← 本文件：概述与导航
├── hg5143f/                   ← 原猫：SDN 网关提权与网络剖析
│   ├── README.md              ← 注入点、持久 shell、22/23 端口为何不可达
│   ├── network-dump.md        ← 实机网络 dump（换猫依据）
│   ├── onu_shell.py           ← 无状态单命令客户端
│   └── onu_console.py         ← 持久化交互式 shell
├── f7015tv3/                  ← 新猫：换机手册
│   ├── README.md              ← 开 Telnet → 备份 → 改区 → 写 LOID → 屏蔽 ITMS
│   └── tools/
│       ├── read_optical.py        ← 光功率采样与 dBm 换算
│       ├── onu_telnet_admin.py    ← Telnet 密码试错 / dump TelnetCfg / 改密码
│       └── verify_backup.py       ← 分区镜像离线校验（尺寸 + SHA256 + CRC）
└── docs/
    └── anonymization.md       ← 脱敏说明：哪些值被隐去、为什么
```

---

## 6. 脱敏说明

仓库里所有设备标识都已打码：**LOID、SN、MAC、Telnet 密码、WiFi SSID/PSK** 一律为占位符。

保留的「半公开」信息及理由见 [docs/anonymization.md](docs/anonymization.md) ——
主要是厂商**出厂超密**（区域内统一，属于厂商侧缺陷）和**区域码**（固件内置映射表，32 行明文）。

---

## 7. 免责与合规

- 所有操作均在**自己拥有 / 已获授权**的设备上进行。未经授权访问他人网络设备在绝大多数司法辖区违法。
- 改区域码会**恢复出厂**，写交换芯片寄存器、刷分区有**变砖风险**，恢复多半只能靠串口或返修。
- 拆机接线接错电平会**永久损坏**设备（3.3V TTL，别接 VCC）。
- 文中提到的默认密码、硬编码 cookie、未授权信息泄露接口，属于厂商侧安全缺陷。
  **请勿用于攻击他人设备**；如果你是自己设备的用户，建议改掉密码并向运营商报备。

---

## 8. 参考资料

- [haoqi366/SDN_research](https://github.com/haoqi366/SDN_research) —— 本仓库起点，首次公开了 HG5143F 的 URL 路径注入链
- [qiudz/zte-f7015tv3-telnet-solidify](https://github.com/qiudz/zte-f7015tv3-telnet-solidify) —— F7015TV3 开 Telnet 固化脚本
- [hack-gpon/hack-gpon.github.io](https://github.com/hack-gpon/hack-gpon.github.io) —— GPON/ONU 总 wiki，改区与刷机流程
- [douniwan5788/zte_modem_tools](https://github.com/douniwan5788/zte_modem_tools) —— 中兴开 Telnet、权限门控
- [edisionnano/F8648P](https://github.com/edisionnano/F8648P) —— 中兴 `flag_type` 与命令白名单机制剖析
- [dreamzone-cc/zudz](https://github.com/dreamzone-cc/zudz) —— 中兴改区 / 解密 / GPON 身份工具集

---

*整理时间：2026-11-22*
