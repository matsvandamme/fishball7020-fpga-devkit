#!/usr/bin/env python3
"""Check an SD card image against the release files it was written from.

    # run from: the repo root, on Linux, as root (it loop-mounts the image)
    sudo python3 tools/check_card_image.py card.img RELEASE_DIR

Checks the partition table (128 MB FAT32 at sector 2048, Linux after it), runs
fsck.vfat and e2fsck on both partitions, then mounts them read-only and
compares every boot file and every entry of debian-rootfs.tar.gz - type,
permissions (setuid and setgid included), owner, timestamp, symlink target,
hardlink, device number and contents. Works on
a raw image and on a fixed VHD (a raw image with a 512-byte footer). Exit 0
only if everything matches.

Three things no fsck and no read-only mount shows are checked as well, each of
which stops a board that the checks above would pass:

  - the FAT volume label, in the boot sector and in the root directory: the
    board's /etc/fstab mounts LABEL=FISHBOOT
  - the 8.3 name of each boot file, read from the raw directory: the Zynq
    BootROM and the FSBL look for "BOOT    BIN" and read no long names
  - the journal: the root partition is mounted read-write (as ext3 and as
    ext4, whichever this kernel has), written to, unmounted and fsck'ed again.
    A journal the kernel cannot load mounts fine with ro,noload and not at all
    on the board. This is done on the copy of the partition made for fsck, after
    everything has been compared: the image itself is only ever read.

Written for tools/write-card.cmd, whose CI job writes a virtual disk on Windows
and hands it here; it checks tools/card_image.py's images (the macOS writer)
the same way, and a card made any other way just as well.
"""
import hashlib
import os
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile

BOOT_FILES = ["BOOT.bin", "uImage", "devicetree.dtb", "uEnv.txt"]
FAT_LABEL = b"FISHBOOT   "
# The 8.3 directory entry each boot file must have: what mkfs.vfat + cp on
# Linux, Windows itself, tools/write-card.cmd and tools/card_image.py all make.
SHORT_NAMES = {"BOOT.bin": b"BOOT    BIN", "uImage": b"UIMAGE     ", "devicetree.dtb": b"DEVICE~1DTB",
               "uEnv.txt": b"UENV    TXT"}


class Failed(Exception):
    """A check that did not hold."""


def fail(msg):
    raise Failed(msg)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_partitions(image):
    with open(image, "rb") as f:
        mbr = f.read(512)
    if mbr[510:512] != b"\x55\xaa":
        fail("no partition table")
    parts = []
    for i in range(4):
        e = mbr[446 + 16 * i: 462 + 16 * i]
        ptype = e[4]
        lba, count = struct.unpack_from("<II", e, 8)
        if ptype:
            parts.append((e[0], ptype, lba, count))
    return parts


# ------------------------------------------------------------------ FAT, raw
def fat_root_entries(path, offset=0):
    """(boot sector, [entry]) of the FAT32 filesystem at offset in path. Each
    entry of the root directory in use is a dict: short (the 11 raw bytes),
    attr, nt (the case byte), long (the name its long-name entries spell, or
    None), long_ok (they are in sequence and carry the short name's checksum)."""
    with open(path, "rb") as f:
        f.seek(offset)
        bs = f.read(512)
        if len(bs) < 512 or bs[510:512] != b"\x55\xaa":
            fail("boot partition: no FAT boot sector")
        bps, spc, rsvd, nfats = struct.unpack_from("<HBHB", bs, 11)
        fat_sz, = struct.unpack_from("<I", bs, 36)
        cluster, = struct.unpack_from("<I", bs, 44)
        if bps != 512 or not spc or not nfats or not fat_sz or struct.unpack_from("<H", bs, 22)[0]:
            fail("boot partition: not FAT32 with 512-byte sectors")
        data = offset + (rsvd + nfats * fat_sz) * bps
        raw, seen = b"", 0
        while 2 <= cluster < 0x0FFFFFF8 and seen < 4096:
            f.seek(data + (cluster - 2) * spc * bps)
            raw += f.read(spc * bps)
            f.seek(offset + rsvd * bps + cluster * 4)
            cluster = struct.unpack("<I", f.read(4))[0] & 0x0FFFFFFF
            seen += 1
    entries, pieces = [], []
    for o in range(0, len(raw) - 31, 32):
        e = raw[o:o + 32]
        if e[0] == 0:
            break
        if e[0] == 0xE5:
            pieces = []
            continue
        if e[11] == 0x0F:
            pieces.append((e[0], e[13], e[1:11] + e[14:26] + e[28:32]))
            continue
        long_name, long_ok = None, True
        if pieces:
            csum = 0
            for c in e[0:11]:
                csum = (((csum & 1) << 7) + (csum >> 1) + c) & 0xFF
            n = len(pieces)
            long_ok = (pieces[0][0] == (0x40 | n) and [p[0] & 0x3F for p in pieces] == list(range(n, 0, -1))
                       and all(p[1] == csum for p in pieces))
            long_name = b"".join(p[2] for p in reversed(pieces)).decode("utf-16-le", "replace").split("\0")[0]
        entries.append({"short": bytes(e[0:11]), "attr": e[11], "nt": e[12], "long": long_name, "long_ok": long_ok})
        pieces = []
    return bs, entries


