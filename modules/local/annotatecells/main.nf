process ANNOTATE_CELLS {
    tag "$meta.id"
    label 'process_single'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(cells), path(roi_mask), path(roi_labels), path(roi_classes)

    output:
    tuple val(meta), path("*_cells_roi.csv"), path(roi_classes), emit: csv
    path "versions.yml"                                        , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    annotate_cells.py \\
        $args \\
        --cells ${cells} \\
        --roi_mask ${roi_mask} \\
        --roi_labels ${roi_labels} \\
        --roi_classes ${roi_classes} \\
        --output ${prefix}_cells_roi.csv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        annotate_cells.py: \$(grep -m1 'Version:' "\$(command -v annotate_cells.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}_cells_roi.csv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        annotate_cells.py: \$(grep -m1 'Version:' "\$(command -v annotate_cells.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
