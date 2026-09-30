process TISSUE_DETECT {
    tag "$meta.id"
    label 'process_low'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(image), path(xml)

    output:
    tuple val(meta), path("*_roi_mask.ome.tif"), path("*_roi_labels.tif"), path("*_roi_classes.csv"), emit: roi
    tuple val(meta), path("*_roi.png")                                                             , emit: png
    path "versions.yml"                                                                            , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    export MPLCONFIGDIR=./matplotlib

    prepare_roi.py \\
        $args \\
        --xml ${xml} \\
        --prefix ${prefix} \\
        --tissue_image ${image}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        prepare_roi.py: \$(grep -m1 'Version:' "\$(command -v prepare_roi.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}_roi_mask.ome.tif
    touch ${prefix}_roi_labels.tif
    touch ${prefix}_roi_classes.csv
    touch ${prefix}_roi.png

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        prepare_roi.py: \$(grep -m1 'Version:' "\$(command -v prepare_roi.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
