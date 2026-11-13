"""Compiled SDK-style card exception recovery, not real ROM/ISR qualification.

Faults redirect the CPU at the actual volatile MOVE.W (after mapping checks),
restoring the SDK's ErrJumpBuf registers to re-enter the compiled catch path.
The OS jump is modeled; no NioLib error handler or service is substituted.
"""
import struct
import unittest
import test_palmos_shared as f
from test_palmos_shared_network import HAS_NETWORK
from test_palmos_shared_services import ServiceMachine
if f.HAVE_UNICORN:
    from unicorn import UC_MEM_WRITE, m68k_const
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC, UC_M68K_REG_D0


class CardFaultMachine(ServiceMachine):
    OUTER = 0x7e000

    def __init__(self):
        self.fault = None
        self.injected = []
        self.after_doorbell = False
        self.raise_next = False
        self.last_word = None
        self.guard_starts = 0
        super().__init__()
        self.uc.mem_write(self.CARD_EXCEPTION_LIST, struct.pack('>I', self.OUTER))

    def diagnostic(self):
        return struct.unpack('>22H3I', self.preferences[0x4e694c31, 0x4e37][1])

    def phase(self):
        return self.read16(self.globals + self.symbols['nl_cs1_diag'] + 8)

    def raise_card_fault(self):
        frame = self.read32(self.CARD_EXCEPTION_LIST)
        assert frame not in (0, self.OUTER), 'unprotected module access'
        assert self.read32(frame) == self.OUTER, 'unexpected nested library guard'
        jump = struct.unpack('>12I', self.uc.mem_read(frame + 4, 48))
        self.uc.mem_write(frame + 52, struct.pack('>I', 0x1234beef))
        self.injected.append((self.phase(), self.last_word, self.mmio))
        self.fault = None; self.raise_next = False
        self.present = False
        # Simulate clobbering by deeper code before the OS restores the jump
        # context. In particular A4 must be restored before the catch uses it.
        for name in self.JUMP_REGISTERS:
            if name not in ('PC', 'A7'):
                self.uc.reg_write(getattr(m68k_const, 'UC_M68K_REG_' + name), 0xdead4444)
        for name, value in zip(self.JUMP_REGISTERS, jump):
            self.uc.reg_write(getattr(m68k_const, 'UC_M68K_REG_' + name), value)
        self.uc.reg_write(UC_M68K_REG_D0, 1)

    def hook(self, uc, pc, size, context):
        if self.raise_next:
            self.raise_card_fault()
            return
        # Decode actual MOVE.W (An) operands at arbitrary linked/relocated
        # code addresses, rather than depending on fixed instruction offsets.
        opcode = self.read16(pc)
        word = None
        if opcode & 0xf000 == 0x3000:
            for kind, mode, reg in (('read', (opcode >> 3) & 7, opcode & 7),
                                    ('write', (opcode >> 6) & 7, (opcode >> 9) & 7)):
                if mode == 2:
                    address = uc.reg_read(getattr(m68k_const, 'UC_M68K_REG_A' + str(reg)))
                    if self.CS1 <= address < self.CS1 + 0x100000:
                        word = kind, address
        if word:
            kind, address = word
            assert address == self.read32(self.globals + self.symbols['access_address'])
            self.last_word = address
            if self.fault == (kind, self.phase(), address - self.CS1):
                self.raise_card_fault()
                return
        if bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f' and self.read16(pc + 2) == 0xa085:
            self.guard_starts += 1
        super().hook(uc, pc, size, context)

    def bus(self, uc, access, address, size, value, context):
        assert self.read32(self.CARD_EXCEPTION_LIST) not in (0, self.OUTER), 'MMIO without guard'
        super().bus(uc, access, address, size, value, context)
        if self.after_doorbell and access == UC_MEM_WRITE and address == self.CS1 + 0x30000:
            self.after_doorbell = False
            self.raise_next = True


