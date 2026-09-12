# Self-contained BIDSCard runtime: Python + pydicom/numpy + dcm2niix, so
# converting/harmonizing DICOM data needs nothing installed on the host beyond
# Docker or Singularity/Apptainer.
FROM python:3.9-slim

WORKDIR /app

# dcm2niix is installed from Debian's package (precompiled binary, avoiding
# a from-source build). Debian trixie ships 1.0.20241211-1; this may differ
# from the version pinned in requirements.txt / res/config/bidscard.yml,
# which is fine since dcm2niix's DICOM parsing and BIDS output have been
# stable across these releases.
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
