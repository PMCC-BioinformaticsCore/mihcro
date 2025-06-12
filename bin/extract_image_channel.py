#!/usr/bin/env python

# Written by Song Li
# Version 0.0.1

import sys, os
import argparse
import xmltodict
import skimage

def extract_channel(xml, channel_name):
    with open(xml, 'r') as file:
        xml_str = file.read()

    xml_dict = xmltodict.parse(xml_str, attr_prefix='', cdata_key='')
    channels = xml_dict['OME']['Image']['Pixels']['Channel'] 

    for channel in channels:
        if channel_name in channel['Name'].upper():
            ch_extracted = channel['ID']
            ch_extracted = ch_extracted.split(':')[-1]

            return int(ch_extracted) 

    return 

def save_channel_image(ch, img_path, out_path):
    img = skimage.io.imread(img_path)
    channel = img[:,:,3]
    skimage.io.imsave(out_path, channel)

def main():
    parser = argparse.ArgumentParser(description="Extract channel from image")
    parser.add_argument("-o", "--output", type=str, required=True, help="Output .tif file for extracted channel")
    parser.add_argument("-i", "--image", type=str, required=True, help="Input .tif image")
    parser.add_argument("-x", "--xml", type=str, required=True, help="Metadata .xml for .tif image")
    parser.add_argument("-c", "--channel", type=str, default='DAPI', help="Channel name to extract")
    
    args = parser.parse_args()

    channel_extracted = extract_channel(args.xml, args.channel)

    if channel_extracted:
        save_channel_image(channel_extracted, args.image, args.output)
    else:
        print(f"{args.channel} channel could not be found")
        sys.exit(os.EX_SOFTWARE)

    return


if __name__ == "__main__":
    main()