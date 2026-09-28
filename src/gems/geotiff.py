"""Minimal, dependency-free GeoTIFF reader/writer for float32 single-band rasters.

Why this exists: the competition requires a single-band float32 GeoTIFF in
EPSG:32611 at 100 m with the same bounds as the training data (problem
description, "Submission format": same CRS, same resolution, same bounds,
outside values null/nan, single 32-bit float layer with values 0-1).  The
submission generator must be runnable on any machine with a stock Python, so the
writer is written against TIFF 6.0 with a hand-built tag table rather than a GDAL
stack.  The reader covers the subset the writer emits plus common single-band
float32/int8 rasters.

Tags emitted, and why each is required:

    256 ImageWidth              257 ImageLength
    258 BitsPerSample = 32       259 Compression = 8 (Adobe deflate)
    262 Photometric = 1          273/279 StripOffsets / StripByteCounts
    277 SamplesPerPixel = 1      278 RowsPerStrip
    282/283 X/YResolution        284 PlanarConfiguration = 1
    339 SampleFormat = 3 (IEEE float)  -- without this, readers treat the
                                           payload as unsigned integers
    33550 ModelPixelScale              -- (100, 100, 0)
    33922 ModelTiepoint                -- top-left corner in map units
    34735 GeoKeyDirectory              -- projected / PixelIsArea / EPSG:32611
    42113 GDAL_NODATA = "nan"          -- the required NaN outside the footprint

Layout written: header(8) -> IFD -> out-of-line tag values -> strip payloads.
The value-area size is fixed before the payload offset is known, so strip
offsets are computed in one pass with no back-patching.
"""

from __future__ import annotations

import struct
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

TAG_IMAGE_WIDTH = 256
TAG_IMAGE_LENGTH = 257
TAG_BITS_PER_SAMPLE = 258
TAG_COMPRESSION = 259
TAG_PHOTOMETRIC = 262
TAG_STRIP_OFFSETS = 273
TAG_SAMPLES_PER_PIXEL = 277
TAG_ROWS_PER_STRIP = 278
TAG_STRIP_BYTE_COUNTS = 279
TAG_X_RESOLUTION = 282
TAG_Y_RESOLUTION = 283
TAG_PLANAR_CONFIG = 284
TAG_SAMPLE_FORMAT = 339
TAG_MODEL_PIXEL_SCALE = 33550
TAG_MODEL_TIEPOINT = 33922
TAG_GEO_KEY_DIRECTORY = 34735
TAG_GDAL_NODATA = 42113

GT_MODEL_TYPE = 1024
GTRaster_TYPE = 1025
PROJECTED_CS_TYPE = 3072
PROJ_LINEAR_UNITS = 3076

TYPE_ASCII = 2
TYPE_SHORT = 3
TYPE_LONG = 4
TYPE_DOUBLE = 12

_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 8: 2, 9: 4, 11: 4, 12: 8}
_FMT = {3: "H", 4: "I", 12: "d"}  # struct codes, packed little-endian


def _entry_count(entries, tag):
    for t, ttype, vals in entries:
        if t == tag:
            return len(vals)
    raise KeyError(tag)


