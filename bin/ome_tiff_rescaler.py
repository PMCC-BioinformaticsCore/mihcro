#!/usr/bin/env python3
"""
OME-TIFF 1:1 Micron-to-Pixel Rescaler
Finds optimal pyramid level and rescales using integer factors to get to 1um/px.
Input is assumed to be CYX.
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

        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    def extract_physical_size(self, tif: tifffile.TiffFile) -> Tuple[Optional[float], Optional[float]]:
        if not tif.ome_metadata:
            self.logger.warning("No OME metadata found")
            return None, None
        try:
            ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
            root = ET.fromstring(tif.ome_metadata)
            pixels = root.find('.//ome:Pixels', ns)
            if pixels is not None:
                physical_x = pixels.get('PhysicalSizeX')
                physical_y = pixels.get('PhysicalSizeY')
                if physical_x and physical_y:
                    return float(physical_x), float(physical_y)
        except Exception as e:
            self.logger.error(f"Failed to parse OME metadata: {e}")
        return None, None

    def extract_and_modify_ome_xml(self, new_shape: tuple, new_mpp: float) -> Optional[str]:
        with tifffile.TiffFile(self.input_path) as tif:
            if not tif.ome_metadata:
                self.logger.warning("No OME metadata to preserve")
                return None
            try:
                ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
                ET.register_namespace('', ns['ome'])
                root = ET.fromstring(tif.ome_metadata)
                pixels = root.find('.//ome:Pixels', ns)
                if pixels is not None:
                    pixels.set('PhysicalSizeX', str(new_mpp))
                    pixels.set('PhysicalSizeY', str(new_mpp))
                    pixels.set('PhysicalSizeXUnit', 'um')
                    pixels.set('PhysicalSizeYUnit', 'um')
                    pixels.set('SizeX', str(new_shape[2]))  # CYX: X is always index 2
                    pixels.set('SizeY', str(new_shape[1]))  # CYX: Y is always index 1
                    pixels.set('SizeC', str(new_shape[0]))  # CYX: C is always index 0
                    pixels.set('SizeZ', '1')
                    pixels.set('SizeT', '1')
                    pixels.set('DimensionOrder', 'CYX')
                modified_xml = ET.tostring(root, encoding='unicode')
                self.logger.info("Successfully modified OME-XML metadata")
                return modified_xml
            except Exception as e:
                self.logger.error(f"Failed to modify OME-XML: {e}")
                return None

    def analyze_pyramid_scales(self) -> Dict[str, Any]:
        self.logger.info(f"Analyzing {self.input_path}")

        pyramid_info = {
            'levels': [],
            'physical_size_x': None,
            'physical_size_y': None,
            'optimal_level': None
        }

        # Input is always CYX — y_idx=1, x_idx=2
        y_idx, x_idx = 1, 2

        with tifffile.TiffFile(self.input_path) as tif:
            physical_x, physical_y = self.extract_physical_size(tif)
            pyramid_info['physical_size_x'] = physical_x
            pyramid_info['physical_size_y'] = physical_y

            if physical_x is None:
                raise ValueError("Cannot extract PhysicalSizeX from OME metadata")

            self.logger.info(f"Base PhysicalSizeX: {physical_x} µm/pixel")

            series = tif.series[0]
            base_size_x = series.shape[x_idx]

            if len(tif.series) > 1:
                levels_to_check = [(i, s) for i, s in enumerate(tif.series)]
            elif hasattr(series, 'levels') and series.levels:
                levels_to_check = [(i, level) for i, level in enumerate(series.levels)]
            else:
                levels_to_check = [(0, series)]

            for level_idx, level in levels_to_check:
                scale_factor = int(np.floor(base_size_x / level.shape[x_idx] + 0.5))
                effective_mpp = physical_x * scale_factor
                ratio = self.target_mpp / effective_mpp
                integer_scale = int(np.floor(ratio + 0.5))
                final_mpp = effective_mpp * integer_scale

                level_info = {
                    'level': level_idx,
                    'shape': level.shape,
                    'dtype': getattr(level, 'dtype', None),
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
                    f"Level {level_idx}: shape={level.shape}, scale={scale_factor}x, "
                    f"effective_mpp={effective_mpp:.4f}, int_scale={integer_scale}, final_mpp={final_mpp:.4f}"
                )

        best_level = self._select_optimal_level(pyramid_info['levels'])
        pyramid_info['optimal_level'] = best_level
        self.metadata = pyramid_info
        return pyramid_info

    def _select_optimal_level(self, levels: List[Dict]) -> int:
        acceptable_threshold = 0.15

        best_level = 0
        best_error = float('inf')
        best_requires_scaling = True

        for level_info in levels:
            error = level_info['scale_error']
            needs_scaling = level_info['additional_scale_integer'] != 1
            level = level_info['level']

            if level_info['additional_scale_integer'] == 0:
                continue

            if error <= acceptable_threshold and not needs_scaling:
                self.logger.info(f"Level {level} needs no scaling and error ({error:.4f}) within threshold")
                return level

            is_better = False
            if error < best_error - 0.1:
                is_better = True
            elif abs(error - best_error) < 0.1:
                if not needs_scaling and best_requires_scaling:
                    is_better = True
                elif needs_scaling == best_requires_scaling:
                    is_better = level > best_level

            if is_better:
                best_error = error
                best_level = level
                best_requires_scaling = needs_scaling

        self.logger.info(
            f"Selected level {best_level} "
            f"({'scaling required' if best_requires_scaling else 'no scaling needed'}, error={best_error:.4f})"
        )
        return best_level

    def extract_and_rescale(self) -> np.ndarray:
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
        return self._downsample_integer(data, integer_scale, level_info['y_index'], level_info['x_index'])

    def _downsample_integer(self, data: np.ndarray, factor: int, y_idx: int, x_idx: int) -> np.ndarray:
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
        level_info = self.metadata['levels'][self.metadata['optimal_level']]
        final_mpp = level_info['final_mpp']

        self.logger.info(f"Output shape: {data.shape}, axes: CYX, PhysicalSize: {final_mpp:.4f} µm/pixel")

        ome_xml = self.extract_and_modify_ome_xml(data.shape, final_mpp)
        use_bigtiff = data.nbytes > 3.5 * (1024**3)

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
                'output_axes': 'CYX',
            }, f, indent=2)

        self.logger.info(f"Metadata saved to {metadata_path}")

    def process(self) -> Path:
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
    parser.add_argument('--target-mpp', type=float, default=1.0, help='Target microns per pixel (default: 1.0)')
    parser.add_argument('--analyze-only', action='store_true', help='Only analyze pyramid structure')

    args = parser.parse_args()

    output_path = Path(f"{args.prefix}.downscaled.ome.tiff")
    rescaler = OMETIFFRescaler(args.input, output_path, args.target_mpp)

    if args.analyze_only:
        info = rescaler.analyze_pyramid_scales()
        print(f"\nPyramid Analysis for {args.input}:")
        print(f"Base PhysicalSizeX: {info['physical_size_x']} µm/pixel")
        print(f"Target: {args.target_mpp} µm/pixel")
        for level in info['levels']:
            print(f"  Level {level['level']}: shape={level['shape']}, "
                  f"effective_mpp={level['effective_mpp']:.4f}, "
                  f"int_scale={level['additional_scale_integer']}, final_mpp={level['final_mpp']:.4f}")
        print(f"Optimal level: {info['optimal_level']}")
    else:
        output_path = rescaler.process()
        print(f"Successfully created rescaled image: {output_path}")


if __name__ == '__main__':
    main()
