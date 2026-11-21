#!/usr/bin/env python3
"""Execute the card image writer and the macOS card writer's refusals. No card,
no root, no disk: an image file in a temporary directory, and made-up
`diskutil info` answers.

    # run from: the repo root (Linux, macOS or Windows)
    python3 tools/selftest/test_card_image.py

What it cannot do is ask a Linux kernel whether the ext3 it wrote is right:
that is tools/check_card_image.py, on Linux as root, and CI runs it on the
image this OS made (see .github/workflows/host-tools.yml). Here: the image is
built from tools/card_image_testdata.py's hard cases, its partition table and
FAT partition are read back, a damaged byte is caught by the read-back, and
every reason tools/write_card_mac.py has for refusing a disk is tried.

The pre-flight is tried with one archive for each thing the writer refuses,
over a "card" full of old data that must come through untouched. The macOS
writer's whole run on a real disk is driven with a file standing in for
/dev/rdisk4 and made-up diskutil answers: wrong confirmation, a card that
changes, an I/O error, Ctrl-C and a bug in the middle of the write.

On Linux as root (with dosfstools and e2fsprogs) it also runs
tools/check_card_image.py on the image, and on five copies of it broken by
card_image_testdata.py --mutate, which the checker must fail.
Exit 0 if every behaviour holds, 1 otherwise. Python 3.8.
"""
import contextlib
import errno
import gzip
import hashlib
import io
import os
import pathlib
import plistlib
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import card_image  # noqa: E402
import card_image_testdata  # noqa: E402
import check_card_image  # noqa: E402
import write_card_mac  # noqa: E402

FAILURES = []
CHECKS = 0


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    print("%s  %s" % ("ok  " if ok else "FAIL", name))
    if not ok:
        FAILURES.append(name)
        if detail:
            print("        " + str(detail)[:600])


# ---- 1. the image ----------------------------------------------------------
tmp = tempfile.mkdtemp(prefix="card-image-test-")
rel = os.path.join(tmp, "rel")
img = os.path.join(tmp, "card.img")
r = subprocess.run([sys.executable, str(ROOT / "tools" / "card_image_testdata.py"), rel],
                   capture_output=True, text=True)
check("the hard-case test release is made", r.returncode == 0, r.stderr)
r = subprocess.run([sys.executable, str(ROOT / "tools" / "card_image.py"), rel, img, "--size", "1024"],
                   capture_output=True, text=True)
check("card_image.py builds an image from it", r.returncode == 0 and "read back identical" in r.stdout,
      r.stdout + r.stderr)
check("the image is exactly --size", os.path.getsize(img) == 1024 * 1024 * 1024)
check("device nodes, symlinks and directories are all counted",
      "8 device nodes" in r.stdout and "722 symlinks" in r.stdout, r.stdout)

r2 = subprocess.run([sys.executable, str(ROOT / "tools" / "card_image.py"), rel, img, "--size", "1024"],
                    capture_output=True, text=True)
check("an existing image is never overwritten", r2.returncode != 0 and "already exists" in r2.stderr, r2.stderr)
r2 = subprocess.run([sys.executable, str(ROOT / "tools" / "card_image.py"), rel, img + ".small", "--size", "512"],
                    capture_output=True, text=True)
check("an image under 1 GB is refused, and no file is left",
      r2.returncode != 0 and not os.path.exists(img + ".small"), r2.stderr)

