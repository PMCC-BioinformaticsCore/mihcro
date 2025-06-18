process SCIMAP_MCMICRO {
    tag "$meta.id"
    label 'process_single'

    // WARN: Version information not provided by tool on CLI. Please update the VERSION variable when bumping
    container "docker.io/labsyspharm/scimap:2.1.3"

    input:
    tuple val(meta), path(cellbyfeature)

    output:
    tuple val(meta), path("scimap")     , emit: h5ad    , optional:true
    path "versions.yml"                 , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    // Exit if running this module with -profile conda / -profile mamba
    if (workflow.profile.tokenize(',').intersect(['conda', 'mamba']).size() >= 1) {
        error "Scimap module does not support Conda. Please use Docker / Singularity / Podman instead."
    }
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    def VERSION='2.1.3' // WARN: Version information not provided by tool on CLI. Please update this string when bumping
    """
    mkdir numba_cache_dir
    export NUMBA_CACHE_DIR='./numba_cache_dir'

    scimap-mcmicro $cellbyfeature -o ./${prefix}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        scimap: $VERSION
    END_VERSIONS
    """

    stub:
    // Exit if running this module with -profile conda / -profile mamba
    if (workflow.profile.tokenize(',').intersect(['conda', 'mamba']).size() >= 1) {
        error "Scimap module does not support Conda. Please use Docker / Singularity / Podman instead."
    }
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    def VERSION='2.1.3' // WARN: Version information not provided by tool on CLI. Please update this string when bumping
    """
    touch ${prefix}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        scimap: $VERSION
    END_VERSIONS
    """

}
