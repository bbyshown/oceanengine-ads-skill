# 智擎版创建

插件 1.3.15。先执行：

```bash
python3 ads.py ubmax-pro-schema > ubmax-pro.json
```

把示例值换为业务指定的值。文件是一个扁平 JSON 对象：

```json
{
  "name": "UBMAX PRO IAA test",
  "budget": 300,
  "roi": 0.8,
  "roi_mode": "7d",
  "videos": [{"video_id": "REPLACE_VIDEO_ID", "video_cover_id": "REPLACE_COVER_ID"}],
  "titles": ["Example shared title"]
}
```

六项必填；budget 是日预算（元），roi 是系数，roi_mode 为 7d 或 30d。标题为项目共享池（1–30 条），不与视频逐条绑定。如果手里有原标题，可以与 10 条新文案一起提交（总数不超 30）；素材列表不保证能读回原标题。不要把普通版 project/ad、creation_id 或 roi_goal 放进这个文件。

```bash
python3 ads.py --account ACCOUNT --dry-run ubmax-pro-new-project --args-file ubmax-pro.json
```

预检会核验账户、游戏事件资产、审核通过的调起链接；不会写广告，也不证明平台接受真实创建。预检默认使用 delivery_type=NORMAL、delivery_mode=PROCEDURAL、schedule_type=SCHEDULE_FROM_NOW，开始时间为北京时间当前时间，结束时间为十年后。确认实际素材、预算和立即排期后暂停的行为后，去掉全局 --dry-run，加全局 --run-id 和子命令 --accept-create-then-pause。该流程先创建再请求暂停，两次平台请求之间可能开始投放。旧 --accept-scheduled-then-pause 继续使用未来 14 天开始、15 天结束的排期。仅在回读 DISABLE 且关键配置一致时报告成功；不确定时核对原任务，禁止直接重建或删除原项目。

直接使用签名任务时，将六项放在 args 顶层，另加 account_id（整数）。预检 op=ubmax_pro_create_preview；正式 op=ubmax_pro_new_project，并额外提供 accept_create_then_pause=true。idempotency_key 在外层任务对象，不能用 creation_id 替代。确认字段仅用于正式提交，不写进 CLI JSON。

智擎视频创建提交视频及标题素材，游戏调起链接用于预检核验。速玩素材需要平台素材库给出的 app_play_uri，不能由 sslocal 调起链接替代。预检默认立即排期，旧 --accept-scheduled-then-pause 会选择未来排期。要使提交与默认预检一致，使用 --accept-create-then-pause。

智擎项目来源字段为 `project_materials.source`，由当前游戏模板的 `ad.source` 提供，预检会校验来源非空及长度。业务创建清单沿用六项参数。

小游戏调起信息通过 `project_materials.mini_program_info.app_id/url` 提交，取自当前登记游戏及其审核模板。预检和创建使用同一链接，并核对实例审核状态。


创建清单支持可选 `product_info`，传入时覆盖模板产品信息。模板缺少主图或内容不适合当前游戏时，在清单中明确填写。

```json
{
  "product_info": {
    "titles": ["我独自捉妖"],
    "image_ids": ["REPLACE_TARGET_ACCOUNT_PRODUCT_IMAGE_ID"],
    "selling_points": ["REPLACE_PRODUCT_SELLING_POINT"]
  }
}
```

该片段并入六项创建参数所在对象。产品名 1 条、1–20 字，主图 1–10 个，卖点 1–10 条、每条 6–9 字。图片 ID 需来自目标账户可用素材，尺寸及素材权限由平台校验。预检检查产品信息结构与非空字段。


落地页在创建清单中用 `landing_page` 指定审核可用的橙子建站 HTTPS 页面，写入 `project_materials.external_url_material_list`。不传时使用当前游戏配置的落地页。评论开关可传 `is_comment_disable`（ON/OFF，默认 ON）。`asset_id` 由网关核验当前账号和游戏的事件资产后填写，类型为单个整数。监测链接继承当前游戏模板的 `project.track_url_setting`。

查询来源项目详情可用 `ads.py --account ACCOUNT --full-output ubmax-pro-projects --project-id ID --with-materials`。返回项目级配置与 `project_materials` 素材页，保留平台分页信息并标记 `project_materials_paginated=true`，后续页用 `--page` 获取。必须先确认项目属于当前账号及登记游戏，才能读取素材。
