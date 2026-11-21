import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import collector


def record():
    return dict(type="NETFLOW_V9", sampler_address="127.0.0.1", src_addr="192.168.5.2",
                dst_addr="10.10.20.50", opnsense_bytes=1500, opnsense_packets=1, src_port=1234, dst_port=443,
                proto="TCP", time_flow_end_ns=1800000000000000000,
                time_received_ns=1800000001000000000)


class Tests(unittest.TestCase):
    def test_failed_insert_keeps_durable_batch_then_success_drains(self):
        with tempfile.TemporaryDirectory() as folder:
            db = collector.database(Path(folder) / 'pending.sqlite3')
            collector.enqueue(db, collector.normalize(record()))
            with patch.object(collector, 'STATE', Path(folder)), patch.object(collector, 'stop') as stopped:
                stopped.is_set.side_effect = [False, True]
                with patch.object(collector.urllib.request, 'urlopen', side_effect=OSError('offline')):
                    collector.writer()
                self.assertEqual(db.execute('SELECT count(*) FROM pending').fetchone()[0], 1)
                self.assertTrue(collector.stats['insert_error'])
                stopped.is_set.side_effect = [False, True]
                response = MagicMock()
                response.__enter__.return_value.status = 200
                with patch.object(collector.urllib.request, 'urlopen', return_value=response):
                    collector.writer()
                self.assertEqual(db.execute('SELECT count(*) FROM pending').fetchone()[0], 0)
                self.assertFalse(collector.stats['insert_error'])
            db.close()

    def test_normalize_and_stable_receipt_id(self):
        raw = record()
        event = collector.normalize(raw)
        self.assertEqual(event["bytes"], 1500)
        self.assertEqual(event["sampling_rate"], 1)
        raw["time_received_ns"] += 1000000000
        self.assertEqual(event["event_id"], collector.normalize(raw)["event_id"])

    def test_reject_invalid_source_sampling_counters_and_time(self):
        for field, value in [("type", "SFLOW_5"), ("sampler_address", "192.168.5.3"),
                             ("sampling_rate", 10), ("opnsense_bytes", -1), ("opnsense_packets", 0), ("src_addr", "bad"),
                             ("src_port", 65536), ("time_flow_end_ns", 0)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                collector.normalize({**record(), field: value})

    def test_durable_deduplicated_bounded_spool(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pending.sqlite3"
            db = collector.database(path)
            event = collector.normalize(record())
            self.assertTrue(collector.enqueue(db, event))
            self.assertTrue(collector.enqueue(db, event))
            self.assertEqual(db.execute("SELECT count(*) FROM pending").fetchone()[0], 1)
            with patch.object(collector, "MAX_PENDING", 1):
                self.assertFalse(collector.enqueue(db, event))
            db.close()
            db = collector.database(path)
            self.assertEqual(db.execute("SELECT id FROM pending").fetchone()[0], event["event_id"])
            db.close()

    def test_enqueue_batch_tracks_accepted_duplicates_and_overflow(self):
        with tempfile.TemporaryDirectory() as folder:
            db = collector.database(Path(folder) / "pending.sqlite3")
            first = collector.normalize(record())
            second = collector.normalize({**record(), "src_port": 9999})
            third = collector.normalize({**record(), "src_port": 8888})
            with patch.object(collector, "MAX_PENDING", 3):
                accepted, duplicates, overflow = collector.enqueue_batch(db, [first, first, second])
                self.assertEqual((accepted, duplicates, overflow), (2, 1, 0))
                accepted, duplicates, overflow = collector.enqueue_batch(db, [third, third])
                self.assertEqual((accepted, duplicates, overflow), (1, 0, 1))
            db.close()

    def test_invalid_reasons_are_bounded_and_counted(self):
        with collector.lock:
            collector.stats["invalid_records"] = 0
            collector.stats["invalid_reasons"].clear()
        collector._record_invalid("Missing FreeBSD counters")
        collector._record_invalid("Missing FreeBSD counters")
        collector._record_invalid("Invalid exporter timestamp")
        self.assertEqual(collector.stats["invalid_records"], 3)
        self.assertEqual(collector.stats["invalid_reasons"]["Missing FreeBSD counters"], 2)
        self.assertEqual(collector.stats["invalid_reasons"]["Invalid exporter timestamp"], 1)
