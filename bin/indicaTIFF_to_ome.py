#!/usr/bin/env python

## from: https://forum.image.sc/t/trouble-generating-ome-tiffs-in-the-right-shape/89191/7

import argparse
from xml.etree import ElementTree
from tifffile import TiffFile, TiffWriter
from xml.dom import minidom

def tiles(series):
    # yield raw tiles from all pages in TIFF series
    fh = series.parent.filehandle
    for page in series:
        for offset, bytecount in zip(page.dataoffsets, page.databytecounts):
            fh.seek(offset)
            yield fh.read(bytecount)


def main():
    parser = argparse.ArgumentParser(description="Convert HALO/Indica tif to OME tif")
    parser.add_argument("-o", "--output", type=str, required=True, help="Output .ome.tif file")
    parser.add_argument("-i", "--image", type=str, required=True, help="Input .tif image")

    args = parser.parse_args()

    with TiffFile(args.image) as tif:
        print(tif)

        tree = ElementTree.fromstring(tif.pages.first.description)
        channel_names = [
            channel.attrib['name'] for channel in tree.iter('channel')
        ]

        with TiffWriter(
            args.output, bigtiff=True, ome=True, byteorder=tif.byteorder
        ) as ome:
            for series in tif.series:
                print("SERIES:", series)
                print("  series.axes:", series.axes, "series.shape:", series.shape)
                assert series.axes == 'IYX'
                assert series.shape[0] == len(channel_names)

                for i, level in enumerate(series.levels):
                    page = level.keyframe
                    print("  LEVEL", i, "level.shape:", level.shape, "page.keyframe.shape:", getattr(page, 'shape', None))
                    print("    page.imagewidth:", getattr(page, 'imagewidth', None),
                          "page.imagelength:", getattr(page, 'imagelength', None))
                    print("    page.tile:", getattr(page, 'tile', None))
                    print("    TileWidth/TileLength tags:",
                          page.tags.get('TileWidth'), page.tags.get('TileLength'))

                    assert page.is_tiled

                    # --- compute rows/cols and samples confidently from page tags ---
                    rows = getattr(page, 'imagelength', None)
                    cols = getattr(page, 'imagewidth', None)
                    # number of channels/samples (fall back to level.shape if unsure)
                    samples = series.shape[0] if series.shape else (level.shape[0] if len(level.shape) == 3 else 1)

                    # If level.shape looks like (rows, cols, samples) convert to (samples, rows, cols)
                    if len(level.shape) == 3:
                        a, b, c = level.shape
                        if (a == rows and b == cols and c == samples):
                            inferred_shape = (samples, rows, cols)
                        elif (a == samples and b == rows and c == cols):
                            inferred_shape = (a, b, c)  # already (samples, rows, cols)
                        else:
                            # fallback to explicit (samples, rows, cols)
                            inferred_shape = (samples, rows, cols)
                    else:
                        inferred_shape = (rows, cols)

                    # get tile dims from tags if present (TileWidth, TileLength)
                    try:
                        tile_w = page.tags['TileWidth'].value
                        tile_l = page.tags['TileLength'].value
                        tile = (tile_w, tile_l)
                    except Exception:
                        tile = page.tile or None

                    if i == 0:
                        # base-level metadata construction (unchanged)
                        if len(series.levels) > 1:
                            subifds = len(series.levels) - 1
                        else:
                            subifds = None
                        resx, resy = page.get_resolution('micrometer')
                        metadata = {
                            'axes': 'CYX',
                            'PhysicalSizeX': resx,
                            'PhysicalSizeXUnit': 'µm',
                            'PhysicalSizeY': resy,
                            'PhysicalSizeYUnit': 'µm',
                            'Channel': {'Name': channel_names},
                        }
                    else:
                        subifds = None
                        metadata = None

                    dtype = 'float32' if level.dtype == 'uint32' else level.dtype

                    print("    -> writing with shape:", inferred_shape, "tile:", tile)

                    ome.write(
                        tiles(level),
                        shape=inferred_shape,
                        dtype=dtype,
                        photometric=page.photometric,
                        compression=page.compression,
                        resolution=page.resolution,
                        resolutionunit=page.resolutionunit,
                        tile=tile,
                        subifds=subifds,
                        metadata=metadata,
                    )

    return


if __name__ == "__main__":
    main()
