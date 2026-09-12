#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct 21 17:05:44 2024

#########################################################################################################################
#########################################################################################################################
###################                                                                                   ###################
################### Title:               BIDS JSON Sidecar Harmonization Engine                       ###################
###################                                                                                   ###################
################### Description:                                                                      ###################
################### This module updates and augments JSON sidecar files generated from               ###################
################### DICOM-to-NIfTI conversion to ensure compliance with BIDS standards.              ###################
###################                                                                                   ###################
################### It provides robust metadata handling including:                                  ###################
###################   - SliceTiming reconstruction (automatic or user-defined)                       ###################
###################   - Generalized slice-order modeling (ascending, interleaved, stepped)           ###################
###################   - Preservation of legacy lab-specific acquisition logic                        ###################
###################   - PhaseEncodingDirection inference from DICOM or exam card                     ###################
###################   - TotalReadoutTime and EffectiveEchoSpacing estimation                         ###################
###################   - Philips-specific readout computation support                                 ###################
###################   - Metadata provenance tracking (manual vs computed fields)                     ###################
###################                                                                                   ###################
################### Version:        1.0.0                                                             ###################
###################                                                                                   ###################
################### Requirements:                                                                     ###################
###################   - Python modules: pydicom, numpy                                               ###################
###################                                                                                   ###################
################### Author:          Gabriele Amorosino                                              ###################
################### Contact:         gabriele.amorosino@utexas.edu                                   ###################
###################                                                                                   ###################
#########################################################################################################################
#########################################################################################################################
###################                                                                                   ###################
################### v0.7.0 Updates:                                                                   ###################
###################   - Refactored slice-order logic into legacy and generalized frameworks          ###################
###################   - Introduced stepped acquisition mode with configurable step size              ###################
###################   - Removed hard-coded assumptions from legacy logic                             ###################
###################   - Added validation for user-provided slice-order structures                    ###################
###################   - Added PhaseEncodingDirection provenance annotation                            ###################
###################                                                                                   ###################
#########################################################################################################################
#########################################################################################################################

