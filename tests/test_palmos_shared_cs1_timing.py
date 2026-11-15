"""Experimental CS1 accounting: real m68k code, injected costs, no speed claims."""
from collections import Counter
import struct
import unittest
import test_palmos_shared as f
from test_palmos_shared_services import ServiceMachine
import test_palmos_shared_throughput as throughput
from test_palmos_shared_card_fault import CardFaultMachine
from test_palmos_shared_cs1 import DiagnosticViewerMachine
from test_palmos_shared_usb import USBMachine
from test_palmos_shared_transports import config
if f.HAVE_UNICORN:
    from unicorn import UC_MEM_WRITE
    from unicorn.m68k_const import UC_M68K_REG_A7

PREF = 0x4e694c31, 0x4e3a


def decode(data):
    header = struct.unpack_from('>4H4I', data)
    result = dict(zip(('size', 'version', 'ticks_per_second', 'sample_shift',
                       'started', 'exchanges', 'exchange_ticks', 'faults'), header))
    result['features'] = struct.unpack_from('>3I', data, 24)
    result['attributes'] = struct.unpack_from('>3I', data, 36)
    result.update(zip(('poll_checks', 'result_attempts', 'reply_attempts', 'settle_attempts'),
                      struct.unpack_from('>4I', data, 48)))
    result['phases'] = []
    for i in range(3):
        values = struct.unpack_from('>12I', data, 64 + 48 * i)
        result['phases'].append(dict(zip(('spans', 'ticks', 'map_calls', 'map_ticks',
            'pref_calls', 'pref_ticks', 'reads', 'read_samples', 'read_ticks',
            'writes', 'write_samples', 'write_ticks'), values)))
    return result


def live(m):
    return decode(bytes(m.uc.mem_read(m.globals + m.symbols['nl_cs1_timing'], 208)))


class AccountingMachine(ServiceMachine):
    def __init__(self):
        self.inject_costs = False
        self.cost_calls = Counter()
        self.words = Counter()
        self.exports = 0
        super().__init__()

    def hook(self, uc, pc, size, context):
        cost, kind = 0, None
        if bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f':
            trap, sp = self.read16(pc + 2), uc.reg_read(UC_M68K_REG_A7)
            if trap == 0xa2d4 and self.read16(sp + 4) == 0x4e3a:
                self.exports += 1
            if self.inject_costs:
                if trap == 0xa27b and self.read32(sp) == 0x68734578:
                    cost, kind = 1, 'feature'
                elif trap == 0xa349 and self.read16(sp) == 6:
                    cost, kind = 1, 'attribute'
                elif trap in (0xa2d3, 0xa2d4) and self.read16(sp + 4) in (0x4e32, 0x4e37, 0x4e38):
                    cost, kind = (3, 'pref_read') if trap == 0xa2d3 else (7, 'pref_write')
        super().hook(uc, pc, size, context)
        if kind:
            self.cost_calls[kind] += 1
            self.now += cost

    def bus(self, uc, access, address, size, value, context):
        super().bus(uc, access, address, size, value, context)
        if self.inject_costs:
            self.words['writes' if access == UC_MEM_WRITE else 'reads'] += 1
            self.now += 1


class MappingFaultMachine(AccountingMachine, CardFaultMachine):
    def __init__(self):
        self.arm_mapping_fault = False
        super().__init__()

    def hook(self, uc, pc, size, context):
        arm = False
        if self.arm_mapping_fault and bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f':
            sp = uc.reg_read(UC_M68K_REG_A7)
            arm = (self.read16(pc + 2) == 0xa349 and self.read16(sp) == 6 and
                   self.read16(sp + 4) == 3 and self.phase() == 5)
        super().hook(uc, pc, size, context)
        if arm:
            self.arm_mapping_fault = False
            self.raise_next = True


