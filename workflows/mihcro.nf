/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    IMPORT MODULES / SUBWORKFLOWS / FUNCTIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/
include { paramsSummaryMap       } from 'plugin/nf-schema'
include { softwareVersionsToYAML } from '../subworkflows/nf-core/utils_nfcore_pipeline'
include { methodsDescriptionText } from '../subworkflows/local/utils_nfcore_mihcro_pipeline'

include { QUPATH_STITCH } from '../modules/local/qupath/stitch/main'
include { INDICA_TIFF_TO_OME } from '../modules/local/halo/indicatifftoome/main.nf'
include { PREPROCESS_IMAGE } from '../modules/local/preprocessimage/main'
include { DAPI_BACKGROUND_REMOVAL } from '../modules/local/bgremoval/main.nf'

include { PREPARE_ROI } from '../modules/local/roi/prepare/main'
include { TISSUE_DETECT } from '../modules/local/roi/tissue/main'

include { PATCH_SEGMENTATION } from '../subworkflows/local/patch_segmentation/main'

include { MCQUANT } from '../modules/nf-core/mcquant/main'
include { ANNOTATE_CELLS } from '../modules/local/annotatecells/main'

include { RENDER_REPORT } from '../modules/local/qcreportR/main'
include { RENDER_SEGMENTATION } from '../modules/local/renderseg/main'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow MIHCRO {

    take:
    ch_samplesheet // channel: [ meta, [ tiffs ] ] read in from --input
    ch_markers // channel: markers file [[id:markers], params.markers]
    ch_roi // channel: [ meta, [ QuPath GeoJSON files ] ] from the samplesheet 'roi' column ([] if none)

    main:

    //
    // Image preparation: stitch or convert to OME-TIFF if needed, then select the marker channels,
    // downscale from the best pyramid level and extract the nuclear / membrane / AF channels in one pass
    //

    ch_samplesheet
        .map { meta, tiffs -> [meta + [base_id: meta.id], tiffs] }
        .branch { meta, tiffs ->
            tiles: meta.format == 'tiles'
            fused: meta.format == 'fused'
            stitched: meta.format == 'stitched'
                return [meta, tiffs[0]] // exactly one file, checked in PIPELINE_INITIALISATION
        }
        .set { ch_branched }

    QUPATH_STITCH (
        "${projectDir}/bin/stitch.groovy",
        ch_branched.tiles
    )

    INDICA_TIFF_TO_OME (
        ch_branched.fused
    )

    ch_raw_images = QUPATH_STITCH.out.image
        .mix(INDICA_TIFF_TO_OME.out.image)
        .mix(ch_branched.stitched)

    PREPROCESS_IMAGE ( ch_raw_images, ch_markers )

    ch_versions = Channel.empty()
        .mix(QUPATH_STITCH.out.versions)
        .mix(INDICA_TIFF_TO_OME.out.versions)
        .mix(PREPROCESS_IMAGE.out.versions)

    ch_processed_images = PREPROCESS_IMAGE.out.image

    // Optional DAPI background removal / Otsu thresholding, optionally subtracting an AF channel
    if (params.dapi_bg_method != 'none') {
        ch_bg_input = params.dapi_bg_method == 'af'
            ? PREPROCESS_IMAGE.out.nuclear.join(PREPROCESS_IMAGE.out.af)
            : PREPROCESS_IMAGE.out.nuclear.map { meta, dapi -> [meta, dapi, []] }
        DAPI_BACKGROUND_REMOVAL ( ch_bg_input )
        ch_nuclear_image = DAPI_BACKGROUND_REMOVAL.out.processed_image
        ch_versions = ch_versions.mix(DAPI_BACKGROUND_REMOVAL.out.versions)
    } else {
        ch_nuclear_image = PREPROCESS_IMAGE.out.nuclear
    }

    ch_membrane = params.membrane_channel
        ? PREPROCESS_IMAGE.out.membrane
        : PREPROCESS_IMAGE.out.nuclear.map { meta, dapi -> [meta, []] }

    //
    // Regions of interest: QuPath GeoJSON annotations if given, otherwise automatic tissue detection
    //

    ch_roi_input = PREPROCESS_IMAGE.out.xml
        .map { meta, xml -> [meta.id, meta, xml] }
        .join( PREPROCESS_IMAGE.out.scale.map { meta, json -> [meta.id, json] } )
        .join( PREPROCESS_IMAGE.out.nuclear.map { meta, dapi -> [meta.id, dapi] } )
        .join( ch_roi.map { meta, geojson -> [meta.id, geojson] } )
        .branch { id, meta, xml, json, dapi, geojson ->
            annotated: geojson
                return [meta, geojson, xml, json]
            tissue: params.tissue_detection
                return [meta, dapi, xml]
            none: true
                return id
        }

    PREPARE_ROI ( ch_roi_input.annotated )
    TISSUE_DETECT ( ch_roi_input.tissue )
    ch_versions = ch_versions
        .mix(PREPARE_ROI.out.versions)
        .mix(TISSUE_DETECT.out.versions)

    // One element per sample: [ id, roi_mask, roi_labels, roi_classes ], with [] placeholders if there is no ROI
    ch_roi_masks = PREPARE_ROI.out.roi
        .mix( TISSUE_DETECT.out.roi )
        .map { meta, mask, labels, classes -> [meta.id, mask, labels, classes] }
        .mix( ch_roi_input.none.map { id -> [id, [], [], []] } )

    //
    // Segmentation, run per patch (Cellpose stacks the membrane into each patch in MAKE_PATCHES)
    //

    ch_seg_input = ch_nuclear_image
        .map { meta, img -> [meta.id, meta, img] }
        .join( ch_membrane.map { meta, membrane -> [meta.id, membrane] } )
        .join( ch_roi_masks.map { id, mask, labels, classes -> [id, mask] } )
        .map { id, meta, img, membrane, roi_mask -> [meta, img, membrane, roi_mask] }

    PATCH_SEGMENTATION ( ch_seg_input )
    ch_versions = ch_versions.mix(PATCH_SEGMENTATION.out.versions)

    ch_segmentation = PATCH_SEGMENTATION.out.mask
        .map { meta, mask -> [meta.id, meta, mask] }

    //
    // Quantification
    //

    // Use the segmentation meta (carries meta.seg, used in the MCQUANT prefix and publish path)
    ch_quant = ch_segmentation
        .join( ch_processed_images.map { meta, img -> [meta.id, img] } )
        .multiMap { id, meta, mask, img ->
            image: [meta, img]
            mask:  [meta, mask]
        }

    MCQUANT (
        ch_quant.image,
        ch_quant.mask,
        ch_markers
    )
    ch_versions = ch_versions.mix(MCQUANT.out.versions)

    // Add ROI class columns to the cell table where the sample has a ROI
    ch_cells = MCQUANT.out.csv
        .map { meta, csv -> [meta.id, meta, csv] }
        .join( ch_roi_masks )
        .branch { id, meta, csv, mask, labels, classes ->
            annotate: mask
                return [meta, csv, mask, labels, classes]
            plain: true
                return [meta, csv, []]
        }

    ANNOTATE_CELLS ( ch_cells.annotate )
    ch_versions = ch_versions.mix(ANNOTATE_CELLS.out.versions)

    //
    // Reporting
    //

    ch_render = ch_nuclear_image
        .map { meta, img -> [meta.id, img] }
        .join( ch_segmentation )
        .join( ch_roi_masks.map { id, mask, labels, classes -> [id, mask] } )
        .map { id, img, meta, mask, roi_mask -> [meta, img, mask, roi_mask] }

    RENDER_SEGMENTATION ( ch_render )
    ch_versions = ch_versions.mix(RENDER_SEGMENTATION.out.versions)

    // Report input: cell table, ROI classes, pixel-size metadata and patch table per sample
    ch_report = ANNOTATE_CELLS.out.csv
        .mix(ch_cells.plain)
        .map { meta, csv, classes -> [meta.id, meta, csv, classes] }
        .join( PREPROCESS_IMAGE.out.scale.map { meta, json -> [meta.id, json] } )
        .join( PATCH_SEGMENTATION.out.table.map { meta, table -> [meta.id, table] } )
        .map { id, meta, csv, classes, json, table -> [meta, csv, classes, json, table] }

    RENDER_REPORT (
        ch_report,
        ch_markers,
        file("${projectDir}/bin/QCreport.Rmd"),
        file("${projectDir}/bin/QCreport_resolution.Rmd")
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
