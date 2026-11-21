#!/usr/bin/env python3
"""Test the packet handling of overlay/usr/local/sbin/fishball-usb-dhcp.

    # run from: anywhere
    python3 firmware-modern/debian/tests/test_usb_dhcp.py

Only parse() and reply(): what the server answers, to whom, with which options.
The socket (port 67, SO_BINDTODEVICE on usb0) needs Linux and root, so serve()
is not run here. tests/test-usb-gadget.sh runs this file as well.
"""
import importlib.machinery
import importlib.util
import ipaddress
import pathlib
import struct
import sys
import unittest

sys.dont_write_bytecode = True  # no __pycache__ in the overlay: it would ship
SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "overlay/usr/local/sbin/fishball-usb-dhcp"
loader = importlib.machinery.SourceFileLoader("fishball_usb_dhcp", str(SCRIPT))
dhcp = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(dhcp)

SERVER = ipaddress.IPv4Address("192.168.2.1")
LEASE = ipaddress.IPv4Address("192.168.2.10")
MASK = ipaddress.IPv4Address("255.255.255.0")
MAC = bytes.fromhex("00e0222a2b8a")


def request(kind, *, requested=None, ciaddr="0.0.0.0", server_id=None, giaddr="0.0.0.0", flags=0):
    opts = bytes([53, 1, kind])
    if requested:
        opts += bytes([50, 4]) + ipaddress.IPv4Address(requested).packed
    if server_id:
        opts += bytes([54, 4]) + ipaddress.IPv4Address(server_id).packed
    opts += bytes([55, 4, 1, 3, 6, 15, 255])  # the PC asks for a router and DNS
    return (bytes([1, 1, 6, 0]) + b"\xde\xad\xbe\xef" + b"\0\0" + struct.pack("!H", flags)
            + ipaddress.IPv4Address(ciaddr).packed + bytes(8)
            + ipaddress.IPv4Address(giaddr).packed + MAC + bytes(10) + bytes(192)
            + dhcp.MAGIC + opts)


def answer(packet):
    req = dhcp.parse(packet)
    return req and dhcp.reply(req, SERVER, LEASE, MASK)


def options(packet):
    out, i = {}, 240
    while packet[i] != 255:
        out[packet[i]] = packet[i + 2:i + 2 + packet[i + 1]]
        i += 2 + packet[i + 1]
    return out


class Reply(unittest.TestCase):
    def test_discover_gets_an_offer_of_the_one_address(self):
        packet, dest = answer(request(dhcp.DISCOVER))
        self.assertEqual(packet[0], 2)                       # BOOTREPLY
        self.assertEqual(packet[4:8], b"\xde\xad\xbe\xef")   # the PC's xid
        self.assertEqual(packet[16:20], LEASE.packed)        # yiaddr
        self.assertEqual(packet[28:34], MAC)
        self.assertEqual(packet[236:240], dhcp.MAGIC)
        o = options(packet)
        self.assertEqual(o[53], bytes([dhcp.OFFER]))
        self.assertEqual(o[54], SERVER.packed)
        self.assertEqual(o[1], MASK.packed)
        self.assertEqual(o[51], struct.pack("!I", dhcp.LEASE_SECONDS))
        self.assertEqual(dest, "255.255.255.255")            # the PC has no address yet
        self.assertGreaterEqual(len(packet), 300)

    def test_no_router_and_no_dns_even_when_asked(self):
        # With either, a PC may route its internet traffic into the board.
        for kind in (dhcp.DISCOVER, dhcp.REQUEST, dhcp.INFORM):
            o = options(answer(request(kind, requested="192.168.2.10"))[0])
            self.assertNotIn(3, o)
            self.assertNotIn(6, o)

    def test_request_for_the_address_is_acked(self):
        packet, dest = answer(request(dhcp.REQUEST, requested="192.168.2.10", server_id="192.168.2.1"))
        self.assertEqual(options(packet)[53], bytes([dhcp.ACK]))
        self.assertEqual(packet[16:20], LEASE.packed)
        self.assertEqual(dest, "255.255.255.255")

    def test_renewal_is_acked_to_the_pc_itself(self):
        packet, dest = answer(request(dhcp.REQUEST, ciaddr="192.168.2.10"))
        self.assertEqual(options(packet)[53], bytes([dhcp.ACK]))
        self.assertEqual(dest, "192.168.2.10")

    def test_request_for_another_networks_address_is_nakked(self):
        # A laptop that was last on 192.168.1.x asks for that address first.
        packet, dest = answer(request(dhcp.REQUEST, requested="192.168.1.23"))
        o = options(packet)
        self.assertEqual(o[53], bytes([dhcp.NAK]))
        self.assertEqual(packet[16:20], bytes(4))
        self.assertNotIn(51, o)
        self.assertEqual(dest, "255.255.255.255")

    def test_request_meant_for_another_server_is_ignored(self):
        self.assertIsNone(answer(request(dhcp.REQUEST, requested="192.168.2.10", server_id="192.168.2.254")))

    def test_inform_gets_options_but_no_address(self):
        packet, dest = answer(request(dhcp.INFORM, ciaddr="192.168.2.10"))
        o = options(packet)
        self.assertEqual(o[53], bytes([dhcp.ACK]))
        self.assertEqual(packet[16:20], bytes(4))
        self.assertNotIn(51, o)
        self.assertEqual(dest, "192.168.2.10")

    def test_the_broadcast_flag_is_echoed(self):
        packet, _ = answer(request(dhcp.DISCOVER, flags=0x8000))
        self.assertEqual(packet[10:12], b"\x80\x00")

    def test_silence(self):
        self.assertIsNone(answer(request(dhcp.RELEASE, ciaddr="192.168.2.10")))
        self.assertIsNone(answer(request(dhcp.DECLINE, requested="192.168.2.10")))
        self.assertIsNone(answer(request(dhcp.DISCOVER, giaddr="10.0.0.1")))     # relayed
        self.assertIsNone(answer(b"\x02" + request(dhcp.DISCOVER)[1:]))          # a reply, not a request
        self.assertIsNone(answer(request(dhcp.DISCOVER)[:200]))                  # truncated
        self.assertIsNone(answer(request(dhcp.DISCOVER)[:236] + b"\0\0\0\0"))    # BOOTP without DHCP
        self.assertIsNone(answer(bytes(300)))

    def test_a_truncated_option_does_not_raise(self):
        self.assertIsNotNone(answer(request(dhcp.DISCOVER)[:-1] + bytes([61])))


if __name__ == "__main__":
    unittest.main()
