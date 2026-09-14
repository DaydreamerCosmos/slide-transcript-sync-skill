#!/usr/bin/env python3
"""Portable caption normalization, reader construction and integrity checks."""
from __future__ import annotations

import argparse
import bisect
import hashlib
import html
import json
import math
import re
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

SKILL = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
STAMP = r"\d{1,3}:\d{2}(?::\d{2})?(?:[.,]\d+)?"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(text):
    return " ".join(str(text).split())


def number(value, label):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0, f"Invalid {label}: {value!r}")
    return float(value)


def timestamp(value):
    parts = value.replace(",", ".").split(":")
    require(len(parts) in (2, 3), f"Invalid timestamp {value}")
    values = [float(v) for v in parts]
    require(all(math.isfinite(v) and v >= 0 for v in values)
            and all(v < 60 for v in values[1:]), f"Invalid timestamp {value}")
    total = 0
    for v in values:
        total = total * 60 + v
    return total


def validate_cues(raw, duration=None):
    require(isinstance(raw, list) and raw, "No caption cues")
    cues, previous = [], -1
    for i, item in enumerate(raw):
        require(isinstance(item, dict), f"Cue {i + 1} is not an object")
        start, end = number(item.get("start"), "cue start"), number(item.get("end"), "cue end")
        require(start >= previous and end >= start, f"Cue {i + 1}: invalid time order")
        if duration is not None:
            require(end <= duration + 0.001, f"Cue {i + 1} exceeds duration")
        require(isinstance(item.get("text"), str) and norm(item["text"]), f"Cue {i + 1}: empty text")
        cues.append({"id": i + 1, "start": start, "end": end, "text": norm(item["text"])})
        previous = start
    return cues


def parse_captions(path, duration=None):
    path = Path(path)
    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    inferred = False
    if path.suffix.lower() == ".json":
        data = json.loads(content)
        raw = data.get("segments", data.get("cues")) if isinstance(data, dict) else data
    elif "-->" in content:
        raw = []
        for block in re.split(r"\n\s*\n", content):
            if re.match(r"^(NOTE|STYLE|REGION)(?:\s|$)", block.strip()):
                continue
            match = re.search(rf"(?m)^\s*({STAMP})\s*-->\s*({STAMP})[^\n]*\n(.*)", block, re.S)
            require("-->" not in block or match, "Malformed caption timing block; repair the source instead of dropping cues")
            if match:
                body = html.unescape(re.sub(r"<[^>]*>", "", match[3]))
                if norm(body):
                    raw.append({"start": timestamp(match[1]), "end": timestamp(match[2]), "text": body})
    else:
        raw = []
        current = None
        for line in content.splitlines():
            match = re.match(rf"^\s*\[?({STAMP})\]?\s*(.*)$", line)
            if match:
                if current is not None:
                    raw.append(current)
                current = {"start": timestamp(match[1]), "text": match[2]}
            elif current is not None and line.strip():
                current["text"] += " " + line.strip()
        if current is not None:
            raw.append(current)
        require(duration is not None, "Timestamp TXT needs --duration for the last cue")
        for i, cue in enumerate(raw):
            cue["end"] = raw[i + 1]["start"] if i + 1 < len(raw) else duration
        inferred = True
    return {"segments": validate_cues(raw, duration), "timing": "end-times-inferred" if inferred else "source-times"}


def safe_url(value):
    if not value:
        return ""
    parsed = urlparse(value)
    require(parsed.scheme in ("http", "https") and parsed.netloc and not parsed.username
            and not parsed.password, "Source URLs must be HTTP(S), without embedded credentials")
    return value


def validate_slides(slides, duration):
    require(isinstance(slides, list) and slides, "No slides")
    seen, timed, last = set(), [], -1
    for slide in slides:
        sid = slide.get("id", "")
        require(isinstance(sid, str) and ID.fullmatch(sid) and sid not in seen, "Invalid or duplicate slide ID")
        seen.add(sid)
        require(isinstance(slide.get("title"), str) and slide["title"].strip(), f"{sid}: missing title")
        start = slide.get("start")
        if start is not None:
            number(start, f"{sid} start")
            require(start > last and start < duration, f"{sid}: non-increasing/out-of-range start")
            last = start
            timed.append(slide)
        if slide.get("frameTime") is not None:
            require(number(slide["frameTime"], "frameTime") <= duration, f"{sid}: frameTime exceeds duration")
        if slide.get("sourcePage") is not None:
            require(isinstance(slide["sourcePage"], int) and not isinstance(slide["sourcePage"], bool)
                    and slide["sourcePage"] > 0, f"{sid}: invalid sourcePage")
        require(slide.get("confidence", "medium") in ("high", "medium", "low", "unmatched"), f"{sid}: invalid confidence")
    require(timed and timed[0]["start"] == 0, "First timed slide must start at 0")
    return timed


