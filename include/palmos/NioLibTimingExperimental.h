/* EXPERIMENTAL WIP: aggregate Palm preference/transport profiling.
 * Not a public trap or ABI. Snapshot is written once after transport close.
 * Buckets: CS1 marker, USB marker, all other shared-library preferences.
 * Ticks are inclusive wall time. Exchanges include command preference time;
 * preference totals also include initialization and teardown.
 */
#ifndef NIO_LIB_TIMING_EXPERIMENTAL_H
#define NIO_LIB_TIMING_EXPERIMENTAL_H
#include <PalmOS.h>
#define nioTimingPref 0x4e39
#define nioTimingVersion 1
typedef struct {
    UInt32 reads, readTicks, writes, writeTicks;
} NioTimingBucket;
typedef struct {
    UInt16 size, version, transport, ticksPerSecond;
    UInt32 started, sessionTicks, exchanges, exchangeTicks;
    NioTimingBucket bucket[3];
} NioTimingExperimental;
/* Independent experimental CS1 record; never a public trap/ABI structure.
 * Phase times are inclusive. Mapping/prefs are nested; word/Ftr/attribute
 * timings are sparse samples and MUST NOT be added to the inclusive totals. */
#define nioCS1TimingPref 0x4e3a
#define nioCS1TimingVersion 1
#define nioCS1TimingSampleMask 63UL
#define nioCS1TimingOther 0
#define nioCS1TimingPoll 1
#define nioCS1TimingReply 2
#define nioCS1TimingPhases 3
typedef struct {
    UInt32 calls, samples, ticks;
} NioCS1TimingSample;
typedef struct {
    UInt32 spans, ticks, mapCalls, mapTicks, prefCalls, prefTicks;
    NioCS1TimingSample reads, writes;
} NioCS1TimingPhase;
typedef struct {
    UInt16 size, version, ticksPerSecond, sampleShift;
    UInt32 started, exchanges, exchangeTicks, faults;
    NioCS1TimingSample features, attributes;
    UInt32 pollChecks, resultAttempts, replyAttempts, settleAttempts;
    NioCS1TimingPhase phase[nioCS1TimingPhases];
} NioCS1TimingExperimental;
#endif
