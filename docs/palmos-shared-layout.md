# Palm shared-library code layout

The expanded NioLib uses the prc-tools `text_64k` linker script, whose code
resource bound is **64,720 bytes**. This is the conservative resource bound
supported by early Palm OS versions, not the unsigned-16-bit maximum 65,535.
The independent A4 globals budget remains **32,767 bytes**. Normal builds do
not allocate padding or reserve the unused code budget as writable RAM.

The primary source for these limits and the function-placement technique is
[prc-tools, Special projects](https://prc-tools.sourceforge.net/cgi-bin/info/special%2Bprojects.html).
The sibling palmdev-toolchain provides that linker script. No toolchain or
other platform's compiler flags or memory limits have been changed here.

## Placement

`makefiles/palmos-shared.mk` places the following groups in order:

1. Entry, dispatch table and lifecycle/image code.
2. New service entries and existing service entries, keeping trap destinations
   within signed 16-bit reach of the dispatch table.
3. Legacy helpers and higher-level common service codecs.
4. A4 ownership guards (`owner.c`), transport dispatch and configuration, and
   the required libc/libgcc helpers. These functions need to be reachable from
   both the early entries and the later core/backends.
5. Common disk/network codecs and physical backend code.

The common service sources, protocol contracts and public `fn_*` architecture
are retained. File boundaries remain useful for archive selection; the owner
module only relocates existing foreground state/guards and adds no buffer.

The table still uses the existing ordinals and signed offsets. No offset is
silently widened, masked or treated as unsigned. The linker continues to reject
PC-relative relocation overflows. The serializer rejects code-resident absolute
relocations and unsupported globals fixups, and the audit verifies dispatch
ordinals, A4 setup/restoration, and absence of caller A5 dependence.

Objdump also decodes inline data as instructions. The A5 audit exempts only the
already validated dispatch/name bytes and the byte-for-byte verified legacy
appkey hexadecimal/persistent-prefix constants. Every A5 instruction outside
those exact regions is still rejected; tests cover both sides of the regions
and altered constants.

## Measured room and regression checks

The current expanded image, built with sibling
`../palmdev-toolchain`, has these SDK 3.1 results (SDK 3.5 matches):

| Build | Code bytes | Code budget remaining | Globals bytes | Closest project DISP16 margin |
| --- | ---: | ---: | ---: | ---: |
| Normal | 46,136 | 18,584 | 7,872 | 5,521 |
| 4 KB inserted before central helpers | 50,232 | 14,488 | 7,872 | 1,425 |
| 8 KB inserted before backend objects | 54,328 | 10,392 | 7,872 | 5,521 |

Normal dispatch destinations have 18,733 bytes of positive signed-offset room.
The audit measures 627 signed-16-bit relocation sites in project objects,
including table offsets. The linker additionally checks linked archive members.
`verification.json` records actual code/global budgets, dispatch headroom, and
the ten tightest project relocation margins. These values are observations of
this image; changes to feature selection, optimization or compiler may change
them.

Run:

```sh
make test-palmos-layout PALMOS_SHARED_PYTHON=/path/to/venv/bin/python
```

This builds a normal image and independent early/late growth fixtures, audits
their PRCs, checks that the padding was actually linked and did not increase
globals or change trap ordinals, and executes compiled m68k lifecycle/register
and network tests for each padded image. It is included in `make check-palmos`.
The host-only malformed-image/A5 guard tests run in the general `make test`.

The positive growth tests are independent; they do not claim that 12 KB may be
inserted at arbitrary positions. An exploratory 8 KB early insertion was
correctly rejected by signed call-range checks while its total code was still
below the resource ceiling. Total free bytes alone never establish reachability.

## Further growth

Keep entries near the front, helpers central, and review the reported margins
when adding a service. Relink after layout changes (the linked image depends on
its Makefile). A failing signed relocation must be resolved by placement or a
properly validated forwarding mechanism, never by dropping an audit or ignoring
linker errors. The growth fixtures should continue to pass as features grow.

A single resource cannot grow past 64,720 bytes under this model. If expansion
approaches that ceiling, or the call graph no longer permits useful placement
headroom, additional code resources will require explicit library-owned loading,
locking, relocation and cross-resource calls. The current scheme preserves the
existing installed-library architecture and buys measurable room; it is not an
unlimited replacement for that future work.

These checks establish compiled-image and mocked-execution evidence. Physical
Palm OS installation, HotSync and hardware operation remain unqualified for this
expanded revision. The new service bindings pass their feature-specific compiled tests. Full
cross-target upstream validation remains blocked by the unavailable prerequisites
listed in the testing guide.
