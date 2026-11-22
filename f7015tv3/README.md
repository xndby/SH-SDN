# 中兴 ZXHN F7015TV3 换猫手册（上海电信 10G-EPON）

> 场景：上海电信 10G-EPON 线路，用 ZTE ZXHN F7015TV3 替换原烽火 HG5143F-V2，
> 光猫纯桥接，PPPoE 由 RouterOS 拨号。
>
> 所有命令均为**实机验证**（固件 `V4.3.0P1T1`，BusyBox 1.17.2，aarch64 / Linux 5.4.196）。
>
> 文中 LOID、Telnet 密码、SN、MAC 均为占位符，脱敏规则见 [../docs/anonymization.md](../docs/anonymization.md)。
> 被替换的原猫（SDN 网关）那一侧的研究见 [../hg5143f/](../hg5143f/)。

---

## 1. 一句话结论（下次换猫直接抄这个）

| 项 | 值 |
|---|---|
| 区域码 | **205**（上海），`upgradetest sdefconf 205`；原厂为 **206**（重庆） |
| LOID | `XXXXXXXXXX`（10 位数字），写 `setmac 1 2180 XXXXXXXXXX` |
| 超密 | `telecomadmin` / `nE7jA%5m`（改区域码不影响它） |
| Telnet | `root` / `XXXXXXXXXXXX`（12 位，仅 LAN 可达） |
| PON 模式 | 模块本身是 **XEPON_ASY（10G-EPON 非对称）**，无需切换 |
| 上网 WAN | `2_INTERNET_B_VID_`，**Bridge / VLAN 0（不打标签）**，交给 RouterOS |
| 语音/管理 WAN | `1_TR069_VOICE_R_VID_46`，**Enable=0 已禁用** |
| ITMS / TR-069 | 均已屏蔽，重启 + 插纤后无任何下发 |

> 这批参数不是猜的：VLAN 0、IPTV 85/51、管理 46、PON 制式，都是在原猫上实测 dump 出来的，
> 见 [../hg5143f/network-dump.md](../hg5143f/network-dump.md)。
>
> 参数区（flash TagParam）的完整 ID 索引 —— 哪个 Tag ID 对应 LOID / SN / MAC / SSID，
> 换机时到底该改哪 6 项 —— 见 [docs/tagparam-map.md](docs/tagparam-map.md)。

---

## 2. 换猫总流程（按顺序，别跳步）

```
① 记录原猫参数（LOID、VLAN、鉴权方式）      ← 最容易漏，漏了就得求装维
② 新猫开 Telnet（webFac 漏洞，不拆不重置）
③ 全分区备份（13 个 mtd，出问题能回滚）
④ 改区域码（重庆 206 → 上海 205，会恢复出厂）
⑤ 重新开 Telnet（改区把配置清了）
⑥ 写 LOID + 屏蔽 ITMS + 屏蔽 TR069（每步重启验证）
⑦ 禁用 TR069/VOICE WAN，保留桥接 WAN
⑧ 插纤 → 验证 PON 注册 / 光功率 / PPPoE / 配置零漂移
```

关键顺序原因：

- **②③ 必须在 ④ 之前**。`sdefconf` 会恢复出厂并清掉 Telnet，先备份才有退路。
- **⑥ 必须在插纤前**。插上光纤 ITMS 可能立刻下发配置、覆盖区域码甚至关 Telnet
  （本机 `TelnetCfg` 没有 `Lan_EnableAfterOlt` 字段，**没有抗下发机制**）。

---

## 3. 命令速查

### 3.1 开 Telnet（webFac v3）

```bash
# 仓库：https://github.com/qiudz/zte-f7015tv3-telnet-solidify
python scripts/zte_webfac_v3.py auto -u telecomadmin -p 'nE7jA%5m'
# 成功后：23 端口开放，root / <设定密码> 登录，uid=0
```

