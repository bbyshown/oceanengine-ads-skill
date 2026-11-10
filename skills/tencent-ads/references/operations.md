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

## 请求文件与创建规格

首次测试优先用[同事接入](onboarding.md#3-生成已验收结构的暂停清单)的离线 `prepare_iap_batch.py` 生成完整IAP清单，再运行实际客户端 dry-run。不要沿用仅含注册目标的早期最小样例冒充已验收模板。该工具不会查询平台，因此账户、游戏、转化、素材及规格仍需只读核验。

营销单元使用实际营销四元组、转化配置、定向、整数分预算与基础转化出价；深度 expected_roi 独立使用比值。`automatic_site_enabled=false` 配合显式 site_set 可排除视频号。PROGRAM创意使用 description/video/brand/main_jump_info，品牌图与视频封面是两个不同素材；主跳转须指向同一个微信小游戏。COMMON创意需要具体 creative_template_id，不能用程序化模板参数直接替代。

批量清单为1–100个 `{"op":"tencent_new_adgroup或tencent_new_creative","args":{...}}` 步骤，同一account_id/profile_id。创意 `args.adgroup_id` 指向现有单元；或用步骤顶层 `"adgroup_from":1` 引用较早的第1个单元创建步骤（二选一）。父单元回读通过后才创建创意。失败即停止，保留已成功的暂停对象。超时按原run-id恢复；明确拒绝的参数纠正另行留存，不修改原回执。

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

新版以“操作人”保存一次凭据：`operators[operator_id]` 持有 user_token/有效期，账户仅保存 `operator_id` 关联。同一操作人在同一第三方档案下可服务多个有组织认证关系的账户，不能要求每个广告账户重新扫码。OAuth范围、操作人组织关系、网关账户/游戏范围分别检查。

`operator-authorize --operator team-main` 经签名任务生成官方认证组件链接，回执保存在0600本地文件；用户本人完成微信确认，`user_status=2` 后回调自动保存到操作人档案。state绑定档案、应用和本地operator ID、30分钟且单次使用。wx_id兼容但不保存/回显；user_token URL解码一次后使用。令牌有效期以平台回调为准，过期后按操作人更新一次，所有关联账户共用新值。不要要求在聊天粘贴令牌。

用 `bind-operator --operator team-main --ids 123 456` 批量关联**已经登记**的账户；网关调用官方 `user_organization_authentication/get`，只有所有目标都为 AUTHENTICATION_STATUS_AUTHENTICATED 才保存。每次带共享操作人凭据的POST前再次实时核验该账户组织关系，未通过则不发送POST。主体名称相同不能代替这项检查，其他档案的令牌不能自动复用。该校验也不等于完整投放资格或广告创建验收。

BM组织账户发现使用官方organization_account_relation/get，不把不带account_id的advertiser/get用于BM全量列表。账户发现/批量登记见[批量接入](onboarding.md#批量接入与操作人复用)。这些操作不创建广告、不改预算/启停、不打开服务端write_enabled；广告写入仍需本机operator和既有业务授权。签名status新增write_enabled、operators、operator_scope_version、registration_version；operator_credentials保持按账户输出兼容，但反映关联操作人的有效性。live_account_verification改为not_checked_by_status，status本身不做平台实时核验。

旧账户内的凭据继续兼容读取，不会猜测其他账户令牌或静默回退。所有者可在实时核验后调用 `tencent_onboarding.migrate_legacy_operator`，生成0600备份、把指定旧凭据迁到操作人档案并关联显式账户，活动配置中只保存一次。迁移保留OAuth、游戏范围和写开关，并将旧账户式待认证链接标为superseded，避免迟到回调覆盖新关系。不同真实操作人分别建档；单HMAC团队连接不提供同事级身份隔离。

官方依据：[腾讯认证公告](https://docs.qq.com/doc/DSVdkdk1LQ1hOam5n) 明确开发者保存员工与key关系，平台校验操作人与账户组织关系；[官方SDK组织认证接口](https://github.com/TencentAd/marketing-api-go-sdk/blob/master/docs/v3/UserOrganizationAuthenticationApi.md) 接受一个userToken和多个accountIdList。

### 已验证的小游戏建投注意事项

- `user_token` 与 access_token/timestamp/nonce 一样放在请求 URL 的查询参数，不能只放 JSON 请求体或 Header。账户中已存令牌却仍返回11101时，先核对传输位置，不要求用户重复实名。
- 微信小游戏新客增长场景显式配置 `marketing_sub_goal=MARKETING_SUB_GOAL_MINI_GAME_NEW_CUSTOMER_GROWTH`；平台也可能要求 `targeting` 和 `bid_amount`。基础转化出价以分计，与深度 expected_roi 分别核对，不擅自覆盖用户 ROI。
- 营销单元的空 end_date 可能回读为字符串 `0`；仅这两个无结束日期的表示可等价，其他日期与预算/状态仍严格核对。创建已返回 adgroup_id 后遇 mismatch，先核对该 ID，不能重建父单元。
- `DYNAMIC_CREATIVE_TYPE_COMMON` 要求 creative_template_id；程序化组件使用 `DYNAMIC_CREATIVE_TYPE_PROGRAM`，仍须通过目标账户 `creative_template/get` 的 use_new_version=true 和实际营销四元组读取规格。品牌组件必填，常见要求512×512、≤400KB的真实品牌图。品牌跳转支持范围与广告主跳转不同，不把小游戏主跳转直接塞进品牌组件。没有合法品牌素材时保留暂停父单元，向用户取得正确图标/品牌资产后续建创意；不复用其他游戏标识。


已验收：微信小游戏可在 `automatic_site_enabled=false` 且显式 `site_set` 排除 `SITE_SET_CHANNELS` 后，用 PROGRAM 动态创意、原视频/封面、自定义品牌名称+512图及同游戏 main_jump_info 完成暂停创建，无需绑定视频号。不能把包含视频号的自动版位组合所报 WechatChannelsSpec 必填，推广为所有广告必须绑定视频号。现有 adgroups/update 不提供版位字段时，先说明需要创建替代暂停单元，保留原单元暂停；不可忽略未知字段后声称版位已改，最终必须回读 site_set、预算/ROI、父子关系及双方暂停状态。