"""


import os
import pydicom
import json
import numpy as np
import sys
import ast
import re

__title__ = "BIDS JSON Sidecar Harmonization Engine"
__version__ = "1.0.0"
__author__ = "Gabriele Amorosino"
__contact__ = "gabriele.amorosino@utexas.edu"

def _resolve_dicom_file(dicom_path):
    """Return a single DICOM file path; if a directory is given, select the first .dcm file."""
    if os.path.isdir(dicom_path):
        dcm_files = sorted(f for f in os.listdir(dicom_path) if f.lower().endswith(".dcm"))
        if not dcm_files:
            raise FileNotFoundError(f"No .dcm files found in directory: {dicom_path}")
        selected = os.path.join(dicom_path, dcm_files[0])
        print(f"Directory provided; using DICOM file: {selected}")
        return selected
    return dicom_path


def calculate_slice_timing(tr, num_slices, mb_factor, slice_order, sets_per_tr):
    """Calculate slice timing based on acquisition parameters."""
    dt = tr / sets_per_tr  # TR is in seconds (dcm2niix); interval per MB-shot
    slice_timing = np.zeros(num_slices)
    
    for i, slice_group in enumerate(slice_order):
        for slice_index in slice_group:
            slice_timing[slice_index] = i * dt
    return slice_timing.tolist()


def validate_slice_order(slice_order, num_slices, mb_factor):
    if not isinstance(slice_order, list) or not all(isinstance(g, list) for g in slice_order):
        raise ValueError("slice_order must be a list of lists.")

    flat = [s for g in slice_order for s in g]

    if len(flat) != num_slices:
        raise ValueError(f"slice_order covers {len(flat)} slices, expected {num_slices}.")

    if len(set(flat)) != num_slices:
        raise ValueError("slice_order contains duplicate slice indices.")

    if min(flat) < 0 or max(flat) >= num_slices:
        raise ValueError("slice_order indices out of range.")

    if not all(len(g) == mb_factor for g in slice_order):
        raise ValueError("each group in slice_order must have length == mb_factor.")

def shot_order_stepped_with_restart(offset, step):
    order = []
    used = set()
    for start in range(offset):
        i = start
        while i not in used:
            order.append(i)
            used.add(i)
            i = (i + step) % offset
        if len(used) == offset:
            break
    return order

def calculate_correct_slice_order_general(num_slices, mb_factor, mode="ascending", slice_order_step=1):
    if mb_factor is None or mb_factor <= 0:
        raise ValueError("MultiBandFactor must be > 0.")
    if num_slices is None or num_slices <= 0:
        raise ValueError("NumberOfSlices must be > 0.")
    if num_slices % mb_factor != 0:
        raise ValueError("Number of slices must be divisible by MB factor.")

    offset = num_slices // mb_factor

    if mode == "stepped":
        if slice_order_step % offset == 0:
            print(
                f"Warning: slice_order_step={slice_order_step} is a multiple of offset={offset}; "
                "stepped order will degenerate."
            )
            
    if mode == "ascending":
        shot_order = list(range(offset))
    elif mode == "interleaved":
        shot_order = list(range(0, offset, 2)) + list(range(1, offset, 2))
    elif mode == "stepped":
        shot_order = shot_order_stepped_with_restart(offset, slice_order_step)
    else:
        raise ValueError("mode must be 'ascending', 'interleaved', or 'stepped'.")

    return [[i + j * offset for j in range(mb_factor)] for i in shot_order]

def calculate_correct_slice_order_legacy(num_slices, mb_factor, slice_order_step=4):
    """
    Legacy slice-order logic tuned to the original dataset (LAND LAB protocol).
    Assumes mb_factor == 3.
    """
    if mb_factor <= 0:
        raise ValueError("MultiBand Factor (MB Factor) must be > 0.")
    if num_slices % mb_factor != 0:
        raise ValueError("Number of slices must be divisible by MB factor.")

    off = num_slices // mb_factor  # distance between stacks

    LEGACY_MB_FACTOR = 3
    if mb_factor != LEGACY_MB_FACTOR:
        raise ValueError(
            f"Legacy slice order assumes mb_factor={LEGACY_MB_FACTOR}. "
            f"Got mb_factor={mb_factor}. Use slice_order_mode='ascending' or 'interleaved', "
            f"or provide --slice-order."
        )

    slice_order = []
    k = 0
    a_i = 0
    last_stack_offset = (mb_factor - 1) * off  # == 2*off for mb_factor=3

    for shot_idx in range(0, num_slices, mb_factor):
        current_step = 0 if shot_idx == 0 else slice_order_step

        if a_i + current_step + last_stack_offset >= num_slices:
            k += 1
            a_i = k
            current_step = 0

        a_i = a_i + current_step
        group = [a_i + s * off for s in range(mb_factor)]  # size 3 here
        slice_order.append(group)

    validate_slice_order(slice_order, num_slices, mb_factor)
    return slice_order

def calculate_correct_slice_order(num_slices, mb_factor, slice_order_mode="legacy", slice_order_step=1):
    """
    slice_order_mode:
      - "legacy": preserves the original "LANDlab-specific behavior" exactly
      - "ascending": general MB grouping, ascending shot order
      - "interleaved": general MB grouping, interleaved shot order
    """
    if slice_order_mode == "legacy":
        return calculate_correct_slice_order_legacy(num_slices, mb_factor, slice_order_step=slice_order_step)
    else:
        return calculate_correct_slice_order_general(
            num_slices, mb_factor, mode=slice_order_mode, slice_order_step=slice_order_step
        )

def parse_tr_from_exam_card(protocol_details):
    """Extract TR (Repetition Time) from the protocol details, handling various formats."""
    tr = None
    for line in protocol_details.splitlines():
        if "Act. TR/TE (ms)" in line: #or "TR  :" in line:
            match = re.search(r"(\d+)\s*(?:/\s*\d+)?", line)
            if match:
                tr = int(match.group(1))
    return tr


def calculate_total_readout_time(phase_encoding_steps, effective_echo_spacing):
    """Calculate Total Readout Time using DICOM metadata."""
    return (phase_encoding_steps - 1) * effective_echo_spacing


def calculate_total_readout_time_from_philips(dicom_data, json_data):
    """Calculate Total Readout Time using Chris Rorden's Philips formula."""
    water_fat_shift = json_data.get("WaterFatShift", None) or dicom_data.get((2001, 1022), None)
    imaging_frequency = json_data.get("ImagingFrequency", None) or dicom_data.get((0x0018, 0x0084), None)
    epi_factor = json_data.get("EchoTrainLength", None) or dicom_data.get((2001, 1013), None)
    recon_matrix_pe = json_data.get("ReconMatrixPE", None)

    if not all([water_fat_shift, imaging_frequency, epi_factor, recon_matrix_pe]):
        print("Insufficient data to calculate Total Readout Time using Philips formula.")
        return None, None

    try:
        # Chris Rorden's Philips formula. The constant 3.4 is the water-fat chemical
        # shift in ppm (approximate; accepted range 3.4–3.5 ppm at 1.5/3 T).
        # Philips stores EPI factor as N-1 (number of echoes minus 1), hence +1.
        effective_echo_spacing = water_fat_shift / (imaging_frequency * (epi_factor + 1) * 3.4)
        total_readout_time = effective_echo_spacing * (recon_matrix_pe - 1)
        return effective_echo_spacing, total_readout_time
    except Exception as e:
        print(f"Error calculating Philips Total Readout Time: {e}")
        return None, None

