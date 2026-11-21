#!/usr/bin/env python3
"""Make a small, synthetic "release" that exercises every hard case of the
card image writer, for tools/card_image.py and tools/check_card_image.py.

    # run from: the repo root (any OS)
    python3 tools/card_image_testdata.py OUT_DIR
    python3 tools/card_image.py OUT_DIR hard.img --size 1024
    sudo python3 tools/check_card_image.py hard.img OUT_DIR      # Linux

OUT_DIR gets BOOT.bin, uImage, devicetree.dtb, uEnv.txt (random bytes: this is
not firmware and boots nothing), debian-rootfs.tar.gz and SHA256SUMS.

A real Debian root has no device nodes, one hard link and no file past 30 MB,
so a writer can be wrong about all of those and still pass a check against the
release. The archive made here has what a root filesystem is allowed to have:

  - files of 0, 1, 4095, 4096 and 4097 bytes; exactly 12 blocks and one byte
    more (the first indirect block); exactly 12 + 1024 blocks and one byte more
    (the double-indirect block); 9 MB (several indirect blocks under it)
  - setuid, setgid and sticky bits; owners above 65535
  - symlinks of 1, 59, 60, 61, 255 and 4095 bytes (59 is the longest stored in
    the inode, 60 the first in a block), a dangling one, one to a directory
  - hard links: several to one file, one in another directory, one to a symlink
  - character and block devices, with small and with large major/minor numbers;
    a FIFO
  - a directory of 5000 entries (many directory blocks), names of 255 bytes,
    UTF-8 names, an empty directory, 40 directories nested, a file whose parent
    directories the archive never lists
  - timestamps at 0 and at 2^31 - 1

The contents are a fixed function of the path, so two runs give the same files.

    python3 tools/card_image_testdata.py --mutate KIND IMAGE

breaks a COPY of a good image in one small way that fsck does not see and a
read-only mount does not mind, to prove tools/check_card_image.py does:

  journal        the journal superblock's first-block field is zeroed: e2fsck -fn
                 is content and `mount -o ro,noload` works, but the kernel cannot
                 load the journal, so the board never mounts its root
  fat-label      the FAT volume label becomes FISHBOOX, in the root directory and
                 in the boot sector alike, so fsck.vfat sees nothing odd:
                 /etc/fstab's LABEL=FISHBOOT finds nothing
  fat-label-root the same in the root directory only (the one Linux reads)
  fat-label-bs   the same in the boot sector and its backup only
  short-name     BOOT.bin's 8.3 entry becomes BOOT~1.BIN, its long name kept and
                 still valid: Linux and macOS show BOOT.bin as before, the BootROM
                 does not find it
"""
import gzip
import hashlib
import io
import os
import struct
import sys
import tarfile

BS = 4096


def blob(tag, n):
    """n reproducible bytes for tag."""
    out = bytearray()
    i = 0
    while len(out) < n:
        out += hashlib.sha256(("%s/%d" % (tag, i)).encode()).digest()
        i += 1
    return bytes(out[:n])


