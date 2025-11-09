process INDICA_TIFF_TO_OME {
    tag "$meta.id"
    label 'process_low'

    container "ghcr.io/patrickcrock/mihcro_python:1.1"

    input:
    tuple val(meta), path(indica_tif)

    output:
    tuple val(meta), path("*.ome.tif") , emit: image
    path "versions.yml"           , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    # Collect TIFF files into an array, safe against spaces/newlines
    mapfile -d '' tiff_files < <(
        find -L "${indica_tif}" -maxdepth 1 -type f \
        '(' -name "*.tif" -o -name "*.tiff" -o -name "*.ome.tif" -o -name "*.ome.tiff" ')' -print0
    )

    # Check number of TIFF files
    if [ \${#tiff_files[@]} -eq 0 ]; then
        echo "ERROR: No TIFF files found in ${indica_tif}"
        exit 1
    elif [ \${#tiff_files[@]} -gt 1 ]; then
        echo "ERROR: Multiple TIFF files found in ${indica_tif}. Expected exactly one."
        # Print them safely
        for f in "\${tiff_files[@]}"; do
            printf '  %s\n' "\$f"
        done
        exit 1
    fi

    # Pull the tiff file for downstream
    tiff_file="\${tiff_files[0]}"


    indicaTIFF_to_ome.py \\
        $args \\
        --image \${tiff_file} \\
        --output ${prefix}.ome.tif

    cat <<-END_VERSIONS > versions.yml
"${task.process}":
        python: \$(python --version | sed 's/Python //g')
END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.ome.tif

    cat <<-END_VERSIONS > versions.yml
"${task.process}":
        python: \$(python --version | sed 's/Python //g')
END_VERSIONS
    """
}
