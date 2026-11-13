# Springboard completion validation and diagnostics

NioLib ABI 1.6 implementation 10 and later require two consecutive matching completion
snapshots before accepting RESULT. Each snapshot brackets RESULT with the
expected response sequence, checks ACK and idle status, and rejects out-of-range
results. A non-success result must also have zero reply length and word check,
as published by the ABI-4 bridge. Four snapshot attempts are allowed without
another wait deadline. Only a validated BAD_CHECK can authorize the existing
bounded request resend. Invalid completion snapshots never authorize replay.
This tolerates isolated register faults; repeated consistent corruption is
not made impossible by software sampling.

The first failed exchange in each foreground client writes a 56-byte scalar
record to unsaved preference NiL1/0x4e37, version 1. It survives library unload,
but persistence across a soft reset is not assumed. The latest recorded failed
client replaces the previous record; successful clients do not erase it. No URI,
file content or caller pointer is stored. Failure to save diagnostics does not
change the transport result or ownership state. There is no new public trap.
The main Palm-only diagnostic state uses 60 global bytes including state and
alignment. Implementation 15 additionally retains an 84-byte snapshot record
and a four-byte card-access address scalar; no packet buffer or library heap
allocation is added. Serial/USB ownership preference IDs are separate and their
timeout policy is unchanged.

Install the matching NioLib.prc and NioLibTest.prc after closing all NIO apps and
confirming the normal library unload preflight. Reproduce the Config transfer,
then exit Config and open NioLibTest. Select **Network**, then **CS1 log**.
Photograph both dialogs. Viewing the record only reads preferences: it does not
open a client, access CS1 or reset recovery state. The lifecycle test that runs
when NioLibTest starts does not erase this record. Avoid another failing client
operation before viewing it. A record can describe an older failure; its tick
values identify when that exchange occurred, modulo the Palm tick wrap.

The record contains the raw sampled RESULT separately from the engine outcome;
status, ACK and response sequences; expected sequence; captured reply length;
expected and computed word checks; bounded retry counts; packet rejection;
start/end ticks; and the first guarded access address that failed. Sequence
fields describe the completion snapshot (or synchronization snapshot for a
pre-send failure). Diagnostics reuse captured values and add no diagnostic bus
reads. Length/check fields on a failed guard may be incomplete; the guard reason
takes precedence over synthetic zero values.

| Field | Values |
| --- | --- |
| Phase | 1 synchronization, 2 request send, 3 response poll, 4 RESULT validation, 5 reply read |
| Reason | 1 length outside CS1 bound, 2 word checksum, 3 packet validation, 4 unstable/invalid RESULT snapshot, 5 response poll, 6 local guard, 7 bridge error, 8 pre-send synchronization |
| Guard | 0 none, 1 local deadline, 2 mapping/removal check, 3 pending-marker preference write/readback, 4 caught Handspring card fault |
| Guard detail (mapping) | 1 missing mapping/card, 2 installed-attribute query failed, 3 module absent, 4 base query failed, 5 size query failed, 6 zero size/overflow, 7 CS1 changed, 8 CS0 changed |
| Guard detail (card fault) | low 16 bits of the SDK exception error, when supplied; diagnostic only |
| Packet reason | 0 none, 1 short/truncated, 2 device/command echo, 3 packet length, 4 packet checksum, 5 payload/metadata |

Local expiry during a reply now stops reply retries and returns NIO timeout (6),
rather than consuming checksum retries and returning NIO I/O (5). Mapping
failure remains NIO I/O but is explicitly identified as guard 2. A bridge timeout
has guard 0 and raw RESULT 2. No MMIO is performed after a guard fails within the
current deadline. A later foreground entry starts a fresh deadline and must
still pass synchronization before sending.

Implementation 11 uses the [read-only cleanup policy](palmos-readonly-cleanup.md):
failed audited queries do not latch historical mutation uncertainty, but their
errors and this diagnostic record remain available. Outstanding replies and
earlier mutating uncertainty still prevent clean cleanup. Chunk sizes, progress
redraw frequency, bus timing and per-word removal checks are unchanged.

The card-access guard also records faults in discovery/probe/begin or pending-reply
retirement, with device/command zero for pre-exchange operations. It follows
Handspring's documented exception mechanism, restores the enclosing handler,
and preserves possibly posted sequences. See
[card-fault recovery and qualification](palmos-springboard-card-recovery.md).

## Per-attempt RESULT evidence (implementation 15)

The main 56-byte v1 record remains unchanged. When all four completion snapshots
fail validation, a separate unsaved NiL1/0x4e38 v1 preference records 84 scalar
bytes: size/version/count/expected sequence (four UInt16), start tick (UInt32),
then four snapshots of nine UInt16 each: first status, ACK, first response
sequence, raw RESULT, sampled length, sampled word check, last status, tail
response sequence, explanation flags. Length/check are **not sampled for raw
RESULT OK**; zeros there mean not read, not a newly observed empty reply.

Flags are hex: 01 busy status, 02 wrong ACK, 04 wrong first sequence, 08 wrong
tail sequence, 10 out-of-range RESULT, 20 nonempty length/check alongside a
non-OK RESULT, 40 a valid RESULT changed from the previous valid sample, 80
local access failure. Flag 40 explains lack of consecutive agreement; it is
not itself used to classify a snapshot as malformed. The original acceptance
conditions, four-attempt bound, held-reply retries and replay authorization
remain unchanged. These arrays add no diagnostic MMIO or OS calls to successful
transfers. They add 84 Palm-only global bytes and no heap or caller pointers.
Only a first failed snapshot-validation exchange saves the supplemental record.

The viewer adds a third dialog for snapshot failures when the stored sample
count, sequence and start tick match the main record. It shows all four raw
RESULT values, flags and ACKs. Missing/incompatible/stale supplemental records
leave the original two-dialog viewer intact. Full raw fields remain in the
preference for deeper inspection. Matching is best-effort diagnostic correlation,
not an ownership or safety mechanism. The first saved pair remains unchanged
by later successful operations and cleanup.

File speed now displays its start tick (`Start`, with init/end ticks as `I/E`).
Compare that with the diagnostic's start/end ticks before attributing an older
retained record to a new benchmark failure. Default fixture URI is now
`tnfs+tcp://tnfs.fujinet.online/PALM/nio-throughput.bin`, still editable.
