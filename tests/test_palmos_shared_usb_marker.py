"""Execute the Palm USB readiness certificate and unchanged recovery markers.
Only OS/driver traps and the peer are modeled; library code is not replaced.
"""
import unittest
import test_palmos_shared as f
from test_palmos_shared_usb import USBMachine
from test_palmos_shared_transports import config
if f.HAVE_UNICORN:
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0


class MarkerMachine(USBMachine):
    def __init__(self):
        self.marker_calls = []
        self.last_marker_write = None
        self.fail_clear_read = False
        self.fail_pending_read = False
        self.sends_verified = 0
        super().__init__()

    def hook(self, uc, pc, size, context):
        pref = False
        trap = self.read16(pc + 2) if bytes(uc.mem_read(pc, 2)) == b'\x4e\x4f' else 0
        sp = uc.reg_read(UC_M68K_REG_A7)
        if trap in (0xa2d3, 0xa2d4) and self.read16(sp + 4) == 0x4e36:
            pref = True
            if trap == 0xa2d4:
                value = self.read16(self.read32(sp + 8))
                self.last_marker_write = value
                self.marker_calls.append(('write', value))
                assert self.read16(self.globals + self.symbols['usb_marker_clear']) == 0
        super().hook(uc, pc, size, context)
        if pref and trap == 0xa2d3:
            self.marker_calls.append(('read', self.preferences.get((0x4e694c31, 0x4e36))))
            if self.fail_clear_read and self.last_marker_write == 0:
                self.fail_clear_read = False
                uc.reg_write(UC_M68K_REG_D0, 99)
            elif self.fail_pending_read and self.last_marker_write == 1:
                self.fail_pending_read = False
                uc.reg_write(UC_M68K_REG_D0, 99)

    def usb_call(self, trap, sp):
        if trap == 0xa817:
            assert self.preferences[0x4e694c31, 0x4e36] == (1, b'\0\1')
            assert self.marker_calls[-1] == ('read', (1, b'\0\1'))
            assert self.read16(self.globals + self.symbols['usb_marker_clear']) == 0
            self.sends_verified += 1
        return super().usb_call(trap, sp)


@unittest.skipUnless(f.HAVE_UNICORN and (f.OUT / 'usb.o').exists(), 'requires compiled Palm USB image')
class USBMarkerTests(unittest.TestCase):
    def machine(self):
        m = MarkerMachine()
        if 'usb_marker_clear' not in m.symbols:
            self.skipTest('requires USB readiness certificate build')
        self.assertEqual(m.open(), 0)
        self.assertEqual(m.set_config(config(3)), 0)
        err, token, result = m.begin()
        self.assertEqual((err, result), (0, 0))
        return m, token

    def ready(self, m):
        return m.call('nl_usb_ready', b'', a4=m.globals) & 0xffff

    def test_ready_reuses_verified_clear_but_each_send_still_persists_and_verifies(self):
        m, token = self.machine()
        m.marker_calls.clear()
        for _ in range(3): self.assertEqual(self.ready(m), 1)
        self.assertEqual(m.marker_calls, [])
        self.assertEqual(m.clock(token)[:2], (0, 0))
        # Clock's typed read-only wrapper does not add an uncertainty read.
        self.assertEqual(m.marker_calls, [('write', 1), ('read', (1, b'\0\1')),
                                         ('write', 0), ('read', (1, b'\0\0'))])
        calls = list(m.marker_calls)
        for _ in range(3): self.assertEqual(self.ready(m), 1)
        self.assertEqual(m.marker_calls, calls)
        self.assertGreater(m.sends_verified, 0)
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))

    def test_failed_pending_write_invalidates_certificate_without_sending(self):
        m, token = self.machine()
        self.assertEqual(self.ready(m), 1)
        m.pref_write_failure = True
        self.assertNotEqual(m.clock(token)[1], 0)
        self.assertEqual(m.sends_verified, 0)
        self.assertEqual(len(m.requests), 0)
        self.assertEqual(m.read16(m.globals + m.symbols['usb_marker_clear']), 0)
        # No bytes were sent. Preserve baseline's ability to recheck the actual
        # clear preference after a pre-send persistence failure.
        before = len(m.marker_calls)
        self.assertEqual(self.ready(m), 1)
        self.assertEqual(len(m.marker_calls), before + 1)
        m.pref_write_failure = False
        self.assertEqual(m.clock(token)[:2], (0, 0))
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))

    def test_failed_pending_verification_never_sends_and_retains_recovery_marker(self):
        m, token = self.machine()
        m.fail_pending_read = True
        self.assertNotEqual(m.clock(token)[1], 0)
        self.assertEqual(m.sends_verified, 0)
        self.assertEqual(len(m.requests), 0)
        self.assertEqual(self.ready(m), 0)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e36], (1, b'\0\1'))
        self.assertEqual(m.end(token)[1], 6)
        self.assertEqual(m.close(), (0, 0))

    def test_failed_clear_verification_retains_dirty_marker_and_blocks_reopen(self):
        m, token = self.machine()
        m.fail_clear_read = True
        self.assertNotEqual(m.clock(token)[1], 0)
        self.assertEqual(self.ready(m), 0)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e36], (1, b'\0\1'))
        self.assertEqual(m.end(token)[1], 6)
        self.assertEqual(m.close(), (0, 0))
        self.assertEqual(m.open(), 0)
        before = len(m.requests)
        self.assertNotEqual(m.begin()[2], 0)
        self.assertEqual(len(m.requests), before)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e36], (1, b'\0\1'))
        self.assertEqual(m.close(), (0, 0))

    def test_close_discards_certificate_and_reopen_checks_persistent_state(self):
        for version, data in ((1, b'\0\1'), (99, b'bad'), (1, b'\0')):
            with self.subTest(version=version, data=data):
                m, token = self.machine()
                self.assertEqual(m.clock(token)[:2], (0, 0))
                self.assertEqual(m.end(token)[:2], (0, 0))
                self.assertEqual(m.read16(m.globals + m.symbols['usb_marker_clear']), 0)
                m.preferences[0x4e694c31, 0x4e36] = version, data
                before = len(m.requests)
                self.assertNotEqual(m.begin()[2], 0)
                self.assertEqual(len(m.requests), before)
                self.assertEqual(m.close(), (0, 0))

    def test_status_still_reads_actual_pending_state_and_reset_is_busy_while_owned(self):
        m, token = self.machine()
        self.assertEqual(self.ready(m), 1)
        # Applications must not edit private markers. Even injected corruption
        # remains visible to explicit status/pending inspection (not cached).
        m.preferences[0x4e694c31, 0x4e36] = 99, b'bad'
        self.assertTrue(m.status()[1][3] & 8)
        self.assertEqual(self.ready(m), 0)
        self.assertEqual(m.call('nl_usb_reset', b'', a4=m.globals), 0x8006)
        self.assertNotEqual(m.end(token)[1], 0)
        self.assertEqual(m.close(), (0, 0))