@unittest.skipUnless(f.HAVE_UNICORN and HAS_NETWORK, 'requires compiled Palm artifacts')
class CardRecoveryTests(unittest.TestCase):
    def machine(self):
        m = CardFaultMachine()
        self.assertEqual(m.open(), 0)
        return m

    def begin(self, m):
        err, token, result = m.begin()
        self.assertEqual((err, result), (0, 0))
        return token

    def released(self, m):
        self.assertEqual(m.read32(m.CARD_EXCEPTION_LIST), m.OUTER)
        self.assertEqual(m.read16(m.globals + m.symbols['nl_busy']), 0)
        self.assertEqual(m.read32(m.globals + m.symbols['access_address']), 0)
        for symbol in ('_fn_transport_ctx', '_fn_parse_ctx'):
            address = m.globals + m.symbols[symbol]
            self.assertEqual(bytes(m.uc.mem_read(address, 8)), b'\0' * 8)

    def file_read(self, m, token, command='NioLibFileRead'):
        m.files[b'host:/App.prc'] = bytes(range(256))
        m.uc.mem_write(0x9000, struct.pack('>IH', 0x9100, 512))
        m.uc.mem_write(0x9400, b'host:/App.prc\0')
        m.uc.mem_write(0x9600, b'\xcc' * 256)
        args = struct.pack('>HIIIIIHII', 7, token, 0x9000, 0x9400,
                           0, 0x9600, 256, 0x9500, 0x9700)
        self.assertEqual(m.call(command, args), 0)
        return m.read16(0x9700)

    def test_normal_scopes_restore_outer_handler_and_are_not_per_word(self):
        m = self.machine(); token = self.begin(m)
        initial = m.guard_starts
        self.assertEqual(self.file_read(m, token), 0)
        self.assertEqual(m.guard_starts - initial, 1)
        self.assertGreater(m.mmio, 100)
        self.released(m)
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.released(m)
        self.assertEqual(m.close(), (0, 0))
        self.assertEqual(m.read32(m.CARD_EXCEPTION_LIST), m.OUTER)

    def test_discovery_fault_returns_error_clears_provisional_mapping_and_can_retry(self):
        m = self.machine()
        m.fault = ('read', 1, 0)  # MAGIC during fn_init, before Begin's probe
        err, token, result = m.begin()
        self.assertEqual((err, token, result), (0, 0, 5))
        self.released(m)
        self.assertEqual(m.read32(m.globals + m.symbols['_fn_palmos_cs1']), 0)
        self.assertEqual(m.doorbells, 0)
        self.assertEqual(m.diagnostic()[5:7], (6, 4))
        m.present = True
        token = self.begin(m)
        self.assertEqual(m.clock(token)[:2], (0, 0))
        self.assertEqual(m.end(token)[:2], (0, 0))

    def test_probe_fault_zeros_availability_and_restores_handler(self):
        m = self.machine()
        m.fault = ('read', 1, 0)
        m.uc.mem_write(0x8500, struct.pack('>6H', 12, 0xffff, 0xffff, 0xffff, 0, 0))
        self.assertEqual(m.call('NioLibProbe', struct.pack('>HII', 7, 0x8500, 0x8600)), 0)
        self.assertEqual(m.read16(0x8600), 5)
        self.assertEqual(struct.unpack('>3H', m.uc.mem_read(0x8502, 6)), (0, 0, 0))
        self.released(m)

    def test_begin_synchronization_fault_has_no_request_and_releases_owner(self):
        m = self.machine()
        # Discovery reads MAGIC, VERSION and RESP_SEQ. Fault only on the
        # subsequent begin/probe status register, after init became active.
        m.fault = ('read', 1, 4)
        self.assertEqual(m.begin(), (0, 0, 5))
        self.assertEqual(m.doorbells, 0)
        self.released(m)
        self.assertEqual(m.close(), (0, 0))

    def test_faults_in_sync_request_poll_result_reply_and_final_snapshot(self):
        for kind, phase, offset, posted in (
                ('read', 1, 4, False), ('write', 2, 0x10000, False),
                ('write', 2, 0, False), ('write', 2, 0x20000, False),
                ('write', 2, 0x30000, True), ('read', 3, 8, True),
                ('read', 4, 12, True), ('read', 5, 10, True),
                ('read', 5, 0x1000 + 20, True), ('read', 5, 4, True)):
            with self.subTest(kind=kind, phase=phase, offset=hex(offset)):
                m = self.machine(); token = self.begin(m)
                m.fault = (kind, phase, offset)
                self.assertEqual(self.file_read(m, token), 5)
                self.assertEqual(len(m.injected), 1)
                self.assertEqual(m.mmio, m.injected[0][2])
                self.assertEqual(bytes(m.uc.mem_read(0x9600, 256)), b'\xcc' * 256)
                self.released(m)
                d = m.diagnostic()
                self.assertEqual(d[2:7], (0xfe, 3, phase, 6, 4))
                self.assertEqual((d[20], d[21], d[24]), (0xfffe, 0xbeef, m.CS1 + offset))
                marker = m.preferences.get((0x4e694c31, 0x4e32))
                self.assertEqual(bool(marker and struct.unpack('>IIHH', marker[1])[2]), posted)
                self.assertEqual(m.end(token)[1], 6 if posted else 0)
                self.released(m)
                self.assertEqual(m.close(), (0, 0))
                if posted:
                    self.assertEqual(m.preferences[0x4e694c31, 0x4e32], marker)
                self.assertEqual(m.read32(m.CARD_EXCEPTION_LIST), m.OUTER)

    def test_doorbell_applied_before_fault_retains_marker_without_replay(self):
        m = self.machine(); token = self.begin(m)
        m.after_doorbell = True
        self.assertEqual(m.net_open(token)[2], 5)
        self.assertEqual((m.doorbells, len(m.requests), len(m.sessions)), (1, 1, 1))
        marker = m.preferences[0x4e694c31, 0x4e32]
        self.released(m)
        m.present = True
        # End can retire the exact reply but cannot recover an Open handle
        # whose response the app never received. Historical mutation remains.
        self.assertEqual(m.end(token)[1], 6)
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(struct.unpack('>IIHH', m.preferences[0x4e694c31, 0x4e32][1])[2], 0)
        self.assertNotEqual(marker, m.preferences[0x4e694c31, 0x4e32])
        self.released(m)

    def test_cleanup_fault_does_not_clear_pending_or_replace_first_diagnostic(self):
        m = self.machine(); token = self.begin(m)
        self.assertEqual(self.file_read(m, token), 0)
        m.preferences[0x4e694c31, 0x4e32] = (
            1, struct.pack('>IIHH', 0x4e4c5031, m.CS1, m.sequences[-1], 0))
        marker = m.preferences[0x4e694c31, 0x4e32]
        m.fault = ('read', 5, 4)
        self.assertEqual(m.end(token)[1], 6)
        self.released(m)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e32], marker)
        self.assertEqual(m.diagnostic()[6], 4)
        self.assertEqual(m.doorbells, 1)

    def test_second_cleanup_fault_preserves_first_exchange_diagnostic(self):
        m = self.machine(); token = self.begin(m)
        m.fault = ('read', 5, 0x1000 + 20)
        self.assertEqual(self.file_read(m, token), 5)
        evidence = m.preferences[0x4e694c31, 0x4e37]
        marker = m.preferences[0x4e694c31, 0x4e32]
        m.present = True
        m.fault = ('read', 5, 4)
        self.assertEqual(m.end(token)[1], 6)
        self.assertEqual(len(m.injected), 2)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e37], evidence)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e32], marker)
        self.released(m)

    def test_relocated_code_recovers_to_the_saved_pc_and_restores_registers(self):
        for base in (0x51000, 0x90000):
            with self.subTest(code_base=hex(base)):
                machine = type('RelocatedCardFaultMachine', (CardFaultMachine,), {'CODE': base})
                m = machine()
                self.assertEqual(m.open(), 0)
                token = self.begin(m)
                m.fault = ('read', 5, 0x1000 + 20)
                self.assertEqual(self.file_read(m, token), 5)
                self.released(m)
                m.present = True
                self.assertEqual(self.file_read(m, token), 0)
                self.assertEqual(m.end(token)[1], 0)
                self.assertEqual(m.close(), (0, 0))

    def test_readonly_retry_after_reinsertion_preserves_first_diagnostic(self):
        m = self.machine(); token = self.begin(m)
        m.fault = ('read', 5, 0x1000 + 20)
        self.assertEqual(self.file_read(m, token), 5)
        evidence = m.preferences[0x4e694c31, 0x4e37]
        m.present = True
        self.assertEqual(self.file_read(m, token), 0)
        self.assertEqual(m.doorbells, 2)  # explicit app retry, no hidden replay
        self.assertEqual(m.end(token)[1], 0)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e37], evidence)
        self.released(m)
