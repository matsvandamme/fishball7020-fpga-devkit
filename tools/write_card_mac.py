#!/usr/bin/env python3
"""Put the Debian root and the boot files onto an SD card, on macOS.

    # run from: the repo root
    sudo ./devkit write-card --from "$HOME/Downloads/release" /dev/diskN
    ./devkit write-card --from "$HOME/Downloads/release" --dry-run /dev/diskN   # the plan; writes nothing
    ./devkit write-card --from "$HOME/Downloads/release" --image card.img       # a NEW image file, no root
    ./devkit write-card --image card.img --size 4096                            # from this repo's own build

`diskutil list external physical` names the card's disk. ./devkit write-card runs
this file on a Mac and firmware-modern/debian/write-card.sh on Linux; the
options are the same.

--from DIR takes BOOT.bin, uImage, devicetree.dtb, uEnv.txt and - unlike on
Linux, where the root is always this repo's own build - debian-rootfs.tar.gz
from DIR, a downloaded modern release. If DIR has the release's SHA256SUMS,
every one of those listed there is checked against it first. Without --from,
the boot files come from firmware-modern/output/ and the root from
firmware-modern/debian/rootfs.tar, or failing that from
firmware-modern/output/debian-rootfs.tar.gz.

--image FILE writes the same layout into a new file, 2048 MB unless --size says
otherwise. It needs no root, and it does NOT relax any check on a real disk.

THIS DESTROYS EVERYTHING ON THE TARGET. It refuses any disk that macOS does not
report as external AND removable, anything that is a partition rather than a
whole disk, a disk image, the disk macOS runs from, and anything too small for
the layout or over 280 GB (ALLOW_LARGE=1 lifts that last one, as in
`sudo ALLOW_LARGE=1 ./devkit write-card ...`; the Linux writer has no such
limit). One internal disk is written: a card in the Mac's own SD slot, which
macOS reports as protocol "Secure Digital" with removable media.

Before it asks anything it lays the whole release out once without writing
(card_image.plan_card): an archive that cannot be written, or a release that
does not fit this card, is refused while the card is still untouched. It prints
what it is about to erase, then makes you type the disk's name. After writing
it reads back every byte it wrote and compares, then reads the four boot files
back out of the FAT partition and compares their SHA-256.

A write that fails or is interrupted leaves the card INCOMPLETE - its partition
table is erased first, so it reads as blank - and it must be written again.
--debug (or WRITE_CARD_DEBUG=1) shows the Python traceback of an unexpected error.

A Mac has none of the tools the Linux writer drives and cannot write ext4, so
the card is laid out by tools/card_image.py instead - the same card as
tools/write-card.cmd makes on Windows, but with four times the inodes:

  p1   128 MB  FAT32  FISHBOOT   BOOT.bin  uImage  devicetree.dtb  uEnv.txt
  p2   rest    ext3   fishroot   the Debian root (the kernel mounts it with its
                                 ext4 driver; on Linux the writer makes ext4)
"""
import hashlib
import os
import plistlib
import re
import stat
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FW = os.path.join(REPO, "firmware-modern")
DEBIAN = os.path.join(FW, "debian")
sys.path.insert(0, HERE)
import card_image  # noqa: E402

# The smallest card the layout goes on at all. Whether THIS release fits THIS
# card is worked out from the release itself, before anything is erased
# (card_image.plan_card): a nominal "1 GB" card is 953 MiB and is not refused here.
MIN_BYTES = card_image.MIN_CARD_BYTES
# Cards sold as 256 GB are a little over 256 * 10^9 bytes (256 060 514 304 is
# common), and nothing rules out one of 256 GiB. Past this it is more likely a
# USB disk that calls itself removable than a card for this board. The Linux
# writer has no such limit, hence the way round it: ALLOW_LARGE=1.
MAX_BYTES = 280 * 10 ** 9
USAGE = """usage: sudo ./devkit write-card [--dry-run] [--debug] [--from DIR] /dev/diskN
       ./devkit write-card [--dry-run] [--debug] [--from DIR] --image NEW_FILE [--size MB]"""
