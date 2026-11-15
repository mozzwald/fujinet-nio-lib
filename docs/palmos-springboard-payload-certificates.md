# Experimental bounded Springboard reply reads

ABI 1.6 implementation 17 adds Design B on top of Design A's operation-local
`hsEx` cache. It is an unqualified hardware experiment, not a reliability fix.
The existing 64 KiB/512-byte benchmark and all timing records/viewers are intact.

## Selection and scope

`make palmos-shared PALMOS_CS1_PAYLOAD_WORDS=32` selects the default. Accepted
values are **0, 8, 16, 32, 64** words. Zero selects implementation 16 / Design A;
its compiled library and application sections match the preserved Design A
build. Other values select implementation 17; use the package directory and
settings manifest to distinguish intervals. Settings participate in object
invalidation. Only shared-library CS1/state/version/packet-engine objects receive
the flag; it is not passed to static Palm, USB, Serial or common NIO code.

`PALMOS_CS1_BURST_WORDS=0` and `PALMOS_CS1_BURST_WRITE=0` remain mandatory.
No old burst helper is restored. Every bus access remains an individual volatile
16-bit read or write in the existing scalar helper. There is no timer, delay,
yield, interrupt mask, new bus instruction or firmware/protocol change inserted
between the final deadline check and the access.

## Certificate lifetime

After fully guarded reply-length/check reads, `nl_cs1_payload_begin` revokes any
old certificate and performs a full installed/base/size validation with deadline
checks. It grants access only to consecutive aligned words of that reply's
rounded-up payload extent, including words discarded beyond the caller's buffer.
An empty reply still receives initial and final validations.

At most the selected interval of payload words may be read before another full
validation. Every word retains both deadline/sticky-invalid observations and
attempt-address recording. The end helper revokes permission and fully validates
the mapping before packet acceptance, including when a word checksum will fail.
Changed mapping/deadline/fault paths discard the partial reply; they never
authorize another request or accept a partial packet.

Writes and control reads revoke permission and perform their original full
per-word validation. This includes request DATA, BEGIN, CHECK, DOORBELL, polling,
idle synchronization, RESULT/ACK/RESP/STATUS snapshots, length/check metadata,
discovery, probe and retirement. Pending-marker publication/readback and the
post-publication map/deadline check before DOORBELL are unchanged. The consecutive
snapshot rules, checksums, send/reply limits, ownership and uncertainty policy
are unchanged.

Permission is revoked at attempt start/end, phase transitions, mapping or
deadline failure, caught card faults, protected-operation entry/exit, explicit
CS1 reset and last library Close. It never survives unload. No caller pointer or
buffer is retained. State and its small clear helper are linked at the existing
code midpoint so both early lifecycle code and late bus handlers retain signed
DISP16 reach; code/global budgets and growth audits are not relaxed.

## Aperture protection and safety boundary

Every full validation checks that both chip-select windows are aligned and do
not wrap, and that CS1 contains the operation's complete used aperture. In
particular, DOORBELL at offset `0x30000` requires at least `0x30002` bytes; an
SDK-legal 128 KiB chip-select size is too small for this ABI. The reply region
must fit, including an odd reply's padding word. Each access is checked for
alignment and end-exclusive bounds before MMIO. Guard detail 9 under the existing
Mapping guard identifies an aperture/address/certificate-boundary rejection;
existing diagnostic structures and preference versions are unchanged.

This is not a mapping lock. The experiment assumes a controlled runtime without
another extension reprogramming chip selects during the synchronous operation.
Removal uses the existing SDK card exception scope. A persistent non-faulting
remap is detected at the next checkpoint or final validation, but up to one
interval of stale reads can precede detection. A change away and back between
checks need not be detected. A read of a different peripheral can have side
effects even without a write. Exception handling/checksums are not proof of
module identity, and matching base/size/8-bit sequence does not prove continuity
across replacement/reset. No transparent new recovery policy is introduced.

Do not broaden certificates to writes or remove final validation. If qualification
finds unsafe behavior or more failures, retain diagnostics and stop. Do not add
delays, increase retry limits or weaken packet/snapshot criteria to hide it.

## Expected work counts, not hardware speed claims

For W payload words and positive interval N, the number of payload validations
is `max(1, ceil(W/N)) + 1`: an initial validation, interval boundaries, and final
validation. With certificates disabled it is W, as in Design A.

The default fixture's successful 529-byte wire reply contains 265 words. On the
same minimum-wait/no-retry modeled trace (128 requests):

| Interval | Mapping validations | Card attributes | hsEx lookups |
| --- | ---: | ---: | ---: |
| 0 / Design A | 43,008 | 129,024 | 128 |
| 8 | 13,568 | 40,704 | 128 |
| 16 | 11,392 | 34,176 | 128 |
| 32 | 10,368 | 31,104 | 128 |
| 64 | 9,856 | 29,568 | 128 |

Word reads/writes remain 37,888/4,864, with 128 completion polls, 256 RESULT
attempts and 128 held replies in that modeled trace. Real timing can change
polling and internal retries, so these totals are not promised hardware counts.
For Design A's first *physical* trace, holding its 138 reply attempts and all
other accesses fixed would reduce 55,300 maps to 20,110 at interval 32. This is
arithmetic on an old trace, not a new measurement or throughput forecast.

## WIP status and hardware comparison

Design A has completed repeated physical transfers. The first tested Design B
candidate completed byte verification and cleanup, but required more internal
held-reply retrieval attempts than the profiled Design A baseline. The aggregate
counters cannot identify the rejection cause or establish that Design B caused
the increase. Further optimization is paused pending investigation; the default
32-word build is an experimental sharing snapshot, not a qualified replacement
for Design A. Select `PALMOS_CS1_PAYLOAD_WORDS=0` for that baseline.

Keep captured logs, screenshots, benchmark outputs and detailed validation
evidence in ignored build storage or outside the repository.

For the candidate, record the result screen and the existing six timing pages:
verified bytes/sum, throughput/transfer and session/exchange time, mapping time
and validations, features/attributes, preference time, reply attempts minus 128,
RESULT attempts minus 256, errors/faults and cleanup. Keep fixture, URI, app,
host and firmware constant. Do not treat a PASS as a reliability improvement;
compare internal recoveries as well as final success. Investigate the increased
retry activity before treating this experiment as ready for upstream inclusion.

## Regression coverage

`test_palmos_shared_payload.py` runs compiled m68k service/guard/engine code with
scripted OS/peer boundaries. It checks zero/one/31/32/33 words and the configured
interval, odd replies, short output buffers, discarded tail words, maximum and
oversized replies, initial/checkpoint/final map positions, fresh certificates on
retries/exchanges, both checksum layers, no request replay, full control/write
validation, persistent silent remapping, removal with and without a modeled card
fault, between-word/validation deadlines, address alignment/aperture limits, and
scope/reset/close invalidation. Existing RESULT/ownership/recovery tests remain
in the full suite. Modeled exceptions do not qualify real ROM removal behavior.

The normal shared test discovery and `check-palmos` gates include these tests.
SDK 3.1/3.5 images, public ordinals, A4/A5, relocation, resource, DISP16 and
early/late growth fixtures must pass. Evidence belongs in ignored build storage,
not in committed logs, binaries or benchmark screenshots.
