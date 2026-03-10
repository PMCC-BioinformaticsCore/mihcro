/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    IMPORT MODULES / SUBWORKFLOWS / FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/
include { paramsSummaryMap       } from 'plugin/nf-schema'
include { softwareVersionsToYAML } from '../subworkflows/nf-core/utils_nfcore_pipeline'
include { methodsDescriptionText } from '../subworkflows/local/utils_nfcore_mihcro_pipeline'

include { QUPATH_STITCH } from '../modules/local/qupath/stitch/main'
include { BFTOOLS_TIFFMETAXML } from '../modules/local/bftools/tiffmetaxml/main'
include { INDICA_TIFF_TO_OME } from '../modules/local/halo/indicatifftoome/main.nf'
include { PREPROCESS_IMAGE } from '../modules/local/preprocessimage/main'
include { EXTRACTIMAGECHANNEL as EXTRACT_DAPI } from '../modules/local/extractimagechannel/main'
include { EXTRACTIMAGECHANNEL as EXTRACT_AF } from '../modules/local/extractimagechannel/main'
include { EXTRACTIMAGECHANNEL as EXTRACT_MEMBRANE } from '../modules/local/extractimagechannel/main'


include { DOWNSCALE_OME_TIFF } from '../modules/local/downscaletiff'

include { DEEPCELL_MESMER } from '../modules/nf-core/deepcell/mesmer/main'
include { PREPROCESS_CELLPOSE } from '../modules/local/cellpose/main'
include { CELLPOSE } from '../modules/local/cellpose/main' // custom module to set cache directories

include { MCQUANT } from '../modules/nf-core/mcquant/main'

