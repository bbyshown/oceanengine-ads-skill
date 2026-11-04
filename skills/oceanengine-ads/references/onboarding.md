# 接入与交付边界

## 管理员准备

需要兼容管理网关v8协议的HTTPS服务：`/manage/v1/jobs`提交任务，`/manage/v1/job`查询任务。管理网关应完成OAuth与Token自动刷新，并在服务端核验账户、项目、广告、游戏、身份和目的地归属。新建需有游戏事件资产及可用优化目标、已授权抖音号、产品信息、可用落地页及点击监测。

协议使用JSON POST与HMAC-SHA256：待签名字符串依次为`POST`、路径、Unix秒时间、32位随机nonce、请求体SHA256，以换行分隔。请求头为`X-Manage-Time`、`X-Manage-Nonce`、`X-Manage-Signature`，密钥为64个十六进制字符。客户端不直接持有开放平台app_secret或OAuth Token。

当前客户端适配操作名与请求格式，不能替代服务端部署。为同事下发凭证时应使用服务端真实的用户/账户权限机制；如果网关只有单一管理密钥，则尚不具备同事级权限隔离。客户端的`read_only`仅防止误操作，不能成为保密或授权边界。

## 使用者配置

运行`setup.py configure --help`查看参数。在本机终端隐藏输入管理密钥，或指定管理员提供的本地`--key-file`；不要把密钥粘到聊天、截图、命令行值或Git仓库。

`--account alias=ID`可以重复，`--default-account`必须指向其中一个别名。所有请求都会携带明确的账户ID，包括默认账户。不同账户中的相同项目名不会被合并。

`--access read_only`为默认值。只有具备实际操作授权的人员才配置`--access operator`。已有配置不会被隐式覆盖，确认用途后才使用`--overwrite`。

可用环境变量：

| 变量 | 用途 |
|---|---|
| `OCEANENGINE_MANAGEMENT_CONFIG` | 本机连接JSON文件路径 |
| `OCEANENGINE_ADS_HOME` | 该业务工作区的私有状态目录；默认当前目录`.oceanengine-ads/` |

示例结构见[connection.example.json](connection.example.json)。其中网关、ID和密钥占位符必须由管理员的实际本地配置替换，不能直接用示例发投放请求。

## 验证

1. `setup.py doctor`验证HTTPS签名、所选账户、版本及可用操作，输出不含密钥。
2. `ads.py --account main status`核对账户和项目，不改变投放。
3. `ads.py --account main --dry-run --run-id preview-001 budget V02 300`生成计划，无预算写入。
4. 用户下达具体操作后才执行写命令，并等待平台回读；`uncertain`等状态保留原任务排查。

脚本要求Python3.9+及可解析IANA时区的系统；缺少`Asia/Shanghai`时区数据的系统需安装tzdata。所有测试使用离线假客户端，不需要生产密钥。
