#!/usr/bin/env python3
"""
Prepare the analysis image from a stitched OME-TIFF in a single pass:
  - match the markers (and the nuclear / membrane / AF channels) to the image's channel names
  - optionally pick the pyramid level closest to the target resolution, plus an integer downsampling factor
  - read only the needed channels at that level and block-average them to the target resolution
  - write the processed CYX OME-TIFF, its OME-XML, scale metadata (json) and single-channel images

Outputs (for --prefix P):
  P.downscaled.ome.tiff (with --target_mpp) or P.processed.ome.tiff   marker channels, CYX
  P.xml                                                               OME-XML of the processed image
  P.json                                                              scale metadata (original/final pixel size)
  P_dapi.tif, P_membrane.tif, P_AF.tif                                single channels, if requested
"""
# Version: 2.0.0

import argparse
import csv
import json
import re
import sys
from xml.dom import minidom
from xml.etree import ElementTree as ET

import numpy as np
import tifffile

OME_NS = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}


def read_markers(path):
    with open(path) as f:
        return [row['marker_name'] for row in csv.DictReader(f)]


def get_channel_names_from_ome(tif):
    if not tif.ome_metadata:
        return None
    try:
        root = ET.fromstring(tif.ome_metadata)
        channels = root.findall('.//ome:Channel', OME_NS)
        if channels:
            return [c.get('Name', c.get('ID', f'Ch{i}')) for i, c in enumerate(channels)]
    except ET.ParseError:
        pass
    return None


def get_physical_size(tif):
    if not tif.ome_metadata:
        return None, None
    try:
        root = ET.fromstring(tif.ome_metadata)
        pixels = root.find('.//ome:Pixels', OME_NS)
        if pixels is not None:
            px = pixels.get('PhysicalSizeX')
            py = pixels.get('PhysicalSizeY')
            if px and py:
                return float(px), float(py)
    except Exception:
        pass
    return None, None


def normalize_to_cyx(data, axes):
    axes = axes.upper()

    for i in range(data.ndim - 1, -1, -1):
        ax = axes[i]
        if ax not in ('C', 'Y', 'X', 'S', 'I') and data.shape[i] == 1:
            data = np.squeeze(data, axis=i)
            axes = axes[:i] + axes[i+1:]

    if 'C' not in axes:
        for alt in ('S', 'I'):
            if alt in axes:
                axes = axes.replace(alt, 'C', 1)
                break

    if not all(a in axes for a in 'CYX'):
        raise ValueError(f"Cannot resolve axes '{axes}' to CYX — got shape {data.shape}")

    order = [axes.index('C'), axes.index('Y'), axes.index('X')]
    return np.transpose(data, order)


def channel_count(series):
    """Number of channels (C axis, else S or I, as in normalize_to_cyx) without reading pixel data."""
    axes = series.axes.upper()
    for a in ('C', 'S', 'I'):
        if a in axes:
            return series.shape[axes.index(a)]
    raise ValueError(f"No channel axis in '{series.axes}'")


def extract_core(name):
    return re.sub(r'\s*\(.*?\)', '', name).strip()


def score_match(marker, channel_name):
    m_full = marker.upper()
    m_core = extract_core(marker).upper()
    c = channel_name.upper()

    if m_full == c or m_core == c:
        return 1.0
    if re.search(r'(?<![A-Z0-9])' + re.escape(m_core) + r'(?![A-Z0-9])', c):
        return 0.9
    if m_core in c or m_full in c:
        return 0.5
    return -1


def best_match(name, channel_names):
    """Index of the channel best matching `name`, or None."""
    best_score, best_idx, best_ch = max((score_match(name, ch), i, ch) for i, ch in enumerate(channel_names))
    if best_score < 0:
        return None
    print(f"  Matched '{name}' -> '{best_ch}' (score={best_score})")
    return best_idx


def match_channels(markers, channel_names):
    selected = []
    missing  = []
    for marker in markers:
        idx = best_match(marker, channel_names)
        if idx is None:
            missing.append(marker)
            print(f"  WARNING: No match for '{marker}' in {channel_names}")
        else:
            selected.append((idx, marker))
    return selected, missing


# ---------------------------------------------------------------------------
# Pyramid level selection (target resolution = integer-downsampled pyramid level)
# ---------------------------------------------------------------------------

