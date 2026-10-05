process PREPARE_ROI {
    tag "$meta.id"
    label 'process_low'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(geojson, stageAs: 'geojson/roi*.geojson'), path(xml), path(scale_json), path(tissue_image)

    output:
    tuple val(meta), path("*_roi_mask.ome.tif"), path("*_roi_labels.tif"), path("*_roi_classes.csv"), emit: roi
    tuple val(meta), path("*_roi.geojson")                                                         , emit: geojson
    tuple val(meta), path("*_roi.png")                                                             , emit: png
    path "versions.yml"                                                                            , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    def scale_arg = scale_json ? "--scale_json ${scale_json}" : ''
    // With a nuclear image, tissue detection also runs inside each annotation (--roi_tissue_detection)
    def tissue_arg = tissue_image ? "--tissue_image ${tissue_image}" : ''
    """
    export MPLCONFIGDIR=./matplotlib

    prepare_roi.py \\
        $args \\
        --xml ${xml} \\
        --prefix ${prefix} \\
        --geojson ${geojson} \\
        ${scale_arg} \\
        ${tissue_arg}

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
    touch ${prefix}_roi.geojson
    touch ${prefix}_roi.png

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        prepare_roi.py: \$(grep -m1 'Version:' "\$(command -v prepare_roi.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
