process HANDLE_STITCHED {
    tag "$meta.id"
    label 'process_low'

    input:
    tuple val(meta), path(tiff_dir)

    output:
    tuple val(meta), path("*.ome.tiff"), emit: image
    path "versions.yml"                , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"

    // 1. Convert input to a List, regardless of whether it's a single file or a list
    def input_files = tiff_dir instanceof List ? tiff_dir : [tiff_dir]

    // 2. Check the number of files and throw a Nextflow error (more meaningful than a shell exit)
    if (input_files.size() == 0) {
        error "ERROR [HANDLE_STITCHED]: No files received for sample '${meta.id}'. Expected exactly one file."
    }

    if (input_files.size() > 1) {
        def file_list = input_files.join('\n  - ')
        error "ERROR [HANDLE_STITCHED]: Multiple files received for sample '${meta.id}'. Expected exactly one file, but found ${input_files.size()}:\n  - ${file_list}"
    }

    // 3. Get the single file path (Now we know there is exactly one)
    def tiff_file = input_files[0]
    """
    # Create symlink to the single TIFF file
    ln -s ${args} ${tiff_file} "${prefix}.ome.tiff"

    cat <<-END_VERSIONS > versions.yml
"${task.process}":
    handle_stitched: 1.0.0
END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.ome.tiff

    cat <<-END_VERSIONS > versions.yml
"${task.process}":
    handle_stitched: 1.0.0
END_VERSIONS
    """
}
