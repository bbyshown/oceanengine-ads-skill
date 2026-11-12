# 腾讯v3.0网关附加模块

这些通用模块用于已有签名任务网关v9：`tencent_runtime.py`负责腾讯HTTP/OAuth/Token，`tencent_management.py`负责白名单、回读和审计，`tencent_schema.py`负责参数校验，`tencent_onboarding.py`负责批量账户/游戏登记和操作人关联，`tencent_maintenance.py`负责多档案Token定时维护。

当前仓库不含作者的完整生产网关安装、OAuth密钥或业务模板。不要把这些模块直接当成独立HTTP服务运行。现有网关集成需把Tencent操作在巨量账户路由前分流，保留原HMAC鉴权与持久化幂等job，单worker串行执行，并将Failure.state保留为uncertain/mismatch，不能覆盖为done。

OAuth回调是`GET /manage/v1/tencent/oauth/callback`，以一次性state校验后交换授权码，只返回成功标志。不要在访问日志记录带授权码的查询串。状态/授权链接走受保护的任务操作，不开放凭证导出或任意Shell。

私有应用使用新版管理页直接获取Token，不要求OAuth回调。所有者通过服务器本地的`stage_private_tokens`暂存、`finish_private_token_import`在生效窗口后交换一次，按实际返回的TTL安装凭证；函数不是HTTP管理操作。新Token10分钟后生效，重置作废旧Token；不确定结果停止重试。第三方应用OAuth允许先配置空accounts，账户级操作仍要求账户/微信小游戏白名单及写入开关。详情见[接入检查](../../skills/tencent-ads/references/integration.md)。

Linux服务端配置文件为`<网关根目录>/private/tencent/config.json`，owner为运行服务的用户，权限0600，配置示例见下：

```json
{
  "client_id":"管理员申请的client_id",
  "client_secret":"仅在服务器私密配置",
  "redirect_uri":"https://ads-gateway.example.com/manage/v1/tencent/oauth/callback",
  "write_enabled":false,
  "accounts":{
    "123":{"mini_game_ids":["wx0000000000000001"]}
  }
}
```

操作人凭据保存于operators，账户通过operator_id关联；旧账户内user_token仅兼容读取，不应逐账户复制；不要把实际文件或Token提交Git。服务器按需刷新Token，未配置时Tencent状态返回configured=false，不读取或修改任何巨量凭证或广告。

长时间闲置的档案仍需要定时维护，否则超过refresh_token有效期只能重新授权。所有者把 `tencent_maintenance.py` 装到网关目录后执行 `sudo python3 tencent_maintenance.py --install`，会启用15分钟一次的 `tencent-token-refresh.timer`；该任务只枚举 `private/tencent/` 及 `profiles/*/` 下已存在的档案，到期前刷新一次，遇已存在的refresh-pending标记、或refresh_token已过期时只报告 `uncertain`/`reauthorization_required`，不重试、不打印任何凭证，也不调用广告接口。同一刷新窗口由 `runtime.ACCESS_REFRESH_LEAD_SECONDS` 统一定义，定时任务与在线请求不会各判一套。输出为脱敏JSON（每个档案的action与剩余秒数），可直接接监控。

第三方应用多客户授权：所有者在服务器本地调用`provision_profile(root, "customer-b", client_id=..., client_secret=..., redirect_uri=...)`，该函数不暴露HTTP。新配置、Token、独占锁和审计使用`private/tencent/profiles/customer-b/`，不覆盖默认私有应用。签名Tencent操作可带`profile_id`，CLI对应`--profile customer-b`；callback直接交给`runtime.callback`，它按state分流。每个新客户用独立档案，已有授权和不确定交换均禁止覆盖，账户名单须授权后另行核验配置。

## 操作人回调与网关集成

OAuth与操作人认证是两种凭证。除已有OAuth路由，还须集成 `GET /manage/v1/tencent/user/callback`：对query使用parse_qsl，拒绝重复键，然后交给 `runtime.user_callback(root, query)`。仅返回该函数的脱敏结果；异常统一返回400且不回显参数/URL。管理路由关闭访问日志，响应设置 `Cache-Control: no-store` 和 `Referrer-Policy: no-referrer`。

新操作人的认证链接可由签名operator-authorize命令生成；所有者也可在服务器本地生成：

```python
cfg = runtime.load_config(root, profile_id="customer-b")
link = runtime.operator_authorize_url(root, cfg, "team-main")
# 将link写入0600所有者回执，仅向本次授权用户提供，不写公共日志。
```

回调state绑定档案/应用/操作人、30分钟、单次使用；仅user_status=2且令牌有效时保存到operators[operator_id]的user_token/user_token_expires_at。wx_id允许但不保存。应用OAuth Token、账户白名单与write_enabled均不变。POST的user_token放在URL查询参数，JSON仅业务字段；不可在日志、异常或回执中暴露凭证。

`status.operator_credentials` 只输出是否配置、过期时间与有效性。所有者须按业务授权临时控制write_enabled；用户本人认证不会自动启用广告写入。该附加模块不含独立HTTP服务器，安装/升级需同时验证上述两条回调路由。

腾讯小游戏智投（1.2.0）：支持 IAA/IAP 首日、7日 ROI 的独立智投清单、暂停创建、库存过滤及 ROI/基础出价调整。需升级网关；真实智投写入尚待验收。详见 [智投说明](../../skills/tencent-ads/references/smart-delivery.md)。


1.3.0新增签名操作tencent_discover_accounts（只读）、tencent_register_accounts、tencent_bind_operator、tencent_operator_authorize（网关配置写）。配置写与广告写开关分离，但客户端要求operator，不绕过OAuth/实时组织/游戏检查。集成时将这些操作也在其他平台账户路由前分流；配置操作返回verified回执，认证操作返回受保护的一次性链接。安装包加入tencent_onboarding.py，缺模块不可仅更新客户端。详情见[批量接入](../../skills/tencent-ads/references/onboarding.md#批量接入与操作人复用)。
