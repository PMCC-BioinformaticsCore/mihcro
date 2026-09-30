#!/usr/bin/env python3
"""
Build region-of-interest (ROI) masks aligned to the processed image.

Two modes:
  --geojson     QuPath-exported GeoJSON annotations (one or more files, any number of shapes/classes)
  --tissue_image automatic tissue detection on a nuclear (DAPI) image, adapted from sopa's
                 staining-based tissue segmentation (https://github.com/prism-oncology/sopa)

Both modes write the same set of outputs so the rest of the pipeline is agnostic to the source:
  <prefix>_roi_mask.ome.tif  uint8 CYX, channel 0 = 'ROI' (inclusion area), then one channel per class
  <prefix>_roi_labels.tif    per-pixel index of the class of the smallest shape covering the pixel
  <prefix>_roi_classes.csv   lookup table: index, class, column, n_shapes, area_px, area_mm2, excluded
  <prefix>_roi.geojson       shapes rescaled into processed-image pixel coordinates
  <prefix>_roi.png           thumbnail of the ROI classes for QC
"""

# Written by Patrick Crock
# Version: 0.0.1

import argparse
import copy
import fnmatch
import json
import math
import re
import sys
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from skimage.filters import median, threshold_otsu
from skimage.morphology import disk
from skimage.transform import downscale_local_mean

ROI_CHANNEL = "ROI"


# ---------------------------------------------------------------------------
# Image metadata
# ---------------------------------------------------------------------------

def read_image_info(xml_path):
    """Return (height, width, microns per pixel) of the processed image from its OME-XML."""
    root = ET.parse(xml_path).getroot()
    pixels = root.find(".//{*}Pixels")
    if pixels is None:
        sys.exit(f"ERROR: no <Pixels> element found in {xml_path}")
    height = int(pixels.get("SizeY"))
    width = int(pixels.get("SizeX"))
    mpp = pixels.get("PhysicalSizeX")
    mpp = float(mpp) if mpp else None
    return height, width, mpp


def coordinate_scale(scale_json, processed_mpp):
    """
    Factor that maps full-resolution input pixels (the space QuPath exports in) to processed-image pixels.
    Uses the metadata json written by ome_tiff_rescaler.py; no json means the image was not downscaled.
    """
    if not scale_json:
        return 1.0
    with open(scale_json) as f:
        meta = json.load(f)
    original = meta.get("original_physical_size_x")
    final = meta.get("final_physical_size_x") or processed_mpp
    if not original or not final:
        sys.exit(f"ERROR: could not read original/final physical pixel sizes from {scale_json}")
    return float(original) / float(final)


# ---------------------------------------------------------------------------
# GeoJSON parsing
# ---------------------------------------------------------------------------

def iter_features(obj):
    """Yield GeoJSON Features from a FeatureCollection, Feature, list of Features or bare geometry."""
    if isinstance(obj, list):
        for item in obj:
            yield from iter_features(item)
    elif isinstance(obj, dict):
        kind = obj.get("type")
        if kind == "FeatureCollection":
            for item in obj.get("features", []):
                yield from iter_features(item)
        elif kind == "Feature":
            yield obj
        elif kind == "GeometryCollection" or (kind is not None and "coordinates" in obj):
            yield {"type": "Feature", "geometry": obj, "properties": {}}


def geometry_polygons(geom):
    """Return a list of polygons (each a list of rings, exterior first) from a GeoJSON geometry."""
    if not geom:
        return []
    kind = geom.get("type")
    if kind == "Polygon":
        return [geom["coordinates"]]
    if kind == "MultiPolygon":
        return list(geom["coordinates"])
    if kind == "GeometryCollection":
        return [p for g in geom.get("geometries", []) for p in geometry_polygons(g)]
    return []


def feature_class(props):
    classification = props.get("classification")
    if isinstance(classification, dict):
        name = classification.get("name")
    else:
        name = classification
    return str(name).strip() if name else "Unclassified"


def ring_area(ring):
    """Shoelace area of a ring given as [[x, y], ...]."""
    xy = np.asarray(ring, dtype=float)
    if len(xy) < 3:
        return 0.0
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def polygon_area(rings):
    return max(ring_area(rings[0]) - sum(ring_area(r) for r in rings[1:]), 0.0)


