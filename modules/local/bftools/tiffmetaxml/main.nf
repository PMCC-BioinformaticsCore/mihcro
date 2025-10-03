process BFTOOLS_TIFFMETAXML {
    tag "$meta.id"
    label 'process_single'

    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine == 'singularity' && !task.ext.singularity_pull_docker_container ?
        'https://depot.galaxyproject.org/singularity/bftools:8.0.0--hdfd78af_0':
        'biocontainers/bftools:8.0.0--hdfd78af_0' }"

    input:
    tuple val(meta), path(tif)

    output:
    tuple val(meta), path("*.xml"), path(tif), emit: xml_tif
    path "versions.yml"           , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def args2 = task.ext.args2 ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    def BFTOOLS_VERSION='8.0.0' // Edit bftools versions manually
    """
    export _JAVA_OPTIONS="-XX:-UsePerfData -Xlog:disable"

    tiffcomment \\
        $args \\
        $tif \\
        | xmlindent \\
        $args2 \\
        > ${prefix}.xml

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        bftools: ${BFTOOLS_VERSION}
    END_VERSIONS
    """

    stub:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    def BFTOOLS_VERSION='8.0.0' // Edit bftools versions manually
    """

    touch ${prefix}.xml

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        bftools: ${BFTOOLS_VERSION}
    END_VERSIONS
    """
}