def calculate_total_readout_time_from_exam_card(protocol_details):
    """Calculate Total Readout Time using EPI factor and bandwidth from exam card.

    Note: the exam-card path uses `epi_factor` as the number of acquired echoes,
    which on Philips equals the number of phase-encoding lines. This may differ from
    `PhaseEncodingSteps` in the JSON when partial Fourier or oversampling is active.
    Verify against your acquisition protocol if TRT values seem inconsistent.
    """
    epi_factor = None
    bandwidth = None

    for line in protocol_details.splitlines():
        if "EPI factor" in line:
            epi_factor = int(line.split(":")[-1].strip())
        elif "WFS (pix) / BW (Hz)" in line:
            bandwidth = float(line.split("/")[-1].strip().split()[0])

    if epi_factor is None or bandwidth is None:
        raise ValueError("EPI factor or bandwidth not found in exam card protocol.")

    # Effective Echo Spacing in seconds
    effective_echo_spacing = 1 / bandwidth  # Bandwidth is in Hz (cycles per second)
    # Calculate Total Readout Time
    total_readout_time = (epi_factor - 1) * effective_echo_spacing
    total_readout_time = round(total_readout_time, 6)  # Optional: rounding for better precision
    return effective_echo_spacing, total_readout_time



def match_protocol_in_exam_card(series_description, exam_card_path):
    """Match the series description with the corresponding protocol in the exam card."""
    matched_protocol = []
    capture = False
    normalized_series_description = series_description.strip().lower()
    with open(exam_card_path, 'r') as file:
        header = file.read(200)
        if "<soap-env:envelope" in header.lower():
            raise ValueError(
                f"'{exam_card_path}' is a Philips .ExamCard file: a proprietary "
                "SOAP/XML protocol definition for the scanner console's exam-card "
                "editor, not a parameter report. It does not contain readable "
                "acquisition parameters (TR, slices, MB/EPI factor, bandwidth), "
                "and decoding it requires a Philips-proprietary tool this project "
                "does not have. Instead, export the same protocol as .txt or .html "
                "from the scanner console (or a standalone Exam Card viewer) and "
                "pass that file to --exam-card."
            )
        file.seek(0)
        lines = file.readlines()
        for i, line in enumerate(lines):
            normalized_line = line.strip().lower()
            if normalized_series_description in normalized_line and "protocol name:" in normalized_line:
                capture = True
                matched_protocol.append(line)
                continue
            if capture:
                if "protocol name:" in normalized_line and i != 0:
                    break
                matched_protocol.append(line)
    if not matched_protocol:
        print(f"No match found for series: {series_description}")
    return "".join(matched_protocol) if matched_protocol else None


