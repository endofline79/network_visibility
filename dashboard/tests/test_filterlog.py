import ipaddress
import unittest

from backend.filterlog import parse_filterlog, public_endpoint

LOCAL = (ipaddress.ip_network("192.168.5.0/24"), ipaddress.ip_network("10.10.10.0/24"))


def record(message):
    return {"_time": "2026-09-20T02:00:00.123456789Z", "hostname": "fixture", "_msg": message}


V4 = "5,,,rule-uuid,igc1,match,pass,in,4,0x0,,64,12345,0,DF,6,tcp,60,192.168.5.50,198.51.100.20,54321,443,0,S,123456,,64240,,mss"
V6 = "7,,,rule-uuid,igc2,match,block,out,6,0x00,0x00000,64,udp,17,80,2001:db8::1,2001:db8::2,12345,53,40"


class ParsingTests(unittest.TestCase):
    def test_ipv4_tcp_and_interface_direction(self):
        e = parse_filterlog(record(V4), LOCAL)
        self.assertIsNone(e["parse_error"])
        self.assertEqual((e["source"], e["destination_port"], e["rule"]), ("192.168.5.50", 443, "rule-uuid"))
        self.assertTrue(e["source_local"])
        self.assertFalse(e["destination_local"])
        self.assertEqual(e["direction"], "in")
        self.assertEqual(e["raw"], V4)

    def test_ipv6_different_protocol_layout(self):
        e = parse_filterlog(record(V6), LOCAL)
        self.assertIsNone(e["parse_error"])
        self.assertEqual((e["protocol"], e["protocol_number"], e["source_port"], e["destination_port"]), ("UDP", 17, 12345, 53))

    def test_icmp_and_carp_have_no_ports(self):
        for suffix in ["1,icmp,84,192.168.5.50,198.51.100.20,request,999,1", "112,carp,36,192.168.5.1,224.0.0.18,1,255,1,2,0,1"]:
            e = parse_filterlog(record(",".join(V4.split(",")[:15]) + "," + suffix), LOCAL)
            self.assertIsNone(e["parse_error"])
            self.assertIsNone(e["source_port"])
            self.assertIsNone(e["destination_port"])

    def test_fragment_retains_ips_without_invented_ports(self):
        e = parse_filterlog(record(",".join(V4.split(",")[:20])), LOCAL)
        self.assertIsNone(e["parse_error"])
        self.assertIsNone(e["destination_port"])

    def test_invalid_records_remain_visible(self):
        messages = ["", "bad,csv", V4.replace(",443,", ",99999,"), V4.replace("192.168.5.50", "not-an-ip"), V6.replace("2001:db8::1", "192.168.5.50"), V4[:10] + '"bad']
        for message in messages:
            e = parse_filterlog(record(message), LOCAL)
            self.assertIsNotNone(e["parse_error"])
            self.assertEqual(e["raw"], message)

    def test_lookup_eligibility_excludes_nonpublic_and_own_public_prefix(self):
        for address in ["192.168.5.1", "10.10.10.2", "100.67.1.1", "224.0.0.18", "255.255.255.255", "127.0.0.1", "198.51.100.1", "::1", "fe80::1", "ff02::1", "2001:db8::1"]:
            self.assertFalse(public_endpoint(address, LOCAL), address)
        self.assertTrue(public_endpoint("1.1.1.1", LOCAL))
        self.assertTrue(public_endpoint("2606:4700:4700::1111", LOCAL))
        self.assertFalse(public_endpoint("1.1.1.1", (ipaddress.ip_network("1.1.1.0/24"),)))


if __name__ == "__main__":
    unittest.main()
