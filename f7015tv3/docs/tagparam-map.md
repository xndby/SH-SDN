# F7015TV3 参数区（TagParam）索引表

> 这是换猫时**真正要改的地方**。搞清楚「哪个 ID 是什么」，比记住一堆命令重要得多。
> 表里只保留 Tag ID、名称与用途，**所有具体值已隐去**（脱敏规则见 [../../docs/anonymization.md](../../docs/anonymization.md)）。

---

## 1. 这个参数区在哪

| 项 | 说明 |
|---|---|
| 物理位置 | flash **mtd3**（`mtd3_parameter_tags.bin`，4 MB） |
| 访问方式 | `setmac show2`（全量） / `setmac 2 <ID>`（读单个） / `setmac 1 <ID> <值>`（写） |
| 规模 | `setmac show2` 输出 **56 行 / 2310 字节**，就是全部明文可见参数 |
| 加密 | 受 `INDIVKEY[1824]` 个体密钥保护，直接对镜像 `strings` **搜不到任何明文** |
| 与 cspd 库的关系 | **完全独立**。`setmac` 直接写 flash，不需要 `sendcmd 1 DB save` |

这一点是整台机器最容易搞错的地方：

```
cspd 配置库（sendcmd 1 DB）  ← 有 bSave 列，bSave=0 的字段写了不持久
        ↕ 互不同步
flash TagParam（setmac）    ← LOID / SN / MAC / SSID / PSK 真正落盘处
```

`GPONCFG.Loid` 属于前者且 `bSave=0`，所以用 `sendcmd` 写 LOID **永远无效**；
LOID 的真正归属是后者的 `PONLOID[2180]`。

---

## 2. PON 认证参数（换机迁移的核心）

| 名称 | Tag ID | 值与格式 |
|---|---|---|
| `PONLOID` | **2180** | `<LOID>` —— 10 位数字，上海电信唯一鉴权依据 |
| `PONPASSWD` | 2181 | 空（上海线路不需要） |
| `REG_ID` | 2179 | 已隐去 —— 9 位字母数字，LOID 的衍生注册记录，一般不用改 |
| `GPONSN` | 2177 | 已隐去 —— 8 位十六进制 |
| `GPONPWD` | 2178 | 未设置 |
| `EPONSN` | 2182 | 已隐去 —— 12 位十六进制（= `GPONSN` 前补 `OUI` 后段） |
| `VENDORID` | 2176 | `ZTEG` —— 中兴的厂商前缀，**公开值** |
| `PSK` | 2186 | 未设置 |
| `OUI` | 768 | `F43A7B` —— 中兴 OUI，公开值 |

> 本机跑的是 **10G-EPON**，实际生效的是 `EPONSN`；`GPONSN` 是同一块芯片的 GPON 侧标识，两者由同一串硬件序号派生。

---

## 3. 序列号类

| 名称 | Tag ID | 值与格式 |
|---|---|---|
| `SN`（组合串） | **512** | `VENDORID` + `GPONSN` 拼接，改那两项会同步改变它 |
| `NASN`（电信资产号） | 32787 | 已隐去 —— 20 位字母数字，属于运营商资产标识 |
| `NETWORK_SERIALNUM` | 32788 | 已隐去 —— 15 位数字 |
| `NETWORK_SCRAMBCODE` | 32789 | 已隐去 —— `NASN` 的尾段 |
| `ProductSn` | 2197 | 未设置 |
| `CTEI` | 32784 | 未设置 |
| `PRODUCTCLASS` | 32790 | 未设置 |

**`NASN` 是最容易被忽略的一项。** 它是电信内部资产号，局端有些流程会交叉核对；
换机时如果一切参数都对、就是注册不上，可以怀疑这里。但它属于运营商资产，
一般不要自行伪造 —— 这属于「该找装维改工单」的范围。

---

## 4. MAC 地址池（连续 8 个）

| 名称 | Tag ID | 说明 |
|---|---|---|
| `PONMAC` | 32769 | 与 `MAC1` 相同，`OUI + 3 字节`，实际值已隐去 |
| `MAC1` | 256 | 基址，实际值已隐去 |
| `MAC2` ~ `MAC8` | 257 ~ 263 | 由 `MAC1` 顺序递推（+1 ~ +7） |

改 `MAC1` 后其余 7 个通常由系统按序推导，但**稳妥做法是逐个写**：
曾经出现过只改 `MAC1`、而 `MAC2` 之后仍是旧值的情况（表现为 WiFi 客户端拿到的 MAC 与 LAN 侧不一致）。