def extract_parameters_from_exam_card(protocol_details):
    """Extract parameters from the protocol details in the exam card."""
    tr = parse_tr_from_exam_card(protocol_details)
    num_slices = None
    mb_factor = None

    for line in protocol_details.splitlines():
        if "EX_STACKS_0__slices" in line:
            num_slices = int(line.split(":")[-1].strip())
        elif "MB Factor" in line:
            mb_factor = int(line.split(":")[-1].strip())

    return tr, num_slices, mb_factor


def determine_phase_encoding_direction(dicom_path, scanner_type="SIEMENS", exam_card_path=None, flip_phase=False, series_description=None):
    """Determine BIDS PhaseEncodingDirection from DICOM or Exam Card, supporting SIEMENS and PHILIPS.

    dicom_path may be None (DICOM-free operation), in which case series_description
    must be supplied to match the Exam Card protocol, and the DICOM-tag polarity
    fallback below is unavailable.
    """
    rowcol_to_niftidim = {'COL': 'j', 'ROW': 'i'}

    # Read DICOM, if provided
    ds = pydicom.dcmread(_resolve_dicom_file(dicom_path)) if dicom_path else {}
    if not series_description:
        series_description = ds.get("SeriesDescription", "Unknown").strip() if dicom_path else "Unknown"
    protocol_details = None
    if exam_card_path:
        protocol_details = match_protocol_in_exam_card(series_description, exam_card_path)
        if protocol_details:
            prep_dir = None
            fat_shift_dir = None
            for line in protocol_details.splitlines():
                if "EX_STACKS_0__prep_dir" in line:
                    prep_dir = line.split(":")[-1].strip().upper()
                if "EX_STACKS_0__fat_shift_dir" in line:
                    fat_shift_dir = line.split(":")[-1].strip().upper()

            if fat_shift_dir == "A":
                pe_dir = "j"
            elif fat_shift_dir == "P":
                pe_dir = "j-"
            elif prep_dir == "AP":
                pe_dir = "j-"
            elif prep_dir == "PA":
                pe_dir = "j"
            elif prep_dir == "LR":
                pe_dir = "i-"
            elif prep_dir == "RL":
                pe_dir = "i"
            else:
                pe_dir = None

            if pe_dir:
                if flip_phase:
                    pe_dir = pe_dir[:-1] if pe_dir.endswith("-") else pe_dir + "-"

                return pe_dir

    if not dicom_path:
        raise ValueError(
            f"Could not determine PhaseEncodingDirection for SeriesDescription: '{series_description}' "
            "without a DICOM file. Provide --phase-encoding-direction explicitly, or an --exam-card "
            "whose protocol resolves it, or a --dicom file."
        )

    inplane_pe_dir = ds.get((0x0018, 0x1312), None)
    if inplane_pe_dir is None:
        raise ValueError(f"InPlanePhaseEncodingDirection not found in DICOM for SeriesDescription: '{series_description}'")

    inplane_pe_dir = rowcol_to_niftidim[inplane_pe_dir.value]
    print(
        f"Warning: PhaseEncodingDirection axis '{inplane_pe_dir}' inferred from DICOM tag (0018,1312). "
        "DICOM does not encode polarity — the sign (+/-) cannot be determined automatically. "
        "Use --phase-encoding-direction or provide an --exam-card to set polarity explicitly."
    )
    if flip_phase:
        inplane_pe_dir = inplane_pe_dir + "-" if "-" not in inplane_pe_dir else inplane_pe_dir[:-1]

    return inplane_pe_dir


