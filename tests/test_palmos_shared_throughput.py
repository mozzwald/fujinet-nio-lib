"""Execute compiled Palm mapping guards and the app's fixed FileRead benchmark.

Trap counts measure work, not real hardware time. No service implementation is
replaced; the scripted peer only publishes ordinary wire replies.
"""
from collections import Counter
import struct
import unittest
import test_palmos_shared as f
from test_palmos_shared_network import HAS_NETWORK
from test_palmos_shared_services import ServiceMachine
from test_palmos_shared_cs1 import DiagnosticViewerMachine
if f.HAVE_UNICORN:
    from unicorn import UC_MEM_READ, UC_MEM_WRITE
    from unicorn.m68k_const import UC_M68K_REG_A7


class MappingMachine(ServiceMachine):
    def __init__(self):
        self.capture = False
        self.calls, self.attributes, self.accesses = Counter(), Counter(), Counter()
        self.expire = None
        self.expiry_fired = False
        self.late_accesses = []
        self.zero_version = False
        self.support_calls = 0
        self.mapping_change = None
        self.fail_clear = False
        super().__init__()

    def phase(self):
        return self.read16(self.globals + self.symbols['nl_cs1_diag'] + 8)

    def hook(self, uc, pc, size, context):
        fire = False
        if self.capture and bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f':
            trap, sp = self.read16(pc + 2), uc.reg_read(UC_M68K_REG_A7)
            self.calls[trap] += 1
            if trap == 0xa27b and self.read32(sp) == 0x68734578:
                self.support_calls += 1
            if trap == 0xa349 and self.read16(sp) == 6:
                attr = self.read16(sp + 4)
                self.attributes[attr] += 1
                fire = (self.expire == 'mapping' and self.phase() == 5 and attr == 4)
                marker = self.preferences.get((0x4e694c31, 0x4e32))
                if (self.expire == 'doorbell-mapping' and self.phase() == 2 and
                        attr == 4 and marker and struct.unpack('>IIHH', marker[1])[2]):
                    fire = True
            if (trap == 0xa2d3 and self.read16(sp + 4) == 0x4e32 and
                    self.expire == 'marker-readback' and self.phase() == 2):
                marker = self.preferences.get((0x4e694c31, 0x4e32))
                fire = bool(marker and struct.unpack('>IIHH', marker[1])[2])
            if trap == 0xa2d4 and self.read16(sp + 4) == 0x4e32:
                seq = self.read16(self.read32(sp + 8) + 8)
                fire = self.expire == 'marker' and self.phase() == 2 and bool(seq)
                if self.fail_clear and not seq:
                    self.pref_write_failure = True
        super().hook(uc, pc, size, context)
        if fire and not self.expiry_fired:
            self.expiry_fired = True
            self.now = 3500
        if (self.capture and self.zero_version and
                bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f' and
                self.read16(pc + 2) == 0xa27b and self.read32(sp) == 0x68734578):
            uc.mem_write(self.read32(sp + 6), b'\0' * 4)

    def bus(self, uc, access, address, size, value, context):
        if self.capture:
            self.accesses['write' if access == UC_MEM_WRITE else 'read'] += 1
            if self.now >= 3500:
                self.late_accesses.append(address)
        super().bus(uc, access, address, size, value, context)
        if self.capture and self.accesses['read'] == 1 and self.mapping_change:
            if self.mapping_change == 'size': self.card_size += 2
            else: self.present = False
            self.mapping_change = None


