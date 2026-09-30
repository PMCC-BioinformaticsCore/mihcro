# nf-core/mihcro: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.4.0dev - [date]

Major update to nfcore/microscopy. Added ROI specification, and patch-wise segmentation for better performance.

### `Added`

* Patch-based segmentation adapted from [sopa](https://github.com/prism-oncology/sopa):
  * Images are split into overlapping patches (`--patch_size`, `--patch_overlap`).
  * Mesmer or Cellpose runs on each patch as a separate task.
  * Patch masks are resolved into one label mask; duplicated cells are merged with `--patch_merge_threshold`.
* Regions of interest from QuPath-exported GeoJSON, given in a new optional `roi` samplesheet column:
  * Only patches touching the shapes are segmented, and cells outside the shapes are removed.
  * `Ignore*` shapes are excluded (`--roi_exclude_classes`).
  * Annotation classes are added to the cell table (`roi_<Class>`, `roi_class`) and summarised in the QC report.
  * ROI masks are published in `<sample>/roi/` for downstream masking.
* Automatic tissue detection for samples without a GeoJSON, so background patches are skipped (`--tissue_detection`).
* ROI outline drawn in green on the RGB segmentation overlay.
* Optional GPU acceleration for Cellpose with `-profile gpu` (`--use_gpu`, one GPU per patch task).

### `Changed`

* Image preparation is now a single `PREPROCESS_IMAGE` step: it reads the closest pyramid level of the input and only the needed channels, downsamples, and writes the processed image, OME-XML, scale metadata and the nuclear / membrane / AF channels in one pass. This replaces `DOWNSCALE_OME_TIFF`, `BFTOOLS_TIFFMETAXML` and `EXTRACT_DAPI` / `EXTRACT_AF` / `EXTRACT_MEMBRANE`, and no longer writes a full-resolution intermediate image. Output files are unchanged, except `metadata/` no longer holds a duplicate copy of the processed image.
* The nuclear, membrane and AF channels no longer need to be listed in the markerfile.
* `PREPROCESS_CELLPOSE` removed: for two-channel Cellpose, `MAKE_PATCHES` writes each patch as `[membrane, nuclear]`.
* Stitched/fused inputs are checked to be a single TIFF during samplesheet validation.
* `RESOLVE_PATCHES` requests 1 CPU / 16 GB instead of `process_medium`.

### `Fixed`

* Nuclear/membrane images (Mesmer, Cellpose preprocessing) and DAPI/mask pairs (segmentation rendering) are now matched by sample id rather than by channel order, which could mismatch samples in multi-sample runs.

### `Dependencies`

### `Deprecated`
