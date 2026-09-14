# 输入与输出

`config.json` 中的文件路径相对于配置文件。时间单位为秒。建议用独立工作目录存素材，避免把课件提交到 Skill 仓库。

```json
{
  "courseTitle": "示例课程",
  "lectureLabel": "第1讲",
  "title": "问题与方法",
  "titleEn": "Problems and Methods",
  "instructor": "示例讲者",
  "transcriptLanguage": "zh-CN",
  "transcriptLabel": "中文讲稿",
  "captionSource": "人工字幕",
  "duration": 120,
  "sourceUrl": "https://example.org/lecture",
  "sourceMode": "video",
  "captions": "captions.json",
  "chapters": [{"id": "intro", "title": "问题与方法", "firstSlide": "s01"}],
  "slides": [
    {"id": "s01", "title": "问题", "image": "frames/first.jpg", "start": 0, "frameTime": 7, "chapter": "intro", "confidence": "high", "reviewNote": "已回看开头"},
    {"id": "s02", "title": "方法", "image": "frames/second.jpg", "start": 60, "frameTime": 64, "chapter": "intro", "confidence": "medium"},
    {"id": "s03", "title": "补充画面", "image": "frames/extra.jpg", "start": null, "frameTime": 80, "chapter": "intro", "confidence": "unmatched", "reviewNote": "尚无独立讲稿对应"}
  ]
}
```

必填：`title`、`duration`、`sourceMode`、`captions`、`slides`。`sourceMode` 为 `video` 或 `pdf`；PDF 每条应提供原始 `sourcePage`，视频应提供 `frameTime`。字幕为 JSON 数组或 `{ "segments": [...] }`，每条含 `start`、`end`、`text`。时间必须有限、非负，字幕按起点非递减排列，结束不超过视频时长；重叠字幕允许存在但不会自动去重。

非空 `start` 严格递增，第一条从 0 开始。脚本按每条字幕的起点分配到画面，跨边界的 cue 保留完整，不拆句截断。输出段落实际结束时间可能越过语义边界。无匹配画面的 `start` 为 `null`，不承接字幕。讲者回看上一页时，创建新 ID 并复用图片路径。

仅在确认来源后填写可选 `videoId`（YouTube）。其他平台可填 `videoUrlTemplate`，其中用 `{seconds}` 占位；必须确认该平台真实支持该格式。两者都没有时，时间戳不生成假链接。`sourceUrl` 仅生成原始来源入口，支持 HTTP(S)。

`confidence`：`high`、`medium`、`low` 或 `unmatched`。`reviewNote` 应说明不确定处，而非给出未经核验的精确度承诺。

输出：`index.html`、`lecture-data.json`、`assets/`、`source/reader_template.html`、`rebuild.py`、`verification.json`、使用说明。JSON 保留 cue IDs 与原文，便于逐条核验；不包含输入文件绝对路径。`--zip` 在输出目录旁生成 ZIP。`--overwrite` 仅用于已知的生成目录，不清理其他文件；ZIP 只收录本次产物。

`verify --captions` 使用原字幕作外部核验基准；不传该参数时仅做产物内部一致性检查。所有字幕完整并不能证明它们分配到了语义正确的图片上。
