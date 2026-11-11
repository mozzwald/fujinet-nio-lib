"""Compiled CS1 synchronization checks with independent register-read faults.

This models inconsistent snapshots; it does not qualify Springboard hardware.
"""
from collections import deque
import struct
import re
import unittest
import test_palmos_shared as foundation
from test_palmos_shared_network import NetworkMachine, HAS_NETWORK
from test_palmos_shared_services import ServiceMachine
try:
    from unicorn import UC_MEM_READ, UC_MEM_WRITE
except ImportError:
    pass


class SnapshotMachine(NetworkMachine):
    def __init__(self):
        self.snapshots = deque()
        self.snapshot_reads = 0
        self.before_post = False
        self.unchecked_sequence_read = False
        super().__init__()

    def inject(self, *snapshots):
        for status, ack, response, last in snapshots:
            self.snapshots.extend(((4, status), (6, ack), (8, response), (4, last)))
        self.snapshot_reads = 0
        self.before_post = True

    def bus(self, uc, access, address, size, value, context):
        super().bus(uc, access, address, size, value, context)
        off = address - self.CS1
        if access == UC_MEM_WRITE and off == 0x10000:
            assert not self.snapshots, 'request posted before the expected snapshots'
            self.before_post = False
        elif access == UC_MEM_READ and self.before_post:
            if self.snapshots:
                expected, replacement = self.snapshots.popleft()
                assert off == expected, 'read outside the synchronization snapshot'
                self.snapshot_reads += 1
                uc.mem_write(address, struct.pack('>H', replacement))
            elif off == 8:
                self.unchecked_sequence_read = True
                # Expose a standalone read after the validated snapshot.
                uc.mem_write(address, struct.pack('>H', 99))


@unittest.skipUnless(foundation.HAVE_UNICORN and HAS_NETWORK,
                     'requires shared-library artifacts and unicorn==2.1.4')
class CS1SnapshotTests(unittest.TestCase):
    def machine(self):
        m = SnapshotMachine()
        self.assertEqual(m.open(), 0)
        m.regs[6] = m.regs[8] = 7
        err, token, result = m.begin()
        self.assertEqual((err, result), (0, 0))
        return m, token

    def success(self, *snapshots):
        m, token = self.machine()
        m.inject(*snapshots)
        self.assertEqual(m.clock(token)[:2], (0, 0))
        self.assertFalse(m.snapshots)
        self.assertFalse(m.unchecked_sequence_read)
        self.assertEqual(m.sequences, [8])
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))
        return m

    def test_next_sequence_uses_two_checked_snapshots_without_another_read(self):
        self.success((1, 7, 7, 1), (1, 7, 7, 1))

    def test_transient_ack_mismatch_is_reread_without_replaying_a_request(self):
        m = self.success((1, 8, 7, 1), (1, 7, 7, 1), (1, 7, 7, 1))
        self.assertEqual(m.snapshot_reads, 12)
        self.assertEqual(m.doorbells, 1)

    def test_busy_snapshot_requires_two_new_idle_snapshots(self):
        self.success((1, 7, 7, 3), (1, 7, 7, 1), (1, 7, 7, 1))

    def test_bad_snapshot_breaks_the_consecutive_match(self):
        self.success((1, 7, 7, 1), (1, 8, 7, 1),
                     (1, 7, 7, 1), (1, 7, 7, 1))

    def test_changing_agreed_sequences_never_seed_a_request(self):
        m, token = self.machine()
        m.inject((1, 7, 7, 1), (1, 8, 8, 1), (1, 7, 7, 1), (1, 8, 8, 1))
        before = dict(m.preferences)
        self.assertNotEqual(m.clock(token)[1], 0)
        self.assertEqual(m.snapshot_reads, 16)
        self.assertFalse(m.snapshots)
        self.assertEqual(m.doorbells, 0)
        self.assertEqual({k: v for k, v in m.preferences.items()
                          if k != (0x4e694c31, 0x4e37)}, before)

    def test_persistent_mismatch_is_bounded_even_when_ticks_do_not_advance(self):
        m, token = self.machine()
        m.inject(*[(1, 8, 7, 1)] * 4)
        before = dict(m.preferences)
        self.assertNotEqual(m.clock(token)[1], 0)
        self.assertEqual(m.snapshot_reads, 16)
        self.assertEqual(m.doorbells, 0)
        self.assertEqual({k: v for k, v in m.preferences.items()
                          if k != (0x4e694c31, 0x4e37)}, before)
        self.assertEqual(m.now, 0)
        diagnostic = struct.unpack('>22H3I', m.preferences[0x4e694c31, 0x4e37][1])
        self.assertEqual(diagnostic[4:7], (1, 8, 0))
        self.assertEqual(diagnostic[8:12], (1, 8, 7, 1))

    def test_out_of_range_sequences_are_not_truncated_to_eight_bits(self):
        m, token = self.machine()
        m.inject(*[(1, 0x107, 0x107, 1)] * 4)
        self.assertNotEqual(m.clock(token)[1], 0)
        self.assertEqual(m.snapshot_reads, 16)
        self.assertEqual(m.doorbells, 0)

    def test_stable_wrong_completion_does_not_clear_pending_marker(self):
        m, token = self.machine()
        marker = (1, struct.pack('>IIHH', 0x4e4c5031, m.CS1, 6, 0))
        m.preferences[0x4e694c31, 0x4e32] = marker
        m.inject(*[(1, 7, 7, 1)] * 4)
        self.assertNotEqual(m.clock(token)[1], 0)
        self.assertEqual(m.snapshot_reads, 16)
        self.assertEqual(m.doorbells, 0)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e32], marker)

    def test_pending_completion_can_settle_without_being_replayed(self):
        m, token = self.machine()
        m.preferences[0x4e694c31, 0x4e32] = (
            1, struct.pack('>IIHH', 0x4e4c5031, m.CS1, 7, 0))
        m.inject((1, 8, 7, 1), (1, 7, 7, 1), (1, 7, 7, 1),
                 (1, 7, 7, 1), (1, 7, 7, 1))
        self.assertEqual(m.clock(token)[:2], (0, 0))
        self.assertFalse(m.unchecked_sequence_read)
        self.assertEqual(m.sequences, [8])
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))