def validate_chapters(chapters, slides):
    require(isinstance(chapters, list), "chapters must be an array")
    mapping, ids = {s["id"]: s for s in slides}, set()
    for chapter in chapters:
        cid = chapter.get("id", "")
        require(isinstance(cid, str) and ID.fullmatch(cid) and cid not in ids, "Invalid or duplicate chapter ID")
        require(chapter.get("firstSlide") in mapping and chapter.get("title"), "Invalid chapter target/title")
        require(mapping[chapter["firstSlide"]].get("chapter") == cid, "Chapter target must belong to that chapter")
        ids.add(cid)
    require(all(not s.get("chapter") or s["chapter"] in ids for s in slides), "Unknown chapter reference")


def inline_json(data):
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


REBUILD = '''#!/usr/bin/env python3
"""Refresh HTML after editing lecture-data.json. Run sync.py verify afterwards."""
import json
from pathlib import Path
root = Path(__file__).resolve().parent
data = json.loads((root / 'lecture-data.json').read_text(encoding='utf-8'))
payload = json.dumps(data, ensure_ascii=False)
for char in '<>&' + chr(0x2028) + chr(0x2029):
    payload = payload.replace(char, chr(92) + 'u' + format(ord(char), '04x'))
template = (root / 'source/reader_template.html').read_text(encoding='utf-8')
if template.count('__LECTURE_DATA__') != 1:
    raise ValueError('Invalid reader template')
(root / 'index.html').write_text(template.replace('__LECTURE_DATA__', payload), encoding='utf-8')
print('Rebuilt index.html; rerun external verification after data edits.')
'''


def paragraphs(cues):
    result, batch = [], []
    for cue in cues:
        if batch and (len(norm(" ".join(c["text"] for c in batch))) >= 500
                      or cue["start"] - batch[0]["start"] >= 50):
            result.append(batch)
            batch = []
        batch.append(cue)
    if batch:
        result.append(batch)
    return [{"start": b[0]["start"], "end": max(c["end"] for c in b),
             "text": " ".join(c["text"] for c in b), "cueIds": [c["id"] for c in b]} for b in result]


