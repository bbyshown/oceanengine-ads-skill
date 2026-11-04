# 腾讯v3.0网关附加模块

这些通用模块用于已有签名任务网关v9：`tencent_runtime.py`负责腾讯HTTP/OAuth/Token，`tencent_management.py`负责白名单、回读和审计，`tencent_schema.py`负责参数校验。

当前仓库不含作者的完整生产网关安装、OAuth密钥或业务模板。不要把这三个模块直接当成独立HTTP服务运行。现有网关集成需把Tencent操作在巨量账户路由前分流，保留原HMAC鉴权与持久化幂等job，单worker串行执行，并将Failure.state保留为uncertain/mismatch，不能覆盖为done。

OAuth回调是`GET /manage/v1/tencent/oauth/callback`，以一次性state校验后交换授权码，只返回成功标志。不要在访问日志记录带授权码的查询串。状态/授权链接走受保护的任务操作，不开放凭证导出或任意Shell。

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

需要身份验证的账户可在该账户配置中加入user_token；不要把实际文件或Token提交Git。服务器按需刷新Token，未配置时Tencent状态返回configured=false，不读取或修改任何巨量凭证或广告。
