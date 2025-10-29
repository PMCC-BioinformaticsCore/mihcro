#!/usr/bin/env python

# Written by Elora Qing Siaw & Patrick Crock
# Version: 0.0.1

import argparse
import tifffile
import numpy as np
from skimage.filters import threshold_otsu, gaussian  # ADD gaussian import
from skimage.restoration import rolling_ball
import matplotlib.pyplot as plt
from typing import Optional, Tuple  # ADD type hints


def remove_background_gaussian(img: np.ndarray, sigma: float) -> np.ndarray:
    background = gaussian(img, sigma=sigma)
    img_bg_subtracted = img - background
    return np.clip(img_bg_subtracted, 0, None)

def remove_background_rollingball(img: np.ndarray, radius: int) -> np.ndarray:
    background = rolling_ball(img, radius=radius)
    img_bg_subtracted = img - background
    return np.clip(img_bg_subtracted, 0, None)

def remove_background_af(img: np.ndarray, af_img: np.ndarray) -> np.ndarray:
    if img.shape != af_img.shape:
        raise ValueError(f"Shape mismatch: DAPI {img.shape} vs AF {af_img.shape}")

    newimg = np.clip(img - af_img, 0, None)
    # Check if image has any valid data
    if np.all(newimg == 0):
        raise ValueError("DAPI channel contains only zeros after AF subtraction")

    return newimg

def remove_background_mean(img: np.ndarray) -> np.ndarray:  # REMOVE af_img parameter
    background = np.mean(img)
    print(f"Background (mean): {background}")  # FIX print statement
    img_bg_subtracted = img - background
    return np.clip(img_bg_subtracted, 0, None)

def apply_otsu_threshold(img: np.ndarray, leniency: float = 0.0) -> Tuple[np.ndarray, float, float]:  # ADD return type
    thresh = threshold_otsu(img)
    print(f"Otsu threshold value: {thresh}")  # FIX print statement
    adjusted_thresh = thresh * (1 - leniency)
    print(f"Adjusted Otsu threshold value: {adjusted_thresh}")  # FIX print statement
    binary = (img > adjusted_thresh).astype(np.uint8) * 255
    return binary, thresh, adjusted_thresh

def save_diagnostic_png(
    pre_binary: np.ndarray,
    post_binary: np.ndarray,
    otsu_thresh: float,
    adjusted_thresh: float,
    output_path: str
):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    axes[0].imshow(pre_binary, cmap='gray')
    axes[0].set_title('Pre-binarisation')
    axes[0].axis('off')

    axes[1].imshow(post_binary, cmap='gray')
    axes[1].set_title('Post-binarisation')
    axes[1].axis('off')

    axes[2].hist(pre_binary.ravel(), bins=256, color='gray', alpha=0.7)
    axes[2].axvline(otsu_thresh, color='red', linestyle='--', linewidth=2, label=f'Otsu: {otsu_thresh:.2f}')
    axes[2].axvline(adjusted_thresh, color='blue', linestyle='-', linewidth=2, label=f'Adjusted: {adjusted_thresh:.2f}')
    axes[2].set_xlabel('Pixel Intensity')
    axes[2].set_ylabel('Frequency')
    axes[2].set_title('Histogram with Thresholds')
    axes[2].legend()
    axes[2].set_yscale('log')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved diagnostic PNG to {output_path}")

def process_dapi(
    img: np.ndarray,
    method: str,
    sigma: Optional[float] = None,
    radius: Optional[int] = None,
    af_img: Optional[np.ndarray] = None,
    leniency: float = 0.0
) -> Tuple[np.ndarray, np.ndarray, float, float]:  # ADD return type

    # Clean data: remove NaN and Inf values
    if np.any(~np.isfinite(img)):
        print(f"Warning: Found {np.sum(~np.isfinite(img))} non-finite values (NaN/Inf), replacing with 0")
        img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)

    # Check if image has any valid data
    if np.all(img == 0):
        raise ValueError("Image contains only zeros after cleaning non-finite values")

    if method == "otsu_only":
        processed = img

    elif method == "gaussian":
        if sigma is None:
            raise ValueError("--sigma required for gaussian method")
        processed = remove_background_gaussian(img, sigma)

    elif method == "rollingball":
        if radius is None:
            raise ValueError("--radius required for rollingball method")
        processed = remove_background_rollingball(img, radius)  # FIX typo: imgprocessed -> processed

    elif method == "af":
        if af_img is None:
            raise ValueError("--af_image required for af method")
        processed = remove_background_af(img, af_img)

    elif method == "mean":
        processed = remove_background_mean(img)  # REMOVE af_img argument

    else:
        raise ValueError(f"Unknown method: {method}")

    binary, otsu_thresh, adjusted_thresh = apply_otsu_threshold(processed, leniency)
    return binary, processed, otsu_thresh, adjusted_thresh

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply background removal/otsu thresholding to extracted DAPI channel.")
    parser.add_argument("-i", "--input_dapi", type=str, required=True, help="Path to 32-bit grayscale DAPI TIFF image.")
    parser.add_argument("-o", "--output", type=str, required=True, help="Output thresholded .tif image.")
    parser.add_argument("-m", "--method", type=str, required=True, choices=["gaussian", "rollingball", "af", "mean", "otsu_only"],  # ADD choices
                        help="Method for background removal.")
    parser.add_argument("-s", "--sigma", type=float, required=False, help="Sigma parameter for gaussian method.")
    parser.add_argument("-r", "--radius", type=int, required=False, help="Radius parameter for rollingball method.")
    parser.add_argument("-a", "--af_image", type=str, required=False, help="Autofluorescence .tif image for AF method.")
    parser.add_argument("-l", "--leniency", type=float, default=0.0, required=False,
                        help="Leniency parameter for threshold adjustment. (-1 to 1, negative = stricter)")
    parser.add_argument("-p", "--png_output", type=str, required=True, help="Optional diagnostic PNG output path.")

    args = parser.parse_args()

    img = tifffile.imread(args.input_dapi)

    print(f"Image shape: {img.shape}, dtype: {img.dtype}")

    af_img = None
    if args.af_image:
        af_img = tifffile.imread(args.af_image)
        print(f"AF image shape: {af_img.shape}, dtype: {af_img.dtype}")

    binary, processed, otsu_thresh, adjusted_thresh = process_dapi(
        img=img,
        method=args.method,
        sigma=args.sigma,
        radius=args.radius,
        af_img=af_img,
        leniency=args.leniency
    )

    tifffile.imwrite(args.output, binary)
    print(f"Saved binarised image to {args.output}")
    print(f"Otsu threshold: {otsu_thresh:.2f}, Adjusted threshold: {adjusted_thresh:.2f}")

    save_diagnostic_png(processed, binary, otsu_thresh, adjusted_thresh, args.png_output)
