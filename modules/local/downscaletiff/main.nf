process DOWNSCALE_OME_TIFF {
    tag "$meta.id"
    label 'process_medium'

    conda "${moduleDir}/environment.yml"
    container "ghcr.io/patrickcrock/bftools_tifffile:latest"

    input:
    tuple val(meta), path(ome_tiff)

    output:
    tuple val(meta), path("*.downscaled.ome.tiff"), emit: downscaled
    tuple val(meta), path("*.json"), emit: metadata
    path "versions.yml", emit: versions

    script:
    def prefix = task.ext.prefix ?: "${meta.id}"
    def BFTOOLS_VERSION='8.0.0' // Edit bftools versions manually
    """
    export _JAVA_OPTIONS="-Xmx${task.memory.toMega()}m"
    # Step 0: Calculate scale to achieve 1:1 micron to pixel ratio
    origScale=\$(tiffcomment ${ome_tiff} | grep -o 'PhysicalSizeX="[^"]*"' | head -n1 | sed 's/PhysicalSizeX="\\(.*\\)"/\\1/')

    if [ -z "\$origScale" ] || [ "\$origScale" == "0" ]; then
        echo "ERROR: Could not extract PhysicalSizeX from OME-TIFF metadata"
        exit 1
    fi

    # Calculate effective scale (rounding to nearest integer)

    effScale=\$(awk -v scale="\${origScale}" "BEGIN{print int(1/scale + 0.5)}")
    effPhysicalSize=\$(awk -v a="\${origScale}" -v b="\${effScale}" "BEGIN{print a*b}")

    echo "Original PhysicalSizeX: \${origScale} µm"
    echo "Effective scale factor: \${effScale}"
    echo "Effective PhysicalSizeX after scaling: \${effPhysicalSize} µm"

    # If scale is 1, just extract series 1 of the file
    if [ "\$effScale" -eq 1 ]; then
        echo "Scale factor is 1, no downscaling needed"
        bfconvert ${ome_tiff} \\
            -series 0 \\
            -compression zlib \\
            -noflat \\
            ${prefix}.downscaled.ome.tiff
    else
        # Step 1: Extract series 0 (full resolution)
        bfconvert ${ome_tiff} -series 0 -compression zlib ${prefix}.series0.ome.tiff

        # Step 2: Create new pyramid with base layer plus new rescale
        bfconvert ${prefix}.series0.ome.tiff \\
            -pyramid-resolutions 2 \\
            -pyramid-scale \${effScale} \\
            -tilex 256 \\
            -tiley 256 \\
            -compression zlib \\
            -noflat \\
            ${prefix}.rescaled.ome.tiff

        # Step 3: Extract SubIFD level 1 using Python
        python3 - "\${effScale}" <<'PYEOF'
import tifffile
import numpy as np
from xml.etree import ElementTree as ET
import sys


effScale = float(sys.argv[1])

with tifffile.TiffFile("${prefix}.rescaled.ome.tiff") as tif:
    series = tif.series[0]

    if hasattr(series, 'levels') and len(series.levels) > 1:
        level1_data = series.levels[1].asarray()
        level1_shape = level1_data.shape

        print(f"Extracted level 1 shape: {level1_shape}")

        # Parse original OME-XML to extract channel info
        channel_names = []
        channel_colors = []
        physical_size_x = None
        physical_size_y = None

        if tif.ome_metadata:
            root = ET.fromstring(tif.ome_metadata)
            ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}

            # Extract channel info
            for channel in root.findall('.//ome:Channel', ns):
                name = channel.get('Name', '')
                color = channel.get('Color', '-1')
                channel_names.append(name)
                channel_colors.append(color)

            # Extract physical sizes
            pixels = root.find('.//ome:Pixels', ns)
            if pixels is not None:
                physical_size_x = pixels.get('PhysicalSizeX')
                physical_size_y = pixels.get('PhysicalSizeY')

        # Calculate new physical sizes based on downscale factor
        if physical_size_x and physical_size_y:
            new_physical_size_x = float(physical_size_x) * effScale
            new_physical_size_y = float(physical_size_y) * effScale
        else:
            new_physical_size_x = None
            new_physical_size_y = None

        # Determine axes
        if level1_data.ndim == 3 and level1_shape[0] <= 20:
            axes = 'CYX'
            num_channels = level1_shape[0]
        elif level1_data.ndim == 2:
            axes = 'YX'
            num_channels = 1
        else:
            axes = None
            num_channels = 1

        # Build metadata dict
        metadata = {'axes': axes}

        if new_physical_size_x and new_physical_size_y:
            metadata['PhysicalSizeX'] = new_physical_size_x
            metadata['PhysicalSizeY'] = new_physical_size_y
            metadata['PhysicalSizeXUnit'] = 'µm'
            metadata['PhysicalSizeYUnit'] = 'µm'

        if channel_names and len(channel_names) == num_channels:
            metadata['Channel'] = {'Name': channel_names}

        print(f"Channel names: {channel_names}")
        print(f"Physical size: {new_physical_size_x} x {new_physical_size_y} µm")

        # Save with metadata
        tifffile.imwrite(
            "${prefix}.downscaled.ome.tiff",
            level1_data,
            photometric='minisblack',
            compression='deflate',
            compressionargs={'level': 6},
            tile=(256, 256),
            metadata=metadata,
            ome=True,
            bigtiff=True
        )

        print(f"Saved downscaled image with shape {level1_shape}")
    else:
        print("ERROR: No SubIFD levels found")
        sys.exit(1)
PYEOF

        # Cleanup intermediate files
        rm -f ${prefix}.series0.ome.tiff
        rm -f ${prefix}.rescaled.ome.tiff
    fi

    # Save metadata
    cat > ${prefix}.json <<END_METADATA
original_file: ${ome_tiff}
original_scale: \${origScale} µm/pixel
downscale_factor: \${effScale}
effective_scale: \${effPhysicalSize} µm/pixel
END_METADATA

    cat <<END_VERSIONS > versions.yml
"${task.process}":
    bftools: ${BFTOOLS_VERSION}
END_VERSIONS
    """
}
