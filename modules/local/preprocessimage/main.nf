process PREPROCESS_IMAGE {
    tag "$meta.id"
    label 'process_medium'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(image)
    tuple val(meta2), path(markerfile)

    output:
    tuple val(meta), path("*.ome.tiff")      , emit: image
    tuple val(meta), path("*.xml")           , emit: xml
    tuple val(meta), path("*.json")          , emit: scale
    tuple val(meta), path("*_dapi.tif")      , emit: nuclear
    tuple val(meta), path("*_membrane.tif")  , emit: membrane, optional: true
    tuple val(meta), path("*_AF.tif")        , emit: af, optional: true
    path "versions.yml"                      , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    preprocess_image.py \\
        $args \\
        --image ${image} \\
        --markers ${markerfile} \\
        --prefix ${prefix} \\
        --threads ${task.cpus}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        tifffile: \$(python -c "import tifffile; print(tifffile.__version__)")
        preprocess_image.py: \$(grep -m1 'Version:' "\$(command -v preprocess_image.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    def image_name = params.downscale_mode == '1um' ? "${prefix}.downscaled.ome.tiff" : "${prefix}.processed.ome.tiff"
    """
    touch ${image_name}
    touch ${prefix}.xml
    touch ${prefix}.json
    touch ${prefix}_dapi.tif
    ${params.membrane_channel ? "touch ${prefix}_membrane.tif" : ''}
    ${params.dapi_bg_method == 'af' ? "touch ${prefix}_AF.tif" : ''}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        tifffile: \$(python -c "import tifffile; print(tifffile.__version__)")
        preprocess_image.py: \$(grep -m1 'Version:' "\$(command -v preprocess_image.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
