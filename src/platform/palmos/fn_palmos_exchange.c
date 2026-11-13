/* One request/reply exchange over the CS1 link. */
#include <PalmOS.h>
#include "fujinet-nio.h"
#include "fn_palmos_internal.h"

/* NIO's own HTTP opens can take a while (DNS, TLS); the firmware gives up
 * after 30 s and publishes a timeout, so wait a little longer than that. */
#define REPLY_WAIT_SECONDS 35

/* A request the firmware found damaged is sent again; a reply that fails its
 * check is read again (it stays in place) before giving up. */
#define SEND_TRIES 3
#define READ_RETRIES 3

#ifdef FN_PALMOS_SHARED
#define ACCESS_RESULT() nl_cs1_guard_result()
#define PHASE(p) (nl_cs1_diag.phase = (p))
#else
#define ACCESS_RESULT() 0
#define PHASE(p) ((void)0)
#endif

#ifndef FN_PALMOS_EXPIRED
#define FN_PALMOS_EXPIRED(start, wait) (TimGetTicks() - (start) > (wait))
#endif

/* RESULT is a separate, unchecked bus word. Never let one bad read authorize
 * replay of a side-effecting request. Require two consecutive matching idle
 * snapshots bracketed by this request's sequence. ABI-4 error replies have
 * zero length/check; a rejection alongside a nonempty reply is inconsistent.
 * These are bounded reads of the held completion, never a command replay. */
static uint16_t read_result(uint16_t seq)
{
    uint16_t attempt, first, ack, response, result, last, tail;
    uint16_t length, check, previous = 0xffffu;
#ifdef FN_PALMOS_SHARED
    NioLibCS1Snapshot *sample;
    uint16_t flags;
    nl_cs1_samples.count = 0;
    nl_cs1_samples.expectedSequence = seq;
#endif
    for (attempt = 0; attempt < 4; ++attempt) {
        first = FN_PALMOS_RD(SBN_R_STATUS);
        ack = FN_PALMOS_RD(SBN_R_ACK_SEQ);
        response = FN_PALMOS_RD(SBN_R_RESP_SEQ);
        result = FN_PALMOS_RD(SBN_R_RESULT);
        length = check = 0;
        if (result != SBN_RES_OK) {
            length = FN_PALMOS_RD(SBN_R_RESP_LEN);
            check = FN_PALMOS_RD(SBN_R_RESP_CHECK);
        }
        last = FN_PALMOS_RD(SBN_R_STATUS);
        tail = FN_PALMOS_RD(SBN_R_RESP_SEQ);
#ifdef FN_PALMOS_SHARED
        nl_cs1_diag.resultAttempt = attempt + 1;
        nl_cs1_diag.statusFirst = first; nl_cs1_diag.statusLast = last;
        nl_cs1_diag.ack = ack; nl_cs1_diag.sequence = response;
        nl_cs1_diag.sequenceLast = tail; nl_cs1_diag.expectedSequence = seq;
        nl_cs1_diag.result = result;
        if (result != SBN_RES_OK) {
            nl_cs1_diag.wireLength = length; nl_cs1_diag.expectedCheck = check;
        }
        /* Retain the sampled words themselves, without extra bus reads.
         * Length/check are sampled only for a non-OK raw RESULT, as before. */
        flags = 0;
        if ((first | last) & SBN_ST_BUSY) flags |= nioCS1RejectBusy;
        if (ack != seq) flags |= nioCS1RejectAck;
        if (response != seq) flags |= nioCS1RejectSequence;
        if (tail != seq) flags |= nioCS1RejectTail;
        if (result > SBN_RES_REFUSED) flags |= nioCS1RejectResult;
        if (length || check) flags |= nioCS1RejectNonemptyError;
        if (!flags && previous != 0xffffu && previous != result) flags |= nioCS1ChangedResult;
        if (ACCESS_RESULT()) flags |= nioCS1RejectAccess;
        sample = &nl_cs1_samples.snapshot[attempt];
        sample->statusFirst = first; sample->ack = ack;
        sample->sequence = response; sample->result = result;
        sample->length = length; sample->check = check;
        sample->statusLast = last; sample->tail = tail; sample->flags = flags;
        nl_cs1_samples.count = attempt + 1;
#endif
        if (ACCESS_RESULT()) return ACCESS_RESULT();
        if (((first | last) & SBN_ST_BUSY) || ack != seq ||
            response != seq || tail != seq || result > SBN_RES_REFUSED ||
            length || check) {
            previous = 0xffffu;
            continue;
        }
        if (previous == result) return result;
        previous = result;
    }
#ifdef FN_PALMOS_SHARED
    nl_cs1_diag.reason = nioCS1ReasonSnapshot;
#endif
    return FN_PALMOS_BAD_READ;
}

