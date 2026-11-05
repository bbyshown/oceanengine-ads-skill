# 接入与操作

要求Python3.9+与兼容的管理网关v9。此技能可供支持本地Python执行的宿主加载；不依赖Codex专有工具。导入整个`tencent-ads`目录，保留scripts和references。当前业务工作区回执写入`.tencent-ads/`，也可通过`TENCENT_ADS_HOME`指定。

首次在本机终端配置（示例网关不可直接使用）：

```sh
T="/实际安装目录/tencent-ads"
python3 "$T/scripts/tencent_ads.py" configure --base-url https://ads-gateway.example.com
python3 "$T/scripts/tencent_ads.py" status
```

HMAC管理密钥通过隐藏提示输入，或`--key-file /本地文件`读取；默认read_only。配置在`~/.config/tencent-ads/connection.json`、权限0600，环境变量`TENCENT_MANAGEMENT_CONFIG`可覆盖路径。具备操作授权的人员可配置`--access operator`；服务端也须启用write_enabled。不要将全权HMAC密钥视为多用户权限隔离。

## 固定命令

全局参数在子命令前；示例ID是虚构值。

| 用途 | `tencent_ads.py`之后的参数 |
|---|---|
| 服务/配置状态 | `status` |
| 第三方独立身份授权状态 | `--profile customer-b status` |
| 第三方独立身份授权链接 | `--profile customer-b --run-id auth-example-001 authorize` |
| 账户允许游戏的库存 | `--account 123 inventory` |
| 账户资金 | `--account 123 funds` |
| 营销单元日预算，元 | `--account 123 --run-id budget-example-001 budget 456 500` |
| 金额出价，元 | `--account 123 --run-id bid-example-001 bid 456 2.50` |
| 现有ROI目标的比值 | `--account 123 --run-id roi-example-001 roi 456 0.40` |
| 启用/暂停营销单元 | `--account 123 --run-id pause-example-001 pause adgroup 456`；`start adgroup 456` |
| 启用/暂停动态创意 | `--account 123 --run-id creative-example-001 pause creative 789`；`start creative 789` |
| 修改时段 | `--account 123 --run-id hours-example-001 schedule 456 --mask <336位01串>` |
| 修改结束日期 | `--account 123 --run-id dates-example-001 dates 456 --end 2026-12-31`；长期用`--end ''` |
| 新建暂停营销单元 | `--account 123 --run-id group-example-001 new-adgroup --mode IAA --args-file /绝对路径/group.json`；IAP用`--mode IAP` |
| 新建暂停动态创意 | `--account 123 --run-id create-example-001 new-creative --adgroup-id 456 --args-file /绝对路径/creative.json` |
| 修改营销单元 | `--account 123 --run-id edit-example-001 update-adgroup 456 --patch-file /绝对路径/patch.json` |
| 修改创意 | `--account 123 --run-id edit-example-002 update-creative 789 --patch-file /绝对路径/patch.json` |
| 删除暂停创意 | `--account 123 --run-id delete-example-001 delete creative 789` |
| 删除暂停且无创意的单元 | `--account 123 --run-id delete-example-002 delete adgroup 456` |
| 上传素材 | `--account 123 --run-id upload-example-001 upload video /绝对路径/video.mp4`；图片用image |
| 素材/转化配置查询 | `--account 123 materials video --query-file /绝对路径/query.json`；`conversions --query-file ...` |
| 报表 | `--account 123 report --query-file /绝对路径/report.json`；小时报表追加`--hourly` |
| 批量暂停创建 | `--account 123 --run-id batch-example-001 batch-create --manifest /绝对路径/batch.json` |
| 操作审计 | `--account 123 history` |
| 超时恢复 | `resume budget-example-001`，沿用原回执，不换run-id |

多授权身份的所有命令都在子命令前指定`--profile customer-b`；不传时仍使用原默认身份，不会自动合并不同身份的账户。新档案由服务器所有者预配置，生成链接需客户端operator；授权成功本身不开放广告写入。已有授权不能被新的链接覆盖，未过期链接从原run-id回执获取。交换uncertain时保留原档案排查，不重新提交授权码。

写命令加`--dry-run`仅预览。客户端返回job queued/running表示尚未完成，不代表平台参数已生效。只有平台回读verified后才报告变更成功。预算修改不改变开关，启用某一层级也不会自动开启另一层级。

## 请求文件

营销单元示例为注册目标，非已验收的IAA/IAP回收优化模板。具体优化目标、ROI深度配置、版位和资产需通过账户实际权限核对：

```json
{
  "adgroup_name":"微信小游戏_首测",
  "marketing_goal":"MARKETING_GOAL_USER_GROWTH",
  "marketing_carrier_type":"MARKETING_CARRIER_TYPE_WECHAT_MINI_GAME",
  "marketing_carrier_detail":{"marketing_carrier_id":"wx0000000000000001"},
  "marketing_asset_outer_spec":{"marketing_target_type":"MARKETING_TARGET_TYPE_WECHAT_MINI_GAME","marketing_asset_outer_id":"wx0000000000000001"},
  "begin_date":"2026-11-05",
  "end_date":"",
  "time_series":"替换为336个1或明确时段位图",
  "daily_budget":50000,
  "bid_mode":"BID_MODE_OCPM",
  "bid_amount":200,
  "optimization_goal":"OPTIMIZATIONGOAL_APP_REGISTER",
  "automatic_site_enabled":true,
  "configured_status":"AD_STATUS_SUSPEND"
}
```

JSON中的50000分是500元；bid_amount=200是2元。示例时间/出价不构成投放建议。新建无论请求为何开关，服务器都强制暂停。不能用修改名字绕过营销唯一性校验。

创意JSON使用`dynamic_creative_name`和`creative_components`：文本组件形如`description:[{"value":{"content":"实际文案"}}]`；视频组件形如`video:[{"value":{"video_id":"已上传ID","cover_id":"已上传封面ID"}}]`。品牌、图片、行动按钮、creative_template_id等以账户支持的创意规格为准，不能承诺最小样例在所有版位均可投。主跳转默认补同一微信小游戏，跨游戏或H5目的地会被拦截。小游戏监控参数按腾讯文档使用问号开头；巨量的点击宏不能直接复用。

批量清单是1–100个`{"op":"tencent_new_adgroup或tencent_new_creative","args":{...}}`步骤，同一account_id，先全批校验再串行执行。创意必须引用已有的明确adgroup_id；当前不支持用前一步返回值占位，也没有自动跨步骤回滚。某一步失败立即停止，保留已成功的暂停对象。

## 报表

```json
{
  "level":"REPORT_LEVEL_ADGROUP",
  "date_range":{"start_date":"2026-11-04","end_date":"2026-11-04"},
  "group_by":["date","adgroup_id"],
  "fields":["date","adgroup_id","view_count"],
  "filtering":[{"field":"adgroup_id","operator":"EQUALS","values":["456"]}],
  "time_line":"REQUEST_TIME"
}
```

小时报表聚合字段改为hour，起止日期相同。以上是结构示例，具体消耗、点击、IAA收入、IAP付费金额及回收率字段应从当前指标说明和真实账户返回核定后加入，不用旧版impression/click字段名猜测。原始金额为分；缺失数据不补零。

素材上传网关上限图片10MiB、视频50MiB；腾讯文档的视频上限100MiB不等于当前72MiB JSON网关能承载100MiB文件。上传返回ID不代表审核或处理完成，开跑前需核实。
