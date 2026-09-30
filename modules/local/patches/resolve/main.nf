process RESOLVE_PATCHES {
    tag "$meta.id"
    label 'process_medium'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(masks, stageAs: 'masks/*'), path(patch_table), path(roi_mask)

    output:
    tuple val(meta), path("${prefix}.tif"), emit: mask
    path "versions.yml"                   , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    prefix = task.ext.prefix ?: "${meta.id}"
    def roi_arg = roi_mask ? "--roi_mask ${roi_mask}" : ''
    """
    resolve_patches.py \\
        $args \\
        --masks masks/* \\
        --patches ${patch_table} \\
        --output ${prefix}.tif \\
        ${roi_arg}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        resolve_patches.py: \$(grep -m1 'Version:' "\$(command -v resolve_patches.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """

    stub:
    prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.tif

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        resolve_patches.py: \$(grep -m1 'Version:' "\$(command -v resolve_patches.py)" | cut -d ' ' -f 3)
    END_VERSIONS
    """
}
