#!/usr/bin/env python3
"""Build a Fishball7020 SD card - partition table, FAT32 boot partition and
ext3 root partition - into an image file or straight onto an open disk.

    # run from: the repo root (any OS; Python 3.8+, standard library only)
    python3 tools/card_image.py RELEASE_DIR card.img            # a NEW 2048 MB image
    python3 tools/card_image.py RELEASE_DIR card.img --size 4096

RELEASE_DIR holds BOOT.bin, uImage, devicetree.dtb, uEnv.txt and
debian-rootfs.tar.gz - a downloaded modern release. If it also holds
SHA256SUMS, every one of those listed there is checked against it first.

This is the writer behind `./devkit write-card` on macOS, where none of the
tools the Linux writer drives exist (sfdisk, mkfs.vfat, mkfs.ext4, loop
devices, an ext4 driver). tools/write_card_mac.py does the choosing and the
refusing of disks; this file only lays out bytes, and needs no root.

It is a port of the C# embedded in tools/write-card.cmd, which is the reference:
the same layout, the same allocation order, the same on-disk fields. One number
differs: this gives the root four times the inodes (one per 16 KiB, mke2fs's
default; the C# gives one per 64 KiB), so `apt install` does not run out of
inodes on a small card with space to spare.

  sector 0             MBR, two primary partitions
  p1  2048 .. +128MiB  FAT32 "FISHBOOT", type 0x0C, bootable
  p2  rest of card     Linux "fishroot", type 0x83

p2 is ext3 (ext2 + journal) rather than the Linux writer's ext4: it has no
extents and no checksums, so it can be written without e2fsprogs, and the
board's kernel mounts it with its ext4 driver (CONFIG_EXT4_USE_FOR_EXT2).
fstab finds both partitions by label.

Beyond the C#: device nodes, FIFOs and sockets are written (the C# refuses
them), and the directories the Linux writer makes after unpacking - boot,
mnt/jffs2, proc, sys, dev, run - are made here too if the archive lacks them.

Nothing is written before the whole release has been laid out once without
writing (plan_card, the pre-flight): an archive this writer or ext3 cannot hold
- a member listed twice, a hard link before its target, a name over 255 bytes,
more than 65000 links to one file - or a release too big for the card is
refused while the card is still as it was. The pre-flight runs the code that
writes, onto a target that keeps nothing, so the two cannot disagree.

Check an image with tools/check_card_image.py (Linux, root: it mounts it).
"""
import argparse
import hashlib
import os
import stat
import struct
import sys
import tarfile
import time
import uuid
import zlib

BOOT_FILES = ["BOOT.bin", "uImage", "devicetree.dtb", "uEnv.txt"]
ROOTFS = "debian-rootfs.tar.gz"
SECTOR = 512
BOOT_LBA = 2048
BOOT_SECTORS = 128 * 2048
ROOT_LBA = BOOT_LBA + BOOT_SECTORS
# What firmware-modern/debian/write-card.sh makes with mkdir -p after unpacking.
EXTRA_DIRS = ["boot", "mnt/jffs2", "proc", "sys", "dev", "run"]


class CardError(Exception):
    """Something the user can act on: a bad archive, a card too small."""


class ArchiveError(CardError):
    """The release itself cannot be written: its archive is damaged, or holds
    something this writer or ext3 cannot store. No other card will help."""


class TooSmallError(CardError):
    """The release does not fit a card of this size. need_bytes: roughly the
    smallest card that would hold it, when that is known."""
    need_bytes = 0


# ----------------------------------------------------------------------
# Where the bytes go: a disk or a file, as one seekable binary file object.
# Every write is recorded, so verify() can read it all back.
# ----------------------------------------------------------------------
class Target:
    PEND_MAX = 8 << 20

    def __init__(self, fileobj, size):
        self.f = fileobj
        self.size = size
        self.regions = []            # [offset, length], in write order, merged when contiguous
        self.hash = hashlib.sha256()
        self.pend = bytearray()
        self.pend_off = -1
        self.bytes_written = 0

    def write(self, off, data, verify=True):
        n = len(data)
        if n == 0:
            return
        if off % SECTOR or n % SECTOR:
            raise ValueError("unaligned write at %d" % off)
        if off < 0 or off + n > self.size:
            raise CardError("write past the end of the card at %d" % off)
        if verify:
            if self.regions and self.regions[-1][0] + self.regions[-1][1] == off:
                self.regions[-1][1] += n
            else:
                self.regions.append([off, n])
            self.hash.update(data)
        if self.pend_off >= 0 and off == self.pend_off + len(self.pend) and len(self.pend) < self.PEND_MAX:
            self.pend += data
            return
        self._flush_pending()
        self.pend_off = off
        self.pend += data

    def _flush_pending(self):
        if self.pend_off < 0:
            return
        self.f.seek(self.pend_off)
        view = memoryview(self.pend)
        done = 0
        while done < len(view):
            k = self.f.write(view[done:])
            if not k:
                raise OSError("short write at %d" % (self.pend_off + done))
            done += k
        view.release()
        self.bytes_written += done
        self.pend = bytearray()
        self.pend_off = -1

    def flush(self):
        self._flush_pending()
        self.f.flush()
        try:
            os.fsync(self.f.fileno())
        except (OSError, AttributeError, ValueError):
            pass                      # a raw device may not support it; the read-back is the check

    @property
    def verified_bytes(self):
        return sum(n for _, n in self.regions)

    def verify(self, progress=None, reader=None):
        """Read every recorded region back and compare a SHA-256 of it with the
        one taken while writing. reader: another file object to read through
        (a raw device reopened, so the read does not come from a cache)."""
        self.flush()
        r = reader or self.f
        h = hashlib.sha256()
        total, done = self.verified_bytes, 0
        for off, left in self.regions:
            r.seek(off)
            while left > 0:
                n = min(4 << 20, left)
                buf = r.read(n)
                if not buf:
                    raise OSError("short read while verifying at %d" % off)
                h.update(buf)
                left -= len(buf)
                off += len(buf)
                done += len(buf)
                if progress:
                    progress(done, total)
        return h.digest() == self.hash.digest()


class _DryTarget(Target):
    """A card that keeps nothing: every write is checked for alignment and
    bounds, counted, and dropped. plan_card() lays a whole card out onto one,
    with the code that lays it out onto a real one."""

    def __init__(self, size):
        Target.__init__(self, None, size)

    def write(self, off, data, verify=True):
        n = len(data)
        if off % SECTOR or n % SECTOR:
            raise ValueError("unaligned write at %d" % off)
        if off < 0 or off + n > self.size:
            raise CardError("write past the end of the card at %d" % off)
        self.bytes_written += n

    def flush(self):
        pass

    def verify(self, progress=None, reader=None):
        raise ValueError("nothing was written: this is the pre-flight pass")


