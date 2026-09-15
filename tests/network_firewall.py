"""Exercise the deployed firewall helper in isolated Linux network namespaces.

Run as root on Linux: sudo python3 tests/network_firewall.py
No cloud access or changes to the host network namespace are made.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


SERVER = r"""
import socket, threading, time
def tcp(port):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', port)); s.listen()
    def reply(c, peer):
        with c:
            while c.recv(128):
                c.sendall(peer[0].encode())
    while True:
        c, peer = s.accept()
        threading.Thread(target=reply, args=(c, peer), daemon=True).start()
def udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('0.0.0.0', 53))
    while True:
        data, peer = s.recvfrom(128); s.sendto(data, peer)
for port in (22, 80, 443, 8080):
    threading.Thread(target=tcp, args=(port,), daemon=True).start()
threading.Thread(target=udp, daemon=True).start()
while True: time.sleep(60)
"""
CLIENT = r"""
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if sys.argv[3] == 'udp' else socket.SOCK_STREAM)
s.settimeout(0.6)
if sys.argv[4]: s.bind((sys.argv[4], 0))
try:
    s.connect((sys.argv[1], int(sys.argv[2])))
    s.send(b'probe'); print(s.recv(128).decode())
except OSError:
    sys.exit(1)
finally:
    s.close()
"""


class FirewallNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != 'linux' or os.geteuid() != 0:
            raise RuntimeError('Run this integration test as root on Linux.')
        for tool in ('ip', 'iptables', 'iptables-restore', 'terraform'):
            if not shutil.which(tool):
                raise RuntimeError(f'Required tool is missing: {tool}')
        cls.names = {role: f'i31-{role}-{uuid.uuid4().hex[:6]}' for role in ('c', 'r', 's')}
        cls.servers = []
        cls.temporary = tempfile.TemporaryDirectory(prefix='issue31-')
        cls.addClassCleanup(cls.cleanup)
        template = Path(__file__).resolve().parents[1] / 'templates/team-nat-firewall.sh.tftpl'
        expression = f'jsonencode(templatefile({json.dumps(str(template))}, {{subnet_cidr="10.0.5.0/24",nat_tcp_ports="80,443"}}))'
        rendered = subprocess.run(['terraform', 'console', '-no-color'], input=expression + '\n',
                                  cwd=cls.temporary.name, text=True, capture_output=True, check=True)
        cls.script = Path(cls.temporary.name) / 'firewall.sh'
        cls.script.write_text(json.loads(json.loads(rendered.stdout.strip())))
        subprocess.run(['bash', '-n', str(cls.script)], check=True)
        for name in cls.names.values():
            cls.command('ip', 'netns', 'add', name)
            cls.command('ip', '-n', name, 'link', 'set', 'lo', 'up')
        cls.command('ip', '-n', cls.names['c'], 'link', 'add', 'lan', 'type', 'veth', 'peer', 'name', 'client', 'netns', cls.names['r'])
        cls.command('ip', '-n', cls.names['s'], 'link', 'add', 'wan', 'type', 'veth', 'peer', 'name', 'uplink', 'netns', cls.names['r'])
        for role, device, address in (
            ('c', 'lan', '10.0.5.10/24'), ('c', 'lan', '10.0.6.10/24'),
            ('r', 'client', '10.0.5.2/24'), ('r', 'client', '10.0.6.2/24'),
            ('r', 'uplink', '192.0.2.1/24'), ('s', 'wan', '192.0.2.2/24'),
        ):
            cls.command('ip', '-n', cls.names[role], 'addr', 'add', address, 'dev', device)
            cls.command('ip', '-n', cls.names[role], 'link', 'set', device, 'up')
        cls.command('ip', '-n', cls.names['c'], 'route', 'add', 'default', 'via', '10.0.5.2')
        cls.command('ip', '-n', cls.names['r'], 'route', 'add', 'default', 'via', '192.0.2.2')
        cls.command('ip', '-n', cls.names['s'], 'route', 'add', '10.0.6.0/24', 'via', '192.0.2.1')
        for role in ('r', 's'):
            cls.servers.append(subprocess.Popen(['ip', 'netns', 'exec', cls.names[role], sys.executable, '-c', SERVER]))
        # Establish that the host ports really have listeners before testing a deny.
        for _ in range(30):
            if cls.probe('10.0.5.2', 80).returncode == 0:
                break
            time.sleep(0.1)
        for port in (22, 80, 443, 8080):
            if cls.probe('10.0.5.2', port).returncode:
                raise RuntimeError(f'Baseline host listener {port} unavailable.')
        # Preserve unrelated host rules while reloading our own chains.
        cls.ns('r', 'iptables', '-N', 'UNRELATED')
        cls.ns('r', 'iptables', '-A', 'UNRELATED', '-j', 'RETURN')
        cls.load()
        # The destination listeners are checked directly, outside the router's filters.
        for port in (22, 80, 443):
            if cls.probe('192.0.2.2', port, role='s').returncode:
                raise RuntimeError(f'Baseline destination listener {port} unavailable.')
        if cls.probe('192.0.2.2', 53, protocol='udp', role='s').returncode:
            raise RuntimeError('Baseline UDP listener unavailable.')

    @classmethod
    def command(cls, *args):
        return subprocess.run(args, check=True, text=True, capture_output=True)

    @classmethod
    def ns(cls, role, *args):
        return cls.command('ip', 'netns', 'exec', cls.names[role], *args)

    @classmethod
    def load(cls):
        cls.ns('r', 'bash', str(cls.script), '--enable-forwarding')

    @classmethod
    def probe(cls, address, port, protocol='tcp', source='', role='c'):
        return subprocess.run(['ip', 'netns', 'exec', cls.names[role], sys.executable, '-c', CLIENT,
                               address, str(port), protocol, source], text=True, capture_output=True, timeout=3)

    @classmethod
    def cleanup(cls):
        for server in cls.servers:
            server.terminate()
            server.wait(timeout=5)
        for name in cls.names.values():
            subprocess.run(['ip', 'netns', 'delete', name], capture_output=True)
        cls.temporary.cleanup()

    def test_nat_http_https_and_reply_traffic(self):
        for port in (80, 443):
            with self.subTest(port=port):
                result = self.probe('192.0.2.2', port)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), '192.0.2.1', 'The destination must see the NAT address.')

    def test_local_web_ports_blocked_but_ssh_and_headscale_reach_host(self):
        # GCP separately restricts SSH sources and permits 8080 only from Spectre.
        for port in (80, 443):
            self.assertNotEqual(self.probe('10.0.5.2', port).returncode, 0)
        for port in (22, 8080):
            self.assertEqual(self.probe('10.0.5.2', port).returncode, 0)

    def test_other_forwarded_tcp_and_udp_blocked(self):
        self.assertNotEqual(self.probe('192.0.2.2', 22).returncode, 0)
        self.assertNotEqual(self.probe('192.0.2.2', 53, protocol='udp').returncode, 0)

    def test_other_source_network_blocked(self):
        self.assertNotEqual(self.probe('192.0.2.2', 443, source='10.0.6.10').returncode, 0)

    def test_reload_keeps_connections_and_does_not_duplicate_rules(self):
        held_client = r"""
