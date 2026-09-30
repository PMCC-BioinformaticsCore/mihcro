#!/usr/bin/env python3
# Version: 1.0.0
import argparse
import csv
import re
import sys
import numpy as np
import tifffile
from xml.etree import ElementTree as ET


def read_markers(path):
    with open(path) as f:
        return [row['marker_name'] for row in csv.DictReader(f)]


def get_channel_names_from_ome(tif):
    if not tif.ome_metadata:
        return None
    try:
        ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
        root = ET.fromstring(tif.ome_metadata)
        channels = root.findall('.//ome:Channel', ns)
        if channels:
            return [c.get('Name', c.get('ID', f'Ch{i}')) for i, c in enumerate(channels)]
    except ET.ParseError:
        pass
    return None


def get_physical_size(tif):
    if not tif.ome_metadata:
        return None, None
    try:
        ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
        root = ET.fromstring(tif.ome_metadata)
        pixels = root.find('.//ome:Pixels', ns)
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


def match_channels(markers, channel_names):
    selected = []
    missing  = []
    for marker in markers:
        scored = [(score_match(marker, ch), i, ch) for i, ch in enumerate(channel_names)]
        best_score, best_idx, best_ch = max(scored, key=lambda x: x[0])
        if best_score >= 0:
            selected.append((best_idx, marker))
            print(f"  Matched '{marker}' -> '{best_ch}' (score={best_score})")
        else:
            missing.append(marker)
            print(f"  WARNING: No match for '{marker}' in {channel_names}")
    return selected, missing


def main():
    parser = argparse.ArgumentParser(description='Preprocess OME-TIFF: normalize axes to CYX, filter to marker channels')
    parser.add_argument('--image',   required=True)
    parser.add_argument('--markers', required=True)
    parser.add_argument('--output',  required=True)
    args = parser.parse_args()

    markers = read_markers(args.markers)
    print(f"Markers requested ({len(markers)}): {markers}")

    with tifffile.TiffFile(args.image) as tif:
        series        = tif.series[0]
        data          = series.asarray()
        axes          = series.axes
        channel_names = get_channel_names_from_ome(tif)
        physical_x, physical_y = get_physical_size(tif)

    print(f"Input shape: {data.shape}, axes: {axes}")
    print(f"OME channel names: {channel_names}")
    print(f"Physical size: x={physical_x}, y={physical_y}")

    data = normalize_to_cyx(data, axes)
    print(f"Normalized shape: {data.shape}, axes: CYX")

    n_channels = data.shape[0]

    if channel_names is None or len(channel_names) != n_channels:
        if len(markers) == n_channels:
            print(f"WARNING: OME channel names missing or mismatched ({len(channel_names) if channel_names else 0} vs {n_channels} channels); assuming channels match marker order.")
            channel_names = markers
        else:
            print(f"ERROR: {n_channels} image channels but {len(markers)} markers and no usable OME channel names.")
            sys.exit(1)

    selected, missing = match_channels(markers, channel_names)

    if missing:
        print(f"WARNING: unmatched markers: {missing}")
    if not selected:
        print(f"ERROR: No markers matched image channels.")
        sys.exit(1)

    indices, selected_names = zip(*selected)
    data = data[list(indices)]
    print(f"Output shape: {data.shape} — {len(selected_names)} channels: {list(selected_names)}")

    metadata = {
        'axes': 'CYX',
        'Channel': {'Name': list(selected_names)},
    }
    if physical_x is not None:
        metadata.update({
            'PhysicalSizeX': physical_x, 'PhysicalSizeXUnit': 'µm',
            'PhysicalSizeY': physical_y, 'PhysicalSizeYUnit': 'µm',
        })

    use_bigtiff = data.nbytes > 3.5 * (1024**3) or any(d > 65000 for d in data.shape[1:])

    with tifffile.TiffWriter(args.output, bigtiff=use_bigtiff, ome=True) as tif:
            tif.write(
                data,
                shape=data.shape,
                dtype=data.dtype,
                photometric='minisblack',
                metadata=metadata,
                compression='deflate',
                compressionargs={'level': 6},
            )

    print(f"Written to {args.output}")


if __name__ == '__main__':
    main()
