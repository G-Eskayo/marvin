#!/usr/bin/env python3
"""Union content bounding box across a sample of frames, using a brightness
threshold to separate drawn content (nodes/lines/labels) from the near-black
radial-gradient background (max channel <= ~26)."""
import sys
import numpy as np
from PIL import Image
from pathlib import Path

def content_bbox(frame_dir, sample_every=10, threshold=42, edge_exclude=0):
    frame_dir = Path(frame_dir)
    files = sorted(frame_dir.glob("*.png"))[::sample_every]
    min_x, min_y, max_x, max_y = None, None, None, None
    for f in files:
        arr = np.array(Image.open(f).convert("RGB"))
        mask = arr.max(axis=2) > threshold
        if edge_exclude:
            mask[:edge_exclude, :] = False
            mask[-edge_exclude:, :] = False
            mask[:, :edge_exclude] = False
            mask[:, -edge_exclude:] = False
        ys, xs = np.where(mask)
        if not len(xs):
            continue
        x0, x1 = xs.min(), xs.max()
        y0, y1 = ys.min(), ys.max()
        min_x = x0 if min_x is None else min(min_x, x0)
        min_y = y0 if min_y is None else min(min_y, y0)
        max_x = x1 if max_x is None else max(max_x, x1)
        max_y = y1 if max_y is None else max(max_y, y1)
    h, w = arr.shape[0], arr.shape[1]
    print(f"image size: {w}x{h}, sampled {len(files)} frames")
    print(f"raw bbox: x[{min_x},{max_x}] y[{min_y},{max_y}]")
    return min_x, min_y, max_x, max_y, w, h

if __name__ == "__main__":
    frame_dir = sys.argv[1] if len(sys.argv) > 1 else "brain_map_frames_v2"
    margin_frac = float(sys.argv[2]) if len(sys.argv) > 2 else 0.06
    sample_every = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    edge_exclude = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    x0, y0, x1, y1, w, h = content_bbox(frame_dir, sample_every=sample_every, edge_exclude=edge_exclude)
    bw, bh = x1 - x0, y1 - y0
    mx, my = int(bw * margin_frac), int(bh * margin_frac)
    cx0, cy0 = max(0, x0 - mx), max(0, y0 - my)
    cx1, cy1 = min(w, x1 + mx), min(h, y1 + my)
    cw, ch = cx1 - cx0, cy1 - cy0
    print(f"crop: w={cw} h={ch} x={cx0} y={cy0}")
    print(f"ffmpeg crop filter: crop={cw}:{ch}:{cx0}:{cy0}")
