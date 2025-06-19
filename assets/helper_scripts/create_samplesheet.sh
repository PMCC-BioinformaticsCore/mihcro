#!/bin/bash

SCRIPTVERSION="0.0.1"
HELP_TEXT="Usage: $(basename "$0") --sample=SAMPLENAME --data=DATAPATH --output=OUTPUTPATH --samplesheet=SAMPLESHEETPATH

This script will rename TIF files located in '--data', replacing special characters including spaces, commas and [ ], with '_'.
The renamed files will be saved in '--output'. A samplesheet will be created containing the sample name, and the path to the renamed TIF files.

Options:
  -h, --help        Show this help message and exit.
  -v, --version     Display script version.
  --sample          Sample name
  --data            Path to folder containing TIF files
  --output          Path to save renamed TIF files
  --samplesheet     Path to save CSV samplesheet

Example:
 create_samplesheet.sh -h
 create_samplesheet.sh --sample=sample_name --data=/path/to/tif/data --output=/path/to/output/tifs --samplesheet=/path/to/samplesheet
"

if [[ $# -ne 1 && $# -ne 4 ]]; then
    echo "When running the script please use only '-h' or '-v' separately."
    echo "Provide all options --sample, --data, --output, --samplesheet"
    echo
    echo "$HELP_TEXT"
    exit 1
fi

# Check for help arguments
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    echo "$HELP_TEXT"
    exit 0
elif [[ "$1" == "-v" || "$1" == "--version" ]]; then
    echo "$(basename "$0") Version: ${SCRIPTVERSION}"
    exit 0
fi

for i in "$@"; do
    case $i in
        --sample=*)
            samplename="${i#*=}"
            shift 
            ;;
        --data=*)
            datadir="${i#*=}"
            shift 
            ;;
        --output=*)
            outputdir="${i#*=}"
            shift 
            ;;
        --samplesheet=*)
            samplesheet="${i#*=}"
            shift 
            ;;
        -*|--*)
            echo "Unknown option $i"
            exit 1
            ;;
    esac
done

logfile=${outputdir}/create_samplesheet_${samplename}.log

mkdir -p ${outputdir}

echo "Commands: $@" > ${logfile} 
echo "" >> ${logfile}
echo "Renaming files in ${datadir}" >? ${logfile}

find ${datadir} -maxdepth 1 -type f -name '*.tif' -print0 | 
while IFS= read -r -d '' FILE; do
    FILENAME=$(basename "$FILE")
    NEWNAME=${FILENAME//[ \[\],]/_}  

    cp "$FILE" ${outputdir}/$NEWNAME
    echo "Copied $FILE as ${outputdir}/$NEWNAME" >> ${logfile}

done

echo "" >> ${logfile}
echo "Creating samplesheet ${samplesheet}" >> ${logfile}

header="sample,tiffs"
echo ${header} > ${samplesheet}
echo "${samplename},${outputdir}" >> ${samplesheet}