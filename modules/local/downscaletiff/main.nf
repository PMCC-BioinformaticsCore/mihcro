process DOWNSCALE_OME_TIFF {
    tag "$meta.id"
    label 'process_medium'

    conda "${moduleDir}/environment.yml"
    container "ghcr.io/patrickcrock/mihcro_python:1.0"

    input:
    tuple val(meta), path(ome_tiff)

    output:
    tuple val(meta), path("*.downscaled.ome.tiff"), emit: downscaled
    tuple val(meta), path("*.json"), emit: metadata
    path "versions.yml", emit: versions

    script:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    ome_tiff_rescaler.py \\
        ${ome_tiff} \\
        --prefix ${prefix}

    cat <<END_VERSIONS > versions.yml
"${task.process}":
    tifffile: \$(python -c "import tifffile; print(tifffile.__version__)")
    scipy: \$(python -c "import scipy; print(scipy.__version__)")
END_VERSIONS
    """
}
