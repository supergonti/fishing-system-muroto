# fishing_data.csv の nearest_station 列にある長名を短名に正規化する
# 例: 室戸岬沖 -> 室戸
# 気象DB (fishing_condition_db.csv) と結合できるようにするため
import csv, io, sys, os

SRC = "data/fishing_data.csv"
ALIAS = {
    "室戸岬沖": "室戸",
    "高知市沖": "高知",
    "足摺岬沖": "足摺",
    "宇和島沖": "宇和島",
    "松山沖":   "松山",
    "来島海峡": "来島",
    "高松沖":   "高松",
    "阿南市沖": "阿南",
}

if not os.path.exists(SRC):
    print(f"ERR: {SRC} not found", file=sys.stderr); sys.exit(1)

with open(SRC, "r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.reader(f))

if not rows:
    print(f"ERR: {SRC} is empty", file=sys.stderr); sys.exit(1)

header = rows[0]
try:
    col = header.index("nearest_station")
except ValueError:
    print("ERR: nearest_station column not found", file=sys.stderr); sys.exit(1)

changed = 0
for r in rows[1:]:
    if len(r) > col and r[col] in ALIAS:
        r[col] = ALIAS[r[col]]
        changed += 1

buf = io.StringIO()
w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
w.writerows(rows)
with open(SRC, "w", encoding="utf-8-sig", newline="") as f:
    f.write(buf.getvalue())

print(f"normalized {changed} rows in {SRC}")
