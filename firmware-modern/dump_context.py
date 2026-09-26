#!/usr/bin/env python3
"""Dump the board's IIO context as a normalised, diffable contract.

    # run from: the repo root
    python3 firmware-modern/dump_context.py > firmware-modern/baseline/<name>.txt

Every device, channel and attribute the board offers, sorted. This is the
compatibility contract in machine-readable form: diff a run against the
baseline and anything that vanished or got renamed shows up immediately.

It replaces most of what the ~35 source greps in verify-patches.yml assert,
and it keeps working across a kernel replacement, which those greps cannot.
"""
import sys, os, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'selftest'))
from board_addr import resolve
from iiod_min import Iiod

host = sys.argv[1] if len(sys.argv) > 1 else resolve()
with Iiod(host) as c:
    root = ET.fromstring(c.context_xml())
    for a in sorted(root.findall('context-attribute'), key=lambda e: e.get('name')):
        print("context-attr  %s" % a.get('name'))
    for dev in sorted(root.findall('device'), key=lambda d: (d.get('name') or '', d.get('id'))):
        did = "%s (%s)" % (dev.get('name') or '-', dev.get('id'))
        for a in sorted(dev.findall('attribute'), key=lambda e: e.get('name')):
            print("device-attr   %-34s %s" % (did, a.get('name')))
        for ch in sorted(dev.findall('channel'), key=lambda e: (e.get('id'), e.get('type'))):
            ch_id = "%s%s" % (ch.get('id'), "" if ch.get('type') != 'output' else " [out]")
            for a in sorted(ch.findall('attribute'), key=lambda e: e.get('name')):
                print("chan-attr     %-34s %-18s %s" % (did, ch_id, a.get('name')))
            if ch.find('scan-element') is not None:
                print("scan-element  %-34s %s" % (did, ch_id))
        for d in sorted(dev.findall('debug-attribute'), key=lambda e: e.get('name')):
            print("debug-attr    %-34s %s" % (did, d.get('name')))
