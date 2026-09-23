import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import unifi_syslog_rule as rule


def fixture():
    root = ET.fromstring('<opnsense><interfaces><opt2><if>bridge0</if></opt2></interfaces><OPNsense><Firewall><Filter persisted_at="1"><rules/></Filter></Firewall></OPNsense><revision><time>1</time></revision></opnsense>')
    block = ET.SubElement(root.find('.//rules'), 'rule', uuid=rule.BLOCK_ID)
    for key, value in {'enabled': '1', 'sequence': '400', 'action': 'block', 'quick': '1',
                       'interface': 'opt2', 'direction': 'in', 'source_net': 'opt2', 'destination_net': 'lan'}.items():
        ET.SubElement(block, key).text = value
    return root


class RuleGuardTests(unittest.TestCase):
    def test_preflight_stops_for_drift_and_occupied_sequence(self):
        root = fixture()
        rule.preflight(root)
        root.find('.//rule/action').text = 'pass'
        with self.assertRaises(RuntimeError):
            rule.preflight(root)
        root = fixture()
        extra = ET.SubElement(root.find('.//rules'), 'rule', uuid='new')
        ET.SubElement(extra, 'interface').text = 'opt2'
        ET.SubElement(extra, 'sequence').text = '350'
        with self.assertRaises(RuntimeError):
            rule.preflight(root)

    def test_fingerprint_allows_only_new_rule_and_save_metadata(self):
        before = fixture()
        after = copy.deepcopy(before)
        ET.SubElement(after.find('.//rules'), 'rule', uuid='new')
        after.find('.//Filter').set('persisted_at', '2')
        after.find('.//revision/time').text = '2'
        self.assertEqual(rule.protected(before), rule.protected(after, 'new'))
        after.find('.//rule/action').text = 'pass'
        self.assertNotEqual(rule.protected(before), rule.protected(after, 'new'))

    def test_rule_readback_rejects_wider_destination(self):
        with patch.object(rule, 'api', return_value={'rule': dict(rule.EXPECTED)}):
            rule.read_rule('new')
        with patch.object(rule, 'api', return_value={'rule': {**rule.EXPECTED, 'destination_net': 'lan'}}):
            with self.assertRaises(RuntimeError):
                rule.read_rule('new')

    def test_disable_refuses_a_drifted_rule_before_any_write(self):
        with patch.object(rule, 'api', return_value={'rule': {**rule.EXPECTED, 'protocol': 'TCP/UDP'}}) as api:
            with self.assertRaises(RuntimeError):
                rule.disable({'uuid': 'new'})
            self.assertEqual(api.call_count, 1)
            self.assertEqual(len(api.call_args.args), 1)

    def test_runtime_service_name_numeric_port_and_order(self):
        before = fixture()
        after = copy.deepcopy(before)
        ET.SubElement(after.find('.//rules'), 'rule', uuid='new-rule')
        state = {'uuid': 'new-rule', 'protected_sha256': rule.protected(before)}
        block = 'block in quick on bridge0 label "' + rule.BLOCK_ID + '"'
        for port in ['514', 'syslog', '5140']:
            line = 'pass in log quick on bridge0 inet proto udp from 10.10.20.50 to 192.168.5.230 port = ' + port + ' keep state label "new-rule"'
            for reverse in [False, True]:
                runtime = '\n'.join([block, line] if reverse else [line, block]).encode()
                with patch.object(rule, 'read_rule'), patch.object(rule, 'config', return_value=(b'', after)), patch.object(rule, 'ssh', return_value=runtime), patch('builtins.print'):
                    if port == '5140' or reverse:
                        with self.assertRaises(RuntimeError): rule.verify(state)
                    else:
                        rule.verify(state)


if __name__ == '__main__':
    unittest.main()
