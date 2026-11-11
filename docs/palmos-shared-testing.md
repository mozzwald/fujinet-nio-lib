# Palm shared-library testing

Build as described in the [guide](palmos-shared-library.md). Required tests use
Python, a native C compiler and NioLib's pinned test-only
[requirements](../tests/requirements-palmos-shared.txt). Unicorn executes actual
compiled 68K code with mocked OS calls; it does not boot Palm OS.

The CS1 fault suite also covers isolated RESULT corruption without duplicate
remote opens, genuine request rejection, inconsistent completion bounds,
separate deadline/mapping/removal/length/checksum failures, clean settled query
cleanup while retaining pending replies and earlier mutating uncertainty, and
reading the diagnostic dialogs without transport activity.
See [physical CS1 reproduction and record fields](palmos-cs1-diagnostics.md).

```sh
python3 -m venv build/palmos-test-venv
build/palmos-test-venv/bin/pip install -r tests/requirements-palmos-shared.txt
make palmos-shared
make test-palmos-shared PALMOS_SHARED_PYTHON=build/palmos-test-venv/bin/python
```

Missing Unicorn, required artifacts or ABI audit entries **fails** the target.
Native image tests do not replace compiled execution. The build audit checks
resources, trap ordinals, relocations, A4 entry/exit, absence of A5 accesses and
unwanted CRT code. Run the general and Palm gates separately:

```sh
make check
make check-palmos PALMOS_SHARED_PYTHON=build/palmos-test-venv/bin/python
```

The full check requires the other platform toolchains as well; the Palm image
alone is not an all-target environment. Non-Palm builds such as `make linux`
do not require Palm tooling.

Test the optional SDK build separately:

```sh
make palmos-shared PALMOS_SDK_VERSION=3.5
make test-palmos-shared PALMOS_SDK_VERSION=3.5 \
  PALMOS_SHARED_PYTHON=build/palmos-test-venv/bin/python
```

Coverage includes compiled library/client globals, ownership, handles,
validation, CS1 deadlines, serial SLIP/partial I/O, USB counted I/O, retained
driver memory, readiness, JSON selectors and ABI 1.5 confirmed recovery.
Recovery tests check idle/confirmation guards, failed preference writes, no
reset-time packets, reload persistence and reuse after modeled peer reset.
They do not establish real ROM timing, reset persistence or physical recovery.

## Optional application compatibility

ISS/Weather fixtures remain optional. To require checks with existing compiled
applications, supply their owning harness and artifacts:

```sh
PALMOS_APPS_REPO=/path/to/springboard-nio \
PALMOS_APPS_BUILD=/path/to/existing-app-build \
PALMOS_REQUIRE_APPS=1 make test-palmos-shared \
  PALMOS_SHARED_PYTHON=build/palmos-test-venv/bin/python
```

The build directory must contain `isstracker/isstracker{,.symbols}` and
`weather/weather{,.symbols}`; the repository supplies `tests/test_shared_apps.py`.
Missing fixtures explicitly skip normally and fail with REQUIRE_APPS=1.
Do not fabricate fixtures or rebuild old apps to disguise a missing baseline.

## Short physical acceptance

Install with your normal HotSync tool after ending NIO apps, returning Home,
and confirming the old library can safely be released. Release HotSync's cradle
ownership. Start the selected NIO host **before** the Palm client.
Host instructions are in `fujinet-nio/docs/visor-usb-host.md`.

First test SDK 3.1-built NioLib, NioLibTest and NIO Config on the user's Visor
Prism running Palm OS 3.5. Run offline lifecycle checks, then Clock + two HTTP
handles on USB and CS1, normal app exit and repeated launches. This checks
forward compatibility, not actual OS 3.1H support. SDK 3.1H hardware, serial
and macOS qualification remain separate.

For each transport, induce a timeout or malformed reply, end the client and
record RecoveryRequired and its unsaved NiL1 marker. Verify after library
unload/reload. In a separate controlled run perform a Palm soft reset and
inspect the marker before reset/Save/Test actions. Record whether the original
marker and RecoveryRequired survived; do not infer persistence from mocks.
Use a debugger/preference inspector for the raw record.

Reset the actual remote peer/link as described in the
[recovery procedure](palmos-shared-library.md#globals-cleanup-and-recovery),
then confirm Reset in NIO Config. Verify the flag clears, the next Clock passes
and the host has no old handles. Canceling Reset must preserve the marker.
Save changes before Reset. Preserve logs/Palm errors for failures; never replay
a state-changing operation merely to find out whether it succeeded.

## ABI 1.6 services and growth

`tests/palmos_service_link.c` references every added client binding from the real
archive in NioLibTest. `test_palmos_shared_services.py` executes those compiled
wrappers/common codecs and checks file browsing/transfer, caller-buffered disk
inspection, HTTP headers and uncertain Open cleanup, Device/HSIO, Wi-Fi,
AppStore/legacy appkeys, Clock, slot catalogue and mount resolution. File and
device calls also exercise serial/USB framing. The mock peers provide wire
replies and Palm OS traps, never replacement service implementations.

The tests cover nonzero byte arguments and short enums in Palm GCC's C ABI,
UInt16 trap conversions, appkey details before initialization, old library
version/capability negotiation, ownership guards and no raw NetworkService
escape around handle cleanup. Clock binary formats have exact output bounds;
ISO strings are terminated even when the host omits a NUL. Native wire vectors
reject malformed lengths/offsets/versions and verify no partial file output or
hidden file retry. Their shell runners are part of the general `test` target.

`test-palmos-layout` builds independent early/late padding fixtures, verifies
actual resource growth and unchanged globals/ordinals, and executes compiled
lifecycle/register/network tests. The network tests relocate the resource to
three addresses, including above 0x80000. See
[layout and budget evidence](palmos-shared-layout.md).

On 2026-11-11 the user reported three successful TNFS browse/PRC-install cycles
over Springboard to POSIX NIO with implementation 11, without transfer or cleanup
errors. This is physical acceptance evidence for that workflow; HTTP, other
transports and reset/recovery qualification remain separate. Earlier captured
out-of-range CS1 metadata reads remain documented diagnostic evidence, not a
proven hardware root cause or proof that intermittent faults cannot recur.

On this development environment,
BBC/Watcom/Amiga toolchains, the sibling Amiga driver ABI headers and
`soft65c02_unit` are unavailable, so the full general `make check` cannot be
reported as passing. Atari/C64 and hosted Linux archives and available native
wire/link tests provide constrained/non-cc65 coverage; the separate Palm check
uses `../palmdev-toolchain`. Do not replace missing prerequisites with no-op
successes when completing upstream validation.
