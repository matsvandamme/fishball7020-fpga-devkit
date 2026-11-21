<# : the cmd launcher; PowerShell reads this block as a comment
@echo off
rem This one file is both a cmd launcher (this block) and the PowerShell script
rem after it, so it can be sent on its own. Windows will not run a .ps1 by
rem double-click or under the default execution policy, so the launcher copies
rem the whole file to %TEMP% as a .ps1 and runs that, policy bypassed for this
rem run only. -Folder tells the script where the release files are: the folder
rem this file is in. Arguments pass through, e.g.  write-card.cmd -DiskNumber 2
setlocal
set "ps1=%TEMP%\write-card-%RANDOM%.ps1"
copy /y "%~f0" "%ps1%" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%ps1%" -Folder "%~dp0." %*
set rc=%errorlevel%
del "%ps1%" >nul 2>&1
rem Double-clicked: keep the window open so the result can be read.
echo %cmdcmdline% | find /i "/c" >nul && pause
exit /b %rc%
#>
<#
.SYNOPSIS
    Write the Fishball7020 / PlutoSky firmware (modern: Linux 6.12 + Debian 13)
    to a microSD card, on Windows, with nothing installed.

.DESCRIPTION
    Put this file in the folder holding the release files and double-click it.
    It needs these files beside it, from the same GitHub release:

        BOOT.bin  uImage  devicetree.dtb  uEnv.txt  debian-rootfs.tar.gz
        SHA256SUMS

    What it does, in order:
      1. Checks every file against SHA256SUMS, so a damaged download is caught
         before anything is erased.
      2. Lists the SD cards and USB disks it is willing to write - never the
         disk Windows runs from, never a disk over 256 GB - and asks which.
      3. Copies every file on the card's existing Windows-readable partitions
         into a backup folder next to this script.
      4. Asks you to type ERASE.
      5. Writes the whole card: the partition table, a 128 MB FAT32 boot
         partition "FISHBOOT", and the rest of the card as the Linux root
         partition "fishroot", unpacked from debian-rootfs.tar.gz.
      6. Reads everything back from the card and compares it, then checks the
         boot files once more through Windows itself.

    The root partition is ext3, which Windows cannot format, so the script
    builds it itself. The board's kernel mounts it with its ext4 driver.

    Needs administrator rights (to write a whole disk); it asks for them.
    Windows PowerShell 5.1, built into Windows 10 and 11, is enough.

.PARAMETER DiskNumber
    Skip the list and use this disk (the number from Disk Management or the
    list this script prints). You are still asked to type ERASE.

.PARAMETER ImageFile
    Write a card image file instead of a card: for a tool such as Rufus or
    balenaEtcher, or for testing. Needs no administrator rights.

.PARAMETER ImageSizeMB
    The size of the image -ImageFile writes. Default 4096 (4 GB); the root
    partition fills it.

.PARAMETER Folder
    Where the release files are. The launcher passes its own folder.

.PARAMETER NoPause
    Do not wait for Enter before closing (for scripts and CI).

.EXAMPLE
    # run from: the folder holding write-card.cmd and the release files
    .\write-card.cmd
    .\write-card.cmd -DiskNumber 2
    .\write-card.cmd -ImageFile fishball-v2.3.img -ImageSizeMB 7600

    Or double-click write-card.cmd.
