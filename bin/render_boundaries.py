#!/usr/bin/env python

# Written by Niko Thio & Patrick Crock
# Version 0.0.1

import numpy as np
import tifffile
from skimage.segmentation import find_boundaries
import argparse
import os

def instance_mask_to_boundaries(input_path, output_path):
    # Load instance mask image
    instance_mask = tifffile.imread(input_path)

    # Check if 2D or 3D
    if instance_mask.ndim == 2:
        masks = [instance_mask]
    elif instance_mask.ndim == 3:
        masks = instance_mask
    else:
        raise ValueError("Only 2D or 3D instance masks are supported.")

    # Prepare output
    boundary_stack = np.zeros_like(masks, dtype=np.uint8)

    # Process each slice (in case of 3D)
    for i, mask in enumerate(masks):
        boundaries = find_boundaries(mask, mode='outer').astype(np.uint8) * 255
        boundary_stack[i] = boundaries

    # If input was 2D, remove first dimension
    if instance_mask.ndim == 2:
        boundary_stack = boundary_stack[0]

    # Save result
    tifffile.imwrite(output_path, boundary_stack)
    print(f"Saved boundaries to {output_path}")

def create_multichannel_tiff(dapi_path, boundary_path, output_path):
    # Load DAPI image
    dapi = tifffile.imread(dapi_path)
    if dapi.ndim != 2:
        raise ValueError("DAPI image must be a 2D grayscale image.")

    # Load boundary image
    boundary = tifffile.imread(boundary_path)
    if boundary.ndim != 2:
        raise ValueError("Boundary image must be a 2D grayscale image.")

    # Ensure both have the same spatial dimensions
    if dapi.shape != boundary.shape:
        raise ValueError("DAPI and boundary images must have the same dimensions.")

    # Normalize boundary to uint8 if necessary
    if boundary.dtype != np.uint8:
        boundary = (boundary > 0).astype(np.uint8) * 255

    # Stack as (channels, height, width)
    stacked = np.stack([dapi, boundary], axis=0)

    # Save as regular multi-channel TIFF
    tifffile.imwrite(output_path, stacked)
    print(f"Saved multi-channel TIFF to: {output_path}")

def create_rgb_overlay_tiff(dapi_path, boundary_path, output_path):
    dapi = tifffile.imread(dapi_path)
    boundary = tifffile.imread(boundary_path)

    if dapi.shape != boundary.shape:
        raise ValueError("Images must have same dimensions")

    # Percentile normalization - clips extreme values
    p_low, p_high = np.percentile(dapi, [1, 99.5])
    dapi_norm = np.clip((dapi - p_low) / (p_high - p_low) * 255, 0, 255).astype(np.uint8)

    # Create RGB: Blue DAPI + Red boundaries
    rgb = np.zeros((*dapi.shape, 3), dtype=np.uint8)
    rgb[..., 2] = dapi_norm  # Blue channel = DAPI
    rgb[..., 0] = (boundary > 0).astype(np.uint8) * 255  # Red channel = boundaries

    tifffile.imwrite(output_path, rgb, photometric='rgb')
    print(f"Saved rgb TIFF to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combine DAPI and boundary mask into stacked greyscale and overlaid rgb TIFFs.")
    parser.add_argument("--dapi_path", help="Path to 32-bit grayscale DAPI TIFF image")
    parser.add_argument("--mask_path", help="Path to segmentation boundary TIFF image")
    parser.add_argument("--output_prefix", help="Prefix for saved TIFF files")
    args = parser.parse_args()

    boundary_path = f"{args.output_prefix}_temp_boundaries.tiff"
    instance_mask_to_boundaries(args.mask_path, boundary_path)
    print(f"Converted boundary mask to TIFF!")

    output_bw = f"{args.output_prefix}_bw_boundaries.tiff"
    create_multichannel_tiff(args.dapi_path, boundary_path, output_bw)
    print(f"Rendered multichannel grayscale boundary/DAPI TIFF!")

    output_rgb = f"{args.output_prefix}_rgb_boundaries.tiff"
    create_rgb_overlay_tiff(args.dapi_path, boundary_path, output_rgb)
    print(f"Rendered overlaid RGB boundary/DAPI TIFF!")

    os.remove(boundary_path)

