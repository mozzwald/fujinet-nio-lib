# Palm shared-library performance WIP

The shared library includes experimental cumulative preference and transport
timing, and NioLibTest uses a verified 64 KiB fixture with 512-byte FileRead
requests. These diagnostics are intended for investigation, not a stable public
API. Static Palm and other platforms do not include them.

`NioLibTimingExperimental.h` describes two private unsaved preference snapshots:
`0x4e39` for preference/transport totals and `0x4e3a` for Springboard details.
Counters live in library-owned A4 RAM while the transport is active. Snapshots
are exported after transport teardown, outside measured command intervals;
there is no per-call logging or additional command-path persistence. Recovery
markers remain separate and retain their original persistence/readback rules.
The diagnostics add RAM and code to this WIP build, without new public traps.

NioLibTest displays timing after the benchmark. The Springboard viewer matches
the session start, exchange count and elapsed exchange time between records;
an unrelated or incomplete record is rejected. Phase times include nested
mapping and preference time. Subtract those nested totals to obtain the net
poll/reply/other partition. Feature, attribute and word timing samples cover
every 64th access and must not be added to inclusive phase totals. A sampled
zero is below clock resolution, not proof that the operation has no cost.

USB readiness reuses a verified-clear marker during the owned driver lifetime.
Pending/clear writes still receive readback verification; unknown state and
explicit inspection still read preferences. Close invalidates the RAM cache.
No operation is made replayable by this optimization.

The Springboard Design A cache stores only successful `hsEx` capability
detection for one protected card operation. Installation/base/size remain
dynamic checks. Extension support is checked again on the next operation,
including after a fault. See the [throughput workload and safety rules](palmos-springboard-throughput.md)
and [test instructions](palmos-shared-testing.md).

Compiled regression tests model OS calls, peer packets and faults; they do not
establish real ROM timing or physical-removal safety. Keep hardware logs,
screenshots, benchmark outputs and generated binaries outside tracked source.