#>
[CmdletBinding()]
param(
    [int]$DiskNumber = -1,
    [string]$ImageFile = '',
    [long]$ImageSizeMB = 4096,
    [string]$Folder = '',
    [switch]$NoPause,
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'
if (-not $Folder) { $Folder = $PSScriptRoot }
$Folder = (Resolve-Path -LiteralPath $Folder).Path
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Required = @('BOOT.bin', 'uImage', 'devicetree.dtb', 'uEnv.txt', 'debian-rootfs.tar.gz')

function Say([string]$s) { Write-Host $s }
function Step([string]$s) { Write-Host ''; Write-Host "== $s" -ForegroundColor Cyan }
function Fail([string]$s) {
    Write-Host ''
    Write-Host "ERROR: $s" -ForegroundColor Red
    Finish 1
}
function Finish([int]$code) {
    try { Stop-Transcript | Out-Null } catch { }
    if ($Elevated -and -not $NoPause) { Write-Host ''; Read-Host 'Press Enter to close this window' | Out-Null }
    exit $code
}
function GB([double]$bytes) { '{0:0.0} GB' -f ($bytes / 1e9) }

$IsWin = [Environment]::OSVersion.Platform -eq 'Win32NT'
$ImageMode = [bool]$ImageFile

# Writing a whole disk needs administrator rights. Ask for them by starting an
# elevated copy of this script, and wait for it.
if ($IsWin -and -not $ImageMode) {
    $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        if ($Elevated) { Fail 'still not running as administrator.' }
        Say 'Writing an SD card needs administrator rights. Windows will ask you to allow it;'
        Say 'the card writer then continues in a new window.'
        $args2 = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"",
                   '-Folder', "`"$($Folder.TrimEnd('\'))\.`"", '-Elevated')
        if ($DiskNumber -ge 0) { $args2 += @('-DiskNumber', "$DiskNumber") }
        try { $p = Start-Process powershell.exe -Verb RunAs -ArgumentList $args2 -Wait -PassThru }
        catch { Say ''; Say 'Administrator rights were not given, so nothing was written.'; exit 1 }
        Say "The card writer finished (exit code $($p.ExitCode)). Its log is in $Folder."
        exit $p.ExitCode
    }
}

try { Start-Transcript -Path (Join-Path $Folder "write-card-$Stamp.log") | Out-Null } catch { }

Say ''
Say 'Fishball7020 / PlutoSky SD card writer'
Say 'Firmware: modern (Linux 6.12 + Debian 13), from the files in:'
Say "  $Folder"

# ---------------------------------------------------------------- 1. files
Step '1/6  Checking the release files'
$sums = Join-Path $Folder 'SHA256SUMS'
if (-not (Test-Path -LiteralPath $sums)) {
    Fail "SHA256SUMS is not in $Folder. Download it from the same release as the other files and put it next to this script."
}
$want = @{}
foreach ($line in Get-Content -LiteralPath $sums) {
    if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') { $want[$Matches[2]] = $Matches[1].ToLower() }
}
foreach ($f in $Required) {
    $path = Join-Path $Folder $f
    if (-not (Test-Path -LiteralPath $path)) {
        Fail "$f is missing from $Folder. This script needs: $($Required -join ', ') and SHA256SUMS, all from the same release. (A browser sometimes renames a download, e.g. 'uImage (1)'.)"
    }
    if (-not $want.ContainsKey($f)) { Fail "SHA256SUMS has no line for $f - is it from the same release?" }
    $h = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
    if ($h -ne $want[$f]) { Fail "$f does not match SHA256SUMS: the download is damaged or from another release. Download it again." }
    Say ('  OK  {0,-22} {1,12:N0} bytes' -f $f, (Get-Item -LiteralPath $path).Length)
}
if (Select-String -LiteralPath (Join-Path $Folder 'uEnv.txt') -Pattern 'mmcblk0p2' -Quiet) { }
else { Fail 'uEnv.txt does not boot from the SD card root partition: these look like factory (v1.x) files, which this script does not write.' }

# --------------------------------------------------------- compile the writer
$src = @'
// Builds a Fishball7020 SD card - partition table, FAT32 boot partition and
// ext3 root partition - and writes it straight to a disk or an image file.
//
// Embedded in tools/write-card.cmd and compiled there by Add-Type. Windows
// PowerShell 5.1 compiles with the .NET Framework's C# 5 compiler, so this file
// must stay C# 5: no string interpolation, no "?.", no expression-bodied
// members, no tuples, no "out var". CI compiles it with LangVersion 5.
//
// The layout matches firmware-modern/debian/write-card.sh:
//   sector 0            MBR, two primary partitions
//   p1  2048 .. +128MiB  FAT32 "FISHBOOT", type 0x0C, bootable
//   p2  rest of card     Linux "fishroot", type 0x83
// p2 is ext3 (ext2 + journal) rather than ext4: it has no extents and no
// checksums, so it can be written without e2fsprogs, and the board's kernel
// mounts it with its ext4 driver (CONFIG_EXT4_USE_FOR_EXT2). fstab finds both
// partitions by label.

using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace Fishball
{
    // ------------------------------------------------------------------
    // Where the bytes go: a physical disk (\\.\PhysicalDriveN) or a file.
    // Every write is recorded, so Verify() can read it all back.
    // ------------------------------------------------------------------
    public sealed class Target : IDisposable
    {
        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr sa, uint disposition, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool DeviceIoControl(SafeFileHandle h, uint code, IntPtr inBuf, uint inSize, IntPtr outBuf, uint outSize, out uint returned, IntPtr overlapped);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool ReadFile(SafeFileHandle h, IntPtr buf, uint toRead, out uint read, IntPtr overlapped);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetFilePointerEx(SafeFileHandle h, long distance, out long newPos, uint method);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr VirtualAlloc(IntPtr addr, UIntPtr size, uint type, uint protect);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool VirtualFree(IntPtr addr, UIntPtr size, uint type);

        const uint GENERIC_READ = 0x80000000, GENERIC_WRITE = 0x40000000;
        const uint SHARE_RW = 3, OPEN_EXISTING = 3;
        const uint FLAG_WRITE_THROUGH = 0x80000000, FLAG_NO_BUFFERING = 0x20000000;
        const uint FSCTL_LOCK_VOLUME = 0x00090018, FSCTL_DISMOUNT_VOLUME = 0x00090020;
        const uint IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C, IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140;

        Stream stream;
        SafeFileHandle disk;
        string diskPath, imagePath;
        readonly List<SafeFileHandle> volumeLocks = new List<SafeFileHandle>();
        public long Size;

        // written regions, in write order, merged when contiguous
        readonly List<long> regOff = new List<long>();
        readonly List<long> regLen = new List<long>();
        readonly SHA256 writeHash = SHA256.Create();

        // coalescing write buffer
        readonly byte[] pend = new byte[8 << 20];
        long pendOff = -1;
        int pendLen = 0;
        public long BytesWritten;

        Target() { }

        public static Target OpenImage(string path, long size)
        {
            Target t = new Target();
            t.imagePath = path;
            t.stream = new FileStream(path, FileMode.Create, FileAccess.ReadWrite, FileShare.Read, 1 << 20);
            t.stream.SetLength(size);
            t.Size = size;
            return t;
        }

        // volumePaths: \\?\Volume{...} paths (no trailing backslash) of every
        // volume on the disk. They are locked and dismounted so Windows lets the
        // raw writes through, and stay locked until Dispose.
        public static Target OpenDisk(int number, string[] volumePaths)
        {
            Target t = new Target();
            foreach (string v in volumePaths)
            {
                SafeFileHandle h = CreateFile(v, GENERIC_READ | GENERIC_WRITE, SHARE_RW, IntPtr.Zero, OPEN_EXISTING, 0, IntPtr.Zero);
                if (h.IsInvalid) throw new IOException("cannot open volume " + v + " (error " + Marshal.GetLastWin32Error() + ")");
                uint ret;
                bool locked = false;
                for (int i = 0; i < 40 && !locked; i++)
                {
                    locked = DeviceIoControl(h, FSCTL_LOCK_VOLUME, IntPtr.Zero, 0, IntPtr.Zero, 0, out ret, IntPtr.Zero);
                    if (!locked) System.Threading.Thread.Sleep(250);
                }
                // Dismounting works even when the lock did not: it closes every
                // other handle (an Explorer window, an antivirus scan) on the volume.
                if (!DeviceIoControl(h, FSCTL_DISMOUNT_VOLUME, IntPtr.Zero, 0, IntPtr.Zero, 0, out ret, IntPtr.Zero))
                    throw new IOException("cannot dismount volume " + v + " (error " + Marshal.GetLastWin32Error() + "). Close any window or program using the card and run again.");
                t.volumeLocks.Add(h);
            }
            t.diskPath = @"\\.\PhysicalDrive" + number;
            t.disk = CreateFile(t.diskPath, GENERIC_READ | GENERIC_WRITE, SHARE_RW, IntPtr.Zero, OPEN_EXISTING, FLAG_WRITE_THROUGH, IntPtr.Zero);
            if (t.disk.IsInvalid) throw new IOException("cannot open " + t.diskPath + " (error " + Marshal.GetLastWin32Error() + ")");
            IntPtr buf = Marshal.AllocHGlobal(8);
            try
            {
                uint ret;
                if (!DeviceIoControl(t.disk, IOCTL_DISK_GET_LENGTH_INFO, IntPtr.Zero, 0, buf, 8, out ret, IntPtr.Zero))
                    throw new IOException("cannot read the size of " + t.diskPath + " (error " + Marshal.GetLastWin32Error() + ")");
                t.Size = Marshal.ReadInt64(buf);
            }
            finally { Marshal.FreeHGlobal(buf); }
            t.stream = new FileStream(t.disk, FileAccess.ReadWrite, 1, false);
            return t;
        }

        public void Write(long off, byte[] buf, int idx, int len, bool verify)
        {
            if (len == 0) return;
            if ((off & 511) != 0 || (len & 511) != 0) throw new ArgumentException("unaligned write at " + off);
            if (off < 0 || off + len > Size) throw new IOException("write past the end of the card at " + off);
            if (verify)
            {
                int n = regOff.Count;
                if (n > 0 && regOff[n - 1] + regLen[n - 1] == off) regLen[n - 1] += len;
                else { regOff.Add(off); regLen.Add(len); }
                writeHash.TransformBlock(buf, idx, len, null, 0);
            }
            if (pendOff >= 0 && off == pendOff + pendLen && pendLen + len <= pend.Length)
            {
                Buffer.BlockCopy(buf, idx, pend, pendLen, len);
                pendLen += len;
                return;
            }
            FlushPending();
            if (len > pend.Length) { RawWrite(off, buf, idx, len); return; }
            Buffer.BlockCopy(buf, idx, pend, 0, len);
            pendOff = off;
            pendLen = len;
        }

        void FlushPending()
        {
            if (pendOff < 0) return;
            RawWrite(pendOff, pend, 0, pendLen);
            pendOff = -1;
            pendLen = 0;
        }

        void RawWrite(long off, byte[] buf, int idx, int len)
        {
            stream.Seek(off, SeekOrigin.Begin);
            stream.Write(buf, idx, len);
            BytesWritten += len;
        }

        public void Flush()
        {
            FlushPending();
            stream.Flush();
        }

        // Reads every recorded region back from the card itself and compares
        // a SHA-256 of it with the one taken while writing.
        public bool Verify(Action<long, long> progress)
        {
            Flush();
            writeHash.TransformFinalBlock(new byte[0], 0, 0);
            byte[] want = writeHash.Hash;
            long total = 0;
            for (int i = 0; i < regLen.Count; i++) total += regLen[i];
            SHA256 h = SHA256.Create();
            const int CHUNK = 4 << 20;
            byte[] managed = new byte[CHUNK];
            long done = 0;
            if (disk != null)
            {
                // A second handle without the cache, so the read-back comes from
                // the card and not from memory.
                SafeFileHandle r = CreateFile(diskPath, GENERIC_READ, SHARE_RW, IntPtr.Zero, OPEN_EXISTING, FLAG_NO_BUFFERING, IntPtr.Zero);
                if (r.IsInvalid) throw new IOException("cannot reopen " + diskPath + " to verify (error " + Marshal.GetLastWin32Error() + ")");
                IntPtr ab = VirtualAlloc(IntPtr.Zero, (UIntPtr)CHUNK, 0x3000, 0x04);
                try
                {
                    for (int i = 0; i < regOff.Count; i++)
                    {
                        long off = regOff[i], left = regLen[i];
                        while (left > 0)
                        {
                            int n = (int)Math.Min(CHUNK, left);
                            long np;
                            if (!SetFilePointerEx(r, off, out np, 0)) throw new IOException("seek failed while verifying");
                            uint got;
                            if (!ReadFile(r, ab, (uint)n, out got, IntPtr.Zero) || got != n)
                                throw new IOException("read failed while verifying at " + off + " (error " + Marshal.GetLastWin32Error() + ")");
                            Marshal.Copy(ab, managed, 0, n);
                            h.TransformBlock(managed, 0, n, null, 0);
                            off += n; left -= n; done += n;
                            if (progress != null) progress(done, total);
                        }
                    }
                }
                finally { VirtualFree(ab, UIntPtr.Zero, 0x8000); r.Dispose(); }
            }
            else
            {
                using (FileStream r = new FileStream(imagePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite, 1 << 20))
                {
                    for (int i = 0; i < regOff.Count; i++)
                    {
                        long left = regLen[i];
                        r.Seek(regOff[i], SeekOrigin.Begin);
                        while (left > 0)
                        {
                            int n = (int)Math.Min(CHUNK, left);
                            int got = 0;
                            while (got < n)
                            {
                                int k = r.Read(managed, got, n - got);
                                if (k <= 0) throw new IOException("short read while verifying");
                                got += k;
                            }
                            h.TransformBlock(managed, 0, n, null, 0);
                            left -= n; done += n;
                            if (progress != null) progress(done, total);
                        }
                    }
                }
            }
            h.TransformFinalBlock(new byte[0], 0, 0);
            byte[] got2 = h.Hash;
            for (int i = 0; i < want.Length; i++) if (want[i] != got2[i]) return false;
            return true;
        }

        public long VerifiedBytes
        {
            get { long t = 0; for (int i = 0; i < regLen.Count; i++) t += regLen[i]; return t; }
        }

        public void Dispose()
        {
            try { Flush(); } catch { }
            // The old volumes' locks go first, then Windows re-reads the new
            // partition table, so the boot partition appears without a replug.
            foreach (SafeFileHandle h in volumeLocks) h.Dispose();
            volumeLocks.Clear();
            if (disk != null && !disk.IsInvalid)
            {
                uint ret;
                DeviceIoControl(disk, IOCTL_DISK_UPDATE_PROPERTIES, IntPtr.Zero, 0, IntPtr.Zero, 0, out ret, IntPtr.Zero);
            }
            if (stream != null) stream.Dispose();
        }
    }

    static class LE
    {
        public static void U16(byte[] b, int o, int v) { b[o] = (byte)v; b[o + 1] = (byte)(v >> 8); }
        public static void U32(byte[] b, int o, long v) { b[o] = (byte)v; b[o + 1] = (byte)(v >> 8); b[o + 2] = (byte)(v >> 16); b[o + 3] = (byte)(v >> 24); }
        public static void BE32(byte[] b, int o, long v) { b[o] = (byte)(v >> 24); b[o + 1] = (byte)(v >> 16); b[o + 2] = (byte)(v >> 8); b[o + 3] = (byte)v; }
    }

    // ------------------------------------------------------------------
    // FAT32 boot partition holding a handful of files in its root.
    // ------------------------------------------------------------------
    public static class Fat32
    {
        const int BPS = 512, SPC = 1, RSVD = 32, NFATS = 2;   // as mkfs.vfat -F 32 lays out 128 MB

        public static void Write(Target t, long partLba, long partSectors, string label, string[] names, byte[][] contents, DateTime when)
        {
            long fatSz = ((partSectors - RSVD) + (256 * SPC + NFATS) / 2 - 1) / ((256 * SPC + NFATS) / 2);
            long dataStart = RSVD + NFATS * fatSz;
            long clusters = (partSectors - dataStart) / SPC;
            if (clusters < 65525) throw new InvalidOperationException("boot partition too small for FAT32");
            int clusterBytes = BPS * SPC;

            // root directory: volume label, then each file as long-name entries + 8.3 entry
            List<byte[]> dirEntries = new List<byte[]>();
            byte[] lab = new byte[32];
            byte[] labName = Encoding.ASCII.GetBytes(label.ToUpperInvariant().PadRight(11).Substring(0, 11));
            Buffer.BlockCopy(labName, 0, lab, 0, 11);
            lab[11] = 0x08;
            int fdate = ((when.Year - 1980) << 9) | (when.Month << 5) | when.Day;
            int ftime = (when.Hour << 11) | (when.Minute << 5) | (when.Second / 2);
            LE.U16(lab, 22, ftime); LE.U16(lab, 24, fdate);
            dirEntries.Add(lab);

            uint[] fat = new uint[clusters + 2];
            fat[0] = 0x0FFFFFF8; fat[1] = 0x0FFFFFFF;
            fat[2] = 0x0FFFFFFF;                 // root directory, one cluster
            long next = 3;
            long[] firstCluster = new long[names.Length];
            Dictionary<string, bool> shorts = new Dictionary<string, bool>();
            for (int i = 0; i < names.Length; i++)
            {
                long n = (contents[i].Length + clusterBytes - 1) / clusterBytes;
                firstCluster[i] = n == 0 ? 0 : next;
                for (long c = 0; c < n; c++) fat[next + c] = (c == n - 1) ? 0x0FFFFFFFu : (uint)(next + c + 1);
                next += n;
                if (next > clusters + 2) throw new InvalidOperationException("boot files do not fit the boot partition");

                byte[] sn = ShortName(names[i], shorts);
                foreach (byte[] e in LongNameEntries(names[i], sn)) dirEntries.Add(e);
                byte[] d = new byte[32];
                Buffer.BlockCopy(sn, 0, d, 0, 11);
                d[11] = 0x20;
                LE.U16(d, 14, ftime); LE.U16(d, 16, fdate); LE.U16(d, 18, fdate);
                LE.U16(d, 20, (int)(firstCluster[i] >> 16));
                LE.U16(d, 22, ftime); LE.U16(d, 24, fdate);
                LE.U16(d, 26, (int)(firstCluster[i] & 0xFFFF));
                LE.U32(d, 28, contents[i].Length);
                dirEntries.Add(d);
            }
            if (dirEntries.Count * 32 > clusterBytes) throw new InvalidOperationException("too many boot files for one directory cluster");

            // reserved region: boot sector, FSInfo, sector 2, and their backups at 6..8
            byte[] rsvd = new byte[RSVD * BPS];
            byte[] bs = new byte[BPS];
            bs[0] = 0xEB; bs[1] = 0x58; bs[2] = 0x90;
            Buffer.BlockCopy(Encoding.ASCII.GetBytes("FISHBALL"), 0, bs, 3, 8);
            LE.U16(bs, 11, BPS); bs[13] = SPC; LE.U16(bs, 14, RSVD); bs[16] = NFATS;
            bs[21] = 0xF8; LE.U16(bs, 24, 63); LE.U16(bs, 26, 255);
            LE.U32(bs, 28, partLba); LE.U32(bs, 32, partSectors); LE.U32(bs, 36, fatSz);
            LE.U32(bs, 44, 2); LE.U16(bs, 48, 1); LE.U16(bs, 50, 6);
            bs[64] = 0x80; bs[66] = 0x29;
            LE.U32(bs, 67, (uint)Guid.NewGuid().GetHashCode());
            Buffer.BlockCopy(labName, 0, bs, 71, 11);
            Buffer.BlockCopy(Encoding.ASCII.GetBytes("FAT32   "), 0, bs, 82, 8);
            bs[510] = 0x55; bs[511] = 0xAA;
            byte[] fsi = new byte[BPS];
            LE.U32(fsi, 0, 0x41615252); LE.U32(fsi, 484, 0x61417272);
            LE.U32(fsi, 488, clusters - (next - 2)); LE.U32(fsi, 492, next);
            LE.U32(fsi, 508, 0xAA550000);
            byte[] s2 = new byte[BPS]; s2[510] = 0x55; s2[511] = 0xAA;
            foreach (int b in new int[] { 0, 6 })
            {
                Buffer.BlockCopy(bs, 0, rsvd, (b + 0) * BPS, BPS);
                Buffer.BlockCopy(fsi, 0, rsvd, (b + 1) * BPS, BPS);
                Buffer.BlockCopy(s2, 0, rsvd, (b + 2) * BPS, BPS);
            }
            long p = partLba * BPS;
            t.Write(p, rsvd, 0, rsvd.Length, true);

            byte[] fatBytes = new byte[fatSz * BPS];
            for (long c = 0; c < fat.Length; c++) LE.U32(fatBytes, (int)(c * 4), fat[c]);
            for (int f = 0; f < NFATS; f++) t.Write(p + (RSVD + f * fatSz) * BPS, fatBytes, 0, fatBytes.Length, true);

            long data = p + dataStart * BPS;
            byte[] root = new byte[clusterBytes];
            for (int i = 0; i < dirEntries.Count; i++) Buffer.BlockCopy(dirEntries[i], 0, root, i * 32, 32);
            t.Write(data, root, 0, root.Length, true);
            for (int i = 0; i < names.Length; i++)
            {
                if (firstCluster[i] == 0) continue;
                long n = (contents[i].Length + clusterBytes - 1) / clusterBytes;
                byte[] padded = new byte[n * clusterBytes];
                Buffer.BlockCopy(contents[i], 0, padded, 0, contents[i].Length);
                t.Write(data + (firstCluster[i] - 2) * clusterBytes, padded, 0, padded.Length, true);
            }
        }

        static byte[] ShortName(string name, Dictionary<string, bool> used)
        {
            string b = name, e = "";
            int dot = name.LastIndexOf('.');
            if (dot > 0) { b = name.Substring(0, dot); e = name.Substring(dot + 1); }
            b = Clean(b); e = Clean(e);
            if (e.Length > 3) e = e.Substring(0, 3);
            string s = b.Length > 8 ? b.Substring(0, 6) + "~1" : b;
            for (int k = 2; used.ContainsKey(s + "." + e); k++) s = b.Substring(0, Math.Min(b.Length, 6)) + "~" + k;
            used[s + "." + e] = true;
            return Encoding.ASCII.GetBytes(s.PadRight(8) + e.PadRight(3));
        }

        static string Clean(string s)
        {
            StringBuilder sb = new StringBuilder();
            foreach (char c in s.ToUpperInvariant()) if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-') sb.Append(c);
            return sb.ToString();
        }

        static List<byte[]> LongNameEntries(string name, byte[] shortName)
        {
            int sum = 0;
            for (int i = 0; i < 11; i++) sum = (((sum & 1) << 7) + (sum >> 1) + shortName[i]) & 0xFF;
            int n = (name.Length + 12) / 13;
            List<byte[]> list = new List<byte[]>();
            int[] pos = { 1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30 };
            for (int k = n; k >= 1; k--)
            {
                byte[] e = new byte[32];
                e[0] = (byte)(k | (k == n ? 0x40 : 0));
                e[11] = 0x0F; e[13] = (byte)sum;
                for (int j = 0; j < 13; j++)
                {
                    int ci = (k - 1) * 13 + j;
                    int v = ci < name.Length ? name[ci] : (ci == name.Length ? 0 : 0xFFFF);
                    LE.U16(e, pos[j], v);
                }
                list.Add(e);
            }
            return list;
        }
    }

    // ------------------------------------------------------------------
    // A streaming reader for (pax/GNU/ustar) tar archives.
    // ------------------------------------------------------------------
    public sealed class TarEntry
    {
        public string Name, LinkName;
        public char Type;
        public int Mode;
        public int Uid, Gid;
        public long Size, Mtime;
    }

    public sealed class TarReader
    {
        readonly Stream s;
        readonly byte[] hdr = new byte[512];
        long remaining;   // data bytes of the current entry not yet read
        long padding;

        public TarReader(Stream s) { this.s = s; }

        public TarEntry Next()
        {
            Skip(remaining + padding);
            remaining = padding = 0;
            Dictionary<string, string> pax = null;
            string longName = null, longLink = null;
            while (true)
            {
                if (!ReadFull(hdr, 512)) return null;
                bool zero = true;
                for (int i = 0; i < 512; i++) if (hdr[i] != 0) { zero = false; break; }
                if (zero) return null;
                long chk = 0;
                for (int i = 0; i < 512; i++) chk += (i >= 148 && i < 156) ? 32 : hdr[i];
                if (chk != Num(148, 8)) throw new InvalidDataException("tar header checksum mismatch - the archive is damaged");
                char type = hdr[156] == 0 ? '0' : (char)hdr[156];
                long size = Num(124, 12);
                if (type == 'x' || type == 'g' || type == 'L' || type == 'K')
                {
                    byte[] d = new byte[size];
                    if (!ReadFull(d, (int)size)) throw new EndOfStreamException("truncated tar archive");
                    Skip((512 - size % 512) % 512);
                    if (type == 'x') pax = ParsePax(d);
                    else if (type == 'L') longName = Str(d, 0, d.Length);
                    else if (type == 'K') longLink = Str(d, 0, d.Length);
                    continue;
                }
                TarEntry e = new TarEntry();
                e.Type = type;
                e.Name = Str(hdr, 0, 100);
                string magic = Str(hdr, 257, 6);
                if (magic.StartsWith("ustar"))
                {
                    string prefix = Str(hdr, 345, 155);
                    if (prefix.Length > 0) e.Name = prefix + "/" + e.Name;
                }
                e.LinkName = Str(hdr, 157, 100);
                e.Mode = (int)Num(100, 8);
                e.Uid = (int)Num(108, 8);
                e.Gid = (int)Num(116, 8);
                e.Size = size;
                e.Mtime = Num(136, 12);
                if (longName != null) e.Name = longName;
                if (longLink != null) e.LinkName = longLink;
                if (pax != null)
                {
                    string v;
                    if (pax.TryGetValue("path", out v)) e.Name = v;
                    if (pax.TryGetValue("linkpath", out v)) e.LinkName = v;
                    if (pax.TryGetValue("size", out v)) e.Size = long.Parse(v);
                    if (pax.TryGetValue("uid", out v)) e.Uid = int.Parse(v);
                    if (pax.TryGetValue("gid", out v)) e.Gid = int.Parse(v);
                    if (pax.TryGetValue("mtime", out v)) e.Mtime = (long)double.Parse(v.Split('.')[0]);
                }
                // links, directories, devices and FIFOs carry no data
                if (type != '0' && type != '7') e.Size = 0;
                remaining = e.Size;
                padding = (512 - e.Size % 512) % 512;
                return e;
            }
        }

        // Reads up to count bytes of the current entry's data.
        public int Read(byte[] buf, int off, int count)
        {
            int want = (int)Math.Min(count, remaining);
            int got = 0;
            while (got < want)
            {
                int k = s.Read(buf, off + got, want - got);
                if (k <= 0) throw new EndOfStreamException("truncated tar archive");
                got += k;
            }
            remaining -= got;
            return got;
        }

        bool ReadFull(byte[] b, int n)
        {
            int got = 0;
            while (got < n)
            {
                int k = s.Read(b, got, n - got);
                if (k <= 0) { if (got == 0) return false; throw new EndOfStreamException("truncated tar archive"); }
                got += k;
            }
            return true;
        }

        void Skip(long n)
        {
            byte[] junk = new byte[65536];
            while (n > 0)
            {
                int k = s.Read(junk, 0, (int)Math.Min(junk.Length, n));
                if (k <= 0) throw new EndOfStreamException("truncated tar archive");
                n -= k;
            }
        }

        long Num(int off, int len)
        {
            if ((hdr[off] & 0x80) != 0)
            {
                long v = hdr[off] & 0x7F;
                for (int i = 1; i < len; i++) v = (v << 8) | hdr[off + i];
                return v;
            }
            long r = 0;
            for (int i = 0; i < len; i++)
            {
                byte c = hdr[off + i];
                if (c >= '0' && c <= '7') r = r * 8 + (c - '0');
                else if (c == 0 || (c == ' ' && r > 0)) break;
            }
            return r;
        }

        static string Str(byte[] b, int off, int len)
        {
            int end = off;
            while (end < off + len && b[end] != 0) end++;
            return Encoding.UTF8.GetString(b, off, end - off);
        }

        static Dictionary<string, string> ParsePax(byte[] d)
        {
            Dictionary<string, string> m = new Dictionary<string, string>();
            int i = 0;
            while (i < d.Length)
            {
                int sp = Array.IndexOf(d, (byte)' ', i);
                if (sp < 0) break;
                int len = int.Parse(Encoding.ASCII.GetString(d, i, sp - i));
                string rec = Encoding.UTF8.GetString(d, sp + 1, len - (sp - i) - 2);
                int eq = rec.IndexOf('=');
                if (eq > 0) m[rec.Substring(0, eq)] = rec.Substring(eq + 1);
                i += len;
            }
            return m;
        }
    }

    // ------------------------------------------------------------------
    // ext3 filesystem written directly from a tar archive.
    // ------------------------------------------------------------------
    public sealed class Ext3
    {
        const int BS = 4096, BPG = 32768, ISIZE = 256, FIRST_INO = 11;
        const int S_IFREG = 0x8000, S_IFDIR = 0x4000, S_IFLNK = 0xA000;

        sealed class Inode
        {
            public int Mode, Uid, Gid, Links;
            public long Size, Blocks512, Mtime;
            public uint[] Block = new uint[15];
            public byte[] Fast;   // fast symlink target, stored in i_block
        }

        sealed class Dir
        {
            public uint Ino;
            public Dir Parent;
            public int Mode = 0x1ED, Uid, Gid;   // 0755 until the archive says otherwise
            public long Mtime;
            public int ExtraBlocks;
            public readonly List<byte[]> Names = new List<byte[]>();
            public readonly List<uint> Inos = new List<uint>();
            public readonly List<byte> Types = new List<byte>();
            public readonly Dictionary<string, Dir> Subdirs = new Dictionary<string, Dir>();
            public readonly Dictionary<string, uint> Children = new Dictionary<string, uint>();
        }

        readonly Target t;
        readonly long part;              // byte offset of the partition
        readonly long blocks;
        readonly int groups, ipg, itb, gdtBlocks;
        readonly byte[] bitmap;          // one bit per block
        readonly long[] grpBB, grpIB, grpIT;
        long cursor;
        uint nextIno = FIRST_INO;
        readonly Dictionary<uint, Inode> inodes = new Dictionary<uint, Inode>();
        readonly Dir root;
        readonly Dictionary<string, uint> paths = new Dictionary<string, uint>();
        readonly byte[] uuid = Guid.NewGuid().ToByteArray();
        readonly uint now;
        long journalBlocks;
        public long Files, Dirs, Links, DataBytes;

        public Ext3(Target target, long partOffset, long partBytes)
        {
            t = target; part = partOffset;
            now = (uint)(DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds;
            long b = partBytes / BS;
            if (b > 0xFFFFFFFFL) b = 0xFFFFFFFFL;
            int g = (int)((b + BPG - 1) / BPG);
            // fewer inodes on big cards: the inode tables are written in full
            ipg = g <= 512 ? 2048 : 1024;
            itb = ipg * ISIZE / BS;
            gdtBlocks = (g * 32 + BS - 1) / BS;
            long last = b - (long)(g - 1) * BPG;
            int lastMeta = (HasSuper(g - 1) ? 1 + gdtBlocks : 0) + 2 + itb;
            if (g > 1 && last < lastMeta + 256) { g--; b = (long)g * BPG; }
            blocks = b; groups = g;
            gdtBlocks = (groups * 32 + BS - 1) / BS;
            bitmap = new byte[(blocks + 7) / 8 + 1];
            grpBB = new long[groups]; grpIB = new long[groups]; grpIT = new long[groups];
            for (int i = 0; i < groups; i++)
            {
                long s = (long)i * BPG;
                long m = s + (HasSuper(i) ? 1 + gdtBlocks : 0);
                grpBB[i] = m; grpIB[i] = m + 1; grpIT[i] = m + 2;
                for (long k = s; k < m + 2 + itb; k++) Mark(k);
            }
            root = new Dir();
            root.Ino = 2; root.Parent = root; root.Mtime = now;
            inodes[2] = new Inode();
        }

        public long BlockCount { get { return blocks; } }
        public int GroupCount { get { return groups; } }

        static bool HasSuper(int g)
        {
            if (g <= 1) return true;
            foreach (int p in new int[] { 3, 5, 7 })
            {
                long v = p;
                while (v < g) v *= p;
                if (v == g) return true;
            }
            return false;
        }

        void Mark(long b) { bitmap[b >> 3] |= (byte)(1 << (int)(b & 7)); }
        bool Used(long b) { return (bitmap[b >> 3] & (1 << (int)(b & 7))) != 0; }

        uint Alloc()
        {
            while (cursor < blocks && Used(cursor)) cursor++;
            if (cursor >= blocks) throw new IOException("the card is too small for the root filesystem");
            Mark(cursor);
            return (uint)cursor++;
        }

        uint NewIno()
        {
            if (nextIno > (uint)groups * (uint)ipg) throw new IOException("out of inodes");
            return nextIno++;
        }

        void WriteBlock(uint blk, byte[] buf, int idx)
        {
            t.Write(part + (long)blk * BS, buf, idx, BS, true);
        }

        // Allocates n data blocks plus the indirect blocks that map them, in
        // file order (an indirect block just before the data it maps), and calls
        // fill(i, block) once per data block to write its content.
        uint[] MapBlocks(long n, Action<long, uint> fill, out long total)
        {
            uint[] ib = new uint[15];
            total = 0;
            uint[] ind = null, dind = null;
            uint indBlk = 0, dindBlk = 0;
            for (long i = 0; i < n; i++)
            {
                uint b;
                if (i < 12) { b = Alloc(); ib[i] = b; }
                else if (i < 12 + 1024)
                {
                    if (i == 12) { indBlk = Alloc(); ib[12] = indBlk; ind = new uint[1024]; total++; }
                    b = Alloc(); ind[i - 12] = b;
                    if (i == 12 + 1023 || i == n - 1) WritePtrs(indBlk, ind);
                }
                else
                {
                    long j = i - 1036;
                    if (j >= 1024L * 1024) throw new IOException("file too large");
                    if (j == 0) { dindBlk = Alloc(); ib[13] = dindBlk; dind = new uint[1024]; total++; }
                    if (j % 1024 == 0) { indBlk = Alloc(); dind[j / 1024] = indBlk; ind = new uint[1024]; total++; }
                    b = Alloc(); ind[j % 1024] = b;
                    if (j % 1024 == 1023 || i == n - 1) WritePtrs(indBlk, ind);
                    if (i == n - 1) WritePtrs(dindBlk, dind);
                }
                total++;
                fill(i, b);
            }
            return ib;
        }

        void WritePtrs(uint blk, uint[] p)
        {
            byte[] b = new byte[BS];
            for (int i = 0; i < 1024; i++) LE.U32(b, i * 4, p[i]);
            WriteBlock(blk, b, 0);
        }

        // inode 8: the journal, all zeros except its superblock (big-endian, JBD2)
        public void CreateJournal()
        {
            long jb = blocks < 32768 ? 1024 : blocks < 262144 ? 4096 : blocks < 524288 ? 8192 : blocks < 4194304 ? 16384 : 32768;
            journalBlocks = jb;
            byte[] zero = new byte[BS];
            byte[] jsb = new byte[BS];
            LE.BE32(jsb, 0, 0xC03B3998); LE.BE32(jsb, 4, 4);
            LE.BE32(jsb, 12, BS); LE.BE32(jsb, 16, jb); LE.BE32(jsb, 20, 1); LE.BE32(jsb, 24, 1);
            Buffer.BlockCopy(uuid, 0, jsb, 48, 16);
            LE.BE32(jsb, 64, 1);
            long total;
            Inode ino = new Inode();
            ino.Block = MapBlocks(jb, delegate(long i, uint b) { WriteBlock(b, i == 0 ? jsb : zero, 0); }, out total);
            ino.Mode = S_IFREG | 0x180; ino.Links = 1; ino.Size = jb * BS; ino.Blocks512 = total * 8; ino.Mtime = now;
            inodes[8] = ino;
        }

        public void CreateLostFound()
        {
            Dir d = MakeDir(root, "lost+found");
            d.Mode = 0x1C0; d.Mtime = now; d.ExtraBlocks = 3;
        }

        Dir MakeDir(Dir parent, string name)
        {
            Dir d = new Dir();
            d.Ino = NewIno(); d.Parent = parent; d.Mtime = now;
            parent.Subdirs[name] = d;
            AddEntry(parent, name, d.Ino, 2);
            inodes[d.Ino] = new Inode();
            Dirs++;
            return d;
        }

        void AddEntry(Dir parent, string name, uint ino, byte type)
        {
            if (parent.Children.ContainsKey(name)) throw new InvalidDataException("duplicate path in archive: " + name);
            parent.Children[name] = ino;
            parent.Names.Add(Encoding.UTF8.GetBytes(name));
            parent.Inos.Add(ino);
            parent.Types.Add(type);
        }

        static string Clean(string p)
        {
            while (p.StartsWith("./")) p = p.Substring(2);
            p = p.Trim('/');
            return p == "." ? "" : p;
        }

        Dir DirFor(string path, bool create)
        {
            Dir d = root;
            if (path.Length == 0) return d;
            foreach (string part2 in path.Split('/'))
            {
                if (part2.Length == 0 || part2 == ".") continue;
                Dir next;
                if (!d.Subdirs.TryGetValue(part2, out next))
                {
                    if (!create) throw new InvalidDataException("no directory " + path);
                    next = MakeDir(d, part2);
                }
                d = next;
            }
            return d;
        }

        public void AddFromTar(TarReader tar, Action<long> progress)
        {
            byte[] buf = new byte[BS];
            TarEntry e;
            long n = 0;
            while ((e = tar.Next()) != null)
            {
                string path = Clean(e.Name);
                string parentPath = path.Contains("/") ? path.Substring(0, path.LastIndexOf('/')) : "";
                string name = path.Substring(parentPath.Length == 0 ? 0 : parentPath.Length + 1);
                int perm = e.Mode & 0xFFF;
                if (e.Type == '5')
                {
                    Dir d = path.Length == 0 ? root : DirFor(path, true);
                    d.Mode = perm; d.Uid = e.Uid; d.Gid = e.Gid; d.Mtime = e.Mtime;
                    continue;
                }
                if (path.Length == 0) continue;
                Dir parent = DirFor(parentPath, true);
                if (e.Type == '0' || e.Type == '7')
                {
                    uint ino = NewIno();
                    Inode node = new Inode();
                    long size = e.Size;
                    long nb = (size + BS - 1) / BS;
                    long total;
                    node.Block = MapBlocks(nb, delegate(long i, uint b)
                    {
                        int got = tar.Read(buf, 0, BS);
                        if (got < BS) Array.Clear(buf, got, BS - got);
                        WriteBlock(b, buf, 0);
                    }, out total);
                    node.Mode = S_IFREG | perm; node.Uid = e.Uid; node.Gid = e.Gid; node.Links = 1;
                    node.Size = size; node.Blocks512 = total * 8; node.Mtime = e.Mtime;
                    inodes[ino] = node;
                    AddEntry(parent, name, ino, 1);
                    paths[path] = ino;
                    Files++; DataBytes += size;
                }
                else if (e.Type == '2')
                {
                    uint ino = NewIno();
                    Inode node = new Inode();
                    byte[] target = Encoding.UTF8.GetBytes(e.LinkName);
                    node.Mode = S_IFLNK | 0x1FF; node.Uid = e.Uid; node.Gid = e.Gid; node.Links = 1;
                    node.Size = target.Length; node.Mtime = e.Mtime;
                    if (target.Length < 60) node.Fast = target;
                    else
                    {
                        if (target.Length >= BS) throw new InvalidDataException("symlink target too long: " + path);
                        byte[] blk = new byte[BS];
                        Buffer.BlockCopy(target, 0, blk, 0, target.Length);
                        long total;
                        node.Block = MapBlocks(1, delegate(long i, uint b) { WriteBlock(b, blk, 0); }, out total);
                        node.Blocks512 = total * 8;
                    }
                    inodes[ino] = node;
                    AddEntry(parent, name, ino, 7);
                    paths[path] = ino;
                    Links++;
                }
                else if (e.Type == '1')
                {
                    uint ino;
                    if (!paths.TryGetValue(Clean(e.LinkName), out ino)) throw new InvalidDataException("hard link to unknown file: " + e.LinkName);
                    inodes[ino].Links++;
                    AddEntry(parent, name, ino, (byte)((inodes[ino].Mode & 0xF000) == S_IFLNK ? 7 : 1));
                    paths[path] = ino;
                }
                else throw new InvalidDataException("unsupported entry type '" + e.Type + "' for " + path);
                if (progress != null && (++n & 63) == 0) progress(n);
            }
        }

        void WriteDirs(Dir d)
        {
            // entries: ".", "..", then the children
            List<byte[]> names = new List<byte[]>();
            List<uint> inos = new List<uint>();
            List<byte> types = new List<byte>();
            names.Add(new byte[] { (byte)'.' }); inos.Add(d.Ino); types.Add(2);
            names.Add(new byte[] { (byte)'.', (byte)'.' }); inos.Add(d.Parent.Ino); types.Add(2);
            names.AddRange(d.Names); inos.AddRange(d.Inos); types.AddRange(d.Types);

            List<byte[]> blks = new List<byte[]>();
            byte[] cur = new byte[BS];
            int pos = 0, lastPos = -1;
            for (int i = 0; i < names.Count; i++)
            {
                int rec = (8 + names[i].Length + 3) & ~3;
                if (pos + rec > BS)
                {
                    LE.U16(cur, lastPos + 4, BS - lastPos);
                    blks.Add(cur); cur = new byte[BS]; pos = 0;
                }
                LE.U32(cur, pos, inos[i]);
                LE.U16(cur, pos + 4, rec);
                cur[pos + 6] = (byte)names[i].Length;
                cur[pos + 7] = types[i];
                Buffer.BlockCopy(names[i], 0, cur, pos + 8, names[i].Length);
                lastPos = pos; pos += rec;
            }
            LE.U16(cur, lastPos + 4, BS - lastPos);
            blks.Add(cur);
            for (int i = 0; i < d.ExtraBlocks; i++) { byte[] empty = new byte[BS]; LE.U16(empty, 4, BS); blks.Add(empty); }

            long total;
            Inode node = inodes[d.Ino];
            node.Block = MapBlocks(blks.Count, delegate(long i, uint b) { WriteBlock(b, blks[(int)i], 0); }, out total);
            node.Mode = S_IFDIR | d.Mode; node.Uid = d.Uid; node.Gid = d.Gid; node.Mtime = d.Mtime;
            node.Links = 2 + d.Subdirs.Count;
            node.Size = (long)blks.Count * BS; node.Blocks512 = total * 8;
            foreach (Dir s in d.Subdirs.Values) WriteDirs(s);
        }

        // Directories, inode tables, bitmaps, group descriptors, superblocks.
        public void Finish(string label)
        {
            WriteDirs(root);

            long[] freeB = new long[groups];
            int[] freeI = new int[groups], dirsIn = new int[groups];
            long totalFreeB = 0, totalFreeI = 0;
            byte[] table = new byte[itb * BS];
            byte[] bmp = new byte[BS];
            for (int g = 0; g < groups; g++)
            {
                long start = (long)g * BPG, end = Math.Min(start + BPG, blocks);
                // block bitmap; bits past the end of the filesystem are set
                Array.Clear(bmp, 0, BS);
                for (long b = start; b < start + BPG; b++)
                {
                    int bit = (int)(b - start);
                    if (b >= end || Used(b)) bmp[bit >> 3] |= (byte)(1 << (bit & 7));
                    else freeB[g]++;
                }
                WriteBlock((uint)grpBB[g], bmp, 0);

                // inode table and inode bitmap; bits past ipg are set
                Array.Clear(table, 0, table.Length);
                Array.Clear(bmp, 0, BS);
                for (int k = ipg; k < BS * 8; k++) bmp[k >> 3] |= (byte)(1 << (k & 7));
                for (int k = 0; k < ipg; k++)
                {
                    uint ino = (uint)(g * ipg + k + 1);
                    Inode node;
                    bool used = ino < FIRST_INO || inodes.ContainsKey(ino);
                    if (used) bmp[k >> 3] |= (byte)(1 << (k & 7)); else freeI[g]++;
                    if (!inodes.TryGetValue(ino, out node)) continue;
                    if ((node.Mode & 0xF000) == S_IFDIR) dirsIn[g]++;
                    PutInode(table, k * ISIZE, node);
                }
                WriteBlock((uint)grpIB[g], bmp, 0);
                for (int k = 0; k < itb; k++) WriteBlock((uint)(grpIT[g] + k), table, k * BS);
                totalFreeB += freeB[g]; totalFreeI += freeI[g];
            }

            byte[] gdt = new byte[gdtBlocks * BS];
            for (int g = 0; g < groups; g++)
            {
                int o = g * 32;
                LE.U32(gdt, o, grpBB[g]); LE.U32(gdt, o + 4, grpIB[g]); LE.U32(gdt, o + 8, grpIT[g]);
                LE.U16(gdt, o + 12, (int)freeB[g]); LE.U16(gdt, o + 14, freeI[g]); LE.U16(gdt, o + 16, dirsIn[g]);
            }

            Inode j = inodes[8];
            for (int g = 0; g < groups; g++)
            {
                if (!HasSuper(g)) continue;
                byte[] sb = new byte[1024];
                LE.U32(sb, 0, (long)groups * ipg);
                LE.U32(sb, 4, blocks);
                LE.U32(sb, 8, blocks / 100);
                LE.U32(sb, 12, totalFreeB);
                LE.U32(sb, 16, totalFreeI);
                LE.U32(sb, 20, 0);
                LE.U32(sb, 24, 2); LE.U32(sb, 28, 2);
                LE.U32(sb, 32, BPG); LE.U32(sb, 36, BPG); LE.U32(sb, 40, ipg);
                LE.U32(sb, 48, now);
                LE.U16(sb, 54, 0xFFFF);
                LE.U16(sb, 56, 0xEF53); LE.U16(sb, 58, 1); LE.U16(sb, 60, 1);
                LE.U32(sb, 64, now);
                LE.U32(sb, 76, 1);
                LE.U32(sb, 84, FIRST_INO); LE.U16(sb, 88, ISIZE); LE.U16(sb, 90, g);
                LE.U32(sb, 92, 0x04 | 0x20);       // has_journal, dir_index
                LE.U32(sb, 96, 0x02);              // filetype
                LE.U32(sb, 100, 0x01 | 0x02);      // sparse_super, large_file
                Buffer.BlockCopy(uuid, 0, sb, 104, 16);
                byte[] lab = Encoding.ASCII.GetBytes(label);
                Buffer.BlockCopy(lab, 0, sb, 120, Math.Min(16, lab.Length));
                LE.U32(sb, 224, 8);
                Buffer.BlockCopy(Guid.NewGuid().ToByteArray(), 0, sb, 236, 16);
                sb[252] = 1;                       // half_md4
                sb[253] = 1;                       // journal inode backed up below
                LE.U32(sb, 264, now);
                for (int k = 0; k < 15; k++) LE.U32(sb, 268 + k * 4, j.Block[k]);
                LE.U32(sb, 268 + 15 * 4, 0); LE.U32(sb, 268 + 16 * 4, j.Size);
                LE.U16(sb, 348, 32); LE.U16(sb, 350, 32);
                LE.U32(sb, 352, 1);                // signed directory hash
                byte[] first = new byte[BS];
                Buffer.BlockCopy(sb, 0, first, g == 0 ? 1024 : 0, 1024);
                long at = (long)g * BPG;
                WriteBlock((uint)at, first, 0);
                for (int k = 0; k < gdtBlocks; k++) WriteBlock((uint)(at + 1 + k), gdt, k * BS);
            }
        }

        void PutInode(byte[] t2, int o, Inode n)
        {
            LE.U16(t2, o, n.Mode);
            LE.U16(t2, o + 2, n.Uid & 0xFFFF);
            LE.U32(t2, o + 4, n.Size & 0xFFFFFFFFL);
            LE.U32(t2, o + 8, n.Mtime); LE.U32(t2, o + 12, n.Mtime); LE.U32(t2, o + 16, n.Mtime);
            LE.U16(t2, o + 24, n.Gid & 0xFFFF);
            LE.U16(t2, o + 26, n.Links);
            LE.U32(t2, o + 28, n.Blocks512);
            if (n.Fast != null) Buffer.BlockCopy(n.Fast, 0, t2, o + 40, n.Fast.Length);
            else for (int k = 0; k < 15; k++) LE.U32(t2, o + 40 + k * 4, n.Block[k]);
            LE.U32(t2, o + 108, n.Size >> 32);
            LE.U16(t2, o + 120, n.Uid >> 16);
            LE.U16(t2, o + 122, n.Gid >> 16);
            LE.U16(t2, o + 128, 32);
        }

        public long FreeBytes()
        {
            long used = 0;
            for (long b = 0; b < blocks; b++) if (Used(b)) used++;
            return (blocks - used) * (long)BS;
        }
    }

    // ------------------------------------------------------------------
    // The whole card.
    // ------------------------------------------------------------------
    public static class Card
    {
        public const long BootLba = 2048, BootSectors = 128L * 2048, RootLba = BootLba + BootSectors;

        public static void Write(Target t, string folder, Action<string> say)
        {
            long sectors = t.Size / 512;
            if (sectors > 0xFFFFFFFFL) throw new IOException("card larger than 2 TB");
            long rootSectors = (sectors - RootLba) / 8 * 8;
            if (rootSectors * 512 < 700L * 1024 * 1024) throw new IOException("the card is too small: it needs at least 1 GB");

            // The old partition table goes first, so a write that is interrupted
            // leaves a card that is plainly blank rather than half-written.
            byte[] gap = new byte[BootLba * 512];
            t.Write(0, gap, 0, 512, false);
            t.Write(512, gap, 0, gap.Length - 512, true);

            say("boot partition (FAT32, 128 MB)");
            string[] names = { "BOOT.bin", "uImage", "devicetree.dtb", "uEnv.txt" };
            byte[][] contents = new byte[names.Length][];
            for (int i = 0; i < names.Length; i++) contents[i] = File.ReadAllBytes(Path.Combine(folder, names[i]));
            Fat32.Write(t, BootLba, BootSectors, "FISHBOOT", names, contents, DateTime.Now);

            Ext3 fs = new Ext3(t, RootLba * 512, rootSectors * 512);
            say("root partition (ext3, " + (fs.BlockCount * 4096 / 1000000) + " MB, " + fs.GroupCount + " block groups)");
            fs.CreateJournal();
            fs.CreateLostFound();
            string tgz = Path.Combine(folder, "debian-rootfs.tar.gz");
            using (FileStream fsrc = new FileStream(tgz, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
            using (GZipStream gz = new GZipStream(fsrc, CompressionMode.Decompress))
            using (BufferedStream bs = new BufferedStream(gz, 1 << 20))
            {
                DateTime last = DateTime.MinValue;
                FileStream src = fsrc;
                fs.AddFromTar(new TarReader(bs), delegate(long n)
                {
                    if ((DateTime.Now - last).TotalMilliseconds < 500) return;
                    last = DateTime.Now;
                    Console.Write("\r    unpacking Debian: " + (src.Position * 100 / src.Length) + "%  (" + n + " files)   ");
                });
                Console.WriteLine("\r    unpacking Debian: 100%  (" + (fs.Files + fs.Dirs + fs.Links) + " files)            ");
            }
            say("writing directories, inode tables and superblocks");
            fs.Finish("fishroot");

            // Partition table last: until it is written the card has no partitions.
            byte[] mbr = new byte[512];
            LE.U32(mbr, 440, (uint)Guid.NewGuid().GetHashCode());
            PartEntry(mbr, 446, 0x80, 0x0C, BootLba, BootSectors);
            PartEntry(mbr, 462, 0x00, 0x83, RootLba, rootSectors);
            mbr[510] = 0x55; mbr[511] = 0xAA;
            t.Write(0, mbr, 0, 512, true);
            t.Flush();
            say(string.Format("{0} files, {1} directories, {2} symlinks, {3:0.0} MB of file data; {4:0.0} GB free",
                fs.Files, fs.Dirs, fs.Links, fs.DataBytes / 1e6, fs.FreeBytes() / 1e9));
        }

        static void PartEntry(byte[] m, int o, byte status, byte type, long lba, long count)
        {
            m[o] = status;
            m[o + 1] = 0xFE; m[o + 2] = 0xFF; m[o + 3] = 0xFF;    // CHS unused: LBA only
            m[o + 4] = type;
            m[o + 5] = 0xFE; m[o + 6] = 0xFF; m[o + 7] = 0xFF;
            LE.U32(m, o + 8, lba);
            LE.U32(m, o + 12, count);
        }
    }
}
'@
if (-not ('Fishball.Card' -as [type])) { Add-Type -TypeDefinition $src -Language CSharp }

function Inner($e) {
    $x = $e.Exception
    while ($x.InnerException) { $x = $x.InnerException }
    $x.Message
}
function Letter($part) { "$($part.DriveLetter)".Trim([char]0).Trim() }

if ($ImageMode) {
    # ------------------------------------------------------------ image file
    $img = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ImageFile)
    Step '2/6  Card image'
    Say "  $img, $ImageSizeMB MB"
    Step '3/6  Backup: not needed for an image file'
    Step '4/6  (no card is erased)'
    $target = [Fishball.Target]::OpenImage($img, $ImageSizeMB * 1MB)
    $diskNo = -1
} else {
    if (-not $IsWin) { Fail 'writing a card with this script needs Windows. On macOS and Linux, write it from the repo: sudo ./devkit write-card --from FOLDER /dev/...  (or use -ImageFile here to make a card image instead).' }

    # ------------------------------------------------------------- 2. which card
    Step '2/6  Choosing the card'
    $hereDisk = -1
    if ($Folder -match '^([A-Za-z]):') {
        try { $hereDisk = (Get-Partition -DriveLetter $Matches[1] -ErrorAction Stop).DiskNumber } catch { }
    }
    $all = @(Get-Disk)
    $buses = @('USB', 'SD', 'MMC')
    # CI only: lets the Windows job write a virtual disk and skip the question.
    $ci = $env:FISHBALL_WRITE_CARD_CI -eq '1'
    if ($ci) { $buses += 'File Backed Virtual' }
    $cards = @($all | Where-Object {
        -not $_.IsSystem -and -not $_.IsBoot -and $_.Number -ne $hereDisk -and
        $_.Size -ge 1GB -and $_.Size -le 256GB -and (@($buses) -contains "$($_.BusType)")
    })
    function Describe($d) {
        $parts = @(Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue | ForEach-Object {
            $v = $_ | Get-Volume -ErrorAction SilentlyContinue
            $l = Letter $_
            $l = if ($l) { "${l}:" } else { '-' }
            if ($v -and $v.FileSystem) { "$l '$($v.FileSystemLabel)' $($v.FileSystem)" } else { "$l (not readable by Windows)" }
        })
        $what = if ($parts.Count) { $parts -join ', ' } else { 'no partitions' }
        '  Disk {0,-3} {1,-34} {2,8}  {3,-4}  {4}' -f $d.Number, "$($d.FriendlyName)", (GB $d.Size), "$($d.BusType)", $what
    }
    if ($cards.Count -eq 0) {
        Say '  No SD card found. Disks on this PC (none of them will be written):'
        foreach ($d in $all) { Say (Describe $d) }
        Fail 'put the microSD card in the reader (for a USB reader: plug it in first), wait a few seconds and run this again. A card over 256 GB is refused on purpose.'
    }
    Say '  Cards and USB disks this script can write:'
    foreach ($d in $cards) { Say (Describe $d) }
    Say '  (Never listed: the disk Windows runs from, the disk this folder is on, anything'
    Say '  under 1 GB or over 256 GB. Unplug the board itself while you do this: its'
    Say '  factory firmware shows up as a small USB drive.)'
    if ($DiskNumber -lt 0) {
        Say ''
        $ans = Read-Host '  Type the disk number of your SD card'
        if ($ans -notmatch '^\s*\d+\s*$') { Say '  Stopped. Nothing was written.'; Finish 1 }
        $DiskNumber = [int]$ans
    }
    $disk = $cards | Where-Object { $_.Number -eq $DiskNumber }
    if (-not $disk) { Fail "disk $DiskNumber is not in the list above, so this script will not write it." }
    if ($disk.IsReadOnly) { Fail "disk $DiskNumber is write-protected. If it is a full-size SD adapter, slide its lock switch up (away from the contacts) and run again." }
    if ($disk.Size -lt 1GB) { Fail "disk $DiskNumber is too small: the card needs at least 1 GB." }
    $diskNo = $disk.Number

    # ------------------------------------------------------------- 3. backup
    Step '3/6  Backing up what is on the card now'
    $backup = Join-Path $Folder "card-backup-$Stamp"
    $parts = @(Get-Partition -DiskNumber $diskNo -ErrorAction SilentlyContinue)
    $copied = 0; $skipped = @()
    if ($parts.Count -eq 0) { Say '  The card has no partitions: nothing to back up.' }
    foreach ($p in $parts) {
        $v = $p | Get-Volume -ErrorAction SilentlyContinue
        if (-not $v -or -not $v.FileSystem) {
            $skipped += $p.PartitionNumber
            Say "  partition $($p.PartitionNumber): not readable by Windows (a Linux partition, for example), so not backed up"
            continue
        }
        $l = Letter $p
        if (-not $l) {
            try {
                Add-PartitionAccessPath -DiskNumber $diskNo -PartitionNumber $p.PartitionNumber -AssignDriveLetter -ErrorAction Stop
                Start-Sleep -Seconds 2
                $l = Letter (Get-Partition -DiskNumber $diskNo -PartitionNumber $p.PartitionNumber)
            } catch { }
        }
        if (-not $l) { Fail "partition $($p.PartitionNumber) has files but Windows would not give it a drive letter, so it cannot be backed up. Give it one in Disk Management and run again." }
        $label = if ($v.FileSystemLabel) { $v.FileSystemLabel -replace '[^\w\-]', '_' } else { 'nolabel' }
        $dest = Join-Path $backup ("partition{0}-{1}" -f $p.PartitionNumber, $label)
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        $skip = '\\System Volume Information(\\|$)|\\\$RECYCLE\.BIN(\\|$)'
        $srcFiles = @(Get-ChildItem -LiteralPath "${l}:\" -Recurse -Force -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch $skip })
        $bytes = ($srcFiles | Measure-Object -Property Length -Sum).Sum
        if ($null -eq $bytes) { $bytes = 0 }
        $free = $null
        try { $free = (Get-PSDrive -Name $Folder.Substring(0, 1) -ErrorAction Stop).Free } catch { }
        if ($free -and $bytes -gt $free) { Fail "the backup needs $(GB $bytes) and the drive holding $Folder has $(GB $free) free." }
        foreach ($i in Get-ChildItem -LiteralPath "${l}:\" -Force | Where-Object { $_.FullName -notmatch $skip }) {
            Copy-Item -LiteralPath $i.FullName -Destination $dest -Recurse -Force
        }
        $got = @(Get-ChildItem -LiteralPath $dest -Recurse -Force -File)
        if ($got.Count -ne $srcFiles.Count) { Fail "the backup of ${l}: copied $($got.Count) of $($srcFiles.Count) files. Nothing was erased." }
        Say ('  {0}: {1} files, {2:N1} MB  ->  {3}' -f $l, $got.Count, ($bytes / 1MB), $dest)
        $copied += $got.Count
    }
    if ($copied -gt 0) {
        $readme = @(
            'This is what was on the SD card before write-card.cmd replaced it.',
            '',
            'To go back to it: format a microSD card as FAT32 with one partition',
            '(Windows: right-click the card in Explorer, Format, FAT32), copy the',
            'files from the partition1-... folder onto it, and put it in the board.',
            'If there are several partitionN folders, the card had several',
            'partitions; recreate them in the same order before copying.'
        )
        Set-Content -LiteralPath (Join-Path $backup 'README.txt') -Value $readme -Encoding ASCII
        Say "  Backup complete: $backup"
    }

    # ------------------------------------------------------------- 4. confirm
    Step '4/6  Last check'
    Say (Describe $disk)
    Say "  EVERYTHING on disk $diskNo will be erased."
    $ans = if ($ci) { 'ERASE' } else { Read-Host '  Type ERASE (capitals) to write the card, anything else to stop' }
    if ($ans -cne 'ERASE') { Say '  Stopped. Nothing was written.'; Finish 0 }

    $vols = @(Get-Partition -DiskNumber $diskNo -ErrorAction SilentlyContinue |
        ForEach-Object { $_.AccessPaths } | Where-Object { $_ -like '\\?\Volume*' } | ForEach-Object { $_.TrimEnd('\') })
    try { $target = [Fishball.Target]::OpenDisk($diskNo, [string[]]$vols) }
    catch { Fail ("could not open the card for writing: " + (Inner $_) + ". Close any Explorer window showing the card and run again.") }
}

# ----------------------------------------------------------------- 5. write
Step '5/6  Writing'
$t0 = Get-Date
$ok = $false
try {
    [Fishball.Card]::Write($target, $Folder, [Action[string]] { param($s) Write-Host "  $s" })
    $secs = ((Get-Date) - $t0).TotalSeconds
    Say ('  wrote {0:N0} MB in {1:N0} s' -f ($target.BytesWritten / 1MB), $secs)

    Step '6/6  Verifying: reading the card back'
    $script:pct = -1
    $ok = $target.Verify([Action[long, long]] {
        param($done, $total)
        $n = [int][Math]::Floor($done * 100 / $total)
        if ($n -ne $script:pct) { $script:pct = $n; Write-Host -NoNewline ("`r  {0,3}%  " -f $n) }
    })
    Write-Host ''
} catch {
    try { $target.Dispose() } catch { }
    $msg = Inner $_
    if ($ImageMode) { Fail "writing the image failed: $msg" }
    Fail "writing the card failed: $msg`nThe card is probably blank now (your backup is safe). Run this again; if it fails twice, try another card or card reader."
}
$target.Dispose()
if (-not $ok) { Fail 'what was read back differs from what was written. The card or the reader is faulty: try another card.' }
Say ('  OK: all {0:N0} MB read back identical' -f ($target.VerifiedBytes / 1MB))

if (-not $ImageMode) {
    # Windows re-reads the new partition table; check the boot files through it.
    try { Update-Disk -Number $diskNo -ErrorAction SilentlyContinue } catch { }
    Start-Sleep -Seconds 3
    $l = ''
    for ($i = 0; $i -lt 10 -and -not $l; $i++) {
        $p1 = Get-Partition -DiskNumber $diskNo -PartitionNumber 1 -ErrorAction SilentlyContinue
        if ($p1) {
            $l = Letter $p1
            if (-not $l) { try { Add-PartitionAccessPath -DiskNumber $diskNo -PartitionNumber 1 -AssignDriveLetter -ErrorAction Stop } catch { } }
        }
        if (-not $l) { Start-Sleep -Seconds 1 }
    }
    if ($l) {
        foreach ($f in @('BOOT.bin', 'uImage', 'devicetree.dtb', 'uEnv.txt')) {
            $h = (Get-FileHash -LiteralPath "${l}:\$f" -Algorithm SHA256).Hash.ToLower()
            if ($h -ne $want[$f]) { Fail "${l}:\$f differs from the release after writing. Try another card." }
        }
        Say "  OK: Windows reads the boot partition as ${l}: FISHBOOT, and all four boot files match"
        if (-not $ci) { try { (New-Object -ComObject Shell.Application).Namespace(17).ParseName("${l}:").InvokeVerb('Eject') } catch { } }
    } else {
        Say '  (Windows did not show the boot partition yet; the read-back above already checked it.)'
    }
}

Step 'Done'
if ($ImageMode) {
    Say "  Card image: $img"
    Say '  Write it to a card with Rufus or balenaEtcher, or check it with:'
    Say '  fsck.vfat / e2fsck on Linux (boot partition at sector 2048, root at 264192).'
    Finish 0
}
Say '  The card is ready. You can take it out of the reader now.'
Say ''
Say '  Next:'
Say '   1. With the board unpowered, put the card in it.'
Say '   2. Use BOTH USB-C sockets: one to a mains USB charger, the other to this PC.'
Say '      On laptop USB power alone the board can hang.'
Say '   3. After about a minute it answers at 192.168.2.1 over the USB cable.'
Say '      Check from this PC, in a Command Prompt:'
Say '          ssh root@192.168.2.1          (password: analog)'
Say '          cat /etc/os-release           (says Debian GNU/Linux 13)'
Say '   4. SDR software connects to ip:192.168.2.1 as before.'
Say ''
Say '  Never update this board with DFU or through a "PlutoSDR" USB drive: that'
Say '  route is meant for a different board (the ADALM-Pluto) and has bricked'
Say '  boards like this one. Change firmware by rewriting the card, as here.'
if ($copied -gt 0) { Say "  To go back to the old firmware: $backup\README.txt" }
Finish 0
