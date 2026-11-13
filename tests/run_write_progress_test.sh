#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT=build/tests/write-progress
mkdir -p "$OUT"
common=(fn_state fn_packet_build_rw fn_packet_parse_common fn_packet_header
        fn_packet_checksum_packet fn_packet_checksum fn_checksum_fold)
sources=()
for name in "${common[@]}"; do sources+=("src/common/$name.c"); done
gcc -std=c99 -Wall -Wextra -Werror -DFN_WRITE_RETRY_LIMIT=2 -Iinclude \
    tests/write_progress_wire_test.c src/common/fn_rw.c "${sources[@]}" -o "$OUT/native"
"$OUT/native"

for variant in common atari; do
    mkdir -p "$OUT/$variant"
    objects=()
    writer=src/common/fn_rw.c
    if [ "$variant" = atari ]; then writer=src/platform/atari/fn_compact_write.s; fi
    for source in tests/write_progress_wire_test.c "$writer" "${sources[@]}"; do
        object="$OUT/$variant/$(basename "${source%.*}").o"
        cl65 -t sim6502 -Osir -O -DFN_WRITE_RETRY_LIMIT=2 \
            --asm-define FN_WRITE_RETRY_LIMIT=2 -Iinclude -c -o "$object" "$source"
        objects+=("$object")
    done
    cl65 -t sim6502 -m "$OUT/$variant/test.map" -Ln "$OUT/$variant/test.lbl" \
        -o "$OUT/$variant/test" "${objects[@]}"
    sim65 "$OUT/$variant/test"
    # The original API vectors keep their normal 500-retry limit and test
    # invalid arguments, NULL output, diagnostics and builder/parser failures.
    mkdir -p "$OUT/$variant/vectors"
    objects=()
    for source in tests/atari_network_write_soft65c02.c tests/atari_network_write_profile.s \
                  "$writer" tests/write_progress_sim_main.c; do
        object="$OUT/$variant/vectors/$(basename "${source%.*}").o"
        cl65 -t sim6502 -Osir -O -Iinclude -c -o "$object" "$source"
        objects+=("$object")
    done
    cl65 -t sim6502 -o "$OUT/$variant/vectors/test" "${objects[@]}"
    sim65 "$OUT/$variant/vectors/test"
done

mkdir -p "$OUT/bbc"
objects=()
for source in tests/bbc_write_progress_test.c tests/bbc_write_progress_osword.s \
              src/platform/bbc/fn_write.s src/platform/bbc/fn_rw_common.s src/common/fn_state.c; do
    object="$OUT/bbc/$(basename "${source%.*}").o"
    cl65 -t sim6502 -Osir -O --asm-define FN_MAX_SESSIONS=2 \
        -Iinclude -Isrc/platform/bbc -c -o "$object" "$source"
    objects+=("$object")
done
cl65 -t sim6502 -m "$OUT/bbc/test.map" -Ln "$OUT/bbc/test.lbl" \
    -o "$OUT/bbc/test" "${objects[@]}"
sim65 "$OUT/bbc/test"
