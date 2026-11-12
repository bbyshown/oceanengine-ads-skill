# 接入与交付边界

## 管理员准备

需要兼容管理网关v8协议的HTTPS服务：`/manage/v1/jobs`提交任务，`/manage/v1/job`查询任务。管理网关应完成OAuth与Token自动刷新，并在服务端核验账户、项目、广告、游戏、身份和目的地归属。新建需有游戏事件资产及可用优化目标、已授权抖音号、产品信息、可用落地页及点击监测。

协议使用JSON POST与HMAC-SHA256：待签名字符串依次为`POST`、路径、Unix秒时间、32位随机nonce、请求体SHA256，以换行分隔。请求头为`X-Manage-Time`、`X-Manage-Nonce`、`X-Manage-Signature`，密钥为64个十六进制字符。客户端不直接持有开放平台app_secret或OAuth Token。

当前客户端适配操作名与请求格式，不能替代服务端部署。为同事下发凭证时应使用服务端真实的用户/账户权限机制；如果网关只有单一管理密钥，则尚不具备同事级权限隔离。客户端的`read_only`仅防止误操作，不能成为保密或授权边界。

## 使用者配置

运行`setup.py configure --help`查看参数。在本机终端隐藏输入管理密钥，或指定管理员提供的本地`--key-file`；不要把密钥粘到聊天、截图、命令行值或Git仓库。

`--account alias=ID`可以重复，`--default-account`必须指向其中一个别名。广告业务请求携带明确的账户ID，包括默认账户；账户发现/登记为安装级签名操作，目标用`target_account_id`单独传递，首次接入时也可调用。不同账户中的相同项目名不会被合并。

`--access read_only`为默认值。只有具备实际操作授权的人员才配置`--access operator`。已有配置不会被隐式覆盖，确认用途后才使用`--overwrite`。

可用环境变量：

| 变量 | 用途 |
|---|---|
| `OCEANENGINE_MANAGEMENT_CONFIG` | 本机连接JSON文件路径 |
| `OCEANENGINE_ADS_HOME` | 该业务工作区的私有状态目录；默认当前目录`.oceanengine-ads/` |

示例结构见[connection.example.json](connection.example.json)。其中网关、ID和密钥占位符必须由管理员的实际本地配置替换，不能直接用示例发投放请求。

## 自助添加账户

兼容网关提供`discover_accounts`和`register_account`后，持有团队有效管理密钥的授权同事无需请管理员修改服务端代码。先查看平台当前授权身份下可见的账户及其登记状态，再按用户明确指定添加：

```sh
python3 "$SKILL_DIR/scripts/setup.py" accounts
python3 "$SKILL_DIR/scripts/setup.py" add-account secondary=2222222222222222 --run-id enroll-secondary-001 --dry-run
python3 "$SKILL_DIR/scripts/setup.py" add-account secondary=2222222222222222 --run-id enroll-secondary-001
python3 "$SKILL_DIR/scripts/ads.py" --account secondary status
```

`add-account`要求本地`operator`模式。预览不改登记或本地配置。执行会实时核验目标属于服务器当前授权工作台、可访问服务器配置的游戏及广告查询API，再持久保存登记；回读确认后合并本地别名，保留管理密钥、默认账户及其他别名。不会自动创建资产/项目/广告、导入既有项目管理范围、改预算或启投。新账户创建广告时仍需对应游戏资产与素材。

兼容网关可按账户绑定独立授权档案和已配置游戏：

```sh
python3 "$SKILL_DIR/scripts/setup.py" accounts --profile new-team
python3 "$SKILL_DIR/scripts/setup.py" add-account secondary=2222222222222222 \
  --profile new-team --game-app-id tt000000000000000001 --run-id enroll-secondary-001
```

替换示例游戏ID为服务器已配置且目标账户真实可用的游戏。档案只在登记时明确选择；以后业务请求仍用账户别名，服务器按已验证的绑定选Token和游戏模板。静态既有账户及其他账户的绑定不会被覆盖，同一账户不能通过重复登记自动换游戏或授权档案。客户端不能提交任意模板文件、工作台ID或跳转地址。当前兼容实现仅允许安装方配置的EBP工作台和游戏模板，其他CUSTOMER工作台不能直接套用。

### 存量项目纳管

`add-account`只授予读权限。账户里**早就存在**的项目不会自动进入管理范围，所以直接对这些项目改预算/出价/启停会报“超出管理范围”。要让它们可改，显式纳管：

