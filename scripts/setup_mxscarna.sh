#!/usr/bin/env bash
# Build mxscarnamod and install it into the pixi "seed" environment.
#
# Not expected to run, even on a fresh clone. The routine alignment build needs only mafft +
# Infernal's cmalign, both supplied by the "align" pixi environment; the NCR covariance models
# themselves are committed as inputs-of-record under registry/alignment_seeds/. This script exists
# solely to reconstruct a covariance model from scratch, which is a rare, explicitly-invoked
# operation gated on registry/alignment_seeds/ being absent -- see align/toolchain.py's
# `resolve(..., environment=ENV_SEED, tools=SEED_TOOLS)` and docs/reproducibility.md's
# "The alignment toolchain" section.
#
# Why this exists at all: bioconda's mafft package omits the mxscarnamod helper binary, so
# mafft-xinsi and mafft-qinsi fail outright ("Please 'make' at the 'extensions' directory...")
# until it is compiled from a separate source tarball. Verified 2026-07-30: the tarball builds
# cleanly with the system compiler (g++, C++98, no non-standard flags) in well under a minute.
#
# Requires: network access to mafft.cbrc.jp, and a C++ compiler (make + g++/clang). Both are
# genuinely optional prerequisites -- the pixi "align" environment needs neither.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED_ENV="${REPO_ROOT}/.pixi/envs/seed"
LIBEXEC_MAFFT="${SEED_ENV}/libexec/mafft"

# Pinned by sha256, not by trusting the download. mafft's own release notes call this version
# skew (extensions built from 7.525 source, conda env resolves mafft 7.526) insensitive; upstream
# ran it this way without incident.
SOURCE_URL="https://mafft.cbrc.jp/alignment/software/mafft-7.525-with-extensions-src.tgz"
SOURCE_SHA256="2876f4adc1a2de4ed206bc40896763bf208bf1a02bda52f8bfdd91cf52d73e4a"

if [[ ! -d "${SEED_ENV}" ]]; then
  echo "error: ${SEED_ENV} does not exist. Run \`pixi install --locked -e seed\` first." >&2
  exit 1
fi

if [[ -x "${LIBEXEC_MAFFT}/mxscarnamod" ]]; then
  echo "mxscarnamod is already installed at ${LIBEXEC_MAFFT}/mxscarnamod; nothing to do."
  echo "Delete it first if you want to rebuild from a fresh download."
  exit 0
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

ARCHIVE="${WORK_DIR}/mafft-7.525-with-extensions-src.tgz"
echo "Fetching ${SOURCE_URL} ..."
curl -sL --max-time 300 "${SOURCE_URL}" -o "${ARCHIVE}"

ACTUAL_SHA256="$(shasum -a 256 "${ARCHIVE}" | cut -d' ' -f1)"
if [[ "${ACTUAL_SHA256}" != "${SOURCE_SHA256}" ]]; then
  echo "error: downloaded tarball sha256 ${ACTUAL_SHA256} does not match the pinned" \
       "${SOURCE_SHA256}. Refusing to build from an unverified source. If mafft.cbrc.jp has" \
       "republished this version deliberately, verify the new file out-of-band and update" \
       "SOURCE_SHA256 in this script." >&2
  exit 1
fi
echo "sha256 verified."

tar xzf "${ARCHIVE}" -C "${WORK_DIR}"
EXTRACTED_DIR="${WORK_DIR}/mafft-7.525-with-extensions"
if [[ ! -d "${EXTRACTED_DIR}/extensions" ]]; then
  echo "error: expected ${EXTRACTED_DIR}/extensions after extraction; the tarball layout changed." >&2
  exit 1
fi

echo "Building mxscarnamod ..."
make -C "${EXTRACTED_DIR}/extensions"

BUILT="${EXTRACTED_DIR}/extensions/mxscarnamod"
if [[ ! -x "${BUILT}" ]]; then
  echo "error: build did not produce an executable mxscarnamod." >&2
  exit 1
fi

mkdir -p "${LIBEXEC_MAFFT}"
install -m 755 "${BUILT}" "${LIBEXEC_MAFFT}/mxscarnamod"

# The liveness probe align/toolchain.py's seed-tier resolution repeats: mxscarnamod refuses to run
# with no arguments (exit 1, by design -- it is not a missing-executable failure), but its usage
# banner names itself. A missing or broken binary would fail differently -- "command not found" or
# a linker error -- so the two are distinguishable.
#
# Captured with `|| true` before grepping it, not piped directly into grep: under `pipefail`, a
# pipeline's exit status is mxscarnamod's own non-zero one regardless of whether grep found its
# match, so `mxscarnamod | grep -q SCARNA` fails this check even when the probe legitimately
# passes. Found by running the probe, not by reasoning about it.
PROBE_OUTPUT="$("${LIBEXEC_MAFFT}/mxscarnamod" 2>&1 || true)"
if ! grep -q "SCARNA" <<<"${PROBE_OUTPUT}"; then
  echo "error: mxscarnamod was installed but does not respond to the liveness probe." >&2
  exit 1
fi

echo "mxscarnamod installed at ${LIBEXEC_MAFFT}/mxscarnamod and passes its liveness probe."
