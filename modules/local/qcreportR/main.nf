process RENDER_REPORT {
    tag "$meta.id"
    label 'process_medium'
    publishDir "${params.outdir}/reports", pattern: "*.html", mode: 'copy'

    container "ghcr.io/patrickcrock/rmdqc_microscopy:1.0"

    input:
    tuple val(meta), path(cellbyfeature)
    tuple val(meta3), path(markerfile)
    path rmd_file

    output:
    tuple val(meta), path("*_report.html"), emit: html
    path "versions.yml", emit: versions

    script:
    def prefix = task.ext.prefix ?: "${meta.id}"
    def VERSION='1.0' // Container version
    """
    R -e "rmarkdown::render('${rmd_file}', \
        output_format='html_document', \
        output_file='${prefix}_report.html', \
        params=list(cellbyfeature='${cellbyfeature.name}', markerfile='${markerfile.name}', samplename='${prefix}'), \
        envir=new.env())"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        container: '${VERSION}'
        r-base: \$(Rscript -e "cat(R.version.string)")
        rmarkdown: \$(Rscript -e "cat(as.character(packageVersion('rmarkdown')))")
    END_VERSIONS
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    def VERSION='1.0' // Container version
    """
    touch '${prefix}_report.html'

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        container: '${VERSION}'
        r-base: \$(Rscript -e "cat(R.version.string)")
        rmarkdown: \$(Rscript -e "cat(as.character(packageVersion('rmarkdown')))")
    END_VERSIONS
    """

}
