# nf-core/mihcro: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.1.0dev - [date]

First update to nfcore/microscopy.

### `Added`

* Selection of segmentation method as a parameter.
* Altered workflow to handle pre-stitched or legacy HALO tiff inputs.
* Added a downscaling step which reduces resolution to 1px/um for faster segmentation.
* Expanded README and added a metro diagram.

### `Fixed`

* Fixed a bug where warnings were exported into tiff metadata xml.

### `Dependencies`

### `Deprecated`
