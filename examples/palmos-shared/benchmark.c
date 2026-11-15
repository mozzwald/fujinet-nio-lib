/* Fixed 64 KiB, 512-byte FileRead workload. No UI, installation, retry or
 * remote mutation. Compare the same app/fixture against both library builds.
 * The stack buffers belong to this test app, not the installed library. */
#include "benchmark.h"

NioTestBenchmarkResult nio_benchmark;
UInt32 nio_benchmark_started;
UInt16 nio_benchmark_failure;

void NioTestBenchmark(const Char *uri)
{
    /* FileRead needs ten payload metadata bytes in addition to file data.
     * These buffers add 266 stack bytes versus the 256-byte benchmark; no new
     * persistent buffer, heap allocation or library state is required. */
    UInt8 scratch[522], data[512];
    fn_file_io_t io;
    fn_file_read_t read;
    NioLibCleanup cleanup;
    UInt32 start, offset;
    UInt16 i;
    UInt8 expected;
    MemSet(&nio_benchmark, sizeof(nio_benchmark), 0);
    nio_benchmark_failure = 0;
    io.buffer = scratch; io.capacity = sizeof(scratch);
    start = TimGetTicks();
    nio_benchmark_started = start;
    nio_benchmark.result = fn_init();
    nio_benchmark.palm = NioLibClientLastError();
    nio_benchmark.initTicks = TimGetTicks() - start;
    if (nio_benchmark.result) nio_benchmark_failure = nioBenchmarkInit;
    start = TimGetTicks();
    if (!nio_benchmark.result) {
        while (nio_benchmark.bytes < 65536UL) {
            offset = nio_benchmark.bytes;
            ++nio_benchmark.calls;
            nio_benchmark.result = fn_file_read(&io, uri, offset,
                                                data, sizeof(data), &read);
            nio_benchmark.palm = NioLibClientLastError();
            if (nio_benchmark.result) {
                nio_benchmark_failure = nioBenchmarkRead;
                break;
            }
            if (read.bytes_read != sizeof(data)) {
                nio_benchmark_failure = nioBenchmarkShort;
                nio_benchmark.result = FN_ERR_IO;
                break;
            }
            for (i = 0; i < sizeof(data); ++i) {
                /* Fixture changes between 256-byte blocks too, exposing a
                 * wrong block even when the wire offset echo is correct. */
                expected = (UInt8)((offset + i) ^ ((offset + i) >> 8));
                if (data[i] != expected) {
                    nio_benchmark_failure = nioBenchmarkPattern;
                    nio_benchmark.result = FN_ERR_IO;
                    break;
                }
                nio_benchmark.checksum += data[i];
            }
            if (nio_benchmark.result) break;
            nio_benchmark.bytes += read.bytes_read;
        }
    }
    nio_benchmark.ticks = TimGetTicks() - start;
    nio_benchmark.errors = nio_benchmark.result ? 1 : 0;
    if (nio_benchmark.ticks)
        nio_benchmark.rate = nio_benchmark.bytes * SysTicksPerSecond() /
                             nio_benchmark.ticks;
    start = TimGetTicks();
    fn_shutdown();
    nio_benchmark.cleanupResult = NioLibClientLastResult();
    nio_benchmark.cleanupPalm = NioLibClientLastError();
    nio_benchmark.cleanupTicks = TimGetTicks() - start;
    NioLibClientCleanupReport(&cleanup);
    if (!nio_benchmark.cleanupResult &&
        (cleanup.uncertain || cleanup.ambiguousOperation))
        nio_benchmark.cleanupResult = FN_ERR_TIMEOUT;
}
