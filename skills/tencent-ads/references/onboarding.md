# 同事接入与升级

## 1. 更新实际使用的技能

Codex 插件安装方式：

```sh
codex plugin marketplace upgrade bbyshown-ads
codex plugin add game-ads@bbyshown-ads
codex plugin list --marketplace bbyshown-ads --json
```

尚未添加目录时，先运行 `codex plugin marketplace add bbyshown/oceanengine-ads-skill --ref main`。本次发布版本为 **1.1.1**；以 list 返回的版本、installed、enabled 为准。更新后新开聊天或重新加载技能，确认调用的是新缓存目录中的脚本。只 `git pull` 不会自动更新另一个已安装的插件副本。

独立克隆安装：在仓库运行 `git pull --ff-only`，将 `skills/tencent-ads` 整体更新到实际技能目录，保留 scripts/references。不要覆盖本机连接配置和业务工作区回执。巨量与腾讯使用不同的连接配置、状态目录和账户参数。

## 2. 连接团队网关

从管理员处取得网关地址、管理密钥、明确的第三方 profile、账户ID和游戏wxAppID。不要从公开仓库或其他同事的聊天中猜测这些值。安装技能本身不授予账户权限；使用现有团队档案时也不需要重复 OAuth。

```sh
T="/实际安装路径/tencent-ads"
python3 "$T/scripts/tencent_ads.py" configure --base-url https://ads-gateway.example.com
python3 "$T/scripts/tencent_ads.py" --profile customer-b status
python3 "$T/scripts/tencent_ads.py" --profile customer-b --account 123 inventory
```

密钥只在隐藏提示或本地 `--key-file` 中输入，不放入命令行值/聊天。首次配置默认 read_only；只有管理员授予本次操作权限后，才切到 operator（已有配置显式重配时需 `--overwrite`）。服务端 write_enabled 仍须由网关所有者控制。一个共享管理密钥不构成同事级隔离。

### 已有巨量配置，腾讯提示 connection missing

如果管理员确认巨量与腾讯使用的是**同一个团队网关和管理密钥**，可显式复用本机已有连接，不需要在聊天传密钥：

```sh
python3 "$T/scripts/tencent_ads.py" configure \
  --from-oceanengine-config "$HOME/.config/oceanengine-ads/connection.json"
python3 "$T/scripts/tencent_ads.py" --profile customer-b status
python3 "$T/scripts/tencent_ads.py" --profile customer-b --account 123 inventory
```

替换实际profile和账户ID；源配置在其他路径时使用实际路径。导入只复制base_url/key，默认read_only，不继承源operator权限、巨量账户别名、游戏或OAuth档案。源文件保持原样，目标0600；已有腾讯配置需先检查，明确重配时才用 `--overwrite`。若两平台网关或管理密钥不同，仍按原方式独立configure。

`Tencent connection missing` 只说明本机找不到连接文件，不能据此断言服务器未接腾讯、要求重新申请开发者权限或重复OAuth。服务器是否已授权应在连接成功后用**显式第三方profile**的status和真实只读账户接口判断。

接入检查：

- `authorized=true`：应用 OAuth 已保存；仍需实际账户接口成功。
- `managed_account_ids` 包含目标：账户已经登记到该档案；不得退回默认私有档案。
- `operator_credentials[账户].valid=true`：操作人实名令牌可用。没有令牌时由网关所有者提供认证组件链接，用户本人完成微信确认，令牌自动保存；不用复制令牌给聊天。
- `inventory` 成功：检查实际账户/游戏、现有父子ID和暂停状态。读取失败不当作空库存。
- 使用目标账户素材ID、转化配置、品牌图，不能跨账户直接复用作者的ID。

## 3. 生成已验收结构的暂停清单

`prepare_iap_batch.py` 是离线工具，无网络请求，也不读取管理凭证。仅覆盖「微信小游戏注册＋首日付费 ROAS」IAP结构；IAA或其他优化目标走参数文件并先核对转化资产，不把此模板当成通用目标。

以下ID都是示例，必须替换。预算和注册基础出价以**元**输入，ROAS为比值。工具生成 1 单元＋1 创意，年龄18岁以上，手动版位排除视频号，生成文件不覆盖已存在清单；必须在提交前检查这些设置是否符合本次业务指令。

```sh
python3 "$T/scripts/prepare_iap_batch.py" \
  --account 123 --profile customer-b --game wx0000000000000001 \
  --conversion 456 --video 111111 --cover 222222 --brand-image 333333 \
  --brand-name 示例小游戏 --description 示例小游戏 \
  --name-prefix 同事暂停测试01 --budget 300 --roi 0.2 --registration-bid 2 \
  --out batch.json
python3 "$T/scripts/tencent_ads.py" --profile customer-b --account 123 \
  --run-id colleague-test-001 --dry-run batch-create --manifest batch.json
```

日期默认北京时间今天，可用 `--date YYYY-MM-DD`；可重复 `--site` 覆盖默认手动版位集合，工具不接受视频号。品牌图常见规格为512×512、≤400KB，仍以该账户 `creative_template/get` 的真实规格为准。自定义品牌仅名称和品牌图，小游戏跳转放在 main_jump_info；不把主跳转当成品牌页。

用户明确授权实际暂停创建后，由管理员临时开放对应账户写入，再去掉 `--dry-run`，保持相同清单和稳定 run-id。每步完成平台回读后才继续；完成后关闭服务端写开关。不要为试运行自动开启广告。

## 4. 成功与失败的判断

成功需营销单元和创意都返回真实ID、verified=true，再次 inventory 核对父子关系、双方暂停、预算/ROAS、素材和 site_set 不含视频号。暂停创建不等于审核通过、余额充足或收入回传已验收。

- 超时/uncertain：查原 job/history，并以原 run-id resume，不能换ID盲重试。
- mismatch：即使客户端报错，对象可能已经创建；先按原对象ID查回读，不重建父单元。
- 平台明确 rejected 且无对象：保留原回执、先确认库存，再用纠正后的参数安排新批次；不能修改旧回执冒充成功。
- 营销单元已成功、创意失败：后续直接指定已有 adgroup_id，只补创意。
- WechatChannelsSpec 必填：先看父单元是否包含视频号。无需视频号投放时可在新单元用手动版位排除；更新接口没有版位字段时不能声称原单元已被修改，另建替代单元前说明影响并保留原单元暂停。

更多报错与协议细节见 [接入检查](integration.md) 和 [操作参考](operations.md)。
