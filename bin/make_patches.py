#!/usr/bin/env python3
"""
Split a segmentation input image into overlapping patches, following sopa's patching approach
(https://github.com/prism-oncology/sopa, sopa/patches/patches.py).

Patches are laid out on a regular grid with stride (patch_size - patch_overlap). When an ROI mask is
given, patches that do not touch the ROI are skipped, kept patches are cropped to the ROI's bounding box,
and pixels outside the ROI are filled with each channel's mean inside the ROI so no cells are called there.

Outputs:
  patches/<prefix>_patch<NNNN>.tif           image patch (2D, or CYX if the input is multi-channel)
  patches/<prefix>_patch<NNNN>_membrane.tif  membrane patch, if --membrane is given
  <prefix>_patches.csv                       patch windows in image pixel coordinates
  <prefix>_patches.png                       overview of processed/skipped patches over the image
"""

# Written by Patrick Crock
# Version: 0.0.1

import argparse
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile
from matplotlib.patches import Rectangle


def grid_1d(length, patch_size, overlap):
    """sopa Patches1D: patches of width patch_size with the given overlap, truncated at the image edge."""
    if patch_size <= 0 or patch_size >= length:
        return [(0, length)]
    stride = patch_size - overlap
    n = math.ceil((length - overlap) / stride)
    return [(i * stride, min(i * stride + patch_size, length)) for i in range(n)]