class HeldReplyMachine(NetworkMachine):
    def __init__(self):
        self.length_reads = 0
        self.glitch_length_read = 0
        self.bad_packet = False
        self.repair_packet = False
        self.good_packet = None
        super().__init__()

    def publish(self, seq, packet, result=0):
        self.length_reads = 0
        self.good_packet = (seq, bytes(packet), result)
        if self.bad_packet and packet:
            # Keep the CS1 word checksum valid but break the FujiBus checksum.
            # The complete validation loop must re-read the held response.
            packet = bytearray(packet)
            packet[4] ^= 1
            packet = bytes(packet)
        super().publish(seq, packet, result)

    def bus(self, uc, access, address, size, value, context):
        if access == UC_MEM_READ and address == self.CS1 + 10:
            self.length_reads += 1
            if self.repair_packet and self.length_reads == 2:
                NetworkMachine.publish(self, *self.good_packet)
        super().bus(uc, access, address, size, value, context)
        if (access == UC_MEM_READ and address == self.CS1 + 10 and
                self.length_reads == self.glitch_length_read):
            # High-bit corruption is immediately out of range in read_reply;
            # a late unprotected read would instead reject a valid packet.
            uc.mem_write(address, struct.pack('>H', self.regs[10] ^ 0x8000))


@unittest.skipUnless(foundation.HAVE_UNICORN and HAS_NETWORK,
                     'requires shared-library artifacts and unicorn==2.1.4')
