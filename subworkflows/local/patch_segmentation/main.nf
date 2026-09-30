//
// Patch-based segmentation, adapted from sopa (https://github.com/prism-oncology/sopa):
// split the image into overlapping patches restricted to the ROI, segment every patch as its own task,
// then resolve the patch masks into a single whole-image label mask
//

include { MAKE_PATCHES    } from '../../../modules/local/patches/make/main'
include { RESOLVE_PATCHES } from '../../../modules/local/patches/resolve/main'
include { DEEPCELL_MESMER } from '../../../modules/nf-core/deepcell/mesmer/main'
include { CELLPOSE        } from '../../../modules/local/cellpose/main'

workflow PATCH_SEGMENTATION {

    take:
    ch_input // channel: [ val(meta), path(image), path(membrane) or [], path(roi_mask) or [] ]

    main:

    ch_versions = Channel.empty()

    MAKE_PATCHES ( ch_input )
    ch_versions = ch_versions.mix(MAKE_PATCHES.out.versions)

    // One element per patch: [ meta + [patch, n_patches], image patch, membrane patch or [] ]
    ch_patches = MAKE_PATCHES.out.patches
        .flatMap { meta, files ->
            def all_files = [files].flatten()
            def membranes = all_files
                .findAll { f -> f.name.endsWith('_membrane.tif') }
                .collectEntries { f -> [ patchId(f), f ] }
            def images = all_files.findAll { f -> !f.name.endsWith('_membrane.tif') }
            images.collect { image ->
                def patch = patchId(image)
                [ meta + [ patch: patch, n_patches: images.size() ], image, membranes[patch] ?: [] ]
            }
        }

    if (params.segmentation == 'mesmer') {
        // multiMap keeps each nuclear patch paired with its own membrane patch
        ch_mesmer = ch_patches
            .multiMap { meta, image, membrane ->
                nuclear:  [ meta, image ]
                membrane: [ meta, membrane ]
            }
        DEEPCELL_MESMER ( ch_mesmer.nuclear, ch_mesmer.membrane )
        ch_patch_masks = DEEPCELL_MESMER.out.mask
        ch_versions = ch_versions.mix(DEEPCELL_MESMER.out.versions.first())

    } else if (params.segmentation == 'cellpose') {
        // Multi-channel (membrane + nuclear) input is already combined into the image before patching
        CELLPOSE ( ch_patches.map { meta, image, membrane -> [ meta, image ] }, [] )
        ch_patch_masks = CELLPOSE.out.mask
        ch_versions = ch_versions.mix(CELLPOSE.out.versions.first())
    }

    // Regroup patch masks per sample as soon as all of its patches are done
    ch_resolve = ch_patch_masks
        .map { meta, mask -> [ groupKey(meta.id, meta.n_patches), mask ] }
        .groupTuple()
        .map { id, masks -> [ id.toString(), masks ] }
        .join( MAKE_PATCHES.out.table.map { meta, table -> [ meta.id, meta, table ] } )
        .join( ch_input.map { meta, image, membrane, roi_mask -> [ meta.id, roi_mask ] } )
        .map { id, masks, meta, table, roi_mask -> [ meta + [ seg: params.segmentation ], masks, table, roi_mask ] }

    RESOLVE_PATCHES ( ch_resolve )
    ch_versions = ch_versions.mix(RESOLVE_PATCHES.out.versions)

    emit:
    mask     = RESOLVE_PATCHES.out.mask   // channel: [ val(meta), path(mask) ]
    table    = MAKE_PATCHES.out.table     // channel: [ val(meta), path(csv) ]
    versions = ch_versions                // channel: [ path(versions.yml) ]
}

//
// Patch index from a patch file name, e.g. S1_patch0012.tif -> '0012'
//
def patchId(file) {
    def match = file.name =~ /_patch(\d+)/
    if (!match.find()) {
        error("Cannot parse patch index from file name: ${file.name}")
    }
    return match.group(1)
}