def grow(lo, hi, bound_lo, bound_hi, target):
    """Grow [lo, hi) symmetrically to at least `target` pixels without leaving [bound_lo, bound_hi)."""
    target = min(target, bound_hi - bound_lo)
    missing = target - (hi - lo)
    if missing <= 0:
        return lo, hi
    lo = max(bound_lo, lo - missing // 2)
    hi = min(bound_hi, lo + target)
    lo = hi - target
    return lo, hi


def fill_outside(crop, inside):
    """Replace pixels outside the ROI with each channel's mean inside the ROI (sopa _channels_average_within_mask)."""
    if inside.all():
        return crop
    crop = crop.copy()
    for c in range(crop.shape[0]):
        mean = crop[c][inside].mean()
        if np.issubdtype(crop.dtype, np.integer):
            mean = np.round(mean)
        crop[c][~inside] = mean
    return crop


def read_image(path):
    img = np.squeeze(tifffile.imread(path))
    if img.ndim not in (2, 3):
        sys.exit(f"ERROR: expected a 2D or CYX image, got shape {img.shape} for {path}")
    return img


def save_overview(path, prefix, image, roi, rows, height, width):
    step = max(1, int(math.ceil(max(height, width) / 1500)))
    thumb = image[..., ::step, ::step]
    if thumb.ndim == 3:
        thumb = thumb.max(axis=0)
    thumb = thumb.astype(np.float32)
    lo, hi = np.percentile(thumb, [1, 99.5])
    thumb = np.clip((thumb - lo) / (hi - lo if hi > lo else 1), 0, 1)

    fig, ax = plt.subplots(figsize=(10, 10 * height / width))
    ax.imshow(thumb, cmap="gray", extent=(0, width, height, 0))
    if roi is not None:
        ax.contour(np.arange(0, width, step)[: thumb.shape[1]], np.arange(0, height, step)[: thumb.shape[0]],
                   roi[::step, ::step], levels=[0.5], colors="yellow", linewidths=0.8)
    for row in rows:
        kept = row["status"] == "kept"
        ax.add_patch(Rectangle(
            (row["x0"], row["y0"]), row["x1"] - row["x0"], row["y1"] - row["y0"],
            fill=False, edgecolor="lime" if kept else "red", linestyle="-" if kept else ":", linewidth=0.8,
        ))
    n_kept = sum(r["status"] == "kept" for r in rows)
    ax.set_title(f"{prefix}: {n_kept}/{len(rows)} patches segmented")
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Split an image into overlapping patches for segmentation.")
    parser.add_argument("--image", required=True, help="Segmentation input image (2D or CYX)")
    parser.add_argument("--membrane", default=None, help="Optional membrane image, patched on the same grid")
    parser.add_argument("--roi_mask", default=None, help="Optional ROI mask (channel 0 is the inclusion area)")
    parser.add_argument("--prefix", required=True, help="Output file prefix")
    parser.add_argument("--patch_size", type=int, default=2048, help="Patch width/height in pixels (0 = whole image)")
    parser.add_argument("--patch_overlap", type=int, default=100, help="Overlap between neighbouring patches in pixels")
    parser.add_argument("--min_size", type=int, default=256,
                        help="Minimum patch side after cropping to the ROI (bounded by the grid patch size)")
    parser.add_argument("--outdir", default="patches", help="Directory for patch images")
    args = parser.parse_args()

    if args.patch_size > 0 and args.patch_overlap >= args.patch_size:
        sys.exit(f"ERROR: patch_overlap ({args.patch_overlap}) must be smaller than patch_size ({args.patch_size})")

    image = read_image(args.image)
    is_2d = image.ndim == 2
    image = image[np.newaxis] if is_2d else image
    height, width = image.shape[-2:]
    print(f"Image: shape {image.shape}, dtype {image.dtype}")

    membrane = None
    if args.membrane:
        membrane = read_image(args.membrane)
        if membrane.ndim != 2 or membrane.shape != (height, width):
            sys.exit(f"ERROR: membrane image shape {membrane.shape} does not match image ({height}, {width})")
        membrane = membrane[np.newaxis]

    roi = None
    if args.roi_mask:
        roi = tifffile.imread(args.roi_mask, key=0) > 0
        if roi.shape != (height, width):
            sys.exit(f"ERROR: ROI mask shape {roi.shape} does not match image ({height}, {width})")
        print(f"ROI covers {roi.mean() * 100:.2f}% of the image")

    os.makedirs(args.outdir, exist_ok=True)
    ys = grid_1d(height, args.patch_size, args.patch_overlap)
    xs = grid_1d(width, args.patch_size, args.patch_overlap)
    min_size = args.min_size if args.patch_size <= 0 else min(args.min_size, args.patch_size)

    rows = []
    for iy, (gy0, gy1) in enumerate(ys):
        for ix, (gx0, gx1) in enumerate(xs):
            index = iy * len(xs) + ix
            y0, y1, x0, x1 = gy0, gy1, gx0, gx1
            grid = dict(grid_x0=gx0, grid_y0=gy0, grid_x1=gx1, grid_y1=gy1)
            roi_fraction = 1.0
            if roi is not None:
                sub = roi[gy0:gy1, gx0:gx1]
                if not sub.any():
                    rows.append(dict(patch=index, x0=gx0, y0=gy0, x1=gx1, y1=gy1, **grid, roi_fraction=0.0, status="skipped"))
                    continue
                inside_rows = np.flatnonzero(sub.any(axis=1))
                inside_cols = np.flatnonzero(sub.any(axis=0))
                y0, y1 = grow(gy0 + inside_rows[0], gy0 + inside_rows[-1] + 1, gy0, gy1, min_size)
                x0, x1 = grow(gx0 + inside_cols[0], gx0 + inside_cols[-1] + 1, gx0, gx1, min_size)
                roi_fraction = float(roi[y0:y1, x0:x1].mean())

            inside = roi[y0:y1, x0:x1] if roi is not None else None
            crop = image[:, y0:y1, x0:x1]
            if inside is not None:
                crop = fill_outside(crop, inside)
            name = f"{args.prefix}_patch{index:04d}"
            tifffile.imwrite(os.path.join(args.outdir, f"{name}.tif"), crop[0] if is_2d else crop)
            if membrane is not None:
                mem = membrane[:, y0:y1, x0:x1]
                if inside is not None:
                    mem = fill_outside(mem, inside)
                tifffile.imwrite(os.path.join(args.outdir, f"{name}_membrane.tif"), mem[0])
            rows.append(dict(patch=index, x0=x0, y0=y0, x1=x1, y1=y1, **grid, roi_fraction=roi_fraction, status="kept"))

    kept = [r for r in rows if r["status"] == "kept"]
    if not kept:
        sys.exit("ERROR: no patches intersect the ROI")

    table = pd.DataFrame(rows)
    table["patch_overlap"] = args.patch_overlap if len(ys) * len(xs) > 1 else 0
    table["image_height"] = height
    table["image_width"] = width
    table.to_csv(f"{args.prefix}_patches.csv", index=False)
    print(f"Wrote {len(kept)} of {len(rows)} patches (grid {len(ys)} x {len(xs)}, "
          f"size {args.patch_size}, overlap {args.patch_overlap})")

    save_overview(f"{args.prefix}_patches.png", args.prefix, image, roi, rows, height, width)


if __name__ == "__main__":
    main()
