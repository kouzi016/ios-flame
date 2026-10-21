#!/usr/bin/env python3
"""Check the flame constants in mkadt.py and the shim against a live FDT.

The values in this port come from Google's public device trees, not from a
phone. Run this on the live.dts that tools/flame-dump.sh pulled; every
MISMATCH must be fixed (mkadt.py, shim/*.h, xnu/patches/0082) before the
first fastboot boot.  Usage:  flame-check.py dumps/<date>/live.dts
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkadt  # noqa: E402

SHIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../shim')


def parse(text):
    """{path: {prop: raw value}} from dtc's text output (two cells per address)."""
    nodes, stack = {}, []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r'^(?:[\w,.-]+:\s*)*([\w,.@+-]+|/)\s*\{$', line)
        if m:
            stack.append(m.group(1))
            nodes.setdefault('/'.join(stack).replace('//', '/'), {})
            continue
        if line == '};':
            stack.pop()
            continue
        m = re.match(r'^([\w,.#+-]+)\s*=\s*(.*);$', line)
        if m and stack:
            nodes['/'.join(stack).replace('//', '/')][m.group(1)] = m.group(2)
    return nodes


def cells(raw):
    return [int(c, 16) for c in re.findall(r'0x[0-9a-fA-F]+', raw or '')]


def pairs(raw):
    c = cells(raw)
    return [((c[i] << 32) | c[i + 1], (c[i + 2] << 32) | c[i + 3]) for i in range(0, len(c) - 3, 4)]


def shim_define(name):
    for f in os.listdir(SHIM):
        if f.endswith(('.h', '.c')):
            m = re.search(r'#define\s+%s\s+(0x[0-9a-fA-F]+|\d+)' % name, open(os.path.join(SHIM, f)).read())
            if m:
                return int(m.group(1), 0)
    raise SystemExit(f'{name} not defined in shim/')


def main(path):
    nodes = parse(open(path).read())
    bad = 0

    def check(what, ok, detail):
        nonlocal bad
        bad += not ok
        print(f'{"OK      " if ok else "MISMATCH"} {what}: {detail}')

    mem = [r for p, n in nodes.items() if re.fullmatch(r'/memory(@\w+)?', p) for r in pairs(n.get('reg'))]
    print('DDR from /memory:', ', '.join(f'{b:#x}+{s:#x}' for b, s in mem) or 'none')
    reserved = [(p, b, s) for p, n in nodes.items() if p.startswith('/reserved-memory/')
                for b, s in pairs(n.get('reg'))]

    # Only the --highmem range is booted on the phone; the low one is informational.
    for label, base, size in (('kernel RAM (--highmem)', mkadt.HIGH_PHYS_BASE, mkadt.HIGH_MEM_SIZE),):
        # DDR banks may be adjacent (0xc0000000+2G, 0x140000000+3G): walk them.
        cur = base
        while cur < base + size:
            nxt = [b + s for b, s in mem if b <= cur < b + s]
            if not nxt:
                break
            cur = max(nxt)
        inside = cur >= base + size
        hits = [p.split('/')[-1] for p, b, s in reserved if b < base + size and base < b + s]
        check(label, inside and not hits,
              f'{base:#x}+{size:#x} ' + ('inside DDR' if inside else 'NOT inside DDR') +
              (f', overlaps {", ".join(hits)}' if hits else ''))

    splash = [(p, b, s) for p, b, s in reserved if 'splash' in p]
    fb = shim_define('FB_BASE')
    check('splash framebuffer', any(b == fb == mkadt.FB for _, b, _ in splash),
          f'shim {fb:#x}, mkadt {mkadt.FB:#x}, DT ' + (', '.join(f'{p.split("/")[-1]}={b:#x}+{s:#x}' for p, b, s in splash) or 'none'))
    w = re.search(r'#define\s+FB_W\s+(\d+)', open(os.path.join(SHIM, 'console.h')).read()).group(1)
    h = re.search(r'#define\s+FB_H\s+(\d+)', open(os.path.join(SHIM, 'console.h')).read()).group(1)
    panel = [(n.get('qcom,mdss-dsi-panel-width'), n.get('qcom,mdss-dsi-panel-height'), p)
             for p, n in nodes.items() if 'qcom,mdss-dsi-panel-width' in n]
    sizes = {(cells(pw)[0], cells(ph)[0]) for pw, ph, _ in panel if cells(pw) and cells(ph)}
    check('panel size', (int(w), int(h)) in sizes or not sizes,
          f'shim {w}x{h}, DT ' + (', '.join(f'{a}x{b}' for a, b in sorted(sizes)) or 'no panel node (check ABL cmdline)'))

    def has_node(pattern):
        return [p for p in nodes if re.search(pattern, p)]

    for what, pattern in (('GICD', r'interrupt-controller@%x$' % mkadt.GICD),
                          ('UFS host', r'ufshc@%x$' % mkadt.UFS),
                          ('PS_HOLD', r'@%x$' % shim_define('PSHOLD'))):
        found = has_node(pattern)
        check(what, bool(found), found[0] if found else f'no node matching {pattern}')

    imem = shim_define('IMEM_RESTART_REASON')
    rr = [p for p in has_node(r'restart_reason@65c$') if ('%x' % (imem - 0x65c)) in p]
    check('IMEM restart_reason', bool(rr), rr[0] if rr else f'{imem:#x} not found (search restart_reason)')

    fts = [p for p, n in nodes.items() if 'st,fts' in n.get('compatible', '')]
    check('touch IC (ST FTM5, SPI)', bool(fts), fts[0] if fts else 'no "st,fts" node: touch plan in FLAME.md is wrong')

    print(f'\n{bad} mismatch(es)')
    return 1 if bad else 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
