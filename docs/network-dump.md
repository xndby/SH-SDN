# HG5143F-V2 网络配置 Dump（换光猫 / 换光模块参考）

> ⚠️ **敏感信息已打码。** LOID 与该线路的宽带账号绑定，公开前务必保持占位符状态。

采集方式：`python onu_console.py "<命令>"`，全部为实机读取。
注入点线索来自 **[haoqi366/SDN_research](https://github.com/haoqi366/SDN_research)**，详见 README「鸣谢」。

---

## 1. 设备身份

```
sn            : D8F507-XXXXXXXXXXXXXXXXXXXX
mac_address   : D8:F5:07:XX:XX:XX
fw_version    : FHQZ.4.0.0
hw_version    : V4.0.0
model         : HG5143F-V2
chipmodel     : BCM68560
vendor        : Fiberhome
region        : SH
cpu_temperature  : 54
pon_temperature  : 48.23
wl_num        : 2
```

## 2. PON 注册参数（换猫必须一致）

```bash
ctapi pon get loid      # XXXXXXXXXX          <- 光路身份证，与宽带账号绑定
ctapi pon get gpon_sn   # 46485454XXXXXXXX    <- 前 4 字节 46485454 = ASCII "FHTT"
ctapi pon get pon_type  # 10GEPON
ctapi pon get pon_state # success
```

| 项 | 值 | 说明 |
|---|---|---|
| LOID | `XXXXXXXXXX` | 10GEPON 的注册凭据（原型为 10 位数字） |
| ONU SN | `FHTTXXXXXXXX` | 厂商前缀 `FHTT` = Fiberhome |
| PON 制式 | **10GEPON** | 不是 GPON，也不是 XG-PON |
| 光功率 | Rx **-23.01 dBm** / Tx **3.53 dBm** / 温度 48℃ | 正常范围（Rx 优于 -27 即可） |

> **换光模块要点**：新设备必须支持 **10GEPON**，并按 LOID 注册；若局端还校验 SN，
> 需把 SN 改写成 `FHTT` 开头（部分设备支持 SN 克隆）。

## 3. 网络命名空间

```bash
ip netns list
# APP  FM  MNG  NM  obox  acprobe
```

| 命名空间 | 接口 | 地址 | 用途 |
|---|---|---|---|
| `NM` | `si` | **192.168.1.1/24** | LAN、Web 管理 |
| `MNG` | `manager` | DHCP（实测 /17 公网段） | 管理 WAN / TR-069 |
| `MNG` | `utest` | 192.168.1.1/24 | 测试口 |
| `FM` | `foi` | 192.168.1.254/24 | 光纤管理面 |
| `APP` | `appi` | 192.168.1.253/24 | 应用沙箱 |
| `obox` | `SDN-out-default` | 192.168.1.1/24 | 上网 WAN 容器 |

```bash
# 在哪个命名空间里看，结果完全不同
ip netns exec MNG ip -4 addr
ip netns exec obox ip -4 addr
```

## 4. LAN（DHCP 服务）

`/etc/udhcpd.conf`：

```
interface si
lease_file /etc/udhcpd.leases
opt subnet 255.255.255.0
opt router 192.168.1.1
opt dns 192.168.1.1
opt wins 192.168.1.1
start 192.168.1.2
end 192.168.1.100
max_leases 252
option lease 86400
```

即：网段 `192.168.1.0/24`，地址池 `.2 ~ .100`，租期 24 小时。

## 5. DNS / NTP

```
# /etc/resolv.conf
nameserver 15.192.252.188
nameserver 15.192.251.188

# ctapi sys get ntpServer
15.192.251.5 15.192.252.5
```

均属中国电信上海。

## 6. VLAN 与 MAC 分配（重点）

来自 `/usr/init_scripts/create_vlandev.sh` 源码注释：

```
# veip0.1(for PPP):  vlan00  -  basemac+2
# manager:           vlan46  -  basemac+3
# iptv.xx(1):        vlan85  -  basemac+4
# iptv.xx(2):        vlan51  -  basemac+5
# sip:               vlan46  -  basemac+6
```

| 业务 | VLAN | MAC 偏移 | 实测核对 | 备注 |
|---|---|---|---|---|
| 上网（IPoE） | **0（不打标签）** | base **+2** | ✅ `WANConnection` | 见下方权威来源 |
| 管理 TR-069 | **46** | base **+3** | 上海固定 46 | |
| IPTV 1 | **85** | base **+4** | ✅ MAC = base+4 | OVS 端口 `iptv.85` |
| IPTV 2 | **51** | base **+5** | ✅ MAC = base+5 | OVS 端口 `iptv.51` |
| VoIP SIP | **46** | base **+6** | | |
| IPoE 备用 | — | base **+7** | | |

基础 MAC：`/var/run/base_mac` → `D8:F5:07:XX:XX:XX`

### VLAN 数值的权威来源（实测确认）

上面的注释是「设计意图」，**运行时真值**要去 ovsdb 的 `WANConnection` 表拿：

```bash
sed -n '4p' /usr/local/db/conf.db \
  | grep -aoE '"WANConnection":\{.{0,1200}'
```

实测结果（原文摘录，UUID 已省略）：

```json
"WANConnection":{
  "…":{"binding_port_name":"bridge0", "connection_settings":["map",[["ofport","199"],["vlan","0"]]], "enabled":1},
  "…":{"binding_port_name":"iptv.85", "connection_settings":["map",[["ofport","85"], ["vlan","85"]]],"enabled":1},
  "…":{"binding_port_name":"iptv.51", "connection_settings":["map",[["ofport","51"], ["vlan","51"]]],"enabled":1}
}
```

| 绑定端口 | ofport | VLAN |
|---|---|---|
| `bridge0`（PON 侧） | 199 | **0** |
| `iptv.85` | 85 | **85** |
| `iptv.51` | 51 | **51** |

**这就是换光猫时「上网 VLAN 填多少」的最终答案：填 0，不打标签。**
上表不是从注释推断的，是从设备配置库里读出来的运行时值。

顺带验证了 MAC 派生：`iptv.85` 的 MAC 末位 = base+4，`iptv.51` = base+5，
与 `create_vlandev.sh` 注释完全吻合。

### `vlanctl` 在这台机器上不可用（踩坑记录）

别在 `vlanctl` 上浪费时间，这台固件里它一律报错：

```
vlanctl --rule-dump-all                        → 输出为空
vlanctl --if bridge0 --show-tpid               → vlanCtl_dumpTpidTable, 797: Invalid argument
vlanctl --if eth0 --rx --tags 1 --show-table   → vlanCtl_dumpRuleTable, 596: Invalid argument
```

原因：`vlanctl` 要和 Broadcom 驱动的 ioctl 接口对口，而本机的 VLAN 由交换芯片 +
云端控制器直接管，内核侧这套接口没接上。（注意 `--rule-dump-all` 也不依赖 `--if`，
照样为空，所以不是参数问题。）

另一个坑：**数据面接口不在主命名空间**。主命名空间里只有 `si`，`eth0~eth3` /
`wl0.vif` / `iptv.*` / `bridge0` 全在 `MNG` 命名空间，所以 `vlanctl` 和 `ip link`
都得在 `ip netns exec MNG` 下跑。

还有一个坑：`ovs-ofctl dump-flows` 里只能看到 IPTV 的 `mod_vlan_vid:85`，
**上网那条看不到** —— 它纯走芯片硬件转发，压根不经过 OVS 流表。
所以「流表里没有」≠「没有 VLAN」。

### 为什么不用 `ovsdb-client`

本机 `ovsdb-client` 是精简编译版，连基础命令都不支持：

```
ovsdb-client list-dbs      → "list_dbs" is not a valid command
ovsdb-client list-tables   → 同上
ovsdb-client list-commands → unknown command
```

只能直接读 `/usr/local/db/conf.db`。它是 OVSDB JSON 文本：第 1/3/5… 行是校验头，
**第 4 行是数据段**，第 2 行是 schema（注意别把 schema 当成数据）。
用 `awk '{print NR": "length($0)}'` 一眼就能分清哪行是数据。

### VLAN 是怎么打上的

```bash
# /usr/init_scripts/create_vlandev.sh
vlanctl --if-create-name veip0 <vlan_name>
vlanctl --if veip0 --rx --tags 1 --filter-vid <vid> 0 --pop-tag --set-rxif <vlan_name> --rule-append
vlanctl --if veip0 --tx --tags 0 --filter-txif <vlan_name> --push-tag --set-vid <vid> 0 --rule-append
```

`vlanctl` 直接操作 Broadcom 的 VLAN VOPI（虚拟接口），不是 Linux 的 `8021q`。
所以 `ip link add link ... type vlan` 那套在这里无效，也看不到 `<iface>.<vid>` 设备。

### 另一条线索：`/etc/vlan`

一个直接写交换芯片寄存器的脚本：

```sh
#!/bin/sh
vid="$1"; flags="$2"
cd /proc
echo "05 62 02:" "$vid" > switch        # 0x0562 = VLAN ID 寄存器
...
```

`/proc/switch` 是 Broadcom 芯片的寄存器直通接口 —— VLAN 配置在**硬件层**完成。

## 7. WAN 是怎么建的

`/usr/init_scripts/create_WAN.sh` 头部注释直接说明了参数来源：

```sh
# Call by cm with env: $user $password $portname $vlanid $ipv6 $wan_type
```

按设计，PPPoE 账号密码本应由云端控制器 `cm` 运行时下发、不落盘在光猫里
（但下面会说明：这条线路实际没在用 PPPoE）。

PPPoE 分支的实际动作：

```sh
$CFG_PATH/create_vlandev.sh veip0.1 $vlanid obox
/fhrom/fhshell/pppd.sh veip0.1 $user $password $ipv6 &
```

**但这台机器上 PPPoE 分支根本没实现。** 三条独立证据：

1. `create_WAN.sh` 里 PPPoE 部分只有一行占位注释：

   ```sh
   #TODO add other pppoe code here
   ```

   真正写了逻辑的是 l2tp 分支（生成 pppd 选项、`restart_xl2tpd.sh`）。

2. `/etc/ppp` **目录不存在**，`/var/run/xl2tpd` 不存在，`ps` 里没有任何 pppd。
3. `WANConnection` 表里三条连接的 `binding_port_name` 是 `bridge0` / `iptv.85` / `iptv.51`，
   **没有 `veip0.1`** —— 也就是没走 PPP 虚拟接口。

所以这条线路是 **IPoE + VLAN 0 透传**，不是 PPPoE 拨号。
这也解释了一个常见误解：**「换光猫要抄宽带账号密码」在这条线路上不成立 ——
设备里压根没有这个凭据可抄。**

佐证：通过注入拿到的 shell 里 `ping 114.114.114.114` 返回 `Network is unreachable`
（缺省路由不在 CPU），而 iptables 四表全空 —— **NAT 与路由都在 BCM68560 硬件流表里做**。

## 8. SDN 控制器

```bash
ovs-vsctl show
# Controller "tcp:15.192.24.125:6633/<连接密钥已隐去>"
# fail_mode: secure
#   is_connected: true
```

```bash
# /usr/etc/dm_addr.conf
# <Region> <HA address> <MNG vlan> <NTP> <login msg>
SH   sgwauth.edatahome.com   46  15.192.251.5|15.192.252.5   c2RuMTIzNDU2
SH2  15.192.130.5            46  15.192.251.5|15.192.252.5   c2RuMTIzNDU2
AH   15.192.20.129           46  ...
SN   192.168.99.58           46  ...
CQ   10.255.254.11           46  ...
```

- 控制器：`sodgw.edatahome.com` / `tcp:15.192.24.125:6633`
- 认证：`sgwauth.edatahome.com`
- 管理 VLAN：**46**
- 登录报文 base64 `c2RuMTIzNDU2` = `sdn123456`（区域内设备共用的固定凭据）

## 9. OVS 端口结构

```
Bridge SDN-bridge   (fail_mode: secure, controller 已连)
├── eth0 eth1 eth2 eth3      LAN 物理口
├── wl0.vif wl1.vif          2.4G / 5G WiFi
├── iptv.51  iptv.85         IPTV VLAN 口
├── bridge0                  PON 侧
├── si      (internal)       192.168.1.1  LAN
├── foi     (internal)       192.168.1.254 光纤管理
├── appi    (internal)       192.168.1.253 应用
├── utest   (internal)       测试
├── testprobe / dtest        探针
└── SDN-out-default (internal) 上网容器
```

CPU 只有 80 端口可达：

```
table=1 priority=125 tcp,nw_src=192.168.1.0/24,nw_dst=192.168.1.1,tp_dst=80 → resubmit(,4)
table=1 priority=125 tcp,nw_src=192.168.1.1,nw_dst=192.168.1.0/24,tp_src=80 → resubmit(,4)
table=4 in_port=1..12 → output:100   (100 = CPU 口)
```

## 10. 换光猫时的对照清单

换成自己的光猫 / 光模块之前，逐条确认：

- [ ] 新设备支持 **10GEPON**（不是 GPON）
- [ ] 能以 **LOID `XXXXXXXXXX`** 完成注册
- [ ] 如需 SN 校验，SN 设为 `FHTTXXXXXXXX`
- [ ] 上网方式选 **IPoE / DHCP**，**不要选 PPPoE**（本线路无 PPPoE 凭据，选了拨不上）
- [ ] 上网 VLAN = **0（不打标签）** —— 从 `WANConnection` 表实测确认，不是猜的
- [ ] IPTV 为 **VLAN 85 / 51**，如需保留 IPTV 要配两个 VLAN
- [ ] VoIP 若使用，VLAN **46**
- [ ] MAC 若被绑定，按 `base` / `base+2` / `base+4` / `base+5` 逐项派生
- [ ] DNS 可填 `15.192.252.188` / `15.192.251.188`
- [ ] 管理 VLAN 46（只影响 TR-069 远程管理，不影响上网）

> ⚠️ 各地电信 VLAN 规划并不统一，上表是**上海**实测结果。换机前建议先用原机
> `tcpdump` 或局端工单确认本地实际 VLAN。
