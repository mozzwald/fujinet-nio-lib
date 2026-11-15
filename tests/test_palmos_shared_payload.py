"""Experimental scalar read certificates in real compiled Palm operations.

OS traps and the CS1 peer are modeled. No library service/guard is replaced;
argument corruption and non-faulting map changes explicitly exercise rejection.
This does not qualify physical removal interrupts or electrical bus timing.
"""
import struct
import unittest
import test_palmos_shared as f
from test_palmos_shared_throughput import MappingMachine
from test_palmos_shared_card_fault import CardFaultMachine
from test_palmos_shared_network import reply, checksum
if f.HAVE_UNICORN:
    from unicorn import UC_MEM_READ, UC_MEM_WRITE
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC


class CertificateMachine(MappingMachine, CardFaultMachine):
    def __init__(self):
        self.reply_packet = None
        self.attempts, self.current = [], None
        self.end_return = None
        self.payload_reads = 0
        self.access_trace = []
        self.last_attrs = 0
        self.corrupt_first = self.repair_word = False
        self.corrupt_each = False
        self.change_after = self.expire_after = None
        self.remove_after = None
        self.reported_removed = False
        self.expire_validation = None
        self.replace_address = None
        self.discovery_address = None
        self.redirect_write = False
        self.active_at_fault = None
        self.free_permission = []
        super().__init__()

    def active(self):
        return bool(self.uc.mem_read(self.globals + self.symbols['nl_payload_active'], 1)[0])

    def execute(self, request):
        if self.reply_packet is None:
            return super().execute(request)
        self.requests.append(request)
        assert checksum(request) == request[4]
        return self.reply_packet

    def hook(self, uc, pc, size, context):
        if (self.globals and bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f' and
                self.read16(pc + 2) == 0xa012):
            self.free_permission.append(self.active())
        if self.capture:
            sp = uc.reg_read(UC_M68K_REG_A7)
            if pc == self.end_return:
                self.current = self.end_return = None
            if pc == self.CODE + self.symbols['nl_cs1_payload_begin']:
                self.current = {'bytes': self.read16(sp + 4), 'words': [],
                                'maps': [], 'stage': 'begin', 'active_at_begin': self.active()}
                self.attempts.append(self.current)
            if pc == self.CODE + self.symbols['nl_cs1_payload_end']:
                self.current['stage'] = 'end'
                self.end_return = self.read32(sp)
            if (self.current and bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f' and
                    self.read16(pc + 2) == 0xa349 and self.read16(sp) == 6):
                attr = self.read16(sp + 4)
                if attr == 1:
                    self.current['maps'].append(len(self.current['words']))
                if attr == 4 and self.expire_validation == self.current['stage']:
                    self.now = 3500
                    self.expire_validation = None
            if (self.current and pc == self.CODE + self.symbols['nl_bus_read'] and
                    self.read32(sp + 4) >= self.CS1 + 0x1000):
                if self.replace_address is not None:
                    uc.mem_write(sp + 4, struct.pack('>I', self.replace_address))
                    self.replace_address = None
                if self.redirect_write:
                    self.redirect_write = False
                    self.card_size += 2
                    uc.reg_write(UC_M68K_REG_PC, self.CODE + self.symbols['nl_bus_write'])
                    return
            elif (not self.current and self.discovery_address is not None and
                  pc == self.CODE + self.symbols['nl_bus_read']):
                uc.mem_write(sp + 4, struct.pack('>I', self.discovery_address))
                self.discovery_address = None
        super().hook(uc, pc, size, context)
        # Model an installed-attribute transition independently of a bus fault:
        # this test deliberately keeps the old window readable until checked.
        if (self.capture and self.reported_removed and
                bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f' and
                self.read16(pc + 2) == 0xa349 and self.read16(sp) == 6 and
                self.read16(sp + 4) == 1):
            uc.mem_write(self.read32(sp + 6), b'\0')

    def bus(self, uc, access, address, size, value, context):
        if self.capture:
            payload = self.current is not None and access == UC_MEM_READ and address >= self.CS1 + 0x1000
            attrs = self.attributes[1]
            self.access_trace.append((access, address, attrs - self.last_attrs, self.active()))
            self.last_attrs = attrs
            if payload:
                assert self.current is not None
                self.current['stage'] = 'payload'
                self.current['words'].append(address)
                self.payload_reads += 1
        super().bus(uc, access, address, size, value, context)
        if self.capture and self.current is not None and access == UC_MEM_READ and address >= self.CS1 + 0x1000:
            n = len(self.current['words'])
            if (self.corrupt_each or (self.corrupt_first and len(self.attempts) == 1)) and n == 1:
                uc.mem_write(address, struct.pack('>H', self.read16(address) ^ 1))
                if self.repair_word: self.corrupt_first = False
            if n == self.change_after:
                self.card_size += 2
                self.change_after = None
            if n == self.remove_after:
                self.reported_removed = True
                self.remove_after = None
            if n == self.expire_after:
                self.now = 3500
                self.expire_after = None

    def raise_card_fault(self):
        self.active_at_fault = self.active()
        super().raise_card_fault()


