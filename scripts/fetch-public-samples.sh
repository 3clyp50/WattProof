#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$script_directory/.." && pwd)"
destination_directory="$repository_root/tmp/public-samples"
temporary_file=""

cleanup() {
  if [[ -n "$temporary_file" && -e "$temporary_file" ]]; then
    rm -f -- "$temporary_file"
  fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if command -v sha256sum >/dev/null 2>&1; then
  hash_command="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  hash_command="shasum"
else
  printf 'error: sha256sum or shasum is required\n' >&2
  exit 1
fi

sha256_file() {
  local path="$1"
  if [[ "$hash_command" == "sha256sum" ]]; then
    sha256sum -- "$path" | awk '{print $1}'
  else
    shasum -a 256 -- "$path" | awk '{print $1}'
  fi
}

download_file() {
  local url="$1"
  local output="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error \
      --connect-timeout 20 --max-time 180 --output "$output" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --quiet --timeout=180 --output-document="$output" "$url"
  else
    printf 'error: curl or wget is required\n' >&2
    return 1
  fi
}

fetch_sample() {
  local filename="$1"
  local expected_sha256="$2"
  local url="$3"
  local destination="$destination_directory/$filename"
  local actual_sha256

  if [[ -e "$destination" || -L "$destination" ]]; then
    if [[ ! -f "$destination" || -L "$destination" ]]; then
      printf 'error: refusing non-regular existing path: %s\n' "$destination" >&2
      return 1
    fi
    actual_sha256="$(sha256_file "$destination")"
    if [[ "$actual_sha256" != "$expected_sha256" ]]; then
      printf 'error: existing %s has SHA-256 %s; expected %s\n' \
        "$filename" "$actual_sha256" "$expected_sha256" >&2
      printf 'error: the existing file was not replaced\n' >&2
      return 1
    fi
    printf 'Reusing verified %s\n' "$destination"
    return 0
  fi

  temporary_file="$(mktemp "$destination_directory/.download.${filename}.XXXXXX")"
  download_file "$url" "$temporary_file"
  actual_sha256="$(sha256_file "$temporary_file")"
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    printf 'error: downloaded %s has SHA-256 %s; expected %s\n' \
      "$filename" "$actual_sha256" "$expected_sha256" >&2
    return 1
  fi

  if [[ -e "$destination" || -L "$destination" ]]; then
    printf 'error: destination appeared while downloading; refusing to replace %s\n' \
      "$destination" >&2
    return 1
  fi
  if ! ln "$temporary_file" "$destination"; then
    printf 'error: could not publish without replacing an existing path: %s\n' \
      "$destination" >&2
    return 1
  fi
  rm -f -- "$temporary_file"
  temporary_file=""
  printf 'Downloaded and verified %s\n' "$destination"
}

mkdir -p "$destination_directory"

fetch_sample \
  "duke-electricity.pdf" \
  "b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a" \
  "https://www.duke-energy.com/-/media/pdfs/bill-examples/260482-bill-tutorial-handout-res-dei.pdf"
fetch_sample \
  "centerpoint-gas.pdf" \
  "c0b7d9b0252226078b39d6760308506c28b388729906d3ac54db950b9f819262" \
  "https://www.centerpointenergy.com/en-us/CustomerService/Documents/bill-guides/240312-20-EIP-IN%20Gas-bill-guide.pdf"
fetch_sample \
  "bloomington-water.pdf" \
  "a414c296e3dd71a08aa459bb1a7c38fcdeab0c90aa0bb05f7c4e39ae9d70b79c" \
  "https://bloomington.in.gov/sites/default/files/2026-02/Understanding%20Your%20Water%20Bill%202026%20Accessible.pdf"
