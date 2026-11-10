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

批量清单是1–100个`{"op":"tencent_new_adgroup或tencent_new_creative","args":{...}}`步骤，同一account_id，先全批校验再串行执行。创意可在 `args` 中填写已有的 `adgroup_id`，也可在步骤顶层填写 `"adgroup_from": 1`，引用同一清单内较早的第 1 个步骤（从 1 开始）。引用步骤必须是同一账户和授权档案的 `tencent_new_adgroup`，两种写法二选一。多个创意可以引用同一个营销单元。先用 `--dry-run` 检查清单。实际执行时，客户端等网关确认营销单元已暂停并完成回读后，再用真实 ID 创建创意。失败即停止，保留已成功的暂停对象；请求超时用原 `run-id` 恢复。

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


### OAuth 授权节点与令牌节点不一致

收到授权码但令牌接口返回 5014 时，先读签名 `status` 的 `authorization_diagnostic`，不能仅凭错误码断言账号角色不足。腾讯支持曾确认：授权页面与 token 请求连接到不同远程节点会导致认证码无效。

网关所有者可在对应独立档案的 0600 `config.json` 配置 `oauth_token_remote_ip`，值必须是已核实的授权页面真实公网目标 IP。浏览器代理的 198.18.* 虚拟 DNS 地址、客户端出口 IP、回调服务器 IP 均不能代替该节点；先通过浏览器连接记录核验实际远端。不要把某个部署环境的 IP 硬编码进共享 Skill。

配置后必须生成新的授权链接并重新扫码；state 会绑定当时的节点，配置改变时拒绝交换。令牌请求只在 `/oauth/token` 固定连接该 IP，仍使用所配置腾讯域名的 Host、SNI 和证书校验，禁用该请求的环境代理与重定向，不影响普通广告 API。签名 status 可核对 `oauth_token_remote_ip`。禁止关闭 TLS 验证或在多个节点重放同一授权码。新授权成功后另行核验账户、游戏和素材范围，才能接续暂停建投。


节点验证还须核对域名路由：同一公网 IP 可能只为 `developers.e.qq.com` 路由 `/oauth/token`，而对 `api.e.qq.com` 断连。网关所有者可配置 `oauth_token_host`（默认 `api.e.qq.com`，仅另允许 `developers.e.qq.com`）。这是经现场探测的可选路由，官方文档默认接口仍是 `api.e.qq.com`；不要在未核验的环境自动切换。先以假参数在目标节点验证 TLS 与 OAuth JSON 响应，再配置匹配的域名/IP 并生成新链接。state 同时绑定域名与 IP，域名改变后拒绝消费旧链接。假参数可达只证明传输链路，不证明真实授权成功；真实新 code 只交换一次，拒绝后停止，不跨域名或跨节点重试。


### 操作人认证与 user_token

OAuth Token 和操作人 `user_token` 是两种凭证。腾讯创建接口若返回 11101 缺少 `user_token`，不能推断用户不是主管理员或未加入组织；第三方应用同样需要此参数。不要重复 OAuth 或要求用户把令牌发到聊天。

网关运行包需安装 `tencent/user/callback` GET 路由到 `tencent_runtime.user_callback`（严格拒绝重复查询字段、错误响应不回显参数），并关闭管理路由的访问日志。网关所有者在已授权且登记账户的显式档案上调用 `tencent_runtime.user_authorize_url(root, cfg, account_id)`，生成腾讯官方 `https://ad.qq.com/account-center/single/user-authorize` 组件链接，包含 HTTPS redirect_uri 与一次性 state。链接有效 30 分钟；用户本人完成腾讯确认后，回调只在 user_status=2、user_token及expire_time合法时保存到该档案的选定账户。其余状态表示认证未完成，不保存令牌。

令牌只留在服务器 0600 config.json，原 OAuth 凭证、账户范围和 write_enabled 不变。签名 status 的 operator_credentials 仅显示配置/有效性及过期时间。重复/过期/错档案回调拒绝；令牌过期在写请求前停止。拿到令牌仍不等于广告创建成功，应回读库存，并依原拒绝回执处理纠正后的暂停批次。

操作人回调兼容腾讯附加的 `wx_id` 字段，仅忽略，不写入档案或回显；不要因该字段拒绝有效的 user_status=2 回调。


### 已验证的小游戏建投注意事项

- `user_token` 与 access_token/timestamp/nonce 一样放在请求 URL 的查询参数，不能只放 JSON 请求体或 Header。账户中已存令牌却仍返回11101时，先核对传输位置，不要求用户重复实名。
- 微信小游戏新客增长场景显式配置 `marketing_sub_goal=MARKETING_SUB_GOAL_MINI_GAME_NEW_CUSTOMER_GROWTH`；平台也可能要求 `targeting` 和 `bid_amount`。基础转化出价以分计，与深度 expected_roi 分别核对，不擅自覆盖用户 ROI。
- 营销单元的空 end_date 可能回读为字符串 `0`；仅这两个无结束日期的表示可等价，其他日期与预算/状态仍严格核对。创建已返回 adgroup_id 后遇 mismatch，先核对该 ID，不能重建父单元。
- `DYNAMIC_CREATIVE_TYPE_COMMON` 要求 creative_template_id；程序化组件使用 `DYNAMIC_CREATIVE_TYPE_PROGRAM`，仍须通过目标账户 `creative_template/get` 的 use_new_version=true 和实际营销四元组读取规格。品牌组件必填，常见要求512×512、≤400KB的真实品牌图。品牌跳转支持范围与广告主跳转不同，不把小游戏主跳转直接塞进品牌组件。没有合法品牌素材时保留暂停父单元，向用户取得正确图标/品牌资产后续建创意；不复用其他游戏标识。


已验收：微信小游戏可在 `automatic_site_enabled=false` 且显式 `site_set` 排除 `SITE_SET_CHANNELS` 后，用 PROGRAM 动态创意、原视频/封面、自定义品牌名称+512图及同游戏 main_jump_info 完成暂停创建，无需绑定视频号。不能把包含视频号的自动版位组合所报 WechatChannelsSpec 必填，推广为所有广告必须绑定视频号。现有 adgroups/update 不提供版位字段时，先说明需要创建替代暂停单元，保留原单元暂停；不可忽略未知字段后声称版位已改，最终必须回读 site_set、预算/ROI、父子关系及双方暂停状态。