def update_json_with_dicom_info(
    json_path,
    output_path,
    dicom_path=None,
    calculate_total_readout=False,
    scanner_type="SIEMENS",
    exam_card_path=None,
    compute_slice_timing=False,
    user_slice_order=None,
    flip_phase=False,
    user_phase_encoding_direction=None,
    slice_order_mode="legacy",
    slice_order_step=1,
    user_series_description=None,
):
    """Update a JSON sidecar from a DICOM file, an Exam Card, and/or manual overrides.

    dicom_path is optional: when omitted, matching an Exam Card protocol requires
    user_series_description (there is no DICOM SeriesDescription to read), and any
    field this function would otherwise infer from the DICOM header must already be
    present in the JSON sidecar, come from the Exam Card, or be supplied manually
    (user_slice_order, user_phase_encoding_direction).
    """

    if exam_card_path and not dicom_path and not user_series_description:
        raise ValueError(
            "Using --exam-card without --dicom requires --series-description, to "
            "identify which Exam Card protocol matches this acquisition."
        )

    # Read the DICOM file, if provided; otherwise ds stands in as an always-empty
    # source so downstream `ds.get(...)`/`getattr(ds, ...)` calls degrade to their
    # JSON/Exam Card/manual fallbacks instead of erroring.
    ds = pydicom.dcmread(_resolve_dicom_file(dicom_path)) if dicom_path else {}
    with open(json_path, 'r') as f:
        json_data = json.load(f)
    pes_raw = json_data.get("PhaseEncodingSteps")
    phase_encoding_steps = int(pes_raw) if pes_raw is not None else None
    ees_raw = json_data.get("EstimatedEffectiveEchoSpacing")
    effective_echo_spacing = float(ees_raw) if ees_raw is not None else None
    tr_raw = json_data.get("RepetitionTime")
    tr = float(tr_raw) if tr_raw is not None else None
    #if tr: tr=tr
    num_slices = json_data.get("NumberOfSlices", None)
    if num_slices: num_slices=int(num_slices)
    mb_factor = json_data.get("MultiBandFactor", None)
    if mb_factor: mb_factor=int(mb_factor)
    series_description = user_series_description or (ds.get("SeriesDescription", "Unknown").strip() if dicom_path else "Unknown")

    print('Read information from provided json file...')
    print("tr: ",tr)
    print("num_slices: ",num_slices)
    print("mb_factor: ",mb_factor)
    print("effective_echo_spacing: ",effective_echo_spacing)
    print("phase_encoding_steps: ",phase_encoding_steps)

    if tr is None:
        tr_dicom = getattr(ds, "RepetitionTime", None)
        if tr_dicom is not None:
            tr = float(tr_dicom) / 1000.0  # DICOM RepetitionTime is in ms; convert to seconds

    if num_slices is None:
        num_slices = getattr(ds, "NumberOfSlices", None)
        if num_slices is not None: num_slices = int(num_slices)

    if mb_factor is None:
        mb_factor = getattr(ds, "MultiBandFactor", None)
        if mb_factor is not None: mb_factor = int(mb_factor)

    if effective_echo_spacing is None:
        effective_echo_spacing = getattr(ds, "EffectiveEchoSpacing", None)
        if effective_echo_spacing is not None: effective_echo_spacing = float(effective_echo_spacing)

    if phase_encoding_steps is None:
        phase_encoding_steps = getattr(ds, "PhaseEncodingSteps", None)
        if phase_encoding_steps is not None: phase_encoding_steps = int(phase_encoding_steps)

    print('Read information from dicom file...')
    print("tr: ",tr)
    print("num_slices: ",num_slices)
    print("mb_factor: ",mb_factor)
    print("effective_echo_spacing: ",effective_echo_spacing)
    print("phase_encoding_steps: ",phase_encoding_steps)


    # Fallback to exam card if parameters are missing
    if tr is None or num_slices is None or mb_factor is None:
        if exam_card_path:
            protocol_details = match_protocol_in_exam_card(series_description, exam_card_path)
            if protocol_details:
                tr_card, slices_card, mb_card = extract_parameters_from_exam_card(protocol_details)
                if tr is None and tr_card is not None:
                    tr = tr_card / 1000.0  # exam card TR is in ms; convert to seconds
                if num_slices is None: num_slices = slices_card
                if mb_factor is None: mb_factor = mb_card

    if tr is None:
        raise ValueError(f"Repetition Time not found SeriesDescription: '{series_description}'")

    if num_slices is None:
        raise ValueError(f"Number of Slices not found SeriesDescription: '{series_description}'")

    if mb_factor is None:
        mb_factor = 1

    print('Read information from exam card file...')
    print("tr: ",tr)
    print("num_slices: ",num_slices)
    print("mb_factor: ",mb_factor)



    # Calculate Slice Timing
    slice_timing = None
    if compute_slice_timing:
        if user_slice_order:
            slice_order = ast.literal_eval(user_slice_order)
            validate_slice_order(slice_order, num_slices, mb_factor)
            print(f"Using user-provided slice order: {slice_order}")
        else:
            # step is only meaningful for "stepped" (and legacy uses it as well)
            effective_step = 1 if slice_order_mode in ("ascending", "interleaved") else slice_order_step

            slice_order = calculate_correct_slice_order(
                num_slices,
                mb_factor,
                slice_order_mode=slice_order_mode,
                slice_order_step=effective_step
            )
            print(f"Using automatic slice order mode: {slice_order_mode}")
            if slice_order_mode == "stepped":
                print(f"Using step size: {effective_step}")
            print(f"Calculated slice order: {slice_order}")

        sets_per_tr = num_slices // mb_factor
        slice_timing = calculate_slice_timing(tr, num_slices, mb_factor, slice_order, sets_per_tr)

    # Determine Phase Encoding Direction
    if user_phase_encoding_direction:
        bids_phase_encoding_direction = user_phase_encoding_direction
        print(f"Using user-provided PhaseEncodingDirection: {bids_phase_encoding_direction}")
    else:
        bids_phase_encoding_direction = determine_phase_encoding_direction(
            dicom_path, scanner_type, exam_card_path, flip_phase=flip_phase, series_description=series_description
        )

    # Calculate Total Readout Time

    if calculate_total_readout:
        protocol_details = None
        if exam_card_path:
            protocol_details = match_protocol_in_exam_card(series_description, exam_card_path)

        # Calculate Total Readout Time
        effective_echo_spacing_philips, total_readout_time_philips = calculate_total_readout_time_from_philips(ds, json_data)

        print("Calculate Total Readout Time")
        if protocol_details:
            effective_echo_spacing_exame, total_readout_time = calculate_total_readout_time_from_exam_card(protocol_details)
        
            if not effective_echo_spacing:
                print("Effective echo spacing is missing from the provided JSON file. The value will be estimated based on the exam card settings.")
                effective_echo_spacing = effective_echo_spacing_exame

        elif total_readout_time_philips is not None:
            total_readout_time = total_readout_time_philips
            if not effective_echo_spacing:
                print("Effective echo spacing is missing from the provided JSON file. The value will be estimated based on the dicom header info.")
                effective_echo_spacing = effective_echo_spacing_philips
        else:
            if effective_echo_spacing is not None:
                total_readout_time = calculate_total_readout_time(phase_encoding_steps, effective_echo_spacing)
            else:
                raise ValueError("Effective echo spacing is missing from the provided JSON file.")
    else:
        trt_raw = json_data.get("EstimatedTotalReadoutTime")
        total_readout_time = float(trt_raw) if trt_raw is not None else None
        print('Set Total Readout Time as EstimatedTotalReadoutTime field of json file')
        if total_readout_time is None and dicom_path:
            trt_dicom = ds.get("EstimatedTotalReadoutTime", None)
            total_readout_time = float(trt_dicom) if trt_dicom is not None else None
        if total_readout_time is None:
            raise ValueError('EstimatedTotalReadoutTime missed from json file...')
    # Heuristic unit guard: valid TRT in seconds is always < 10 s; if larger, value is likely in ms.
    if total_readout_time is not None and total_readout_time > 10:
        total_readout_time /= 1000.0


    # Update JSON
    with open(json_path, 'r') as f:
        json_data = json.load(f)

    if slice_timing:
        json_data["SliceTiming"] = slice_timing
    json_data["TotalReadoutTime"] = total_readout_time
    if effective_echo_spacing is not None:
        json_data["EffectiveEchoSpacing"] = effective_echo_spacing
    json_data["PhaseEncodingDirection"] = bids_phase_encoding_direction
    # provenance field (safe, optional metadata extension)
    json_data["PhaseEncodingDirectionSource"] = (
        "manual" if user_phase_encoding_direction else "computed"
    )
    print("Slice Timing: ",slice_timing)
    print("Total Readout Time: ",total_readout_time)
    print("Effective echo spacing: ",effective_echo_spacing)
    print("Phase Encoding Direction: ",bids_phase_encoding_direction)


    with open(output_path, 'w') as f:
        json.dump(json_data, f, indent=4)

    print(f"Updated JSON saved to {output_path}")