def check_fat_names(path, offset=0, names=BOOT_FILES):
    """The volume label and the 8.3 names, from the raw boot sector and root
    directory at offset in path. Returns the list of what is wrong (empty: fine).
    Needs nothing but Python, so it runs wherever the image is."""
    bad = []
    bs, entries = fat_root_entries(path, offset)
    if bs[71:82] != FAT_LABEL:
        bad.append("boot sector volume label is %r, not %r" % (bs[71:82], FAT_LABEL))
    with open(path, "rb") as f:
        backup, = struct.unpack_from("<H", bs, 50)
        f.seek(offset + backup * 512)
        if backup and f.read(512)[71:82] != bs[71:82]:
            bad.append("backup boot sector carries another volume label than the boot sector")
    labels = [e["short"] for e in entries if e["attr"] & 0x08 and e["attr"] != 0x0F]
    if labels != [FAT_LABEL]:
        bad.append("root directory volume label is %s, not %r (fstab mounts LABEL=FISHBOOT)"
                   % (labels[0] if len(labels) == 1 else labels or "missing", FAT_LABEL))
    files = [e for e in entries if not e["attr"] & 0x18]
    shorts = [e["short"] for e in files]
    for s in shorts:
        if shorts.count(s) > 1:
            bad.append("two files share the 8.3 name %r" % s)
            break
    for e in files:
        if any(c < 0x21 and c != 0x20 or 0x61 <= c <= 0x7A or c in b'"*+,./:;<=>?[\\]|' for c in e["short"]) \
                or e["short"][0:1] == b" ":
            bad.append("8.3 name %r has a character FAT does not allow there" % e["short"])
        if not e["long_ok"]:
            bad.append("the long name of %r does not belong to it (sequence or checksum)" % e["short"])
    for name in names:
        want = SHORT_NAMES.get(name)
        if want is None:
            continue
        mine = [e for e in files if e["long"] == name
                or (e["long"] is None and e["short"] == want)]
        if not mine:
            bad.append("%s: no directory entry by that name" % name)
        elif mine[0]["short"] != want:
            bad.append("%s: its 8.3 name is %r, not %r%s" % (
                name, mine[0]["short"], want,
                " - the BootROM and the FSBL find BOOT.BIN by this name alone" if name == "BOOT.bin" else ""))
    return bad