def build(config_path, output, zipped=False, overwrite=False):
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    config = read_json(config_path)
    require(config.get("title"), "Missing lecture title")
    duration = number(config.get("duration"), "duration")
    require(duration > 0 and config.get("sourceMode") in ("pdf", "video"), "Invalid duration/sourceMode")
    require(not output.exists() or (output.is_dir() and (overwrite or not any(output.iterdir()))), "Output is not empty; choose a new directory or --overwrite")
    caption_path = (config_path.parent / config["captions"]).resolve()
    cues = parse_captions(caption_path, duration)["segments"]
    slides = [{k: s[k] for k in ("id", "title", "start", "frameTime", "sourcePage", "chapter", "confidence", "reviewNote") if k in s} for s in config["slides"]]
    timed = validate_slides(slides, duration)
    chapters = config.get("chapters", [])
    validate_chapters(chapters, slides)
    assets = []
    for original, slide in zip(config["slides"], slides):
        source = (config_path.parent / original["image"]).resolve()
        require(source.is_file() and source.stat().st_size > 0, f"Missing/empty image for {slide['id']}")
        require(source.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"), "Use JPG, PNG or WebP images")
        target = "assets/" + slide["id"] + source.suffix.lower()
        slide.update(image=target, paragraphs=[], start=slide.get("start"), end=None)
        assets.append((source, target))
    starts, groups = [s["start"] for s in timed], [[] for _ in timed]
    for cue in cues:
        groups[bisect.bisect_right(starts, cue["start"]) - 1].append(cue)
    for i, slide in enumerate(timed):
        slide["end"] = starts[i + 1] if i + 1 < len(timed) else duration
        slide["paragraphs"] = paragraphs(groups[i])
    data = {k: config[k] for k in ("courseTitle", "lectureLabel", "title", "titleEn", "instructor", "transcriptLanguage", "transcriptLabel", "captionSource", "sourceMode", "videoId") if k in config}
    data.update(duration=duration, sourceUrl=safe_url(config.get("sourceUrl", "")),
                videoUrlTemplate=safe_url(config.get("videoUrlTemplate", "")),
                chapters=chapters, slides=slides, cues=cues, schemaVersion=1)
    require(not data.get("videoId") or re.fullmatch(r"[A-Za-z0-9_-]{11}", data["videoId"]), "Invalid YouTube video ID")
    require(not data["videoUrlTemplate"] or "{seconds}" in data["videoUrlTemplate"], "videoUrlTemplate needs {seconds}")
    template = (SKILL / "assets/reader_template.html").read_text(encoding="utf-8")
    require(template.count("__LECTURE_DATA__") == 1, "Invalid template")
    # Never overwrite source inputs, including inputs nested inside the output directory.
    protected = [config_path, caption_path] + [src for src, _ in assets]
    targets = [output / rel for rel in ["lecture-data.json", "index.html", "rebuild.py", "source/reader_template.html", "verification.json", "使用说明.txt"] + [rel for _, rel in assets]]
    for target in targets:
        require(not target.is_symlink() and not any(p.is_symlink() for p in target.parents), "Output symlink is not allowed")
        require(target.resolve() not in protected, "Output would overwrite an input file")
    output.mkdir(parents=True, exist_ok=True)
    for src, rel in assets:
        (output / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, output / rel)
    (output / "source").mkdir(exist_ok=True)
    write_json(output / "lecture-data.json", data)
    (output / "source/reader_template.html").write_text(template, encoding="utf-8")
    (output / "index.html").write_text(template.replace("__LECTURE_DATA__", inline_json(data)), encoding="utf-8")
    (output / "rebuild.py").write_text(REBUILD, encoding="utf-8")
    (output / "使用说明.txt").write_text("双击 index.html 离线阅读，保持 assets 文件夹相邻。\n修改 lecture-data.json 后运行 python rebuild.py，再用 Skill 的 sync.py verify 复查。\n时间边界为近似语义配对；外部视频播放需要联网。\n", encoding="utf-8")
    report = verify(output, caption_path)
    write_json(output / "verification.json", report)
    if zipped:
        zip_path = output.with_suffix(output.suffix + ".zip")
        require(not zip_path.exists() or overwrite, "ZIP exists; choose a new output or --overwrite")
        require(not zip_path.is_symlink() and zip_path.resolve() not in protected, "Unsafe ZIP target")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in targets:
                archive.write(path, (Path(output.name) / path.relative_to(output)).as_posix())
    return report


def verify(site, captions=None):
    site = Path(site).resolve()
    data = read_json(site / "lecture-data.json")
    duration = number(data.get("duration"), "duration")
    slides, source = data["slides"], validate_cues(data["cues"], duration)
    require([c.get("id") for c in data["cues"]] == list(range(1, len(source) + 1)), "Source cue IDs must be sequential")
    timed = validate_slides(slides, duration)
    validate_chapters(data.get("chapters", []), slides)
    starts = [s["start"] for s in timed]
    expected_ids = {s["id"]: [] for s in slides}
    for cue in source:
        expected_ids[timed[bisect.bisect_right(starts, cue["start"]) - 1]["id"]].append(cue["id"])
    assigned, texts = [], []
    for slide in slides:
        path = (site / slide["image"]).resolve()
        require(path.is_relative_to(site / "assets") and path.is_file() and path.stat().st_size > 0, "Invalid/missing image")
        ids_here = []
        if slide["start"] is None:
            require(slide.get("end") is None, "Unmatched slide has an end time")
        else:
            pos = timed.index(slide)
            require(slide.get("end") == (starts[pos + 1] if pos + 1 < len(timed) else duration), "Invalid slide end")
        for p in slide.get("paragraphs", []):
            ids = p.get("cueIds", [])
            require(ids and all(isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= len(source) for i in ids), "Invalid cue IDs")
            batch = [source[i - 1] for i in ids]
            require(norm(p["text"]) == norm(" ".join(c["text"] for c in batch)), "Paragraph text differs from source cues")
            require(p["start"] == batch[0]["start"] and p["end"] == max(c["end"] for c in batch), "Paragraph timing differs from cues")
            ids_here.extend(ids)
            texts.append(p["text"])
        require(ids_here == expected_ids[slide["id"]], f"Wrong cue assignment at {slide['id']}")
        assigned.extend(ids_here)
    require(assigned == list(range(1, len(source) + 1)), "Missing, repeated or reordered cues")
    require(norm(" ".join(texts)) == norm(" ".join(c["text"] for c in source)), "Transcript roundtrip mismatch")
    if captions:
        require(source == parse_captions(captions, duration)["segments"], "Source caption comparison failed")
    page = (site / "index.html").read_text(encoding="utf-8")
    embedded = re.search(r'<script id="lecture-data" type="application/json">(.*?)</script>', page, re.S)
    require(embedded and json.loads(embedded[1]) == data, "HTML data differs from JSON; run rebuild.py")
    return {"passed": True, "slides": len(slides), "cues": len(source),
            "paragraphs": sum(len(s.get("paragraphs", [])) for s in slides),
            "externalCaptionComparison": bool(captions),
            "dataSha256": hashlib.sha256((site / "lecture-data.json").read_bytes()).hexdigest(),
            "limitation": "Structural and caption-coverage checks only; semantic alignment and image readability require visual review."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("captions")
    c.add_argument("--input", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--duration", type=float)
    b = commands.add_parser("build")
    b.add_argument("--config", required=True)
    b.add_argument("--output", required=True)
    b.add_argument("--zip", action="store_true")
    b.add_argument("--overwrite", action="store_true")
    v = commands.add_parser("verify")
    v.add_argument("--site", required=True)
    v.add_argument("--captions")
    args = parser.parse_args()
    try:
        if args.command == "captions":
            require(Path(args.input).resolve() != Path(args.output).resolve(), "Input and output must differ")
            result = parse_captions(args.input, args.duration)
            write_json(args.output, result)
            print(f"Normalized {len(result['segments'])} cues ({result['timing']})")
        elif args.command == "build":
            print(json.dumps(build(args.config, args.output, args.zip, args.overwrite), ensure_ascii=False))
        else:
            print(json.dumps(verify(args.site, args.captions), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
