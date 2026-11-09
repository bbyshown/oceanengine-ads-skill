# Oceanengine Ads Skill

本仓库现包含两个独立技能：[巨量引擎 oceanengine-ads](skills/oceanengine-ads/SKILL.md)与[腾讯广告 tencent-ads](skills/tencent-ads/SKILL.md)。两个平台的账户、游戏、Token和参数分别配置，安装不会继承作者生产权限。

供同事安装复用的巨量引擎小游戏投放技能，含实际可运行的Python客户端、报表与只读监控。Python 3.9+，运行代码仅依赖标准库。

功能覆盖查询、多账户选择、新建项目及广告、批量阶梯ROI创建、素材上传、文案修改、预算/出价/日期/时段调整、启停、切换、删除、审计与中断恢复。监控只提醒，不自动关停。

## 安装

仓库已公开，同事可直接下载或克隆，无需申请仓库访问权限：

```sh
git clone https://github.com/bbyshown/oceanengine-ads-skill.git
mkdir -p ~/.codex/skills
ln -s "$(pwd)/oceanengine-ads-skill/skills/oceanengine-ads" ~/.codex/skills/oceanengine-ads
```

若安装目标已有同名技能，先检查，避免覆盖。让Codex重新加载技能后，可直接说：

> 使用 $oceanengine-ads 查看main账户V02昨天的数据。

## Codex 插件安装

使用插件入口时，添加本仓库的团队目录，再安装「小游戏广告投放」。

```sh
codex plugin marketplace add bbyshown/oceanengine-ads-skill --ref main
codex plugin add game-ads@bbyshown-ads
```

在 Codex 插件目录选择「小游戏投放工具」来源，即可找到该插件。插件包含巨量和腾讯两个 Skill，需要本机 Python 3.9+ 和团队网关配置。公共目录上架需另行提交审核，本仓库提供团队目录安装。已用独立 Skill 安装的用户仍可沿用原入口。

## 首次连接

技能依赖团队已部署、已获授权的管理网关，协议版本v8或兼容版本。服务端负责OAuth、Token刷新、账户白名单、游戏与落地页模板；本仓库是可分享的客户端技能，不附带作者的生产服务器配置或开放平台凭证。

在新业务工作区内运行，替换示例网关和账户ID：

```sh
SKILL_DIR="$HOME/.codex/skills/oceanengine-ads"
python3 "$SKILL_DIR/scripts/setup.py" configure \
  --base-url https://ads-gateway.example.com \
  --account main=1111111111111111 \
  --default-account main
python3 "$SKILL_DIR/scripts/setup.py" doctor
```

密钥在本机隐藏终端提示中输入，或通过`--key-file /本地/管理员下发的密钥文件`读取，不出现在命令行值、聊天或Git中。默认本地配置为`read_only`；执行实际投放操作还需管理员配置`operator`并授予相应服务端权限。**本地模式不能代替网关的权限隔离**，不要把同一全权管理密钥当作同事之间的独立授权。

配置默认保存到`~/.config/oceanengine-ads/connection.json`，权限0600。运行回执保存到当前工作区`.oceanengine-ads/`；可分别用`OCEANENGINE_MANAGEMENT_CONFIG`和`OCEANENGINE_ADS_HOME`指定位置。

当前生产网关及OAuth服务需要由管理员维护。接入其他账户或游戏时，服务端也必须完成对应授权和模板配置；仅更改客户端账户别名不能扩大平台权限。

兼容网关支持自助账户登记后，授权同事可运行`setup.py accounts`，再用`setup.py add-account 别名=账户ID --run-id 唯一标识`添加已获平台授权、使用现有游戏模板的账户，无需修改或重启网关。需要有效管理密钥和operator配置；仅安装技能不会获得权限。详见[接入说明](skills/oceanengine-ads/references/onboarding.md#自助添加账户)。

## 文档与验证

- [技能入口](skills/oceanengine-ads/SKILL.md)
- [接入说明](skills/oceanengine-ads/references/onboarding.md)
- [命令和创建参数](skills/oceanengine-ads/references/commands.md)
- [分析与只读监控](skills/oceanengine-ads/references/monitoring.md)

离线测试，不调用生产API：

```sh
PYTHONPATH=skills/oceanengine-ads/scripts:skills/tencent-ads/scripts:gateway/tencent python3 -m unittest discover -s tests -v
```

仓库不包含生产密钥、OAuth Token、真实账户/广告/游戏ID、服务器地址、素材、监控历史或回执；示例中的ID与网关均为虚构配置。

## 腾讯广告 / 广点通

将`skills/tencent-ads`整体安装到宿主技能目录；例如Codex使用`~/.codex/skills/tencent-ads`，支持本地技能导入的其他宿主可导入该目录及其脚本资源。客户端要求Python3.9+，仅使用标准库。

腾讯技能需要兼容的管理网关v9、腾讯开发者应用权限及推广账户授权。客户端不直接持有腾讯OAuth凭证。现有账户尚未申请API权限时，可完成开发与预览，真实账户功能应标注待联调。详细见[腾讯接入与操作](skills/tencent-ads/references/operations.md)和[官方依据与检查清单](skills/tencent-ads/references/integration.md)。

目前提供营销单元/动态创意暂停创建、修改、预算出价排期、启停删除、素材、资金及日报/小时报表接口。IAA和IAP使用各自的ROAS目标；收入字段和账户可用目标须经真实联调核定。腾讯周期监控、自动关停和账户日限额尚未开放。

仓库中的[gateway/tencent](gateway/tencent/README.md)是供已有网关集成的通用附加模块，不是完整生产网关或一键自建服务。生产凭证与模板仍由各团队管理员提供。
