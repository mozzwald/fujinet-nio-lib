/* Real packet builders/parser with a scripted peer, shared by native GCC,
 * portable cc65 and the actual Atari compact writer under sim65. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "fn_internal.h"
#include "fn_platform.h"

enum { transport_busy, transport_not_ready, service_busy, service_not_ready,
       zero_accepted, transport_io, transport_timeout, bad_checksum,
       short_reply, service_io, overaccepted, complete };
static uint8_t mode, first_done;
static unsigned calls;
static uint16_t prefix, peer_count;
static uint32_t initial;
static uint8_t data[FN_MAX_PACKET_SIZE + 32];

uint8_t fn_transport_exchange(void)
{
    const uint8_t *request = _fn_transport_ctx.request;
    uint8_t *response = _fn_transport_ctx.response;
    uint16_t pos, n, accepted = 0;
    uint8_t status = FN_OK;
    ++calls;
    n = FN_READ_LE16(request, 13);
    assert(request[0] == FN_DEVICE_NETWORK && request[1] == FN_CMD_WRITE);
    assert(FN_READ_LE16(request, 7) == 0x1234);
    assert(FN_READ_LE32(request, 9) == initial + peer_count);
    assert(_fn_transport_ctx.req_len == 15 + n);
    assert(n <= FN_MAX_PACKET_SIZE - 15);
    assert(memcmp(request + 15, data + peer_count, n) == 0);
    if (!first_done && prefix) {
        assert(prefix <= n);
        accepted = prefix;
        first_done = 1;
    } else {
        switch (mode) {
        case transport_busy: return FN_ERR_BUSY;
        case transport_not_ready: return FN_ERR_NOT_READY;
        case service_busy: status = FN_ERR_BUSY; break;
        case service_not_ready: status = FN_ERR_NOT_READY; break;
        case zero_accepted: break;
        case transport_io: return FN_ERR_IO;
        case transport_timeout:
            /* The peer consumed data, but the caller cannot confirm it. */
            peer_count += n;
            return FN_ERR_TIMEOUT;
        case service_io: status = FN_ERR_IO; break;
        case overaccepted: accepted = n + 1; break;
        case bad_checksum: accepted = n; break;
        case short_reply: _fn_transport_ctx.resp_len = 0; return FN_OK;
        case complete: accepted = n; break;
        }
    }
    if (status) {
        pos = fn_build_header(response, FN_DEVICE_NETWORK, FN_CMD_WRITE, FN_HEADER_SIZE + 1);
        response[5] = 1;
        response[pos++] = status;
    } else {
        pos = fn_build_header(response, FN_DEVICE_NETWORK, FN_CMD_WRITE, FN_HEADER_SIZE + 12);
        memset(response + pos, 0, 12);
        response[pos] = 1;
        response[pos + 10] = (uint8_t)accepted;
        response[pos + 11] = (uint8_t)(accepted >> 8);
        pos += 12;
        if (accepted <= n) peer_count += accepted;
    }
    response[FN_CHECKSUM_OFFSET] = fn_calc_packet_checksum(response, pos);
    if (mode == bad_checksum && calls > 1) response[FN_CHECKSUM_OFFSET] ^= 1;
    _fn_transport_ctx.resp_len = pos;
    return FN_OK;
}

static void prepare(uint8_t failure, uint16_t confirmed)
{
    uint16_t i;
    for (i = 0; i < sizeof(data); ++i) data[i] = (uint8_t)(i ^ (i >> 8));
    mode = failure; prefix = confirmed; peer_count = 0; calls = 0; first_done = 0;
    initial = 0x0000fffeUL;
    _fn_initialized = 1;
    memset(_fn_sessions, 0, sizeof(_fn_sessions));
    _fn_sessions[0].active = 1; _fn_sessions[0].handle = 0x1234;
    _fn_sessions[0].write_offset = initial;
}

int main(void)
{
    static const uint8_t errors[] = {FN_ERR_BUSY, FN_ERR_NOT_READY, FN_ERR_BUSY,
        FN_ERR_NOT_READY, FN_ERR_BUSY, FN_ERR_IO, FN_ERR_TIMEOUT, FN_ERR_IO,
        FN_ERR_INVALID, FN_ERR_IO, FN_ERR_IO};
    uint8_t scenario;
    uint16_t written, before;
    /* The runner uses two retries: one acceptance, then three refusals, or
     * one acceptance followed by one non-retryable/ambiguous failure. */
    for (scenario = 0; scenario < complete; ++scenario) {
        prepare(scenario, 2); written = 99;
        assert(fn_write(0x1234, initial, data, 4, &written) == errors[scenario]);
        assert(written == 2 && _fn_sessions[0].write_offset == initial + 2);
        assert(calls == (scenario <= zero_accepted ? 4 : 2));
        before = calls;
        assert(fn_write(0x1234, initial, data, 4, &written) == FN_ERR_INVALID);
        assert(written == 0 && calls == before);
        if (scenario <= zero_accepted) {
            mode = complete;
            assert(fn_write(0x1234, initial + 2, data + 2, 2, &written) == FN_OK);
            assert(written == 2 && peer_count == 4);
            assert(_fn_sessions[0].write_offset == initial + 4);
        }
        /* No retry for an uncertain final exchange, even with known prefix. */
    }
    prepare(service_busy, 0); written = 99;
    assert(fn_write(0x1234, initial, data, 4, &written) == FN_ERR_BUSY);
    assert(written == 0 && _fn_sessions[0].write_offset == initial && calls == 3);
    prepare(service_busy, 2);
    assert(fn_write(0x1234, initial, data, 4, NULL) == FN_ERR_BUSY);
    assert(_fn_sessions[0].write_offset == initial + 2);
    /* Preserve a whole acknowledged packet before a later packet fails. */
    prepare(service_busy, FN_MAX_PACKET_SIZE - 15); written = 99;
    assert(fn_write(0x1234, initial, data, sizeof(data), &written) == FN_ERR_BUSY);
    assert(written == FN_MAX_PACKET_SIZE - 15);
    assert(_fn_sessions[0].write_offset == initial + written);
    before = written; mode = complete;
    assert(fn_write(0x1234, initial + before, data + before,
                    sizeof(data) - before, &written) == FN_OK);
    assert(written == sizeof(data) - before && peer_count == sizeof(data));
    prepare(complete, 0); written = 99;
    assert(fn_write(0x1234, initial, NULL, 0, &written) == FN_OK && written == 0);
    puts("write progress wire/offset/retry tests passed");
    return 0;
}
