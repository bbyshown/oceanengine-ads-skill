# 微信小游戏智投

插件 1.2.0 和支持 `smart_delivery_support_version=1` 的网关配套使用。先 `status` 核对能力。这里的智投是小游戏跑量平台 `SMART_DELIVERY_PLATFORM_EDITION_MINI_GAME_PROMOTION`，不以自动版位判断，不将普通单元原地转换为智投。

## 目标与清单

| 模式 | 目标 | `--smart-goal` |
|---|---|---|
| IAA | 首日变现 ROI | SMART_DELIVERY_GOAL_FIRST_DAY_MONETIZATION |
| IAA | 7日变现 ROI | SMART_DELIVERY_GOAL_SEVEN_DAY_MONETIZATION |
| IAP | 首日付费 ROI | SMART_DELIVERY_GOAL_MINI_GAME_FIRST_DAY_PURCHASE_ROI |
| IAP | 7日付费 ROI | SMART_DELIVERY_GOAL_SEVEN_DAY_PURCHASE |

复用 `scripts/prepare_iap_batch.py` 的完整素材、品牌、游戏、预算等参数，追加上表 `--smart-goal`，即可离线生成1单元1创意的智投批次。脚本名保留兼容；不传此选项仍生成原普通IAP清单。预算和注册基础出价用元，ROI用比值；选项决定IAA/IAP和周期。必须提供对应账户、同游戏、已接入且注册优化/深度ROI目标匹配的单个conversion ID，网关创建前实时复核。

智投生成器目前采用自动版位，不接受 `--site`；自动版位可能要求视频号身份，不能套用普通单元排除视频号已验收的结论。用户需要手动版位时先核对平台智投资格和规格，不擅自开视频号或重建单元。

生成的JSON可按接入文档 `--dry-run batch-create --manifest 清单` 检查，再以稳定run-id提交。原始单元JSON也可用 `--dry-run new-smart --mode IAA|IAP --args-file 文件`；必须显式包含平台和scene，不会回退普通投放。动态创意仍用 `adgroup_from` 引用已核验父单元。所有创建固定暂停，超时或核验不一致不重建。

## 查询与调整

使用明确档案和账户执行 `inventory --delivery smart`，可选 `standard` 或 `all`。返回 `delivery_type` 和原平台/scene，保持游戏白名单及父子校验。`roi ID 值` 修改既有scene的ROI，`bid ID 元` 修改scene中的register_cost；均保留原goal、转化及另一个出价字段，不用普通深度出价字段覆盖智投。预算、排期、启停、创意和报表沿用既有入口与业务授权要求。未知智投平台的出价调整停止，不猜测映射。

网关回读须包含请求的平台与完整scene，平台忽略智投字段会报mismatch；uncertain/mismatch不能称为创建成功。当前完成离线测试及真实平台结构只读验证；智投真实暂停创建、调价和收入回传尚未验收。无需为技能升级创建广告。

## 官方依据

- [腾讯官方Go SDK SmartDeliverySceneSpec](https://github.com/TencentAd/marketing-api-go-sdk/blob/master/docs/v3/SmartDeliverySceneSpec.md)
- [小游戏跑量目标参数](https://github.com/TencentAd/marketing-api-go-sdk/blob/master/docs/v3/SmartDeliveryGoalMiniGamePromotionSpec.md)
- [腾讯v3枚举](https://developers.e.qq.com/v3.0/docs/enums)
- [腾讯快速API场景](https://developers.e.qq.com/v3.0/pages/quick_api_mcp)

官方快速API区分普通小游戏与智投场景；当前入口复用既有v3营销单元接口及真实平台字段，不调用默认可能开启投放的快速创建接口。平台文档和SDK更新可能不同步，字段支持以目标账户实际返回和严格回执为准。

## 排错：不要猜操作名

`new-smart` 是客户端命令，网关实际操作仍为 **`tencent_new_adgroup`**，payload显式带上述平台和scene。不存在 `smart_delivery`、`new_smart_delivery`、`smart_create` 或单独的AIM+项目层op。不要用猜测的op探测功能，也不要依据未知op的账户错误推断腾讯智投未实现。以签名status的operations、smart_delivery_support_version和客户端dry-run的实际映射核对。

当前 `live_account_verification` 是固定返回pending的历史提示，不是可配置的权限开关，也不阻断创建；不能要求管理员将其改为完成。账户真实可见性以inventory/conversions等成功回执核验。实际写入需要本机operator、所选profile的write_enabled=true、账户/游戏范围及该账户自己的有效操作人凭据；这些条件与智投字段支持是不同检查项。未经具体业务授权不要为排错开启写入。
