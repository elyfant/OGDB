#!/usr/bin/env python3
"""Ingest a Seaglider mission NetCDF into OGDB: mission metadata + surface track.

Target file format
------------------
The UW/APL binned *profile* product, e.g.
    sg560_Svinoy_section_5.0m_up_and_down_profile.nc
A `time` dimension where each record is one CTD *profile* (not a within-dive
timeseries) and a `depth` dimension of fixed bins. For an "Up and Down profile"
file the down cast and up cast of a single dive are two consecutive records, so
dive N == records (2N-2, 2N-1) zero-based; the two records of a dive carry
identical depth-average current (`u_da`/`v_da`), used here to sanity-check the
pairing.

input: std_mission_name (positional) -- see mission_ingest_common.

What it does
------------
1. Resolves the mission by std_mission_name, reads its missions.l2_file (this
   NetCDF), and from the file computes:
       launch_date / launch_latitude / launch_longitude   (start of first dive)
       end_date_science / recovery_date                    (end of last profile)
       recovery_latitude / recovery_longitude              (end of last profile)
       dives                                               (record count / 2)
       distance_km                                         (great-circle sum along
                                                            the surface track)
2. Surface track: for every dive, the first sample of that dive's down cast ->
   latitude, longitude, utc, temperature, salinity (shallowest finite bin),
   dacu, dacv. A final row is appended for the last surfacing so the track
   reaches the recovery position.
3. Overwrites those missions columns and UPSERTs the track, one transaction.
   l1_file / l2_file untouched. Dry-run by default; --commit to write.

Usage
-----
    DATABASE_URL=postgresql://... python scripts/ingest_seaglider_mission.py sg560_naco_svinoy_may2012
    DATABASE_URL=postgresql://... python scripts/ingest_seaglider_mission.py --commit sg560_naco_svinoy_may2012
"""
import numpy as np
from netCDF4 import Dataset

from mission_ingest_common import (
    col,
    epoch_to_aware_utc,
    epoch_to_naive_utc,
    first_finite,
    out_of_range_fixes,
    run_ingest,
    track_length_km,
)


def read_netcdf(path):
    warnings = []
    ds = Dataset(path)
    try:
        n = ds.dimensions["time"].size

        data_type = getattr(ds, "file_data_type", "") or ""
        up_and_down = "up and down" in data_type.lower()

        start_lat = col(ds, "start_latitude")
        start_lon = col(ds, "start_longitude")
        start_time = col(ds, "start_time")
        end_lat = col(ds, "end_latitude")
        end_lon = col(ds, "end_longitude")
        end_time = col(ds, "end_time")
        u_da = col(ds, "u_da")
        v_da = col(ds, "v_da")
        temp = col(ds, "temp")          # (time, depth)
        salinity = col(ds, "salinity")

        if up_and_down:
            if n % 2 != 0:
                warnings.append(
                    f"'Up and Down profile' file but odd record count ({n}); "
                    "last record treated as a lone dive."
                )
            down_idx = np.arange(0, n, 2)  # each dive's down cast
            pairs = min(len(down_idx), n // 2)
            mism = np.sum(
                ~(
                    np.isclose(u_da[0 : 2 * pairs : 2], u_da[1 : 2 * pairs : 2], equal_nan=True)
                    & np.isclose(v_da[0 : 2 * pairs : 2], v_da[1 : 2 * pairs : 2], equal_nan=True)
                )
            )
            if mism:
                warnings.append(
                    f"{mism} of {pairs} dive pairs have differing u_da/v_da between "
                    "their two records -- the down/up pairing may be wrong."
                )
        else:
            warnings.append(
                f"file_data_type={data_type!r} is not an 'Up and Down profile'; "
                "treating every record as its own dive."
            )
            down_idx = np.arange(n)

        dives = int(len(down_idx))

        track = []
        for i in down_idx:
            i = int(i)
            track.append(
                {
                    "latitude": float(start_lat[i]),
                    "longitude": float(start_lon[i]),
                    "utc": epoch_to_aware_utc(start_time[i]),
                    "temperature": first_finite(temp[i]),
                    "salinity": first_finite(salinity[i]),
                    "dacu": None if np.isnan(u_da[i]) else float(u_da[i]),
                    "dacv": None if np.isnan(v_da[i]) else float(v_da[i]),
                }
            )
        last = n - 1
        final_utc = epoch_to_aware_utc(end_time[last])
        if not track or final_utc > track[-1]["utc"]:
            track.append(
                {
                    "latitude": float(end_lat[last]),
                    "longitude": float(end_lon[last]),
                    "utc": final_utc,
                    "temperature": first_finite(temp[last]),
                    "salinity": first_finite(salinity[last]),
                    "dacu": None if np.isnan(u_da[last]) else float(u_da[last]),
                    "dacv": None if np.isnan(v_da[last]) else float(v_da[last]),
                }
            )

        bad = out_of_range_fixes(track)
        if bad:
            warnings.append(
                f"{len(bad)} surface fix(es) outside valid lat/lon range -- "
                "the tracks CHECK constraint will reject them."
            )

        metadata = {
            "launch_date": epoch_to_naive_utc(start_time[0]),
            "launch_latitude": float(start_lat[0]),
            "launch_longitude": float(start_lon[0]),
            "end_date_science": epoch_to_naive_utc(end_time[last]),
            "recovery_date": epoch_to_naive_utc(end_time[last]),
            "recovery_latitude": float(end_lat[last]),
            "recovery_longitude": float(end_lon[last]),
            "dives": dives,
            "distance_km": round(track_length_km(track), 3),
        }
        return metadata, track, warnings
    finally:
        ds.close()


if __name__ == "__main__":
    run_ingest("Seaglider", read_netcdf)
