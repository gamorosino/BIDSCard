# Self-contained BIDSCard runtime: Python + pydicom/numpy + dcm2niix, so
# converting/harmonizing DICOM data needs nothing installed on the host beyond
# Docker or Singularity/Apptainer.
FROM python:3.9-slim

WORKDIR /app

# dcm2niix is installed from Debian's package (precompiled binary; the PyPI
# dcm2niix package builds from source via CMake and needs a full C++ toolchain,
# which this apt package avoids). Debian trixie ships 1.0.20241211-1, matching
# the version pinned in requirements.txt / res/config/bidscard.yml.
RUN apt-get update \
    && apt-get install -y --no-install-recommends dcm2niix \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        pydicom==2.4.4 \
        numpy==2.0.2

COPY dcm_convert.py update_json_sidecar.py ./
RUN chmod +x dcm_convert.py update_json_sidecar.py

ENV PATH="/app:${PATH}"
WORKDIR /data
