// Converting dimension order required: https://github.com/labsyspharm/quantification/issues/41

process SEPARATEIMAGECHANNELS {
    tag "$meta.id"
    label 'process_low'

    container "docker://mcmero/tifftools:python-3.12.5_aicsimageio_dask_tifffile_xmlschema--007280ae0ab35b3e"

    input:
    tuple val(meta), path(ome_tif)
    
    output:
    tuple val(meta), path("*.tif"), emit: image
    path "versions.yml"           , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    convert_ome_tiff.py \\
        $args \\
        --image ${ome_tif} \\
        --output ${prefix}.tif 

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        convert_ome_tiff.py: \$(grep 'Version:'  convert_ome_tiff.py | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    
    touch ${prefix}.tif

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        convert_ome_tiff.py: \$(grep 'Version:'  convert_ome_tiff.py | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
