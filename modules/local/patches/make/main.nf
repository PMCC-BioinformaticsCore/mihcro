process MAKE_PATCHES {
    tag "$meta.id"
    label 'process_low'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(image), path(membrane), path(roi_mask)

    output:
    tuple val(meta), path("patches/*.tif") , emit: patches
    tuple val(meta), path("*_patches.csv") , emit: table
    tuple val(meta), path("*_patches.png") , emit: png
    path "versions.yml"                    , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    def membrane_arg = membrane ? "--membrane ${membrane}" : ''
    def roi_arg = roi_mask ? "--roi_mask ${roi_mask}" : ''
    """
    export MPLCONFIGDIR=./matplotlib

    make_patches.py \\
        $args \\
        --image ${image} \\
        --prefix ${prefix} \\
        ${membrane_arg} \\
        ${roi_arg}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        make_patches.py: \$(grep -m1 'Version:' "\$(command -v make_patches.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    mkdir -p patches
    touch patches/${prefix}_patch0000.tif
    touch patches/${prefix}_patch0001.tif
    ${membrane ? "touch patches/${prefix}_patch0000_membrane.tif patches/${prefix}_patch0001_membrane.tif" : ''}
    touch ${prefix}_patches.csv
    touch ${prefix}_patches.png

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        make_patches.py: \$(grep -m1 'Version:' "\$(command -v make_patches.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