```sh
python3 "$SKILL_DIR/scripts/ads.py" --account secondary --run-id claim-secondary-001 claim-projects --all
python3 "$SKILL_DIR/scripts/ads.py" --account secondary --run-id claim-secondary-002 claim-projects 123 456
python3 "$SKILL_DIR/scripts/ads.py" --account secondary --dry-run --run-id claim-secondary-003 claim-projects --all
```

纳管前实时读取账户项目并核对游戏实例：

- `--all`只纳管**本游戏**的项目，账户里其他游戏的项目自动跳过，不影响纳管。
- 点名`project_ids`时严格校验：**只要有一个属于别的游戏，整批都不纳管**，不做部分写入。
- 本来就在管理范围内的项目（自己建的、或已在登记表里的）不会被重新纳管，重复执行幂等。

纳管不创建、不开启、不改预算，也不改变已登记的账户/游戏范围。

纳管后的项目可以改，但**默认不能删**。删除或`keep-only`命中纳管项目时会直接拒绝并列出ID；确认要删时同一请求额外加`--confirm-adopted`。这条确认是替代保护：此前“存量项目不在管理范围内”本身就挡住了批量清理，纳管后必须由人明确说删。

`inventory`返回的`adopted_project_ids`即纳管来源的项目，可据此判断哪些是工具自己建的、哪些是接管来的。

#### 同事完整操作顺序

以把一个已授权账户`secondary`的存量项目接管过来为例：

```sh
# 1. 先确认账户账号和可见范围（只读）
python3 "$SKILL_DIR/scripts/setup.py" accounts
python3 "$SKILL_DIR/scripts/ads.py" --account secondary --dry-run --run-id claim-secondary-001 claim-projects --all

# 2. 正式纳管（dry-run 通过后去掉 --dry-run，run-id 保持不变）
python3 "$SKILL_DIR/scripts/ads.py" --account secondary --run-id claim-secondary-001 claim-projects --all

# 3. 回读确认：看 managed_project_ids 和 adopted_project_ids
python3 "$SKILL_DIR/scripts/ads.py" --account secondary --full-output status

# 4. 之后改预算/出价/启停按账户别名正常操作
python3 "$SKILL_DIR/scripts/ads.py" --account secondary --run-id budget-secondary-001 budget V02 500
```

`--dry-run`是全局参数，**必须写在子命令`claim-projects`之前**，写在后面会报`unrecognized arguments`。
它只打印计划、不写任何东西，`scope_changed`为false。第2步中断或超时，**用同一个run-id重跑**，不要换新ID，客户端会先查原job。

不需要纳管也不要紧：新项目直接在网关里建，自动进入管理范围，只有**接管历史项目**才需要这一步。

同一命令中断或任务仍在运行，重复使用原run-id查原job；明确拒绝/uncertain先检查回执，不能换新标识盲重试。客户端不会在未核验时把账户加入本地配置。安装级job仍要求HMAC签名，并使用已有审计与幂等机制。

签名请求格式（不是匿名注册接口）：

```json
{"op":"discover_accounts","args":{},"idempotency_key":"discover-accounts-001"}
```

```json
{"op":"register_account","args":{"target_account_id":2222222222222222,"game_app_id":"tt_gateway_configured_game"},"idempotency_key":"enroll-secondary-001"}
```

游戏ID必须使用发现接口返回的`game_app_id`。客户端不能指定新的工作台、游戏模板、服务端文件或Token。不同OAuth身份的账户必须先完成平台授权；腾讯广告的私有应用限制与多身份凭证隔离不能用此巨量接口绕过。旧网关不提供这两个操作时，先由网关维护者升级，不能只改客户端白名单。

当前单一HMAC密钥具有团队共享的管理范围，自助登记也会对同密钥使用者可见；这不是每位同事独立的账户权限。仅安装公开技能而没有密钥的人无法登记或操作。

## 新身份的隔离授权

其他工作台/授权身份先使用支持`oauth_profile_authorize/oauth_profile_status`的网关，创建独立授权档案：

```sh
python3 "$SKILL_DIR/scripts/setup.py" authorize-profile new-team --run-id oauth-new-team-001
python3 "$SKILL_DIR/scripts/setup.py" authorization-status new-team
```

创建链接要求operator。档案ID为4至48位小写字母、数字、下划线或短横线，首位字母；不要使用default/primary/legacy。客户端只接收授权链接和状态，不接收平台Token。用户用目标账户的管理身份登录平台并确认授权；回调地址仍由服务端固定，不改开放平台回调配置。

链接有效期从创建时起30分钟，state持久化且单次使用，不需要重启服务。任务未完成或提交结果不明时仍查原run-id；确认只是未使用链接已过期，可用新的run-id为同一未授权档案创建新链接。平台明确拒绝可查状态和错误码；交换结果uncertain必须先核查，不能盲目生成/交换。已有凭证的档案不能覆盖。不要沿用旧版服务启动日志中的全局授权链接接入其他身份。