- 走的是 webFac 工厂接口的 `re_rand` 二次校验（`FactoryMode.gch`），**不需要恢复出厂、不需要拔纤**。
- 附带工具 [`tools/onu_telnet_admin.py`](tools/onu_telnet_admin.py)：`--try <pw>` 试密码并 dump `TelnetCfg`，`--set <newpw>` 改密码。
- 改完后 `TelnetCfg` 应为：`Lan_Enable=1`、`Wan_Enable=0`（只允许 LAN 侧登录）、
  `Max_Con_Num=99`、`ExitTime=999999`、`InitSecLvl=3`。

> **工具依赖**：`tools/` 下两个脚本复用第三方仓库的 telnet 登录封装，本仓库不内置它：
>
> ```bash
> git clone https://github.com/qiudz/zte-f7015tv3-telnet-solidify
> export ZTE_SOLIDIFY_SCRIPTS=$PWD/zte-f7015tv3-telnet-solidify/scripts
> ```
>
> 凭据一律走参数或环境变量（`F7_HOST` / `F7_USER` / `F7_PASS`），脚本里没有任何硬编码密码。

### 3.2 全分区备份

```bash
python scripts/tftp_server.py            # 用能过防火墙的解释器启动
python scripts/backup_mtd_all.py         # 13 个 mtd + cspd.bin，约 27 分钟
python tools/verify_backup.py            # 离线校验：尺寸 + SHA256 + 格式级 CRC
```

### 3.3 改区域码

```bash
upgradetest gdefconf                     # 查当前：返回 "206!" / "205!"
upgradetest sdefconf 205                 # 改上海，返回 success! 后自动重启
```

三处交叉验证（缺一不可）：

```bash
upgradetest gdefconf                     # → 205!
hexdump -C /userconfig/flag_type         # → "current : 205\n\0"（15 字节）
ls -l /userconfig/cfg/db_default_cfg.xml # → 8136 字节 = Shanghai 模板（重庆是 6872）
```

> **为什么看字节数最可靠**：区域码本身只是个数字，真正决定行为的是「哪份模板被复制到
> `db_default_cfg.xml`」。上海模板 8136 字节、重庆模板 6872 字节，长度对得上就说明模板真的换了。

### 3.4 LOID（不在配置库里，在 flash TagParam）

```bash
setmac show2                             # 看全部明文参数（56 行 / 2310 字节）
setmac 1 2180 XXXXXXXXXX                 # 写 PONLOID，唯一正确入口
setmac 2 2180                            # 回读：hex 30 30 33 33 ... = ASCII 的 LOID
# PONPASSWD(2181) 上海电信保持为空
```

> ⚠️ `sendcmd 1 DB set GPONCFG 0 Loid xxx` **无效**，该字段 `bSave=0`，改完 `Change` 仍为 0。
> 这是最容易踩的坑。

### 3.5 屏蔽 ITMS 下发

```bash
sendcmd 1 DB set PDTCTUSERINFO 0 Status 0
sendcmd 1 DB set PDTCTUSERINFO 0 Result 1
sendcmd 1 DB set PDTCTUSERINFO 0 AutoRegFlg 0
sendcmd 1 DB set PDTCTUSERINFO 0 tForcePushFlg 0
sendcmd 1 DB save
```

### 3.6 屏蔽 TR-069

```bash
sendcmd 1 DB set MgtServer 0 Tr069Enable 0
sendcmd 1 DB set MgtServer 0 PeriodicInformEnable 0
sendcmd 1 DB set MgtServer 0 URL http://127.0.0.1
sendcmd 1 DB save
```

### 3.7 禁用 TR069/VOICE WAN（不用语音才做）

```bash
sendcmd 1 DB p WANC                      # 先确认行号：Row0=TR069/VOICE，Row1=INTERNET Bridge
sendcmd 1 DB set WANC 0 Enable 0
sendcmd 1 DB save
```

### 3.8 状态与光功率

```bash
ct_getPonStat                            # → PON_STAT=Registered
opticaltst -getpara                      # 光功率/温度/电压/Bias（SFF-8472 DDM）
opticaltst -gettransceiverinfo           # 模块厂商、PN、生产日期
tail -5 /proc/tempsensor; cat /proc/cpuusage
cat /proc/lanrate/portspeed              # 各口字节计数（无速率字段）
```

