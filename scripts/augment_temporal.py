"""Add numeric valid-time fields to the relations staging for the FinReflectKgTemporal
build (G9/M8, §4.8). Reads data/staging/full/relations/*.json and writes
data/staging/temporal/relations/*.json with two extra fields (all others preserved):

  validFrom = YYYYMM of startDate  (fallback: Jan of filing `year` when startDate is null)
  validTo   = YYYYMM of the month AFTER endDate (EXCLUSIVE); NEVER_EXPIRES when open-ended

So a fiscal-year edge 2018-01..2018-12 -> validFrom=201801, validTo=201901, and the as-of
predicate `validFrom <= @t AND validTo > @t` (half-open) selects it for any @t in 2018.
Degenerate/inverted spans (endDate < startDate, seen in the raw extraction) are clamped to a
>=1-month interval. Idempotent: a shard whose output already has the same line count is skipped.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data/staging/full/relations"
DST = ROOT / "data/staging/temporal/relations"
NEVER_EXPIRES = 999912
MIN_YEAR, MAX_YEAR = 2013, 2026   # plausible fiscal window for 2014-2024 10-Ks (+ slack)
YM = re.compile(r"^(\d{4})-(\d{2})$")


def ym_int(s):
    m = YM.match(s) if isinstance(s, str) else None
    return int(m.group(1)) * 100 + int(m.group(2)) if m else None


def next_month(v):  # 201212 -> 201301 ; 201805 -> 201806
    y, m = divmod(v, 100)
    return (y + 1) * 100 + 1 if m >= 12 else y * 100 + (m + 1)


def line_count(p):
    with open(p, "rb") as f:
        return sum(1 for _ in f)


def augment(d):
    yr = d.get("year")
    floor = int(yr) * 100 + 1 if yr else 0
    vf = ym_int(d.get("startDate"))
    # startDate is frequently noisy (OCR): absurd years like 1163 / 8176 parse
    # cleanly but would make an edge match every (or no) as-of snapshot. Fall back
    # to the filing year when the parsed start year is outside the plausible window.
    if vf is None or not (MIN_YEAR * 100 + 1 <= vf <= MAX_YEAR * 100 + 12):
        vf = floor
    # endDate is left lenient: legitimate far-future maturities (e.g. a bond "due
    # 2034") should read as open-ended for as-of queries within the data range.
    ve = ym_int(d.get("endDate"))
    vt = next_month(ve) if ve is not None else NEVER_EXPIRES
    if vt <= vf:                         # inverted/degenerate span -> min 1-month interval
        vt = next_month(vf)
    d["validFrom"] = vf
    d["validTo"] = vt
    return d


def main():
    DST.mkdir(parents=True, exist_ok=True)
    for src in sorted(SRC.glob("*.json")):
        dst = DST / src.name
        if dst.exists() and line_count(dst) == line_count(src):
            print(f"{src.name}: up-to-date, skip")
            continue
        n = 0
        with open(src) as fi, open(dst, "w") as fo:
            for line in fi:
                line = line.strip()
                if not line:
                    continue
                fo.write(json.dumps(augment(json.loads(line)), separators=(",", ":")) + "\n")
                n += 1
        print(f"{src.name}: {n} rows -> {dst.relative_to(ROOT)}")
    print("temporal augmentation complete")


if __name__ == "__main__":
    main()
