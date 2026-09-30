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

include { PREPARE_ROI } from '../modules/local/roi/prepare/main'
include { TISSUE_DETECT } from '../modules/local/roi/tissue/main'

include { PREPROCESS_CELLPOSE } from '../modules/local/cellpose/main'
include { PATCH_SEGMENTATION } from '../subworkflows/local/patch_segmentation/main'

include { MCQUANT } from '../modules/nf-core/mcquant/main'
include { ANNOTATE_CELLS } from '../modules/local/annotatecells/main'

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
    ch_roi // channel: [ meta, [ QuPath GeoJSON files ] ] from the samplesheet 'roi' column ([] if none)

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
        ch_scale = DOWNSCALE_OME_TIFF.out.metadata
        ch_versions = ch_versions.mix(DOWNSCALE_OME_TIFF.out.versions)
    } else {
        ch_processed_images = PREPROCESS_IMAGE.out.image
        ch_scale = PREPROCESS_IMAGE.out.image.map { meta, img -> [meta, []] }
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

    // Regions of interest: QuPath GeoJSON annotations if given, otherwise automatic tissue detection

    ch_roi_input = BFTOOLS_TIFFMETAXML.out.xml_tif
        .map { meta, xml, tif -> [meta.id, meta, xml] }
        .join( ch_scale.map { meta, json -> [meta.id, json] } )
        .join( ch_roi.map { meta, geojson -> [meta.id, geojson] } )
        .join( EXTRACT_DAPI.out.image.map { meta, dapi -> [meta.id, dapi] } )
        .branch { id, meta, xml, json, geojson, dapi ->
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

    // Segmentation, run per patch

    if (params.segmentation == 'cellpose' && params.membrane_channel != null) {
        ch_cellpose_pairs = ch_nuclear_image
            .map { meta, img -> [meta.id, meta, img] }
            .join( ch_membrane.map { meta, img -> [meta.id, img] } )
            .multiMap { id, meta, nuclear, membrane ->
                nuclear:  [meta, nuclear]
                membrane: [meta, membrane]
            }
        PREPROCESS_CELLPOSE ( ch_cellpose_pairs.nuclear, ch_cellpose_pairs.membrane )
        // Membrane is already combined into the Cellpose input image
        ch_seg_image = PREPROCESS_CELLPOSE.out.combined
        ch_seg_membrane = ch_seg_image.map { meta, img -> [meta, []] }
    } else if (params.segmentation == 'cellpose') {
        ch_seg_image = ch_nuclear_image
        ch_seg_membrane = ch_seg_image.map { meta, img -> [meta, []] }
    } else {
        ch_seg_image = ch_nuclear_image
        ch_seg_membrane = ch_membrane
    }

    ch_seg_input = ch_seg_image
        .map { meta, img -> [meta.id, meta, img] }
        .join( ch_seg_membrane.map { meta, membrane -> [meta.id, membrane] } )
        .join( ch_roi_masks.map { id, mask, labels, classes -> [id, mask] } )
        .map { id, meta, img, membrane, roi_mask -> [meta, img, membrane, roi_mask] }

    PATCH_SEGMENTATION ( ch_seg_input )

    ch_segmentation = PATCH_SEGMENTATION.out.mask
        .map { meta, mask ->
            return [meta.id, meta, mask]
        }
    ch_versions = ch_versions.mix(PATCH_SEGMENTATION.out.versions)

    // Quantification
    ch_separatedimg = ch_processed_images
        .map { meta, img -> [meta.id, meta, img] }

    // Use the segmentation meta (carries meta.seg, used in MCQUANT prefix and publish path)
    ch_quant = ch_segmentation
        .combine(ch_separatedimg, by: 0)
        .multiMap { id, meta_seg, seg, meta_img, img ->
            image: [meta_seg, img]
            mask:  [meta_seg, seg]
        }

    MCQUANT (
        ch_quant.image,
        ch_quant.mask,
        ch_markers
    )
    ch_versions = ch_versions.mix(MCQUANT.out.versions)

    ch_render = ch_nuclear_image
        .map { meta, img -> [meta.id, img] }
        .join( ch_segmentation )
        .join( ch_roi_masks.map { id, mask, labels, classes -> [id, mask] } )
        .map { id, img, meta, mask, roi_mask -> [meta, img, mask, roi_mask] }

    RENDER_SEGMENTATION (
        ch_render
    )

    ch_versions = ch_versions.mix(RENDER_SEGMENTATION.out.versions)

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

    RENDER_REPORT (
        ANNOTATE_CELLS.out.csv.mix(ch_cells.plain),
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
