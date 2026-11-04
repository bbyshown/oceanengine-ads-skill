# 操作命令

将`S`设为本技能目录。以下为语法示例，运行中的账户、项目和数值应从用户当前指令确定，示例本身不构成投放授权。全局参数在子命令之前。

```sh
S="$HOME/.codex/skills/oceanengine-ads"
python3 "$S/scripts/ads.py" --help
```

| 任务 | `ads.py`之后的参数 |
|---|---|
| 库存、状态 | `--account main status` |
| 网关能力 | `--account main capabilities` |
| 账户接入只读检查 | `--account main preflight` |
| 准备游戏事件资产/事件 | `--account main --run-id req-asset-001 ensure-game-asset`；`ensure-game-events` |
| 账户日预算 | `--account main --run-id req-budget-001 account-budget 1000` |
| 项目日预算 | `--account main --run-id req-budget-002 budget V02 300` |
| UBMAX项目ROI系数 | `--account main --run-id req-roi-001 roi V02 0.35` |
| 开启项目及广告 | `--account main --run-id req-start-001 start V02` |
| 暂停项目及广告 | `--account main --run-id req-pause-001 pause V02` |
| 切换投放 | `--account main --run-id req-switch-001 switch V02 V03` |
| 删除项目和子广告 | `--account main --run-id req-delete-001 delete V03` |
| 仅保留指定项目 | `--account main --run-id req-clean-001 keep-only V02` |
| 每周投放时段 | `--account main --run-id req-hours-001 schedule V02 --mask <336位01串>` |
| 结束时间/长期 | `--account main --run-id req-date-001 dates V02 --end '2026-12-01 23:59:59'`；或`--long-term` |
| 广告标题/卖点/素材 | `--account main --run-id req-edit-001 edit-ad V02 --patch-file /绝对路径/patch.json` |
| 指定多广告中的某条 | 在`edit-ad`加`--promotion-id <实际广告ID>` |
| 上传视频/图/头像 | `--account main --run-id req-upload-001 upload video /绝对路径/video.mp4`；也支持`image`、`avatar` |
| 查询审计 | `--account main history --limit 10` |
| 恢复原操作 | `resume req-edit-001`，自动恢复原账户；显式指定错误账户会拒绝 |

视频上限50MiB、普通图片5MiB，以目标网关及平台的实际要求为准。ROI/预算范围同样受平台业务模式约束；UBMAX在项目层调整ROI，不把它当CPC出价。

## 新建与批量

```sh
python3 "$S/scripts/ads.py" --account main --run-id req-project-001 \
  new-project AI_V21_首测 --budget 300 --roi 0.4

python3 "$S/scripts/ads.py" --account main --run-id req-campaign-001 \
  new-campaign AI_V21_男性 --budget 300 --roi 0.4 --gender male \
  --video-id <已上传的视频ID> --cover-id <已上传的封面ID> \
  --product-image-id <该账户可用产品图ID>

python3 "$S/scripts/ads.py" --account main --run-id req-ad-001 \
  new-ad V02 --name AI_V02_新素材 --video-id <视频ID> --cover-id <封面ID>

python3 "$S/scripts/ads.py" --account main --run-id req-batch-001 \
  batch-create --manifest /绝对路径/videos.json --budget 300 \
  --roi-start 0.4 --roi-end 0.5 --prefix AI_新批次_
```

新建默认暂停，男性定向只传平台支持的性别字段；UBMAX场景不能盲加`audience_extend=OFF`，应回读实际限制。向运行中项目新增广告时，父项目开关保留，新广告暂停。`--title`可重复以指定文案；默认竖版，横版用`--orientation HORIZONTAL`。

批量清单1至100行：

```json
[
  {"name":"V21_首测","video_id":"uploaded-video-one","cover_id":"uploaded-cover-one"},
  {"name":"V22_首测","video_id":"uploaded-video-two","cover_id":"uploaded-cover-two","titles":["准备防线迎接下一波挑战"]}
]
```

统一系数用`--roi 0.4`替代范围；每行可显式给`budget`和`roi_goal`。整批输入先校验，再逐条创建。`creation-status <creation_id>`查看阶段记录；明确平台拒绝后修正配置，用新请求run-id调用`resume-creation <原creation_id>`，不通过换creation_id绕过不确定写入。

## 修改文案

广告标题补丁：

```json
{"promotion_materials":{"title_material_list":[{"title":"怪物来袭，你准备怎样布置防线？"},{"title":"金币有限，每次升级都要想清楚"},{"title":"换一种策略，迎接下一波挑战"}]}}
```

产品卖点补丁：

```json
{"promotion_materials":{"product_info":{"selling_points":["每次升级都要取舍","怪物来袭守到最后","搭建自己的防守线"]}}}
```

`edit-ad`自动保留完整的其他可写素材字段并移除只读字段。不要直接提交缺少原标题/视频等必填信息的材料片段。

## 报表

```sh
python3 "$S/scripts/report_ads.py" --account main --project V02 --date 2026-11-03
python3 "$S/scripts/report_ads.py" --account main --project V02 --date 2026-11-03 --hourly
```

多广告时可加`--promotion-id`。元数据按账户缓存24小时；支持的指标取自网关`report_config`。原始报表及指标定义保存在本地状态目录，首日收入/ROI与未成熟7日数据应分开解释。高级查询仍可用`ads.py report --args-file ...`；`filters`和`order_by`必须显式传入。
