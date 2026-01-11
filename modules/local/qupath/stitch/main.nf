process QUPATH_STITCH {
    tag "$meta.id"
    label 'process_medium'

    input:
    path(stitch_script)
    tuple val(meta), path(tifs)

    output:
    tuple val(meta), path("*.ome.tif"), emit: image
    path "versions.yml"           , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"

    // Generate a file containing the list of input TIFFs
    def input_manifest = "input_files.list"
    def tif_list_content = tifs instanceof List ? tifs.join('\n') : tifs.toString()

    """
    # Write the list of files to a manifest file
    echo "$tif_list_content" > ${input_manifest}

    # Pass the manifest file to QuPath instead of the raw file list
    QuPath script \\
        ${stitch_script} \\
        --args ${input_manifest} \\
        --args ${prefix} \\
        $args

    cat <<-END_VERSIONS > versions.yml
"${task.process}":
        QuPath: \$(QuPath --version | head -n1 | cut -d ' ' -f 2)
END_VERSIONS
    """

    stub:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.ome.tif

    cat <<-END_VERSIONS > versions.yml
"${task.process}":
        QuPath: \$(QuPath --version | head -n1 | cut -d ' ' -f 2)
END_VERSIONS
    """
}