def load_shapes(geojson_paths, scale, exclude_patterns):
    """Read all polygonal annotations, rescaled into processed-image pixel coordinates."""
    shapes = []
    skipped = {}
    for path in geojson_paths:
        with open(path) as f:
            data = json.load(f)
        for feature in iter_features(data):
            props = feature.get("properties") or {}
            object_type = props.get("objectType")
            if object_type not in (None, "annotation"):
                skipped[object_type] = skipped.get(object_type, 0) + 1
                continue
            geom = feature.get("geometry") or {}
            polygons = geometry_polygons(geom)
            if not polygons:
                kind = geom.get("type", "none")
                skipped[kind] = skipped.get(kind, 0) + 1
                continue
            name = feature_class(props)
            excluded = any(fnmatch.fnmatch(name.lower(), p.lower()) for p in exclude_patterns)
            for rings in polygons:
                scaled = [[[x * scale, y * scale] for x, y, *_ in ring] for ring in rings if len(ring) >= 3]
                if not scaled:
                    continue
                shapes.append({
                    "class": name,
                    "excluded": excluded,
                    "rings": scaled,
                    "area": polygon_area(scaled),
                    "properties": props,
                })
    for kind, n in skipped.items():
        print(f"WARNING: skipped {n} non-polygon/non-annotation object(s) of type '{kind}'")
    return shapes


# ---------------------------------------------------------------------------
# Rasterisation
# ---------------------------------------------------------------------------

def rasterize_shape(rings, height, width):
    """
    Rasterize one polygon (exterior + holes) within its bounding box.
    Returns (y0, x0, mask) or None if the shape lies outside the image.
    Coordinates use QuPath's convention (pixel i spans [i, i+1)), so they are shifted by -0.5 to pixel centres.
    """
    exterior = np.asarray(rings[0], dtype=float) - 0.5
    x0 = max(int(math.floor(exterior[:, 0].min())), 0)
    y0 = max(int(math.floor(exterior[:, 1].min())), 0)
    x1 = min(int(math.ceil(exterior[:, 0].max())) + 1, width)
    y1 = min(int(math.ceil(exterior[:, 1].max())) + 1, height)
    if x1 <= x0 or y1 <= y0:
        return None
    canvas = Image.new("L", (x1 - x0, y1 - y0), 0)
    draw = ImageDraw.Draw(canvas)
    draw.polygon([(x - x0, y - y0) for x, y in exterior], fill=1)
    for hole in rings[1:]:
        hole = np.asarray(hole, dtype=float) - 0.5
        draw.polygon([(x - x0, y - y0) for x, y in hole], fill=0)
    return y0, x0, np.asarray(canvas, dtype=bool)


def column_name(name, used):
    base = "roi_" + (re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_") or "Unclassified")
    column, i = base, 2
    while column in used:
        column, i = f"{base}_{i}", i + 1
    used.add(column)
    return column


def masks_from_shapes(shapes, height, width):
    """
    Build the inclusion mask, per-class masks and primary-class label raster.
    Inclusion = union(non-excluded shapes) - union(excluded shapes); if only excluded shapes were
    given, the inclusion area is the whole image minus the exclusions.
    """
    included = [s for s in shapes if not s["excluded"]]
    excluded = [s for s in shapes if s["excluded"]]

    class_names = sorted({s["class"] for s in included})
    class_index = {name: i + 1 for i, name in enumerate(class_names)}
    label_dtype = np.uint8 if len(class_names) < 255 else np.uint16

    inclusion = np.zeros((height, width), dtype=bool) if included else np.ones((height, width), dtype=bool)
    class_masks = {name: np.zeros((height, width), dtype=bool) for name in class_names}
    labels = np.zeros((height, width), dtype=label_dtype)
    exclusion = np.zeros((height, width), dtype=bool)
    shape_counts = {}

    # Paint largest shapes first so the smallest (most specific) shape wins in the label raster
    for shape in sorted(included, key=lambda s: s["area"], reverse=True):
        raster = rasterize_shape(shape["rings"], height, width)
        if raster is None:
            continue
        y0, x0, m = raster
        window = (slice(y0, y0 + m.shape[0]), slice(x0, x0 + m.shape[1]))
        inclusion[window] |= m
        class_masks[shape["class"]][window] |= m
        labels[window][m] = class_index[shape["class"]]
        shape_counts[shape["class"]] = shape_counts.get(shape["class"], 0) + 1

    excluded_areas = {}
    for shape in excluded:
        raster = rasterize_shape(shape["rings"], height, width)
        if raster is None:
            continue
        y0, x0, m = raster
        exclusion[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] |= m
        excluded_areas.setdefault(shape["class"], [0, 0])
        excluded_areas[shape["class"]][0] += 1
        excluded_areas[shape["class"]][1] += int(m.sum())

    inclusion &= ~exclusion
    labels[~inclusion] = 0
    for m in class_masks.values():
        m &= inclusion

    return inclusion, class_masks, labels, shape_counts, excluded_areas


# ---------------------------------------------------------------------------
# Tissue detection (adapted from sopa.segmentation.tissue, 'staining' mode)
# ---------------------------------------------------------------------------

def detect_tissue(image_path, height, width, downsample, blur_radius, drop_threshold, expand_ratio):
    img = np.squeeze(tifffile.imread(image_path)).astype(np.float32)
    if img.ndim == 3:
        img = img.max(axis=0)
    if img.shape != (height, width):
        sys.exit(f"ERROR: tissue image shape {img.shape} does not match processed image ({height}, {width})")
    img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)

    thumb = downscale_local_mean(img, (downsample, downsample))
    del img

    # Saturate everything above a fifth of the 90th percentile, as in sopa's staining mode
    upper = np.quantile(thumb, 0.9) / 5
    if upper <= 0:
        upper = thumb.max() if thumb.max() > 0 else 1.0
    thumb = (np.clip(thumb, 0, upper) / upper * 255).astype(np.uint8)

    footprint = disk(blur_radius)
    thumb = median(thumb, footprint)
    if thumb.min() == thumb.max():
        return None
    mask = thumb > threshold_otsu(thumb)
    mask = ndi.binary_opening(mask, structure=footprint)
    mask = ndi.binary_closing(mask, structure=footprint)

    labelled, n = ndi.label(mask)
    if n == 0:
        return None
    sizes = np.bincount(labelled.ravel())[1:]
    keep = np.flatnonzero(sizes >= drop_threshold * sizes.sum()) + 1
    mask = np.isin(labelled, keep)

    radius = int(math.ceil(expand_ratio * math.sqrt(mask.sum() / math.pi)))
    if radius > 0:
        mask = ndi.binary_dilation(mask, structure=disk(radius))

    full = np.repeat(np.repeat(mask, downsample, axis=0), downsample, axis=1)[:height, :width]
    return full


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

