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
    """
    # Collect TIFF files into an array, safe against spaces/newlines
    mapfile -d '' tiff_files < <(
        find -L "${tiff_dir}" -maxdepth 1 -type f \
        '(' -name "*.tif" -o -name "*.tiff" -o -name "*.ome.tif" -o -name "*.ome.tiff" ')' -print0
    )

    # Check number of TIFF files
    if [ \${#tiff_files[@]} -eq 0 ]; then
        echo "ERROR: No TIFF files found in ${tiff_dir}"
        exit 1
    elif [ \${#tiff_files[@]} -gt 1 ]; then
        echo "ERROR: Multiple TIFF files found in ${tiff_dir}. Expected exactly one."
        # Print them safely
        for f in "\${tiff_files[@]}"; do
            printf '  %s\n' "\$f"
        done
        exit 1
    fi

    # Create symlink to the single TIFF file
    tiff_file="\${tiff_files[0]}"
    ln -s $args "\${tiff_file}" "${prefix}.ome.tiff"

    cat <<EOF > versions.yml
"${task.process}":
    handle_stitched: 1.0.0
EOF
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.ome.tiff

    cat <<EOF > versions.yml
"${task.process}":
    handle_stitched: 1.0.0
EOF
    """
}
