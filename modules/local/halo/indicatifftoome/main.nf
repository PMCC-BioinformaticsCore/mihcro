process INDICA_TIFF_TO_OME {
    tag "$meta.id"
    label 'process_low'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(indica_tif)

    output:
    tuple val(meta), path("*.ome.tif") , emit: image
    path "versions.yml"           , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"

    def input_files = indica_tif instanceof List ? indica_tif : [indica_tif]

    if (input_files.size() == 0) {
        error "ERROR [INDICA_TIFF_TO_OME]: No files received for sample '${meta.id}'. Expected exactly one file."
    }

    if (input_files.size() > 1) {
        def file_list = input_files.join('\n  - ')
        error "ERROR [INDICA_TIFF_TO_OME]: Multiple files received for sample '${meta.id}'. Expected exactly one file, but found ${input_files.size()}:\n  - ${file_list}"
    }

    def tiff_file = input_files[0]
    """
    indicaTIFF_to_ome.py \\
        $args \\
        --image ${tiff_file} \\
        --output ${prefix}.ome.tif

    cat <<-END_VERSIONS > versions.yml
"${task.process}":
        python: \$(python --version | sed 's/Python //g')
END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.ome.tif

    cat <<-END_VERSIONS > versions.yml
"${task.process}":
        python: \$(python --version | sed 's/Python //g')
END_VERSIONS
    """
}
