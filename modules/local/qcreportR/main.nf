process RENDER_REPORT {
    tag "$meta.id"
    label 'process_medium'

    container "ghcr.io/patrickcrock/rmdqc_microscopy:1.0"

    input:
    tuple val(meta), path(cellbyfeature), path(roi_classes), path(scale_json), path(patches_csv)
    tuple val(meta3), path(markerfile)
    path rmd_file
    path rmd_child

    output:
    tuple val(meta), path("*_report.html"), emit: html
    tuple val(meta), path("*_seurat.rds"), emit: seurat
    path "*_cluster_mean_intensity.csv", emit: cluster_markers
    path "versions.yml", emit: versions

    script:
    def prefix = task.ext.prefix ?: "${meta.id}"
    def roi_classes_name = roi_classes ? roi_classes.name : ''
    def scale_json_name = scale_json ? scale_json.name : ''
    def patches_name = patches_csv ? patches_csv.name : ''
    def VERSION='1.0' // Container version

    // Workflow settings shown in the report overview. Only values that are stable between runs are
    // included (no run name or date), so that -resume still reuses this task.
    def run_info = [
        ['group', 'parameter', 'value'],
        ['Pipeline', 'mihcro version', workflow.manifest.version],
        ['Pipeline', 'Nextflow version', nextflow.version],
        ['Image preparation', 'downscale_mode', params.downscale_mode],
        ['Image preparation', 'nuclear_channel', params.nuclear_channel],
        ['Image preparation', 'membrane_channel', params.membrane_channel],
        ['Background removal', 'dapi_bg_method', params.dapi_bg_method],
        ['Background removal', 'dapi_bg_sigma', params.dapi_bg_sigma],
        ['Background removal', 'dapi_bg_radius', params.dapi_bg_radius],
        ['Background removal', 'dapi_otsu_leniency', params.dapi_otsu_leniency],
        ['Background removal', 'af_channel', params.af_channel],
        ['Segmentation', 'segmentation', params.segmentation],
        ['Segmentation', 'cellpose_model', params.cellpose_model],
        ['Segmentation', 'cellpose_diam', params.cellpose_diam],
        ['Patching and ROI', 'patch_size', params.patch_size],
        ['Patching and ROI', 'patch_overlap', params.patch_overlap],
        ['Patching and ROI', 'patch_merge_threshold', params.patch_merge_threshold],
        ['Patching and ROI', 'tissue_detection', params.tissue_detection],
        ['Patching and ROI', 'roi_tissue_detection', params.roi_tissue_detection],
        ['Patching and ROI', 'roi_exclude_classes', params.roi_exclude_classes],
    ]
    def run_info_args = run_info.flatten()
        .collect { value -> "'" + (value == null ? '' : value.toString()).replace("'", "'\\''") + "'" }
        .join(' ')
    """
    printf '%s\\t%s\\t%s\\n' ${run_info_args} > run_info.tsv

    R -e "rmarkdown::render('${rmd_file}', \
        output_format='html_document', \
        output_file='${prefix}_report.html', \
        params=list(cellbyfeature='${cellbyfeature.name}', markerfile='${markerfile.name}', samplename='${prefix}', roiclasses='${roi_classes_name}', runinfo='run_info.tsv', scalejson='${scale_json_name}', patches='${patches_name}'), \
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
    touch '${prefix}_seurat.rds'
    touch '${prefix}_res.0.5_cluster_mean_intensity.csv'

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        container: '${VERSION}'
        r-base: \$(Rscript -e "cat(R.version.string)")
        rmarkdown: \$(Rscript -e "cat(as.character(packageVersion('rmarkdown')))")
    END_VERSIONS
    """

}
