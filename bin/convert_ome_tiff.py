#!/usr/bin/env python

# Written by Song Li & Patrick Crock
# Version: 0.0.2 Changed default order to match upstream outputs.

import argparse
import tifffile
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET

def main():
    parser = argparse.ArgumentParser(description="Extract channel from image")
    parser.add_argument("-m", "--markers", type=str, required=True, help="Marker list from markerfile for markers to keep in image")
    parser.add_argument("-o", "--output", type=str, required=True, help="Output .tif file for extracted channel")
    parser.add_argument("-i", "--image", type=str, required=True, help="Input .tif image")
    parser.add_argument("--order", type=str, default='0,1,2', help="Transpose dimensions, assuming X,Y,C input dimension order")

    args = parser.parse_args()

    img = tifffile.imread(args.image)

    with tifffile.TiffFile(args.image) as tif:
        ome_xml = tif.ome_metadata

    root = ET.fromstring(ome_xml)
    ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
    channels = root.findall('.//ome:Channel', ns)

    markerfile = pd.read_csv(args.markers).marker_name

    channel_indices = []

    for channel_name in markerfile:
        channel_name_upper = channel_name.upper()
        matches = []

        for i, channel in enumerate(channels):
            name = channel.get('Name', '').upper()
            if channel_name_upper in name:
                matches.append((i, name))

        if len(matches) == 0:
            print(f"Warning: Channel '{channel_name}' not found")
        elif len(matches) > 1:
            print(f"Warning: '{channel_name}' matched multiple channels: {[m[1] for m in matches]}, using first")
            channel_indices.append(matches[0][0])
        else:
            channel_indices.append(matches[0][0])

    order = [int(item) for item in args.order.split(',')]
    img_transposed = np.transpose(img, order)
    img_out = img_transposed[channel_indices]

    tifffile.imwrite(args.output, img_out, photometric='minisblack')


if __name__ == "__main__":
    main()
