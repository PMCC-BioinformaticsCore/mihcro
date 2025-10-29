process DAPI_BACKGROUND_REMOVAL {
    tag "$meta.id"
    label 'process_low'

    container "ghcr.io/patrickcrock/mihcro_python:1.0"
    containerOptions "--env MPLCONFIGDIR=/tmp/matplotlib-${task.index}"

    publishDir "${params.outdir}/dapi_processed", mode: 'copy'

    input:
    tuple val(meta), path(dapi_tif), path(af_tif, stageAs: 'af_channel?.tif')

    output:
    tuple val(meta), path("*_dapi_processed.tif"), emit: processed_image
    tuple val(meta), path("*_dapi_diagnostic.png"), emit: diagnostic
    path "versions.yml"           , emit: versions

    when:
    params.dapi_bg_method != "none"

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    def sigma_arg = params.dapi_bg_sigma ? "-s ${params.dapi_bg_sigma}" : ''
    def radius_arg = params.dapi_bg_radius ? "-r ${params.dapi_bg_radius}" : ''
    def af_arg = af_tif && af_tif.name != 'af_channel.tif' ? "-a ${af_tif}" : ''
    """
    otsu_thresholding.py \\
        -i ${dapi_tif} \\
        -o ${prefix}_dapi_processed.tif \\
        -m ${params.dapi_bg_method} \\
        -l ${params.dapi_otsu_leniency} \\
        -p ${prefix}_dapi_diagnostic.png \\
        ${af_arg} \\
        ${sigma_arg} \\
        ${radius_arg}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        otsu_thresholding.py: \$(grep 'Version: ' otsu_thresholding.py | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}_dapi_processed.tif
    touch ${prefix}_dapi_diagnostic.png

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        otsu_thresholding.py: \$(grep 'Version: ' otsu_thresholding.py | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