class CS1HeldReplyTests(unittest.TestCase):
    def machine(self, kind=HeldReplyMachine):
        m = kind()
        self.assertEqual(m.open(), 0)
        err, token, result = m.begin()
        self.assertEqual((err, result), (0, 0))
        return m, token

    def test_valid_reply_has_no_unprotected_second_length_read(self):
        m, token = self.machine()
        m.glitch_length_read = 2
        self.assertEqual(m.clock(token)[:2], (0, 0))
        self.assertEqual(m.length_reads, 1)
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))

    def test_corrupt_length_retries_the_held_reply_without_command_replay(self):
        m, token = self.machine()
        m.glitch_length_read = 1
        self.assertEqual(m.clock(token)[:2], (0, 0))
        self.assertEqual(m.length_reads, 2)
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))

    def test_packet_checksum_failure_retries_same_reply_and_cleanup_is_clean(self):
        m, token = self.machine()
        m.bad_packet = m.repair_packet = True
        self.assertEqual(m.clock(token)[:2], (0, 0))
        self.assertEqual(m.length_reads, 2)
        self.assertEqual((m.doorbells, len(m.requests)), (1, 1))
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.close(), (0, 0))

    def test_persistent_readonly_bad_packet_reports_error_without_cleanup_uncertainty(self):
        m, token = self.machine()
        m.bad_packet = True
        self.assertEqual(m.clock(token)[:2], (0, 5))
        self.assertEqual(m.length_reads, 4)
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(m.end(token)[1:], (0, (12, 0, 0, 0, 0, 0)))
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(m.close(), (0, 0))

    def test_end_client_retires_exact_completed_sequence_without_another_request(self):
        m, token = self.machine(SnapshotMachine)
        self.assertEqual(m.clock(token)[:2], (0, 0))
        seq = m.sequences[-1]
        # Model a failed final completion snapshot after a valid reply.
        m.preferences[0x4e694c31, 0x4e32] = (
            1, struct.pack('>IIHH', 0x4e4c5031, m.CS1, seq, 0))
        m.inject((1, seq+1, seq, 1), (1, seq, seq, 1), (1, seq, seq, 1))
        self.assertEqual(m.end(token), (0, 0, (12, 0, 0, 0, 0, 0)))
        self.assertEqual(m.doorbells, 1)
        self.assertFalse(m.snapshots)
        self.assertEqual(struct.unpack('>IIHH', m.preferences[0x4e694c31, 0x4e32][1])[2], 0)
        self.assertEqual(m.close(), (0, 0))

    def test_end_client_leaves_a_different_pending_sequence_untouched(self):
        m, token = self.machine()
        self.assertEqual(m.clock(token)[:2], (0, 0))
        marker = (1, struct.pack('>IIHH', 0x4e4c5031, m.CS1, m.sequences[-1]+1, 0))
        m.preferences[0x4e694c31, 0x4e32] = marker
        self.assertEqual(m.end(token)[1:], (6, (12, 0, 0, 0, 1, 0)))
        self.assertEqual(m.preferences[0x4e694c31, 0x4e32], marker)
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(m.close(), (0, 0))

    def test_late_completion_does_not_erase_an_earlier_unknown_command_outcome(self):
        m, token = self.machine()
        m.silent = True
        self.assertEqual(m.net_open(token)[2], 6)
        m.silent = False
        m.publish(m.pending_seq, m.execute(m.pending_request))
        self.assertEqual(m.end(token)[1:], (6, (12, 0, 0, 0, 1, 0)))
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(struct.unpack('>IIHH', m.preferences[0x4e694c31, 0x4e32][1])[2], 0)
        self.assertEqual(m.close(), (0, 0))


class ResultMachine(NetworkMachine):
    def __init__(self):
        self.result_faults = deque()
        self.result_reads = 0
        super().__init__()

    def bus(self, uc, access, address, size, value, context):
        super().bus(uc, access, address, size, value, context)
        if access == UC_MEM_READ and address == self.CS1 + 12:
            self.result_reads += 1
            if self.result_faults:
                uc.mem_write(address, struct.pack('>H', self.result_faults.popleft()))


class GuardMachine(ServiceMachine):
    def __init__(self):
        self.failure = None
        self.words = 0
        super().__init__()

    def bus(self, uc, access, address, size, value, context):
        super().bus(uc, access, address, size, value, context)
        if access == UC_MEM_READ and address >= self.CS1 + 0x1000:
            self.words += 1
            if self.words == 10:
                if self.failure == 'deadline': self.now = 3500
                elif self.failure == 'mapping': self.card_size += 2
                elif self.failure == 'removed': self.present = False

    def publish(self, *args):
        super().publish(*args)
        if self.failure == 'checksum': self.regs[14] ^= 1
        elif self.failure == 'length': self.regs[10] = 0x8000


