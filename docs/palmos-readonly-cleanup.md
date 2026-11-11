# Palm read-only query cleanup policy

ABI 1.6 implementation 11 separates a failed query from an unresolved resource
or mutating command. Typed, audited handleless queries return their original
error and retain diagnostics, but do not latch historical command uncertainty.
This applies on every shared-library transport, without new traps, packet
formats, buffers, automatic retries or a change to common service codecs.

The explicitly opted-in calls are:

- FileRead (explicit offset), FileStat, FileListPages.
- ClockGet, ClockTimezone, ClockGetFormat, ClockGetTz.
- FujiGetInfo, FujiGetHsio.
- WifiGetStatus, WifiGetConfig, WifiGetAdapterInfo, WifiGetJoinStatus.
- AppstoreStat, AppstoreRead, AppstoreList.
- SlotCatalogGet, SlotCatalogRange.
- LegacyReadAppkey, LegacyReadAppkeyBuffered.

Their wrappers use `nl_leave_readonly()` to release caller pointers/foreground
ownership without setting the historical mutation-uncertainty latch. It never
clears that latch if an earlier operation set it. All other entries retain
`nl_leave()`, including raw calls, network stream/handle operations, disk calls,
Wi-Fi scan/join initiation and settings writes. A future getter is conservative
until its wire semantics and resource ownership are audited and its wrapper
explicitly opts in. A function name alone is not sufficient classification.

EndClient still checks pending transport state, uncertain handle closes, prior
mutating uncertainty and retained physical drivers. A failed read with a reply
still outstanding therefore cannot report clean cleanup. On CS1, the exact
completed sequence can be retired without a new command; only then can cleanup
succeed. Serial and USB pending markers retain their existing recovery policy.
An earlier unknown write/Open outcome survives a later successful query.

For example, a CS1 FileRead whose reply fails all held-reply attempts still
returns NIO 5. If synchronization confirms completion, Config can issue its
existing explicit-offset retry. A successful retry and settled transport can
now finish with clean EndClient. Even without a retry, EndClient reports the
actual resource-cleanup result rather than repeating the earlier query error.
The caller must still handle the read's NIO 5; EndClient success does not make
the failed read successful or validate/install its data. Pending replies and
unknown mutation outcomes remain errors. No failed request is replayed by this
policy change.

The first failed CS1 exchange remains available in the existing diagnostic
preference and NioLibTest viewer. Ordinary server error replies (such as a
TNFS timeout mapped to I/O status) already had a transport-success outcome and
remain ordinary operation errors. This policy neither diagnoses nor repairs
the intermittent invalid CS1 length/checksum reads observed on hardware.
