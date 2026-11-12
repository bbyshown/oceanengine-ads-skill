# 官方依据与接入检查

核对日期：2026-11-10。腾讯v1.3旧SDK、旧版案例与当前v3.0存在差异，优先以以下官方资料和账户实际返回为准。

| 事项 | 当前依据与落地要求 |
|---|---|
| v3.0升级 | [用户提供的升级说明](https://support.e.qq.com/detail?cid=4531&pid=10276)：营销单元＋动态创意；营销唯一性校验；不提供v3.0沙箱；旧商务管家/MP账户不能直接当新ADQ权限 |
| 开发者注册 | [官方注册说明](https://developers.e.qq.com/v3.0/pages/regist_developer)：使用团队持有的登录身份注册，完善资料 |
| 请求协议 | [发起请求](https://developers.e.qq.com/v3.0/pages/send_request)：HTTPS、v3.0、全局鉴权参数在query；GET非字符串JSON序列化，POST用JSON，文件multipart |
| 授权 | [新版授权认证](https://developers.e.qq.com/v3.0/pages/authorization_and_authentication)：私有应用在应用详情页选身份后直接获取Token；第三方应用使用OAuth；Token刷新与实际有效期以平台返回为准 |
| 创建/修改 | [创建营销单元](https://developers.e.qq.com/v3.0/docs/api/adgroups/add)、[更新营销单元](https://developers.e.qq.com/v3.0/docs/api/adgroups/update)、[创建动态创意](https://developers.e.qq.com/v3.0/docs/api/dynamic_creatives/add) |
| 报表 | [日报表](https://developers.e.qq.com/v3.0/docs/api/daily_reports/get)、[小时报表](https://developers.e.qq.com/v3.0/docs/api/hourly_reports/get)：金额分，字段/归因时间/聚合必须核对，超限改用官方异步报表，本客户端不会返回截断结果 |
| 可选MCP | [腾讯官方MCP](https://developers.e.qq.com/mcp)、[快速投放场景](https://developers.e.qq.com/v3.0/pages/quick_api_mcp)：可作为另一路接入，默认开启的快速创建不能直接替代本工具的暂停创建策略 |

## 管理员接入顺序

1. 在开发者平台注册、创建适合团队用途的应用并申请账户管理、广告管理及报表相关权限。需要自行上报转化时，再申请对应的数据接入权限；不要把有广告后台等同于已有API权限。私有/第三方应用可用范围及申请要求以当前管理页面为准。
2. 确认IAA/IAP业务模式、应用类型及所选账户身份，应用凭证通过隐藏输入或本地文件安装。应用ID、广告account_id和微信wx小游戏ID用途不同，不能套用巨量ID。授权后优先从接口发现账户和资产；直客advertiser/get仍需account_id时，再请用户补充。
3. 私有应用：在应用详情页选择身份，直接获取access_token及refresh_token，不要求配置回调。Token仅展示一次，生成10分钟后生效；重置立即作废该身份在此应用上的旧Token，不能未经明确需要替用户重置。通过本地文件安全交给管理员导入，不在聊天或Git中传递。
4. 第三方应用：登记`/manage/v1/tencent/oauth/callback`完整HTTPS回调地址，再由管理员打开一次性OAuth链接。IP回调能否登记需看后台实际校验，不假设支持。生成授权/处理回调可以先配置空accounts；账户/游戏白名单不属于OAuth协议的前置要求。两种方式均在服务器保存Token，完成账户/游戏范围核验后才开放账户级查询与写入。受限写接口还需要独立的操作人user_token；通过官方认证组件和网关/user/callback自动接收。组织主管理员/已加入组织不代表请求已携带该令牌，不要求用户在聊天提交。
5. 先只读验收账户、游戏、素材、资金、转化配置和报表；核定IAA变现回收和IAP付费回收指标。完成后，管理员按团队授权范围开启服务端write_enabled及客户端operator，再按具体业务指令操作。
6. 真正投放前验收素材/游戏资质审核、微信游戏调起、真实注册/付费/变现回传与收入对账。接口可创建不代表已可投，也不代表收入归因已准确。

第三方应用的每个客户身份使用独立profile。所有者通过`provision_profile`安全写入新应用配置，随后`--profile customer-b --run-id auth-example-001 authorize`生成链接。凭证保存到`private/tencent/profiles/<profile>/`，默认身份原文件不动；新身份初始accounts为空、写入关闭。回调state绑定档案和应用，跨档案、重复回调或不确定交换均拒绝再次交换。

服务端Token使用提前刷新及独占锁，轮换结果不确定时停止再次刷新，保留排查标记。网关同时按需刷新和定时维护：所有者安装 `tencent_maintenance.py --install` 后，`tencent-token-refresh.timer` 每15分钟检查一次所有已配置档案，在access_token到期前3小时刷新一次。定时任务只处理凭证，不调用广告接口；遇到已存在的refresh-pending标记或refresh_token过期时只报告，不重试。若集群部署多套网关或未安装该任务，仍需以各自实际部署为准，不能只看客户端。

私有Token导入辅助函数在附加网关模块中，不通过HTTP导入/导出凭证：所有者用`stage_private_tokens`暂存并设置生效检查时间，再用`finish_private_token_import`做一次刷新并按返回TTL安装。不得把未知旧Token的有效期从导入时重新算满30天。刷新超时或被拒绝后先检查原导入记录，不盲目重试或要求重置。

## IAA与IAP

代码识别IAA的`GOAL_1DAY_MONETIZATION_ROAS`、`GOAL_7DAY_MONETIZATION_ROAS`与IAP的`GOAL_1DAY_PURCHASE_ROAS`、`GOAL_7DAY_PURCHASE_ROAS`等。文档中有枚举不等于每个账户/游戏都已开通该目标。ROI命令仅修改现有明确目标；不会自动把注册目标切成付费/变现目标。

当前能力边界：已实现v3.0协议、暂停创建、更新、启停、删除、预算/金额出价/明确ROI目标/时间、素材及同步报表适配。账户日限额接口、收入字段的账户模板、异步大报表、腾讯自动关停和周期监控不在当前开放能力中，不以旧接口拼接冒充已支持。真实账户验收必须在获得API权限后完成。


## 发布验收范围

| 能力 | 当前实现 | 真实验收范围 |
|---|---|---|
| 第三方OAuth | profile隔离、一次性state、按实际TTL刷新、脱敏诊断 | 独立档案授权成功并查询目标账户成功 |
| 操作人认证 | 官方组件、一次性操作人绑定回调、批量组织核验、兼容wx_id、有效期检查 | user_status=2安全保存，受限创建接口通过身份校验 |
| 暂停创建 | 单元＋PROGRAM创意、adgroup_from批量依赖、父子回读 | 微信小游戏IAP注册＋首日付费ROAS、手动排除视频号、品牌图＋既有视频/封面创建成功 |
| 素材 | 图片/视频上传、素材查询 | 真实视频、封面和512×512品牌图可见/上传成功；审核及开跑仍需另验 |
| 维护 | 库存、预算、基础出价、现有ROI、时间、启停、删除、审计/恢复 | 有离线协议验证；不能把暂停创建验收推广为每类真实变更均已验收 |
| 报表 | 日/小时同步查询与显式指标口径 | 数据权限及收入/归因口径按具体账户另验；不支持异步大报表与自动关停 |

排除视频号可完成创建，不普遍要求绑定视频号。包含视频号的版位组合及其依赖则需对应视频号身份；现有单元版位不能通过未支持字段假装更新。
