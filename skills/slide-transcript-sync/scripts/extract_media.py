#!/usr/bin/env python3
"""Optional local extraction. Does not install packages or download media."""
import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    pdf = sub.add_parser("pdf")
    pdf.add_argument("--input", required=True)
    pdf.add_argument("--output", required=True)
    pdf.add_argument("--width", type=int, default=1920)
    video = sub.add_parser("video")
    video.add_argument("--input", required=True)
    video.add_argument("--times", required=True)
    video.add_argument("--output", required=True)
    video.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    source, target = Path(args.input).resolve(), Path(args.output).resolve()
    if not source.is_file():
        parser.error("Input file not found")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        parser.error("Use an empty output directory")
    if args.mode == "pdf":
        try:
            import fitz
        except ImportError:
            parser.error("PyMuPDF is not available. Use an existing PDF renderer or install it separately.")
        if args.width < 100:
            parser.error("--width must be at least 100")
        target.mkdir(parents=True, exist_ok=True)
        records = []
        with fitz.open(source) as doc:
            for i, page in enumerate(doc):
                scale = args.width / page.rect.width
                image = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                name = f"page-{i + 1:03d}.png"
                image.save(str(target / name))
                records.append({"sourcePage": i + 1, "image": name, "text": page.get_text(), "width": image.width, "height": image.height})
    else:
        ffmpeg = shutil.which(args.ffmpeg)
        if not ffmpeg:
            parser.error("FFmpeg not found; supply --ffmpeg PATH or use an existing extraction tool")
        times = json.loads(Path(args.times).read_text(encoding="utf-8-sig"))
        if not isinstance(times, list) or not times or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in times):
            parser.error("times.json must be a nonempty array of finite nonnegative seconds")
        target.mkdir(parents=True, exist_ok=True)
        records = []
        for i, t in enumerate(times):
            name = f"frame-{i + 1:03d}.jpg"
            subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-ss", str(t), "-i", str(source), "-frames:v", "1", "-q:v", "2", str(target / name)], check=True)
            if not (target / name).is_file() or not (target / name).stat().st_size:
                parser.error(f"No frame at {t}s; check video duration")
            records.append({"frameTime": t, "image": name})
    (target / "images.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Extracted {len(records)} images to {target}")


if __name__ == "__main__":
    main()
