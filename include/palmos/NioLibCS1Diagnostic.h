/* Developer-only, versioned unsaved preference. Not a public library trap or
 * wire protocol. Contains scalars only: no caller pointers, URIs or file data. */
#ifndef NIO_LIB_CS1_DIAGNOSTIC_H
#define NIO_LIB_CS1_DIAGNOSTIC_H
#include <PalmOS.h>

#define nioCS1DiagnosticPref 0x4e37
#define nioCS1DiagnosticVersion 1
#define nioCS1PhaseSync 1
#define nioCS1PhaseSend 2
#define nioCS1PhaseWait 3
#define nioCS1PhaseResult 4
#define nioCS1PhaseReply 5
#define nioCS1ReasonLength 1
#define nioCS1ReasonWordCheck 2
#define nioCS1ReasonPacket 3
#define nioCS1ReasonSnapshot 4
#define nioCS1ReasonPoll 5
#define nioCS1ReasonLocal 6
#define nioCS1ReasonBridge 7
#define nioCS1ReasonSync 8
#define nioCS1GuardDeadline 1
#define nioCS1GuardMapping 2
#define nioCS1GuardPreference 3
#define nioCS1GuardCardFault 4

typedef struct {
    UInt16 size, version, device, command, phase, reason, guard, result;
    UInt16 statusFirst, ack, sequence, statusLast, sequenceLast, expectedSequence;
    UInt16 wireLength, expectedCheck, computedCheck, replyAttempt, resultAttempt;
    UInt16 packetReason, outcome, guardDetail;
    UInt32 ticksStarted, ticksFinished, faultAddress;
} NioLibCS1Diagnostic;
/* Separate correlated evidence preserves the existing 56-byte record/ABI.
 * Rejected snapshots never authorize replay; these flags only explain why. */
#define nioCS1SamplesPref 0x4e38
#define nioCS1SamplesVersion 1
#define nioCS1RejectBusy 0x01
#define nioCS1RejectAck 0x02
#define nioCS1RejectSequence 0x04
#define nioCS1RejectTail 0x08
#define nioCS1RejectResult 0x10
#define nioCS1RejectNonemptyError 0x20
#define nioCS1ChangedResult 0x40
#define nioCS1RejectAccess 0x80
typedef struct {
    UInt16 statusFirst, ack, sequence, result, length, check;
    UInt16 statusLast, tail, flags;
} NioLibCS1Snapshot;
typedef struct {
    UInt16 size, version, count, expectedSequence;
    UInt32 ticksStarted;
    NioLibCS1Snapshot snapshot[4];
} NioLibCS1Samples;
#endif
