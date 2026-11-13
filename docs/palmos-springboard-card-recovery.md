# Springboard card-fault recovery

ABI 1.6 implementation 15 retains a card-removal exception scope in the
installed Palm shared library. Mapping checks still run before every word. Serial,
USB, static Palm transport code, public ordinals and wire formats are unchanged.
The conservative support-check and deadline-ordering changes remain in place.

## SDK mechanism and scope

Handspring's `HsExt.h` and *Springboard Development Guide* section 4.5.5 specify
`HsCardErrTry` / `HsCardErrCatch` for shared libraries accessing removable
module memory. The macros obtain `HsPrvErrCatchListP` (selector 9), link a local
`ErrExceptionType`, call Palm's `ErrSetJump`, and restore the previous list on
both success and catch. The shared backend uses exactly that sequence with
the selected Palm SDK's own exception type and function declaration. It uses
a narrow selector declaration, like the existing attribute adapter, because
prc-tools GCC 2.95 rejects the original Handspring header's CRLF macro
continuations. No external SDK files are modified or copied into the repo.

The scope encloses each complete discovery/open, probe, begin, exchange
(including pre-send synchronization and final completion), or pending-reply
retirement. Initial discovery reads MAGIC/VERSION too and must be protected.
There is no per-word setjmp, callback registration or retained exception pointer.
No return/goto leaves an installed scope. The list pointer and result are
volatile; the SDK error field is read from memory after recovery. The catcher
restores the outer handler before reporting the fault. The service wrapper
then executes its ordinary foreground release and clears caller pointers.

The code never masks interrupts or installs a CPU-wide bus handler. It relies
on Handspring's documented removal handling; it cannot recover arbitrary CPU
faults, a permanently hung OS call, code removed with the module, or silent
remapping to another valid memory window. These scopes do not justify reducing
mapping validation frequency. SDK 3.1 and 3.5 compilation is not proof of real
Palm OS 3.1H or 3.5 removal behavior.

## Failure behavior

- Caught faults return NIO I/O (5); partial replies have zero reported length
  and never reach the typed caller's data buffer. Guard 4 distinguishes the
  fault from mapping rejection (2), deadline expiry (1), and preference error (3).
- A failed initial discovery clears its provisional CS1 mapping. A later
  discovery can retry normally after reinsertion; no remote reset is implied.
- The pending marker is persisted before attempting the doorbell. `posted` is
  set before the physical write, so a fault before or after the module observes
  that write conservatively retains the sequence. No command is auto-replayed.
  Even a prepared marker whose non-posting cannot be proved remains retained.
- Earlier mutating uncertainty remains latched. An explicit audited read-only
  retry may synchronize a completed sequence and succeed, but cannot erase an
  earlier unknown mutation. Outstanding replies still prevent clean cleanup.
- A fault while retiring a reply leaves the marker untouched. The first saved
  diagnostic remains unchanged by subsequent cleanup/retry faults. The raw SDK
  error's low 16 bits are diagnostic detail only, never replay authorization.

The record format/preference version is unchanged. Fault address is the last
attempted word address, or zero if none was attempted; an asynchronous removal
inside other code need not identify a faulting bus cycle. Partial scalar data
in the record is not a validated response.

## Memory and regression coverage

One scope uses the selected SDK's 56-byte exception object plus the list
pointer, result, compiler locals and saved registers on the stack. The
volatile four-byte last-access address is library-owned; no caller pointer,
packet buffer or heap allocation is retained. Support-check deduplication
retains every per-word mapping check. The guard adds one support lookup,
one selector-9 call and one ErrSetJump per complete operation.

`test_palmos_shared_card_fault.py` executes actual compiled guard/handlers and
injects a modeled OS jump at the peripheral MOVE.W, after mapping checks. It
restores the SDK's twelve saved registers, including A4/A5, frame pointer and
SP, and re-enters the compiled catch path. Tests cover discovery, probe, begin,
each exchange phase, cleanup, an outer caller's handler, foreground/pointer
release, zero partial output, no MMIO after catch, both possible doorbell
outcomes, retained markers/diagnostics, explicit read-only retry, earlier
mutating uncertainty and code relocation.

These tests run under `make test-palmos-shared` / `check-palmos`. SDK 3.1/3.5
and early/late growth images retain their A4/A5, ordinal, relocation, resource
and signed-displacement audits. Mocked OS jumps exercise the public ABI;
they do not qualify Palm ROM's removal interrupt handler.

## Physical qualification limits

Normal browsing, PRC installation and the File speed workload exercise
compatibility, not card-removal recovery. Real removal/reinsertion, OS 3.1H
ROM behavior and soft-reset marker persistence require separate qualification.
For a controlled removal test, use disposable read-only traffic with logs and
a recovery plan. A possibly posted command may require actual peer reset plus
the existing explicit recovery confirmation. Reinsertion alone cannot prove
that an unknown remote operation is safe to replay.
