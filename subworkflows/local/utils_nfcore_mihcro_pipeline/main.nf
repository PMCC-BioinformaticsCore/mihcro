//
// Subworkflow with functionality specific to the nf-core/mihcro pipeline
//

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    IMPORT FUNCTIONS / MODULES / SUBWORKFLOWS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

include { UTILS_NFSCHEMA_PLUGIN     } from '../../nf-core/utils_nfschema_plugin'
include { paramsSummaryMap          } from 'plugin/nf-schema'
include { samplesheetToList         } from 'plugin/nf-schema'
include { completionEmail           } from '../../nf-core/utils_nfcore_pipeline'
include { completionSummary         } from '../../nf-core/utils_nfcore_pipeline'
include { imNotification            } from '../../nf-core/utils_nfcore_pipeline'
include { UTILS_NFCORE_PIPELINE     } from '../../nf-core/utils_nfcore_pipeline'
include { UTILS_NEXTFLOW_PIPELINE   } from '../../nf-core/utils_nextflow_pipeline'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    SUBWORKFLOW TO INITIALISE PIPELINE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow PIPELINE_INITIALISATION {

    take:
    version           // boolean: Display version and exit
    validate_params   // boolean: Boolean whether to validate parameters against the schema at runtime
    monochrome_logs   // boolean: Do not use coloured log outputs
    nextflow_cli_args //   array: List of positional nextflow CLI args
    outdir            //  string: The output directory where the results will be saved
    input             //  string: Path to input samplesheet

    main:

    ch_versions = Channel.empty()

    //
    // Print version and exit if required and dump pipeline parameters to JSON file
    //
    UTILS_NEXTFLOW_PIPELINE (
        version,
        true,
        outdir,
        workflow.profile.tokenize(',').intersect(['conda', 'mamba']).size() >= 1
    )

    //
    // Validate parameters and generate parameter summary to stdout
    //
    UTILS_NFSCHEMA_PLUGIN (
        workflow,
        validate_params,
        null
    )

    //
    // Check config provided to the pipeline
    //
    UTILS_NFCORE_PIPELINE (
        nextflow_cli_args
    )

    //
    // Validate segmentation parameter
    //
    validateSegmentationParams()

    //
    // Validate downsampling parameters
    //
    validateDownscaleParams()

    //
    // Validate DAPI background removal parameters
    //
    validateDAPIbgParams()

    //
    // Validate patching parameters
    //
    validatePatchParams()

    //
    // Create channel from input file provided through params.input
    //

    Channel
        .fromList(samplesheetToList(params.input, "${projectDir}/assets/schema_input.json"))
        // The 'roi' column is optional, so older samplesheets without it still work
        .map { row -> [row[0], row[1], row.size() > 2 ? row[2] : []] }
        .multiMap { meta, tifs, roi ->
            samplesheet: [meta, tifs]
            roi: [meta, resolveRoiFiles(meta, roi)]
        }
        .set { ch_input }

    ch_input.samplesheet
        .map { meta, tifs ->
            def path = file(tifs)
            def tif_list

            if (path.isDirectory()) {
                // Directory: grab all TIFFs
                tif_list = path.listFiles().findAll {
                    it.name.endsWith('.tif') || it.name.endsWith('.tiff') ||
                    it.name.endsWith('.ome.tif') || it.name.endsWith('.ome.tiff')
                }
                if (tif_list.isEmpty()) {
                    error("Sample '${meta.id}': No TIFF files found in directory: ${tifs}")
                }
            } else if (path.isFile()) {
                // Single file: use it directly
                if (!(path.name.endsWith('.tif') || path.name.endsWith('.tiff') ||
                    path.name.endsWith('.ome.tif') || path.name.endsWith('.ome.tiff'))) {
                    error("Sample '${meta.id}': File must be a TIFF: ${tifs}")
                }
                tif_list = [path]
            } else {
                error("Sample '${meta.id}': Path does not exist or is not a file/directory: ${tifs}")
            }

            return [meta, tif_list]
        }
        .set { ch_samplesheet }

    //
    // Check if markers file provided through params.markers is valid, and create channel from params.markers
    //
    Channel
        .fromList(samplesheetToList(params.markers, "${projectDir}/assets/schema_markers.json"))
        .collect({ it[0] }, flat: false)
        .map { it ->
            validateInputMarkers(it)
        }

    Channel
        .fromPath(params.markers)
        .map { it ->
            return [ [id: 'markers'], it]
        }
        .collect()
        .set { ch_markers }

    emit:
    samplesheet = ch_samplesheet
    markers     = ch_markers
    roi         = ch_input.roi // channel: [ meta, [ GeoJSON files ] ], empty list if no ROI was given
    versions    = ch_versions
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    SUBWORKFLOW FOR PIPELINE COMPLETION
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow PIPELINE_COMPLETION {

    take:
    email           //  string: email address
    email_on_fail   //  string: email address sent on pipeline failure
    plaintext_email // boolean: Send plain-text email instead of HTML
    outdir          //    path: Path to output directory where results will be published
    monochrome_logs // boolean: Disable ANSI colour codes in log output
    hook_url        //  string: hook URL for notifications

    main:
    summary_params = paramsSummaryMap(workflow, parameters_schema: "nextflow_schema.json")

    //
    // Completion email and summary
    //
    workflow.onComplete {
        if (email || email_on_fail) {
            completionEmail(
                summary_params,
                email,
                email_on_fail,
                plaintext_email,
                outdir,
                monochrome_logs,
                []
            )
        }

        completionSummary(monochrome_logs)
        if (hook_url) {
            imNotification(summary_params, hook_url)
        }
    }

    workflow.onError {
        log.error "Pipeline failed. Please refer to troubleshooting docs: https://nf-co.re/docs/usage/troubleshooting"
    }
}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

//
// Validate segmentation parameter
//
def validateSegmentationParams() {
    if (params.segmentation && !(params.segmentation in ['mesmer', 'cellpose'])) {
        error("Invalid segmentation method: '${params.segmentation}'. Must be 'mesmer' or 'cellpose'")
    }
}

//
// Validate downsampling parameters
//
def validateDownscaleParams() {

    // downscale mode
    if (params.downscale_mode && !(params.downscale_mode in ['1um', 'none'])) {
        error("Invalid downsampling selection: '${params.downscale_mode}'. Must be '1um', or 'none'")
    }

}

//
// Validate DAPI background removal parameters
//
def validateDAPIbgParams() {
    def valid_methods = ['none', 'otsu_only', 'gaussian', 'rollingball', 'af', 'mean']

    if (!(params.dapi_bg_method in valid_methods)) {
        error("Invalid dapi_bg_method: '${params.dapi_bg_method}'. Must be one of: ${valid_methods.join(', ')}")
    }

    if (params.dapi_bg_method == 'gaussian' && !params.dapi_bg_sigma) {
        error("--dapi_bg_sigma is required when using dapi_bg_method='gaussian'")
    }

    if (params.dapi_bg_method == 'rollingball' && !params.dapi_bg_radius) {
        error("--dapi_bg_radius is required when using dapi_bg_method='rollingball'")
    }

    if (params.dapi_bg_method == 'af' && !params.af_channel) {
        error("--af_channel is required when using dapi_bg_method='af'")
    }

    if (params.dapi_otsu_leniency < -1.0 || params.dapi_otsu_leniency > 1.0) {
        error("--dapi_otsu_leniency must be between -1.0 and 1.0, got: ${params.dapi_otsu_leniency}")
    }
}

//
// Validate patching parameters
//
def validatePatchParams() {
    if (params.patch_size < 0) {
        error("--patch_size must be 0 (whole image) or a positive number of pixels, got: ${params.patch_size}")
    }
    if (params.patch_size > 0 && params.patch_overlap >= params.patch_size) {
        error("--patch_overlap (${params.patch_overlap}) must be smaller than --patch_size (${params.patch_size})")
    }
    if (params.patch_merge_threshold <= 0 || params.patch_merge_threshold > 1) {
        error("--patch_merge_threshold must be in (0, 1], got: ${params.patch_merge_threshold}")
    }
}

//
// Resolve the samplesheet 'roi' column (a GeoJSON file or a directory of them) to a list of files
//
def resolveRoiFiles(meta, roi) {
    if (!roi) {
        return []
    }
    def path = file(roi)
    if (path.isDirectory()) {
        def roi_list = path.listFiles().findAll { f -> f.isFile() && isGeojsonFile(f) }.sort { f -> f.name }
        if (roi_list.isEmpty()) {
            error("Sample '${meta.id}': No .geojson files found in ROI directory: ${roi}")
        }
        return roi_list
    }
    if (!isGeojsonFile(path)) {
        error("Sample '${meta.id}': ROI file must be a .geojson (or .json) file: ${roi}")
    }
    return [path]
}

def isGeojsonFile(f) {
    def name = f.name.toLowerCase()
    return name.endsWith('.geojson') || name.endsWith('.json')
}

//
// Validate channels from input marker sheet
//
def validateInputMarkers(markerdata) {

    // Check that marker names are unique
    def marker_name_list = []
    markerdata.each { row ->
        if (marker_name_list.contains(row.marker_name)) {
            error("Duplicate marker names for: '${row.marker_name}' in marker sheet")
        } else {
            marker_name_list.add(row.marker_name)
        }
    }

}

//
// Validate channels from input samplesheet
//
def validateInputSamplesheet(input) {
    def (metas, fastqs) = input[1..2]

    // Check that multiple runs of the same sample are of the same datatype i.e. single-end / paired-end
    def endedness_ok = metas.collect{ meta -> meta.single_end }.unique().size == 1
    if (!endedness_ok) {
        error("Please check input samplesheet -> Multiple runs of a sample must be of the same datatype i.e. single-end or paired-end: ${metas[0].id}")
    }

    return [ metas[0], fastqs ]
}
//
// Generate methods description for MultiQC
//
def toolCitationText() {
    // TODO nf-core: Optionally add in-text citation tools to this list.
    // Can use ternary operators to dynamically construct based conditions, e.g. params["run_xyz"] ? "Tool (Foo et al. 2023)" : "",
    // Uncomment function in methodsDescriptionText to render in MultiQC report
    def citation_text = [
            "Tools used in the workflow included:",
            "."
        ].join(' ').trim()

    return citation_text
}

def toolBibliographyText() {
    // TODO nf-core: Optionally add bibliographic entries to this list.
    // Can use ternary operators to dynamically construct based conditions, e.g. params["run_xyz"] ? "<li>Author (2023) Pub name, Journal, DOI</li>" : "",
    // Uncomment function in methodsDescriptionText to render in MultiQC report
    def reference_text = [
        ].join(' ').trim()

    return reference_text
}

def methodsDescriptionText(mqc_methods_yaml) {
    // Convert  to a named map so can be used as with familiar NXF ${workflow} variable syntax in the MultiQC YML file
    def meta = [:]
    meta.workflow = workflow.toMap()
    meta["manifest_map"] = workflow.manifest.toMap()

    // Pipeline DOI
    if (meta.manifest_map.doi) {
        // Using a loop to handle multiple DOIs
        // Removing `https://doi.org/` to handle pipelines using DOIs vs DOI resolvers
        // Removing ` ` since the manifest.doi is a string and not a proper list
        def temp_doi_ref = ""
        def manifest_doi = meta.manifest_map.doi.tokenize(",")
        manifest_doi.each { doi_ref ->
            temp_doi_ref += "(doi: <a href=\'https://doi.org/${doi_ref.replace("https://doi.org/", "").replace(" ", "")}\'>${doi_ref.replace("https://doi.org/", "").replace(" ", "")}</a>), "
        }
        meta["doi_text"] = temp_doi_ref.substring(0, temp_doi_ref.length() - 2)
    } else meta["doi_text"] = ""
    meta["nodoi_text"] = meta.manifest_map.doi ? "" : "<li>If available, make sure to update the text to include the Zenodo DOI of version of the pipeline used. </li>"

    // Tool references
    meta["tool_citations"] = ""
    meta["tool_bibliography"] = ""

    // TODO nf-core: Only uncomment below if logic in toolCitationText/toolBibliographyText has been filled!
    // meta["tool_citations"] = toolCitationText().replaceAll(", \\.", ".").replaceAll("\\. \\.", ".").replaceAll(", \\.", ".")
    // meta["tool_bibliography"] = toolBibliographyText()


    def methods_text = mqc_methods_yaml.text

    def engine =  new groovy.text.SimpleTemplateEngine()
    def description_html = engine.createTemplate(methods_text).make(meta)

    return description_html.toString()
}
