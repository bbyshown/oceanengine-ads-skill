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

预检会核验账户、游戏事件资产、审核通过的调起链接；不会写广告，也不证明平台接受真实创建。用户明确同意未来排期后立即暂停，且确认实际素材与预算后，才去掉全局 --dry-run，加全局 --run-id 和子命令 --accept-scheduled-then-pause。仅在回读 DISABLE 且关键配置一致时报告成功；不确定时核对原任务，禁止直接重建或删除原项目。

直接使用签名任务时，将六项放在 args 顶层，另加 account_id（整数）。预检 op=ubmax_pro_create_preview；正式 op=ubmax_pro_new_project，并额外提供 accept_scheduled_then_pause=true。idempotency_key 在外层任务对象，不能用 creation_id 替代。确认字段仅用于正式提交，不写进 CLI JSON。
