# 官方依据与接入检查

核对日期：2026-11-05。腾讯v1.3旧SDK、旧版案例与当前v3.0存在差异，优先以以下官方资料和账户实际返回为准。

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
4. 第三方应用：登记`/manage/v1/tencent/oauth/callback`完整HTTPS回调地址，再由管理员打开一次性OAuth链接。IP回调能否登记需看后台实际校验，不假设支持。生成授权/处理回调可以先配置空accounts；账户/游戏白名单不属于OAuth协议的前置要求。两种方式均在服务器保存Token，完成账户/游戏范围核验后才开放账户级查询与写入。如果受限写接口要求user_token，按官方身份验证流程私密配置。
5. 先只读验收账户、游戏、素材、资金、转化配置和报表；核定IAA变现回收和IAP付费回收指标。完成后，管理员按团队授权范围开启服务端write_enabled及客户端operator，再按具体业务指令操作。
6. 真正投放前验收素材/游戏资质审核、微信游戏调起、真实注册/付费/变现回传与收入对账。接口可创建不代表已可投，也不代表收入归因已准确。

服务端Token使用提前刷新及独占锁，轮换结果不确定时停止再次刷新，保留排查标记。当前仅在API调用时按需刷新，不宣称已部署腾讯全天Token刷新守护；若连续闲置超过refresh_token有效期，需要重新授权。

私有Token导入辅助函数在附加网关模块中，不通过HTTP导入/导出凭证：所有者用`stage_private_tokens`暂存并设置生效检查时间，再用`finish_private_token_import`做一次刷新并按返回TTL安装。不得把未知旧Token的有效期从导入时重新算满30天。刷新超时或被拒绝后先检查原导入记录，不盲目重试或要求重置。

## IAA与IAP

代码识别IAA的`GOAL_1DAY_MONETIZATION_ROAS`、`GOAL_7DAY_MONETIZATION_ROAS`与IAP的`GOAL_1DAY_PURCHASE_ROAS`、`GOAL_7DAY_PURCHASE_ROAS`等。文档中有枚举不等于每个账户/游戏都已开通该目标。ROI命令仅修改现有明确目标；不会自动把注册目标切成付费/变现目标。

当前能力边界：已实现v3.0协议、暂停创建、更新、启停、删除、预算/金额出价/明确ROI目标/时间、素材及同步报表适配。账户日限额接口、收入字段的账户模板、异步大报表、腾讯自动关停和周期监控不在当前开放能力中，不以旧接口拼接冒充已支持。真实账户验收必须在获得API权限后完成。
