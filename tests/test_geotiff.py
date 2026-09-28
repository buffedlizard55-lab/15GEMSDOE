"""The dependency-free writer must produce a file that real GDAL reads as the
competition requires, and the submission validator must reject the failure the
user actually hit ("Predicted values must be in range [0, 1]").
"""

from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gems.geotiff import read_geotiff, write_float32_geotiff  # noqa: E402

ROWS = [[float("nan"), 0.0, 0.25, 1.0],
        [1.0, 0.5, 0.0, float("nan")]]


def test_round_trip_through_our_reader():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.tif")
        man = write_float32_geotiff(p, ROWS, origin_x=243350.0, origin_y=4508550.0)
        r = read_geotiff(p)
        assert r["width"] == 4 and r["height"] == 2
        assert r["sample_format"] == 3 and r["bits_per_sample"] == 32
        assert r["samples_per_pixel"] == 1 and r["compression"] == 8
        assert r["epsg"] == 32611
        assert r["origin_x"] == 243350.0 and r["origin_y"] == 4508550.0
        assert r["pixel_x"] == 100.0 and r["pixel_y"] == 100.0
        assert r["nodata"] == "nan"
        got = r["rows"]
        assert np.isnan(got[0][0]) and got[0][1] == 0.0 and got[0][2] == 0.25
        assert got[1][0] == 1.0 and got[1][1] == 0.5
        assert np.isnan(got[1][3])
        assert man["bytes"] > 0


def test_rasterio_reads_it_correctly():
    try:
        import rasterio
    except ImportError:
        print("skip: rasterio not installed")
        return
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.tif")
        write_float32_geotiff(p, ROWS, origin_x=243350.0, origin_y=4508550.0)
        with rasterio.open(p) as s:
            assert s.count == 1 and s.dtypes[0] == "float32"
            assert str(s.crs) == "EPSG:32611"
            assert list(s.res) == [100.0, 100.0]
            assert (s.width, s.height) == (4, 2)
            assert s.transform.a == 100.0 and s.transform.e == -100.0
            assert s.transform.c == 243350.0 and s.transform.f == 4508550.0
            a = s.read(1)
            assert np.isnan(a[0, 0]) and a[0, 1] == 0.0
            assert a[1, 0] == 1.0 and np.isnan(a[1, 3])


def test_validator_rejects_out_of_range_values():
    try:
        import rasterio
    except ImportError:
        print("skip: rasterio not installed")
        return
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    from validate_submission import validate
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.tif")
        bad = os.path.join(d, "bad.tif")
        npy = np.array([[np.nan, 0.0], [1.0, 0.5]], dtype=np.float32)
        prof = dict(driver="GTiff", height=2, width=2, count=1, dtype="float32",
                    crs="EPSG:32611", transform=rasterio.transform.from_origin(243350, 4508550, 100, 100))
        with rasterio.open(good, "w", **prof) as dst:
            dst.write(npy, 1)
        with rasterio.open(bad, "w", **prof) as dst:
            dst.write(npy * 2.0, 1)     # values above 1 -> 2.0
        assert validate(good, None)["ok"] is True
        res = validate(bad, None)
        assert res["ok"] is False
        assert res["checks"]["R4c_values_in_unit_interval"]["passed"] is False


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS %s" % name)
            except AssertionError as exc:
                fails += 1
                print("FAIL %s  %s" % (name, exc))
    raise SystemExit(1 if fails else 0)
