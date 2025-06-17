#!/usr/bin/env python

# Written by Song Li
# Version: 0.0.1

import argparse
import tifffile
import numpy as np

def main():
    parser = argparse.ArgumentParser(description="Extract channel from image")
    parser.add_argument("-o", "--output", type=str, required=True, help="Output .tif file for extracted channel")
    parser.add_argument("-i", "--image", type=str, required=True, help="Input .tif image")
    parser.add_argument("--order", type=str, default='2,0,1', help="Transpose dimensions, assuming Y,X,C input dimension order")
    
    args = parser.parse_args()

    img = tifffile.imread(args.image)

    # Transpose (Y, X, C) -> (C, Y, X)
    order = args.order.split(',')
    order = [int(item) for item in order]
    img_cyx = np.transpose(img, order)

    # Write each channel as a separate page
    tifffile.imwrite(args.output, img_cyx, photometric='minisblack')

    return


if __name__ == "__main__":
    main()