class DiagnosticViewerMachine(ResultMachine):
    def __init__(self):
        self.dialogs = []
        self.form = 1002
        self.erases, self.text_draws = [], []
        super().__init__()

    def string(self, address):
        value = bytearray()
        while self.uc.mem_read(address + len(value), 1)[0]:
            value += self.uc.mem_read(address + len(value), 1)
        return value.decode()

    def hook(self, uc, pc, size, context):
        from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_PC
        if bytes(uc.mem_read(pc, 2)) != b'\x4e\x4f':
            return super().hook(uc, pc, size, context)
        trap, sp = self.read16(pc + 2), uc.reg_read(UC_M68K_REG_A7)
        if trap == 0xa175: result = self.form
        elif trap == 0xa219:
            self.erases.append(struct.unpack('>4h', uc.mem_read(self.read32(sp), 8)))
            result = 0
        elif trap == 0xa220:
            self.text_draws.append((self.string(self.read32(sp)), self.read16(sp + 6), self.read16(sp + 8)))
            result = 0
        elif trap == 0xa194:  # FrmCustomAlert: record all three displayed strings
            self.dialogs.append(tuple(self.string(self.read32(sp + at)) for at in (2, 6, 10)))
            result = 0
        elif trap == 0xa2de:  # StrPrintF: Palm's 16-bit int / 32-bit long varargs
            offset = sp + 8
            def substitute(match):
                nonlocal offset
                spec = match[0]
                if spec.endswith('s'):
                    value = self.string(self.read32(offset)); offset += 4
                    return value
                width = 4 if 'l' in spec else 2
                value = self.read32(offset) if width == 4 else self.read16(offset)
                offset += width
                return spec.replace('l', '') % value
            output = re.sub(r'%0?\d*l?[suX]', substitute,
                            self.string(self.read32(sp + 4))).encode()
            uc.mem_write(self.read32(sp), output + b'\0')
            result = len(output)
        else:
            return super().hook(uc, pc, size, context)
        uc.reg_write(UC_M68K_REG_D0, result)
        uc.reg_write(UC_M68K_REG_PC, pc + 4)


@unittest.skipUnless(foundation.HAVE_UNICORN and HAS_NETWORK,
                     'requires shared-library artifacts and unicorn==2.1.4')