创建授权档案本身只收取、隔离保存凭证，初始`management_enabled=false`；随后对明确选择的账户运行带`--profile`的登记命令，平台、游戏和读取权限核验通过后才开放该账户范围。兼容网关按绑定档案隔离刷新Token，支持业务请求时检查和原有服务端定时维护；状态返回已绑定账户及维护方式。刷新结果不确定时保留marker并阻止重复交换，不覆盖旧Token或其他档案。私有应用的主体/客户范围等平台限制仍由平台决定，隔离档案不能绕过它们。只有真实创建并回读通过后，才能报告对应账户的创建能力已验收。

## 验证

1. `setup.py doctor`验证HTTPS签名、所选账户、版本及可用操作，输出不含密钥。
2. `ads.py --account main status`核对账户和项目，不改变投放。
3. `ads.py --account main --dry-run --run-id preview-001 budget V02 300`生成计划，无预算写入。
4. 用户下达具体操作后才执行写命令，并等待平台回读；`uncertain`等状态保留原任务排查。

脚本要求Python3.9+及可解析IANA时区的系统；缺少`Asia/Shanghai`时区数据的系统需安装tzdata。所有测试使用离线假客户端，不需要生产密钥。

## 同事接入与故障定位顺序

同一团队网关的链路是：宿主能执行Python → 本地HTTPS/HMAC配置 → 平台授权档案 → 账户登记与游戏绑定 → 素材/事件/身份/落地页 → 暂停创建与回读 → 明确启投。安装公开Skill仅完成第一步。

1. 确认实际执行的是最新版技能脚本，使用同一个HTTPS网关。先配置本机connection.json，实际操作人员设operator；read_only只能读取/预览。Python环境和工作目录必须允许脚本读素材、写私有回执。
2. 同一账户已在网关登记时，先将该完整ID配置为本地别名，运行doctor和`ads.py --account 别名 status`。若读取到正确项目，说明账户级HMAC读取及登记路由已通；不需要因另一台电脑而重新OAuth。读取成功仍不替代写入模式、素材和真实创建验收。
3. `setup.py accounts`只发现默认OAuth身份可见的账户，**不是所有授权档案的账户并集，也不是已登记账户的全集**。目标不在默认发现结果中，不能断言网关没有该账户或它未获授权。已知独立档案时用`setup.py accounts --profile 档案`；其中顶层game_app_id是默认游戏，目标行的game_app_id才是该账户的绑定，不能据顶层字段断言服务器只有一种游戏。
4. 本地尚无目标别名时，按已有平台身份/游戏执行`setup.py add-account 别名=ID --profile 档案 --game-app-id tt... --run-id 稳定标识`。已经登记且绑定相同时只核验/补本地别名，不改变广告；不要用默认档案重新登记另一身份的账户。已有本地别名直接用它，避免给同ID重复起别名。
5. 业务命令使用`ads.py --account 别名 ...`，服务器按该账户绑定自动选Token和游戏。Oceanengine的`--profile`用于setup.py账户发现/登记，不是ads.py投放命令的全局选项。不要把安装级发现与账户级业务查询混为一谈。
6. 上传到目标账户或核验该账户可用的视频、封面和产品主图；本机素材路径不能照搬另一台电脑，服务端模板中的素材ID也不能默认视为跨账户通用。本次接口要求产品主图108×108；同时核验正确游戏落地页、身份、CTA、监测与事件。真实收入归因必须另验收。
7. 单条暂停创建并回读通过后再批量。批量可给`--product-image-id`作为统一主图，或逐行product_image_id覆盖。日预算是每个项目预算，批建20个各300元意味着项目日预算合计6000元，不能解释为合计300元；账户日上限另设且不等于全周期测试总额。
8. 保存原run-id/job/creation_id和服务器原始错误；uncertain不要重复建。创建成功仍为暂停，审核、余额、账户限额、排期和回传分别核验后才根据新指令开启。

`doctor`账户级返回版本8可能是兼容协议版本，不能单凭该值断言部署落后；结合实际操作列表与读取到的账户/游戏核对。遇TLS/超时先查网络及实际任务，不把读取失败当成未授权。

排查回传最小集合：宿主与操作系统、技能版本、脱敏后的base_url/实际脚本路径、目标账户/游戏、profile、doctor输出、原始报错和run-id/job_id。不要提供密钥、Secret、Token、完整connection.json或带授权码的回调URL。
