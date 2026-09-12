#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct 21 17:05:44 2024

#########################################################################################################################
#########################################################################################################################
###################                                                                                   ###################
################### Title:               DICOM Convert and BIDS Sidecar Harmonization                ###################
###################                                                                                   ###################
################### Description:                                                                      ###################
################### This script converts DICOM data to NIfTI format using dcm2niix and               ###################
################### programmatically updates the resulting JSON sidecar to ensure                    ###################
################### compliance with BIDS (Brain Imaging Data Structure) standards.                   ###################
###################                                                                                   ###################
################### The tool supports advanced metadata handling, including:                         ###################
###################   - Automatic or user-defined slice-order reconstruction                         ###################
###################   - Legacy protocol preservation (LAB-specific behavior)                         ###################
###################   - Generalized slice acquisition modes (ascending, interleaved, stepped)        ###################
###################   - SliceTiming computation                                                      ###################
###################   - TotalReadoutTime and EffectiveEchoSpacing estimation                         ###################
###################   - PhaseEncodingDirection inference with optional manual override               ###################
###################   - Provenance tracking of computed vs manual metadata                           ###################
###################                                                                                   ###################
################### Version:        1.0.0                                                             ###################
###################                                                                                   ###################
################### Requirements:                                                                     ###################
###################   - Python modules: nibabel, dipy, pydicom                                       ###################
###################   - External tool: dcm2niix                                                       ###################
###################                                                                                   ###################
################### Bash Version:   Tested on GNU bash 4.3.48                                        ###################
###################                                                                                   ###################
################### Author:          Gabriele Amorosino                                              ###################
################### Contact:         gabriele.amorosino@utexas.edu                                   ###################
###################                                                                                   ###################
#########################################################################################################################
#########################################################################################################################
###################                                                                                   ###################
################### v0.7.0 Updates:                                                                   ###################
###################   - Introduced generalized slice-order framework                                 ###################
###################   - Added stepped acquisition mode with configurable step size                   ###################
###################   - Preserved legacy LAND-lab acquisition behavior                               ###################
###################   - Improved CLI argument consistency across wrapper and sidecar                 ###################
###################   - Added explicit metadata provenance field                                      ###################
###################                                                                                   ###################
#########################################################################################################################
#########################################################################################################################
###################                                                                                   ###################
################### v0.7.2 Updates:                                                                   ###################
###################   - Renamed --no-fmri to --no-epi (BIDSCard also harmonizes DWI, not just fMRI) ###################
###################                                                                                   ###################
#########################################################################################################################
#########################################################################################################################
###################                                                                                   ###################
################### v0.7.3 Updates:                                                                   ###################
###################   - Added docker/Dockerfile: self-contained runtime (Python + pydicom/numpy +    ###################
###################     dcm2niix), usable via Docker or Singularity/Apptainer with no local install   ###################
###################                                                                                   ###################
#########################################################################################################################
#########################################################################################################################
"""


import os
import shutil
import tempfile
import subprocess
import argparse
import sys
from update_json_sidecar import update_json_with_dicom_info

__title__ = "DICOM Convert and BIDS Sidecar Harmonization"
__version__ = "1.0.0"
__author__ = "Gabriele Amorosino"
__contact__ = "gabriele.amorosino@utexas.edu"

def convert_dicom_to_nifti(dicom_file: str, output_dir: str, tmp_dir: str = None):
    """
    Converts DICOM to NIfTI format using dcm2niix and stores results in output_dir.

    Parameters:
        dicom_file (str): Path to the DICOM file or directory.
        output_dir (str): Output directory for the NIfTI and JSON files.
        tmp_dir (str): Optional. Directory for temporary storage. If not provided, uses a system temporary directory.

    Returns:
        Tuple[str, str]: Paths to the generated NIfTI and JSON files.
    """
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Manage temporary directory
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp()
        cleanup_tmp = True
    else:
        tmp_dir = os.path.abspath(tmp_dir)
        os.makedirs(tmp_dir, exist_ok=True)
        cleanup_tmp = False

    print(f"Using temporary directory: {tmp_dir}")

    # Create a subdirectory for dcm2niix output
    temp_output_dir = os.path.join(tmp_dir, "nifti_output")
    os.makedirs(temp_output_dir, exist_ok=True)

    try:
        # Copy DICOM file(s) to temporary directory
        dicom_basename = os.path.basename(dicom_file)
        tmp_dicom_path = os.path.join(tmp_dir, dicom_basename)
        if os.path.isdir(dicom_file):
            shutil.copytree(dicom_file, tmp_dicom_path)
        else:
            shutil.copy(dicom_file, tmp_dicom_path)

        # Run dcm2niix and output to temp_output_dir
        subprocess.run(
            ["dcm2niix", "-o", temp_output_dir, "-z", "y", "-v", "y", "-f", "%p", tmp_dicom_path],
            check=True
        )

        # Identify generated NIfTI and JSON files in temp_output_dir
        def _stem(fname):
            for ext in (".nii.gz", ".nii", ".json"):
                if fname.endswith(ext):
                    return fname[:-len(ext)]
            return fname

        all_files = os.listdir(temp_output_dir)
        nifti_files = [f for f in all_files if f.endswith(".nii.gz") or f.endswith(".nii")]
        json_files  = [f for f in all_files if f.endswith(".json")]
        if not nifti_files or not json_files:
            raise FileNotFoundError("NIfTI or JSON files were not generated in the temporary directory.")

        # Match NIfTI and JSON by shared filename stem to avoid cross-series pairing
        nifti_by_stem = {_stem(f): f for f in nifti_files}
        json_by_stem  = {_stem(f): f for f in json_files}
        common_stems  = sorted(set(nifti_by_stem) & set(json_by_stem))
        if not common_stems:
            raise FileNotFoundError("No matching NIfTI/JSON pairs found after conversion.")
        if len(common_stems) > 1:
            print(f"Warning: {len(common_stems)} series detected. Processing only: {common_stems[0]}")

        stem = common_stems[0]
        nifti_file = os.path.join(temp_output_dir, nifti_by_stem[stem])
        json_file  = os.path.join(temp_output_dir, json_by_stem[stem])
        
        # Move the files to the output directory
        final_nifti_path = os.path.join(output_dir, os.path.basename(nifti_file))
        final_json_path = os.path.join(output_dir, os.path.basename(json_file))
        shutil.move(nifti_file, final_nifti_path)
        shutil.move(json_file, final_json_path)

        print(f"NIfTI file moved to: {final_nifti_path}")
        print(f"JSON file moved to: {final_json_path}")

        return final_nifti_path, final_json_path

    finally:
        # Clean up temporary directory if created by this function
        if cleanup_tmp:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            print(f"Temporary directory {tmp_dir} cleaned up.")

def main():
    parser = argparse.ArgumentParser(
        description="Convert DICOM to NIfTI and (optionally) update JSON sidecar."
    )
    parser.add_argument("dicom_file", help="Path to the DICOM file or directory.")
    parser.add_argument("output_dir", help="Output directory for the NIfTI and JSON files.")
    parser.add_argument(
        "--no-epi",
        help="Skip JSON-sidecar update (useful for structural or non-EPI data; BIDSCard also handles DWI, not just fMRI).",
        action="store_true",
    )
    parser.add_argument("--exam-card", help="Path to the exam card file.", default=None)
    parser.add_argument("--compute-slice-timing", help="Enable Slice Timing calculation.", action="store_true")
    parser.add_argument("--compute-total-readout", help="Enable Total Readout Time calculation.", action="store_true")
    parser.add_argument("--slice-order", help="Custom slice order as a list of lists.", default=None)
    parser.add_argument("--tmp-dir", help="Optional temporary directory for processing.", default=None)
    parser.add_argument("--scanner-type", help="Scanner type (default: 'Philips').", default="Philips")
    parser.add_argument("--flip-phase-encoding-direction", help="Toggle the sign of the phase encoding direction.", action="store_true")
    parser.add_argument(
    "--phase-encoding-direction",
    help="Manually specify PhaseEncodingDirection (e.g., j, j-, i, i-).",
    default=None)
    parser.add_argument(
    "--slice-order-mode",
    help="Automatic slice-order strategy when --slice-order is not provided.",
    choices=["legacy", "ascending", "interleaved", "stepped"],
    default="legacy",   # this is the safe retrocompatible default      
)
    parser.add_argument(
        "--slice-order-step",
        help=(
            "Step size for slice-order calculation. Used only for "
            "--slice-order-mode stepped (and legacy if you choose it)."
        ),
        type=int,
        default=None,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=(
            "%(prog)s "
            f"v{__version__}  "
            f"Python {sys.version.split()[0]}  "
            f"({sys.platform})"
        ),
    )
    args = parser.parse_args()

    if args.slice_order_step is not None and args.slice_order_step <= 0:
        parser.error("--slice-order-step must be > 0.")

    # Step 1: DICOM → NIfTI
    nifti_file, json_file = convert_dicom_to_nifti(
        args.dicom_file, args.output_dir, tmp_dir=args.tmp_dir
    )

    # Step 2: update JSON sidecar unless the user asked not to
    if not args.no_epi:
        slice_order_step = args.slice_order_step
        if slice_order_step is None:
            slice_order_step = 4 if args.slice_order_mode == "legacy" else 1

        slice_order_mode_was_set = ("--slice-order-mode" in sys.argv)
        slice_order_step_was_set = ("--slice-order-step" in sys.argv)

        if args.slice_order and (slice_order_mode_was_set or slice_order_step_was_set):
            print("Note: --slice-order provided; ignoring --slice-order-mode and --slice-order-step.")

        update_json_with_dicom_info(
            dicom_path=args.dicom_file,
            json_path=json_file,
            output_path=json_file,
            exam_card_path=args.exam_card,
            compute_slice_timing=args.compute_slice_timing,
            user_slice_order=args.slice_order,
            scanner_type=args.scanner_type.upper(),
            calculate_total_readout=args.compute_total_readout,
            flip_phase=args.flip_phase_encoding_direction,
            user_phase_encoding_direction=args.phase_encoding_direction,
            slice_order_mode=args.slice_order_mode,
            slice_order_step=slice_order_step,
        )

if __name__ == "__main__":
    main()
