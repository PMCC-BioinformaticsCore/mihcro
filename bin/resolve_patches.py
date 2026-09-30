#!/usr/bin/env python3
"""
Stitch per-patch segmentation label masks into one whole-image label mask.

Cells found twice in the overlap between patches are resolved with the rule from sopa's solve_conflicts
(https://github.com/prism-oncology/sopa, sopa/segmentation/resolve.py), applied directly to label images
instead of polygons: two overlapping cells from different patches are merged (pixel union) when their
intersection is at least `threshold` times the area of the smaller cell. Below the threshold both cells are
kept and the pixels already assigned keep their label, so the output is a clean, non-overlapping label image.

Before merging, cells cut by an interior patch edge are dropped when their centroid lies in the half of the
overlap owned by the neighbouring patch (which sees the whole cell), so truncated slivers do not survive.

Optionally, cells whose centroid falls outside the ROI mask (channel 0) are removed.
"""

# Written by Patrick Crock
# Version: 0.0.1

import argparse
import os
import re
import sys

import numpy as np
import pandas as pd
import tifffile
from skimage.segmentation import relabel_sequential


class UnionFind:
    """Union-find over integer cell ids, with areas tracked per root."""

    def __init__(self, capacity=1024):
        self.parent = np.arange(capacity, dtype=np.int64)
        self.area = np.zeros(capacity, dtype=np.int64)

    def reserve(self, n):
        if n <= len(self.parent):
            return
        size = max(n, 2 * len(self.parent))
        old = len(self.parent)
        self.parent = np.concatenate([self.parent, np.arange(old, size, dtype=np.int64)])
        self.area = np.concatenate([self.area, np.zeros(size - old, dtype=np.int64)])

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def find_all(self, ids):
        roots = self.parent[ids]
        while True:
            nxt = self.parent[roots]
            if np.array_equal(nxt, roots):
                return roots
            roots = nxt

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        self.parent[rb] = ra
        self.area[ra] += self.area[rb]
        return ra


def patch_index(path):
    match = re.search(r"_patch(\d+)", os.path.basename(path))
    if not match:
        sys.exit(f"ERROR: cannot parse patch index from mask file name: {path}")
    return int(match.group(1))


def drop_truncated(local, row, height, width):
    """
    Remove cells cut by an interior patch edge whose centroid lies in the half of the overlap owned by a
    neighbouring patch. With an overlap of at least ~2x the cell diameter, that neighbour sees the whole cell,
    so dropping the truncated copy avoids slivers too small to reach the merge threshold with the full cell.
    """
    y0, x0 = int(row.y0), int(row.x0)
    gy0, gy1, gx0, gx1 = int(row.grid_y0), int(row.grid_y1), int(row.grid_x0), int(row.grid_x1)
    h, w = local.shape
    cut_top, cut_bottom = y0 == gy0 and gy0 > 0, y0 + h == gy1 and gy1 < height
    cut_left, cut_right = x0 == gx0 and gx0 > 0, x0 + w == gx1 and gx1 < width
    edges = [e for cut, e in ((cut_top, local[0]), (cut_bottom, local[-1]),
                              (cut_left, local[:, 0]), (cut_right, local[:, -1])) if cut]
    if not edges:
        return local
    cut = np.unique(np.concatenate(edges))
    cut = cut[cut > 0]
    if not cut.size:
        return local

    half = float(row.patch_overlap) / 2
    core_y0, core_y1 = (gy0 + half if gy0 > 0 else 0), (gy1 - half if gy1 < height else height)
    core_x0, core_x1 = (gx0 + half if gx0 > 0 else 0), (gx1 - half if gx1 < width else width)

    n = int(local.max())
    flat = local.ravel()
    count = np.bincount(flat, minlength=n + 1)[cut]
    cy = np.bincount(flat, weights=np.repeat(np.arange(h), w), minlength=n + 1)[cut] / count + y0
    cx = np.bincount(flat, weights=np.tile(np.arange(w), h), minlength=n + 1)[cut] / count + x0
    outside = (cy < core_y0) | (cy >= core_y1) | (cx < core_x0) | (cx >= core_x1)
    drop = cut[outside]
    if drop.size:
        local = np.where(np.isin(local, drop), 0, local)
    return local


