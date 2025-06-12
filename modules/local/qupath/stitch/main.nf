process QUPATH_STITCH {
    tag "$meta.id"
    label 'process_medium'

    input:
    path(stitch_script)
    tuple val(meta), path(tifs)

    output:
    tuple val(meta), path("*.ome.tif"), emit: tif
    path "versions.yml"           , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    QuPath script \\
        ${stitch_script} \\
        --args ${tifs} \\
        --args ${prefix} \\
        $args \\

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        Qupath: \$(Qupath --version | head -n1 | cut -d ' ' -f 2)
    END_VERSIONS
    """

    stub:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    
    touch ${prefix}.ome.tif

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        Qupath: \$(Qupath --version | head -n1 | cut -d ' ' -f 2)
    END_VERSIONS
    """
}