include { RENDER_REPORT } from '../modules/local/qcreportR/main'
include { RENDER_SEGMENTATION } from '../modules/local/renderseg/main'
include { DAPI_BACKGROUND_REMOVAL } from '../modules/local/bgremoval/main.nf'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow MIHCRO {

    take:
    ch_samplesheet // channel: samplesheet read in from --input
    ch_markers // channel: markers file [[id:markers], params.markers]

    main:

    // Branch input based on format
    ch_samplesheet
        .map { meta, tiffs ->
            [meta + [base_id: meta.id], tiffs]
        }
        .branch { meta, tiffs ->
            tiles: meta.format == 'tiles'
            stitched: meta.format == 'stitched'
            fused: meta.format == 'fused'
        }
        .set { ch_branched }

    // Process special format types

    // Stitch tiled input
    stitch_script = "${projectDir}/bin/stitch.groovy"
    QUPATH_STITCH (
        stitch_script,
        ch_branched.tiles
    )

    // Process HALO fused input
    INDICA_TIFF_TO_OME (
        ch_branched.fused
    )

    // Validate stitched input

    ch_validated_stitched = ch_branched.stitched
        .map { meta, tiff ->
            def input_files = tiff instanceof List ? tiff : [tiff]

            if (input_files.size() == 0) {
                error "ERROR [PREPROCESS_IMAGE]: No files received for sample '${meta.id}'."
            }
            if (input_files.size() > 1) {
                error "ERROR [PREPROCESS_IMAGE]: Multiple files received for sample '${meta.id}'. Expected exactly one file, but found ${input_files.size()}:\n  - ${input_files.join('\n  - ')}"
            }

            def resolved = input_files[0]

            if (resolved.isDirectory()) {
                def tiffs = resolved.listFiles().findAll { it.name =~ /(?i)\.ome\.tiff?$|\.tiff?$/ }
                if (tiffs.size() == 0) {
                    error "ERROR [PREPROCESS_IMAGE]: Directory '${resolved}' for sample '${meta.id}' contains no TIFF files."
                }
                if (tiffs.size() > 1) {
                    error "ERROR [PREPROCESS_IMAGE]: Directory '${resolved}' for sample '${meta.id}' contains multiple TIFF files. Expected exactly one:\n  - ${tiffs.join('\n  - ')}"
                }
                resolved = tiffs[0]
            }

            [meta, resolved]
        }

    // Preprocess
    ch_raw_images = Channel.empty()
    .mix(QUPATH_STITCH.out.image)
    .mix(ch_validated_stitched)
    .mix(INDICA_TIFF_TO_OME.out.image)

    PREPROCESS_IMAGE(ch_raw_images, ch_markers)

    ch_versions = Channel.empty()
        .mix(QUPATH_STITCH.out.versions)
        .mix(INDICA_TIFF_TO_OME.out.versions)
        .mix(PREPROCESS_IMAGE.out.versions)

    if (params.downscale_mode == '1um') {
        DOWNSCALE_OME_TIFF(PREPROCESS_IMAGE.out.image)
        ch_processed_images = DOWNSCALE_OME_TIFF.out.downscaled
        ch_versions = ch_versions.mix(DOWNSCALE_OME_TIFF.out.versions)
    } else {
        ch_processed_images = PREPROCESS_IMAGE.out.image
    }

    // Extract XML, DAPI channel from processed images
    BFTOOLS_TIFFMETAXML(ch_processed_images)

    ch_versions = ch_versions.mix(BFTOOLS_TIFFMETAXML.out.versions)

    EXTRACT_DAPI (
        BFTOOLS_TIFFMETAXML.out.xml_tif
    )
    ch_versions = ch_versions.mix(EXTRACT_DAPI.out.versions)

    // Background removal and otsu thresholding, if requested
    if (params.dapi_bg_method != "none") {
        if (params.dapi_bg_method == "af") {
            // Extract both DAPI and AF channels
            ch_dapi = EXTRACT_DAPI.out.image
            ch_af = EXTRACT_AF(BFTOOLS_TIFFMETAXML.out.xml_tif).image

            // Join DAPI and AF by meta.id, then pass to background removal
            ch_bg_input = ch_dapi.join(ch_af, by: 0)
            DAPI_BACKGROUND_REMOVAL(ch_bg_input)
        } else {
            // No AF channel needed - add empty placeholder
            ch_bg_input = EXTRACT_DAPI.out.image.map { meta, dapi ->
                [meta, dapi, []]
            }
            DAPI_BACKGROUND_REMOVAL(ch_bg_input)
        }
        ch_nuclear_image = DAPI_BACKGROUND_REMOVAL.out.processed_image
        ch_versions = ch_versions.mix(DAPI_BACKGROUND_REMOVAL.out.versions)
    } else {
        ch_nuclear_image = EXTRACT_DAPI.out.image
    }

    // Extract membrane channel if requested
    if (params.membrane_channel != null) {
        EXTRACT_MEMBRANE(BFTOOLS_TIFFMETAXML.out.xml_tif)
        ch_membrane = EXTRACT_MEMBRANE.out.image
    } else {
        // Create a dummy membrane channel matched to nuclear images
        ch_membrane = ch_nuclear_image.map { meta, img -> [meta, []] }
    }

    // Segmentation

    if (params.segmentation == 'mesmer') {

        DEEPCELL_MESMER (
            ch_nuclear_image,
            ch_membrane
        )

        ch_segmentation = DEEPCELL_MESMER.out.mask
            .map { meta, it ->
                return [meta.id, meta + [seg: 'mesmer'], it]
            }
        ch_versions = ch_versions.mix(DEEPCELL_MESMER.out.versions)

    } else if (params.segmentation == 'cellpose') {

        if (params.membrane_channel != null) {
            PREPROCESS_CELLPOSE(ch_nuclear_image, ch_membrane)
            ch_cellpose_input = PREPROCESS_CELLPOSE.out.combined
        } else {
            ch_cellpose_input = ch_nuclear_image
        }

        CELLPOSE (
            ch_cellpose_input
        )

        ch_segmentation = CELLPOSE.out.mask
            .map { meta, it ->
                return [meta.id, meta + [seg: 'cellpose'], it]
            }
        ch_versions = ch_versions.mix(CELLPOSE.out.versions)
    }

    // Quantification
    ch_separatedimg = ch_processed_images
            .map { meta, it -> [meta.id, meta, it] }

        ch_quant = ch_segmentation
            .combine(ch_separatedimg, by: 0)
            .multiMap { id, meta_seg, seg, meta_img, img ->
                image: [meta_img, img]
                mask:  [meta_img, seg]
            }

    MCQUANT (
        ch_quant.image,
        ch_quant.mask,
        ch_markers
    )
    ch_versions = ch_versions.mix(MCQUANT.out.versions)

    RENDER_SEGMENTATION (
        ch_nuclear_image,
        ch_quant.mask
    )

    ch_versions = ch_versions.mix(RENDER_SEGMENTATION.out.versions)

    RENDER_REPORT (
        MCQUANT.out.csv,
        ch_markers,
        file("${projectDir}/bin/QCreport.Rmd")
    )

    ch_versions = ch_versions.mix(RENDER_REPORT.out.versions)

    //
    // Collate and save software versions
    //
    softwareVersionsToYAML(ch_versions)
        .collectFile(
            storeDir: "${params.outdir}/pipeline_info",
            name: 'nf_core_'  +  'mihcro_software_'  + 'versions.yml',
            sort: true,
            newLine: true
        ).set { ch_collated_versions }


    emit:
    versions       = ch_versions                 // channel: [ path(versions.yml) ]

}

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    THE END
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/