def pyramid_levels(tif):
    """Resolution levels of the image, largest first (SubIFD pyramids or one series per level)."""
    series = tif.series[0]
    if series.levels and len(series.levels) > 1:
        return list(series.levels)
    if len(tif.series) > 1:
        # Older pyramids store each level as its own series; ignore unrelated series (labels, macros)
        return [s for s in tif.series if s.axes == series.axes]
    return [series]


def choose_level(levels, base_mpp, target_mpp):
    """
    Return (level_index, integer_factor, level_mpp_after_scaling).
    Prefers a level that needs no extra scaling when it is within 0.15 µm/px of the target;
    otherwise the level with the smallest error, preferring no scaling and then smaller levels.
    """
    x_idx = levels[0].axes.upper().index('X')
    base_x = levels[0].shape[x_idx]
    candidates = []
    for i, level in enumerate(levels):
        scale_factor = int(np.floor(base_x / level.shape[level.axes.upper().index('X')] + 0.5))
        effective_mpp = base_mpp * scale_factor
        integer_scale = int(np.floor(target_mpp / effective_mpp + 0.5))
        final_mpp = effective_mpp * integer_scale
        candidates.append(dict(level=i, scale_factor=scale_factor, integer_scale=integer_scale,
                               final_mpp=final_mpp, error=abs(final_mpp - target_mpp)))
        print(f"  Level {i}: shape={level.shape}, scale={scale_factor}x, effective_mpp={effective_mpp:.4f}, "
              f"int_scale={integer_scale}, final_mpp={final_mpp:.4f}")

    best = None
    for c in candidates:
        if c['integer_scale'] == 0:
            continue
        needs_scaling = c['integer_scale'] != 1
        if c['error'] <= 0.15 and not needs_scaling:
            return c
        if best is None or c['error'] < best['error'] - 0.1:
            best = c
        elif abs(c['error'] - best['error']) < 0.1:
            best_scaling = best['integer_scale'] != 1
            if (not needs_scaling and best_scaling) or (needs_scaling == best_scaling and c['level'] > best['level']):
                best = c
    if best is None:
        sys.exit(f"ERROR: no pyramid level can be downsampled to {target_mpp} µm/px (base {base_mpp} µm/px)")
    return best


def downsample(channel, factor):
    """Block-average a 2D array by an integer factor (edges that do not fill a block are cropped)."""
    if factor == 1:
        return channel
    new_y, new_x = channel.shape[0] // factor, channel.shape[1] // factor
    blocks = channel[:new_y * factor, :new_x * factor].reshape(new_y, factor, new_x, factor)
    out = blocks.mean(axis=(1, 3))
    if np.issubdtype(channel.dtype, np.integer):
        out = np.round(out).astype(channel.dtype)
    return out


def read_channels(level, indices, n_channels):
    """
    Read only the requested channels of one pyramid level, as a list of 2D arrays.
    Planar images (one page per channel) are read page by page; interleaved images are read whole.
    """
    keyframe = level.keyframe
    planar = len(level.pages) == n_channels and len(keyframe.shape) == 2
    if planar:
        return {i: np.squeeze(level.asarray(key=i)) for i in sorted(set(indices))}
    data = normalize_to_cyx(level.asarray(), level.axes)
    return {i: data[i] for i in sorted(set(indices))}