import socket, sys
s = socket.create_connection(('192.0.2.2', 443), timeout=3)
for line in sys.stdin:
    s.send(line.encode()); print(s.recv(128).decode(), flush=True)
"""
        with subprocess.Popen(['ip', 'netns', 'exec', self.names['c'], sys.executable, '-c', held_client],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as client:
            client.stdin.write('before\n'); client.stdin.flush()
            self.assertEqual(client.stdout.readline().strip(), '192.0.2.1')
            self.load()
            self.load()
            client.stdin.write('after\n'); client.stdin.flush()
            self.assertEqual(client.stdout.readline().strip(), '192.0.2.1')
            client.stdin.close()
        for chain, target in (('INPUT', 'TEAM-NAT-INPUT'), ('FORWARD', 'TEAM-NAT-FORWARD')):
            lines = self.ns('r', 'iptables', '-S', chain).stdout.splitlines()
            self.assertEqual(lines.count(f'-A {chain} -j {target}'), 1)
        nat = self.ns('r', 'iptables', '-t', 'nat', '-S', 'POSTROUTING').stdout
        self.assertEqual(nat.count('MASQUERADE'), 1)
        self.assertIn('-A UNRELATED -j RETURN', self.ns('r', 'iptables', '-S', 'UNRELATED').stdout)

    def test_rules_can_be_rebuilt_after_loss_of_runtime_state(self):
        # Simulate volatile firewall/NAT state loss; this is not a VM reboot test.
        self.ns('r', 'iptables', '-F')
        self.ns('r', 'iptables', '-X')
        self.ns('r', 'iptables', '-t', 'nat', '-F')
        self.ns('r', 'bash', str(self.script))
        self.assertNotEqual(self.probe('10.0.5.2', 443).returncode, 0)
        self.load()
        self.assertEqual(self.probe('192.0.2.2', 443).returncode, 0)
        # Leave the fixture in its original state for other tests.
        self.ns('r', 'iptables', '-N', 'UNRELATED')
        self.ns('r', 'iptables', '-A', 'UNRELATED', '-j', 'RETURN')

    def test_selective_filter_rollback_restores_access(self):
        try:
            for chain, target in (('INPUT', 'TEAM-NAT-INPUT'), ('FORWARD', 'TEAM-NAT-FORWARD')):
                self.ns('r', 'iptables', '-D', chain, '-j', target)
                self.ns('r', 'iptables', '-F', target)
                self.ns('r', 'iptables', '-X', target)
            self.assertEqual(self.probe('10.0.5.2', 80).returncode, 0)
            self.assertEqual(self.probe('192.0.2.2', 22).returncode, 0)
            self.assertIn('-A UNRELATED -j RETURN', self.ns('r', 'iptables', '-S', 'UNRELATED').stdout)
        finally:
            self.load()


if __name__ == '__main__':
    unittest.main(verbosity=2)
