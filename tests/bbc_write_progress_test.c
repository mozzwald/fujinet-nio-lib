/* Execute the actual ROM-backed assembly writer with a modeled OSWORD.
 * The mock confirms only successful chunks, never a failed chunk's length. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "fn_bbc_internal.h"

static uint8_t data[600];
static uint16_t calls, peer_count, first_count;
static uint8_t failure, fail_first;

uint8_t __fastcall__ mock_osword78(uint8_t *block)
{
    uint16_t n = FN_READ_LE16(block, 4);
    const uint8_t *p = (const uint8_t *)FN_READ_LE16(block, 2);
    ++calls;
    assert(block[0] == FN_BBC_REASON_WRITE_DATA && block[6] == 0x34);
    assert(p == data + peer_count && n <= 512 && n <= sizeof(data) - peer_count);
    if ((calls > 1 || fail_first) && failure) {
        block[4] = block[5] = 0xff; /* invalid failed-call output is not progress */
        return failure;
    }
    if (calls == 1 && first_count < n) n = first_count;
    block[4] = (uint8_t)n; block[5] = (uint8_t)(n >> 8);
    peer_count += n;
    return 0;
}

static void prepare(uint8_t error, uint16_t first)
{
    memset(_fn_sessions, 0, sizeof(_fn_sessions));
    _fn_initialized = 1;
    _fn_sessions[0].active = 1; _fn_sessions[0].handle = 0x1234;
    _fn_sessions[0].write_offset = 0x0000fffeUL;
    calls = peer_count = fail_first = 0; failure = error; first_count = first;
}

int main(void)
{
    uint16_t written, count;
    uint8_t code, result;
    for (count = 2; count <= 512; count += 510) {
        for (code = 1; code <= 3; ++code) {
            prepare(code, count); written = 99;
            result = fn_write(0x1234, 0xfffeUL, data, sizeof(data), &written);
            assert(result == (code == 1 ? FN_ERR_INVALID : code == 3 ? FN_ERR_NOT_FOUND : FN_ERR_IO));
            assert(written == count && calls == 2 && peer_count == count);
            assert(_fn_sessions[0].write_offset == 0xfffeUL + count);
            if (code == 1) {
                /* The scripted BAD_CALL did not accept any additional bytes. */
                failure = 0;
                assert(fn_write(0x1234, 0xfffeUL + count, data + count,
                                sizeof(data) - count, &written) == FN_OK);
                assert(written == sizeof(data) - count && peer_count == sizeof(data));
                assert(_fn_sessions[0].write_offset == 0xfffeUL + sizeof(data));
            }
        }
    }
    prepare(2, 512); fail_first = 1; written = 99;
    assert(fn_write(0x1234, 0xfffeUL, data, sizeof(data), &written) == FN_ERR_IO);
    assert(written == 0 && calls == 1 && peer_count == 0);
    assert(_fn_sessions[0].write_offset == 0xfffeUL);
    prepare(2, 512);
    assert(fn_write(0x1234, 0xfffeUL, data, sizeof(data), NULL) == FN_ERR_IO);
    assert(_fn_sessions[0].write_offset == 0x101feUL);
    prepare(0, 512); written = 99;
    assert(fn_write(0x1234, 0xfffeUL, data, sizeof(data), &written) == FN_OK);
    assert(written == sizeof(data) && calls == 2);
    assert(_fn_sessions[0].write_offset == 0xfffeUL + sizeof(data));
    written = 99;
    assert(fn_write(0x1234, 0xfffeUL, data, 1, &written) == FN_ERR_INVALID);
    assert(written == 0 && calls == 2);
    prepare(0, 512); written = 99;
    assert(fn_write(0x1234, 0xfffeUL, NULL, 0, &written) == FN_OK);
    assert(written == 0 && calls == 0 && _fn_sessions[0].write_offset == 0xfffeUL);
    written = 99;
    assert(fn_write(0x9999, 0xfffeUL, data, 1, &written) == FN_ERR_NOT_FOUND);
    assert(written == 0 && calls == 0);
    written = 99;
    assert(fn_write(0x1234, 0xfffeUL, NULL, 1, &written) == FN_ERR_INVALID);
    assert(written == 0 && calls == 0);
    _fn_initialized = 0; written = 99;
    assert(fn_write(0x1234, 0xfffeUL, data, 1, &written) == FN_ERR_INVALID);
    assert(written == 0 && calls == 0);
    puts("BBC compiled write progress tests passed");
    return 0;
}