# ----------------------------------------------------------------------
# FAT32 boot partition holding a handful of files in its root.
# ----------------------------------------------------------------------
class Fat32:
    BPS, SPC, RSVD, NFATS = 512, 1, 32, 2      # as mkfs.vfat -F 32 lays out 128 MB

    @classmethod
    def write(cls, t, part_lba, part_sectors, label, files, when=None):
        """files: [(name, bytes)]. when: time.struct_time, local."""
        BPS, SPC, RSVD, NFATS = cls.BPS, cls.SPC, cls.RSVD, cls.NFATS
        when = when or time.localtime()
        per = (256 * SPC + NFATS) // 2
        fat_sz = ((part_sectors - RSVD) + per - 1) // per
        data_start = RSVD + NFATS * fat_sz
        clusters = (part_sectors - data_start) // SPC
        if clusters < 65525:
            raise CardError("boot partition too small for FAT32")
        cb = BPS * SPC

        lab_name = label.upper().ljust(11)[:11].encode("ascii")
        fdate = (max(when.tm_year, 1980) - 1980) << 9 | when.tm_mon << 5 | when.tm_mday
        ftime = when.tm_hour << 11 | when.tm_min << 5 | min(when.tm_sec, 59) // 2

        # Directory entries first, without cluster numbers: their count decides
        # how many clusters the root directory takes, and the files follow it.
        shorts = set()
        plan = []                                  # (short name, long-name entries)
        n_entries = 1
        for name, _ in files:
            sn = cls._short_name(name, shorts)
            lfn = cls._long_name_entries(name, sn)
            plan.append((sn, lfn))
            n_entries += len(lfn) + 1
        root_clusters = max(1, (n_entries * 32 + cb - 1) // cb)

        fat = [0] * (clusters + 2)
        fat[0], fat[1] = 0x0FFFFFF8, 0x0FFFFFFF
        nxt = 2
        for c in range(root_clusters):
            fat[nxt + c] = 0x0FFFFFFF if c == root_clusters - 1 else nxt + c + 1
        nxt += root_clusters

        lab = bytearray(32)
        lab[0:11] = lab_name
        lab[11] = 0x08
        struct.pack_into("<HH", lab, 22, ftime, fdate)
        root = bytearray(lab)
        first = []
        for (name, content), (sn, lfn) in zip(files, plan):
            n = (len(content) + cb - 1) // cb
            if nxt + n > clusters + 2:
                raise CardError("boot files do not fit the boot partition")
            fc = nxt if n else 0
            first.append(fc)
            for c in range(n):
                fat[nxt + c] = 0x0FFFFFFF if c == n - 1 else nxt + c + 1
            nxt += n
            for e in lfn:
                root += e
            d = bytearray(32)
            d[0:11] = sn
            d[11] = 0x20
            struct.pack_into("<HHH", d, 14, ftime, fdate, fdate)
            struct.pack_into("<H", d, 20, fc >> 16)
            struct.pack_into("<HHHI", d, 22, ftime, fdate, fc & 0xFFFF, len(content))
            root += d
        root += bytes(root_clusters * cb - len(root))

        # reserved region: boot sector, FSInfo, sector 2, and their backups at 6..8
        bs = bytearray(BPS)
        bs[0:3] = b"\xEB\x58\x90"
        bs[3:11] = b"FISHBALL"
        struct.pack_into("<HBHB", bs, 11, BPS, SPC, RSVD, NFATS)
        bs[21] = 0xF8
        struct.pack_into("<HH", bs, 24, 63, 255)
        struct.pack_into("<III", bs, 28, part_lba, part_sectors, fat_sz)
        struct.pack_into("<IHH", bs, 44, 2, 1, 6)
        bs[64], bs[66] = 0x80, 0x29
        bs[67:71] = os.urandom(4)
        bs[71:82] = lab_name
        bs[82:90] = b"FAT32   "
        bs[510:512] = b"\x55\xAA"
        fsi = bytearray(BPS)
        struct.pack_into("<I", fsi, 0, 0x41615252)
        struct.pack_into("<III", fsi, 484, 0x61417272, clusters - (nxt - 2), nxt)
        struct.pack_into("<I", fsi, 508, 0xAA550000)
        s2 = bytearray(BPS)
        s2[510:512] = b"\x55\xAA"
        rsvd = bytearray(RSVD * BPS)
        for b in (0, 6):
            rsvd[b * BPS:(b + 3) * BPS] = bs + fsi + s2
        p = part_lba * BPS
        t.write(p, bytes(rsvd))

        fat_bytes = struct.pack("<%dI" % len(fat), *fat).ljust(fat_sz * BPS, b"\0")
        for k in range(NFATS):
            t.write(p + (RSVD + k * fat_sz) * BPS, fat_bytes)

        data = p + data_start * BPS
        t.write(data, bytes(root))
        for (name, content), fc in zip(files, first):
            if fc:
                pad = -len(content) % cb
                t.write(data + (fc - 2) * cb, content + bytes(pad))

    @staticmethod
    def _clean(s):
        return "".join(c for c in s.upper() if c.isascii() and (c.isalnum() or c in "_-"))

    @classmethod
    def _short_name(cls, name, used):
        b, e = name, ""
        dot = name.rfind(".")
        if dot > 0:
            b, e = name[:dot], name[dot + 1:]
        b, e = cls._clean(b), cls._clean(e)[:3]
        s = b[:6] + "~1" if len(b) > 8 else b
        k = 2
        while s + "." + e in used:
            s = b[:6] + "~%d" % k
            k += 1
        used.add(s + "." + e)
        return (s.ljust(8) + e.ljust(3)).encode("ascii")

    @staticmethod
    def _long_name_entries(name, short):
        csum = 0
        for c in short:
            csum = (((csum & 1) << 7) + (csum >> 1) + c) & 0xFF
        units = struct.unpack("<%dH" % (len(name.encode("utf-16-le")) // 2), name.encode("utf-16-le"))
        n = (len(units) + 12) // 13
        pos = (1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30)
        out = []
        for k in range(n, 0, -1):
            e = bytearray(32)
            e[0] = k | (0x40 if k == n else 0)
            e[11], e[13] = 0x0F, csum
            for j in range(13):
                ci = (k - 1) * 13 + j
                v = units[ci] if ci < len(units) else (0 if ci == len(units) else 0xFFFF)
                struct.pack_into("<H", e, pos[j], v)
            out.append(bytes(e))
        return out


def read_mbr(f):
    """[(bootable, type, lba, sectors)] for the non-empty MBR entries, or None."""
    f.seek(0)
    mbr = f.read(SECTOR)
    if len(mbr) < SECTOR or mbr[510:512] != b"\x55\xaa":
        return None
    parts = []
    for i in range(4):
        e = mbr[446 + 16 * i:462 + 16 * i]
        lba, count = struct.unpack_from("<II", e, 8)
        if e[4]:
            parts.append((e[0], e[4], lba, count))
    return parts


def fat32_read_root(f, part_off, want=None, limit=64 << 20):
    """{name: bytes} of the regular files in a FAT32 partition's root directory.

    Reads in whole sectors at sector-aligned offsets, so it works through a raw
    disk device. want: only these names (compared case-insensitively). Used to
    read the boot files back from a card after writing it, and BOOT.bin from the
    card about to be overwritten. Raises ValueError on anything that is not a
    FAT32 filesystem it can follow.
    """
    def rd(off, n):
        f.seek(off)
        buf = b""
        while len(buf) < n:
            k = f.read(n - len(buf))
            if not k:
                raise ValueError("short read at %d" % off)
            buf += k
        return buf

    bs = rd(part_off, SECTOR)
    if bs[510:512] != b"\x55\xaa":
        raise ValueError("no FAT boot sector")
    bps, spc, rsvd, nfats = struct.unpack_from("<HBHB", bs, 11)
    fat16_sz, = struct.unpack_from("<H", bs, 22)
    fat_sz, = struct.unpack_from("<I", bs, 36)
    root_cluster, = struct.unpack_from("<I", bs, 44)
    if bps != 512 or spc == 0 or fat16_sz != 0 or fat_sz == 0 or nfats == 0:
        raise ValueError("not FAT32")
    cb = bps * spc
    data = part_off + (rsvd + nfats * fat_sz) * bps
    fat = rd(part_off + rsvd * bps, min(fat_sz * bps, 64 << 20))

    def chain(c, max_bytes):
        out, seen = [], 0
        while 2 <= c < 0x0FFFFFF8:
            if c * 4 + 4 > len(fat) or seen > max_bytes:
                raise ValueError("bad cluster chain")
            out.append(c)
            seen += cb
            c = struct.unpack_from("<I", fat, c * 4)[0] & 0x0FFFFFFF
        return out

    def read_chain(c, size):
        cl = chain(c, size + cb)
        buf = bytearray()
        i = 0
        while i < len(cl):                      # contiguous runs in one read
            j = i
            while j + 1 < len(cl) and cl[j + 1] == cl[j] + 1 and (j - i + 1) * cb < (4 << 20):
                j += 1
            buf += rd(data + (cl[i] - 2) * cb, (j - i + 1) * cb)
            i = j + 1
        return bytes(buf[:size])

    wanted = None if want is None else {w.lower() for w in want}
    root = read_chain(root_cluster, 1 << 20)
    files, lfn = {}, []
    for o in range(0, len(root) - 31, 32):
        e = root[o:o + 32]
        if e[0] == 0:
            break
        if e[0] == 0xE5:
            lfn = []
            continue
        if e[11] == 0x0F:
            lfn.insert(0, e[1:11] + e[14:26] + e[28:32])
            continue
        attr = e[11]
        if lfn:
            name = b"".join(lfn).decode("utf-16-le", "replace").split("\0")[0]
        else:
            base, ext = e[0:8].decode("ascii", "replace").rstrip(), e[8:11].decode("ascii", "replace").rstrip()
            if e[12] & 0x08:
                base = base.lower()
            if e[12] & 0x10:
                ext = ext.lower()
            name = base + ("." + ext if ext else "")
        lfn = []
        if attr & 0x18:                         # volume label or directory
            continue
        size, = struct.unpack_from("<I", e, 28)
        fc = struct.unpack_from("<H", e, 20)[0] << 16 | struct.unpack_from("<H", e, 26)[0]
        if wanted is not None and name.lower() not in wanted:
            continue
        if size > limit:
            raise ValueError("%s is larger than expected" % name)
        files[name] = read_chain(fc, size) if size else b""
    return files


# ----------------------------------------------------------------------
# ext3 filesystem written directly from a tar archive.
# ----------------------------------------------------------------------
BS, BPG, ISIZE, FIRST_INO = 4096, 32768, 256, 11
PTRS = BS // 4
FT_REG, FT_DIR, FT_CHR, FT_BLK, FT_FIFO, FT_SOCK, FT_LNK = 1, 2, 3, 4, 5, 6, 7
_FT_OF = {stat.S_IFREG: FT_REG, stat.S_IFDIR: FT_DIR, stat.S_IFCHR: FT_CHR, stat.S_IFBLK: FT_BLK,
          stat.S_IFIFO: FT_FIFO, stat.S_IFSOCK: FT_SOCK, stat.S_IFLNK: FT_LNK}
_ZERO_BLOCK = bytes(BS)
# What the kernel's ext4 driver allows on this feature set (no dir_nlink): an
# inode's link count stops at 65000, so a file has at most 65000 names and a
# directory at most 64998 subdirectories. Measured on Linux 6.8, mounted as ext3
# and as ext4: link() and mkdir() fail with EMLINK exactly there.
LINK_MAX = 65000
# One inode per 16 KiB, mke2fs's default (inode_ratio = 16384): 8192 for each
# 128 MiB block group. Past 512 groups (64 GiB) half that, because the inode
# tables are written in full and a card that size has millions of inodes anyway.
INODES_PER_GROUP, INODES_PER_GROUP_BIG, BIG_GROUPS = 8192, 4096, 512
T32_MAX = 0x7FFFFFFF


def _t32(v):
    """A timestamp as ext3 stores it: seconds, 32 bits."""
    return max(0, min(int(v), T32_MAX))


class _Inode:
    __slots__ = ("mode", "uid", "gid", "links", "size", "blocks512", "mtime", "block", "fast")

    def __init__(self):
        self.mode = self.uid = self.gid = self.links = 0
        self.size = self.blocks512 = self.mtime = 0
        self.block = [0] * 15
        self.fast = None             # fast symlink target, stored in i_block


class _Dir:
    __slots__ = ("ino", "parent", "mode", "uid", "gid", "mtime", "extra_blocks", "entries", "subdirs", "children")

    def __init__(self):
        self.ino = 0
        self.parent = None
        self.mode = 0o755            # until the archive says otherwise
        self.uid = self.gid = 0
        self.mtime = 0
        self.extra_blocks = 0
        self.entries = []            # (name bytes, inode, file type)
        self.subdirs = {}
        self.children = {}


class Ext3:
    def __init__(self, target, part_offset, part_bytes, now=None, dry=False):
        self.t = target
        self.part = part_offset
        # dry: the pre-flight pass. Nothing differs but what running out does:
        # a real write stops at once, the pre-flight counts on to the end so it
        # can say how much is missing (short_blocks, short_inodes).
        self.dry = dry
        self.short_blocks = self.short_inodes = 0
        self.clamped = 0             # timestamps ext3's 32 bits could not hold
        self.now = _t32(time.time() if now is None else now)
        b = min(part_bytes // BS, 0xFFFFFFFF)
        g = (b + BPG - 1) // BPG
        self.ipg = INODES_PER_GROUP if g <= BIG_GROUPS else INODES_PER_GROUP_BIG
        self.itb = self.ipg * ISIZE // BS
        gdt = (g * 32 + BS - 1) // BS
        last = b - (g - 1) * BPG
        last_meta = (1 + gdt if self._has_super(g - 1) else 0) + 2 + self.itb
        if g > 1 and last < last_meta + 256:
            g -= 1
            b = g * BPG
        if g < 1 or b < 8192:
            raise TooSmallError("the card is too small for the root filesystem")
        self.blocks, self.groups = b, g
        self.gdt_blocks = (g * 32 + BS - 1) // BS
        # Each group starts with its metadata: [superblock + descriptors,] block
        # bitmap, inode bitmap, inode table. Everything after it is handed out
        # in order by one cursor, so "used" needs no bitmap: a block is used if
        # it is group metadata or below the cursor.
        self.grp_bb, self.grp_ib, self.grp_it, self.meta = [], [], [], []
        for i in range(g):
            m = i * BPG + (1 + self.gdt_blocks if self._has_super(i) else 0)
            self.grp_bb.append(m)
            self.grp_ib.append(m + 1)
            self.grp_it.append(m + 2)
            self.meta.append(m + 2 + self.itb - i * BPG)
        self.cursor = 0
        self.next_ino = FIRST_INO
        self.inodes = {}
        self.paths = {}
        self.uuid = uuid.uuid4().bytes
        self.journal_blocks = 0
        self.files = self.dirs = self.links = self.nodes = self.data_bytes = 0
        self.root = _Dir()
        self.root.ino, self.root.parent, self.root.mtime = 2, self.root, self.now
        self.inodes[2] = _Inode()

    @staticmethod
    def _has_super(g):
        if g <= 1:
            return True
        for p in (3, 5, 7):
            v = p
            while v < g:
                v *= p
            if v == g:
                return True
        return False

    def _alloc(self):
        c = self.cursor
        if c < self.blocks:
            g = c // BPG
            if c - g * BPG < self.meta[g]:
                c = g * BPG + self.meta[g]       # step over the group's metadata
        if c >= self.blocks:
            if self.dry:
                self.short_blocks += 1
                self.cursor = self.blocks
                return self.blocks - 1           # counted, and written nowhere
            raise TooSmallError("the card is too small for the root filesystem")
        self.cursor = c + 1
        return c

    def _new_ino(self):
        if self.next_ino > self.groups * self.ipg:
            if not self.dry:
                raise TooSmallError("out of inodes: the root filesystem has more files than a card this size is "
                                    "given inodes for (%d) - use a larger card or image" % (self.groups * self.ipg))
            self.short_inodes += 1
        self.next_ino += 1
        return self.next_ino - 1

    def _check_fits(self):
        """After everything has been allocated: raise TooSmallError if the
        pre-flight ran out of blocks or inodes, with the size that would do."""
        if not (self.short_blocks or self.short_inodes):
            return
        per_group = self.gdt_blocks + 4 + self.itb
        more = self.short_blocks + (self.short_blocks // (BPG - per_group) + 1) * per_group + 256
        need_blocks = self.blocks + more if self.short_blocks else self.blocks
        if self.short_inodes:
            need_blocks = max(need_blocks, -(-(self.next_ino - 1) // self.ipg) * BPG)
        why = []
        if self.short_blocks:
            why.append("%d MB more room than the card has" % -(-self.short_blocks * BS // 1000000))
        if self.short_inodes:
            why.append("%d inodes where a card this size is given %d"
                       % (self.next_ino - 1, self.groups * self.ipg))
        e = TooSmallError("the root filesystem needs " + " and ".join(why))
        e.need_bytes = -(-(self.part + need_blocks * BS) // (1 << 20)) << 20
        raise e

    def _time(self, v):
        """A member's timestamp as it will be stored, counting the ones that had to be moved."""
        t = _t32(v)
        if t != int(v):
            self.clamped += 1
        return t

    def _write_block(self, blk, data):
        self.t.write(self.part + blk * BS, data)

    def _write_ptrs(self, blk, ptrs):
        self._write_block(blk, struct.pack("<%dI" % PTRS, *ptrs))

    def _map_blocks(self, n, fill):
        """Allocate n data blocks plus the indirect blocks that map them, in file
        order (an indirect block just before the data it maps), calling fill(i)
        for the content of data block i. Returns (i_block[15], blocks used).

        The data blocks under one indirect block are held back until that
        indirect block is complete, so it and they go out in ascending order -
        one long sequential write on a card, rather than a seek back per file.
        """
        ib = [0] * 15
        total = 0
        if n > 12 + PTRS + PTRS * PTRS:
            raise ArchiveError("file too large for this writer (over 4 GB)")
        for i in range(min(n, 12)):
            b = self._alloc()
            ib[i] = b
            self._write_block(b, fill(i))
            total += 1
        i = 12
        dind = None
        while i < n:
            if i == 12 + PTRS:
                ib[13] = self._alloc()
                dind = [0] * PTRS
                total += 1
            ind_blk = self._alloc()
            total += 1
            if dind is None:
                ib[12] = ind_blk
            else:
                dind[(i - 12 - PTRS) // PTRS] = ind_blk
            k = min(PTRS, n - i)
            ptrs = [0] * PTRS
            held = []
            for j in range(k):
                ptrs[j] = self._alloc()
                held.append(fill(i + j))
            self._write_ptrs(ind_blk, ptrs)
            for j in range(k):
                self._write_block(ptrs[j], held[j])
            total += k
            i += k
        if dind is not None:
            self._write_ptrs(ib[13], dind)
        return ib, total

    def create_journal(self):
        """inode 8: the journal, all zeros except its superblock (big-endian, JBD2)."""
        b = self.blocks
        jb = 1024 if b < 32768 else 4096 if b < 262144 else 8192 if b < 524288 else 16384 if b < 4194304 else 32768
        self.journal_blocks = jb
        jsb = bytearray(BS)
        struct.pack_into(">II", jsb, 0, 0xC03B3998, 4)
        struct.pack_into(">IIII", jsb, 12, BS, jb, 1, 1)
        jsb[48:64] = self.uuid
        struct.pack_into(">I", jsb, 64, 1)
        jsb = bytes(jsb)
        ino = _Inode()
        ino.block, total = self._map_blocks(jb, lambda i: jsb if i == 0 else _ZERO_BLOCK)
        ino.mode, ino.links, ino.size, ino.blocks512, ino.mtime = stat.S_IFREG | 0o600, 1, jb * BS, total * 8, self.now
        self.inodes[8] = ino

    def create_lost_found(self):
        d = self._make_dir(self.root, "lost+found")
        d.mode, d.mtime, d.extra_blocks = 0o700, self.now, 3

    def _make_dir(self, parent, name, path=None):
        if len(parent.subdirs) >= LINK_MAX - 2:
            raise ArchiveError("more than %d directories in one directory, which ext3 cannot hold: %s is one too many"
                               % (LINK_MAX - 2, path or name))
        d = _Dir()
        d.ino, d.parent, d.mtime = self._new_ino(), parent, self.now
        parent.subdirs[name] = d
        self._add_entry(parent, name, d.ino, FT_DIR, path)
        self.inodes[d.ino] = _Inode()
        self.dirs += 1
        return d

    @staticmethod
    def _add_entry(parent, name, ino, ftype, path=None):
        if name in parent.children:
            # tar itself would let the later member replace the earlier one. Which
            # of the two the archive's maker meant is not this writer's to guess.
            raise ArchiveError("the archive lists %s twice. Unpacking it with tar would keep the later one; "
                               "this writer refuses instead of choosing" % (path or name))
        raw = name.encode("utf-8", "surrogateescape")
        if not raw or len(raw) > 255 or b"/" in raw or b"\0" in raw:
            raise ArchiveError("file name the filesystem cannot hold (%d bytes; the limit is 255): %r"
                               % (len(raw), path or name))
        parent.children[name] = ino
        parent.entries.append((raw, ino, ftype))

    @staticmethod
    def _clean(p):
        while p.startswith("./"):
            p = p[2:]
        p = p.strip("/")
        p = "" if p == "." else p
        parts = [x for x in p.split("/") if x not in ("", ".")]
        if ".." in parts:
            raise ArchiveError("archive path with '..' in it: " + p)
        return "/".join(parts)

    def _dir_for(self, path):
        d = self.root
        for name in path.split("/") if path else ():
            nxt = d.subdirs.get(name)
            if nxt is None:
                if name in d.children:
                    raise ArchiveError("archive uses %s as a directory and as a file" % path)
                nxt = self._make_dir(d, name, path)
            d = nxt
        return d

    def ensure_dir(self, path):
        """mkdir -p: make path (root-owned, 0755) unless the archive already did."""
        self._dir_for(self._clean(path))

    def add_from_tar(self, tar, progress=None):
        """tar: a tarfile.TarFile, read as a stream."""
        n = 0
        for m in tar:
            path = self._clean(m.name)
            parent_path, _, name = path.rpartition("/")
            perm = m.mode & 0o7777
            if m.isdir():
                d = self._dir_for(path)
                d.mode, d.uid, d.gid, d.mtime = perm, m.uid, m.gid, self._time(m.mtime)
                continue
            if not path:
                continue
            parent = self._dir_for(parent_path)
            if m.islnk():
                ino = self.paths.get(self._clean(m.linkname))
                if ino is None:
                    raise ArchiveError("%s is a hard link to %s, which the archive has not listed before it "
                                       "(or which is a directory)" % (path, m.linkname))
                node = self.inodes[ino]
                if node.links >= LINK_MAX:
                    raise ArchiveError("more than %d hard links to one file, which ext3 cannot hold: %s -> %s"
                                       % (LINK_MAX, path, m.linkname))
                node.links += 1
                self._add_entry(parent, name, ino, _FT_OF[stat.S_IFMT(node.mode)], path)
                self.paths[path] = ino
                continue
            node = _Inode()
            node.uid, node.gid, node.links, node.mtime = m.uid, m.gid, 1, self._time(m.mtime)
            if m.isreg():
                src = tar.extractfile(m)
                size = m.size
                got = [0]

                def fill(i, src=src, got=got):
                    buf = src.read(BS)
                    got[0] += len(buf)
                    return buf if len(buf) == BS else buf + bytes(BS - len(buf))
                node.block, total = self._map_blocks((size + BS - 1) // BS, fill)
                if got[0] != size:
                    raise ArchiveError("truncated tar archive at " + path)
                node.mode, node.size, node.blocks512 = stat.S_IFREG | perm, size, total * 8
                ftype = FT_REG
                self.files += 1
                self.data_bytes += size
            elif m.issym():
                target = m.linkname.encode("utf-8", "surrogateescape")
                node.mode, node.size = stat.S_IFLNK | 0o777, len(target)
                if len(target) < 60:
                    node.fast = target
                else:
                    if len(target) >= BS:
                        raise ArchiveError("symlink target too long (%d bytes; the limit is %d): %s"
                                           % (len(target), BS - 1, path))
                    blk = target + bytes(BS - len(target))
                    node.block, total = self._map_blocks(1, lambda i: blk)
                    node.blocks512 = total * 8
                ftype = FT_LNK
                self.links += 1
            elif m.ischr() or m.isblk():
                node.mode = (stat.S_IFCHR if m.ischr() else stat.S_IFBLK) | perm
                major, minor = m.devmajor, m.devminor
                if not (0 <= major < 1 << 12 and 0 <= minor < 1 << 20):
                    raise ArchiveError("device number %d:%d is more than Linux has: %s" % (major, minor, path))
                if major < 256 and minor < 256:
                    node.block[0] = major << 8 | minor                       # old encoding
                else:
                    node.block[1] = (minor & 0xFF) | major << 8 | (minor & ~0xFF) << 12
                ftype = FT_CHR if m.ischr() else FT_BLK
                self.nodes += 1
            elif m.isfifo():
                node.mode = stat.S_IFIFO | perm
                ftype = FT_FIFO
                self.nodes += 1
            else:
                raise ArchiveError("unsupported entry type %r for %s" % (m.type, path))
            ino = self._new_ino()
            self.inodes[ino] = node
            self._add_entry(parent, name, ino, ftype, path)
            self.paths[path] = ino
            n += 1
            if progress and not n & 63:
                progress(n)

    def _write_dirs(self, root):
        # Each directory, then its subdirectories in the order they were made:
        # the order a recursive walk gives, without its depth limit.
        stack = [root]
        while stack:
            d = stack.pop()
            self._write_dir(d)
            stack.extend(reversed(list(d.subdirs.values())))

    def _write_dir(self, d):
        # entries: ".", "..", then the children
        entries = [(b".", d.ino, FT_DIR), (b"..", d.parent.ino, FT_DIR)] + d.entries
        blks = []
        cur = bytearray(BS)
        pos, last = 0, -1
        for name, ino, ftype in entries:
            rec = (8 + len(name) + 3) & ~3
            if pos + rec > BS:
                struct.pack_into("<H", cur, last + 4, BS - last)
                blks.append(bytes(cur))
                cur = bytearray(BS)
                pos = 0
            struct.pack_into("<IHBB", cur, pos, ino, rec, len(name), ftype)
            cur[pos + 8:pos + 8 + len(name)] = name
            last = pos
            pos += rec
        struct.pack_into("<H", cur, last + 4, BS - last)
        blks.append(bytes(cur))
        empty = bytearray(BS)
        struct.pack_into("<H", empty, 4, BS)
        blks += [bytes(empty)] * d.extra_blocks

        node = self.inodes[d.ino]
        node.block, total = self._map_blocks(len(blks), lambda i: blks[i])
        node.mode, node.uid, node.gid, node.mtime = stat.S_IFDIR | d.mode, d.uid, d.gid, d.mtime
        node.links = 2 + len(d.subdirs)
        node.size, node.blocks512 = len(blks) * BS, total * 8

    def _used_in_group(self, g):
        """How many blocks of group g are in use: a prefix of the group."""
        start = g * BPG
        end = min(start + BPG, self.blocks)
        return max(self.meta[g], min(self.cursor, end) - start), end - start

    def finish(self, label):
        """Directories, inode tables, bitmaps, group descriptors, superblocks."""
        self._write_dirs(self.root)
        self._check_fits()

        ipg, itb, groups = self.ipg, self.itb, self.groups
        free_b, free_i, dirs_in = [], [], []
        empty_table = bytes(itb * BS)
        last_ino = self.next_ino - 1
        for g in range(groups):
            # block bitmap; bits past the end of the filesystem are set
            used, size = self._used_in_group(g)
            bits = (1 << used) - 1
            if size < BPG:
                bits |= ((1 << (BPG - size)) - 1) << size
            self._write_block(self.grp_bb[g], bits.to_bytes(BS, "little"))
            free_b.append(size - used)

            # inode table and inode bitmap; bits past ipg are set. Inodes are
            # handed out in order, so the used ones are 1 .. last_ino.
            used_i = max(0, min(ipg, last_ino - g * ipg))
            bits = ((1 << used_i) - 1) | (((1 << (BS * 8 - ipg)) - 1) << ipg)
            table = bytearray(itb * BS) if used_i else empty_table
            nd = 0
            for k in range(used_i):
                node = self.inodes.get(g * ipg + k + 1)
                if node is None:
                    continue
                if stat.S_IFMT(node.mode) == stat.S_IFDIR:
                    nd += 1
                self._put_inode(table, k * ISIZE, node)
            self._write_block(self.grp_ib[g], bits.to_bytes(BS, "little"))
            self.t.write(self.part + self.grp_it[g] * BS, bytes(table))
            free_i.append(ipg - used_i)
            dirs_in.append(nd)

        gdt = bytearray(self.gdt_blocks * BS)
        for g in range(groups):
            struct.pack_into("<IIIHHH", gdt, g * 32, self.grp_bb[g], self.grp_ib[g], self.grp_it[g],
                             free_b[g], free_i[g], dirs_in[g])

        j = self.inodes[8]
        hash_seed = uuid.uuid4().bytes
        for g in range(groups):
            if not self._has_super(g):
                continue
            sb = bytearray(1024)
            struct.pack_into("<IIIIIIII", sb, 0, groups * ipg, self.blocks, self.blocks // 100,
                             sum(free_b), sum(free_i), 0, 2, 2)
            struct.pack_into("<III", sb, 32, BPG, BPG, ipg)
            struct.pack_into("<I", sb, 48, self.now)
            struct.pack_into("<HHHH", sb, 54, 0xFFFF, 0xEF53, 1, 1)
            struct.pack_into("<I", sb, 64, self.now)
            struct.pack_into("<I", sb, 76, 1)
            struct.pack_into("<IHH", sb, 84, FIRST_INO, ISIZE, g)
            struct.pack_into("<III", sb, 92, 0x04 | 0x20,      # has_journal, dir_index
                             0x02,                               # filetype
                             0x01 | 0x02)                        # sparse_super, large_file
            sb[104:120] = self.uuid
            lab = label.encode("ascii")[:16]
            sb[120:120 + len(lab)] = lab
            struct.pack_into("<I", sb, 224, 8)
            sb[236:252] = hash_seed
            sb[252] = 1                                          # half_md4
            sb[253] = 1                                          # journal inode backed up below
            struct.pack_into("<I", sb, 264, self.now)
            struct.pack_into("<15I", sb, 268, *j.block)
            struct.pack_into("<II", sb, 268 + 15 * 4, 0, j.size)
            struct.pack_into("<HH", sb, 348, 32, 32)
            struct.pack_into("<I", sb, 352, 1)                   # signed directory hash
            first = bytearray(BS)
            o = 1024 if g == 0 else 0
            first[o:o + 1024] = sb
            at = g * BPG
            self._write_block(at, bytes(first))
            self.t.write(self.part + (at + 1) * BS, bytes(gdt))

    @staticmethod
    def _put_inode(t, o, n):
        mt = _t32(n.mtime)
        struct.pack_into("<HHIIII", t, o, n.mode, n.uid & 0xFFFF, n.size & 0xFFFFFFFF, mt, mt, mt)
        struct.pack_into("<HHI", t, o + 24, n.gid & 0xFFFF, n.links, n.blocks512)
        if n.fast is not None:
            t[o + 40:o + 40 + len(n.fast)] = n.fast
        else:
            struct.pack_into("<15I", t, o + 40, *n.block)
        if stat.S_IFMT(n.mode) == stat.S_IFREG:
            struct.pack_into("<I", t, o + 108, n.size >> 32)
        struct.pack_into("<HH", t, o + 120, (n.uid >> 16) & 0xFFFF, (n.gid >> 16) & 0xFFFF)
        struct.pack_into("<H", t, o + 128, 32)

    def free_bytes(self):
        free = 0
        for g in range(self.groups):
            used, size = self._used_in_group(g)
            free += size - used
        return free * BS


# ----------------------------------------------------------------------
# The whole card.
# ----------------------------------------------------------------------
class _Counting:
    """A read-only file wrapper that knows how far it has been read."""

    def __init__(self, f):
        self.f, self.pos = f, 0

    def read(self, n=-1):
        b = self.f.read(n)
        self.pos += len(b)
        return b


# The smallest card the layout itself can be put on, whatever the release: the
# boot partition and a 700 MiB root. Whether a given release fits a given card
# is plan_card()'s to say.
MIN_ROOT_BYTES = 700 * 1024 * 1024
MIN_CARD_BYTES = ROOT_LBA * SECTOR + MIN_ROOT_BYTES
# A GPT keeps a second copy of itself in the last 33 sectors of a disk. A card
# that once had one would keep it under the new MBR, for macOS or Linux to find.
GPT_TAIL_SECTORS = 33


def _lay_out(t, boot_files, rootfs_tar, say, progress, dry=False):
    """Everything write_card() puts on a card, in order, onto Target t. With
    dry (and a _DryTarget) the same statements run and nothing is kept: that is
    the pre-flight, and why it cannot disagree with the write."""
    sectors = t.size // SECTOR
    if sectors > 0xFFFFFFFF:
        raise CardError("card larger than 2 TB")
    root_sectors = (sectors - ROOT_LBA) // 8 * 8
    if root_sectors * SECTOR < MIN_ROOT_BYTES:
        e = TooSmallError("the card is too small: the layout needs at least %d MB" % -(-MIN_CARD_BYTES // 1000000))
        e.need_bytes = MIN_CARD_BYTES
        raise e

    # The old partition table goes first, so a write that is interrupted
    # leaves a card that is plainly blank rather than half-written. With it go
    # the rest of the first megabyte (a GPT's first copy) and the last 33
    # sectors (its second). The root partition may reach into those: whatever
    # the filesystem puts there is written later, over the zeros.
    t.write(0, bytes(SECTOR), verify=False)
    t.write(SECTOR, bytes(BOOT_LBA * SECTOR - SECTOR))
    t.write((sectors - GPT_TAIL_SECTORS) * SECTOR, bytes(GPT_TAIL_SECTORS * SECTOR), verify=False)

    say("boot partition (FAT32, 128 MB)")
    files = []
    for name, path in boot_files:
        with open(path, "rb") as f:
            files.append((name, f.read()))
    Fat32.write(t, BOOT_LBA, BOOT_SECTORS, "FISHBOOT", files)

    fs = Ext3(t, ROOT_LBA * SECTOR, root_sectors * SECTOR, dry=dry)
    say("root partition (ext3, %d MB, %d block groups)" % (fs.blocks * BS // 1000000, fs.groups))
    fs.create_journal()
    fs.create_lost_found()
    total = os.path.getsize(rootfs_tar)
    tty = progress and sys.stdout.isatty()
    doing = "checking the release" if dry else "unpacking Debian"
    with open(rootfs_tar, "rb") as raw:
        src = _Counting(raw)
        last = [0.0]

        def tick(n):
            if tty and time.time() - last[0] >= 0.5:
                last[0] = time.time()
                sys.stdout.write("\r    %s: %d%%  (%d files)   " % (doing, src.pos * 100 // max(total, 1), n))
                sys.stdout.flush()
        try:
            with tarfile.open(fileobj=src, mode="r|*") as tar:
                fs.add_from_tar(tar, tick)
        except (tarfile.TarError, EOFError, OSError, zlib.error) as e:
            if isinstance(e, OSError) and not isinstance(e, tarfile.TarError) and e.errno:
                raise                              # the card or the disk, not the archive
            raise ArchiveError("%s is damaged or not a tar archive: %s" % (os.path.basename(rootfs_tar), e))
        finally:
            if tty:
                sys.stdout.write("\r" + " " * 70 + "\r")
                sys.stdout.flush()
    for d in EXTRA_DIRS:
        fs.ensure_dir(d)
    say("writing directories, inode tables and superblocks")
    fs.finish("fishroot")

    # Partition table last: until it is written the card has no partitions.
    mbr = bytearray(SECTOR)
    mbr[440:444] = os.urandom(4)
    for o, status, ptype, lba, count in ((446, 0x80, 0x0C, BOOT_LBA, BOOT_SECTORS),
                                         (462, 0x00, 0x83, ROOT_LBA, root_sectors)):
        mbr[o] = status
        mbr[o + 1:o + 4] = b"\xFE\xFF\xFF"         # CHS unused: LBA only
        mbr[o + 4] = ptype
        mbr[o + 5:o + 8] = b"\xFE\xFF\xFF"
        struct.pack_into("<II", mbr, o + 8, lba, count)
    mbr[510:512] = b"\x55\xAA"
    t.write(0, bytes(mbr))
    t.flush()
    return fs


def _source_key(size, boot_files, rootfs_tar):
    """What a plan was made from: the card's size and each file's path, size and time."""
    key = [size]
    for path in [p for _, p in boot_files] + [rootfs_tar]:
        st = os.stat(path)
        key.append((os.path.abspath(path), st.st_size, st.st_mtime_ns))
    return tuple(key)


class Plan:
    """What plan_card() found: the card that write_card() would make."""

    def __init__(self, key, t, fs):
        self.key = key
        self.size = t.size
        self.write_bytes = t.bytes_written
        self.files, self.dirs, self.links, self.nodes = fs.files, fs.dirs, fs.links, fs.nodes
        self.data_bytes, self.clamped = fs.data_bytes, fs.clamped
        self.inodes_used, self.inodes_total = fs.next_ino - 1, fs.groups * fs.ipg
        self.root_bytes, self.free_bytes = fs.blocks * BS, fs.free_bytes()
        self.layout = _layout_of(fs)


def _layout_of(fs):
    """Where a pass over the archive ended up: the same for two passes that agree."""
    return (fs.groups, fs.blocks, fs.ipg, fs.next_ino, fs.cursor, fs.files, fs.dirs, fs.links, fs.nodes,
            fs.data_bytes, fs.clamped)


def summary(p):
    """The lines that describe a Plan, or an Ext3 just written."""
    if isinstance(p, Ext3):
        p = Plan(None, p.t, p)
    lines = ["%d files, %d directories, %d symlinks, %d device nodes, %.1f MB of file data; %.1f GB free"
             % (p.files, p.dirs, p.links, p.nodes, p.data_bytes / 1e6, p.free_bytes / 1e9),
             "%d of %d inodes used, %d free" % (p.inodes_used, p.inodes_total, p.inodes_total - p.inodes_used)]
    if p.clamped:
        lines.append("note: " + clamp_note(p.clamped))
    return lines


def clamp_note(n):
    return ("%d timestamp(s) in the archive lie outside 1970..2038, all this ext3 stores: "
            "written as the nearest end of that range" % n)


def plan_card(size, boot_files, rootfs_tar, progress=True):
    """The pre-flight: lay the whole card out for a card of size bytes without
    writing a byte, reading the archive once. Returns a Plan, or raises

      ArchiveError   the release cannot be written to any card: a damaged
                     archive, a member listed twice, a name or a link ext3
                     cannot hold, a member type this writer does not write
      TooSmallError  it does not fit a card this size (.need_bytes: one it would fit)

    Run it before anything is erased. write_card() runs it too if not handed
    its result, so no caller can skip it."""
    key = _source_key(size, boot_files, rootfs_tar)
    t = _DryTarget(size)
    try:
        fs = _lay_out(t, boot_files, rootfs_tar, lambda s: None, progress, dry=True)
    except (struct.error, OverflowError, RecursionError) as e:
        # A number in the archive that a field on the card cannot hold, and that
        # no check above names. Better said here than halfway down a card.
        raise ArchiveError("%s holds a value the card's filesystem has no room for (%s)"
                           % (os.path.basename(rootfs_tar), e))
    return Plan(key, t, fs)


def write_card(t, boot_files, rootfs_tar, say=print, progress=True, plan=None):
    """Write the whole card to Target t.

    boot_files: [(name on the card, path)] - BOOT.bin, uImage, devicetree.dtb,
    uEnv.txt, and anything else that belongs beside them.
    rootfs_tar: the root filesystem archive, .tar or .tar.gz.
    plan: plan_card()'s result for this card size and these files. Without one,
    or with one made from other files, the pre-flight is run here: either way
    nothing is written until the whole release has been laid out once.
    Returns the Ext3 object, for its counters.
    """
    if plan is None or plan.key != _source_key(t.size, boot_files, rootfs_tar):
        plan = plan_card(t.size, boot_files, rootfs_tar, progress)
    fs = _lay_out(t, boot_files, rootfs_tar, say, progress)
    if _layout_of(fs) != plan.layout:
        raise CardError("the release changed while it was being written: what is on the card is not what was checked")
    for line in summary(fs):
        say(line)
    return fs


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sums(path):
    """{file name: sha256} from a SHA256SUMS file."""
    sums = {}
    with open(path) as f:
        for line in f:
            p = line.split(None, 1)
            if len(p) == 2 and len(p[0]) == 64:
                sums[p[1].strip().lstrip("*")] = p[0].lower()
    return sums


def check_boot_readback(f, want, say=print):
    """Read the boot files back out of the FAT partition through f - found by
    the partition table, as the BootROM finds it - and compare their SHA-256
    with want {name: hex}. Returns the list of names that differ or are missing."""
    parts = read_mbr(f)
    if not parts or parts[0][1] not in (0x0B, 0x0C):
        return sorted(want)
    got = fat32_read_root(f, parts[0][2] * SECTOR, want=list(want))
    bad = []
    for name in want:
        h = hashlib.sha256(got[name]).hexdigest() if name in got else None
        say("  %-20s %s" % (name, (h or "MISSING")[:12] + ("" if h == want[name] else "   <- DIFFERS")))
        if h != want[name]:
            bad.append(name)
    return bad


def build_image(path, size_mb, boot_files, rootfs_tar, say=print, plan=None):
    """Create path - which must not exist - as a card image of size_mb MB, then
    read it back. The release is checked first (plan_card) and no file is made
    if it cannot be written; a run that fails later leaves no file behind."""
    size = size_mb * 1024 * 1024
    if plan is None or plan.key != _source_key(size, boot_files, rootfs_tar):
        plan = plan_card(size, boot_files, rootfs_tar)
    done = False
    f = open(path, "x+b", buffering=0)
    try:
        f.truncate(size)
        t = Target(f, size)
        write_card(t, boot_files, rootfs_tar, say, plan=plan)
        if not t.verify():
            raise CardError("what was read back from %s differs from what was written" % path)
        want = {name: sha256_file(p) for name, p in boot_files}
        say("boot files, read back from the image's FAT partition:")
        bad = check_boot_readback(f, want, say)
        if bad:
            raise CardError("boot file(s) read back wrong: " + ", ".join(bad))
        done = True
        return t
    finally:
        f.close()
        if not done:
            try:
                os.remove(path)
            except OSError:
                pass


def explain(e, target):
    """A CardError from plan_card() as a message for the user: what is wrong is
    the release or the size, not the card, and nothing was written to target."""
    if isinstance(e, TooSmallError):
        need = "" if not e.need_bytes else " It needs about %d MB or more." % (e.need_bytes >> 20)
        return "this release does not fit: %s.%s\n       Nothing was written to %s." % (e, need, target)
    if isinstance(e, ArchiveError):
        return ("this release cannot be written to a card: %s.\n"
                "       That is a fault in the release (its %s), not in the card: another card will not help.\n"
                "       Nothing was written to %s." % (e, ROOTFS, target))
    return "%s.\n       Nothing was written to %s." % (e, target)


def main():
    ap = argparse.ArgumentParser(description="Build a Fishball7020 SD card image from a release's files.",
                                 epilog="Run from the repo root. Writes a NEW file; never a disk.")
    ap.add_argument("release", help="directory with BOOT.bin uImage devicetree.dtb uEnv.txt debian-rootfs.tar.gz")
    ap.add_argument("image", help="the image file to create (must not exist)")
    ap.add_argument("--size", type=int, default=2048, metavar="MB", help="image size, default 2048")
    a = ap.parse_args()
    if os.path.lexists(a.image):
        sys.exit("ERROR: %s already exists - this writes a NEW file, it never overwrites" % a.image)
    if a.size < 1024:
        sys.exit("ERROR: --size %d is too small; a Debian root needs ~1 GB minimum" % a.size)
    need = BOOT_FILES + [ROOTFS]
    for n in need:
        if not os.path.isfile(os.path.join(a.release, n)):
            sys.exit("ERROR: %s is missing from %s" % (n, a.release))
    sums_path = os.path.join(a.release, "SHA256SUMS")
    if os.path.isfile(sums_path):
        sums = read_sums(sums_path)
        for n in need:
            if n in sums and sha256_file(os.path.join(a.release, n)) != sums[n]:
                sys.exit("ERROR: %s does not match SHA256SUMS - download it again" % n)
        print("note: %s match SHA256SUMS" % " ".join(n for n in need if n in sums))
    boot = [(n, os.path.join(a.release, n)) for n in BOOT_FILES]
    rootfs = os.path.join(a.release, ROOTFS)
    try:
        plan = plan_card(a.size * 1024 * 1024, boot, rootfs)
    except CardError as e:
        sys.exit("ERROR: " + explain(e, a.image))
    try:
        t0 = time.time()
        t = build_image(a.image, a.size, boot, rootfs, lambda s: print("  " + s), plan=plan)
    except CardError as e:
        sys.exit("ERROR: %s\n       No image was left behind." % e)
    print("OK: %s, %d MB; %d MB written and read back identical in %.0f s"
          % (a.image, a.size, t.verified_bytes >> 20, time.time() - t0))


if __name__ == "__main__":
    main()
