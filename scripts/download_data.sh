#!/usr/bin/env bash
# Idempotently download the public EHR datasets used by Task 1+:
#   - Synthea sample data (FHIR R4 JSON + CSV, ~100 synthetic patients)
#   - MIMIC-IV demo (CSV, 100 deidentified ICU patients)
#
# Re-running skips datasets that are already present on disk.
# Output: data/synthea/{fhir,csv}/ and data/mimic_iv_demo/

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT_DIR/data"
SYNTHEA_FHIR_DIR="$DATA_DIR/synthea/fhir"
SYNTHEA_CSV_DIR="$DATA_DIR/synthea/csv"
MIMIC_DIR="$DATA_DIR/mimic_iv_demo"

SYNTHEA_FHIR_URL="https://raw.githubusercontent.com/synthetichealth/synthea-sample-data/main/downloads/synthea_sample_data_fhir_r4_nov2021.zip"
SYNTHEA_CSV_URL="https://raw.githubusercontent.com/synthetichealth/synthea-sample-data/main/downloads/synthea_sample_data_csv_nov2021.zip"
MIMIC_URL="https://physionet.org/content/mimic-iv-demo/get-zip/2.2/"

mkdir -p "$DATA_DIR"

fetch_and_unzip() {
    local label="$1"
    local url="$2"
    local target_dir="$3"
    local marker="$4"   # path of a file we expect to exist post-extract

    if [ -e "$marker" ]; then
        echo "[$label] already present at $target_dir — skipping"
        return 0
    fi

    echo "[$label] downloading from $url"
    local tmpzip
    tmpzip="$(mktemp -t download_data.XXXXXX).zip"
    trap 'rm -f "$tmpzip"' EXIT

    curl -fLo "$tmpzip" "$url"

    mkdir -p "$target_dir"
    echo "[$label] extracting to $target_dir"
    unzip -q -o "$tmpzip" -d "$target_dir"

    rm -f "$tmpzip"
    trap - EXIT
    echo "[$label] done"
}

fetch_and_unzip "synthea-fhir" "$SYNTHEA_FHIR_URL" "$SYNTHEA_FHIR_DIR" "$SYNTHEA_FHIR_DIR/fhir"
fetch_and_unzip "synthea-csv"  "$SYNTHEA_CSV_URL"  "$SYNTHEA_CSV_DIR"  "$SYNTHEA_CSV_DIR/csv/patients.csv"
fetch_and_unzip "mimic-iv-demo" "$MIMIC_URL"      "$MIMIC_DIR"        "$MIMIC_DIR/mimic-iv-clinical-database-demo-2.2/hosp/patients.csv.gz"

echo ""
echo "All datasets ready under $DATA_DIR"
echo "  Synthea FHIR patient bundles: $(ls "$SYNTHEA_FHIR_DIR"/fhir/*.json 2>/dev/null | wc -l | tr -d ' ')"
echo "  Synthea CSV tables:           $(ls "$SYNTHEA_CSV_DIR"/csv/*.csv 2>/dev/null | wc -l | tr -d ' ')"
echo "  MIMIC patient rows:           $(zcat < "$MIMIC_DIR/mimic-iv-clinical-database-demo-2.2/hosp/patients.csv.gz" 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')"