# <sys/disk.h>: _IOR('d', 24, uint32_t) and _IOR('d', 25, uint64_t)
DKIOCGETBLOCKSIZE, DKIOCGETBLOCKCOUNT = 0x40046418, 0x40086419


def die(msg):
    sys.exit("ERROR: " + msg)


def note(msg):
    print("note: " + msg)


def warn(msg):
    print("WARNING: " + msg, file=sys.stderr)


# ------------------------------------------------------------------ diskutil
def diskutil_plist(*args):
    """`diskutil ARGS -plist` parsed, or None if diskutil refuses. Read-only uses only."""
    try:
        r = subprocess.run(["diskutil"] + list(args), capture_output=True)
    except FileNotFoundError:
        die("diskutil not found - this is the macOS card writer (on Linux: firmware-modern/debian/write-card.sh)")
    if r.returncode != 0:
        return None
    try:
        return plistlib.loads(r.stdout)
    except Exception:
        return None


def boot_disks():
    """The whole disks macOS itself is on: the APFS container holding / and the
    physical disk(s) under it. Raises if that cannot be worked out - not knowing
    which disk the system is on is a reason to stop, not to carry on."""
    info = diskutil_plist("info", "-plist", "/")
    if not info or not info.get("ParentWholeDisk"):
        raise RuntimeError("diskutil would not say which disk macOS runs from")
    disks = {info["ParentWholeDisk"]}
    for store in info.get("APFSPhysicalStores") or []:
        ident = store.get("APFSPhysicalStore", "")
        m = re.match(r"^(disk\d+)", ident)
        if not m:
            raise RuntimeError("unexpected APFS physical store %r" % ident)
        disks.add(m.group(1))
    return disks


def is_sd_slot(info):
    """A card in the Mac's built-in SD slot: the one internal disk that is a
    legitimate target. macOS reports it as internal, protocol "Secure Digital",
    with removable media; an internal SSD or NVMe disk is neither of the last two."""
    return (info.get("Internal") is True and info.get("BusProtocol") == "Secure Digital"
            and info.get("RemovableMedia") is True)


