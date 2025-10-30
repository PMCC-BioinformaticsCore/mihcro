process RENDER_SEGMENTATION {
    tag "$meta.id"
    label 'process_low'
    publishDir "${params.outdir}/images", pattern: "*_boundaries.tiff", mode: 'copy'

    container "ghcr.io/patrickcrock/mihcro_python:1.0"

    input:
    tuple val(meta), path(dapi_image)
    tuple val(meta2), path(boundary_mask)

    output:
    tuple val(meta), path("*_bw_boundaries.tiff"), emit: boundaries_bw
    tuple val(meta), path("*_rgb_boundaries.tiff"), emit: boundaries_rgb
    path "versions.yml", emit: versions

    script:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    render_boundaries.py \\
        --dapi_path ${dapi_image} \\
        --mask_path ${boundary_mask} \\
        --output_prefix ${prefix}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        render_boundaries.py: \$(grep 'Version:'  render_boundaries.py | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """

    touch ${prefix}_bw_boundaries.tiff
    touch ${prefix}_rgb_boundaries.tiff


    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        render_boundaries.py: \$(grep 'Version:'  render_boundaries.py | cut -d ' ' -f 3)
    END_VERSIONS
    """

}