def write_outputs(prefix, inclusion, class_masks, labels, shape_counts, excluded_areas, mpp, shapes):
    class_names = list(class_masks.keys())
    channel_names = [ROI_CHANNEL] + class_names

    stack = np.zeros((len(channel_names), *inclusion.shape), dtype=np.uint8)
    stack[0][inclusion] = 255
    for i, name in enumerate(class_names, start=1):
        stack[i][class_masks[name]] = 255

    metadata = {"axes": "CYX", "Channel": {"Name": channel_names}}
    if mpp:
        metadata.update({"PhysicalSizeX": mpp, "PhysicalSizeXUnit": "µm",
                         "PhysicalSizeY": mpp, "PhysicalSizeYUnit": "µm"})
    tifffile.imwrite(
        f"{prefix}_roi_mask.ome.tif",
        stack,
        ome=True,
        photometric="minisblack",
        compression="deflate",
        tile=(256, 256),
        bigtiff=stack.nbytes > 3.5 * (1024 ** 3),
        metadata=metadata,
    )
    tifffile.imwrite(f"{prefix}_roi_labels.tif", labels, compression="deflate", tile=(256, 256),
                     bigtiff=labels.nbytes > 3.5 * (1024 ** 3))

    px_to_mm2 = (mpp / 1000.0) ** 2 if mpp else float("nan")
    used = set()
    rows = [{
        "index": 0, "class": ROI_CHANNEL, "column": "", "n_shapes": sum(shape_counts.values()),
        "area_px": int(inclusion.sum()), "area_mm2": inclusion.sum() * px_to_mm2, "excluded": False,
    }]
    for i, name in enumerate(class_names, start=1):
        area = int(class_masks[name].sum())
        rows.append({
            "index": i, "class": name, "column": column_name(name, used), "n_shapes": shape_counts.get(name, 0),
            "area_px": area, "area_mm2": area * px_to_mm2, "excluded": False,
        })
    for name, (n, area) in sorted(excluded_areas.items()):
        rows.append({
            "index": "", "class": name, "column": "", "n_shapes": n,
            "area_px": area, "area_mm2": area * px_to_mm2, "excluded": True,
        })
    table = pd.DataFrame(rows)
    table["excluded"] = table["excluded"].map({True: "TRUE", False: "FALSE"})  # readable as logical by R and pandas
    table.to_csv(f"{prefix}_roi_classes.csv", index=False)

    features = []
    for shape in shapes:
        props = dict(shape["properties"])
        props["mihcro_excluded"] = shape["excluded"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": shape["rings"]},
            "properties": props,
        })
    with open(f"{prefix}_roi.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)

    step = max(1, int(math.ceil(max(labels.shape) / 1500)))
    fig, ax = plt.subplots(figsize=(10, 10 * labels.shape[0] / labels.shape[1]))
    cmap = copy.copy(plt.get_cmap("tab20"))
    cmap.set_bad("white")
    ax.imshow(np.ma.masked_equal(labels[::step, ::step], 0), cmap=cmap, interpolation="nearest",
              vmin=0, vmax=max(20, len(class_names)))
    ax.contour(inclusion[::step, ::step], levels=[0.5], colors="black", linewidths=0.8)
    handles = [plt.Rectangle((0, 0), 1, 1, color=plt.cm.tab20(i / max(20, len(class_names)))) for i in range(1, len(class_names) + 1)]
    if handles:
        ax.legend(handles, class_names, loc="upper right", fontsize="small")
    ax.set_title(f"{prefix}: ROI ({inclusion.mean() * 100:.1f}% of image)")
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(f"{prefix}_roi.png", dpi=120)
    plt.close(fig)

    print(f"ROI covers {inclusion.sum()} px ({inclusion.mean() * 100:.2f}% of image), classes: {class_names}")


def main():
    parser = argparse.ArgumentParser(description="Build ROI masks from QuPath GeoJSON or automatic tissue detection.")
    parser.add_argument("--xml", required=True, help="OME-XML of the processed image (gives shape and pixel size)")
    parser.add_argument("--prefix", required=True, help="Output file prefix")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--geojson", nargs="+", help="QuPath-exported GeoJSON file(s)")
    source.add_argument("--tissue_image", help="Nuclear image for automatic tissue detection")
    parser.add_argument("--scale_json", default=None, help="Downscaling metadata json (ome_tiff_rescaler.py)")
    parser.add_argument("--exclude", default="Ignore*",
                        help="Comma-separated, case-insensitive class name globs whose shapes are subtracted from the ROI")
    parser.add_argument("--tissue_downsample", type=int, default=16, help="Downsampling factor for tissue detection")
    parser.add_argument("--tissue_blur_radius", type=int, default=5, help="Median blur / morphology radius (thumbnail px)")
    parser.add_argument("--tissue_drop_threshold", type=float, default=0.01,
                        help="Drop tissue components smaller than this fraction of total tissue area")
    parser.add_argument("--tissue_expand_ratio", type=float, default=0.05,
                        help="Dilate tissue by this fraction of its equivalent radius")
    args = parser.parse_args()

    height, width, mpp = read_image_info(args.xml)
    print(f"Processed image: {height} x {width} px, {mpp} µm/px")

    if args.geojson:
        scale = coordinate_scale(args.scale_json, mpp)
        print(f"Scaling GeoJSON coordinates by {scale:.6f}")
        exclude = [p.strip() for p in args.exclude.split(",") if p.strip()]
        shapes = load_shapes(args.geojson, scale, exclude)
        if not shapes:
            sys.exit("ERROR: no polygon annotations found in the supplied GeoJSON file(s)")
        inclusion, class_masks, labels, shape_counts, excluded_areas = masks_from_shapes(shapes, height, width)
        if not inclusion.any():
            xs = [x for s in shapes for x, _ in s["rings"][0]]
            ys = [y for s in shapes for _, y in s["rings"][0]]
            sys.exit(
                f"ERROR: the ROI does not overlap the processed image ({width} x {height} px). Scaled shape bounds are "
                f"x=[{min(xs):.0f}, {max(xs):.0f}], y=[{min(ys):.0f}, {max(ys):.0f}]. Check that the GeoJSON was "
                f"exported from the full-resolution image that the pipeline ingests."
            )
    else:
        mask = detect_tissue(args.tissue_image, height, width, args.tissue_downsample, args.tissue_blur_radius,
                             args.tissue_drop_threshold, args.tissue_expand_ratio)
        fraction = mask.mean() if mask is not None else 0.0
        if mask is None or fraction < 0.01 or fraction > 0.99:
            print(f"WARNING: tissue detection was degenerate (tissue fraction {fraction:.3f}); using the whole image")
            mask = np.ones((height, width), dtype=bool)
        inclusion = mask
        class_masks = {"Tissue": mask}
        labels = mask.astype(np.uint8)
        shape_counts = {"Tissue": 1}
        excluded_areas = {}
        shapes = []

    write_outputs(args.prefix, inclusion, class_masks, labels, shape_counts, excluded_areas, mpp, shapes)


if __name__ == "__main__":
    main()