@unittest.skipUnless(f.HAVE_UNICORN and HAS_NETWORK, 'requires compiled Palm artifacts')
class MappingCostTests(unittest.TestCase):
    def prepare(self, kind=MappingMachine):
        m = kind()
        self.assertEqual(m.open(), 0)
        err, token, result = m.begin()
        self.assertEqual((err, result), (0, 0))
        m.files[b'host:/App.prc'] = bytes(range(256)) * 4
        m.uc.mem_write(0x9000, struct.pack('>IH', 0xa000, 1024))
        m.uc.mem_write(0x9400, b'host:/App.prc\0')
        m.uc.mem_write(0xb000, b'\xcc' * 256)
        args = struct.pack('>HIIIIIHII', 7, token, 0x9000, 0x9400,
                           0, 0xb000, 256, 0x9500, 0x9700)
        return m, token, args

    def test_one_feature_lookup_per_operation_without_caching_attributes(self):
        m, token, args = self.prepare()
        m.capture = True
        self.assertEqual(m.call('NioLibFileRead', args), 0)
        m.capture = False
        self.assertEqual(m.read16(0x9700), 0)
        self.assertEqual(bytes(m.uc.mem_read(0xb000, 256)), bytes(range(256)))
        # Cache only support; retain every dynamic query and exact bus trace.
        maps = 187
        self.assertEqual(m.accesses, {'read': 168, 'write': 17})
        self.assertEqual(m.attributes, {1: maps, 3: maps, 4: maps})
        self.assertEqual(m.calls[0xa27b], 1)
        self.assertEqual(m.support_calls, 1)
        self.assertEqual(m.calls[0xa085], 1)  # one exception scope, not one per word
        extra_timers = 12 if "nl_timing_pref_get" in m.symbols else 0
        if 'nl_cs1_timing' in m.symbols:
            # Sparse profiling adds clocks only, not features/attributes/I/O.
            self.assertEqual(sum(m.calls.values()) - m.calls[0xa0f7], 3 * maps + 14)
        else:
            self.assertEqual(sum(m.calls.values()), 5 * maps + 15 + extra_timers)
        self.assertEqual(bytes(m.uc.mem_read(
            m.globals + m.symbols['support_in_operation'], 1)), b'\0')
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))

    def test_support_is_rechecked_each_operation_before_any_selector(self):
        m, token, args = self.prepare()
        m.capture = True
        self.assertEqual(m.call('NioLibFileRead', args), 0)
        self.assertEqual(m.read16(0x9700), 0)
        before = m.calls.copy(), m.accesses.copy(), m.doorbells
        # hsEx is assumed stable within one synchronous card operation, not
        # across operations or for the lifetime of the installed library.
        m.handspring = False
        self.assertEqual(m.call('NioLibFileRead', args), 0)
        self.assertNotEqual(m.read16(0x9700), 0)
        self.assertEqual(m.calls[0xa27b] - before[0][0xa27b], 1)
        self.assertEqual(m.calls[0xa349], before[0][0xa349])
        self.assertEqual((m.accesses, m.doorbells), before[1:])
        m.handspring = True
        self.assertEqual(m.call('NioLibFileRead', args), 0)
        self.assertEqual(m.read16(0x9700), 0)
        self.assertEqual(m.support_calls, 3)
        m.capture = False
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))

    def test_failed_support_is_not_cached_and_discovery_remains_guarded(self):
        for failure in ('absent', 'zero-version'):
            with self.subTest(failure=failure):
                m = MappingMachine()
                self.assertEqual(m.open(), 0)
                m.capture = True
                m.handspring = failure != 'absent'
                m.zero_version = failure == 'zero-version'
                err, token, result = m.begin()
                self.assertEqual((err, token), (0, 0))
                self.assertNotEqual(result, 0)
                self.assertEqual(m.calls[0xa349], 0)
                self.assertFalse(m.accesses)
                self.assertEqual(m.support_calls, 1)
                m.handspring, m.zero_version = True, False
                err, token, result = m.begin()
                self.assertEqual((err, result), (0, 0))
                # Fresh cardInit and cardBegin scopes; discovery's provisional
                # CS1/card candidate must still pass per-word attributes.
                self.assertEqual(m.support_calls, 3)
                self.assertEqual(m.calls[0xa085], 2)
                self.assertEqual(m.read32(m.globals + m.symbols['_fn_palmos_cs1']), m.CS1)
                self.assertEqual(m.read16(m.globals + m.symbols['_fn_palmos_card']), 1)
                self.assertGreater(m.attributes[1], 0)
                self.assertEqual(m.attributes[3], m.attributes[4])
                m.capture = False
                self.assertEqual(m.end(token)[:2], (0, 0))
                self.assertEqual(m.close(), (0, 0))

    def test_dynamic_mapping_change_still_blocks_the_very_next_word(self):
        for change in ('size', 'removed'):
            with self.subTest(change=change):
                m, token, args = self.prepare()
                original_size = m.card_size
                m.capture, m.mapping_change = True, change
                self.assertEqual(m.call('NioLibFileRead', args), 0)
                self.assertNotEqual(m.read16(0x9700), 0)
                self.assertEqual(m.support_calls, 1)
                self.assertEqual(m.accesses, {'read': 1})
                self.assertEqual(m.doorbells, 0)
                self.assertEqual(bytes(m.uc.mem_read(0xb000, 256)), b'\xcc' * 256)
                m.capture = False
                m.card_size, m.present = original_size, True
                self.assertEqual(m.end(token)[:2], (0, 0))
                self.assertEqual(m.close(), (0, 0))

    def test_deadline_consumed_inside_mapping_prevents_the_next_word_access(self):
        m, token, args = self.prepare()
        m.capture, m.expire = True, 'mapping'
        m.call('NioLibFileRead', args)
        m.capture = False
        self.assertTrue(m.expiry_fired)
        self.assertEqual(m.read16(0x9700), 6)
        self.assertFalse(m.late_accesses)
        self.assertEqual(bytes(m.uc.mem_read(0xb000, 256)), b'\xcc' * 256)
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(m.end(token)[:2], (0, 0))

    def test_deadline_consumed_persisting_marker_never_posts_doorbell(self):
        for mode, fail_clear in (('marker', False), ('marker', True),
                                 ('marker-readback', False), ('doorbell-mapping', False)):
            with self.subTest(mode=mode, fail_clear=fail_clear):
                m, token, args = self.prepare()
                m.capture, m.expire, m.fail_clear = True, mode, fail_clear
                m.call('NioLibFileRead', args)
                m.capture = False
                self.assertTrue(m.expiry_fired)
                self.assertEqual(m.read16(0x9700), 6)
                self.assertFalse(m.late_accesses)
                self.assertEqual(m.doorbells, 0)
                marker = m.preferences[0x4e694c31, 0x4e32]
                self.assertEqual(struct.unpack('>IIHH', marker[1])[2], int(fail_clear))
                self.assertEqual(m.end(token)[1], 6 if fail_clear else 0)
                if fail_clear:
                    self.assertEqual(m.preferences[0x4e694c31, 0x4e32], marker)


