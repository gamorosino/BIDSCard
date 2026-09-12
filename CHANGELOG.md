# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0] - 2026-09-11

### Added

- **`update_json_sidecar.py` can now run without a DICOM file.** Previously
  it unconditionally read a DICOM (`pydicom.dcmread(...)` ran regardless of
  whether any of its fields were actually needed), making it a hard
  requirement even for post-hoc corrections that could otherwise be driven
  entirely by the JSON sidecar, an Exam Card, and/or manual overrides. The
  DICOM is now supplied via an optional `--dicom <path>` flag; without it,
  the tool operates DICOM-free using the existing JSON sidecar, an
  `--exam-card`, and/or manual overrides (`--phase-encoding-direction`,
  `--slice-order`). Since matching an Exam Card protocol block ordinarily
  relies on the DICOM's `SeriesDescription`, a new `--series-description
  <name>` flag lets that be supplied manually instead. Using `--exam-card`
  without `--dicom` now requires `--series-description`, and raises a clear
  error if it's missing.

### Fixed

- **`requirements.txt`** — Bumps the pinned `dcm2niix` version from
  `1.0.20241211` to `1.0.20260724`. The old pin built from source via CMake
  and failed on current systems: its bundled `ucm.cmake` set
  `cmake_minimum_required(VERSION 2.8.12)`, and CMake has since removed
  compatibility with versions below 3.5, making `pip install -r
  requirements.txt` fail outright on any host with a modern CMake. The new
  pin ships a prebuilt manylinux wheel, so it doesn't need to build from
  source at all. (Conda and Docker installs were unaffected, since they
  already install prebuilt `dcm2niix` binaries via conda-forge/apt.)
- **`update_json_sidecar.py`'s total-readout-time fallback** — Guarded a
  latent crash: when `EstimatedTotalReadoutTime` was absent from the JSON
  sidecar (and `--compute-total-readout` wasn't passed), the code called
  `float(ds.get("EstimatedTotalReadoutTime", None))`, which raised
  `TypeError` instead of the intended `ValueError` whenever that DICOM
  field was also absent (essentially always, since it isn't a standard
  DICOM tag).

### Changed

- **`update_json_sidecar.py`'s CLI signature.** `<dicom_file>` is no
  longer a required positional argument; usage is now
  `update_json_sidecar.py <json_file> <output_file> [--dicom <path>]
  [--exam-card <path>] [--series-description <name>] [options]`. The Exam
  Card path is likewise `--exam-card`-only now (the undocumented
  positional-4th-argument form, briefly supported for backward
  compatibility earlier in this same release, is removed).
- **Project renamed from FixSidecar to BIDSCard.** The tool, repository, and
  Docker Hub image (`gamorosino/bidscard`, replacing `gamorosino/fixsidecar`)
  are now named BIDSCard; no functional change beyond the above. The former
  `gamorosino/fixSidecar` repository has been marked deprecated and points
  here.

---

## [0.7.3] - 2026-08-07

### Added

- **`docker/Dockerfile`** — Self-contained runtime image (Python 3.9 + `pydicom`,
  `numpy`, and `dcm2niix` installed from Debian's package) so `dcm_convert.py`
  and `update_json_sidecar.py` can be run via Docker or Singularity/Apptainer
  without installing anything locally. See the README's "Running via Docker /
  Singularity / Apptainer" section. Published as `gamorosino/bidscard` on
  Docker Hub.
- **Clear error for `.ExamCard` input** — `--exam-card` now detects Philips's
  proprietary SOAP/XML `.ExamCard` format (the scanner console's protocol-editor
  export) and raises a descriptive `ValueError` instead of silently reporting
  "no match" per series. That format carries no readable acquisition parameters
  and would require a Philips-proprietary decoder we don't have; the message
  points users to the `.txt`/`.html` export of the same protocol, which
  BIDSCard already parses successfully.

---

## [0.7.2] - 2026-08-07

### Changed

- **`dcm_convert.py`** — Renamed `--no-fmri` to `--no-epi`. BIDSCard's sidecar
  harmonization applies to any EPI acquisition (fMRI and DWI alike), not just fMRI,
  so `--no-fmri` was a misleading name for what it actually skips. This is a
  breaking CLI change: update any scripts that pass `--no-fmri`.

---

## [0.7.1] - 2026-07-16

### Fixed

- **`update_json_sidecar.py`** — `TotalReadoutTime` unit conversion used a divisor of 100
  instead of 1000, producing a 10× systematic error when the raw value was in milliseconds.
  The threshold for triggering the conversion was also tightened from `> 1` to `> 10`
  (valid TRT in seconds is always below 10 s for any real MRI acquisition).

- **`update_json_sidecar.py`** — `RepetitionTime` read from the DICOM header was stored
  without converting from milliseconds to seconds (DICOM tag 0018,0080 is in ms; dcm2niix
  JSON stores TR in seconds). This caused SliceTiming to be computed ~1000× too large when
  TR was not present in the JSON sidecar. The same conversion is now applied when TR is
  obtained from the Philips Exam Card.

- **`update_json_sidecar.py`** — `PhaseEncodingDirection` inferred from DICOM tag
  (0018,1312) carries axis information only (`i`/`j`) with no polarity sign. The tool now
  prints an explicit warning when falling back to DICOM-only inference, instructing the user
  to set polarity via `--phase-encoding-direction` or `--exam-card`.

- **`update_json_sidecar.py`** — `calculate_correct_slice_order_legacy` had no
  post-generation validation of the produced slice order. A call to `validate_slice_order()`
  is now performed after generation to catch any miscoverage or duplicate indices.

- **`update_json_sidecar.py`** — `EffectiveEchoSpacing` was unconditionally written to the
  output JSON even when its value was `None`, producing an invalid `null` entry not allowed
  by the BIDS specification. The field is now written only when a value is available.

- **`update_json_sidecar.py`** — The fallback logic to replace a missing
  `EffectiveEchoSpacing` with the Exam Card or Philips estimate used `== 0` instead of
  `is None`, silently skipping the fallback when the value was absent (`None`).
  Changed to `if not effective_echo_spacing`.

- **`update_json_sidecar.py`** — `pydicom.dcmread()` was called directly on the path
  provided by the user, which may be a directory (e.g., when a DICOM folder is passed).
  A new helper `_resolve_dicom_file()` now selects the first `.dcm` file from a directory
  before reading, raising a clear error if none is found.

- **`update_json_sidecar.py`** — All metadata presence checks (`if not tr`, `if not
  num_slices`, etc.) used truthiness tests that conflate `None` with `0`, risking incorrect
  fallback behaviour for numerically zero values. Changed to explicit `if x is None` checks
  throughout.

- **`dcm_convert.py`** — When `dcm2niix` produced multiple NIfTI/JSON pairs (e.g., from a
  DICOM directory containing more than one series), only the first file in filesystem order
  was selected, potentially pairing a NIfTI from one series with the JSON of another.
  Files are now matched by shared filename stem; a warning is printed if multiple series are
  detected.

### Changed

- **`dcm_convert.py`** — `dcm2niix` is now invoked with `-z y` to produce gzip-compressed
  `.nii.gz` output, consistent with BIDS recommendations. Previously `-z n` produced
  uncompressed `.nii` files.

- **`update_json_sidecar.py`** — The standalone CLI (`__main__`) previously hard-coded
  `scanner_type="PHILIPS"` and `calculate_total_readout=False` with no way to override
  them. Two new options have been added:
  - `--scanner-type <type>` (default: `PHILIPS`)
  - `--compute-total-readout`

### Documentation / Comments

- Added inline comment in `calculate_total_readout_time_from_philips` explaining the
  water-fat chemical shift constant (3.4 ppm, Chris Rorden's heuristic) and the Philips
  convention that EPI factor is stored as N−1 (hence `epi_factor + 1` in the denominator).

- Added docstring note in `calculate_total_readout_time_from_exam_card` clarifying that
  the Exam Card path uses `epi_factor` as the number of acquired echoes, which may differ
  from `PhaseEncodingSteps` when partial Fourier or oversampling is active.

---

## [0.7.0] - 2025-10-21

### Added

- Generalized slice-order framework with four acquisition modes: `ascending`,
  `interleaved`, `stepped`, and `legacy`.
- Stepped acquisition mode with configurable step size (`--slice-order-step`).
- Validation of user-provided slice orders (full coverage, no duplicates, correct
  multi-band grouping).
- `PhaseEncodingDirectionSource` provenance field written to the output JSON sidecar
  (`"manual"` or `"computed"`).
- `--version` flag for both `dcm_convert.py` and `update_json_sidecar.py`.

### Changed

- Legacy acquisition logic refactored and isolated into
  `calculate_correct_slice_order_legacy`; preserved as backward-compatible default.
- CLI argument naming made consistent between `dcm_convert.py` and
  `update_json_sidecar.py`.

---

## [0.1.0] - 2024-10-21

### Added

- Initial release.
- DICOM-to-NIfTI conversion via `dcm2niix` wrapper (`dcm_convert.py`).
- BIDS JSON sidecar harmonization (`update_json_sidecar.py`).
- Metadata inference from DICOM headers and Philips Exam Card files.
- Computation of `SliceTiming`, `TotalReadoutTime`, `EffectiveEchoSpacing`, and
  `PhaseEncodingDirection`.