/* BEGIN, the bytes two per DATA word (first one high), then CHECK over them. */
static void send_request(const uint8_t *req, uint16_t len)
{
    fn_palmos_port_t port = FN_PALMOS_PORT(_fn_palmos_cs1 + SBN_W(SBN_W_DATA));
    uint16_t pairs = len >> 1, w, check = 0;

    FN_PALMOS_WR(SBN_W_BEGIN, len);
    while (pairs--) {
        w = (uint16_t)((uint16_t)req[0] << 8 | req[1]);
        req += 2;
        check = SBN_CHECK_STEP(check, w);
        FN_PALMOS_PUT(port, w);
    }
    if (len & 1) {
        w = (uint16_t)((uint16_t)req[0] << 8);
        check = SBN_CHECK_STEP(check, w);
        FN_PALMOS_PUT(port, w);
    }
    FN_PALMOS_WR(SBN_W_CHECK, check);
}

/* Read the reply words, keep at most cap bytes, check every word. Zero if
 * the length or the check did not read back right. */
static uint8_t read_reply(uint8_t *resp, uint16_t cap, uint16_t *resp_len,
                          uint16_t *wire_len)
{
    fn_palmos_port_t port = FN_PALMOS_PORT(_fn_palmos_cs1 + SBN_R_RESP);
    uint16_t n = FN_PALMOS_RD(SBN_R_RESP_LEN), want = FN_PALMOS_RD(SBN_R_RESP_CHECK);
    uint16_t keep, pairs, words, w, check = 0;

    *wire_len = n;
#ifdef FN_PALMOS_SHARED
    nl_cs1_diag.wireLength = n; nl_cs1_diag.expectedCheck = want;
    nl_cs1_diag.computedCheck = 0;
    nl_cs1_diag.reason = nioCS1ReasonLength;
#endif
    if (ACCESS_RESULT()) return 0;
    if (n > SBN_RESP_MAX) return 0;
    keep = n < cap ? n : cap;
    pairs = keep >> 1;
    words = ((n + 1) >> 1) - pairs;
    while (pairs--) {
        w = FN_PALMOS_GET(port);
        check = SBN_CHECK_STEP(check, w);
        resp[0] = (uint8_t)(w >> 8);
        resp[1] = (uint8_t)w;
        resp += 2;
    }
    if (words) {
        /* The word with an odd last byte to keep, or the first one past cap. */
        w = FN_PALMOS_GET(port);
        check = SBN_CHECK_STEP(check, w);
        if (keep & 1) *resp = (uint8_t)(w >> 8);
        words--;
    }
    while (words--) {
        w = FN_PALMOS_GET(port);
        check = SBN_CHECK_STEP(check, w);
    }
    *resp_len = keep;
#ifdef FN_PALMOS_SHARED
    nl_cs1_diag.computedCheck = check;
    nl_cs1_diag.reason = nioCS1ReasonWordCheck;
#endif
    if (ACCESS_RESULT()) return 0;
    return check == want;
}

uint16_t fn_palmos_exchange(const uint8_t *req, uint16_t len, uint8_t *resp, uint16_t cap,
                            uint16_t *resp_len)
{
    uint16_t tries, wire_len, result = SBN_RES_BAD_CHECK;
    uint32_t start, wait = (uint32_t)REPLY_WAIT_SECONDS * SysTicksPerSecond();

    *resp_len = 0;
    if (!fn_palmos_open()) return FN_PALMOS_NO_ANSWER;
    if (!len || len > SBN_REQ_MAX) return SBN_RES_BAD_LEN;
    for (tries = 0; tries < SEND_TRIES && result == SBN_RES_BAD_CHECK; tries++) {
        if (++_fn_palmos_seq == 0) _fn_palmos_seq = 1;
        PHASE(nioCS1PhaseSend);
        send_request(req, len);
        if (ACCESS_RESULT()) return ACCESS_RESULT();
        FN_PALMOS_WR(SBN_W_DOORBELL, _fn_palmos_seq);
        if (ACCESS_RESULT()) return ACCESS_RESULT();
        PHASE(nioCS1PhaseWait);
        start = TimGetTicks();
        while (FN_PALMOS_RD(SBN_R_RESP_SEQ) != _fn_palmos_seq)
            if (FN_PALMOS_EXPIRED(start, wait)) {
#ifdef FN_PALMOS_SHARED
                nl_cs1_diag.reason = nioCS1ReasonPoll;
#endif
                return FN_PALMOS_NO_ANSWER;
            }
        PHASE(nioCS1PhaseResult);
        result = read_result(_fn_palmos_seq);
    }
    /* Only a good result has a reply to read. */
    if (result != SBN_RES_OK) {
#ifdef FN_PALMOS_SHARED
        if (!nl_cs1_diag.reason) nl_cs1_diag.reason = nioCS1ReasonBridge;
#endif
        return result;
    }
    PHASE(nioCS1PhaseReply);
    for (tries = 0; tries <= READ_RETRIES; tries++) {
#ifdef FN_PALMOS_SHARED
        nl_cs1_diag.replyAttempt = tries + 1;
#endif
        if (!read_reply(resp, cap, resp_len, &wire_len)) {
            if (ACCESS_RESULT()) { *resp_len = 0; return ACCESS_RESULT(); }
            continue;
        }
#ifdef FN_PALMOS_SHARED
        /* Validate the same captured length/data as the word checksum. A bad
         * read retries this held reply, never the remote command. */
        if (!nl_cs1_reply_valid(req, resp, *resp_len, wire_len, cap)) continue;
#endif
        return result;
    }
    *resp_len = 0;
    return FN_PALMOS_BAD_READ;
}
