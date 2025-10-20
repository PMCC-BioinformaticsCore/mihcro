process EXTRACTIMAGECHANNEL {
    tag "$meta.id"
    label 'process_low'

    container "ghcr.io/patrickcrock/mihcro_python:1.0"

    input:
    tuple val(meta), path(xml), path(ome_tif)

    output:
    tuple val(meta), path("*.tif") , emit: image
    path "versions.yml"           , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    extract_image_channel.py \\
        $args \\
        --xml ${xml} \\
        --image ${ome_tif} \\
        --output ${prefix}.tif

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        extract_image_channel.py: \$(grep 'Version:'  extract_image_channel.py | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """

    touch ${prefix}.tif

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        extract_image_channel.py: \$(grep 'Version:'  extract_image_channel.py | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