def write_float32_geotiff(
    path: str,
    data: Sequence[Sequence[float]],
    *,
    origin_x: float,
    origin_y: float,
    pixel_x: float = 100.0,
    pixel_y: float = 100.0,
    epsg: int = 32611,
    nodata_nan: bool = True,
    rows_per_strip: int = 16,
) -> Dict[str, object]:
    """Write `data` (row 0 = north) as a single-band float32 deflate GeoTIFF.

    NaN values are preserved and declared via GDAL_NODATA.  Returns a manifest.
    """
    height = len(data)
    width = len(data[0]) if height else 0
    if height == 0 or width == 0:
        raise ValueError("empty raster")

    rows_per_strip = max(1, min(int(rows_per_strip), height))
    strips: List[bytes] = []
    for y0 in range(0, height, rows_per_strip):
        buf = bytearray()
        for y in range(y0, min(height, y0 + rows_per_strip)):
            row = data[y]
            if len(row) != width:
                raise ValueError("ragged rows at y=%d" % y)
            buf += struct.pack("<%df" % width, *row)
        strips.append(zlib.compress(bytes(buf), 6))
    n_strips = len(strips)

    # ---- tag values that are fully known now -------------------------------
    entries: List[Tuple[int, int, Sequence[object]]] = [
        (TAG_IMAGE_WIDTH, TYPE_LONG, [width]),
        (TAG_IMAGE_LENGTH, TYPE_LONG, [height]),
        (TAG_BITS_PER_SAMPLE, TYPE_SHORT, [32]),
        (TAG_COMPRESSION, TYPE_SHORT, [8]),
        (TAG_PHOTOMETRIC, TYPE_SHORT, [1]),
        (TAG_SAMPLES_PER_PIXEL, TYPE_SHORT, [1]),
        (TAG_ROWS_PER_STRIP, TYPE_LONG, [rows_per_strip]),
        (TAG_PLANAR_CONFIG, TYPE_SHORT, [1]),
        (TAG_SAMPLE_FORMAT, TYPE_SHORT, [3]),
        (TAG_X_RESOLUTION, TYPE_DOUBLE, [1.0 / pixel_x]),
        (TAG_Y_RESOLUTION, TYPE_DOUBLE, [1.0 / pixel_y]),
        (TAG_MODEL_PIXEL_SCALE, TYPE_DOUBLE, [pixel_x, pixel_y, 0.0]),
        (TAG_MODEL_TIEPOINT, TYPE_DOUBLE, [0.0, 0.0, 0.0, origin_x, origin_y, 0.0]),
        (TAG_GEO_KEY_DIRECTORY, TYPE_SHORT, [
            1, 1, 0, 4,
            GT_MODEL_TYPE, 0, 1, 1,        # 1 = projected
            GTRaster_TYPE, 0, 1, 1,        # 1 = PixelIsArea
            PROJECTED_CS_TYPE, 0, 1, epsg,
            PROJ_LINEAR_UNITS, 0, 1, 9001,  # 9001 = metre
        ]),
    ]
    if nodata_nan:
        entries.append((TAG_GDAL_NODATA, TYPE_ASCII, "nan"))
    # strip offsets/counts are computed below but their SIZES are known here
    entries.append((TAG_STRIP_OFFSETS, TYPE_LONG, [0] * n_strips))
    entries.append((TAG_STRIP_BYTE_COUNTS, TYPE_LONG, [0] * n_strips))
    entries.sort(key=lambda e: e[0])

    def encode(ttype: int, vals) -> bytes:
        if ttype == TYPE_ASCII:
            return str(vals).encode("ascii") + b"\x00"
        seq = list(vals)
        return struct.pack("<%d%s" % (len(seq), _FMT[ttype]), *seq)

    def raw_size(ttype: int, vals: Sequence[object]) -> int:
        return len(encode(ttype, vals))

    ifd_offset = 8
    ifd_size = 2 + 12 * len(entries) + 4
    value_off = ifd_offset + ifd_size

    # value area layout: every entry whose encoded value exceeds 4 bytes
    out_of_line: Dict[int, int] = {}
    cursor = value_off
    for tag, ttype, vals in entries:
        if raw_size(ttype, vals) > 4:
            if cursor % 2:
                cursor += 1
            out_of_line[tag] = cursor
            cursor += raw_size(ttype, vals)
    payload_off = cursor
    if payload_off % 2:
        payload_off += 1

    strip_offsets: List[int] = []
    strip_counts: List[int] = []
    cur = payload_off
    for s in strips:
        strip_offsets.append(cur)
        strip_counts.append(len(s))
        cur += len(s)

    # now fill the two placeholder entries and re-encode everything
    final: List[Tuple[int, int, Sequence[object]]] = []
    for tag, ttype, vals in entries:
        if tag == TAG_STRIP_OFFSETS:
            vals = strip_offsets
        elif tag == TAG_STRIP_BYTE_COUNTS:
            vals = strip_counts
        final.append((tag, ttype, vals))

    out = bytearray(struct.pack("<2sHI", b"II", 42, ifd_offset))
    out += struct.pack("<H", len(final))
    for tag, ttype, vals in final:
        enc = encode(ttype, vals)
        if len(enc) <= 4:
            out += struct.pack("<HHI", tag, ttype, len(vals)) + enc + b"\x00" * (4 - len(enc))
        else:
            out += struct.pack("<HHII", tag, ttype, len(vals), out_of_line[tag])
    out += struct.pack("<I", 0)
    assert len(out) == value_off, (len(out), value_off)

    for tag, ttype, vals in final:
        if raw_size(ttype, vals) > 4:
            while len(out) < out_of_line[tag]:
                out += b"\x00"
            assert len(out) == out_of_line[tag], (tag, len(out), out_of_line[tag])
            out += encode(ttype, vals)
    while len(out) < payload_off:
        out += b"\x00"
    assert len(out) == payload_off, (len(out), payload_off)
    for s in strips:
        out += s

    with open(path, "wb") as fh:
        fh.write(out)

    return {"path": path, "width": width, "height": height, "epsg": epsg,
            "origin_x": origin_x, "origin_y": origin_y,
            "pixel_x": pixel_x, "pixel_y": pixel_y, "bytes": len(out),
            "strips": n_strips, "rows_per_strip": rows_per_strip}


