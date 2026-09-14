# Slide Transcript Sync Skill

将一讲课程整理成「课件画面 × 时间戳讲稿」离线阅读网页。支持 PDF 课件或视频取帧，保留原语言全文，提供章节导航、关键词搜索、图片放大和回到视频的时间链接。

## 安装

把 `skills/slide-transcript-sync` 整个文件夹复制到你的 Agent 技能目录，例如 Codex 的 `~/.codex/skills/`。重新打开会话后调用：

```text
使用 $slide-transcript-sync，把这个课程视频和 PDF 课件做成逐页课件与讲稿对照网页。
```

也可以提供本地图片和 SRT/VTT 字幕。没有原课件时可使用视频帧，但会标明其来源。脚本负责字幕完整性与网页生成，Agent 负责理解内容、选择画面、对齐和视觉审核。

## 内容

- `skills/slide-transcript-sync/SKILL.md`：完整工作流与质量标准。
- `scripts/sync.py`：字幕转换、静态网页构建与数据检查。
- `scripts/extract_media.py`：可选的 PDF 渲染、视频取帧。
- `assets/reader_template.html`：无 CDN 依赖的阅读器。
- `references/`：输入格式和素材获取说明。
- `tests/test_sync.py`：合成素材回归测试。

网页生成与验证只需 Python 3.10+ 标准库。PDF 渲染可选安装 PyMuPDF，视频取帧可选使用 FFmpeg；本仓库不会自动安装工具。使用方法见 Skill 内的文档。

```text
python -m unittest discover -s tests -v
```

时间边界默认是语义上的近似配对，不承诺自动识别全部课件切换。数据检查不能替代人工语义审核。单纯的视频 URL 也不能保证平台字幕和视频文件可获取。

灵感来自 [az9713/cme296-slide-transcript-sync](https://github.com/az9713/cme296-slide-transcript-sync)。本仓库提供独立的通用工作流、脚本和阅读器，不包含该仓库课程数据或本次课程媒体。