def build_tar(path):
    raw = open(path, "wb")
    # mtime=0 in the gzip header: the file is then the same on every run.
    gz = gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=1)
    t = tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT)
    MT = 1760000000

    def add(name, type_=tarfile.REGTYPE, data=b"", mode=0o644, uid=0, gid=0, mtime=MT, link="", dev=None):
        m = tarfile.TarInfo("./" + name if name else "./")
        m.type, m.mode, m.uid, m.gid, m.mtime, m.linkname = type_, mode, uid, gid, mtime, link
        m.uname = m.gname = ""
        if dev:
            m.devmajor, m.devminor = dev
        if type_ == tarfile.REGTYPE:
            m.size = len(data)
            t.addfile(m, io.BytesIO(data))
        else:
            t.addfile(m)

    def d(name, mode=0o755, **kw):
        add(name, tarfile.DIRTYPE, mode=mode, **kw)

    d("")
    for name in ("bin", "etc", "usr", "usr/bin", "home", "var", "sizes", "links", "nodes", "names"):
        d(name)
    d("dev")                                   # one of the writer's own mkdir -p set, listed
    d("tmp", mode=0o1777)
    d("var/mail", mode=0o2775, gid=8)
    d("root", mode=0o700)
    d("home/far", mode=0o750, uid=100000, gid=70000)
    d("empty")
    d("epoch", mtime=0)

    # sizes: each boundary of the block map
    for n in (0, 1, BS - 1, BS, BS + 1, 12 * BS, 12 * BS + 1, (12 + 1024) * BS, (12 + 1024) * BS + 1,
              9 * 1024 * 1024 + 123):
        add("sizes/f%d" % n, data=blob("sizes/%d" % n, n))
    add("sizes/zeros", data=bytes(3 * BS + 7))

    # permissions and owners
    add("usr/bin/su", data=blob("su", 30000), mode=0o4755)
    add("usr/bin/wall", data=blob("wall", 20000), mode=0o2755, gid=5)
    add("usr/bin/both", data=blob("both", 100), mode=0o6755)
    add("etc/shadow", data=b"root:*:19000:0:99999:7:::\n", mode=0o640, gid=42)
    add("etc/noperm", data=b"x", mode=0)
    add("home/far/file", data=b"far away\n", uid=100000, gid=70000, mode=0o600)
    add("home/far/mixed", data=b"mixed\n", uid=65535, gid=65536)
    add("epoch/zero", data=b"1970\n", mtime=0)
    add("epoch/last", data=b"2038\n", mtime=2 ** 31 - 1)

    # symlinks
    add("links/target", data=b"the target\n")
    for n in (1, 59, 60, 61, 255, 4095):
        tgt = ("x" * n) if n < 20 else ("../" * (n // 3 - 4) + "links/target").rjust(n, "/")
        assert len(tgt) == n
        add("links/sym%d" % n, tarfile.SYMTYPE, link=tgt, mode=0o777)
    add("links/dangling", tarfile.SYMTYPE, link="/nonexistent/path", mode=0o777, uid=1000, gid=1000, mtime=5)
    add("links/todir", tarfile.SYMTYPE, link="../etc", mode=0o777)
    add("bin/sh", tarfile.SYMTYPE, link="../usr/bin/su", mode=0o777)

    # hard links
    add("links/hard1", tarfile.LNKTYPE, link="./links/target")
    add("links/hard2", tarfile.LNKTYPE, link="links/target")
    add("etc/hard3", tarfile.LNKTYPE, link="./links/target")
    add("links/hardsym", tarfile.LNKTYPE, link="./links/dangling", mode=0o777, uid=1000, gid=1000, mtime=5)
    add("usr/bin/su2", tarfile.LNKTYPE, link="./usr/bin/su", mode=0o4755)

    # device nodes
    add("nodes/null", tarfile.CHRTYPE, mode=0o666, dev=(1, 3))
    add("nodes/console", tarfile.CHRTYPE, mode=0o600, dev=(5, 1))
    add("nodes/sda", tarfile.BLKTYPE, mode=0o660, gid=6, dev=(8, 0))
    add("nodes/mmcblk0p2", tarfile.BLKTYPE, mode=0o660, gid=6, dev=(179, 2))
    add("nodes/bigminor", tarfile.CHRTYPE, mode=0o600, dev=(4, 70000))
    add("nodes/bigmajor", tarfile.BLKTYPE, mode=0o600, dev=(300, 5))
    add("nodes/bigboth", tarfile.CHRTYPE, mode=0o600, dev=(4000, 1000000))
    add("nodes/fifo", tarfile.FIFOTYPE, mode=0o622)
    add("nodes/hardnull", tarfile.LNKTYPE, link="./nodes/null", mode=0o666)

    # names and directories
    d("many")
    for i in range(5000):
        name = "many/%05d-%s" % (i, "n" * (i % 97))
        if i % 500 == 0:
            d(name)
        elif i % 7 == 0:
            add(name, tarfile.SYMTYPE, link="target-%d" % i, mode=0o777)
        else:
            add(name, data=blob(name, i % 300))
    add("names/" + "L" * 255, data=b"255\n")
    d("names/" + "D" * 255)
    add("names/" + "D" * 255 + "/" + "F" * 255, data=b"deep long\n")
    add("names/with space and 'quotes'", data=b"space\n")
    add("names/ümläut-日本語-\U0001F41F", data=b"utf-8\n")
    add("names/.hidden", data=b"hidden\n")
    add("names/trailing.", data=b"dot\n")
    deep = "deep"
    d(deep)
    for i in range(40):
        deep += "/level%02d" % i
        d(deep, mode=0o755 if i % 2 else 0o711)
    add(deep + "/bottom", data=b"bottom\n")
    add("implicit/parents/never/listed/file", data=b"implicit\n")

    t.close()
    gz.close()
    raw.close()


MUTATIONS = ("journal", "fat-label", "fat-label-root", "fat-label-bs", "short-name")


def mutate(image, kind):
    """Break image in place, as the header says. Returns a line saying what was changed."""
    with open(image, "r+b") as f:
        mbr = f.read(512)
        p1 = struct.unpack_from("<I", mbr, 446 + 8)[0] * 512
        p2 = struct.unpack_from("<I", mbr, 462 + 8)[0] * 512

        def at(off, n):
            f.seek(off)
            return bytearray(f.read(n))

        def put(off, data):
            f.seek(off)
            f.write(data)

        if kind == "journal":
            sb = at(p2 + 1024, 1024)
            block_size = 1024 << struct.unpack_from("<I", sb, 24)[0]
            first_journal_block, = struct.unpack_from("<I", sb, 268)      # s_jnl_blocks[0]
            off = p2 + first_journal_block * block_size
            jsb = at(off, 1024)
            assert struct.unpack_from(">I", jsb, 0)[0] == 0xC03B3998, "no journal superblock where the backup says"
            struct.pack_into(">I", jsb, 20, 0)                            # s_first
            put(off, jsb)
            return "journal superblock at block %d: s_first = 0" % first_journal_block
        bs = at(p1, 512)
        bps, spc, rsvd, nfats = struct.unpack_from("<HBHB", bs, 11)
        fat_sz, = struct.unpack_from("<I", bs, 36)
        root_cluster, = struct.unpack_from("<I", bs, 44)
        if kind in ("fat-label", "fat-label-bs"):
            backup, = struct.unpack_from("<H", bs, 50)
            for sector in (0, backup):
                b = at(p1 + sector * 512, 512)
                b[71:82] = b"FISHBOOX   "
                put(p1 + sector * 512, b)
            if kind == "fat-label-bs":
                return "boot sector and its backup: label FISHBOOX"
        root_off = p1 + (rsvd + nfats * fat_sz + (root_cluster - 2) * spc) * bps
        root = at(root_off, spc * bps)                                    # the first cluster holds them all
        for o in range(0, len(root), 32):
            e = root[o:o + 32]
            if kind in ("fat-label", "fat-label-root") and e[11] == 0x08:
                root[o:o + 11] = b"FISHBOOX   "
                put(root_off, root)
                return "root directory%s: label FISHBOOX" % (", boot sector and its backup" if kind == "fat-label" else "")
            if kind == "short-name" and e[11] != 0x0F and bytes(e[0:11]) == b"BOOT    BIN":
                new = b"BOOT~1  BIN"
                csum = 0
                for c in new:
                    csum = (((csum & 1) << 7) + (csum >> 1) + c) & 0xFF
                root[o:o + 11] = new
                k = o - 32
                while k >= 0 and root[k + 11] == 0x0F:                    # its long-name entries: keep them valid
                    root[k + 13] = csum
                    if root[k] & 0x40:
                        break
                    k -= 32
                put(root_off, root)
                return "root directory: BOOT.bin's 8.3 entry is now BOOT~1.BIN"
    sys.exit("nothing to mutate for %r in %s" % (kind, image))


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--mutate" and sys.argv[2] in MUTATIONS:
        print("mutated %s: %s" % (sys.argv[3], mutate(sys.argv[3], sys.argv[2])))
        return
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    # Sizes around a FAT cluster (512 bytes) boundary, and one over a megabyte.
    for name, n in (("BOOT.bin", 1500000 + 1), ("uImage", 512 * 4096), ("devicetree.dtb", 511), ("uEnv.txt", 513)):
        with open(os.path.join(out, name), "wb") as f:
            f.write(blob(name, n))
    build_tar(os.path.join(out, "debian-rootfs.tar.gz"))
    with open(os.path.join(out, "SHA256SUMS"), "w", newline="\n") as f:
        for name in ("BOOT.bin", "uImage", "devicetree.dtb", "uEnv.txt", "debian-rootfs.tar.gz"):
            with open(os.path.join(out, name), "rb") as g:
                f.write("%s  %s\n" % (hashlib.sha256(g.read()).hexdigest(), name))
    print("test release in %s" % out)


if __name__ == "__main__":
    main()