class CS1ResultTests(unittest.TestCase):
    def machine(self, kind=ResultMachine):
        m = kind()
        self.assertEqual(m.open(), 0)
        err, token, result = m.begin()
        self.assertEqual((err, result), (0, 0))
        return m, token

    def test_single_bad_result_cannot_replay_open_or_report_false_timeout(self):
        for bad in (2, 4, 8, 9, 0xffff):
            with self.subTest(result=bad):
                m, token = self.machine()
                m.result_faults.append(bad)
                self.assertEqual(m.net_open(token), (0, 256, 0))
                self.assertEqual((m.doorbells, len(m.requests), m.result_reads), (1, 1, 3))
                self.assertEqual(m.end(token)[:2], (0, 0))
                self.assertEqual(m.sessions, {})

    def test_rejection_cannot_authorize_replay_while_success_payload_is_held(self):
        m, token = self.machine()
        m.result_faults.extend([4] * 4)
        self.assertEqual(m.net_open(token)[2], 5)
        self.assertEqual((m.doorbells, len(m.requests), m.result_reads), (1, 1, 4))
        self.assertEqual(m.end(token)[1], 6)

    def test_alternating_results_are_bounded_without_replay_or_advancing_ticks(self):
        m, token = self.machine()
        m.result_faults.extend([0, 4, 0, 4])
        self.assertEqual(m.clock(token)[1], 5)
        self.assertEqual((m.doorbells, m.result_reads, m.now), (1, 4, 0))
        self.assertEqual(m.end(token)[1], 0)

    def test_actual_request_rejection_can_still_be_retried(self):
        m, token = self.machine()
        m.bad_check = 1
        self.assertEqual(m.net_open(token), (0, 256, 0))
        self.assertEqual((m.doorbells, len(m.requests), m.result_reads), (2, 1, 4))
        self.assertEqual(m.end(token)[:2], (0, 0))
        self.assertEqual(m.sessions, {})

    def test_stable_bridge_timeout_is_distinct_from_local_guard_failure(self):
        m, token = self.machine()
        # Diagnostics must not overwrite the serial/USB ownership tombstones.
        m.preferences[0x4e694c31, 0x4e35] = (1, b'\0\0')
        m.preferences[0x4e694c31, 0x4e36] = (1, b'\0\0')
        m.forced_result = 2
        self.assertEqual(m.clock(token)[1], 6)
        d = self.diagnostic(m)
        self.assertEqual((d[4], d[5], d[6], d[7], d[20]), (4, 7, 0, 2, 2))
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(m.preferences[0x4e694c31, 0x4e35], (1, b'\0\0'))
        self.assertEqual(m.preferences[0x4e694c31, 0x4e36], (1, b'\0\0'))

    def test_viewer_reads_evidence_without_starting_transport_or_changing_ownership(self):
        m, token = self.machine(DiagnosticViewerMachine)
        m.result_faults.extend([4] * 4)
        self.assertEqual(m.clock(token)[1], 5)
        self.assertEqual(m.end(token)[1], 0)
        before = (m.mmio, dict(m.preferences), dict(m.features))
        m.call('show_cs1_diagnostic', b'', app=True, a5=m.app_a5)
        self.assertEqual((m.mmio, m.preferences, m.features), before)
        self.assertEqual(len(m.dialogs), 2)
        self.assertIn('Phase 4 Reason 4 Guard 0', m.dialogs[0][0])
        self.assertIn('Outcome FFFE Result 0004', m.dialogs[0][1])
        self.assertIn('Want seq 1 Ack 1', m.dialogs[1][0])

    def test_viewer_rejects_missing_or_incompatible_record_without_bus_access(self):
        for data in (None, (2, b'\0' * 56), (1, b'\0' * 12), (1, b'\0' * 56)):
            m = DiagnosticViewerMachine()
            if data: m.preferences[0x4e694c31, 0x4e37] = data
            m.call('show_cs1_diagnostic', b'', app=True, a5=m.app_a5)
            self.assertEqual(m.mmio, 0)
            self.assertEqual(m.dialogs, [('No compatible CS1 failure record.', '', '')])

    def test_results_redraw_never_erases_form_controls(self):
        resources = (foundation.ROOT / 'examples/palmos-shared/test.rcp').read_text()
        for form in (1000, 1002, 1010):
            with self.subTest(form=form):
                m = DiagnosticViewerMachine(); m.form = form
                # The foundation page normally receives this string from run_tests.
                m.uc.mem_write(0x9000, b'Ready\0')
                m.uc.mem_write(m.app_data + m.app_symbols['stage'], struct.pack('>I', 0x9000))
                m.call('draw_results', b'', app=True, a5=m.app_a5)
                section = re.search(r'FORM ID %d\b.*?\nEND' % form, resources, re.S)[0]
                controls = re.findall(r'BUTTON .*? AT \((\d+) (\d+) (\d+) (\d+)\)', section)
                for x, y, width, height in m.erases:
                    for bx, by, bw, bh in controls:
                        # Include the one-pixel button frame, not just its label.
                        bx, by, bw, bh = map(int, (bx, by, bw, bh))
                        self.assertFalse(x < bx + bw + 1 and x + width > bx - 1 and
                                         y < by + bh + 1 and y + height > by - 1)
                self.assertEqual(m.mmio, 0)

    @staticmethod
    def diagnostic(m):
        version, data = m.preferences[0x4e694c31, 0x4e37]
        assert version == 1 and len(data) == 56
        return struct.unpack('>22H3I', data)

    def test_readonly_reply_failures_keep_diagnostics_and_clear_settled_cleanup(self):
        for failure, outcome, reason, guard in (
                ('checksum', 5, 2, 0), ('length', 5, 1, 0),
                ('deadline', 6, 6, 1), ('mapping', 5, 6, 2), ('removed', 5, 6, 2)):
            with self.subTest(failure=failure):
                m, token = self.machine(GuardMachine)
                m.files[b'host:/App.prc'] = bytes(range(256)) * 4
                m.uc.mem_write(0x9000, struct.pack('>IH', 0x9100, 512))
                m.uc.mem_write(0x9400, b'host:/App.prc\0')
                m.uc.mem_write(0x9600, b'\xcc' * 256)
                args = struct.pack('>HIIIIIHII', 7, token, 0x9000, 0x9400,
                                   0, 0x9600, 256, 0x9500, 0x9700)
                m.failure = failure
                m.call('NioLibFileRead', args)
                self.assertEqual(m.read16(0x9700), outcome)
                self.assertEqual(bytes(m.uc.mem_read(0x9600, 256)), b'\xcc' * 256)
                d = self.diagnostic(m)
                self.assertEqual(d[2:7], (0xfe, 3, 5, reason, guard))
                if failure == 'checksum':
                    self.assertEqual(d[14], 273)
                    self.assertNotEqual(d[15], d[16])
                    self.assertEqual(d[17], 4)
                if guard:
                    self.assertEqual(m.words, 10)  # no MMIO after guard failure
                    self.assertNotEqual(d[24], 0)
                    self.assertEqual(d[21], {'deadline': 0, 'mapping': 7, 'removed': 3}[failure])
                evidence = m.preferences[0x4e694c31, 0x4e37]
                m.failure = None; m.card_size = 0x1000000; m.present = True
                m.call('NioLibFileRead', args)
                self.assertEqual(m.read16(0x9700), 0)
                self.assertEqual(m.end(token)[1], 0)
                self.assertEqual(m.preferences[0x4e694c31, 0x4e37], evidence)

    def file_args(self, m, token):
        m.files[b'host:/App.prc'] = b'PRC'
        m.uc.mem_write(0x9000, struct.pack('>IH', 0x9100, 512))
        m.uc.mem_write(0x9400, b'host:/App.prc\0')
        m.uc.mem_write(0x9600, b'NEW')
        return struct.pack('>HIIIIIHII', 7, token, 0x9000, 0x9400,
                           0, 0x9600, 3, 0x9500, 0x9700)

    def test_failed_readonly_query_without_retry_still_has_clean_settled_cleanup(self):
        for name in ('NioLibFileRead', 'NioLibFileStat', 'NioLibFileListPages'):
            with self.subTest(trap=name):
                m, token = self.machine(GuardMachine)
                args = self.file_args(m, token)
                if name == 'NioLibFileStat':
                    args = struct.pack('>HIIIII', 7, token, 0x9000, 0x9400, 0x9500, 0x9700)
                elif name == 'NioLibFileListPages':
                    m.uc.mem_write(0x9a00, struct.pack('>HBBHBBI', 0, 1, 0, 256, 1, 64, 0))
                    args = struct.pack('>HIIIIII', 7, token, 0x9000, 0x9400, 0x9a00, 0x9500, 0x9700)
                m.failure = 'checksum'
                m.call(name, args)
                self.assertEqual(m.read16(0x9700), 5)
                self.assertEqual(m.end(token), (0, 0, (12, 0, 0, 0, 0, 0)))
                self.assertEqual(m.doorbells, 1)

    def test_readonly_timeout_retains_pending_until_exact_completion_without_replay(self):
        for late_reply in (False, True):
            with self.subTest(late_reply=late_reply):
                m, token = self.machine(GuardMachine)
                args = self.file_args(m, token); m.silent = True
                m.call('NioLibFileRead', args)
                self.assertEqual(m.read16(0x9700), 6)
                marker = m.preferences[0x4e694c31, 0x4e32]
                if late_reply:
                    m.silent = False
                    m.publish(m.pending_seq, m.execute(m.pending_request))
                self.assertEqual(m.end(token)[1], 0 if late_reply else 6)
                self.assertEqual(m.doorbells, 1)
                if not late_reply:
                    self.assertEqual(m.preferences[0x4e694c31, 0x4e32], marker)

    def test_successful_read_does_not_erase_an_ambiguous_write_or_raw_call(self):
        for name in ('NioLibFileWrite', 'NioLibRawCall'):
            with self.subTest(trap=name):
                m, token = self.machine(GuardMachine)
                args = self.file_args(m, token); m.failure = 'checksum'
                if name == 'NioLibRawCall':
                    payload = b'\x01' + struct.pack('<H', 13) + b'host:/App.prc' + struct.pack('<IH', 0, 3)
                    m.uc.mem_write(0x9a00, payload)
                    raw_args = struct.pack('>HIHHIHIHII', 7, token, 0xfe, 3,
                        0x9a00, len(payload), 0x9b00, 512, 0x9d00, 0x9700)
                    m.call(name, raw_args)
                else:
                    m.call(name, args)
                    self.assertEqual(m.files[b'host:/App.prc'], b'NEW')
                self.assertEqual(m.read16(0x9700), 5)
                m.failure = None
                m.call('NioLibFileRead', args)
                self.assertEqual(m.read16(0x9700), 0)
                self.assertEqual(m.end(token), (0, 6, (12, 0, 0, 0, 1, 0)))
                self.assertEqual(m.doorbells, 2)


if __name__ == '__main__':
    unittest.main()
