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
include { HANDLE_STITCHED } from '../modules/local/handlestitched/main'
include { EXTRACTIMAGECHANNEL as EXTRACT_DAPI } from '../modules/local/extractimagechannel/main'
include { EXTRACTIMAGECHANNEL as EXTRACT_AF } from '../modules/local/extractimagechannel/main'
include { EXTRACTIMAGECHANNEL as EXTRACT_MEMBRANE } from '../modules/local/extractimagechannel/main'


include { DOWNSCALE_OME_TIFF } from '../modules/local/downscaletiff'

include { DEEPCELL_MESMER } from '../modules/nf-core/deepcell/mesmer/main'
include { PREPROCESS_CELLPOSE } from '../modules/local/cellpose/main'
include { CELLPOSE } from '../modules/local/cellpose/main' // custom module to set cache directories

include { SEPARATEIMAGECHANNELS } from '../modules/local/separateimagechannels/main'
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
        .branch { meta, tiffs ->
            tiles: meta.format == 'tiles'
            stitched: meta.format == 'stitched'
            fused: meta.format == 'fused'
        }
        .set { ch_branched }

    // Process each format type

    // Stitch tiled input
    stitch_script = "${projectDir}/bin/stitch.groovy"
    QUPATH_STITCH (
        stitch_script,
        ch_branched.tiles
    )

    // Link to tiff from stitched input
    HANDLE_STITCHED (
        ch_branched.stitched
    )

    // Process HALO fused input
    INDICA_TIFF_TO_OME (
        ch_branched.fused
    )

    // Combine all processed images
    ch_images = Channel.empty()
        .mix(QUPATH_STITCH.out.image)
        .mix(HANDLE_STITCHED.out.image)
        .mix(INDICA_TIFF_TO_OME.out.image)

    ch_versions = Channel.empty()
        .mix(QUPATH_STITCH.out.versions)
        .mix(HANDLE_STITCHED.out.versions)
        .mix(INDICA_TIFF_TO_OME.out.versions)


    // Conditional downscaling based on parameter
    if (params.downscale_mode == '1um') {
        DOWNSCALE_OME_TIFF(
            ch_images
        )
        ch_processed_images = DOWNSCALE_OME_TIFF.out.downscaled
        ch_versions = ch_versions.mix(DOWNSCALE_OME_TIFF.out.versions)
    } else {
        ch_processed_images = ch_images
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
            ch_cellpose_input,
            []
        )

        ch_segmentation = CELLPOSE.out.mask
            .map { meta, it ->
                return [meta.id, meta + [seg: 'cellpose'], it]
            }
        ch_versions = ch_versions.mix(CELLPOSE.out.versions)
    }

    // Quantification
    SEPARATEIMAGECHANNELS (
        ch_processed_images,
        ch_markers
    )
    ch_separatedimg = SEPARATEIMAGECHANNELS.out.image
        .map { meta, it ->
            [meta.id, meta, it]
        }
    ch_versions = ch_versions.mix(SEPARATEIMAGECHANNELS.out.versions)

    ch_quant = ch_segmentation
        .combine( ch_separatedimg, by:0 )
        .multiMap { meta1, meta2, seg, meta3, img ->
            image: [meta2, img]
            mask: [meta2, seg]
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