@unittest.skipUnless(f.HAVE_UNICORN and (f.OUT / 'cs1.o').exists(), 'requires compiled Palm images')
class CS1TimingTests(unittest.TestCase):
    def prepare(self, kind=AccountingMachine):
        m = kind()
        if 'nl_cs1_timing' not in m.symbols:
            self.skipTest('requires experimental CS1 timing build')
        # Use the existing short-URI, 256-byte guard fixture for exact counts.
        return throughput.MappingCostTests().prepare(kind=lambda: m)

    def finished(self, m, p):
        self.assertEqual(p['size'], 208)
        self.assertEqual((p['version'], p['ticks_per_second'], p['sample_shift']), (1, 100, 6))
        self.assertEqual(p['exchanges'], 1)
        self.assertEqual(sum(x['ticks'] for x in p['phases']), p['exchange_ticks'])
        for phase in p['phases']:
            self.assertLessEqual(phase['map_ticks'] + phase['pref_ticks'], phase['ticks'])
            self.assertLessEqual(phase['read_samples'], phase['reads'] // 64)
            self.assertLessEqual(phase['write_samples'], phase['writes'] // 64)
        self.assertEqual(m.read16(m.globals + m.symbols['nl_cs1_timing_active']), 0)
        self.assertEqual(m.read16(m.globals + m.symbols['nl_cs1_map_active']), 0)
        self.assertEqual(m.read32(m.globals + m.symbols['nl_cs1_timing_current']), 0)

    def test_exact_mapping_preference_and_sampled_word_costs_without_added_mmio(self):
        m, token, args = self.prepare()
        m.inject_costs = True
        self.assertEqual(m.call('NioLibFileRead', args), 0)
        m.inject_costs = False
        self.assertEqual(m.read16(0x9700), 0)
        p = live(m)
        self.finished(m, p)
        maps = 187 - 137 + f.payload_maps(137)
        attributes = 3 * maps
        self.assertEqual(p['features'], (1, 0, 0))
        self.assertEqual(p['attributes'], (attributes, attributes // 64, attributes // 64))
        self.assertEqual(sum(x['map_calls'] for x in p['phases']), maps)
        self.assertEqual(sum(x['map_ticks'] for x in p['phases']), attributes)
        self.assertEqual(sum(x['pref_calls'] for x in p['phases']), 5)
        self.assertEqual(sum(x['pref_ticks'] for x in p['phases']), 23)
        self.assertEqual(m.words, {'reads': 168, 'writes': 17})
        for kind in ('reads', 'writes'):
            self.assertEqual(sum(x[kind] for x in p['phases']), m.words[kind])
        self.assertEqual(sum(x['read_samples'] for x in p['phases']), 2)
        self.assertEqual(sum(x['read_ticks'] for x in p['phases']), 2)
        self.assertEqual(p['exchange_ticks'], attributes + 209)
        self.assertEqual([x['spans'] for x in p['phases']], [4, 3, 1])
        self.assertEqual([p[k] for k in ('poll_checks', 'result_attempts', 'reply_attempts', 'settle_attempts')],
                         [1, 2, 1, 4])
        self.assertEqual((m.doorbells, len(m.requests)), (1, 1))
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(decode(m.preferences[PREF][1]), p)
        self.assertEqual(m.exports, 1)
        self.assertEqual(m.close(), (0, 0))

    def test_timeout_is_charged_to_polling_and_does_not_erase_pending(self):
        m, token, args = self.prepare()
        m.silent = True
        self.assertEqual(m.call('NioLibFileRead', args), 0)
        self.assertEqual(m.read16(0x9700), 6)
        p = live(m)
        self.finished(m, p)
        self.assertGreater(p['phases'][1]['ticks'], 0)
        self.assertEqual(p['phases'][2]['spans'], 0)
        self.assertEqual(m.doorbells, 1)
        marker = m.preferences[0x4e694c31, 0x4e32]
        self.assertNotEqual(struct.unpack('>IIHH', marker[1])[2], 0)
        self.assertEqual(m.end(token)[1], 6)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e32], marker)
        self.assertEqual(m.close(), (0, 0))

    def test_card_fault_closes_interrupted_mapping_before_diagnostic_io(self):
        m, token, args = self.prepare(MappingFaultMachine)
        m.inject_costs = m.arm_mapping_fault = True
        self.assertEqual(m.call('NioLibFileRead', args), 0)
        m.inject_costs = False
        self.assertEqual(m.read16(0x9700), 5)
        p = live(m)
        self.finished(m, p)
        self.assertEqual((p['faults'], len(m.injected), m.doorbells), (1, 1, 1))
        self.assertEqual(m.read32(m.CARD_EXCEPTION_LIST), m.OUTER)
        self.assertEqual(m.read16(m.globals + m.symbols['nl_busy']), 0)
        self.assertEqual(bytes(m.uc.mem_read(0xb000, 256)), b'\xcc' * 256)
        self.assertEqual(m.end(token)[1], 6)
        self.assertEqual(m.close(), (0, 0))

    def test_usb_does_not_capture_or_export_a_cs1_profile(self):
        m = USBMachine()
        if 'nl_cs1_timing' not in m.symbols:
            self.skipTest('requires experimental CS1 timing build')
        self.assertEqual(m.open(), 0)
        self.assertEqual(m.set_config(config(3)), 0)
        err, token, result = m.begin()
        self.assertEqual((err, result), (0, 0))
        self.assertEqual(m.clock(token)[:2], (0, 0))
        self.assertEqual(live(m)['exchanges'], 0)
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertNotIn(PREF, m.preferences)
        self.assertEqual(m.close(), (0, 0))

    def test_viewer_checks_correlation_and_does_not_access_bus(self):
        m = DiagnosticViewerMachine()
        if 'show_cs1_timing' not in m.app_symbols:
            self.skipTest('requires experimental CS1 timing app')
        legacy = struct.pack('>4H4I', 72, 1, 1, 100, 1234, 30, 1, 30) + bytes(48)
        data = struct.pack('>4H4I', 208, 1, 100, 6, 1234, 1, 30, 0) + bytes(24) + struct.pack('>4I', 1, 2, 1, 4)
        data += struct.pack('>12I', 1, 10, 1, 1, 1, 1, 64, 1, 1, 0, 0, 0) * 3
        m.preferences[PREF] = 1, data
        m.uc.mem_write(0x9000, legacy)
        m.call('show_cs1_timing', struct.pack('>I', 0x9000), app=True, a5=m.app_a5)
        self.assertEqual(len(m.dialogs), 4)
        self.assertIn('Poll net 8 ticks', m.dialogs[3][0])
        self.assertEqual(m.mmio, 0)
        m.dialogs.clear()
        bad = bytearray(data); struct.pack_into('>I', bad, 8, 1235)
        m.preferences[PREF] = 1, bytes(bad)
        m.call('show_cs1_timing', struct.pack('>I', 0x9000), app=True, a5=m.app_a5)
        self.assertEqual(len(m.dialogs), 1)
        self.assertIn('No matching CS1 timing', m.dialogs[0][0])
        self.assertEqual(m.mmio, 0)
