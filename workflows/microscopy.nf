/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    IMPORT MODULES / SUBWORKFLOWS / FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/
include { paramsSummaryMap       } from 'plugin/nf-schema'
include { softwareVersionsToYAML } from '../subworkflows/nf-core/utils_nfcore_pipeline'
include { methodsDescriptionText } from '../subworkflows/local/utils_nfcore_microscopy_pipeline'

include { QUPATH_STITCH } from '../modules/local/qupath/stitch/main'
include { BFTOOLS_TIFFMETAXML } from '../modules/local/bftools/tiffmetaxml/main'
include { INDICA_TIFF_TO_OME } from '../modules/local/halo/indicatifftoome/main.nf'
include { HANDLE_STITCHED } from '../modules/local/handlestitched/main'
include { EXTRACTIMAGECHANNEL } from '../modules/local/extractimagechannel/main'

include { DEEPCELL_MESMER } from '../modules/nf-core/deepcell/mesmer/main'
include { CELLPOSE } from '../modules/local/cellpose/main' // custom module to set cache directories

include { SEPARATEIMAGECHANNELS } from '../modules/local/separateimagechannels/main'
include { MCQUANT } from '../modules/nf-core/mcquant/main'
include { SCIMAP_MCMICRO } from '../modules/local/scimap/mcmicro/main' // custom module to get all output contents

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow MICROSCOPY {

    take:
    ch_samplesheet // channel: samplesheet read in from --input
    ch_markers // channel: markers file [[id:markers], params.markers]

    main:
    ch_versions = Channel.empty()

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
    ch_images = QUPATH_STITCH.out.image
        .mix(HANDLE_STITCHED.out.image)
        .mix(INDICA_TIFF_TO_OME.out.image)

    ch_versions = ch_versions.mix(QUPATH_STITCH.out.versions)
    ch_versions = ch_versions.mix(HANDLE_STITCHED.out.versions)
    ch_versions = ch_versions.mix(INDICA_TIFF_TO_OME.out.versions)

    // Extract XML, DAPI channel
    BFTOOLS_TIFFMETAXML(ch_images)

    ch_versions = ch_versions.mix(BFTOOLS_TIFFMETAXML.out.versions)

    EXTRACTIMAGECHANNEL (
        BFTOOLS_TIFFMETAXML.out.xml_tif
    )
    ch_versions = ch_versions.mix(EXTRACTIMAGECHANNEL.out.versions)

    // Segmentation - use only nuclear image
    ch_nuclear_image = EXTRACTIMAGECHANNEL.out.image

    if (params.segmentation == 'mesmer') {
        DEEPCELL_MESMER (
            ch_nuclear_image,
            [[], []]
        )
        ch_segmentation = DEEPCELL_MESMER.out.mask
            .map { meta, it ->
                return [meta.id, meta + [seg: 'mesmer'], it]
            }
        ch_versions = ch_versions.mix(DEEPCELL_MESMER.out.versions)

    } else if (params.segmentation == 'cellpose') {
        CELLPOSE (
            ch_nuclear_image,
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
        ch_images
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

    SCIMAP_MCMICRO {
        MCQUANT.out.csv
    }
    ch_versions = ch_versions.mix(SCIMAP_MCMICRO.out.versions)

    //
    // Collate and save software versions
    //
    softwareVersionsToYAML(ch_versions)
        .collectFile(
            storeDir: "${params.outdir}/pipeline_info",
            name: 'nf_core_'  +  'microscopy_software_'  + 'versions.yml',
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