现成脚本：[`tools/read_optical.py`](tools/read_optical.py)（采样 5 次并自动换算 dBm）。

---

## 4. 原理：为什么这么做

### 4.1 区域码怎么生效

```
/etc/init.d/regioncode            # 32 行明文映射表，如 205:Shanghai、206:Chongqing
        ↓ 由 /userconfig/flag_type 里的 "current : <码>" 决定
/etc/init.d/rcS (199-260)         # 读码 → 映射省名
        ↓
cp -f /etc/db_default_<省>_cfg.xml  →  /userconfig/cfg/db_default_cfg.xml
```

- 所以判断改区是否真生效，看 `db_default_cfg.xml` 的**字节数**最直接（上海 8136 / 重庆 6872）。
- `db_user_cfg.xml` 不受影响，但 `sdefconf` 本身会恢复出厂。
- 网页端没有入口（`hidden_version_switch.gch`、`version_switch.gch` 均不存在，482 个 gch 里没有省区相关）。
- 改区**不影响 telecomadmin 超密**，205 区域下仍是 `telecomadmin` / `nE7jA%5m`。

### 4.2 参数存哪：cspd 配置库 vs flash TagParam

| 存储 | 访问方式 | 特点 |
|---|---|---|
| cspd 配置库 | `sendcmd 1 DB p/get/set/save` | 有 `bSave` 列，`bSave=0` 的字段**改了不持久**（如 `GPONCFG.Loid`） |
| flash TagParam (mtd3) | `setmac show2 / 1 / 2` | LOID、SN、MAC、SSID、PSK 真正落盘处；受 `INDIVKEY[1824]` 加密 |

> 判断一个字段能不能改：`sendcmd 1 DB pti <表> <字段>` 看 `bSave`。`bSave=0` 且 `Change` 不变 = 改了白改。
> 注意：`sendcmd 1 DB set` 对**不存在**的字段是**静默忽略**，不报错
> （README 里常见的 `Lan_EnableAfterOlt`、`CloseServerTime` 在本固件就不存在）。

### 4.3 为什么光猫要纯桥接

- 原猫 HG5143F 是 SDN 版，跑的是 **IPoE/DHCP**，本机根本没有 PPPoE 账号密码
  （`/etc/ppp` 不存在、无 pppd）。这一点在 [../hg5143f/network-dump.md](../hg5143f/network-dump.md)
  第 7 节有三条独立证据。
- 新猫保留 `2_INTERNET_B_VID_` 为 **Bridge / VLAN 0（不打标签）**，RouterOS 用宽带账号直接
  PPPoE 拨号，光猫自身**无 WAN IP** → 没有双重 NAT。
- 换句话说：**原猫里抄不到 PPPoE 账号**（它不用），但这条线路确实支持 PPPoE —— 账号得从
  装机单或电信 App 取，不是从光猫取。

---

## 5. 坑位清单（现象 → 原因 → 解法）

