"""Compiled CS1 synchronization checks with independent register-read faults.

This models inconsistent snapshots; it does not qualify Springboard hardware.
"""
from collections import deque
import struct
import unittest
import test_palmos_shared as foundation
from test_palmos_shared_network import NetworkMachine, HAS_NETWORK
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
        self.assertEqual(m.preferences, before)

    def test_persistent_mismatch_is_bounded_even_when_ticks_do_not_advance(self):
        m, token = self.machine()
        m.inject(*[(1, 8, 7, 1)] * 4)
        before = dict(m.preferences)
        self.assertNotEqual(m.clock(token)[1], 0)
        self.assertEqual(m.snapshot_reads, 16)
        self.assertEqual(m.doorbells, 0)
        self.assertEqual(m.preferences, before)
        self.assertEqual(m.now, 0)

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

    def test_persistent_bad_packet_is_bounded_and_preserves_uncertain_outcome(self):
        m, token = self.machine()
        m.bad_packet = True
        self.assertEqual(m.clock(token)[:2], (0, 5))
        self.assertEqual(m.length_reads, 4)
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(m.end(token)[1:], (6, (12, 0, 0, 0, 1, 0)))
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
        self.assertEqual(m.clock(token)[:2], (0, 6))
        m.silent = False
        m.publish(m.pending_seq, m.execute(m.pending_request))
        self.assertEqual(m.end(token)[1:], (6, (12, 0, 0, 0, 1, 0)))
        self.assertEqual(m.doorbells, 1)
        self.assertEqual(struct.unpack('>IIHH', m.preferences[0x4e694c31, 0x4e32][1])[2], 0)
        self.assertEqual(m.close(), (0, 0))


if __name__ == '__main__':
    unittest.main()