# --------------------------------------------------------------------------
# reader
# --------------------------------------------------------------------------
def read_ifd(buf: bytes, offset: int):
    (count,) = struct.unpack_from("<H", buf, offset)
    entries: Dict[int, Tuple[int, int, bytes]] = {}
    for i in range(count):
        tag, ttype, cnt = struct.unpack_from("<HHI", buf, offset + 2 + 12 * i)
        size = _SIZES[ttype] * cnt
        if size <= 4:
            raw = buf[offset + 2 + 12 * i + 8: offset + 2 + 12 * i + 8 + size]
        else:
            (valoff,) = struct.unpack_from("<I", buf, offset + 2 + 12 * i + 8)
            raw = buf[valoff: valoff + size]
        entries[tag] = (ttype, cnt, raw)
    (next_ifd,) = struct.unpack_from("<I", buf, offset + 2 + 12 * count)
    return entries, next_ifd


def decode_value(ttype: int, cnt: int, raw: bytes):
    if ttype == TYPE_ASCII:
        return raw.rstrip(b"\x00").decode("ascii", "replace")
    fmt = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d"}[ttype]
    values = list(struct.unpack("<%d%s" % (cnt, fmt), raw[: _SIZES[ttype] * cnt]))
    return values[0] if cnt == 1 else values


def read_geotiff(path: str, decode_pixels: bool = True) -> Dict[str, object]:
    """Read the subset of GeoTIFF this project writes (deflate float32, strips)."""
    with open(path, "rb") as fh:
        buf = fh.read()
    magic, version = struct.unpack_from("<2sH", buf, 0)
    if magic != b"II" or version != 42:
        raise ValueError("not a little-endian TIFF: %r %r" % (magic, version))
    (ifd_off,) = struct.unpack_from("<I", buf, 4)
    entries, _ = read_ifd(buf, ifd_off)

    def val(tag, default=None):
        if tag not in entries:
            return default
        return decode_value(*entries[tag])

    width = val(TAG_IMAGE_WIDTH)
    height = val(TAG_IMAGE_LENGTH)
    compression = val(TAG_COMPRESSION, 1)
    sample_format = val(TAG_SAMPLE_FORMAT, 1)
    bits = val(TAG_BITS_PER_SAMPLE, 8)
    spp = val(TAG_SAMPLES_PER_PIXEL, 1)
    rps = val(TAG_ROWS_PER_STRIP, height)
    offs = val(TAG_STRIP_OFFSETS)
    counts = val(TAG_STRIP_BYTE_COUNTS)
    scale = val(TAG_MODEL_PIXEL_SCALE)
    tie = val(TAG_MODEL_TIEPOINT)
    geokeys = val(TAG_GEO_KEY_DIRECTORY)
    nodata = val(TAG_GDAL_NODATA)

    if isinstance(offs, int):
        offs, counts = [offs], [counts]

    raw = bytearray()
    for o, c in zip(offs, counts):
        chunk = buf[o: o + c]
        raw += zlib.decompress(chunk) if compression in (8, 32946) else chunk

    n = width * height * spp
    if bits == 32 and sample_format == 3:
        data = list(struct.unpack_from("<%df" % n, bytes(raw), 0))
    elif bits == 32:
        data = list(struct.unpack_from("<%dI" % n, bytes(raw), 0))
    elif bits == 16:
        data = list(struct.unpack_from("<%dH" % n, bytes(raw), 0))
    elif bits == 8:
        data = list(struct.unpack_from("<%dB" % n, bytes(raw), 0))
    else:
        raise ValueError("unsupported bit depth %r" % bits)

    epsg = None
    if geokeys:
        keys = list(geokeys)[4:]
        for i in range(0, len(keys) - 3, 4):
            if keys[i] == PROJECTED_CS_TYPE:
                epsg = keys[i + 3]

    out: Dict[str, object] = {
        "width": width, "height": height, "epsg": epsg,
        "origin_x": tie[3] if tie else None,
        "origin_y": tie[4] if tie else None,
        "pixel_x": scale[0] if scale else None,
        "pixel_y": scale[1] if scale else None,
        "nodata": nodata, "compression": compression,
        "sample_format": sample_format, "bits_per_sample": bits,
        "samples_per_pixel": spp, "rows_per_strip": rps,
        "bounding_box": None,
    }
    if tie and scale and width and height:
        x0, y0 = tie[3], tie[4]
        out["bounding_box"] = (x0, y0 - height * scale[1], x0 + width * scale[0], y0)
    if decode_pixels:
        out["rows"] = [data[i * width:(i + 1) * width] for i in range(height)]
    return out
