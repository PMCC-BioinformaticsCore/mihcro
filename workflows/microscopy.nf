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
include { EXTRACTIMAGECHANNEL } from '../modules/local/extractimagechannel/main' 

include { DEEPCELL_MESMER } from '../modules/nf-core/deepcell/mesmer/main'  
include { CELLPOSE } from '../modules/local/cellpose/main' // custom module to set cache directories

include { SEPARATEIMAGECHANNELS } from '../modules/local/separateimagechannels/main' 
include { MCQUANT } from '../modules/nf-core/mcquant/main'                   
include { SCIMAP_MCMICRO } from '../modules/nf-core/scimap/mcmicro/main' 

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow MICROSCOPY {

    take:
    ch_samplesheet // channel: samplesheet read in from --input

    main:
    ch_versions = Channel.empty()

    // Stitch images together
    stitch_script = "${projectDir}/bin/stitch.groovy"
    QUPATH_STITCH (
        stitch_script, 
        ch_samplesheet
    )
    ch_versions = ch_versions.mix(QUPATH_STITCH.out.versions)

    // Get DAPI channel
    BFTOOLS_TIFFMETAXML (
        QUPATH_STITCH.out.image
    )
    ch_versions = ch_versions.mix(BFTOOLS_TIFFMETAXML.out.versions)

    EXTRACTIMAGECHANNEL (
        BFTOOLS_TIFFMETAXML.out.xml,
        QUPATH_STITCH.out.image
    )
    ch_versions = ch_versions.mix(EXTRACTIMAGECHANNEL.out.versions)

    // Segmentation - use only nuclear image
    ch_nuclear_image = EXTRACTIMAGECHANNEL.out.image

    DEEPCELL_MESMER (
        ch_nuclear_image,
        [[], []]
    )
    ch_versions = ch_versions.mix(EXTRACTIMAGECHANNEL.out.versions)

    CELLPOSE (
        ch_nuclear_image,
        []
    )
    ch_versions = ch_versions.mix(CELLPOSE.out.versions)

    // Quantification
    SEPARATEIMAGECHANNELS (
        QUPATH_STITCH.out.image
    )
    ch_versions = ch_versions.mix(SEPARATEIMAGECHANNELS.out.versions)

    Channel.fromPath(params.markers)
        .map { it -> 
            [[id: 'markers'], it]
        }
        .collect()
        .set { ch_markers }

    ch_segmentation = DEEPCELL_MESMER.out.mask
        .mix( CELLPOSE.out.mask )
        .combine(SEPARATEIMAGECHANNELS.out.image, by: 0)
        .multiMap{ meta, mask, image ->
            image: [meta, image]
            mask: [meta, mask]
        }

    MCQUANT (
        ch_segmentation.image,
        ch_segmentation.mask,
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
