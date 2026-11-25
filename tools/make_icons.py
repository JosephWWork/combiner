"""Generate the toolbar icons (no dependencies): two nodes merging into one.

Usage: python3 tools/make_icons.py
Writes ParameterCombiner/resources/MergeDuplicates/{16x16,32x32,64x64}.png
"""
import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(__file__), '..', 'ParameterCombiner', 'resources', 'MergeDuplicates')
COLOR = (0, 120, 215)  # blue
SAMPLES = 4  # supersampling per axis for anti-aliasing

# Shapes in a 0..1 coordinate space.
NODES = [((0.2, 0.22), 0.14), ((0.2, 0.78), 0.14), ((0.8, 0.5), 0.17)]
LINES = [((0.2, 0.22), (0.8, 0.5)), ((0.2, 0.78), (0.8, 0.5))]
LINE_W = 0.09


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _inside(x, y):
    for (cx, cy), r in NODES:
        if math.hypot(x - cx, y - cy) <= r:
            return True
    return any(_seg_dist((x, y), a, b) <= LINE_W / 2 for a, b in LINES)


def _png(size):
    rows = []
    for py in range(size):
        row = bytearray([0])  # filter: none
        for px in range(size):
            hits = sum(_inside((px + (i + 0.5) / SAMPLES) / size, (py + (j + 0.5) / SAMPLES) / size)
                       for i in range(SAMPLES) for j in range(SAMPLES))
            row += bytes(COLOR) + bytes([round(255 * hits / SAMPLES ** 2)])
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows), 9))
            + chunk(b'IEND', b''))


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for size in (16, 32, 64):
        with open(os.path.join(OUT, f'{size}x{size}.png'), 'wb') as f:
            f.write(_png(size))
    print('wrote icons to', os.path.abspath(OUT))
