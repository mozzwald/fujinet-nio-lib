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

typedef struct {
    UInt16 size, version, device, command, phase, reason, guard, result;
    UInt16 statusFirst, ack, sequence, statusLast, sequenceLast, expectedSequence;
    UInt16 wireLength, expectedCheck, computedCheck, replyAttempt, resultAttempt;
    UInt16 packetReason, outcome, guardDetail;
    UInt32 ticksStarted, ticksFinished, faultAddress;
} NioLibCS1Diagnostic;
#endif
