# Oceanengine Ads Skill

供同事安装复用的巨量引擎小游戏投放技能，含实际可运行的Python客户端、报表与只读监控。Python 3.9+，运行代码仅依赖标准库。

功能覆盖查询、多账户选择、新建项目及广告、批量阶梯ROI创建、素材上传、文案修改、预算/出价/日期/时段调整、启停、切换、删除、审计与中断恢复。监控只提醒，不自动关停。

## 安装

仓库默认私有，同事先取得仓库访问权限：

```sh
git clone https://github.com/bbyshown/oceanengine-ads-skill.git
mkdir -p ~/.codex/skills
ln -s "$(pwd)/oceanengine-ads-skill/skills/oceanengine-ads" ~/.codex/skills/oceanengine-ads
```

若安装目标已有同名技能，先检查，避免覆盖。让Codex重新加载技能后，可直接说：

> 使用 $oceanengine-ads 查看main账户V02昨天的数据。

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

## 文档与验证

- [技能入口](skills/oceanengine-ads/SKILL.md)
- [接入说明](skills/oceanengine-ads/references/onboarding.md)
- [命令和创建参数](skills/oceanengine-ads/references/commands.md)
- [分析与只读监控](skills/oceanengine-ads/references/monitoring.md)

离线测试，不调用生产API：

```sh
PYTHONPATH=skills/oceanengine-ads/scripts python3 -m unittest discover -s tests -v
```

仓库不包含生产密钥、OAuth Token、真实账户/广告/游戏ID、服务器地址、素材、监控历史或回执；示例中的ID与网关均为虚构配置。