def add_patch(labels, cells, mask, row, next_id, threshold):
    """Merge one patch's label mask into the global label image. Returns the next free cell id."""
    y0, x0 = int(row.y0), int(row.x0)
    local, _, _ = relabel_sequential(mask)
    local = drop_truncated(local, row, *labels.shape)
    n_local = int(local.max())
    if n_local == 0:
        return next_id
    cells.reserve(next_id + n_local)

    window = labels[y0:y0 + local.shape[0], x0:x0 + local.shape[1]]
    new_area = np.bincount(local.ravel(), minlength=n_local + 1)
    target = np.arange(next_id - 1, next_id + n_local, dtype=np.int64)
    target[0] = 0

    overlap = (local > 0) & (window > 0)
    if overlap.any():
        new_ids = local[overlap].astype(np.int64)
        old_roots = cells.find_all(window[overlap].astype(np.int64))
        pairs, intersections = np.unique(np.stack([new_ids, old_roots]), axis=1, return_counts=True)
        merged_into = {}
        for (new, old), inter in zip(pairs.T, intersections):
            old = cells.find(old)
            if inter >= threshold * min(new_area[new], cells.area[old]):
                if new in merged_into:
                    merged_into[new] = cells.union(merged_into[new], old)
                else:
                    merged_into[new] = old
        for new, root in merged_into.items():
            target[new] = cells.find(root)

    free = (local > 0) & (window == 0)
    written = target[local[free]]
    window[free] = written
    ids, counts = np.unique(written, return_counts=True)
    for cell, count in zip(ids, counts):
        cells.area[cells.find(cell)] += count

    return next_id + n_local


def centroids(labels, n_labels, chunk_rows=1024):
    """Pixel centroids (row, col) of labels 1..n_labels, computed in row chunks to bound memory."""
    count = np.zeros(n_labels + 1)
    sum_r = np.zeros(n_labels + 1)
    sum_c = np.zeros(n_labels + 1)
    height, width = labels.shape
    cols = np.arange(width)
    for r0 in range(0, height, chunk_rows):
        block = labels[r0:r0 + chunk_rows]
        flat = block.ravel()
        rows = np.repeat(np.arange(r0, r0 + block.shape[0]), width)
        count += np.bincount(flat, minlength=n_labels + 1)
        sum_r += np.bincount(flat, weights=rows, minlength=n_labels + 1)
        sum_c += np.bincount(flat, weights=np.tile(cols, block.shape[0]), minlength=n_labels + 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return sum_r / count, sum_c / count


def main():
    parser = argparse.ArgumentParser(description="Resolve per-patch segmentation masks into one label image.")
    parser.add_argument("--masks", nargs="+", required=True, help="Per-patch label masks (file names contain _patchNNNN)")
    parser.add_argument("--patches", required=True, help="Patch table written by make_patches.py")
    parser.add_argument("--output", required=True, help="Output label mask .tif")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Merge two overlapping cells if intersection >= threshold * smaller cell area")
    parser.add_argument("--roi_mask", default=None, help="Optional ROI mask; cells with centroid outside channel 0 are removed")
    args = parser.parse_args()

    table = pd.read_csv(args.patches)
    table = table[table["status"] == "kept"].set_index("patch")
    height, width = int(table["image_height"].iloc[0]), int(table["image_width"].iloc[0])

    masks = {patch_index(m): m for m in args.masks}
    missing = sorted(set(table.index) - set(masks))
    unexpected = sorted(set(masks) - set(table.index))
    if missing or unexpected:
        sys.exit(f"ERROR: patch masks do not match the patch table (missing: {missing}, unexpected: {unexpected})")

    labels = np.zeros((height, width), dtype=np.uint32)
    cells = UnionFind()
    next_id = 1
    for index in sorted(masks):
        row = table.loc[index]
        mask = np.squeeze(tifffile.imread(masks[index]))
        expected = (int(row.y1 - row.y0), int(row.x1 - row.x0))
        if mask.shape != expected:
            sys.exit(f"ERROR: mask for patch {index} has shape {mask.shape}, expected {expected}")
        next_id = add_patch(labels, cells, mask, row, next_id, args.threshold)
        if next_id >= np.iinfo(np.uint32).max:
            sys.exit("ERROR: too many cells for a uint32 label image")

    lut = cells.find_all(np.arange(next_id, dtype=np.int64)).astype(np.uint32)
    labels = lut[labels]
    labels = relabel_sequential(labels)[0].astype(np.uint32, copy=False)
    n_cells = int(labels.max())
    print(f"Resolved {len(masks)} patches into {n_cells} cells")

    if args.roi_mask:
        roi = tifffile.imread(args.roi_mask, key=0) > 0
        if roi.shape != labels.shape:
            sys.exit(f"ERROR: ROI mask shape {roi.shape} does not match image ({height}, {width})")
        cy, cx = centroids(labels, n_cells)
        present = np.isfinite(cy)
        keep = np.zeros(n_cells + 1, dtype=bool)
        keep[present] = roi[np.round(cy[present]).astype(int), np.round(cx[present]).astype(int)]
        keep[0] = False
        lut = np.where(keep, np.arange(n_cells + 1), 0).astype(np.uint32)
        labels = relabel_sequential(lut[labels])[0].astype(np.uint32, copy=False)
        print(f"Removed {n_cells - int(labels.max())} cells with centroids outside the ROI; {int(labels.max())} remain")

    tifffile.imwrite(args.output, labels, bigtiff=labels.nbytes > 3.5 * (1024 ** 3))
    print(f"Saved label mask to {args.output}")


if __name__ == "__main__":
    main()
