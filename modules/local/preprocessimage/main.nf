process PREPROCESS_IMAGE {
    tag "$meta.id"
    label 'process_medium'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(image)
    tuple val(meta2), path(markerfile)

    output:
    tuple val(meta), path("*.preproc.ome.tif"), emit: image
    path "versions.yml",                        emit: versions

    script:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    preprocess_image.py \\
        --image ${image} \\
        --markers ${markerfile} \\
        --output ${prefix}.preproc.ome.tif

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        preprocess_image.py: \$(grep 'Version:' preprocess_image.py | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.preproc.ome.tif

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        preprocess_image.py: \$(grep 'Version:' preprocess_image.py | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