# -------------------------------------------------------------------- checks
def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def check_image(image, rel):
    parts = read_partitions(image)
    print("partitions:", [(hex(t), lba, count) for _, t, lba, count in parts])
    if len(parts) != 2 or parts[0][1:4] != (0x0C, 2048, 262144) or parts[0][0] != 0x80:
        fail("p1 is not a bootable 128 MB FAT32 (0x0C) partition at sector 2048")
    if parts[1][1] != 0x83 or parts[1][2] != 2048 + 262144:
        fail("p2 is not a Linux (0x83) partition right after p1")

    sums = {}
    for line in open(os.path.join(rel, "SHA256SUMS")):
        h, name = line.split()
        sums[name.lstrip("*")] = h

    bad = check_fat_names(image, parts[0][2] * 512)
    if bad:
        for b in bad:
            print("  " + b)
        fail("boot partition: volume label or 8.3 names are wrong")
    print("boot partition: label FISHBOOT in boot sector and root directory; 8.3 names "
          + ", ".join(SHORT_NAMES[n].decode() for n in BOOT_FILES))

    with tempfile.TemporaryDirectory() as tmp:
        p1, p2 = os.path.join(tmp, "p1.img"), os.path.join(tmp, "p2.img")
        for path, (_, _, lba, count) in ((p1, parts[0]), (p2, parts[1])):
            subprocess.run(["dd", "if=" + image, "of=" + path, "bs=512", "skip=%d" % lba,
                            "count=%d" % count, "status=none", "conv=sparse"], check=True)
        for cmd in (["fsck.vfat", "-n", p1], ["e2fsck", "-fn", p2]):
            r = run(cmd)
            print("$ " + " ".join(cmd[:2]) + "\n" + (r.stdout.strip().splitlines() or [r.stderr.strip()])[-1])
            if r.returncode != 0 and not fsinfo_hint_only(cmd[0], r.stdout):
                print(r.stdout + r.stderr)
                fail(cmd[0] + " found problems")
        label = run(["e2label", p2]).stdout.strip()
        if label != "fishroot":
            fail("root label is %r, not 'fishroot' (fstab mounts it by label)" % label)
        if shutil.which("blkid"):                # what the board's mount -L sees
            label = run(["blkid", "-p", "-o", "value", "-s", "LABEL", p1]).stdout.strip()
            if label != "FISHBOOT":
                fail("blkid reads the boot partition's label as %r, not 'FISHBOOT'" % label)

        m1, m2 = os.path.join(tmp, "m1"), os.path.join(tmp, "m2")
        os.mkdir(m1)
        os.mkdir(m2)
        subprocess.run(["mount", "-o", "ro,loop", p1, m1], check=True)
        try:
            subprocess.run(["mount", "-o", "ro,loop,noload", p2, m2], check=True)
        except subprocess.CalledProcessError:
            subprocess.run(["umount", m1])
            raise
        try:
            for name in BOOT_FILES:
                if sha(open(os.path.join(m1, name), "rb").read()) != sums[name]:
                    fail("boot partition: %s differs from SHA256SUMS" % name)
            print("boot partition: %s match SHA256SUMS" % ", ".join(BOOT_FILES))
            check_root(m2, os.path.join(rel, "debian-rootfs.tar.gz"))
            st = os.statvfs(m2)
            print("root partition: %d inodes, %d free; %d MB free"
                  % (st.f_files, st.f_ffree, st.f_bfree * st.f_frsize // 1000000))
        finally:
            subprocess.run(["umount", m1, m2])
        check_writable(p2, m2)


def check_writable(p2, mnt):
    """Mount the copy of the root partition read-write - which loads the
    journal, as the board does - write to it, unmount, fsck. As ext3 and as
    ext4 where this kernel has both drivers; the ext4 driver is the board's."""
    known = open("/proc/filesystems").read().split()
    tried = 0
    for fstype in ("ext3", "ext4"):
        r = run(["mount", "-t", fstype, "-o", "loop,rw", p2, mnt])
        if r.returncode != 0:
            if fstype not in known and "unknown filesystem type" in r.stderr:
                print("read-write mount as %s: this kernel has no %s driver, skipped" % (fstype, fstype))
                continue
            print(r.stdout + r.stderr)
            fail("the root partition does not mount read-write as %s: on the board that is a root that "
                 "never mounts. Its journal is the first suspect (dmesg says which)" % fstype)
        tried += 1
        try:
            d = os.path.join(mnt, "check-card-image-" + fstype)
            os.mkdir(d)
            for i in range(200):
                with open(os.path.join(d, "f%d" % i), "w") as f:
                    f.write("x" * i)
            with open(os.path.join(d, "big"), "wb") as f:
                f.write(os.urandom(1 << 20) * 8)             # past the direct blocks, into the journal's work
                f.flush()
                os.fsync(f.fileno())
            for i in range(0, 200, 2):
                os.remove(os.path.join(d, "f%d" % i))
            os.symlink("big", os.path.join(d, "link"))
        except OSError as e:
            subprocess.run(["umount", mnt])
            fail("writing to the root partition mounted as %s failed: %s" % (fstype, e))
        if subprocess.run(["umount", mnt]).returncode != 0:
            fail("the root partition would not unmount after being written as " + fstype)
        r = run(["e2fsck", "-fn", p2])
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            fail("e2fsck found problems after the root partition was written to as " + fstype)
        print("read-write mount as %s: journal loaded, 201 files written, unmounted, e2fsck clean" % fstype)
    if not tried:
        fail("the root partition could be mounted read-write with no driver this kernel has")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    try:
        check_image(sys.argv[1], sys.argv[2])
    except Failed as e:
        print("FAIL: %s" % e)
        sys.exit(1)
    print("PASS")


def fsinfo_hint_only(tool, out):
    """True if fsck.vfat's only complaint is FSInfo's free-cluster count.

    That count is a hint the FAT32 specification lets go stale, and Windows
    does: a card Windows has mounted (it adds "System Volume Information")
    often reads one or two clusters off. Nothing that boots the board reads it.
    """
    if tool != "fsck.vfat":
        return False
    problems = [l for l in out.splitlines()
                if l.strip() and not l.startswith(("fsck.fat ", "/", "Leaving filesystem"))
                and "Auto-correcting" not in l]
    if problems and all(l.startswith("Free cluster summary wrong") for l in problems):
        print("  (only FSInfo's free-cluster hint is stale, as Windows leaves it: not an error)")
        return True
    return False


# Made by the writers themselves, as mount points, when the archive lacks them.
WRITER_DIRS = {"boot", "mnt", "mnt/jffs2", "proc", "sys", "dev", "run"}


def norm(name):
    """A member name as a path below the root: no leading "./" or "/", no
    empty or "." components. "a//b/./c" and "./a/b/c" are the same file."""
    return "/".join(x for x in name.split("/") if x not in ("", "."))


def check_root(root, tgz):
    t = tarfile.open(tgz)
    bad, n, seen = [], 0, {""}
    special = {"setuid/setgid": 0, "device nodes": 0, "FIFOs": 0, "symlinks": 0, "hard links": 0}
    dirs = {}                                    # path -> the LAST member that lists it
    for m in t:
        p = norm(m.name)
        fp = os.path.join(root, p)
        n += 1
        seen.add(p)
        # A parent directory the archive never lists is still made, by any writer.
        q = os.path.dirname(p)
        while q and q not in seen:
            seen.add(q)
            q = os.path.dirname(q)
        if m.isdir():
            # An archive may list a directory more than once (tar appends do);
            # the last listing is the one that stands, so compare with that.
            dirs[p] = m
            continue
        bad += check_member(root, p, fp, m, t, special)
    for p, m in dirs.items():
        bad += check_member(root, p, os.path.join(root, p), m, t, special)
    extra = []
    for d, ds, fs in os.walk(root):
        for x in ds + fs:
            rel = os.path.relpath(os.path.join(d, x), root)
            if rel in seen or rel == "lost+found":
                continue
            if rel in WRITER_DIRS and x in ds and not os.listdir(os.path.join(d, x)):
                continue
            if rel == "mnt" and os.listdir(os.path.join(d, x)) == ["jffs2"]:
                continue
            extra.append(rel)
    print("root partition: %d archive entries checked, %d mismatches, %d extra" % (n, len(bad), len(extra)))
    print("  of which " + ", ".join("%d %s" % (v, k) for k, v in special.items()))
    if bad or extra:
        for b in (bad + ["extra " + e for e in extra])[:20]:
            print("  " + b)
        fail("root partition differs from debian-rootfs.tar.gz")


def check_member(root, p, fp, m, t, special):
    """What differs between archive member m and the file fp on the card."""
    bad = []
    try:
        st = os.lstat(fp)
    except FileNotFoundError:
        return ["missing " + p]
    if m.issym():
        special["symlinks"] += 1
        if not stat.S_ISLNK(st.st_mode) or os.readlink(fp) != m.linkname:
            bad.append("symlink " + p)
        if (st.st_uid, st.st_gid) != (m.uid, m.gid):
            bad.append("owner " + p)
        if int(st.st_mtime) != int(m.mtime):
            bad.append("mtime " + p)
        return bad
    want = (stat.S_IFDIR if m.isdir() else stat.S_IFREG if m.isreg() else stat.S_IFCHR if m.ischr()
            else stat.S_IFBLK if m.isblk() else stat.S_IFIFO if m.isfifo() else None)
    if want is not None and stat.S_IFMT(st.st_mode) != want:
        bad.append("type " + p)
    if stat.S_IMODE(st.st_mode) != m.mode & 0o7777:
        bad.append("mode " + p)
    if (st.st_uid, st.st_gid) != (m.uid, m.gid):
        bad.append("owner " + p)
    # mkdir -p mnt/jffs2 by the Linux writer gives mnt the time of writing.
    if int(st.st_mtime) != int(m.mtime) and not (p == "mnt" and m.isdir()):
        bad.append("mtime " + p)
    if m.isreg():
        if m.mode & 0o6000:
            special["setuid/setgid"] += 1
        if st.st_size != m.size or sha(open(fp, "rb").read()) != sha(t.extractfile(m).read()):
            bad.append("content " + p)
    if m.ischr() or m.isblk():
        special["device nodes"] += 1
        if (os.major(st.st_rdev), os.minor(st.st_rdev)) != (m.devmajor, m.devminor):
            bad.append("device number " + p)
    if m.isfifo():
        special["FIFOs"] += 1
    if m.islnk():
        special["hard links"] += 1
        try:
            if os.lstat(os.path.join(root, norm(m.linkname))).st_ino != st.st_ino:
                bad.append("hardlink " + p)
        except FileNotFoundError:
            bad.append("hardlink " + p)
    return bad


if __name__ == "__main__":
    main()