| # | 现象 | 原因 | 解法 |
|---|---|---|---|
| 1 | `sendcmd set GPONCFG Loid` 返回成功但重启后 LOID 没变 | 该字段 `bSave=0`，不入库 | 用 `setmac 1 2180` |
| 2 | 给不存在的字段 set，也不报错 | BusyBox 版 sendcmd 静默忽略 | 先 `sendcmd 1 DB p <表>` 确认字段存在 |
| 3 | 设备上没有 `dd`（`busybox dd` 也没有） | 固件裁剪 | 取字节区间用 `hexdump -s off -n len` 或 `tail -c +N` |
| 4 | 也没有 `head` / `strings` | 同上 | 用 `sed -n`、`grep`、`cat`、`hexdump`、`wc` |
| 5 | 备份脚本 mtd12/mtd13 尺寸对不上 | 脚本内置参考表把这两项写反 | 一律以 `/proc/mtd` 为准 |
| 6 | mtd5/mtd8 md5 每次都不一样 | 是 rw 挂载的 jffs2，内容持续变动 | 只当作时间点快照；用「设备算 md5 → 立即拉取 → 比对」证明传输无损 |
| 7 | 大分区 TFTP 传到一半数据错乱 | BusyBox tftp 512 字节块 + 逐块 ACK，块号在 32MB 处回绕 | 控制在 32MB 以内分段拉，或换服务端支持 blksize |
| 8 | telnet 交互读不到输出 / 错位 | 命令回显里含提示符 `# `，`read_until` 被污染 | 改成「设备写文件，新开会话 cat 出来」 |
| 9 | `upgradetest` 没有 `sfactoryconf` | 本 build 只编译了 `gdefconf` / `sdefconf`（与 hack-gpon wiki 不同） | 只用这两个 |
| 10 | `sdefconf` 后 Telnet 立刻断、脚本拿不到回读 | 恢复出厂触发重启，连接被重置 | 正常现象，等 50~60s 重连 |
| 11 | 改区后 FTP/23 全关 | 恢复出厂已发生 | 重新跑一遍 Telnet 固化 |
| 12 | 插纤后 Telnet 被关 | ITMS 下发覆盖；本固件无 `Lan_EnableAfterOlt` 防覆盖字段 | 插纤前先把 ITMS/TR069 全屏蔽 |
| 13 | 网线只协商到 100 Mbps | 光猫口无速率限制（`MaxBitRate=0`），瓶颈在网线只通 2 对 | 换 Cat5e 以上成品线，检查水晶头（本项**未修复**） |
| 14 | 上行字节数反而高于下行 | 疑似 Windows/OneDrive 后台上传或 PPPoE 初期重连 | 观察即可，非故障 |
| 15 | 博客说上海 PPPoE 要 VLAN 1 | 本线路实测是**不打标签**（VLAN 0 桥接） | 以 `sendcmd 1 DB p WANC` 实读为准 |
| 16 | `ponstat` 和 `opticaltst` 光功率不一致（Tx 差 3 dB） | 两条不同测量路径（模块 DDM vs 驱动 ADC），OEM BOSA 自校准有偏差 | 以 `opticaltst -getpara`（SFF-8472）为准 |
| 17 | `opticaltst -getreg` 读原始寄存器返回 0 | 该固件参数解析 bug（reg 被当成 0x0/0x2） | 放弃，用 `-getpara` |
| 18 | 想从 mtd3 备份里 `strings` 找 LOID | 参数区加密存储（INDIVKEY 保护） | 只能从运行态 `setmac show2` 读 |
| 19 | 换猫后担心 GPON/EPON 模式不对 | `EGPONSWEN[40963]=1` 可切，但本机模块自带 XEPON | 实测插纤即注册，无需切换 |

---

## 6. 光功率基线（判断线路好坏用）

同一条线、同为 10G-EPON 的实测对比：

| 项 | 烽火 HG5143F-V2（原猫） | 中兴 F7015TV3（新猫） | 说明 |
|---|---|---|---|
| Rx | −23.01 dBm | **−22.1 dBm**（稳定） | 由 ODN 决定，与猫无关；差 0.9 dB 属标定噪声 |
| Tx | +3.53 dBm | +0.9 dBm（DDM） | 见坑 #16，`ponstat` 另报 +3.9 |
| 模块温度 | 48.2℃ | 41.8 ~ 43.8℃ | 新模块更凉 |
| Bias / V | — | 12.9 mA / 3.30 V | 正常 |

**判断标准**

- Rx 优于 **−25 dBm**：良好；−25 ~ −27：临界；差于 **−27 dBm**：需要报修查线路/分光器。
- 当前 −22.1 dBm，到灵敏度还有约 5 dB 余量。
- `EPONSilenceCount=0` 表示没有上行静默/失步事件，是上行链路健康的好指标；开始增长就要警惕。

**读数口径（别混用）**

- `opticaltst -getpara`：SFF-8472 DDM，Tx/Rx 单位 0.1 µW，temp 1/256 ℃，bias 2 µA，V 0.1 mV。
- `ponstat`：驱动另一条 ADC 路径，仅供粗看。
- `sendcmd 1 DB p OPTICAL`：只有告警门限和计数器（当前全 0），没有实时值。

---