def print_help():
    print("""
Usage:
  python update_json_sidecar.py <json_file> <output_file>
      [--dicom <path>]
      [--exam-card <path>]
      [--series-description <name>]
      [--compute-slice-timing]
      [--slice-order "<json_string>"]
      [--slice-order-mode legacy|ascending|interleaved|stepped]
      [--slice-order-step <int>]
      [--phase-encoding-direction "<dir>"]
      [--flip-phase]

Options:
  --dicom <path>
      Path to the DICOM file this sidecar corresponds to. Optional: without
      it, BIDSCard operates DICOM-free, using only the existing JSON sidecar,
      an --exam-card, and/or manual overrides (--phase-encoding-direction,
      --slice-order). Any field this tool would otherwise infer from the
      DICOM header must already be present in the JSON sidecar, come from
      the Exam Card, or be supplied manually.

  --exam-card <path>
      Path to a Philips Exam Card .txt/.html export, used to recover fields
      absent from the DICOM header (or absent entirely, when no DICOM is
      given). Requires --dicom or --series-description to identify which
      Exam Card protocol matches this acquisition.

  --series-description <name>
      Manually specify the acquisition's SeriesDescription, to match the
      corresponding Exam Card protocol. Required when using --exam-card
      without --dicom, since there is then no DICOM SeriesDescription to
      read automatically.

  --compute-slice-timing
      Enable SliceTiming calculation.

  --slice-order
      Provide a custom slice acquisition order (as a JSON string).
      If specified, the script will skip automatic slice-order calculation and use the user-provided order.
      Example: --slice-order "[[0,12,24],[1,13,25],[2,14,26]]"

  --slice-order-mode
      Automatic slice-order strategy used only when --slice-order is NOT provided.
      Choices: legacy, ascending, interleaved, stepped
      Default: legacy (preserves original lab-specific behavior)
          
  --slice-order-step
      Step size used only for:
        - slice-order-mode=stepped (general stepped cycling), and
        - slice-order-mode=legacy (defaults to 4 if not provided).
      Default: 1 (except legacy defaults to 4).
          
  --phase-encoding-direction
      Manually specify PhaseEncodingDirection (e.g., "j", "j-", "i", "i-").
      If specified, it overrides DICOM/ExamCard inference.
      
  --flip-phase
      Toggle the sign of the inferred phase encoding direction.

  --scanner-type <type>
      Scanner type for metadata inference (default: PHILIPS).
      Example: --scanner-type SIEMENS

  --compute-total-readout
      Enable calculation of TotalReadoutTime and EffectiveEchoSpacing.
      If not set, EstimatedTotalReadoutTime from the JSON/DICOM is used.
""")