with open(img, "rb") as f:
    parts = card_image.read_mbr(f)
    check("partition table: bootable FAT32 (0x0C) at 2048, 128 MB; Linux (0x83) right after, to the end",
          parts == [(0x80, 0x0C, 2048, 262144), (0x00, 0x83, 264192, 1024 * 2048 - 264192)], parts)
    got = card_image.fat32_read_root(f, 2048 * 512)
    want = {n: open(os.path.join(rel, n), "rb").read() for n in card_image.BOOT_FILES}
    check("the FAT partition holds exactly the four boot files, byte for byte", got == want, sorted(got))
    f.seek(2048 * 512)
    bs = f.read(512)
    check("FAT32 boot sector: label FISHBOOT, 512-byte sectors, backup at sector 6",
          bs[71:82] == b"FISHBOOT   " and bs[82:90] == b"FAT32   " and struct.unpack_from("<H", bs, 11)[0] == 512
          and struct.unpack_from("<H", bs, 50)[0] == 6)
    f.seek(2054 * 512)
    check("the backup boot sector is a copy", f.read(512) == bs)
    f.seek(264192 * 512 + 1024)
    sb = f.read(1024)
    magic, = struct.unpack_from("<H", sb, 56)
    compat, incompat, ro = struct.unpack_from("<III", sb, 92)
    check("ext superblock: magic, label fishroot, has_journal, no ext4-only feature",
          magic == 0xEF53 and sb[120:136].rstrip(b"\0") == b"fishroot" and compat & 0x04
          and incompat == 0x02 and ro == 0x03, (hex(magic), compat, incompat, ro))
    blocks, = struct.unpack_from("<I", sb, 4)
    check("the root filesystem fills its partition (to within one block group's tail)",
          0 <= (1024 * 2048 - 264192) // 8 - blocks < 32768, blocks)
    inodes, = struct.unpack_from("<I", sb, 0)
    ipg, = struct.unpack_from("<I", sb, 40)
    check("one inode per 16 KiB, as mke2fs gives: 8192 in each 128 MiB group, 57344 on a 1024 MB image",
          (ipg, inodes) == (8192, 57344), (ipg, inodes))
check("the summary says how many inodes are used and free", "5127 of 57344 inodes used, 52217 free" in r.stdout, r.stdout)
check("the FAT volume label and the 8.3 names are what a strict reader needs (raw directory entries)",
      check_card_image.check_fat_names(img, 2048 * 512) == [], check_card_image.check_fat_names(img, 2048 * 512))
_, _ents = check_card_image.fat_root_entries(img, 2048 * 512)
check("raw root directory: label FISHBOOT, then BOOT.BIN UIMAGE DEVICE~1.DTB UENV.TXT, each with its long name",
      [(e["short"], e["long"]) for e in _ents] == [(b"FISHBOOT   ", None), (b"BOOT    BIN", "BOOT.bin"),
                                                  (b"UIMAGE     ", "uImage"), (b"DEVICE~1DTB", "devicetree.dtb"),
                                                  (b"UENV    TXT", "uEnv.txt")], _ents)

# The checker must FAIL an image broken where fsck does not look. The FAT ones
# need only Python; the journal needs a kernel (below, on Linux as root).
for kind, word in (("fat-label", "root directory volume label"), ("fat-label-root", "root directory volume label"),
                   ("fat-label-bs", "boot sector volume label"), ("short-name", "8.3 name is b'BOOT~1  BIN'")):
    mut = os.path.join(tmp, "mut-%s.img" % kind)
    shutil.copyfile(img, mut)
    card_image_testdata.mutate(mut, kind)
    got = check_card_image.check_fat_names(mut, 2048 * 512)
    check("mutation %s: the checker's FAT check names it" % kind,
          len(got) == (2 if kind == "fat-label" else 1) and any(word in g for g in got), got)
    with open(mut, "rb") as f:
        still = card_image.fat32_read_root(f, 2048 * 512)
    check("mutation %s: ...and nothing else notices (the four files still read back by name)" % kind,
          still == want, sorted(still))
    os.remove(mut)

LINUX_ROOT = (sys.platform.startswith("linux") and os.geteuid() == 0
              and all(shutil.which(x) for x in ("fsck.vfat", "e2fsck", "mount", "dd")))
CHECKER = [sys.executable, str(ROOT / "tools" / "check_card_image.py")]
if LINUX_ROOT:
    rc_ = subprocess.run(CHECKER + [img, rel], capture_output=True, text=True)
    check("Linux: check_card_image.py passes the image, read-write mount included",
          rc_.returncode == 0 and "PASS" in rc_.stdout and "read-write mount as ext4: journal loaded" in rc_.stdout,
          rc_.stdout[-1500:] + rc_.stderr[-500:])
    check("Linux: the mounted root shows the higher inode count", "root partition: 57344 inodes" in rc_.stdout,
          rc_.stdout[-600:])
    for kind, word in (("journal", "does not mount read-write"), ("fat-label", "volume label or 8.3 names"),
                       ("fat-label-root", "volume label or 8.3 names"), ("fat-label-bs", "volume label or 8.3 names"),
                       ("short-name", "volume label or 8.3 names")):
        mut = os.path.join(tmp, "mut-%s.img" % kind)
        subprocess.run(["cp", "--sparse=always", img, mut], check=True)
        card_image_testdata.mutate(mut, kind)
        rc_ = subprocess.run(CHECKER + [mut, rel], capture_output=True, text=True)
        check("Linux: check_card_image.py FAILS the image with mutation %s" % kind,
              rc_.returncode == 1 and "FAIL: " in rc_.stdout and word in rc_.stdout, rc_.stdout[-900:] + rc_.stderr[-300:])
        if kind == "journal":
            check("Linux: ...which e2fsck and a read-only mount had passed",
                  "$ e2fsck -fn\nfishroot:" in rc_.stdout and "0 mismatches" in rc_.stdout, rc_.stdout[-900:])
        os.remove(mut)
else:
    print("note  not Linux as root with fsck: check_card_image.py itself is not run here (the journal mutation needs it)")

# A release whose rootfs is damaged: refused before or while writing, no image left.
bad_rel = os.path.join(tmp, "bad")
os.mkdir(bad_rel)
for n in card_image.BOOT_FILES + [card_image.ROOTFS, "SHA256SUMS"]:
    data = open(os.path.join(rel, n), "rb").read()
    if n == card_image.ROOTFS:
        data = data[:len(data) // 2]
    open(os.path.join(bad_rel, n), "wb").write(data)
r2 = subprocess.run([sys.executable, str(ROOT / "tools" / "card_image.py"), bad_rel, img + ".bad"],
                    capture_output=True, text=True)
check("a rootfs that does not match SHA256SUMS is refused",
      r2.returncode != 0 and "does not match SHA256SUMS" in r2.stderr and not os.path.exists(img + ".bad"), r2.stderr)
os.remove(os.path.join(bad_rel, "SHA256SUMS"))
r2 = subprocess.run([sys.executable, str(ROOT / "tools" / "card_image.py"), bad_rel, img + ".bad"],
                    capture_output=True, text=True)
check("a truncated rootfs with no SHA256SUMS fails cleanly and leaves no image",
      r2.returncode != 0 and "damaged" in r2.stderr and "Traceback" not in r2.stderr
      and not os.path.exists(img + ".bad"), r2.stderr)


# ---- 2. the read-back catches a card that did not keep what was written ------
class Flaky:
    """A file that silently drops one write, as a worn card does."""

    def __init__(self, f, drop_at):
        self.f, self.drop_at, self.n = f, drop_at, 0

    def write(self, b):
        self.n += 1
        if self.n == self.drop_at:
            return len(b)
        return self.f.write(b)

    def __getattr__(self, name):
        return getattr(self.f, name)


boot = [(n, os.path.join(rel, n)) for n in card_image.BOOT_FILES]
tgz = os.path.join(rel, card_image.ROOTFS)
quiet = lambda s: None  # noqa: E731
for drop in (3, 9):
    p = os.path.join(tmp, "flaky%d.img" % drop)
    with open(p, "w+b", buffering=0) as f:
        f.truncate(1024 * 1024 * 1024)
        t = card_image.Target(Flaky(f, drop), 1024 * 1024 * 1024)
        card_image.write_card(t, boot, tgz, quiet, progress=False)
        check("a dropped write (number %d) is caught by the read-back" % drop, t.verify() is False)
    os.remove(p)

# A used card: every byte not written keeps its old content. The result must
# still read back, and its boot files must still be found through the FAT.
p = os.path.join(tmp, "used.img")
with open(p, "w+b", buffering=0) as f:
    junk = hashlib.sha256(b"junk").digest() * 32768
    for _ in range(1024):
        f.write(junk)
    t = card_image.Target(f, 1024 * 1024 * 1024)
    card_image.write_card(t, boot, tgz, quiet, progress=False)
    check("over a card full of old data: read-back identical", t.verify() is True)
    check("over a card full of old data: far less than the card is written", t.bytes_written < 200 << 20,
          t.bytes_written)
    want_sha = {n: card_image.sha256_file(q) for n, q in boot}
    check("over a card full of old data: the four boot files read back through the FAT",
          card_image.check_boot_readback(f, want_sha, quiet) == [])
    wrong = dict(want_sha, **{"uImage": "0" * 64})
    check("a boot file with the wrong hash is named", card_image.check_boot_readback(f, wrong, quiet) == ["uImage"])
os.remove(p)

# ---- 3. which disks the macOS writer refuses --------------------------------
# What `diskutil info -plist` says about a card in a USB reader.
CARD = {"DeviceIdentifier": "disk4", "ParentWholeDisk": "disk4", "WholeDisk": True, "Internal": False,
        "RemovableMedia": True, "Removable": True, "Ejectable": True, "VirtualOrPhysical": "Physical",
        "BusProtocol": "USB", "TotalSize": 31914983424, "Size": 31914983424, "MediaName": "SD Card Reader",
        "WritableMedia": True}
SYSTEM = {"disk0", "disk3"}


def refused(dev="/dev/disk4", mounts=(), system=SYSTEM, allow_large=False, **change):
    info = dict(CARD, **change)
    for k in [k for k, v in info.items() if v is None]:
        del info[k]
    try:
        write_card_mac.check_disk(dev, info, system, list(mounts), allow_large)
    except ValueError as e:
        return str(e)
    return ""


check("a card in an external USB reader is accepted", refused() == "", refused())
check("...also named by its raw device", refused("/dev/rdisk4") == "")
check("...also with a FAT volume mounted under /Volumes", refused(mounts=["/Volumes/FISHBOOT"]) == "")
check("an internal disk is refused", "INTERNAL" in refused(Internal=True))
check("...and the refusal says what a built-in SD slot must report, and to use a USB card reader",
      "built-in SD slot" in refused(Internal=True) and "USB card reader" in refused(Internal=True), refused(Internal=True))
SLOT = {"Internal": True, "BusProtocol": "Secure Digital", "RemovableMedia": True, "Removable": True,
        "MediaName": "Built In SDXC Reader"}
check("a card in the Mac's built-in SD slot (internal, Secure Digital, removable media) is accepted",
      refused(**SLOT) == "", refused(**SLOT))
check("an internal SSD is refused", "INTERNAL" in refused(Internal=True, BusProtocol="SATA", RemovableMedia=False,
                                                         Removable=False, SolidState=True))
check("an internal NVMe disk is refused", "INTERNAL" in refused(Internal=True, BusProtocol="PCI-Express",
                                                               RemovableMedia=False, Removable=False))
check("the Mac's own Apple Fabric disk is refused", "INTERNAL" in refused(Internal=True, BusProtocol="Apple Fabric",
                                                                          RemovableMedia=False, Removable=False))
check("an internal disk that says Secure Digital but not removable media is refused",
      "INTERNAL" in refused(**dict(SLOT, RemovableMedia=False)))
check("an internal disk with removable media that is not Secure Digital is refused",
      "INTERNAL" in refused(**dict(SLOT, BusProtocol="SATA")))
check("a built-in-slot disk that is in the boot-disk set is refused",
      "macOS runs from" in refused(system={"disk0", "disk4"}, **SLOT))
check("a built-in-slot disk holding a system volume is refused",
      "running system" in refused(mounts=["/System/Volumes/Data"], **SLOT))
check("a built-in-slot disk that is an APFS container is refused", "APFS" in refused(APFSContainerReference="disk5", **SLOT))
check("a disk whose VirtualOrPhysical is 'Unknown' is accepted (macOS says so of real card readers)",
      refused(VirtualOrPhysical="Unknown") == "")
check("...and one that does not say", refused(VirtualOrPhysical=None) == "")
check("a Virtual disk is refused even on a USB bus", "not a physical disk" in refused(VirtualOrPhysical="Virtual"))
check("a Disk Image is refused even if it claims to be physical", "not a physical disk" in refused(BusProtocol="Disk Image"))
check("a disk that does not say whether it is internal is refused", "INTERNAL" in refused(Internal=None))
check("an external disk that is not removable (a USB SSD) is refused",
      "NOT removable" in refused(RemovableMedia=False, Removable=False))
check("...and one that does not say", "NOT removable" in refused(RemovableMedia=None, Removable=None))
check("a partition is refused by its name", "is a partition" in refused("/dev/disk4s1"))
check("a partition is refused by what diskutil says",
      "not a whole disk" in refused(WholeDisk=False))
check("a mounted disk image is refused",
      "not a physical disk" in refused(VirtualOrPhysical="Virtual", BusProtocol="Disk Image"))
check("an APFS container is refused", "APFS" in refused(APFSContainerReference="disk5"))
check("the disk macOS runs from is refused, whatever else it claims",
      "macOS runs from" in refused(system={"disk0", "disk4"}))
check("a disk with a volume mounted at / is refused", "running system" in refused(mounts=["/"]))
check("a disk with a system volume mounted is refused",
      "running system" in refused(mounts=["/System/Volumes/Data"]))
check("a 512 GB disk is refused, and the refusal says how to insist",
      "over 280 GB is refused" in refused(TotalSize=512 * 10 ** 9) and "ALLOW_LARGE=1" in refused(TotalSize=512 * 10 ** 9))
check("...and is accepted when the user insists", refused(TotalSize=512 * 10 ** 9, allow_large=True) == "")
check("a card sold as 256 GB (256 060 514 304 bytes) is accepted", refused(TotalSize=256060514304) == "")
check("...and one of 256 GiB", refused(TotalSize=256 * 1024 ** 3) == "")
check("a card sold as 1 GB (10^9 bytes, 953 MiB) is accepted: whether the release fits is the pre-flight's to say",
      refused(TotalSize=10 ** 9) == "")
check("a 512 MB card is refused", "layout needs 829 MB" in refused(TotalSize=512 * 1024 * 1024),
      refused(TotalSize=512 * 1024 * 1024))
check("an empty reader (no size) is refused", "no card" in refused(TotalSize=0, Size=0))
check("a Linux device name is refused", "not a macOS disk" in refused("/dev/sdb"))
check("a path that is not a device is refused", "not a macOS disk" in refused("/Volumes/FISHBOOT"))
check("an answer about another disk is refused", "describes" in refused(DeviceIdentifier="disk5"))

def _unknown():
    try:
        write_card_mac.check_disk("/dev/disk9", None, SYSTEM, [])
    except ValueError as e:
        return str(e)
    return ""


check("a disk diskutil does not know is refused", "knows no disk" in _unknown())

# ---- 3b. the pre-flight: nothing is erased for a release that cannot be written
MT = 1760000000


def make_release(name, fill, fmt=tarfile.USTAR_FORMAT):
    """A release in tmp/NAME whose rootfs is what fill(add) adds; boot files from the test release."""
    d = os.path.join(tmp, name)
    os.mkdir(d)
    for n in card_image.BOOT_FILES:
        shutil.copyfile(os.path.join(rel, n), os.path.join(d, n))
    with gzip.GzipFile(os.path.join(d, card_image.ROOTFS), "wb", compresslevel=1, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=fmt) as t:
            def add(path, type_=tarfile.REGTYPE, data=b"", link="", mtime=MT, raw=False, fileobj=None, size=None):
                m = tarfile.TarInfo(path if raw else "./" + path)
                m.type, m.mode, m.mtime, m.linkname = type_, 0o755 if type_ == tarfile.DIRTYPE else 0o644, mtime, link
                if type_ == tarfile.REGTYPE:
                    m.size = len(data) if size is None else size
                    t.addfile(m, fileobj or io.BytesIO(data))
                else:
                    t.addfile(m)
            add("", tarfile.DIRTYPE)
            add("etc", tarfile.DIRTYPE)
            add("etc/passwd", data=b"root\n")
            fill(add)
    return d


class Zeros:
    """n zero bytes as a file, for a member larger than the card."""

    def __init__(self, n):
        self.n = n

    def read(self, k):
        k = min(k, self.n)
        self.n -= k
        return bytes(k)


L, D, S = tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE
CASES = [
    # name, what the archive holds, the error class, words the message must have
    ("dup", lambda add: (add("etc/f", data=b"old"), add("etc/f", data=b"new")),
     card_image.ArchiveError, ("lists etc/f twice", "tar would keep the later one")),
    ("dotdot", lambda add: add("a/../../evil", data=b"x"), card_image.ArchiveError, ("'..'",)),
    ("name256", lambda add: add("n" * 256, data=b"x"), card_image.ArchiveError, ("256 bytes", "limit is 255")),
    ("type", lambda add: add("vol", b"V"), card_image.ArchiveError, ("unsupported entry type", "vol")),
    ("link-first", lambda add: (add("early", L, link="./later"), add("later", data=b"x")),
     card_image.ArchiveError, ("early is a hard link to ./later", "not listed before")),
    ("link-dir", lambda add: add("hd", L, link="./etc"), card_image.ArchiveError, ("hard link",)),
    ("file-dir", lambda add: (add("x", data=b"x"), add("x/y", data=b"y")),
     card_image.ArchiveError, ("as a directory and as a file",)),
    ("symlink4096", lambda add: add("s", S, link="x" * 4096), card_image.ArchiveError, ("symlink target too long",)),
    ("links65001", lambda add: (add("t", data=b"t"), [add("l%05d" % i, L, link="t") for i in range(65000)]),
     card_image.ArchiveError, ("more than 65000 hard links", "l64999")),
    ("subdirs64999", lambda add: (add("sd", D), [add("sd/%05d" % i, D) for i in range(64999)]),
     card_image.ArchiveError, ("more than 64998 directories", "sd/64998")),
    ("inodes", lambda add: (add("many", D), [add("many/%05d" % i, data=b"") for i in range(60000)]),
     card_image.TooSmallError, ("needs 60", "inodes where a card this size is given 57344")),
    ("blocks", lambda add: add("big", fileobj=Zeros(950 << 20), size=950 << 20),
     card_image.TooSmallError, ("MB more room than the card has",)),
]
GIB = 1024 ** 3
old = os.path.join(tmp, "old-card.img")
with open(old, "w+b") as f:                      # a card with something on it worth keeping
    f.truncate(GIB)
    f.write(b"OLD CARD" * 64 * 2048)
    f.seek(GIB - 512)
    f.write(b"EFI PART" + bytes(504))
old_sha = card_image.sha256_file(old)
for name, fill, cls, words in CASES:
    _t0 = time.time()
    fmt = tarfile.PAX_FORMAT if name in ("name256", "symlink4096") else tarfile.USTAR_FORMAT
    d = make_release(name, fill, fmt)
    b, tg = [(n, os.path.join(d, n)) for n in card_image.BOOT_FILES], os.path.join(d, card_image.ROOTFS)
    err = None
    try:
        card_image.plan_card(GIB, b, tg, progress=False)
    except card_image.CardError as e:
        err = e
    check("pre-flight %s: refused as %s, and the message names it" % (name, cls.__name__),
          type(err) is cls and all(w in str(err) for w in words), "%s: %s" % (type(err).__name__, err))
    msg = card_image.explain(err, "/dev/disk4") if err else ""
    check("pre-flight %s: the message blames the %s, not the card, and says nothing was written"
          % (name, "size" if cls is card_image.TooSmallError else "release"),
          "Nothing was written to /dev/disk4" in msg and "try another card" not in msg
          and (("does not fit" in msg and "It needs about" in msg) if cls is card_image.TooSmallError
               else "not in the card" in msg), msg)
    # The writer handed a card directly: the same refusal, before its first write.
    with open(old, "r+b", buffering=0) as f:
        t = card_image.Target(f, GIB)
        err2 = None
        try:
            card_image.write_card(t, b, tg, quiet, progress=False)
        except card_image.CardError as e:
            err2 = e
        t.flush()
    check("pre-flight %s: write_card() itself refuses the same way and leaves the old card byte for byte" % name,
          type(err2) is cls and str(err2) == str(err) and card_image.sha256_file(old) == old_sha, err2)
    if cls is card_image.TooSmallError:
        try:
            card_image.plan_card(err.need_bytes, b, tg, progress=False)
            fits = True
        except card_image.CardError as e:
            fits = str(e)
        check("pre-flight %s: a card of the size it says it needs (%d MB) does hold it" % (name, err.need_bytes >> 20),
              fits is True and err.need_bytes < 4 * GIB, fits)
    r2 = subprocess.run([sys.executable, str(ROOT / "tools" / "card_image.py"), d, img + "." + name, "--size", "1024"],
                        capture_output=True, text=True)
    check("pre-flight %s: card_image.py makes no image file, and no traceback" % name,
          r2.returncode != 0 and not os.path.exists(img + "." + name) and "Traceback" not in r2.stderr
          and "Nothing was written" in r2.stderr, r2.stderr)
    shutil.rmtree(d)
    if "--times" in sys.argv:
        print("      (%s: %.1f s)" % (name, time.time() - _t0))

# The pre-flight and the write are the same code: they must end in the same place.
plan = card_image.plan_card(GIB, boot, tgz, progress=False)
with open(old, "r+b", buffering=0) as f:
    t = card_image.Target(f, GIB)
    said = []
    fs = card_image.write_card(t, boot, tgz, said.append, progress=False, plan=plan)
    check("the pre-flight's plan is where the write ends: same blocks, inodes and counts",
          plan.layout == card_image._layout_of(fs) and plan.write_bytes == t.bytes_written
          and (plan.inodes_used, plan.inodes_total) == (5127, 57344), (plan.layout, plan.write_bytes, t.bytes_written))
    check("over a card with an old GPT: read-back identical", t.verify() is True)
    f.seek(512)
    first = f.read(8)
    f.seek(GIB - 33 * 512)
    tail = f.read(33 * 512)
    check("an old GPT is gone from both ends of the card: sector 1 and the last 33 sectors",
          first == bytes(8) and b"EFI PART" not in tail and tail[-512:] == bytes(512), (first, tail[-512:-500]))
os.remove(old)

# Timestamps ext3's 32 bits cannot hold: moved to the nearest end, counted, said once.
d = make_release("times", lambda add: (add("neg", data=b"x", mtime=-5), add("y2038", data=b"x", mtime=2 ** 31 + 100),
                                       add("y2106", data=b"x", mtime=2 ** 33), add("last", data=b"x", mtime=2 ** 31 - 1),
                                       add("zero", data=b"x", mtime=0), add("float", data=b"x", mtime=MT + 0.75)),
                 tarfile.PAX_FORMAT)
r2 = subprocess.run([sys.executable, str(ROOT / "tools" / "card_image.py"), d, img + ".times", "--size", "1024"],
                    capture_output=True, text=True)
check("3 timestamps outside 1970..2038 are written clamped and reported once in the summary",
      r2.returncode == 0 and r2.stdout.count("timestamp(s)") == 1
      and "note: 3 timestamp(s) in the archive lie outside 1970..2038" in r2.stdout, r2.stdout + r2.stderr)
check("an archive with none says nothing about timestamps", "timestamp(s)" not in r.stdout)
os.remove(img + ".times")
shutil.rmtree(d)

# ---- 3c. the macOS writer's run on a "disk": a file for /dev/rdisk4, made-up diskutil ----
FAKE = os.path.join(tmp, "rdisk4")
FAKE_SIZE = 1977614336                            # a "2 GB" card
ROOT_INFO = {"DeviceIdentifier": "disk3s1s1", "ParentWholeDisk": "disk3",
             "APFSPhysicalStores": [{"APFSPhysicalStore": "disk0s2"}]}


class World:
    """Everything write_card_mac touches outside itself. Every open of /dev/*
    lands on FAKE or fails the test; no diskutil is run."""

    def __init__(self, card=None, unmount_rc=0, fail_after=None, exc=None, fake_size=FAKE_SIZE, change=None,
                 stays_mounted=False):
        self.card = dict(dict(CARD, TotalSize=FAKE_SIZE, Size=FAKE_SIZE), **(card or {}))
        self.unmount_rc, self.fail_after, self.exc, self.change = unmount_rc, fail_after, exc, change
        self.stays_mounted = stays_mounted
        self.log, self.wrote, self.info_calls, self.part_polls = [], 0, 0, 0
        self.mounted, self.remounted = ["/Volumes/HOLIDAY PHOTOS"], False
        with open(FAKE, "wb") as f:               # the old card: something in the MBR, a GPT copy at the end
            f.truncate(fake_size)
            f.write(b"OLDCARD!" * 64)
            f.seek(fake_size - 512)
            f.write(b"EFI PART" + bytes(504))
        self.before = self.fingerprint()

    @staticmethod
    def fingerprint():
        """Size, first and last megabyte: where a card writer starts and ends.
        Every write also goes through Dev.write below, which counts it."""
        with open(FAKE, "rb") as f:
            size = f.seek(0, 2)
            f.seek(0)
            head = f.read(1 << 20)
            f.seek(size - (1 << 20))
            return size, hashlib.sha256(head + f.read()).hexdigest()

    def answer(self, rc, obj=b""):
        out = plistlib.dumps(obj) if isinstance(obj, dict) else obj
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=out[:0])

    def run(self, argv, **kw):
        if argv[0] == "sync":
            return types.SimpleNamespace(returncode=0)
        if argv[0] != "diskutil":
            return subprocess.run(argv, **kw)
        self.log.append(" ".join(argv[1:]))
        verb, tgt = argv[1], argv[-1]
        if verb == "info" and tgt == "/":
            return self.answer(0, ROOT_INFO)
        if verb == "info" and tgt in ("/dev/disk4s1", "/dev/disk4s2"):
            self.part_polls += 1                  # the new partitions show on the third look
            if self.wrote and self.part_polls > 4:
                if not self.remounted:
                    self.mounted, self.remounted = ["/Volumes/FISHBOOT"], True
                return self.answer(0, {"DeviceIdentifier": tgt[5:]})
            return self.answer(1)
        if verb == "info":
            self.info_calls += 1
            if self.change and self.info_calls > 1:
                self.card.update(self.change)
            return self.answer(0, self.card)
        if verb == "list" and "-plist" in argv:
            if self.stays_mounted and self.remounted:
                self.mounted = ["/Volumes/FISHBOOT"]
            part = {"DeviceIdentifier": "disk4s1"}
            if self.mounted:
                part["MountPoint"] = self.mounted[0]
            return self.answer(0, {"AllDisksAndPartitions": [{"DeviceIdentifier": "disk4", "Partitions": [part]}]})
        if verb == "list":
            return self.answer(0, "/dev/disk4 (external, physical):\n   0: FDisk_partition_scheme *2.0 GB disk4\n")
        if verb == "unmountDisk":
            if not self.unmount_rc:
                self.mounted = []
            return types.SimpleNamespace(returncode=self.unmount_rc, stdout="", stderr="busy" if self.unmount_rc else "")
        raise AssertionError("a diskutil verb that changes something, or is unknown: %r" % (argv,))

    def open(self, path, mode="r", *a, **kw):
        if not (isinstance(path, str) and path.startswith("/dev/")):
            return open(path, mode, *a, **kw)
        self.log.append("open %s %s" % (path, mode))
        if path != "/dev/rdisk4":
            raise AssertionError("opened a device other than the card: " + path)
        f = open(FAKE, mode, *a, **kw)
        if "+" not in mode:
            return f
        world = self

        class Dev:
            def __getattr__(self, n):
                return getattr(f, n)

            def write(self, b):
                if world.fail_after is not None and world.wrote >= world.fail_after:
                    raise world.exc or OSError(errno.EIO, "Input/output error")
                world.wrote += len(b)
                return f.write(b)
        return Dev()

    @property
    def opened_for_writing(self):
        return any(x.startswith("open /dev/rdisk4 r+") for x in self.log)

    @property
    def untouched(self):
        return self.wrote == 0 and self.fingerprint() == self.before


def drive(argv, stdin="", euid=0, env=None, **kw):
    """write_card_mac.main(argv) in a World. Returns (world, exit code or message, everything printed)."""
    wd = World(**kw)
    m = write_card_mac
    saved = (m.subprocess, m.os, m.time, getattr(m, "open", None), sys.stdin)
    m.subprocess = types.SimpleNamespace(run=wd.run, DEVNULL=subprocess.DEVNULL, PIPE=subprocess.PIPE)
    m.os = types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")})
    m.os.geteuid = lambda: euid
    m.os.environ = dict({k: v for k, v in os.environ.items() if k not in ("WRITE_CARD_DEBUG", "ALLOW_LARGE", "BOOT_BIN")},
                        **(env or {}))
    m.time = types.SimpleNamespace(time=m.time.time, sleep=lambda s: None)
    m.open = wd.open
    sys.stdin = io.StringIO(stdin)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = m.main(argv)
    except SystemExit as e:
        rc = e.code
        if isinstance(rc, str):
            out.write(rc + "\n")
            rc = 1
    except BaseException as e:                    # noqa: B902 - the point is to see what escapes
        rc = "ESCAPED %s: %s" % (type(e).__name__, e)
    finally:
        m.subprocess, m.os, m.time = saved[0], saved[1], saved[2]
        if saved[3] is None:
            del m.open
        else:
            m.open = saved[3]
        sys.stdin = saved[4]
    return wd, rc, out.getvalue()


no_bootgen = subprocess.run([sys.executable, str(ROOT / "firmware" / "scripts" / "check_bootbin.py"),
                             os.path.join(rel, "BOOT.bin")], capture_output=True).returncode == 4
if not no_bootgen:
    print("note  a bootgen is installed, which refuses the test release's random BOOT.bin: the disk run is skipped")
else:
    A = ["--from", rel, "/dev/disk4"]
    wd, rc, out = drive(["--dry-run"] + A)
    check("disk: --dry-run passes every check, shows the pre-flight's numbers, writes nothing",
          rc == 0 and wd.untouched and not wd.opened_for_writing and "nothing was written" in out
          and "the release fits" in out and "5127 of 114688 inodes" in out, out[-900:])
    wd, rc, out = drive(A, euid=501)
    check("disk: without root nothing is even looked at", rc == 1 and "needs root" in out and wd.log == [], out)
    for answer in ("", "y\n", "yes\n", "/dev/disk4\n", "DISK4\n", "disk40\n", "rdisk4\n"):
        wd, rc, out = drive(A, stdin=answer)
        check("disk: confirmation %r is not the disk's name: nothing written" % answer,
              rc == 1 and wd.untouched and not wd.opened_for_writing and "not confirmed - nothing was written" in out, out[-300:])
    wd, rc, out = drive(A, stdin="disk4\n", unmount_rc=1)
    check("disk: a card that will not unmount is not written", rc == 1 and wd.untouched and not wd.opened_for_writing
          and "could not be unmounted" in out and "Nothing was written" in out, out[-300:])
    wd, rc, out = drive(A, stdin="disk4\n", change={"TotalSize": 2 * FAKE_SIZE, "Size": 2 * FAKE_SIZE})
    check("disk: a card swapped for another size during the prompt is not written",
          rc == 1 and wd.untouched and not wd.opened_for_writing and "changed while you were asked" in out, out[-300:])
    wd, rc, out = drive(A, stdin="disk4\n", change={"Internal": True, "RemovableMedia": False, "Removable": False})
    check("disk: a name that means an internal disk after the prompt is not written",
          rc == 1 and wd.untouched and not wd.opened_for_writing and "INTERNAL" in out and "Nothing was written" in out, out[-500:])
    wd, rc, out = drive(A, stdin="disk4\n", fake_size=FAKE_SIZE + 4096 * 512)
    check("disk: what is open is not the size that was checked (asked of the descriptor): nothing written",
          rc == 1 and wd.untouched and wd.opened_for_writing and "not the same card" in out and "Nothing was written" in out,
          out[-400:])
    for relname, fill, word in (("dup2", CASES[0][1], "twice"), ("links2", CASES[8][1], "65000 hard links")):
        d = make_release(relname, fill)
        shutil.copyfile(os.path.join(rel, "SHA256SUMS"), os.path.join(d, "SHA256SUMS"))
        sums_ = [ln for ln in open(os.path.join(d, "SHA256SUMS")) if card_image.ROOTFS not in ln]
        sums_.append("%s  %s\n" % (card_image.sha256_file(os.path.join(d, card_image.ROOTFS)), card_image.ROOTFS))
        open(os.path.join(d, "SHA256SUMS"), "w").writelines(sums_)
        wd, rc, out = drive(["--from", d, "/dev/disk4"], stdin="disk4\n")
        check("disk: a release that cannot be written (%s) is refused BEFORE the prompt, the card untouched, "
              "the release blamed" % relname,
              rc == 1 and wd.untouched and not wd.opened_for_writing and word in out and "Type the disk name" not in out
              and "Nothing was written to /dev/disk4" in out and "not in the card" in out
              and not any(x.startswith("unmountDisk") for x in wd.log), out[-700:])
        shutil.rmtree(d)
    wd, rc, out = drive(A, stdin="disk4\n", fail_after=40 << 20)
    with open(FAKE, "rb") as f:
        mbr_sig = f.read(512)[510:]
    check("disk: an I/O error mid-write: says the card is INCOMPLETE and to write it again; it reads as blank",
          rc == 1 and "writing the card failed" in out and "Input/output error" in out and "INCOMPLETE" in out
          and "Write it again" in out and mbr_sig == b"\0\0" and "Traceback" not in out, out[-600:])
    wd, rc, out = drive(A, stdin="disk4\n", fail_after=40 << 20, exc=KeyboardInterrupt())
    check("disk: Ctrl-C mid-write: exit 130, says interrupted and INCOMPLETE, no traceback",
          rc == 130 and "interrupted" in out and "INCOMPLETE" in out and "Write it again" in out, (rc, out[-500:]))
    wd, rc, out = drive(A, stdin="disk4\n", fail_after=0, exc=KeyboardInterrupt())
    check("disk: Ctrl-C before the first byte reaches the card: says nothing was written",
          rc == 130 and wd.untouched and "Nothing was written to /dev/disk4" in out and "INCOMPLETE" not in out, (rc, out[-400:]))
    wd, rc, out = drive(A, stdin="disk4\n", fail_after=40 << 20, exc=struct.error("'H' format requires 0 <= number <= 65535"))
    check("disk: a bug mid-write (any exception): exit 1, says INCOMPLETE, names it, offers --debug",
          rc == 1 and "INCOMPLETE" in out and "struct.error" not in out.split("ERROR")[0] and "error: 'H' format" in out
          and "--debug" in out, (rc, out[-600:]))
    wd, rc, out = drive(["--debug"] + A, stdin="disk4\n", fail_after=40 << 20, exc=struct.error("boom"))
    check("disk: ...and with --debug the same message, then the exception itself for its traceback",
          str(rc).startswith("ESCAPED error: boom") and "INCOMPLETE" in out, (rc, out[-300:]))
    wd, rc, out = drive(A, stdin="disk4\n")
    with open(FAKE, "rb") as f:
        parts = card_image.read_mbr(f)
        f.seek(FAKE_SIZE - 512)
        last = f.read(8)
    check("disk: a good run writes, verifies, reads the boot files back and ends unmounted",
          rc == 0 and "read back identical" in out and "Done." in out and "take it out of the reader" in out
          and parts and parts[0][1:3] == (0x0C, 2048), (rc, out[-700:]))
    check("disk: ...it waited for both partitions to show, then unmounted until it stayed unmounted",
          wd.log.count("info -plist /dev/disk4s1") == 3 and wd.log[-1] == "list -plist /dev/disk4"
          and wd.log.count("unmountDisk /dev/disk4") >= 3 and wd.mounted == [], wd.log[-12:])
    check("disk: ...and the old card's backup GPT header is gone", last == bytes(8), last)
    wd, rc, out = drive(A, stdin="disk4\n", stays_mounted=True)
    check("disk: a card macOS keeps mounting is not called unmounted: the user is told to eject it",
          rc == 0 and "diskutil eject /dev/disk4" in out and "take it out of the reader" not in out, out[-300:])
    wd, rc, out = drive(A, stdin="disk4\n", card=dict(SLOT, VirtualOrPhysical="Unknown"))
    check("disk: a card in the built-in SD slot is written, and shown as such before the prompt",
          rc == 0 and "the built-in SD slot, removable" in out and "Done." in out, out[:1500])
    wd, rc, out = drive(["--dry-run"] + A, card={"TotalSize": 256060514304, "Size": 256060514304})
    check("disk: a 256 GB card passes --dry-run (pre-flight for 1908 block groups included)",
          rc == 0 and "every check passed" in out, out[-500:])
    os.remove(FAKE)

# ---- 4. the command line, as ./devkit hands it over --------------------------
MAC = [sys.executable, str(ROOT / "tools" / "write_card_mac.py")]


def run(*args, **env):
    e = dict(os.environ, **env)
    r = subprocess.run(MAC + list(args), capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr


rc, out = run()
check("no arguments: usage, exit 1", rc == 1 and "usage:" in out, out)
rc, out = run("--image", "a.img", "/dev/disk9")
check("a device AND --image is refused", rc == 1 and "give a device OR --image, not both" in out, out)
rc, out = run("--image", img)
check("--image over an existing file is refused", rc == 1 and "already exists" in out, out)
rc, out = run("--size", "4096", "/dev/disk9")
check("--size without --image is refused", rc == 1 and "--size only means something with --image" in out, out)
rc, out = run("--image", os.path.join(tmp, "s.img"), "--size", "100")
check("--image --size under 1 GB is refused", rc == 1 and "too small" in out, out)
rc, out = run("--frob")
check("an unknown option is refused", rc == 1 and "unknown option --frob" in out, out)
rc, out = run("--help")
check("--help prints the header and exits 0", rc == 0 and "--dry-run" in out and "DESTROYS" in out, out)

if sys.platform == "darwin":
    rc, out = run("--dry-run", "/dev/disk0")
    check("macOS: --dry-run on the internal disk is refused, without root", rc == 1 and "Refusing" in out, out)
    rc, out = run("--dry-run", "/dev/disk0s1")
    check("macOS: a partition is refused", rc == 1 and "is a partition" in out, out)
    rc, out = run("--dry-run", "/dev/disk987")
    check("macOS: a disk that does not exist is refused", rc == 1 and "knows no disk" in out, out)
    if os.geteuid() != 0:
        rc, out = run("/dev/disk987")
        check("macOS: writing a disk without root is refused before anything else", rc == 1 and "needs root" in out, out)
    # The whole image route, from a release folder, as `./devkit write-card --from DIR --image F`.
    # BOOT_BIN's check needs bootgen, which a Mac seldom has: SHA256SUMS vouches instead.
    mimg = os.path.join(tmp, "mac.img")
    no_bootgen = subprocess.run([sys.executable, str(ROOT / "firmware" / "scripts" / "check_bootbin.py"),
                                 os.path.join(rel, "BOOT.bin")], capture_output=True).returncode == 4
if sys.platform == "darwin" and no_bootgen:      # with a bootgen, the test release's random BOOT.bin is refused
    rc, out = run("--from", rel, "--dry-run", "--image", mimg)
    check("macOS: --dry-run --image passes every check and writes nothing",
          rc == 0 and "nothing was written" in out and not os.path.exists(mimg), out)
    rc, out = run("--from", rel, "--image", mimg, "--size", "1024")
    check("macOS: --from DIR --image FILE writes the image, without root",
          rc == 0 and os.path.getsize(mimg) == 1024 ** 3 and "the four boot files match" in out, out)
    rc, out = run("--from", bad_rel, "--image", os.path.join(tmp, "mac-bad.img"))
    check("macOS: a damaged release leaves no image behind",
          rc == 1 and not os.path.exists(os.path.join(tmp, "mac-bad.img")), out)

print("\n%d checks, %d failed" % (CHECKS, len(FAILURES)))
if not FAILURES and "--keep" not in sys.argv:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
else:
    print("kept: " + tmp)
sys.exit(1 if FAILURES else 0)
