#!/usr/bin/env python3
"""
Annotate a cell-by-feature table (MCQuant output) with the ROI classes each cell's centroid falls in.

Adds one boolean column per ROI class (roi_<Class>, as listed in the classes table) and a 'roi_class'
column holding the class of the smallest shape covering the centroid ('none' if outside every shape).
"""

# Written by Patrick Crock
# Version: 0.0.1

import argparse

import numpy as np
import pandas as pd
import tifffile


def main():
    parser = argparse.ArgumentParser(description="Add ROI class columns to a cell-by-feature table.")
    parser.add_argument("--cells", required=True, help="Cell-by-feature csv with X_centroid/Y_centroid columns")
    parser.add_argument("--roi_mask", required=True, help="ROI mask OME-TIFF (channel 0 = ROI, then one channel per class)")
    parser.add_argument("--roi_labels", required=True, help="Primary-class label raster")
    parser.add_argument("--roi_classes", required=True, help="ROI classes table")
    parser.add_argument("--output", required=True, help="Output csv")
    args = parser.parse_args()

    cells = pd.read_csv(args.cells)
    classes = pd.read_csv(args.roi_classes)
    classes["index"] = pd.to_numeric(classes["index"], errors="coerce")
    classes = classes[~classes["excluded"].astype(bool) & (classes["index"] > 0)]

    labels = tifffile.imread(args.roi_labels)
    height, width = labels.shape
    x = np.clip(np.round(cells["X_centroid"].to_numpy()).astype(int), 0, width - 1)
    y = np.clip(np.round(cells["Y_centroid"].to_numpy()).astype(int), 0, height - 1)

    for _, row in classes.iterrows():
        channel = tifffile.imread(args.roi_mask, key=int(row["index"]))
        # TRUE/FALSE is read as logical by R's read.csv and as bool by pandas
        cells[row["column"]] = np.where(channel[y, x] > 0, "TRUE", "FALSE")

    names = {int(row["index"]): row["class"] for _, row in classes.iterrows()}
    cells["roi_class"] = [names.get(int(i), "none") for i in labels[y, x]]

    cells.to_csv(args.output, index=False)
    print(f"Annotated {len(cells)} cells:")
    print(cells["roi_class"].value_counts().to_string())


if __name__ == "__main__":
    main()
