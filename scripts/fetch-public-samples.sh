#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -P "$script_directory/.." && pwd -P)"
tmp_directory="$repository_root/tmp"
destination_directory="$tmp_directory/public-samples"
temporary_file=""
repository_identity=""
tmp_identity=""
destination_identity=""

cleanup() {
  if [[ -n "$temporary_file" && -f "$temporary_file" && ! -L "$temporary_file" ]]; then
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

if stat -f '%d:%i' "$repository_root" >/dev/null 2>&1; then
  stat_style="bsd"
elif stat -c '%d:%i' "$repository_root" >/dev/null 2>&1; then
  stat_style="gnu"
else
  printf 'error: a macOS or Linux stat implementation is required\n' >&2
  exit 1
fi

path_identity() {
  local path="$1"
  if [[ "$stat_style" == "bsd" ]]; then
    stat -f '%d:%i' "$path"
  else
    stat -c '%d:%i' "$path"
  fi
}

prepare_destination_directory() {
  local physical_tmp
  local physical_destination

  cd -P "$repository_root"
  repository_identity="$(path_identity .)"

  if [[ -L "tmp" ]]; then
    printf 'error: refusing symlinked path component: %s\n' "$tmp_directory" >&2
    return 1
  fi
  if [[ -e "tmp" ]]; then
    if [[ ! -d "tmp" ]]; then
      printf 'error: refusing non-directory path component: %s\n' \
        "$tmp_directory" >&2
      return 1
    fi
  else
    mkdir "tmp"
  fi

  cd -P "tmp"
  physical_tmp="$(pwd -P)"
  if [[ "$physical_tmp" != "$tmp_directory" ]]; then
    printf 'error: temporary directory escaped physical repository root: %s\n' \
      "$physical_tmp" >&2
    return 1
  fi
  tmp_identity="$(path_identity .)"

  if [[ -L "public-samples" ]]; then
    printf 'error: refusing symlinked path component: %s\n' \
      "$destination_directory" >&2
    return 1
  fi
  if [[ -e "public-samples" ]]; then
    if [[ ! -d "public-samples" ]]; then
      printf 'error: refusing non-directory path component: %s\n' \
        "$destination_directory" >&2
      return 1
    fi
  else
    mkdir "public-samples"
  fi

  cd -P "public-samples"
  physical_destination="$(pwd -P)"
  case "$physical_destination/" in
    "$repository_root/"*) ;;
    *)
      printf 'error: destination escaped physical repository root: %s\n' \
        "$physical_destination" >&2
      return 1
      ;;
  esac
  if [[ "$physical_destination" != "$destination_directory" ]]; then
    printf 'error: destination is not the expected physical path: %s\n' \
      "$physical_destination" >&2
    return 1
  fi
  destination_identity="$(path_identity .)"
}

assert_safe_destination_directory() {
  local physical_tmp
  local physical_destination

  if [[ -L "$tmp_directory" || -L "$destination_directory" ]]; then
    printf 'error: destination directory changed; refusing symlinked path component\n' \
      >&2
    return 1
  fi
  if [[ ! -d "$tmp_directory" || ! -d "$destination_directory" ]]; then
    printf 'error: destination directory changed or disappeared\n' >&2
    return 1
  fi

  physical_tmp="$(cd -P "$tmp_directory" && pwd -P)"
  physical_destination="$(cd -P "$destination_directory" && pwd -P)"
  case "$physical_destination/" in
    "$repository_root/"*) ;;
    *)
      printf 'error: destination directory changed and escaped physical repository root\n' \
        >&2
      return 1
      ;;
  esac
  if [[ "$physical_tmp" != "$tmp_directory" \
    || "$physical_destination" != "$destination_directory" \
    || "$(path_identity "$repository_root")" != "$repository_identity" \
    || "$(path_identity "$tmp_directory")" != "$tmp_identity" \
    || "$(path_identity "$destination_directory")" != "$destination_identity" \
    || "$(path_identity .)" != "$destination_identity" ]]; then
    printf 'error: destination directory changed or escaped physical repository root\n' \
      >&2
    return 1
  fi
}

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
  local destination="$filename"
  local display_destination="$destination_directory/$filename"
  local actual_sha256

  assert_safe_destination_directory
  if [[ -e "$destination" || -L "$destination" ]]; then
    if [[ ! -f "$destination" || -L "$destination" ]]; then
      printf 'error: refusing non-regular existing path: %s\n' \
        "$display_destination" >&2
      return 1
    fi
    actual_sha256="$(sha256_file "$destination")"
    if [[ "$actual_sha256" != "$expected_sha256" ]]; then
      printf 'error: existing %s has SHA-256 %s; expected %s\n' \
        "$filename" "$actual_sha256" "$expected_sha256" >&2
      printf 'error: the existing file was not replaced\n' >&2
      return 1
    fi
    printf 'Reusing verified %s\n' "$display_destination"
    return 0
  fi

  assert_safe_destination_directory
  temporary_file="$(mktemp ".download.${filename}.XXXXXX")"
  assert_safe_destination_directory
  download_file "$url" "$temporary_file"
  assert_safe_destination_directory
  actual_sha256="$(sha256_file "$temporary_file")"
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    printf 'error: downloaded %s has SHA-256 %s; expected %s\n' \
      "$filename" "$actual_sha256" "$expected_sha256" >&2
    return 1
  fi

  assert_safe_destination_directory
  if [[ -e "$destination" || -L "$destination" ]]; then
    printf 'error: destination appeared while downloading; refusing to replace %s\n' \
      "$display_destination" >&2
    return 1
  fi
  actual_sha256="$(sha256_file "$temporary_file")"
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    printf 'error: downloaded %s changed before publication\n' "$filename" >&2
    return 1
  fi
  assert_safe_destination_directory
  if ! ln "$temporary_file" "$destination"; then
    printf 'error: could not publish without replacing an existing path: %s\n' \
      "$display_destination" >&2
    return 1
  fi
  if ! assert_safe_destination_directory; then
    rm -f -- "$destination"
    return 1
  fi
  rm -f -- "$temporary_file"
  temporary_file=""
  printf 'Downloaded and verified %s\n' "$display_destination"
}

prepare_destination_directory

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
