#!/usr/bin/env python

# Written by Song Li & Patrick Crock
# Version 0.0.2 - Fixed critical bugs
import sys, os
import argparse
import xml.etree.ElementTree as ET
import skimage.io

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
    img = skimage.io.imread(img_path)

    # Ensure we have the right number of dimensions
    if len(img.shape) < 3:
        print(f"Error: Image has only {len(img.shape)} dimensions, expected at least 3")
        sys.exit(os.EX_SOFTWARE)

    if ch >= img.shape[2]:
        print(f"Error: Channel {ch} not found, image has {img.shape[2]} channels")
        sys.exit(os.EX_SOFTWARE)

    channel = img[:, :, ch]  # Extract the correct channel
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
