#include <stdio.h>
#include <string.h>
#include "fn_internal.h"
#include "fn_raw.h"
#include "fujinet-nio.h"

static uint8_t expected_device, expected_command, status, transport;
static uint8_t expected[1024], answer[1024];
static uint16_t expected_length, answer_length;
static unsigned calls;
#define CHECK(x) do { if (!(x)) { printf("file wire failure at %d\n", __LINE__); return 1; } } while (0)
uint8_t fn_raw_call(uint8_t device, uint8_t command, const void *payload,
 uint16_t length, void *reply, uint16_t capacity, fn_raw_response_t *r)
{
    ++calls;
    if (device != expected_device || command != expected_command ||
        length != expected_length || memcmp(payload, expected, length)) return FN_ERR_INTERNAL;
    if (transport) return transport;
    if (answer_length > capacity) return FN_ERR_IO;
    memcpy(reply, answer, answer_length);
    r->status = status; r->payload_length = answer_length;
    return FN_OK;
}
static uint16_t setup(uint8_t command)
{
    memset(expected, 0, sizeof(expected)); memset(answer, 0, sizeof(answer));
    expected_device = FN_DEVICE_FILE; expected_command = command;
    expected[0] = answer[0] = 1;
    expected[1] = 6; memcpy(expected + 3, "host:/", 6);
    expected_length = 9; answer_length = 4; status = transport = 0;
    return 9;
}
int main(void)
{
    uint8_t scratch[1024], data[512], saved[512];
    fn_file_io_t io;
    fn_file_stat_t stat;
    fn_file_read_t read;
    fn_file_write_t write;
    fn_disk_inspection_t inspect;
    uint16_t at;
    unsigned before;
    io.buffer = scratch; io.capacity = sizeof(scratch);
    setup(FN_CMD_FILE_STAT); answer[1] = FN_FILE_EXISTS;
    FN_PUT_LE32(answer + 4, 0x12345678UL); FN_PUT_LE32(answer + 8, 2);
    FN_PUT_LE32(answer + 12, 123); FN_PUT_LE32(answer + 16, 3); answer_length = 20;
    CHECK(fn_file_stat(&io, "host:/", &stat) == FN_OK);
    CHECK(stat.flags == FN_FILE_EXISTS && stat.size_bytes == 0x12345678UL &&
          stat.size_bytes_high == 2 && stat.mtime_unix == 123 && stat.mtime_unix_high == 3);
    answer_length = 19;
    CHECK(fn_file_stat(&io, "host:/", &stat) == FN_ERR_IO);
    answer_length = 20; answer[2] = 1;
    CHECK(fn_file_stat(&io, "host:/", &stat) == FN_ERR_IO);
    at = setup(FN_CMD_FILE_READ);
    FN_PUT_LE32(expected + at, 0x12345678UL); FN_PUT_LE16(expected + at + 4, sizeof(data));
    expected_length += 6; answer[1] = FN_FILE_EOF;
    FN_PUT_LE32(answer + 4, 0x12345678UL); FN_PUT_LE16(answer + 8, 3);
    memcpy(answer + 10, "abc", 3); answer_length = 13;
    CHECK(fn_file_read(&io, "host:/", 0x12345678UL, data, sizeof(data), &read) == FN_OK);
    CHECK(read.offset == 0x12345678UL && read.bytes_read == 3 && read.flags == FN_FILE_EOF &&
          !memcmp(data, "abc", 3));
    memset(data, 0xa5, sizeof(data)); memcpy(saved, data, sizeof(data));
    answer[4]++;
    CHECK(fn_file_read(&io, "host:/", 0x12345678UL, data, sizeof(data), &read) == FN_ERR_IO);
    CHECK(!memcmp(data, saved, sizeof(data)));
    answer[4]--; answer_length--;
    CHECK(fn_file_read(&io, "host:/", 0x12345678UL, data, sizeof(data), &read) == FN_ERR_IO);
    answer_length++; answer[0] = 2;
    CHECK(fn_file_read(&io, "host:/", 0x12345678UL, data, sizeof(data), &read) == FN_ERR_IO);
    answer[0] = 1; status = FN_ERR_NOT_FOUND;
    CHECK(fn_file_read(&io, "host:/", 0x12345678UL, data, sizeof(data), &read) == FN_ERR_NOT_FOUND);
    status = 0; transport = FN_ERR_TIMEOUT;
    before = calls;
    CHECK(fn_file_read(&io, "host:/", 0x12345678UL, data, sizeof(data), &read) == FN_ERR_TIMEOUT);
    CHECK(calls == before + 1); /* no hidden replay */
    at = setup(FN_CMD_FILE_WRITE);
    FN_PUT_LE32(expected + at, 9); FN_PUT_LE16(expected + at + 4, 3);
    memcpy(expected + at + 6, "abc", 3); expected_length += 9;
    FN_PUT_LE32(answer + 4, 9); FN_PUT_LE16(answer + 8, 2); answer_length = 10;
    CHECK(fn_file_write(&io, "host:/", 9, (const uint8_t *)"abc", 3, &write) == FN_OK);
    CHECK(write.offset == 9 && write.bytes_written == 2); /* explicit partial write */
    answer[8] = 4;
    CHECK(fn_file_write(&io, "host:/", 9, (const uint8_t *)"abc", 3, &write) == FN_ERR_IO);
    at = setup(FN_CMD_FILE_WRITE); memset(expected + at, 0, 6); expected_length += 6;
    answer_length = 10;
    CHECK(fn_file_write(&io, "host:/", 0, 0, 0, &write) == FN_OK); /* empty file */
    at = setup(FN_CMD_FILE_MKDIR); expected[at] = 3; expected_length++;
    CHECK(fn_file_mkdir(&io, "host:/", 3) == FN_OK);
    before = calls;
    CHECK(fn_file_mkdir(&io, "host:/", 4) == FN_ERR_INVALID);
    CHECK(fn_file_stat(0, "host:/", &stat) == FN_ERR_INVALID);
    CHECK(fn_file_stat(&io, "", &stat) == FN_ERR_INVALID);
    CHECK(fn_file_read(&io, "host:/", 0, data, 0, &read) == FN_ERR_INVALID);
    CHECK(fn_file_write(&io, "host:/", 0, 0, 1, &write) == FN_ERR_INVALID);
    CHECK(calls == before);
    setup(0x0f); expected_device = FN_DEVICE_DISK;
    memset(expected, 0, sizeof(expected)); expected[0] = 1; expected[2] = FN_DISK_TYPE_RAW;
    FN_PUT_LE16(expected + 3, 256); FN_PUT_LE16(expected + 5, 512);
    FN_PUT_LE16(expected + 7, 6); memcpy(expected + 9, "host:/", 6); expected_length = 15;
    answer[1] = FN_DISK_TYPE_RAW; FN_PUT_LE16(answer + 2, 256);
    FN_PUT_LE32(answer + 4, 720); FN_PUT_LE16(answer + 8, 3);
    memcpy(answer + 10, "xyz", 3); answer_length = 13;
    CHECK(fn_disk_inspect(&io, "host:/", FN_DISK_TYPE_RAW, 256, &inspect) == FN_OK);
    CHECK(inspect.media.sector_size == 256 && inspect.media.sector_count == 720 &&
          inspect.boot_length == 3 && !memcmp(inspect.boot_bytes, "xyz", 3));
    answer_length--;
    CHECK(fn_disk_inspect(&io, "host:/", FN_DISK_TYPE_RAW, 256, &inspect) == FN_ERR_IO);
    puts("file/inspection wire tests passed");
    return 0;
}