if __name__ == '__main__':
    if "--version" in sys.argv:
        print(f"update_json_sidecar.py v{__version__}  Python {sys.version.split()[0]}  ({sys.platform})")
        sys.exit(0)

    if len(sys.argv) < 3:
        print_help()
        sys.exit(1)

    json_file = sys.argv[1]
    output_file = sys.argv[2]

    dicom_file = None
    if "--dicom" in sys.argv:
        try:
            dicom_file = sys.argv[sys.argv.index("--dicom") + 1]
        except IndexError:
            print("Error: --dicom requires a path argument.")
            sys.exit(1)

    exam_card_file = None
    if "--exam-card" in sys.argv:
        try:
            exam_card_file = sys.argv[sys.argv.index("--exam-card") + 1]
        except IndexError:
            print("Error: --exam-card requires a path argument.")
            sys.exit(1)

    series_description_arg = None
    if "--series-description" in sys.argv:
        try:
            series_description_arg = sys.argv[sys.argv.index("--series-description") + 1]
        except IndexError:
            print("Error: --series-description requires a value.")
            sys.exit(1)

    compute_slice_timing = "--compute-slice-timing" in sys.argv
    slice_order_arg = None
    if "--slice-order" in sys.argv:
        try:
            slice_order_arg = sys.argv[sys.argv.index("--slice-order") + 1]
        except IndexError:
            print("Error: --slice-order requires a slice order as its argument.")
            sys.exit(1)
    slice_order_mode = "legacy"
    if "--slice-order-mode" in sys.argv:
        try:
            slice_order_mode = sys.argv[sys.argv.index("--slice-order-mode") + 1]
        except IndexError:
            print("Error: --slice-order-mode requires an argument (legacy|ascending|interleaved).")
            sys.exit(1)

        if slice_order_mode not in ("legacy", "ascending", "interleaved", "stepped"):
            print("Error: --slice-order-mode must be one of: legacy, ascending, interleaved, stepped.")
            sys.exit(1)
    phase_encoding_direction = None

    if "--phase-encoding-direction" in sys.argv:
        try:
            phase_encoding_direction = sys.argv[sys.argv.index("--phase-encoding-direction") + 1]
        except IndexError:
            print("Error: --phase-encoding-direction requires a value (e.g., j, -j, i, -i).")
            sys.exit(1)
    flip_phase = "--flip-phase" in sys.argv

    scanner_type = "PHILIPS"
    if "--scanner-type" in sys.argv:
        try:
            scanner_type = sys.argv[sys.argv.index("--scanner-type") + 1].upper()
        except IndexError:
            print("Error: --scanner-type requires an argument (e.g., PHILIPS, SIEMENS).")
            sys.exit(1)

    calculate_total_readout = "--compute-total-readout" in sys.argv

    slice_order_step = 1
    step_was_set = ("--slice-order-step" in sys.argv)

    if step_was_set:
        try:
            slice_order_step = int(sys.argv[sys.argv.index("--slice-order-step") + 1])
        except (IndexError, ValueError):
            print("Error: --slice-order-step requires an integer argument (e.g., 4).")
            sys.exit(1)
    if slice_order_step <= 0:
        print("Error: --slice-order-step must be > 0.")
        sys.exit(1)

    if not step_was_set and slice_order_mode == "legacy":
        slice_order_step = 4


    update_json_with_dicom_info(
    json_file,
    output_file,
    dicom_path=dicom_file,
    calculate_total_readout=calculate_total_readout,
    scanner_type=scanner_type,
    exam_card_path=exam_card_file,
    compute_slice_timing=compute_slice_timing,
    user_slice_order=slice_order_arg,
    flip_phase=flip_phase,
    user_phase_encoding_direction=phase_encoding_direction,
    slice_order_mode=slice_order_mode,
    slice_order_step=slice_order_step,
    user_series_description=series_description_arg,
)