## 7. 备份与回滚

产物目录 `onu_backup/`（**已加入 `.gitignore`，不要提交**）：

- 13 个 mtd 镜像 + `cspd.bin`，合计约 338 MiB
- `SHA256SUMS.txt`、`BACKUP-README.md`、`DEVICE-PARAMS.md`（TagParam 整理版 + 恢复命令）、
  `tagparam_raw_dump.txt`
- `pre_region_change_snapshot.txt`（改区前 9 张表快照）

> `DEVICE-PARAMS.md` 和 `tagparam_raw_dump.txt` 里是**明文 LOID / SN / MAC**，
> 属于最敏感的文件，永远不要进入版本库。

**回滚要点**

- 恢复用 U 盘/TFTP + `mtd write`，注意分区名对应关系，写前先 `cat /proc/mtd` 核对。
- [`tools/verify_backup.py`](tools/verify_backup.py) 可离线校验镜像完整性，恢复前先跑一遍。
- 已知不可逆点：`sdefconf` 恢复出厂后，原厂个性化配置（如旧区域码相关模板）只能靠备份还原。

---

## 8. 下次换猫 / 换回原猫

**换新猫（同线路）**：抄第 1 节参数 → 开 Telnet → 改区 205 → 写 LOID → 屏蔽 ITMS/TR069 → 禁用语音 WAN → 插纤。

**换回电信原猫 HG5143F**：

- 那台是 SDN 版 IPoE，**不是 PPPoE**，插上会自动走 TR-069 注册，
  需要重新让 ITMS 接管（本手册的屏蔽操作对它是反过来的）。
- 原猫的 VLAN 是 0（上网不打标签）、IPTV 85 / 51、管理 46。
- 原猫侧的全部研究（提权、网络 dump、参数清单）见 [../hg5143f/](../hg5143f/)。

---

## 9. 脱敏说明

本手册发布版做了以下替换，规则与理由见 [../docs/anonymization.md](../docs/anonymization.md)：

| 类别 | 处理 |
|---|---|
| LOID | → `XXXXXXXXXX`（仅保留「10 位数字」这一格式特征） |
| Telnet 密码 | → `XXXXXXXXXXXX`（仅保留「12 位」） |
| 设备 SN / PON MAC | 不出现 |
| WiFi SSID / PSK | 不出现 |
| telecomadmin 超密 | **保留** `telecomadmin` / `nE7jA%5m`（区域内统一，属厂商侧缺陷） |
| 区域码 | **保留** 205（上海）/ 206（重庆）（固件内置明文映射表） |

---

## 10. 参考资料

- [`qiudz/zte-f7015tv3-telnet-solidify`](https://github.com/qiudz/zte-f7015tv3-telnet-solidify) —— Telnet 固化脚本（本机用这个）
- [`hack-gpon/hack-gpon.github.io`](https://github.com/hack-gpon/hack-gpon.github.io) —— GPON/ONU 总 wiki，改区与刷机流程
- [`douniwan5788/zte_modem_tools`](https://github.com/douniwan5788/zte_modem_tools) —— 开 Telnet、权限门控（issue #20 提到直接改 `flag_type` 保留配置改区）
- [`edisionnano/F8648P`](https://github.com/edisionnano/F8648P) —— `flag_type` + 命令白名单机制剖析
- [`dreamzone-cc/zudz`](https://github.com/dreamzone-cc/zudz) —— 中兴改区/解密/GPON 身份工具集，`sdefconf` 前自动全备份
- [`rishavnandi/zte_f670l_unlock`](https://github.com/rishavnandi/zte_f670l_unlock) `GUIDE.md` —— 明确 `sdefconf` 会清空全部设置
- [`wyb-cq/ZaJi`](https://github.com/wyb-cq/ZaJi) issue #11 —— ITMS 注册劫持（`PDCTUSERINFO` 四字段来源）
- littlecxm.me —— 上海电信换 F7015TV3 实战（注意其 VLAN 1 说法与本地实测不符）

---

*设备：ZXHN F7015TV3 / V4.3.0P1T1 / 上海电信 10G-EPON*
