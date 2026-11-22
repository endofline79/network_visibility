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

    def test_build_heartbeat_deltas_resets_and_post(self):
        first = {
            "started_at": 1_700_000_000.0,
            "datagrams": 10,
            "rejected_datagrams": 0,
            "decoded_records": 100,
            "duplicate_records": 2,
            "invalid_records": 1,
            "sqlite_errors": 0,
            "overflow_records": 0,
            "inserted_records": 98,
            "decoder_errors": 3,
            "udp_receive_errors": 0,
            "pending_records": 4,
            "buffer_limit": 100000,
            "last_decoded": 1_700_000_050.0,
            "insert_error": False,
            "running": True,
            "stale": False,
            "exporter": "192.168.5.1",
        }
        hb1 = collector.build_heartbeat(first, previous=None, now=1_700_000_060.0)
        self.assertEqual(hb1["app_name"], "opnsense-flow-health")
        self.assertEqual(hb1["kind"], "heartbeat")
        self.assertEqual(hb1["decoded_delta"], 0)
        self.assertEqual(hb1["last_flow_age_seconds"], 10)
        self.assertEqual(hb1["uptime_seconds"], 60)

        second = {
            **first,
            "datagrams": 25,
            "decoded_records": 250,
            "invalid_records": 6,
            "decoder_errors": 5,
            "sqlite_errors": 1,
            "overflow_records": 2,
            "pending_records": 12,
        }
        hb2 = collector.build_heartbeat(second, previous=first, now=1_700_000_120.0)
        self.assertEqual(hb2["datagrams_delta"], 15)
        self.assertEqual(hb2["decoded_delta"], 150)
        self.assertEqual(hb2["invalid_delta"], 5)
        self.assertEqual(hb2["decoder_errors_delta"], 2)
        self.assertEqual(hb2["sqlite_errors_delta"], 1)
        self.assertEqual(hb2["overflow_delta"], 2)
        self.assertIn("decoded=+150", hb2["_msg"])

        reset = {**first, "decoded_records": 5, "decoder_errors": None}
        hb3 = collector.build_heartbeat(reset, previous=second, now=1_700_000_180.0)
        self.assertEqual(hb3["decoded_delta"], 0)
        self.assertEqual(hb3["decoder_errors_delta"], 0)

        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(collector.urllib.request, "urlopen", return_value=response):
            self.assertTrue(collector.post_heartbeat(hb2))
            self.assertFalse(collector.stats["heartbeat_error"])
        with patch.object(collector.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertFalse(collector.post_heartbeat(hb2))
            self.assertTrue(collector.stats["heartbeat_error"])
