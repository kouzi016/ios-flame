#!/usr/bin/env python3
"""Raw HFS+ image -> Android sparse image that skips the volume's free space.

  hfs-sparse.py ROOT.img OUT.simg [--start BLOCK]

img2simg stores every all-zero block as a FILL chunk, and Pixel 4's bootloader
really writes them: the ~4.3 GiB of free space at the end of ios16-root.img
took 12+ minutes inside one `fastboot flash` piece, which looked like a hang
at the last chunk (several wrong "stuck" diagnoses, see NOTES.md). HFS+ does
not care what a free block holds, so this tool reads the allocation bitmap
and emits DONT_CARE for unallocated blocks. Allocated blocks (RAW data and
allocated all-zero blocks) are written as before; the alternate volume header
in the last block is allocated and is kept.

--start BLOCK (4 KiB blocks) emits DONT_CARE for everything before it, for
rewriting only the end of a volume that was flashed once already.

Needs `img2simg` (android-sdk-libsparse-utils) on PATH, or pass an existing
sparse image of the same volume with --simg.
"""
import argparse, os, struct, subprocess, sys, tempfile

BS = 4096
RAW, FILL, DONT_CARE = 0xcac1, 0xcac2, 0xcac3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img'); ap.add_argument('out')
    ap.add_argument('--start', type=int, default=0)
    ap.add_argument('--simg', help='img2simg output of IMG, if already made')
    a = ap.parse_args()

    f = open(a.img, 'rb')
    f.seek(1024)
    vh = f.read(512)
    if vh[:2] != b'H+' and vh[:2] != b'HX':
        sys.exit('not an HFS+ volume')
    if struct.unpack('>I', vh[40:44])[0] != BS:
        sys.exit('HFS+ block size is not 4096')
    tb = struct.unpack('>I', vh[44:48])[0]
    bm = b''
    for i in range(8):                       # allocationFile ForkData extents
        s, c = struct.unpack('>II', vh[128 + 8 * i:136 + 8 * i])
        if c:
            f.seek(s * BS)
            bm += f.read(c * BS)
    if len(bm) * 8 < tb:
        sys.exit('allocation file spans more than 8 extents: not handled')
    alloc = lambda b: (bm[b >> 3] >> (7 - (b & 7))) & 1

    simg = a.simg
    tmp = None
    if not simg:
        tmp = tempfile.NamedTemporaryFile(suffix='.simg', delete=False)
        tmp.close()
        simg = tmp.name
        subprocess.check_call(['img2simg', a.img, simg])

    fi = open(simg, 'rb')
    magic, maj, minr, fhs, chs, bs, total, tc, crc = struct.unpack('<IHHHHIIII', fi.read(28))
    assert bs == BS and total == tb, 'sparse image does not match the volume'
    fo = open(a.out, 'wb')
    fo.write(b'\0' * 28)
    n = 0

    def put(ct, csz, payload=b''):
        nonlocal n
        fo.write(struct.pack('<HHII', ct, 0, csz, 12 + len(payload)))
        fo.write(payload)
        n += 1

    if a.start:
        put(DONT_CARE, a.start)
    pos = kept = dropped = 0
    for _ in range(tc):
        ct, _, csz, tsz = struct.unpack('<HHII', fi.read(12))
        payload = fi.read(tsz - 12)
        end = pos + csz
        lo = max(pos, a.start)
        if end > lo:
            skip = lo - pos
            if ct == RAW:
                put(RAW, end - lo, payload[skip * BS:])
            elif ct == FILL:
                b = lo
                while b < end:
                    al = alloc(b)
                    e = b
                    while e < end and alloc(e) == al:
                        e += 1
                    if al:
                        put(FILL, e - b, payload); kept += e - b
                    else:
                        put(DONT_CARE, e - b); dropped += e - b
                    b = e
        pos = end
    fo.seek(0)
    fo.write(struct.pack('<IHHHHIIII', magic, maj, minr, fhs, chs, BS, tb, n, 0))
    fo.close()
    if tmp:
        os.unlink(tmp.name)
    print(f'{a.out}: {os.path.getsize(a.out)} bytes, {n} chunks; '
          f'zero blocks kept {kept}, skipped (free) {dropped} = {dropped * BS / 2**30:.2f} GiB')


if __name__ == '__main__':
    main()
