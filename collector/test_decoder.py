"""Regression for FreeBSD's IN counters followed by zero OUT counters."""
import json
import selectors
import shutil
import socket
import struct
import subprocess
import time
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('goflow2'), 'decoder integration runs in Docker build')
class DecoderTests(unittest.TestCase):
    def test_freebsd_counter_mapping(self):
        proc = subprocess.Popen(['goflow2', '-listen', 'netflow://127.0.0.1:12055',
            '-addr', '127.0.0.1:18080', '-mapping', str(Path(__file__).with_name('mapping.yaml')),
            '-loglevel', 'error'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        try:
            fields = [(8,4),(12,4),(2,4),(1,4),(24,4),(23,4),(4,1)]
            template = struct.pack('!HH',256,len(fields)) + b''.join(struct.pack('!HH',*f) for f in fields)
            template = struct.pack('!HH',0,len(template)+4)+template
            record = socket.inet_aton('192.168.5.2')+socket.inet_aton('10.10.20.50')+struct.pack('!IIIIB',7,4096,0,0,6)
            data = struct.pack('!HH',256,len(record)+4)+record
            packet = struct.pack('!HHIIII',9,2,1000,int(time.time()),1,0)+template+data
            for _ in range(40):
                udp.sendto(packet,('127.0.0.1',12055))
                if selector.select(.1):
                    output = json.loads(proc.stdout.readline())
                    self.assertEqual(output['opnsense_bytes'],4096)
                    self.assertEqual(output['opnsense_packets'],7)
                    self.assertEqual(output['src_addr'],'192.168.5.2')
                    break
            else:
                self.fail('decoder did not emit synthetic record')
        finally:
            udp.close()
            selector.close()
            proc.terminate()
            proc.wait(timeout=5)
            proc.stdout.close()
