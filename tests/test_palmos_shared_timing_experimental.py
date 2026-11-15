"""UNCOMMITTED timing diagnostics: injected ticks validate accounting only.
These are not hardware speed measurements. Real library/benchmark code executes.
"""
from collections import Counter
import json
import struct
import unittest
import test_palmos_shared as f
from test_palmos_shared_services import ServiceMachine
from test_palmos_shared_usb import USBMachine
from test_palmos_shared_transports import TransportMachine, config
if f.HAVE_UNICORN:
    from unicorn.m68k_const import UC_M68K_REG_A7


class TimingMixin:
    def __init__(self):
        self.observed = Counter()
        self.exports = 0
        self.files, self.values = {}, {}
        self.bad_file_echo = False
        self.service_error = 0
        super().__init__()

    def hook(self, uc, pc, size, context):
        delay = 0
        if bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f':
            trap, sp = self.read16(pc + 2), uc.reg_read(UC_M68K_REG_A7)
            if trap in (0xa2d3, 0xa2d4):
                pref = self.read16(sp + 4)
                if trap == 0xa2d4 and pref == 0x4e39:
                    self.exports += 1
                if self.globals and uc.mem_read(self.globals + self.symbols['timing_active'], 1)[0]:
                    bucket = 0 if pref == 0x4e32 else 1 if pref == 0x4e36 else 2
                    kind = 'read' if trap == 0xa2d3 else 'write'
                    self.observed[bucket, kind] += 1
                    delay = 3 if kind == 'read' else 7
        super().hook(uc, pc, size, context)
        self.now += delay

    def execute(self, request):
        self.now += 1
        return ServiceMachine.execute(self, request)


class TimedCS1(TimingMixin, ServiceMachine):
    pass


class TimedUSB(TimingMixin, USBMachine):
    pass


class TimedSerial(TimingMixin, TransportMachine):
    pass


@unittest.skipUnless(f.HAVE_UNICORN and (f.OUT / 'transport.o').exists(), 'requires compiled Palm images')
class ExperimentalTimingTests(unittest.TestCase):
    def benchmark(self, kind, transport):
        m = kind()
        if 'nl_timing_pref_get' not in m.symbols:
            self.skipTest('experimental diagnostics are not built')
        if transport in (2, 3):
            # Install settings in the modeled saved-pref database, outside timing.
            m.saved_preferences[0x4e694c31, 0x4e34] = 1, config(transport)
        m.files[b'tnfs+tcp://tnfs.fujinet.online/PALM/nio-throughput.bin'] = bytes((i ^ (i >> 8)) & 255 for i in range(65536))
        m.uc.mem_write(0x9000, b'tnfs+tcp://tnfs.fujinet.online/PALM/nio-throughput.bin\0')
        m.call('NioTestBenchmark', struct.pack('>I', 0x9000), app=True,
               a5=m.app_a5, budget=70000000)
        values = struct.unpack('>6I6H', m.uc.mem_read(m.app_data + m.app_symbols['nio_benchmark'], 36))
        self.assertEqual(values[0], 65536)
        self.assertEqual(values[6:12], (128, 0, 0, 0, 0, 0))
        version, data = m.preferences[0x4e694c31, 0x4e39]
        self.assertEqual((version, len(data)), (1, 72))
        metadata = struct.unpack_from('>4H4I', data)
        self.assertEqual(metadata[:4], (72, 1, transport, 100))
        self.assertEqual(metadata[6], 128)
        for bucket in range(3):
            reads, read_ticks, writes, write_ticks = struct.unpack_from('>4I', data, 24 + 16 * bucket)
            self.assertEqual(reads, m.observed[bucket, 'read'])
            self.assertEqual(writes, m.observed[bucket, 'write'])
            self.assertEqual((read_ticks, write_ticks), (3 * reads, 7 * writes))
        marker_bucket = {1: 0, 2: 2, 3: 1}[transport]
        self.assertEqual(struct.unpack_from('>I', data, 24 + 16 * marker_bucket + 8)[0], 256)
        marker_reads = 2 if transport == 3 and 'usb_marker_clear' in m.symbols else 3
        self.assertEqual(metadata[7], 128 * (3 * marker_reads + 7 * 2 + 1))
        if transport == 3:
            expected_reads = 260 if 'usb_marker_clear' in m.symbols else 388
            self.assertEqual(m.observed[1, 'read'], expected_reads)
        self.assertEqual(m.exports, 1)
        self.assertEqual(len(m.requests), 128)
        self.assertTrue(all(p[:2] == b'\xfe\x03' for p in m.requests))
        self.assertEqual(m.globals, 0)
        # Test evidence only: never present injected ticks as hardware timing.
        path = f.OUT / 'experimental-timing-accounting.json'
        report = json.loads(path.read_text()) if path.exists() else {}
        report[str(transport)] = {
            'clock': 'synthetic: read=3 ticks, write=7 ticks, peer=1 tick',
            'hardware_measurement': False, 'chunk_bytes': 512, 'bytes_verified': values[0],
            'benchmark_ticks': values[1], 'benchmark_Bps': values[5],
            'exchanges': metadata[6], 'exchange_ticks': metadata[7],
            'session_ticks': metadata[5],
            'buckets': [dict(zip(('reads', 'read_ticks', 'writes', 'write_ticks'),
                       struct.unpack_from('>4I', data, 24 + 16 * i))) for i in range(3)]}
        if (0x4e694c31, 0x4e3a) in m.preferences and transport == 1:
            from test_palmos_shared_cs1_timing import decode
            report[str(transport)]['cs1_profile'] = decode(m.preferences[0x4e694c31, 0x4e3a][1])
            profile = report[str(transport)]['cs1_profile']
            self.assertEqual(profile['features'][0], 128)
            maps = 43008 - 128 * 265 + 128 * f.payload_maps(265)
            self.assertEqual(profile['attributes'][0], 3 * maps)
            self.assertEqual(sum(p['map_calls'] for p in profile['phases']), maps)
            self.assertEqual(sum(p['reads'] for p in profile['phases']), 37888)
            self.assertEqual(sum(p['writes'] for p in profile['phases']), 4864)
            report[str(transport)]['uri'] = 'tnfs+tcp://tnfs.fujinet.online/PALM/nio-throughput.bin'
        path.write_text(json.dumps(report, indent=2) + '\n')

    def test_springboard_read_write_ticks_counts_and_one_export(self):
        self.benchmark(TimedCS1, 1)

    def test_usb_read_write_ticks_counts_and_one_export(self):
        self.benchmark(TimedUSB, 3)

    def test_serial_read_write_ticks_counts_and_one_export(self):
        self.benchmark(TimedSerial, 2)
