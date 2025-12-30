#!/usr/bin/env python3
"""
OME-TIFF 1:1 Micron-to-Pixel Rescaler
Finds optimal pyramid level and rescales using integer factors to get to 1um/px.
"""

import argparse
import logging
import json
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import numpy as np
import tifffile
from xml.etree import ElementTree as ET


class OMETIFFRescaler:
    """Rescale OME-TIFF to 1:1 micron-to-pixel ratio using optimal pyramid level."""

    def __init__(self, input_path: Path, output_path: Path, target_micron_per_pixel: float = 1.0):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.target_mpp = target_micron_per_pixel
        self.metadata = {}

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def extract_physical_size(self, tif: tifffile.TiffFile) -> Tuple[Optional[float], Optional[float]]:
        """Extract PhysicalSizeX/Y from OME metadata."""
        if not tif.ome_metadata:
            self.logger.warning("No OME metadata found")
            return None, None

        try:
            root = ET.fromstring(tif.ome_metadata)
            ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}

            pixels = root.find('.//ome:Pixels', ns)
            if pixels is not None:
                physical_x = pixels.get('PhysicalSizeX')
                physical_y = pixels.get('PhysicalSizeY')

                if physical_x and physical_y:
                    return float(physical_x), float(physical_y)
        except Exception as e:
            self.logger.error(f"Failed to parse OME metadata: {e}")

        return None, None

    def extract_channel_info(self, tif: tifffile.TiffFile) -> List[str]:
        """Extract channel names from OME metadata."""
        channel_names = []

        if not tif.ome_metadata:
            return channel_names

        try:
            root = ET.fromstring(tif.ome_metadata)
            ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}

            for channel in root.findall('.//ome:Channel', ns):
                channel_names.append(channel.get('Name', ''))
        except Exception as e:
            self.logger.error(f"Failed to parse channel info: {e}")

        return channel_names

    def extract_and_modify_ome_xml(self, new_shape: tuple, new_mpp: float, final_axes: str) -> Optional[str]:
        """Extract OME-XML from input and modify for new dimensions and physical size."""
        with tifffile.TiffFile(self.input_path) as tif:
            if not tif.ome_metadata:
                self.logger.warning("No OME metadata to preserve")
                return None

            try:
                # Register namespace to avoid ns0: prefixes
                ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
                ET.register_namespace('', ns['ome'])

                root = ET.fromstring(tif.ome_metadata)

                pixels = root.find('.//ome:Pixels', ns)
                if pixels is not None:
                    pixels.set('PhysicalSizeX', str(new_mpp))
                    pixels.set('PhysicalSizeY', str(new_mpp))
                    pixels.set('PhysicalSizeXUnit', 'um')
                    pixels.set('PhysicalSizeYUnit', 'um')

                    y_idx = final_axes.index('Y') if 'Y' in final_axes else -2
                    x_idx = final_axes.index('X') if 'X' in final_axes else -1

                    pixels.set('SizeX', str(new_shape[x_idx]))
                    pixels.set('SizeY', str(new_shape[y_idx]))

                    if 'C' in final_axes:
                        c_idx = final_axes.index('C')
                        pixels.set('SizeC', str(new_shape[c_idx]))
                    else:
                        pixels.set('SizeC', '1')

                    channels = pixels.findall('.//ome:Channel', ns)
                    existing_channels = len(channels)
                    expected_channels = len(self.metadata.get("channel_names", []))

                    if expected_channels > 0:
                        if existing_channels != expected_channels:
                            self.logger.warning(f"Adjusting channel count from {existing_channels} to {expected_channels}")
                            for ch in channels:
                                pixels.remove(ch)
                            for i, name in enumerate(self.metadata["channel_names"]):
                                ch_elem = ET.SubElement(
                                    pixels, "Channel",
                                    attrib={"ID": f"Channel:{i}", "Name": name}
                                )
                                ET.SubElement(ch_elem, "LightPath")
                        else:
                            for ch_elem, name in zip(channels, self.metadata["channel_names"]):
                                ch_elem.set("Name", name)

                    if 'Z' in final_axes:
                        z_idx = final_axes.index('Z')
                        pixels.set('SizeZ', str(new_shape[z_idx]))
                    else:
                        pixels.set('SizeZ', '1')

                    if 'T' in final_axes:
                        t_idx = final_axes.index('T')
                        pixels.set('SizeT', str(new_shape[t_idx]))
                    else:
                        pixels.set('SizeT', '1')

                    pixels.set('DimensionOrder', final_axes)

                modified_xml = ET.tostring(root, encoding='unicode')
                self.logger.info(f"Successfully modified OME-XML metadata (DimensionOrder={final_axes})")
                return modified_xml

            except Exception as e:
                self.logger.error(f"Failed to modify OME-XML: {e}")
                return None

    def detect_axes_order(self, ome_axes: Optional[str], shape: Tuple[int, ...]) -> Tuple[str, int, int]:
        """
        Determine the order of axes in the image.
        Priority: Use OME metadata if available, otherwise infer from shape.
        Returns: (axes_string, y_index, x_index)
        """
        if ome_axes:
            axes_upper = ome_axes.upper()
            axes_upper = ''.join(a if a in {'T', 'C', 'Z', 'Y', 'X'} else 'C' for a in axes_upper)
            y_idx = axes_upper.find('Y')
            x_idx = axes_upper.find('X')
            if y_idx != -1 and x_idx != -1:
                self.logger.info(f"Using OME-declared axes: {axes_upper}")
                return axes_upper, y_idx, x_idx
            self.logger.warning(f"OME axes provided ({ome_axes}) but missing Y or X — falling back to heuristic.")

        ndim = len(shape)
        if ndim == 2:
            return "YX", 0, 1
        elif ndim == 3:
            if shape[-1] in (3, 4):
                return "YXC", 0, 1
            return "ZYX", 1, 2
        elif ndim == 4:
            return "CZYX", 2, 3
        elif ndim == 5:
            return "TCZYX", 3, 4

        self.logger.warning(f"Unexpected image dimensions: {shape}")
        return "YX", -2, -1

    def analyze_pyramid_scales(self) -> Dict[str, Any]:
        """Analyze pyramid levels and their effective scales."""
        self.logger.info(f"Analyzing {self.input_path}")

        pyramid_info = {
            'levels': [],
            'physical_size_x': None,
            'physical_size_y': None,
            'channel_names': [],
            'optimal_level': None
        }

        with tifffile.TiffFile(self.input_path) as tif:
            physical_x, physical_y = self.extract_physical_size(tif)
            pyramid_info['physical_size_x'] = physical_x
            pyramid_info['physical_size_y'] = physical_y

            channel_names = self.extract_channel_info(tif)
            pyramid_info['channel_names'] = channel_names

            if physical_x is None:
                raise ValueError("Cannot extract PhysicalSizeX from OME metadata")

            self.logger.info(f"Base PhysicalSizeX: {physical_x} µm/pixel")

            series = tif.series[0]

            ### NOTE: forcing to use series0, since the assumption of existing pyramid image with 2X scaling is not always met, it could use 4X or others, 
            ###       so proper fix would need to calculate scale factor from the series dimension directly.
            ###
            ### if len(tif.series) > 1:
            ###    levels_to_check = [(i, s) for i, s in enumerate(tif.series)]
            ### elif hasattr(series, 'levels') and series.levels:
            ###    levels_to_check = [(i, level) for i, level in enumerate(series.levels)]
            ### else:

            levels_to_check = [(0, series)]

            for level_idx, level in levels_to_check:
                scale_factor = 2 ** level_idx
                effective_mpp = physical_x * scale_factor
                ratio = self.target_mpp / effective_mpp
                integer_scale = int(np.floor(ratio + 0.5))
                final_mpp = effective_mpp * integer_scale

                ome_axes = level.axes if hasattr(level, 'axes') else (series.axes if hasattr(series, 'axes') else '')
                detected_axes, y_idx, x_idx = self.detect_axes_order(ome_axes, level.shape)

                level_info = {
                    'level': level_idx,
                    'shape': level.shape,
                    'dtype': getattr(level, 'dtype', None),
                    'axes': detected_axes,
                    'y_index': y_idx,
                    'x_index': x_idx,
                    'scale_factor': scale_factor,
                    'effective_mpp': effective_mpp,
                    'additional_scale_integer': integer_scale,
                    'final_mpp': final_mpp,
                    'scale_error': abs(final_mpp - self.target_mpp)
                }

                pyramid_info['levels'].append(level_info)

                self.logger.info(
                    f"Level {level_idx}: shape={level.shape}, axes={detected_axes}, "
                    f"scale={scale_factor}x, effective_mpp={effective_mpp:.4f}, "
                    f"int_scale_needed={integer_scale}, final_mpp={final_mpp:.4f}"
                )

        best_level = self._select_optimal_level(pyramid_info['levels'])
        pyramid_info['optimal_level'] = best_level

        self.metadata = pyramid_info
        return pyramid_info
        
    def _select_optimal_level(self, levels: List[Dict]) -> int:
        """Select optimal pyramid level balancing error and scaling requirements."""

        acceptable_threshold = 0.15  # 0.15 µm/pixel max error

        best_level = 0
        best_error = float('inf')
        best_requires_scaling = True

        for level_info in levels:
            error = level_info['scale_error']
            needs_scaling = level_info['additional_scale_integer'] != 1
            level = level_info['level']

            # Skip levels with zero or invalid scaling
            if level_info['additional_scale_integer'] == 0:
                continue

            # If error is within acceptable threshold and no scaling needed, use it immediately
            if error <= acceptable_threshold and not needs_scaling:
                self.logger.info(
                    f"Level {level} needs no scaling and error "
                    f"({error:.4f}) within threshold ({acceptable_threshold})"
                )
                return level

            # Determine if this level is better
            is_better = False

            if error < best_error - 0.1:  # Significantly better error
                is_better = True
            elif abs(error - best_error) < 0.1:  # Similar error (within 0.1)
                # When errors are similar, prefer:
                # 1. No scaling over scaling
                # 2. Higher pyramid level (smaller data, faster)
                if not needs_scaling and best_requires_scaling:
                    is_better = True
                elif needs_scaling == best_requires_scaling:
                    # Both need scaling or both don't - prefer higher level
                    is_better = level > best_level

            if is_better:
                best_error = error
                best_level = level
                best_requires_scaling = needs_scaling

        scaling_msg = "scaling required" if best_requires_scaling else "no scaling needed"
        self.logger.info(
            f"Selected level {best_level} ({scaling_msg}, error={best_error:.4f} µm/pixel)"
        )
        return best_level

    def extract_and_rescale(self) -> np.ndarray:
        """Extract optimal level and rescale to target if needed."""
        if not self.metadata:
            self.analyze_pyramid_scales()

        optimal_level = self.metadata['optimal_level']
        level_info = self.metadata['levels'][optimal_level]
        integer_scale = level_info['additional_scale_integer']

        self.logger.info(f"Extracting level {optimal_level}")

        with tifffile.TiffFile(self.input_path) as tif:
            series = tif.series[0]

            if len(tif.series) > 1 and optimal_level < len(tif.series):
                data = tif.series[optimal_level].asarray()
            elif hasattr(series, 'levels') and series.levels and optimal_level < len(series.levels):
                data = series.levels[optimal_level].asarray()
            else:
                data = series.asarray()

        self.logger.info(f"Extracted shape: {data.shape}, dtype: {data.dtype}")

        if integer_scale == 1:
            self.logger.info("No rescaling needed (scale factor = 1)")
            return data

        self.logger.info(f"Downsampling by integer factor {integer_scale}")
        data = self._downsample_integer(
            data,
            integer_scale,
            level_info['y_index'],
            level_info['x_index']
        )

        return data

    def _downsample_integer(self, data: np.ndarray, factor: int, y_idx: int, x_idx: int) -> np.ndarray:
        """Downsample by integer factor using block averaging for spatial dims only."""
        if factor == 1:
            return data

        self.logger.info(f"Downsampling with factor={factor}, Y={y_idx}, X={x_idx}")

        shape = list(data.shape)
        new_y = shape[y_idx] // factor
        new_x = shape[x_idx] // factor
        crop_y = new_y * factor
        crop_x = new_x * factor

        slices = [slice(None)] * len(shape)
        slices[y_idx] = slice(0, crop_y)
        slices[x_idx] = slice(0, crop_x)
        data_cropped = data[tuple(slices)]

        reshape_dims = []
        for i, dim_size in enumerate(data_cropped.shape):
            if i == y_idx:
                reshape_dims.extend([new_y, factor])
            elif i == x_idx:
                reshape_dims.extend([new_x, factor])
            else:
                reshape_dims.append(dim_size)

        data_reshaped = data_cropped.reshape(reshape_dims)

        axes_to_average = []
        offset = 0
        for i in range(len(data_cropped.shape)):
            if i == y_idx or i == x_idx:
                axes_to_average.append(i + offset + 1)
                offset += 1

        self.logger.info(f"Averaging over axes: {axes_to_average}")
        data_downsampled = data_reshaped.mean(axis=tuple(axes_to_average))

        if data.dtype in [np.uint8, np.uint16, np.uint32]:
            data_downsampled = np.round(data_downsampled).astype(data.dtype)

        self.logger.info(f"Downsampled shape: {data_downsampled.shape}")
        return data_downsampled

    def save_output(self, data: np.ndarray):
        """Save rescaled image with corrected metadata."""
        level_info = self.metadata['levels'][self.metadata['optimal_level']]
        final_mpp = level_info['final_mpp']
        original_axes = level_info['axes']

        self.logger.info(f"Final PhysicalSize: {final_mpp:.4f} µm/pixel")
        self.logger.info(f"Original axes: {original_axes}, shape: {data.shape}")

        normalized_axes = original_axes
        if original_axes == 'YXC':
            self.logger.info("Transposing YXC -> CYX for OME-TIFF compliance")
            data = np.moveaxis(data, -1, 0)
            normalized_axes = 'CYX'
        elif original_axes == 'YX':
            self.logger.info("Adding channel dimension: YX -> CYX")
            data = data[np.newaxis, ...]
            normalized_axes = 'CYX'

        self.logger.info(f"Final shape after normalization: {data.shape}, axes: {normalized_axes}")

        ome_xml = self.extract_and_modify_ome_xml(data.shape, final_mpp, normalized_axes)

        estimated_size = data.nbytes
        use_bigtiff = estimated_size > 3.5 * (1024**3)

        self.logger.info(f"Saving to {self.output_path}")
        self.logger.info(f"Output shape: {data.shape}, size: {estimated_size/(1024**3):.2f}GB")

        self.logger.info(f"Writing OME-TIFF with axes='{normalized_axes}'")

        tifffile.imwrite(
            self.output_path,
            data,
            photometric='minisblack',
            compression='deflate',
            compressionargs={'level': 6},
            tile=(256, 256),
            bigtiff=use_bigtiff,
            description=ome_xml,
            metadata={'axes': 'CYX'},
        )

        metadata_path = self.output_path.with_suffix('.json')
        with open(metadata_path, 'w') as f:
            json.dump({
                'original_file': str(self.input_path),
                'original_physical_size_x': self.metadata['physical_size_x'],
                'original_physical_size_y': self.metadata['physical_size_y'],
                'pyramid_level_used': self.metadata['optimal_level'],
                'pyramid_scale_factor': level_info['scale_factor'],
                'integer_scale_applied': level_info['additional_scale_integer'],
                'final_physical_size_x': final_mpp,
                'final_physical_size_y': final_mpp,
                'target_micron_per_pixel': self.target_mpp,
                'output_shape': list(data.shape),
                'output_axes': normalized_axes,
                'original_axes': original_axes,
                'channel_names': self.metadata.get('channel_names', [])
            }, f, indent=2)

        self.logger.info(f"Metadata saved to {metadata_path}")

    def process(self) -> Path:
        """Main processing pipeline."""
        try:

            self.analyze_pyramid_scales()
            data = self.extract_and_rescale()
            self.save_output(data)

            self.logger.info("Processing complete")
            return self.output_path

        except Exception as e:
            self.logger.error(f"Processing failed: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(
        description='Rescale OME-TIFF to 1:1 micron-to-pixel ratio using optimal pyramid level'
    )
    parser.add_argument('input', type=Path, help='Input OME-TIFF file')
    parser.add_argument('--prefix', type=str, required=True, help='Output file prefix')
    parser.add_argument(
        '--target-mpp',
        type=float,
        default=1.0,
        help='Target microns per pixel (default: 1.0)'
    )
    parser.add_argument(
        '--analyze-only',
        action='store_true',
        help='Only analyze pyramid structure'
    )

    args = parser.parse_args()

    output_path = Path(f"{args.prefix}.downscaled.ome.tiff")
    rescaler = OMETIFFRescaler(args.input, output_path, args.target_mpp)

    if args.analyze_only:
        info = rescaler.analyze_pyramid_scales()
        print(f"\nPyramid Analysis for {args.input}:")
        print(f"Base PhysicalSizeX: {info['physical_size_x']} µm/pixel")
        print(f"Target: {args.target_mpp} µm/pixel")
        print(f"\nLevels:")
        for level in info['levels']:
            print(f"  Level {level['level']}:")
            print(f"    Shape: {level['shape']}, Axes: {level['axes']}")
            print(f"    Effective MPP: {level['effective_mpp']:.4f}")
            print(f"    Integer scale needed: {level['additional_scale_integer']}")
            print(f"    Final MPP: {level['final_mpp']:.4f}")
        print(f"\nOptimal level: {info['optimal_level']}")
    else:
        output_path = rescaler.process()
        print(f"Successfully created rescaled image: {output_path}")


if __name__ == '__main__':
    main()
