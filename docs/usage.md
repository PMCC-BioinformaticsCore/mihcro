# nf-core/mihcro: Usage

## Introduction

This document describes the usage of the pipeline, including information on inputs and parameters.

- [Inputs](#inputs)
  - [Samplesheet](#samplesheet)
  - [Markerfile](#markerfile)
  - [Output directory](#output-directory)
  - [Optional pipeline parameters](#optional-pipeline-parameters)
- [Running the pipeline](#running-the-pipeline)
  - [Updating the pipeline](#updating-the-pipeline)
  - [Reproducibility](#reproducibility)
- [Core Nextflow arguments](#core-nextflow-arguments)
- [Custom configuration](#custom-configuration)
- [Running in the background](#running-in-the-background)
- [Nextflow memory requirements](#nextflow-memory-requirements)


## Inputs

### Samplesheet

You will need to create a samplesheet with information about the samples you would like to analyse before running the pipeline. Use this parameter to specify its location. It has to be a comma-separated file with 3 columns and a header row, as shown in the examples below. The samplesheet file should be specified with the `--input` parameter:

```bash
--input '[path to samplesheet file]'
```

An [example samplesheet](../assets/samplesheet.csv) has been provided with the pipeline.

```csv
sample,tiffs,format
SAMPLE_NAME,/path/to/tiff/directory,tiles
```

There are three columns to consider when creating your samplesheet:

- The `sample` column holds the names of your samples.
- The `tiffs` column holds paths pointing to your files. This can be a directory containing multiple tiles, or a path directly to a .tiff or .ome.tiff file which has already been stitched.
- The `format` column refers to what format your files are in and relates directly to the `tiffs` column. `format` can be one of:
  - `tiles` for tiled inputs
  - `stitched` for pre-stitched, ome-tiff inputs
  - `fused` for legacy HALO outputs (indica-format tiff files)

Each row of the samplesheet will be run through the pipeline separately. All rows do not need to follow the same format.

### Markerfile

Currently, this pipeline is designed to be run on samples which have been analysed with the same set of markers. The pipeline requires the markers used in the panel, specified with the `--markers` parameter:

```bash
--markers '[path to markerfile]'
```

The markerfile format is very simple, with each row representing a different channel in your images:

```csv
marker_name
DAPI
CD14
HMWCK
CD3
CD11c
CD4
CD8
Autofluorescence
```

Markers do not need to be listed in any specific order. Note that marker names cannot contain spaces at this time.

### Output directory

The last required input for the pipeline is the `--outdir` parameter, which is simply a path to the directory where you want pipeline outputs to be stored:

```bash
--outdir '[path to output directory]'
```

### Optional pipeline parameters

The following parameters are optional — they either have defaults built-in, or refer to optional steps in the pipeline. Click on a topic's title to expand it for more information.

<details>
<summary><b>Segmentation</b></summary>

The pipeline, by default, runs Mesmer for segmentation. However, there is also the option to run Cellpose instead.

- `--segmentation` (string, default: `mesmer`): Cell segmentation method. Options:
  - `mesmer`
  - `cellpose`

Sometimes, your panel may have the DNA stain stored under a name other than DAPI. In these cases, use the `--nuclear_channel` parameter to specify the channel on which to segment nuclei:

- `--nuclear_channel` (string, default: `DAPI`)

Additionally, you may wish to use a membrane marker in your panel for segmentation alongside the nuclear marker. If this is the case, use `--membrane_channel` to specify the channel to extract for membrane definition:

- `--membrane_channel` (string)

**Cellpose parameters:**

When running Cellpose for segmentation, the default model used is **cyto3**. However, a custom model can be specified:

- `--cellpose_model` (string): Path to your selected model

In addition, the `diameter` parameter for Cellpose can be specified:

- `--cellpose_diam` (integer, default: `15`)

For more information on custom models, model retraining, and diameter selection, see the [Cellpose documentation](cellpose.md).

</details>

<details>
<summary><b>Downscaling</b></summary>

In order to reduce runtime for segmentation in large files, downscaling the resolution of your OME-TIFF file to 1 µm per pixel is recommended. This also regularises the resolution across multiple-sample runs, which can change depending on file format or pre-processing done outside the pipeline.

- `--downscale_mode` (string, default: `1um`): Image downscaling mode. Options:
  - `1um`: Downscale to 1 pixel per 1 µm (recommended)
  - `none`: No downscaling

</details>

<details>
<summary><b>Background Correction</b></summary>

DAPI preprocessing is the other key optional step in the pipeline. This is designed to make segmentation faster and more effective. There are two main parts to this step:

- Binarising the DAPI channel via Otsu thresholding
  - The threshold derived from the Otsu method can be further tweaked using the `--dapi_otsu_leniency` parameter
- Removing background DAPI signal prior to binarisation
  - There are several options for background removal (see below)
  - There is also the option to subtract an autofluorescence channel defined by the user from the DAPI signal

An overview of the options available for this step:

**Method selection:**

- `--dapi_bg_method` (string, default: `none`): Background removal method. Options:
  - `none`: Skip background removal and Otsu thresholding entirely
  - `otsu_only`: Apply only Otsu thresholding without background removal
  - `gaussian`: Gaussian-based background removal
  - `rollingball`: Rolling ball background removal
  - `mean`: Mean-based background removal
  - `af`: Autofluorescence subtraction from the DAPI channel

**Method-specific parameters:**

- `--dapi_bg_sigma` (number, default: `50`): Sigma parameter for the `gaussian` method.
- `--dapi_bg_radius` (integer, default: `50`): Radius parameter for the `rollingball` method.
- `--af_channel` (string): Name of the autofluorescence channel (present in your `markerfile`) for the `af` method.

**Threshold adjustment:**

- `--dapi_otsu_leniency` (number, default: `0.0`, range: `-1.0` to `1.0`): Otsu threshold adjustment factor.
  - Positive values result in a more lenient (lower) threshold from the Otsu step.
  - Negative values result in a stricter (higher) threshold from the Otsu step.

An example usage for background correction:

```bash
--dapi_bg_method 'gaussian' --dapi_bg_sigma 30 --dapi_otsu_leniency 0.5
```

</details>

## Running the pipeline

As this pipeline is not yet on nf-core, you will need to clone it directly into your directory prior to running:

```bash
git clone PMCC-BioinformaticsCore/mihcro
```

The typical command for running the pipeline is as follows:

```bash
nextflow run mihcro \
  --input ./samplesheet.csv \
  --markers ./markerfile.csv \
  --outdir ./results \
  -profile docker
```

This will launch the pipeline with the `docker` configuration profile. See below for more information about profiles.

Note that the pipeline will create the following files in your working directory:

```bash
work                # Directory containing the nextflow working files
<OUTDIR>            # Finished results in specified location (defined with --outdir)
.nextflow_log       # Log file from Nextflow
# Other nextflow hidden files, e.g. history of pipeline runs and old logs.
```

If you wish to repeatedly use the same parameters for multiple runs, rather than specifying each flag in the command, you can specify these in a params file.

Pipeline settings can be provided in a `yaml` or `json` file via `-params-file <file>`.

> [!WARNING]
> Do not use `-c <file>` to specify parameters as this will result in errors. Custom config files specified with `-c` must only be used for [tuning process resource specifications](https://nf-co.re/docs/usage/configuration#tuning-workflow-resources), other infrastructural tweaks (such as output directories), or module arguments (args).

The above pipeline run specified with a params file in yaml format:

```bash
nextflow run nf-core/mihcro -profile docker -params-file params.yaml
```

with:

```yaml
input: './samplesheet.csv'
markers: './markerfile.csv'
outdir: './results/'
```

You can also generate such `YAML`/`JSON` files via [nf-core/launch](https://nf-co.re/launch).

### Updating the pipeline

To make sure that you're running the latest version of the pipeline, regularly update the version you have cloned:

```bash
git clone PMCC-BioinformaticsCore/mihcro
```

### Reproducibility

It is a good idea to specify the pipeline version when running the pipeline on your data. This ensures that a specific version of the pipeline code and software are used when you run your pipeline. If you keep using the same tag, you'll be running the same version of the pipeline, even if there have been changes to the code since.

To further assist in reproducibility, you can share and reuse [parameter files](#running-the-pipeline) to repeat pipeline runs with the same settings without having to write out a command with every single parameter.

> [!TIP]
> If you wish to share such a params file (e.g. as supplementary material for academic publications), make sure to NOT include cluster-specific paths to files, nor institutional-specific profiles.

## Core Nextflow arguments

> [!NOTE]
> These options are part of Nextflow and use a _single_ hyphen (pipeline parameters use a double-hyphen).

### `-profile`

Use this parameter to choose a configuration profile. Profiles can give configuration presets for different compute environments.

Several generic profiles are bundled with the pipeline which instruct the pipeline to use software packaged using different methods (Docker, Singularity, Podman, Shifter, Charliecloud, Apptainer, Conda) — see below.

> [!IMPORTANT]
> We highly recommend the use of Docker or Singularity containers for full pipeline reproducibility. At this time, Conda is not supported for this pipeline.

The pipeline also dynamically loads configurations from [https://github.com/nf-core/configs](https://github.com/nf-core/configs) when it runs, making multiple config profiles for various institutional clusters available at run time. For more information and to check if your system is supported, please see the [nf-core/configs documentation](https://github.com/nf-core/configs#documentation).

Note that multiple profiles can be loaded, for example: `-profile test,docker` — the order of arguments is important. They are loaded in sequence, so later profiles can overwrite earlier profiles.

If `-profile` is not specified, the pipeline will run locally and expect all software to be installed and available on the `PATH`. This is _not_ recommended, since it can lead to different results on different machines dependent on the compute environment.

- `test` — A profile with a complete configuration for automated testing. Includes links to test data so needs no other parameters.
- `docker` — A generic configuration profile to be used with [Docker](https://docker.com/).
- `singularity` — A generic configuration profile to be used with [Singularity](https://sylabs.io/docs/).
- `podman` — A generic configuration profile to be used with [Podman](https://podman.io/).
- `shifter` — A generic configuration profile to be used with [Shifter](https://nersc.gitlab.io/development/shifter/how-to-use/).
- `charliecloud` — A generic configuration profile to be used with [Charliecloud](https://hpc.github.io/charliecloud/).
- `apptainer` — A generic configuration profile to be used with [Apptainer](https://apptainer.org/).
- `wave` — A generic configuration profile to enable [Wave](https://seqera.io/wave/) containers. Use together with one of the above (requires Nextflow `24.03.0-edge` or later).
- `conda` — A generic configuration profile to be used with [Conda](https://conda.io/docs/). Please only use Conda as a last resort, i.e. when it's not possible to run the pipeline with Docker, Singularity, Podman, Shifter, Charliecloud, or Apptainer.

### `-resume`

Specify this when restarting a pipeline. Nextflow will use cached results from any pipeline steps where the inputs are the same, continuing from where it got to previously. For input to be considered the same, not only the names must be identical but the files' contents as well. For more info about this parameter, see [this blog post](https://www.nextflow.io/blog/2019/demystifying-nextflow-resume.html).

You can also supply a run name to resume a specific run: `-resume [run-name]`. Use the `nextflow log` command to show previous run names.

### `-c`

Specify the path to a specific config file (this is a core Nextflow command). See the [nf-core website documentation](https://nf-co.re/usage/configuration) for more information.

## Custom configuration

### Resource requests

Whilst the default requirements set within the pipeline will hopefully work for most people and with most input data, you may find that you want to customise the compute resources that the pipeline requests. Each step in the pipeline has a default set of requirements for number of CPUs, memory and time. For most pipeline steps, if the job exits with any of the error codes specified [here](https://github.com/nf-core/rnaseq/blob/4c27ef5610c87db00c3c5a3eed10b1d161abf575/conf/base.config#L18) it will automatically be resubmitted with higher resource requests (2× original, then 3× original). If it still fails after the third attempt then the pipeline execution is stopped.

To change the resource requests, please see the [max resources](https://nf-co.re/docs/usage/configuration#max-resources) and [tuning workflow resources](https://nf-co.re/docs/usage/configuration#tuning-workflow-resources) sections of the nf-core website.

### Custom containers

In some cases, you may wish to change the container or conda environment used by a pipeline step for a particular tool. By default, nf-core pipelines use containers and software from the [biocontainers](https://biocontainers.pro/) or [bioconda](https://bioconda.github.io/) projects. However, in some cases the pipeline-specified version may be out of date.

To use a different container from the default container or conda environment specified in a pipeline, please see the [updating tool versions](https://nf-co.re/docs/usage/configuration#updating-tool-versions) section of the nf-core website.

### Custom tool arguments

A pipeline might not always support every possible argument or option of a particular tool. Fortunately, nf-core pipelines provide some freedom to users to insert additional parameters that the pipeline does not include by default.

To learn how to provide additional arguments to a particular tool of the pipeline, please see the [customising tool arguments](https://nf-co.re/docs/usage/configuration#customising-tool-arguments) section of the nf-core website.

### nf-core/configs

In most cases, you will only need to create a custom config as a one-off but if you and others within your organisation are likely to be running nf-core pipelines regularly and need to use the same settings regularly, it may be a good idea to request that your custom config file is uploaded to the `nf-core/configs` git repository. Before you do this, please test that the config file works with your pipeline of choice using the `-c` parameter. You can then create a pull request to the `nf-core/configs` repository with the addition of your config file, associated documentation file (see examples in [`nf-core/configs/docs`](https://github.com/nf-core/configs/tree/master/docs)), and amend [`nfcore_custom.config`](https://github.com/nf-core/configs/blob/master/nfcore_custom.config) to include your custom profile.

See the main [Nextflow documentation](https://www.nextflow.io/docs/latest/config.html) for more information about creating your own configuration files.

If you have any questions or issues, please send us a message on [Slack](https://nf-co.re/join/slack) in the [`#configs` channel](https://nfcore.slack.com/channels/configs).

## Running in the background

Nextflow handles job submissions and supervises the running jobs. The Nextflow process must run until the pipeline is finished.

The Nextflow `-bg` flag launches Nextflow in the background, detached from your terminal so that the workflow does not stop if you log out of your session. The logs are saved to a file.

Alternatively, you can use `screen` / `tmux` or a similar tool to create a detached session which you can log back into at a later time. Some HPC setups also allow you to run Nextflow within a cluster job submitted to your job scheduler (from where it submits further jobs).

## Nextflow memory requirements

In some cases, the Nextflow Java virtual machine can start to request a large amount of memory. We recommend adding the following line to your environment to limit this (typically in `~/.bashrc` or `~/.bash_profile`):

```bash
NXF_OPTS='-Xms1g -Xmx4g'
```