def check_disk(dev, info, system_disks, mounts, allow_large=False):
    """Every reason not to write to this disk. info: `diskutil info -plist DEV`;
    system_disks: boot_disks(); mounts: the mount points of the disk's own
    volumes; allow_large: ALLOW_LARGE=1 was given. Returns (name, bytes);
    raises ValueError with the refusal.

    Kept free of side effects so each refusal can be tested with a made-up
    plist, without the disk it describes."""
    m = re.match(r"^/dev/r?(disk\d+)(s\d+.*)?$", dev)
    if not m:
        raise ValueError("%s is not a macOS disk - pass /dev/diskN (see: diskutil list external physical)" % dev)
    name = m.group(1)
    if m.group(2):
        raise ValueError("%s is a partition, not a disk - pass the whole disk, /dev/%s" % (dev, name))
    if info is None:
        raise ValueError("diskutil knows no disk %s - is the card in the reader? (diskutil list external physical)" % dev)
    if info.get("DeviceIdentifier") != name:
        raise ValueError("diskutil describes %r when asked about %s" % (info.get("DeviceIdentifier"), name))
    if info.get("WholeDisk") is not True or info.get("ParentWholeDisk", name) != name:
        raise ValueError("%s is not a whole disk" % dev)
    if name in system_disks:
        raise ValueError("%s is the disk macOS runs from. Refusing." % dev)
    for mp in mounts:
        if mp == "/" or mp.startswith("/System/") or mp in ("/private/var/vm", "/usr", "/var", "/Users"):
            raise ValueError("%s holds a volume mounted at %s - that is part of the running system. Refusing." % (dev, mp))
    if info.get("Internal") is not False and not is_sd_slot(info):
        raise ValueError("%s is an INTERNAL disk (protocol %s). Refusing. This is the check that stops this script "
                         "eating a system disk.\n"
                         "       A card in the Mac's built-in SD slot is written only if macOS reports it as protocol\n"
                         "       'Secure Digital' with removable media, and it does not report this disk so: put the\n"
                         "       card in a USB card reader instead." % (dev, info.get("BusProtocol") or "unknown"))
    # "Virtual" is the refusal. Anything else passes: macOS has been seen to
    # answer "Unknown" for a real card reader, and every other check still applies.
    if info.get("VirtualOrPhysical") == "Virtual" or info.get("BusProtocol") == "Disk Image":
        raise ValueError("%s is not a physical disk (a disk image, or a volume synthesised from another disk). "
                         "Refusing; for an image file use --image." % dev)
    if info.get("APFSContainerReference") or info.get("APFSPhysicalStores"):
        raise ValueError("%s is an APFS container, not a card. Refusing." % dev)
    if not (info.get("RemovableMedia") is True or info.get("Removable") is True):
        raise ValueError("%s is NOT removable (an external hard disk or SSD, not a card in a reader). Refusing." % dev)
    size = info.get("TotalSize") or info.get("Size") or 0
    if not isinstance(size, int) or size <= 0:
        raise ValueError("%s reports no size - there is no card in the reader" % dev)
    if size < MIN_BYTES:
        raise ValueError("%s is only %d MB; the card's layout needs %d MB before the Debian root is even counted"
                         % (dev, size // 1024 // 1024, -(-MIN_BYTES // 1024 // 1024)))
    if size > MAX_BYTES and not allow_large:
        raise ValueError("%s is %.0f GB; anything over %d GB is refused on purpose - that is unlikely to be an SD "
                         "card for this board.\n"
                         "       If it really is the card, say so:  sudo ALLOW_LARGE=1 ./devkit write-card ... %s"
                         % (dev, size / 1e9, MAX_BYTES // 10 ** 9, dev))
    return name, size


def disk_mounts(name):
    """Mount points of every volume on disk NAME, from `diskutil list -plist`."""
    lst = diskutil_plist("list", "-plist", "/dev/" + name) or {}
    out = []
    for d in lst.get("AllDisksAndPartitions") or []:
        for p in [d] + list(d.get("Partitions") or []) + list(d.get("APFSVolumes") or []):
            if p.get("MountPoint"):
                out.append(p["MountPoint"])
    return out


# ------------------------------------------------------------------- sources
def run_rc(argv):
    return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def gather_sources(from_dir):
    """Decide which files go on the card, checking each the way the Linux
    writer does. Returns (boot_files [(name, path)], rootfs path, temp files)."""
    src = from_dir or os.path.join(FW, "output")
    uimg, dtb = os.path.join(src, "uImage"), os.path.join(src, "devicetree.dtb")
    need = [uimg, dtb] + ([os.path.join(from_dir, "uEnv.txt")] if from_dir else [])
    for f in need:
        if not os.path.isfile(f):
            die("missing %s - %s" % (f, "not a downloaded modern release?" if from_dir else
                                     "build the modern kernel first, or pass --from DIR with a downloaded release"))

    # The root filesystem.
    tar = os.path.join(DEBIAN, "rootfs.tar")
    rel_tgz = os.path.join(from_dir, card_image.ROOTFS) if from_dir else None
    out_tgz = os.path.join(FW, "output", card_image.ROOTFS)
    if rel_tgz and os.path.isfile(rel_tgz):
        rootfs = rel_tgz
    elif os.path.isfile(tar):
        rootfs = tar
        # rootfs.tar is a build artefact; overlay/ is the source of truth, and
        # nothing rebuilds the tar when the overlay changes (see write-card.sh).
        newer = []
        tar_m = os.path.getmtime(tar)
        for d, _, fs in os.walk(os.path.join(DEBIAN, "overlay")):
            for x in fs:
                p = os.path.join(d, x)
                if os.lstat(p).st_mtime > tar_m:
                    newer.append(os.path.relpath(p, os.path.join(DEBIAN, "overlay")))
        if newer:
            warn("overlay/ has files newer than rootfs.tar:")
            for p in sorted(newer)[:10]:
                print("           " + p, file=sys.stderr)
            print("         The card would get a rootfs WITHOUT them. Rebuild it with\n"
                  "             ./devkit build --target modern --rootfs-only\n"
                  "         or pass OVERLAY_OK=1 if the tar really is what you want.", file=sys.stderr)
            if os.environ.get("OVERLAY_OK", "0") != "1":
                die("refusing to write a rootfs older than the overlay")
    elif not from_dir and os.path.isfile(out_tgz):
        rootfs = out_tgz
    else:
        die("no Debian root to write: neither %s%s nor %s.\n"
            "       Download a modern release (BOOT.bin uImage devicetree.dtb uEnv.txt debian-rootfs.tar.gz\n"
            "       SHA256SUMS) into one folder and pass --from that folder, or build the root:\n"
            "           ./devkit build --target modern --rootfs-only"
            % ((rel_tgz + ", ") if rel_tgz else "", tar, out_tgz))
    note("Debian root from " + rootfs)

    # A release carries SHA256SUMS: check every file it lists before trusting any.
    sums_ok = False
    if from_dir and os.path.isfile(os.path.join(from_dir, "SHA256SUMS")):
        sums = card_image.read_sums(os.path.join(from_dir, "SHA256SUMS"))
        listed = [n for n in card_image.BOOT_FILES if n in sums]
        if not listed:
            die("%s/SHA256SUMS lists none of the boot files" % from_dir)
        if rootfs == rel_tgz:
            if card_image.ROOTFS in sums:
                listed.append(card_image.ROOTFS)
            else:
                warn("%s/SHA256SUMS does not list %s; it is written unchecked" % (from_dir, card_image.ROOTFS))
        for n in listed:
            p = os.path.join(from_dir, n)
            if not os.path.isfile(p):
                continue                         # reported as missing where it is needed
            if card_image.sha256_file(p) != sums[n]:
                die("%s in %s does not match its SHA256SUMS - download it again" % (n, from_dir))
        note("%s match %s/SHA256SUMS" % (" ".join(listed), from_dir))
        sums_ok = "BOOT.bin" in listed
    elif from_dir:
        warn("no SHA256SUMS in %s: the files are written without a check against the release" % from_dir)

    # output/ is a copy, and a copy can be stale: compare with what was just built.
    if not from_dir:
        for rel, dst in (("arch/arm/boot/uImage", uimg),
                         ("arch/arm/boot/dts/xilinx/zynq-pluto-sdr-fishball.dtb", dtb)):
            built = os.path.join(FW, "src", "linux", rel)
            if os.path.isfile(built) and card_image.sha256_file(built) != card_image.sha256_file(dst):
                warn("%s in output/ differs from the one just built (%s).\n"
                     "         Copy it over first, or pass STALE_OK=1 if output/ is what you want."
                     % (os.path.basename(dst), built))
                if os.environ.get("STALE_OK", "0") != "1":
                    die("refusing to write a stale " + os.path.basename(dst))

    # WHICH BOOT.bin: BOOT_BIN=/path if set, else the source's own. Nothing else.
    bootbin = os.environ.get("BOOT_BIN", "")
    if not bootbin and os.path.isfile(os.path.join(src, "BOOT.bin")):
        bootbin = os.path.join(src, "BOOT.bin")
        note("BOOT.bin from %s - %s" % (from_dir or "the modern build", bootbin))
    if not bootbin:
        die("no modern BOOT.bin - build one: ./devkit build --target modern --xsa FILE\n"
            "       (or set BOOT_BIN=/path/to/BOOT.bin to write one you chose)")
    if not os.path.isfile(bootbin):
        die("no BOOT.bin found; set BOOT_BIN=/path/to/BOOT.bin")
    checker = os.path.join(REPO, "firmware", "scripts", "check_bootbin.py")
    rc = run_rc([sys.executable, checker, bootbin])
    if rc == 4:
        if sums_ok and from_dir and os.path.abspath(bootbin) == os.path.join(from_dir, "BOOT.bin"):
            note("no bootgen to read BOOT.bin's partitions; its SHA256SUMS match vouches for it")
        else:
            die("cannot check %s: no bootgen here (./devkit setup --target modern builds one)" % bootbin)
    elif rc != 0:
        subprocess.run([sys.executable, checker, bootbin], stdout=sys.stderr)
        die("%s is not a BOOT.bin this board can boot (above)" % bootbin)

    temps = []
    uenv = os.path.join(src, "uEnv.txt")
    if not (os.path.isfile(uenv) and os.path.getsize(uenv) > 0):
        if from_dir:
            die("no uEnv.txt in " + from_dir)
        r = subprocess.run(["bash", os.path.join(DEBIAN, "make-uenv.sh")], capture_output=True)
        if r.returncode != 0 or not r.stdout:
            die("make-uenv.sh could not write a uEnv.txt:\n" + r.stderr.decode(errors="replace"))
        fd, uenv = tempfile.mkstemp(prefix="uEnv-")
        os.write(fd, r.stdout)
        os.close(fd)
        temps.append(uenv)

    boot = [("BOOT.bin", bootbin), ("uImage", uimg), ("devicetree.dtb", dtb), ("uEnv.txt", uenv)]
    ramdisk = os.path.join(REPO, "firmware", "output", "uramdisk.image.gz")
    if os.path.isfile(ramdisk):
        boot.append(("uramdisk.image.gz", ramdisk))
    return boot, rootfs, temps


def compare_bitstream(rdev, bootbin):
    """A changed FPGA design must never be silent: compare the bitstream with the
    card about to be overwritten, the only honest reference. Read-only."""
    ref = None
    try:
        with open(rdev, "rb", buffering=0) as f:
            parts = card_image.read_mbr(f)
            if parts and parts[0][1] in (0x0B, 0x0C):
                got = card_image.fat32_read_root(f, parts[0][2] * 512, want=["BOOT.bin"])
                data = next((v for k, v in got.items() if k.lower() == "boot.bin"), None)
                if data:
                    fd, ref = tempfile.mkstemp(prefix="BOOT-ref-")
                    os.write(fd, data)
                    os.close(fd)
    except (OSError, ValueError):
        ref = None
    if not ref:
        note("nothing to compare the FPGA bitstream with; writing the one below")
        return
    try:
        rc = run_rc([sys.executable, os.path.join(REPO, "firmware", "scripts", "check_bootbin.py"),
                     bootbin, "--ref", ref, "--require-same", "system_top.bit"])
        if rc == 0:
            note("same FPGA bitstream as the card you are about to overwrite")
        elif rc == 3:
            warn("this BOOT.bin carries a DIFFERENT FPGA bitstream from the card\n"
                 "         you are about to overwrite. If that is not what you meant, stop now.")
        elif card_image.sha256_file(ref) == card_image.sha256_file(bootbin):
            note("same BOOT.bin as the card you are about to overwrite")
        else:
            note("could not compare bitstreams with the card being overwritten (its BOOT.bin differs)")
    finally:
        os.remove(ref)


# --------------------------------------------------------------------- write
def debug_on():
    return os.environ.get("WRITE_CARD_DEBUG", "0") not in ("", "0")


def opened_size(f):
    """The size of what is actually open, asked of the descriptor rather than
    of a name: block count times block size for a disk device. (A regular file
    answers with its length; only a test puts one where a device is expected.)"""
    st = os.fstat(f.fileno())
    if stat.S_ISREG(st.st_mode):
        return st.st_size
    if not (stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode)):
        raise OSError("not a disk device")
    import fcntl
    bsize, = struct.unpack("I", fcntl.ioctl(f.fileno(), DKIOCGETBLOCKSIZE, bytes(4)))
    count, = struct.unpack("Q", fcntl.ioctl(f.fileno(), DKIOCGETBLOCKCOUNT, bytes(8)))
    return bsize * count


INCOMPLETE = ("       THE CARD IS NOW INCOMPLETE: its old partition table was erased first, so it reads as a\n"
              "       blank card, and it will not boot the board. Write it again:  sudo ./devkit write-card ... %s")


def settle_and_unmount(name, tries=30, pause=0.5):
    """macOS reads the new partition table once the device is closed and mounts
    FISHBOOT by itself. Wait until it has - `diskutil info` knows both
    partitions - then unmount, and see that it stays unmounted, so "take it
    out" is said only when it is true. Gives up after tries * pause seconds
    each way. Returns whether the card is unmounted."""
    dev = "/dev/" + name
    for _ in range(tries):
        parts = [diskutil_plist("info", "-plist", "%ss%d" % (dev, n)) for n in (1, 2)]
        if all(p and p.get("DeviceIdentifier") == "%ss%d" % (name, n) for p, n in zip(parts, (1, 2))):
            break
        time.sleep(pause)
    quiet = 0
    for _ in range(tries):
        r = subprocess.run(["diskutil", "unmountDisk", dev], capture_output=True, text=True)
        time.sleep(pause)
        if r.returncode == 0 and not disk_mounts(name):
            quiet += 1
            if quiet == 2:                       # unmounted, and still so half a second later
                return True
        else:
            quiet = 0
    return False


def write_disk(name, size, boot, rootfs, want, plan=None):
    dev, rdev = "/dev/" + name, "/dev/r" + name
    print("=== unmounting anything on %s ===" % dev)
    r = subprocess.run(["diskutil", "unmountDisk", dev], capture_output=True, text=True)
    if r.returncode != 0:
        die("%s could not be unmounted - close whatever is using the card and run again:\n%s\n"
            "       Nothing was written." % (dev, (r.stdout + r.stderr).strip()))
    try:
        # The raw device: unbuffered, so what is read back comes from the card.
        f = open(rdev, "r+b", buffering=0)
    except PermissionError as e:
        die("cannot open %s for writing: %s\n"
            "       If you ARE running with sudo: macOS is withholding the card from this terminal.\n"
            "       System Settings > Privacy & Security > Files and Folders (or Full Disk Access):\n"
            "       allow your terminal app 'Removable Volumes', then run this again.\n"
            "       A full-size SD adapter also has a lock switch: slide it away from LOCK." % (rdev, e))
    except OSError as e:
        die("cannot open %s for writing: %s" % (rdev, e))
    t0 = time.time()
    stage = "open"
    try:
        # The disk was checked by name; what is open now is asked directly. A
        # different size means a different disk took the name in between.
        try:
            actual = opened_size(f)
        except OSError as e:
            die("cannot ask the opened %s how large it is (%s): nothing was written." % (rdev, e))
        if actual != size:
            die("%s is %d bytes now that it is open, but was %d bytes when it was checked: that is not the "
                "same card.\n       Nothing was written. Run again." % (rdev, actual, size))
        t = card_image.Target(f, size)
        print("=== writing ===")
        stage = "write"
        card_image.write_card(t, boot, rootfs, lambda s: print("  " + s), plan=plan)
        stage = "verify"
        print("  wrote %d MB in %.0f s" % (t.bytes_written >> 20, time.time() - t0))
        subprocess.run(["sync"])
        print("=== verifying: reading the card back ===")
        tty = sys.stdout.isatty()

        def progress(done, total):
            if tty:
                sys.stdout.write("\r  %3d%%  " % (done * 100 // max(total, 1)))
                sys.stdout.flush()
        try:
            ok = t.verify(progress)
        except OSError as e:
            die("reading the card back failed: %s. The card or the reader is faulty: try another card." % e)
        if tty:
            print()
        if not ok:
            die("what was read back differs from what was written. The card or the reader is faulty: "
                "try another card.")
        print("  OK: all %d MB read back identical" % (t.verified_bytes >> 20))
        print("=== boot partition, read back from the card ===")
        try:
            bad = card_image.check_boot_readback(f, want)
        except (OSError, ValueError) as e:
            die("the boot partition cannot be read back from the card: %s" % e)
        if bad:
            die("boot file(s) on the card differ from the ones written: %s. Try another card." % ", ".join(bad))
        stage = "done"
    except SystemExit:
        raise
    except BaseException as e:
        # Whatever it was, say what state the card is in before anything else.
        sys.stdout.flush()
        untouched = stage == "open" or (stage == "write" and t.bytes_written == 0)
        if stage == "verify":
            state = ("       The card was written to the end but NOT checked: do not trust it. Write it again:\n"
                     "       sudo ./devkit write-card ... %s" % dev)
        elif untouched:
            state = "       Nothing was written to %s." % dev
        else:
            state = INCOMPLETE % dev
        if isinstance(e, KeyboardInterrupt):
            print("\nERROR: interrupted.\n" + state, file=sys.stderr)
            sys.exit(130)
        if isinstance(e, card_image.CardError) and untouched:
            die(card_image.explain(e, dev))
        if isinstance(e, card_image.CardError):
            die("writing the card stopped: %s\n%s" % (e, state))
        if isinstance(e, OSError):
            die("writing the card failed: %s\n%s\n"
                "       If it fails again at the same point, the card or the reader is faulty: try another."
                % (e, state))
        print("ERROR: the card writer itself failed (%s: %s) - that is a bug in it, not a fault in the card.\n%s"
              % (type(e).__name__, e, state), file=sys.stderr)
        if debug_on() or not isinstance(e, Exception):
            raise
        print("       For the traceback, run it again with --debug.", file=sys.stderr)
        sys.exit(1)
    finally:
        f.close()
    # macOS mounts FISHBOOT as soon as it has read the new partition table;
    # unmount it again so the card can simply be pulled.
    try:
        return settle_and_unmount(name)
    except KeyboardInterrupt:
        return False                             # written and verified; just not unmounted by us


def main(argv):
    dry, image, image_mb, dev, from_dir, size_given = False, "", 2048, "", "", False
    it = iter(argv)
    for a in it:
        if a == "--dry-run":
            dry = True
        elif a == "--image":
            image = next(it, "") or die("--image needs a file name")
        elif a == "--from":
            from_dir = next(it, "")
            if not os.path.isdir(from_dir):
                die("--from needs a directory (a downloaded release)")
            from_dir = os.path.abspath(from_dir)
        elif a == "--size":
            v = next(it, "")
            if not v.isdigit():
                die("--size needs megabytes")
            image_mb, size_given = int(v), True
        elif a == "--debug":
            os.environ["WRITE_CARD_DEBUG"] = "1"
        elif a in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        elif a.startswith("-"):
            die("unknown option %s\n%s" % (a, USAGE))
        else:
            if dev:
                die(USAGE)
            dev = a
    if image:
        if dev:
            die("give a device OR --image, not both")
        # A NEW file only: --image must never become a quieter way to overwrite something.
        if os.path.lexists(image):
            die("%s already exists - --image writes a NEW file, it never overwrites" % image)
        if image_mb < 1024:
            die("--size %d is too small; a Debian root needs ~1 GB minimum" % image_mb)
    else:
        if not dev:
            die(USAGE)
        if size_given:
            die("--size only means something with --image")
    if not image and not dry and os.geteuid() != 0:
        die("needs root (it writes a whole disk); --dry-run and --image do not")

    # The disk first: nothing else matters if it is the wrong one.
    allow_large = os.environ.get("ALLOW_LARGE", "0") == "1"
    name = None
    if image:
        size = image_mb * 1024 * 1024
        info = {}
    else:
        m = re.match(r"^/dev/r?(disk\d+)", dev)
        info = diskutil_plist("info", "-plist", dev) if m else None
        try:
            name, size = check_disk(dev, info, boot_disks(), disk_mounts(m.group(1)) if m and info else [],
                                    allow_large)
        except (ValueError, RuntimeError) as e:
            die(str(e))
        if info.get("WritableMedia") is False and not dry:
            die("%s is write-protected. If it is a full-size SD adapter, slide its lock switch away from LOCK." % dev)

    boot, rootfs, temps = gather_sources(from_dir)
    try:
        if name and os.geteuid() == 0:
            compare_bitstream("/dev/r" + name, boot[0][1])
        else:
            note("nothing to compare the FPGA bitstream with; writing the one below")

        # The pre-flight: the whole release laid out for this size, nothing
        # written. Whatever would stop the write stops it here, with the card
        # still as it was.
        target = image or "/dev/" + name
        try:
            plan = card_image.plan_card(size, boot, rootfs)
        except card_image.CardError as e:
            die(card_image.explain(e, target))
        except OSError as e:
            die("cannot read the release: %s.\n       Nothing was written to %s." % (e, target))
        note("the release fits: %d MB to write, %d of %d inodes used, %.1f GB left free on the root"
             % (plan.write_bytes >> 20, plan.inodes_used, plan.inodes_total, plan.free_bytes / 1e9))
        if plan.clamped:
            note(card_image.clamp_note(plan.clamped))
        if plan.free_bytes < 64 << 20:
            warn("only %d MB would be left free on the root: Debian will boot, and fill it quickly. "
                 "A larger card is the better choice." % (plan.free_bytes >> 20))

        print("\nAbout to COMPLETELY ERASE:\n")
        if image:
            print("  %s   %d MB   (a new image file)" % (image, size // 1024 // 1024))
        else:
            print("  /dev/%s   %d MB   %s   (%s, %s, removable)"
                  % (name, size // 1024 // 1024, info.get("MediaName") or info.get("IORegistryEntryName") or "?",
                     info.get("BusProtocol") or "?",
                     "the built-in SD slot" if is_sd_slot(info) else "external"))
            r = subprocess.run(["diskutil", "list", "/dev/" + name], capture_output=True, text=True)
            for line in r.stdout.splitlines()[1:]:
                print("    " + line)
        extra = [n for n, _ in boot[4:]]
        print("\nand write:\n")
        print("  p1  128 MB FAT32    " + "  ".join(n for n, _ in boot[:4]))
        print("                      " + ("%s  (the Buildroot fallback)" % extra[0] if extra else
                                         "(no Buildroot ramdisk here - so no fallback root on this card)"))
        print("  p2  the rest ext3   %d MB of Debian armhf, from %s\n"
              % (os.path.getsize(rootfs) >> 20, os.path.basename(rootfs)))
        if dry:
            print("--dry-run: every check passed and nothing was written.")
            return 0

        want = {n: card_image.sha256_file(p) for n, p in boot}
        if image:
            try:
                card_image.build_image(image, image_mb, boot, rootfs, lambda s: print("  " + s), plan=plan)
            except card_image.CardError as e:
                die("writing the image failed: %s\n       No image was left behind." % e)
            # Under sudo the file would be root's; give it to whoever ran sudo.
            if os.geteuid() == 0 and os.environ.get("SUDO_UID", "").isdigit():
                os.chown(image, int(os.environ["SUDO_UID"]), int(os.environ.get("SUDO_GID", "-1")))
            print("\nDone: %s. Written and read back; the four boot files match." % image)
            print("Check it on Linux with:  sudo python3 tools/check_card_image.py %s RELEASE_DIR" % image)
            return 0

        try:
            confirm = input("Type the disk name again to confirm (%s): " % name)
        except EOFError:
            confirm = ""
        except KeyboardInterrupt:
            print()
            die("not confirmed - nothing was written")
        if confirm.strip() != name:
            die("not confirmed - nothing was written")
        # The card can be swapped between the checks and now; ask again, and
        # write only if nothing about the disk has changed.
        again = diskutil_plist("info", "-plist", "/dev/" + name)
        try:
            check_disk("/dev/" + name, again, boot_disks(), disk_mounts(name) if again else [], allow_large)
        except (ValueError, RuntimeError) as e:
            die(str(e) + "\n       Nothing was written.")
        if (again.get("TotalSize"), again.get("MediaName")) != (info.get("TotalSize"), info.get("MediaName")):
            die("/dev/%s changed while you were asked - nothing was written. Run again." % name)
        unmounted = write_disk(name, size, boot, rootfs, want, plan)
        print("\nDone. The card boots the Debian root by default.")
        print("It is unmounted: take it out of the reader." if unmounted else
              "Eject it before taking it out:  diskutil eject /dev/%s" % name)
        if not extra:
            print("This card boots Debian only; it carries no Buildroot ramdisk to fall back to.")
        return 0
    finally:
        for p in temps:
            try:
                os.remove(p)
            except OSError:
                pass


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        # An interrupt while a card is being written is answered in write_disk,
        # which says what state the card is in. Any other comes here.
        print("\nERROR: interrupted before anything was written to a card.", file=sys.stderr)
        sys.exit(130)
