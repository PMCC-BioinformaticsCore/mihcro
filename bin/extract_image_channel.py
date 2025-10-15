#!/usr/bin/env python

# Written by Song Li & Patrick Crock
# Version 0.0.3 - Made extraction robust to dimension order
import sys, os
import argparse
import xml.etree.ElementTree as ET
import skimage.io
import tifffile
import numpy as np

def extract_channel(xml, channel_name):
    tree = ET.parse(xml)
    root = tree.getroot()

    # Handle namespace
    ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
    channels = root.findall('.//ome:Channel', ns)

    channel_name_upper = channel_name.upper()

    for i, channel in enumerate(channels):
        name = channel.get('Name', '').upper()
        if channel_name_upper in name:
            return i  # Return the channel index directly

    return None

def save_channel_image(ch, img_path, out_path):
    with tifffile.TiffFile(img_path) as tif:
        arr = tif.asarray()
        axes = tif.series[0].axes
        print("Array shape:", arr.shape, "Axes:", axes)

    if "C" in axes:
        c_index = axes.index("C")
    elif "S" in axes:
        c_index = axes.index("S")
    else:
        raise RuntimeError(f"No channel axis in axes string {axes}")

    # move channel axis to last for consistency
    arr = np.moveaxis(arr, c_index, -1)

    if ch >= arr.shape[-1]:
        print(f"Error: Channel {ch} not found, image has {arr.shape[-1]} channels")
        sys.exit(os.EX_SOFTWARE)

    channel = arr[..., ch]
    skimage.io.imsave(out_path, channel)

def main():
    parser = argparse.ArgumentParser(description="Extract channel from image")
    parser.add_argument("-o", "--output", type=str, required=True, help="Output .tif file for extracted channel")
    parser.add_argument("-i", "--image", type=str, required=True, help="Input .tif image")
    parser.add_argument("-x", "--xml", type=str, required=True, help="Metadata .xml for .tif image")
    parser.add_argument("-c", "--channel", type=str, default='DAPI', help="Channel name to extract")

    args = parser.parse_args()
    channel_extracted = extract_channel(args.xml, args.channel)

    if channel_extracted is not None:
        save_channel_image(channel_extracted, args.image, args.output)
        print(f"Successfully extracted channel {channel_extracted} ({args.channel}) to {args.output}")
    else:
        print(f"{args.channel} channel could not be found")
        sys.exit(os.EX_SOFTWARE)

    return

if __name__ == "__main__":
    main()