class BenchmarkMachine(ServiceMachine):
    def execute(self, request):
        if request[:2] == b'\xfe\x03': self.now += 1
        return super().execute(request)


@unittest.skipUnless(f.HAVE_UNICORN and HAS_NETWORK, 'requires compiled Palm artifacts')
class FileBenchmarkTests(unittest.TestCase):
    def run_benchmark(self, contents):
        m = BenchmarkMachine()
        m.files[b'host:/nio-throughput.bin'] = contents
        m.uc.mem_write(0x9000, b'host:/nio-throughput.bin\0')
        m.call('NioTestBenchmark', struct.pack('>I', 0x9000), app=True,
               a5=m.app_a5, budget=60000000)
        values = struct.unpack('>6I6H', m.uc.mem_read(
            m.app_data + m.app_symbols['nio_benchmark'], 36))
        self.assertEqual(m.globals, 0)
        return m, values

    def test_complete_fixture_verifies_every_byte_and_reports_separate_timings(self):
        m, values = self.run_benchmark(bytes((i ^ (i >> 8)) & 255 for i in range(65536)))
        self.assertEqual(values, (65536, 128, 0, 0, 8355840, 51200,
                                  128, 0, 0, 0, 0, 0))
        self.assertEqual(len(m.requests), 128)
        self.assertTrue(all(p[:2] == b'\xfe\x03' for p in m.requests))
        self.assertEqual([struct.unpack_from('<I', p, 9 + len(b'host:/nio-throughput.bin'))[0] for p in m.requests],
                         list(range(0, 65536, 512)))
        self.assertTrue(all(struct.unpack_from('<H', p, 13 + len(b'host:/nio-throughput.bin'))[0] == 512
                            for p in m.requests))

    def test_short_file_or_wrong_second_block_stops_without_retry(self):
        first = bytes((i ^ (i >> 8)) & 255 for i in range(512))
        for contents, calls, good in ((b'', 1, 0), (first[:-1], 1, 0), (first * 2, 2, 512)):
            with self.subTest(calls=calls):
                m, values = self.run_benchmark(contents)
                self.assertEqual(values[0], good)
                self.assertEqual(values[6:9], (calls, 1, 5))
                self.assertEqual(values[10:], (0, 0))
                self.assertEqual(len(m.requests), calls)
                self.assertEqual(m.read16(m.app_data + m.app_symbols['nio_benchmark_failure']),
                                 3 if calls == 1 else 4)

    def test_benchmark_redraw_preserves_uri_field_and_buttons(self):
        m = DiagnosticViewerMachine(); m.form = 1020
        m.call('draw_results', b'', app=True, a5=m.app_a5)
        self.assertEqual(m.erases, [(2, 61, 156, 72)])
        self.assertTrue(all(61 <= y < 133 for _, _, y in m.text_draws))
        self.assertEqual(m.mmio, 0)