@unittest.skipUnless(f.HAVE_UNICORN and f.CS1_PAYLOAD_WORDS,
                     'requires a compiled Design B Palm image')
class PayloadCertificateTests(unittest.TestCase):
    def machine(self):
        m = CertificateMachine()
        self.assertEqual(m.open(), 0)
        err, token, result = m.begin()
        self.assertEqual((err, result), (0, 0))
        return m, token

    def raw(self, m, token, packet, capacity=1024):
        m.reply_packet = packet
        m.uc.mem_write(0xb000, b'\xcc' * 1056)
        m.capture = True
        args = struct.pack('>HIHHIHIHII', 7, token, 0x70, 0x55,
                           0, 0, 0xb000, capacity, 0x9500, 0x9700)
        self.assertEqual(m.call('NioLibRawCall', args, budget=6000000), 0)
        m.capture = False
        self.assertFalse(m.active())
        self.assertEqual(m.read16(m.globals + m.symbols['nl_payload_left']), 0)
        self.assertEqual(m.read32(m.CARD_EXCEPTION_LIST), m.OUTER)
        self.assertEqual(m.read16(m.globals + m.symbols['nl_busy']), 0)
        self.assertEqual(m.doorbells, len(m.requests))
        return m.read16(0x9700)

    @staticmethod
    def packet(words, odd=False):
        size = words * 2 - int(odd)
        return reply(0x70, 0x55, bytes((i * 17) & 255 for i in range(size - 7))) if size >= 7 else bytes(size)

    def expected(self, words):
        return [0] + list(range(f.CS1_PAYLOAD_WORDS, words, f.CS1_PAYLOAD_WORDS)) + [words]

    def test_checkpoints_for_zero_one_and_interval_boundaries(self):
        for words in sorted({0, 1, 31, 32, 33, f.CS1_PAYLOAD_WORDS, f.CS1_PAYLOAD_WORDS + 1}):
            with self.subTest(words=words):
                m, token = self.machine()
                result = self.raw(m, token, self.packet(words))
                self.assertEqual(result, 0 if words >= 4 else 5)
                self.assertEqual(len(m.attempts), 1 if words >= 4 else 4)
                for attempt in m.attempts:
                    self.assertFalse(attempt['active_at_begin'])
                    self.assertEqual(attempt['maps'], self.expected(words))
                    self.assertEqual(attempt['words'], [m.CS1 + 0x1000 + 2*i for i in range(words)])
                self.assertEqual(m.end(token)[1], 0 if result == 0 else 6)
                self.assertEqual(m.close(), (0, 0))

    def test_odd_reply_short_user_buffer_and_guard_bytes(self):
        for odd, capacity in ((False, 1024), (True, 1024), (True, 1)):
            with self.subTest(odd=odd, capacity=capacity):
                m, token = self.machine(); packet = self.packet(33, odd)
                result = self.raw(m, token, packet, capacity)
                self.assertEqual(result, 5 if capacity == 1 else 0)
                self.assertEqual(m.attempts[0]['maps'], self.expected(33))
                self.assertEqual(len(m.attempts[0]['words']), 33)
                if capacity > 1:
                    self.assertEqual(bytes(m.uc.mem_read(0xb000, len(packet)-7)), packet[7:])
                else:
                    self.assertEqual(bytes(m.uc.mem_read(0xb000, 1024)), b'\xcc' * 1024)
                self.assertEqual(bytes(m.uc.mem_read(0xb000 + 1024, 32)), b'\xcc' * 32)
                m.end(token); self.assertEqual(m.close(), (0, 0))

    def test_maximum_reply_discards_tail_but_checks_every_word(self):
        for words, odd in ((4096, False), (513, True)):
            with self.subTest(words=words, odd=odd):
                m, token = self.machine()
                self.assertEqual(self.raw(m, token, self.packet(words, odd)), 5)
                self.assertEqual(len(m.attempts), 4)  # exceeds the local wire buffer
                for attempt in m.attempts:
                    self.assertEqual(attempt['maps'], self.expected(words))
                    self.assertEqual(len(attempt['words']), words)
                self.assertEqual(bytes(m.uc.mem_read(0xb000, 1056)), b'\xcc' * 1056)
                self.assertEqual(m.end(token)[1], 6)
                self.assertEqual(m.close(), (0, 0))

    def test_oversized_wire_length_never_grants_a_certificate(self):
        m, token = self.machine()
        self.assertEqual(self.raw(m, token, bytes(8193)), 5)
        self.assertFalse(m.attempts)
        self.assertEqual(m.payload_reads, 0)
        self.assertEqual(len(m.requests), 1)
        m.end(token); self.assertEqual(m.close(), (0,0))

    def test_checksum_retry_and_later_exchange_get_fresh_certificates(self):
        m, token = self.machine(); m.corrupt_first = m.repair_word = True
        self.assertEqual(self.raw(m, token, self.packet(33)), 0)
        self.assertEqual(len(m.attempts), 2)
        self.assertEqual(len(m.requests), 1)  # re-read, never replay
        self.assertEqual(self.raw(m, token, self.packet(33)), 0)
        self.assertEqual(len(m.attempts), 3)
        self.assertEqual(len(m.requests), 2)
        for a in m.attempts:
            self.assertFalse(a['active_at_begin'])
            self.assertEqual(a['maps'], self.expected(33))
        self.assertEqual(m.end(token)[1], 0)
        self.assertEqual(m.close(), (0, 0))

    def test_exhausted_checksum_retries_do_not_replay_or_leave_permission(self):
        for kind in ('word', 'packet'):
            with self.subTest(kind=kind):
                m, token = self.machine()
                packet = bytearray(self.packet(33))
                if kind == 'word': m.corrupt_each = True
                else: packet[4] ^= 1  # valid word checksum, bad packet checksum
                self.assertEqual(self.raw(m, token, bytes(packet)), 5)
                self.assertEqual(len(m.attempts), 4)
                self.assertEqual(len(m.requests), 1)
                for a in m.attempts: self.assertEqual(a['maps'], self.expected(33))
                self.assertEqual(m.end(token)[1], 6)
                self.assertEqual(m.close(), (0, 0))

    def test_writes_and_control_reads_keep_full_validation(self):
        m, token = self.machine()
        self.assertEqual(self.raw(m, token, self.packet(33)), 0)
        for kind, address, validations, active in m.access_trace:
            if kind == UC_MEM_WRITE or address < m.CS1 + 0x1000:
                self.assertGreaterEqual(validations, 1, hex(address))
                self.assertFalse(active)
        self.assertEqual(m.end(token)[1], 0)
        self.assertEqual(m.close(), (0, 0))

    def test_live_certificate_never_authorizes_a_write_or_control_read(self):
        for write in (False, True):
            with self.subTest(write=write):
                m, token = self.machine()
                if write: m.redirect_write = True
                else:
                    m.replace_address = m.CS1 + 4
                    # After the substituted control read cancels permission,
                    # a map change must still stop the next scalar data read.
                    m.change_after = 1
                self.assertEqual(self.raw(m, token, self.packet(33)), 5)
                self.assertEqual(m.doorbells, 1)
                self.assertFalse(m.active())
                if not write:
                    for kind, address, validations, active in m.access_trace:
                        if address == m.CS1 + 4:
                            self.assertGreaterEqual(validations, 1)
                            self.assertFalse(active)
                m.card_size = 0x1000000
                m.end(token); self.assertEqual(m.close(), (0, 0))

    def test_silent_mapping_change_is_detected_at_checkpoint_or_final_validation(self):
        words = f.CS1_PAYLOAD_WORDS + 1
        for at in (1, f.CS1_PAYLOAD_WORDS, words):
            with self.subTest(changed_after=at):
                m, token = self.machine(); m.change_after = at
                self.assertEqual(self.raw(m, token, self.packet(words)), 5)
                allowed = min(((at + f.CS1_PAYLOAD_WORDS - 1)//f.CS1_PAYLOAD_WORDS)*f.CS1_PAYLOAD_WORDS, words)
                self.assertEqual(m.payload_reads, allowed)
                self.assertEqual(m.diagnostic()[6], 2)
                self.assertEqual(m.diagnostic()[21], 7)
                self.assertEqual(bytes(m.uc.mem_read(0xb000, 1056)), b'\xcc' * 1056)
                m.card_size = 0x1000000
                m.end(token); self.assertEqual(m.close(), (0, 0))

    def test_deadline_is_checked_between_words_and_during_each_validation(self):
        for point in ('word', 'begin', 'payload', 'end'):
            with self.subTest(point=point):
                m, token = self.machine()
                if point == 'word': m.expire_after = 1
                else: m.expire_validation = point
                self.assertEqual(self.raw(m, token, self.packet(f.CS1_PAYLOAD_WORDS + 1)), 6)
                self.assertFalse(m.late_accesses)
                self.assertEqual(m.payload_reads, {'word':1, 'begin':0,
                    'payload':f.CS1_PAYLOAD_WORDS, 'end':f.CS1_PAYLOAD_WORDS+1}[point])
                self.assertEqual(m.diagnostic()[6], 1)
                m.end(token); self.assertEqual(m.close(), (0, 0))

    def test_card_fault_inside_certified_payload_retains_pending_and_restores_scope(self):
        m, token = self.machine(); m.fault = ('read', 5, 0x1000 + 2)
        self.assertEqual(self.raw(m, token, self.packet(33)), 5)
        self.assertTrue(m.active_at_fault)
        self.assertEqual(len(m.injected), 1)
        self.assertEqual(m.mmio, m.injected[0][2])
        self.assertEqual(m.diagnostic()[6], 4)
        self.assertNotEqual(struct.unpack('>IIHH', m.preferences[0x4e694c31,0x4e32][1])[2], 0)
        m.present = True
        self.assertEqual(m.end(token)[1], 6)
        self.assertEqual(m.close(), (0, 0))

    def test_removed_attribute_without_a_bus_fault_is_detected_at_checkpoint(self):
        m, token = self.machine(); m.remove_after = 1
        self.assertEqual(self.raw(m, token, self.packet(f.CS1_PAYLOAD_WORDS + 1)), 5)
        self.assertEqual(m.payload_reads, f.CS1_PAYLOAD_WORDS)
        self.assertFalse(m.injected)
        self.assertEqual((m.diagnostic()[6], m.diagnostic()[21]), (2,3))
        self.assertEqual(len(m.requests), 1)
        m.reported_removed = False
        m.end(token); self.assertEqual(m.close(), (0,0))

    def test_payload_address_must_be_aligned_consecutive_and_inside_reply(self):
        for offset in (0x1001, 0x1002, 0x1000+66, 0x1000000, 0xfffffffe):
            with self.subTest(offset=hex(offset)):
                m, token = self.machine(); m.replace_address = m.CS1 + offset
                if m.replace_address > 0xffffffff: m.replace_address &= 0xffffffff
                self.assertEqual(self.raw(m, token, self.packet(33)), 5)
                self.assertEqual(m.payload_reads, 0)
                self.assertEqual(m.diagnostic()[6], 2)
                self.assertEqual(bytes(m.uc.mem_read(0xb000, 1056)), b'\xcc' * 1056)
                m.end(token); self.assertEqual(m.close(), (0, 0))

    def test_bad_apertures_fail_before_discovery_mmio(self):
        for base, size in ((0x28000000,0x20000), (0x28000000,0x30001),
                           (0x28000001,0x1000000), (0xffff0000,0x1000000),
                           (0xfd000000,0x2000000)):
            with self.subTest(base=hex(base), size=hex(size)):
                m = CertificateMachine(); self.assertEqual(m.open(), 0)
                m.card_base, m.card_size = base, size
                self.assertNotEqual(m.begin()[2], 0)
                self.assertEqual((m.mmio,m.doorbells), (0,0))
                self.assertFalse(m.active())
                self.assertEqual(m.read32(m.CARD_EXCEPTION_LIST), m.OUTER)
                self.assertEqual(m.close(), (0,0))

    def test_aperture_last_word_and_end_exclusive_addresses(self):
        for offset, accesses in ((0x3fffe,1), (0x40000,0), (0x3ffff,0), (-2,0)):
            with self.subTest(offset=offset):
                m = CertificateMachine(); self.assertEqual(m.open(),0)
                m.card_size = 0x40000
                m.card_base = m.CS1 - m.card_size
                m.discovery_address = m.CS1 + offset
                m.capture = True
                self.assertNotEqual(m.begin()[2],0)  # substituted MAGIC is not valid
                m.capture = False
                self.assertEqual(m.mmio,accesses)
                self.assertFalse(m.active())
                self.assertEqual(m.close(),(0,0))

    def test_certificate_cannot_start_outside_card_scope_and_reset_close_clear_state(self):
        m, token = self.machine()
        a4 = m.globals + m.symbols['edata']
        self.assertEqual(m.call('nl_cs1_payload_begin', struct.pack('>H', 66), a4=a4) & 255, 0)
        self.assertFalse(m.active())
        m.end(token)
        # Seed stale private RAM only, never perform MMIO or post a request.
        # Public reset and last Close must independently revoke such permission.
        for operation in ('reset', 'close'):
            m.uc.mem_write(m.globals + m.symbols['nl_payload_active'], b'\1')
            m.uc.mem_write(m.globals + m.symbols['nl_payload_left'], b'\0\x20')
            if operation == 'reset':
                self.assertEqual(m.call('NioLibResetTransport', struct.pack('>3H', 7, 1, 1)), 0)
                self.assertFalse(m.active())
                self.assertEqual(m.read16(m.globals + m.symbols['nl_payload_left']), 0)
            else:
                self.assertEqual(m.close(), (0,0))
                self.assertEqual(m.free_permission, [False])
