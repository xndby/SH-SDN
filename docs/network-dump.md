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
| 光功率 | Rx -22.68 dBm / 温度 48℃ | 正常范围 |

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

| 业务 | VLAN | MAC 偏移 | 备注 |
|---|---|---|---|
| 上网（PPPoE） | **0（不打标签）** | base **+2** | 由控制器下发，默认无标签 |
| 管理 TR-069 | **46** | base **+3** | 上海固定 46 |
| IPTV 1 | **85** | base **+4** | OVS 端口 `iptv.85` |
| IPTV 2 | **51** | base **+5** | OVS 端口 `iptv.51` |
| VoIP SIP | **46** | base **+6** | |
| IPoE | — | base **+7** | 备用 |

基础 MAC：`/var/run/base_mac` → `D8:F5:07:XX:XX:XX`

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

即 **PPPoE 账号密码由云端控制器 `cm` 运行时下发**，不落盘在光猫里。

PPPoE 分支的实际动作：

```sh
$CFG_PATH/create_vlandev.sh veip0.1 $vlanid obox
/fhrom/fhshell/pppd.sh veip0.1 $user $password $ipv6 &
```

实测本机**当前没有 pppd 进程、没有 veip0.1 接口**，说明本机上网并非走 PPPoE，
或者 WAN 完全由硬件流表接管、CPU 侧无感知。

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
- [ ] 上网 VLAN = **0（不打标签）**；如局端要求打标签，按当地实际填
- [ ] IPTV 为 **VLAN 85 / 51**，如需保留 IPTV 要配两个 VLAN
- [ ] VoIP 若使用，VLAN **46**
- [ ] MAC 若被绑定，按 `base` / `base+2` / `base+4` / `base+5` 逐项派生
- [ ] DNS 可填 `15.192.252.188` / `15.192.251.188`
- [ ] 管理 VLAN 46（只影响 TR-069 远程管理，不影响上网）

> ⚠️ 各地电信 VLAN 规划并不统一，上表是**上海**实测结果。换机前建议先用原机
> `tcpdump` 或局端工单确认本地实际 VLAN。
