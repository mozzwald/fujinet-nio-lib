# Conservative Springboard throughput and benchmark

The selectable Design A baseline below uses `PALMOS_CS1_PAYLOAD_WORDS=0`.
The default experimental implementation 17 uses bounded payload certificates;
see [Design B selection and safety limits](palmos-springboard-payload-certificates.md).

Experimental ABI 1.6 implementation 16 checks Handspring extension availability
once per protected card operation. A one-byte A4-owned positive-support flag is
set only inside the installed card-exception scope and cleared on both normal
and caught exits. Every later operation probes `hsEx` afresh; failed support
detection is not cached. This assumes the system extension remains available
during the synchronous operation, rather than supporting its mid-call removal.

Every word access still queries installation, base and size. Discovery retains
its checked adapter, provisional CS1 mapping and candidate-card handling. No
dynamic mapping is cached. The existing per-word deadlines, exception handling,
pending-marker persistence, sequence checks and reply validation are unchanged.
This describes Design A; Design B changes only explicitly certified payload reads.

Deadline checks run both before and after mapping queries. After persisting
the pending marker, the doorbell path checks mapping and time again immediately
before posting. A prepared marker is cleared only when no doorbell access was
attempted; failure to clear remains pending for cleanup/recovery. These checks
cannot preempt a stuck OS call or eliminate the check/access instruction race.
The [card-fault guard](palmos-springboard-card-recovery.md) handles the SDK's
supported exceptions separately.

Only conservative per-word access is supported. Both build settings
`PALMOS_CS1_BURST_WORDS=0` and `PALMOS_CS1_BURST_WRITE=0` must remain zero;
nonzero settings are rejected. Experimental burst implementations are removed.
No polling, command/reply retry, protocol, Config chunk-size or redraw policy
has changed. Static Palm transport and other platforms are unaffected.

## File speed workload

NioLibTest's **Network → File speed** page reads exactly 64 KiB using 128
explicit-offset FileRead calls of 512 bytes. It checks every byte against
`(offset ^ (offset >> 8)) & 255`. There is no app retry, PRC installation,
remote mutation or per-chunk drawing. Scratch/data buffers belong to the app.
Library held-reply/request retry policy remains unchanged.

Generate the fixture outside the source tree:

```sh
python3 scripts/palmos_throughput_fixture.py /tmp/nio-throughput.bin
```

Publish that file under the configured POSIX NIO filesystem root for
`host:/nio-throughput.bin`, or copy it to a TNFS server. The editable default is
`tnfs+tcp://tnfs.fujinet.online/PALM/nio-throughput.bin`. Use `tnfs://` for UDP;
there is no automatic fallback between TCP and UDP.

End NIO apps and return Home before replacing the library/test app. Release
HotSync ownership and start the selected host before opening the client.
Keep the app, fixture, URI, transport, cache conditions and firmware logging
settings identical when comparing libraries. Separate cold and warm runs;
repeat warm runs rather than judging one sample. Avoid heavy bridge tracing
while measuring throughput. Test normal browsing and PRC installs separately.

Success requires PASS, 65536 verified bytes, 128 calls, no errors, the expected
sum `007F8000`, and clean FN/Palm cleanup. The byte pattern check is stronger
than the additive sum. Only complete verified chunks count toward bytes;
the sum can include a verified prefix of a failing chunk.

Transfer ticks and B/s include reads and byte verification, excluding init,
cleanup and UI work. Init/cleanup durations are separate; `I/E` labels refer
to those durations. Tick subtraction handles wrap. Zero transfer ticks yield
no meaningful rate, displayed as zero. Failures distinguish initialization,
FileRead API, short file, byte mismatch and cleanup, retaining original FN/Palm
errors independently of cleanup results.

Compare the run's `Start` tick with the retained CS1 record before attributing
an old diagnostic to a new failure. FN 5 alone cannot distinguish a server
error from a local transport fault. See [diagnostic fields and
capture](palmos-cs1-diagnostics.md). Physical success does not establish a root
cause or prove intermittent faults cannot recur.

## Automated regression coverage

`test_palmos_shared_throughput.py` executes the compiled library/app under the
existing `test-palmos-shared` / `check-palmos` gates. It checks unchanged word
and dynamic attribute counts, one support query per protected operation, renewed
support checks at the next operation, expiry inside mapping/persistence, no late
doorbell, failed marker clears, exact fixture bytes/offsets, early failure without
replay, separate
cleanup and redraw geometry. Modeled trap counts measure work, not real bus
bandwidth or ROM timing. Actual throughput remains a physical qualification.