---

## 5. WiFi 出厂预设

| 名称 | Tag ID | 说明 |
|---|---|---|
| `SSID1` | 1024 | 上海模板带来的默认 SSID，形如 `ChinaNet-XXXX`（实际值已隐去） |
| `PSKKEY1` | 1296 | 默认预共享密钥，8 位（实际值已隐去） |
| `WEPKEY1` | 1280 | 未设置（本固件用 WPA2，不用 WEP） |
| `SSID2` / `SSID9` / `SSID10` | 1025 / 1028 / 1029 | 未设置 |
| `WEPKEY2` / `9` / `10` | 1284 / 1312 / 1316 | 未设置 |
| `PSKKEY2` / `9` / `10` | 1297 / 1328 / 1329 | 未设置 |

本机用 RouterOS 拨号 + 自有 AP，光猫 WiFi 不参与组网，这几项只在「恢复出厂后想临时连一下」时有意义。

---

## 6. Web 登录账户

| 名称 | Tag ID | 说明 |
|---|---|---|
| `USERNAME` | 1537 | `useradmin` —— 普通用户，公开默认值 |
| `USERPASSWD` | 1793 | 存储值（非明文口令形态），实际值已隐去 |
| 超级管理员 | — | `telecomadmin` / `nE7jA%5m` —— 出厂超密，不在此参数区 |

---

## 7. 定制与内部参数

| 名称 | Tag ID | 说明 |
|---|---|---|
| `SOFTVER` | 36864 | 报 `V4.3.0P1N18`，与 DevInfo 的 `SoftwareVer`（`V4.3.0P1T1`）**不同**，以后者为准 |
| `WANTYPE` | 40960 | 未设置；`sdefconf` 改区时报 `TAG_ID_WAN_TYPE` 错误即与此相关 |
| `DEFWANTYPE` | 40962 | 未设置 |
| `EGPONSWEN` | **40963** | `1` —— EPON/GPON 切换使能。本机模块自带 XEPON，无需动 |
| `VERSIONMODE` | 32770 | 未设置 |
| `HLTMODE` | 2193 | 未设置 |
| `VoIPProtocolType` | 2054 | `4`（本机不用语音） |
| `CollusionVerFlag` | 2199 | `1` |
| `rreset` | 2185 | `1` —— 恢复出厂标志位 |
| `CHIPID` | 32785 | 已隐去 —— 32 位十六进制，**芯片唯一 ID，与本机硬件绑定** |
| `ChECKKEY` | 32786 | 已隐去 —— 32 位十六进制，参数区校验密钥 |
| `INDIVKEY` | 1824 | `******` —— 个体密钥，`setmac show2` 也只显示星号 |
| `BOOT_NUM` | 3072 | 未设置 |
| `KeyNorm` | 2195 | 未设置 |
| `FRAMSTART` | 32771 | 未设置 |

---

## 8. 迁移 / 恢复要点

1. **换机迁移身份，只需六项**：`PONMAC[32769]`、`MAC1[256]`、`VENDORID[2176]`、`GPONSN[2177]`、
   `SN[512]`、`PONLOID[2180]`。这六项对齐，运营商侧基本就认作同一台设备。
2. **绝不能把别的机器的 mtd3 整块刷进来**：`CHIPID`、`ChECKKEY`、`INDIVKEY` 与本机硬件绑定，
   刷错会导致参数区**无法解密**，届时连 `setmac show2` 都读不出来。
3. **mtd3 备份最完整的兜底**是 `mtd3_parameter_tags.bin`（4 MB），冷备一份放本地。
4. **读不到明文是正常现象**：从备份镜像 `strings` 找不到 LOID/SN/MAC，只能从运行态 `setmac show2` 读。
   这也意味着「拿旧备份反查改区前的 LOID」这条路走不通。
5. `setmac` 写的是 flash，掉电不丢、恢复出厂也**不一定会清**（视 `rreset` 标志而定）——
   所以换机转手前记得把自己的 LOID/SN/MAC 清掉。

---

## 9. 本文件的值去哪了

所有设备唯一值都替换成了「格式描述 + 已隐去」，保留的是：

- Tag ID（固件内置的编号，所有同型号设备一样）
- 参数名称与用途（换猫知识的主体）
- 厂商公开值：`ZTEG`、`F43A7B`、`useradmin`

真实值在本地 `onu_backup/DEVICE-PARAMS.md` 与 `tagparam_raw_dump.txt`，
两者都被 `.gitignore` 排除，永远不进入版本库。