def main():
    parser = argparse.ArgumentParser(description='Prepare the analysis image: channel selection, downscaling, channel extraction')
    parser.add_argument('--image',      required=True)
    parser.add_argument('--markers',    required=True)
    parser.add_argument('--prefix',     required=True)
    parser.add_argument('--target_mpp', type=float, default=None, help='Downscale to this many µm per pixel (default: no downscaling)')
    parser.add_argument('--nuclear',    default='DAPI', help='Nuclear channel name, written to <prefix>_dapi.tif')
    parser.add_argument('--membrane',   default=None, help='Membrane channel name, written to <prefix>_membrane.tif')
    parser.add_argument('--af',         default=None, help='Autofluorescence channel name, written to <prefix>_AF.tif')
    parser.add_argument('--threads',    type=int, default=1, help='Threads for TIFF compression')
    args = parser.parse_args()

    markers = read_markers(args.markers)
    print(f"Markers requested ({len(markers)}): {markers}")

    with tifffile.TiffFile(args.image) as tif:
        channel_names = get_channel_names_from_ome(tif)
        physical_x, physical_y = get_physical_size(tif)
        levels = pyramid_levels(tif)
        base = levels[0]
        n_channels = channel_count(base)

        print(f"Input: shape {base.shape}, axes {base.axes}, {len(levels)} level(s)")
        print(f"OME channel names: {channel_names}")
        print(f"Physical size: x={physical_x}, y={physical_y}")

        if channel_names is None or len(channel_names) != n_channels:
            if len(markers) == n_channels:
                print(f"WARNING: OME channel names missing or mismatched ({len(channel_names) if channel_names else 0} vs {n_channels} channels); assuming channels match marker order.")
                channel_names = markers
            else:
                sys.exit(f"ERROR: {n_channels} image channels but {len(markers)} markers and no usable OME channel names.")

        selected, missing = match_channels(markers, channel_names)
        if missing:
            print(f"WARNING: unmatched markers: {missing}")
        if not selected:
            sys.exit("ERROR: No markers matched image channels.")

        extra = {}
        for label, name in (('dapi', args.nuclear), ('membrane', args.membrane), ('AF', args.af)):
            if not name:
                continue
            idx = best_match(name, channel_names)
            if idx is None:
                sys.exit(f"ERROR: channel '{name}' ({label}) not found in image channels {channel_names}")
            extra[label] = idx

        # Resolution
        if args.target_mpp:
            if physical_x is None:
                sys.exit("ERROR: cannot downscale: no PhysicalSizeX in the OME metadata (use --downscale_mode none)")
            choice = choose_level(levels, physical_x, args.target_mpp)
        else:
            choice = dict(level=0, scale_factor=1, integer_scale=1, final_mpp=physical_x)
        level = levels[choice['level']]
        factor = choice['integer_scale']
        print(f"Using level {choice['level']} with integer downsampling x{factor} -> {choice['final_mpp']} µm/px")

        needed = [i for i, _ in selected] + list(extra.values())
        channels = read_channels(level, needed, n_channels)

    channels = {i: downsample(ch, factor) for i, ch in channels.items()}

    # Processed image: marker channels in markerfile order, named by marker
    indices, names = zip(*selected)
    data = np.stack([channels[i] for i in indices])
    print(f"Output shape: {data.shape} — {len(names)} channels: {list(names)}")

    final_mpp = choice['final_mpp']
    metadata = {'axes': 'CYX', 'Channel': {'Name': list(names)}}
    if final_mpp is not None:
        metadata.update({
            'PhysicalSizeX': final_mpp, 'PhysicalSizeXUnit': 'µm',
            'PhysicalSizeY': final_mpp, 'PhysicalSizeYUnit': 'µm',
        })
    image_out = f"{args.prefix}.downscaled.ome.tiff" if args.target_mpp else f"{args.prefix}.processed.ome.tiff"
    tifffile.imwrite(
        image_out,
        data,
        ome=True,
        photometric='minisblack',
        metadata=metadata,
        tile=(512, 512),
        compression='deflate',
        compressionargs={'level': 6},
        maxworkers=args.threads,
        bigtiff=data.nbytes > 3.5 * (1024 ** 3) or any(d > 65000 for d in data.shape[1:]),
    )
    print(f"Written {image_out}")

    with tifffile.TiffFile(image_out) as tif:
        ome_xml = tif.ome_metadata
    with open(f"{args.prefix}.xml", 'w', encoding='utf-8') as f:
        f.write(minidom.parseString(ome_xml).toprettyxml(indent='  '))

    with open(f"{args.prefix}.json", 'w') as f:
        json.dump({
            'original_file': args.image,
            'original_physical_size_x': physical_x,
            'original_physical_size_y': physical_y,
            'pyramid_level_used': choice['level'],
            'pyramid_scale_factor': choice['scale_factor'],
            'integer_scale_applied': factor,
            'final_physical_size_x': final_mpp,
            'final_physical_size_y': final_mpp,
            'target_micron_per_pixel': args.target_mpp,
            'output_shape': list(data.shape),
            'output_axes': 'CYX',
            'channel_names': list(names),
        }, f, indent=2)

    for label, idx in extra.items():
        out = f"{args.prefix}_{label}.tif"
        tifffile.imwrite(out, channels[idx])
        print(f"Written {out} (channel '{channel_names[idx]}')")


if __name__ == '__main__':
    main()
