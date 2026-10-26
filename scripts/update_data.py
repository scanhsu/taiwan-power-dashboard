#!/usr/bin/env python3
"""
抓取台電公開資料，整理成網頁要讀的 JSON。

資料來源（優先順序）：
  1. 政府資料開放平臺 / 台電開放資料（service.taipower.com.tw）  ← 主要來源
  2. 台電「今日電力資訊」網頁資料（www.taipower.com.tw）        ← 備援（海外 IP 常被擋）

產生的檔案（都在 data/ 資料夾）：
  latest.json    即時資料：燈號、用電曲線、能源結構、區域供需、各機組發電量（每次執行都重寫，不存進 git）
  today.json     今天的用電與各能源曲線（開放資料只有「當下」數值，曲線靠每次執行累積；不存進 git，隨網站發布）
  history.json   需要累積的資料：昨日用電曲線、每日尖峰備轉容量率
  counties.json  各縣市用電（每月更新一次）

只用 Python 內建模組，不需要安裝任何套件。
在自己電腦測試：  python scripts/update_data.py
"""
import csv
import datetime as dt
import html
import io
import json
import os
import re
import sys
import time
import urllib.request

BASE = "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/"
OPEN = "https://service.taipower.com.tw/data/opendata/apply/file/"
TZ = dt.timezone(dt.timedelta(hours=8))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

errors = []


def log(msg):
    print(msg, flush=True)


def fetch(url, tries=3):
    """下載網址內容，失敗會重試三次。"""
    last = None
    for i in range(tries):
        try:
            sep = "&" if "?" in url else "?"
            req = urllib.request.Request(f"{url}{sep}t={int(time.time())}", headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                "Referer": "https://service.taipower.com.tw/" if "service.taipower" in url else "https://www.taipower.com.tw/tc/page.aspx?mid=206",
                "Cache-Control": "no-cache",
            })
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read()
            for enc in ("utf-8-sig", "big5", "cp950"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"下載失敗 {url}: {last}")


def num(s):
    """把 '2,922.7'、'3460.4(5.637%)'、'-'、'N/A' 轉成數字或 None。"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    s = re.sub(r"\(.*?\)", "", s).strip()
    if s in ("", "-", "N/A", "NA", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def hour_of(t):
    """'00' -> 0、'13:30' -> 13.5"""
    t = t.strip()
    if not t:
        return None
    if ":" in t:
        h, m = t.split(":")[:2]
        return int(h) + int(m) / 60
    return float(int(t))


def r1(v):
    return None if v is None else round(v, 1)


def load_json(name, default):
    p = os.path.join(DATA, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def save_json(name, obj):
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    log(f"已寫入 data/{name}（{os.path.getsize(p):,} bytes）")


# ---------- 能源別對照 ----------
def fuel_of(category):
    c = category
    if "儲能負載" in c:
        return "storage_load"
    if "儲能" in c:
        return "storage"
    if "核能" in c:
        return "nuclear"
    if "燃煤" in c:
        return "coal"
    if "燃氣" in c:
        return "lng"
    if "汽電共生" in c:
        return "cogen"
    if "燃料油" in c or "燃油" in c or "重油" in c or "輕油" in c:
        return "oil"
    if "水力" in c:
        return "hydro"
    if "風力" in c:
        return "wind"
    if "太陽能" in c:
        return "solar"
    if "再生" in c:
        return "other"
    return "other"


MIX_KEYS = ["lng", "coal", "cogen", "oil", "hydro", "wind", "solar", "other", "storage", "nuclear"]

# loadfueltype.csv 欄位順序（依台電網頁圖表的順序；12 欄時沒有核能）
FUELTYPE_12 = ["lng", "lng", "coal", "coal", "cogen", "oil", "solar", "wind", "hydro", "storage", "other", "storage_load"]


# ---------- 各檔案解析 ----------
def parse_loadpara(text):
    j = json.loads(text)
    rec = {}
    for item in j.get("records", []):
        if isinstance(item, dict):
            rec.update(item)
    return rec


def roc_to_date(s):
    """'115.10.25' 或 '115.10.26(一)11:50' -> date"""
    m = re.search(r"(\d{2,3})\.(\d{1,2})\.(\d{1,2})", s or "")
    if not m:
        return None
    return dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))


def parse_genary(text):
    j = json.loads(text)
    stamp = j.get("") or ""
    units = []
    for row in j.get("aaData", []):
        if len(row) < 5:
            continue
        cat = re.sub(r"<[^>]+>", "", row[0]).strip()
        name = html.unescape(str(row[2])).strip()
        if not name or name.startswith("小計"):
            continue
        cap, mw = num(row[3]), num(row[4])
        note = html.unescape(str(row[6])).strip() if len(row) > 6 else ""
        units.append([fuel_of(cat), name, cap, mw, note])
    return stamp, units


def parse_fueltype(text):
    stack = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 13 or not cells[0]:
            continue
        vals = [num(c) or 0.0 for c in cells[1:]]
        if len(vals) == 12:
            keys = FUELTYPE_12
        elif len(vals) == 13:
            keys = ["nuclear"] + FUELTYPE_12
        else:
            continue
        p = {k: 0.0 for k in MIX_KEYS}
        for k, v in zip(keys, vals):
            if k == "storage_load":
                continue
            p[k] += v
        p["storage"] = max(0.0, p["storage"])
        p = {k: round(v, 1) for k, v in p.items()}
        p["h"] = round(hour_of(cells[0]), 4)
        stack.append(p)
    return stack


def parse_loadareas(text):
    """每行：時間, 東部, 南部, 中部, 北部（萬瓩）"""
    out = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 5 or not cells[0]:
            continue
        vals = [num(c) for c in cells[1:5]]
        if any(v is None for v in vals):
            continue
        out.append([round(hour_of(cells[0]), 4), round(sum(vals), 1)])
    return out


def parse_areaperc(text):
    """一行：時間, 北發電, 北用電, 中發電, 中用電, 南發電, 南用電, 東發電, 東用電"""
    line = text.strip().splitlines()[0]
    c = [x.strip() for x in line.split(",")]
    v = [num(x) for x in c[1:9]]
    names = ["北部", "中部", "南部", "東部"]
    return c[0], [{"n": names[i], "gen": r1(v[i * 2]), "load": r1(v[i * 2 + 1])} for i in range(4)]


def pick(row, prefix):
    """從一筆資料（字典）取出欄位名稱以 prefix 開頭的值（容忍括號等小差異）。"""
    for k, v in row.items():
        if str(k).strip().lstrip("\ufeff").startswith(prefix):
            return v
    return None


def parse_open_genary(text):
    """開放資料 d006001：{"DateTime": "...", "aaData": [{機組類型, 機組名稱, 裝置容量(MW), 淨發電量(MW), ..., 備註}]}"""
    j = json.loads(text)
    stamp = str(j.get("DateTime") or "").replace("T", " ")[:16]
    units = []
    for row in j.get("aaData", []):
        if not isinstance(row, dict):
            continue
        cat = re.sub(r"<[^>]+>", "", str(pick(row, "機組類型") or "")).strip()
        name = html.unescape(str(pick(row, "機組名稱") or "")).strip()
        if not name or name.startswith("小計"):
            continue
        units.append([fuel_of(cat), name, num(pick(row, "裝置容量")), num(pick(row, "淨發電量(MW)")),
                      html.unescape(str(pick(row, "備註") or "")).strip()])
    if not units:
        raise ValueError("d006001 沒有解析到任何機組")
    return stamp, units


def parse_open_areas(text):
    """開放資料 d006019：時間,區域,發電(萬瓩),用電(萬瓩)，北中南東各一行。"""
    names = ["北部", "中部", "南部", "東部"]
    got = {}
    for r in csv.reader(io.StringIO(text.replace("\ufeff", ""))):
        if len(r) >= 4 and r[1].strip() in names:
            got[r[1].strip()] = (num(r[2]), num(r[3]))
    if len(got) < 4:
        raise ValueError(f"d006019 只找到 {len(got)} 個區域")
    return [{"n": n, "gen": r1(got[n][0]), "load": r1(got[n][1])} for n in names]


def accumulate_today(pdate, h, load_wan, mix):
    """開放資料只有「當下」的數字，所以每次執行就把這一筆加進今天的曲線，存在 data/today.json。
    （GitHub Actions 會在執行前，從已發布的網站把上一次的 today.json 取回來。）"""
    cur = load_json("today.json", {})
    if cur.get("date") != pdate.isoformat():
        cur = {"date": pdate.isoformat(), "load": [], "stack": []}
    if load_wan is not None:
        cur["load"] = sorted([p for p in cur["load"] if abs(p[0] - h) > 0.01] + [[h, round(load_wan, 1)]])
    if mix:
        pt = {k: round(mix.get(k, 0.0), 1) for k in MIX_KEYS}
        pt["h"] = h
        cur["stack"] = sorted([p for p in cur["stack"] if abs(p["h"] - h) > 0.01] + [pt], key=lambda p: p["h"])
    save_json("today.json", cur)
    return cur["load"], cur["stack"]


def try_sources(label, *getters):
    """依序嘗試多個來源，回傳（來源名稱, 結果）。"""
    last = None
    for name, fn in getters:
        try:
            res = fn()
            log(f"{label}：使用 {name}")
            return name, res
        except Exception as e:  # noqa: BLE001
            log(f"{label}：{name} 失敗：{e}")
            last = e
    raise RuntimeError(f"{label}：所有來源都失敗（{last}）")


# ---------- 歷史資料 ----------
def seed_reserve_from_opendata(hist):
    """備轉容量率歷史太少時，從開放資料補上每日數值。d006002 是今年每日資料；d006005 是更長的歷史。"""
    for fname in ("d006002/001.csv", "d006005/001.csv"):
        try:
            text = fetch(OPEN + fname)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fname}：{e}")
            continue
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            continue
        head = [h.strip().lstrip("\ufeff") for h in rows[0]]
        try:
            di = next(i for i, h in enumerate(head) if "日期" in h)
            ri = next(i for i, h in enumerate(head) if "備轉容量率" in h)
        except StopIteration:
            errors.append(f"{fname}：找不到日期或備轉容量率欄位")
            continue
        known = {r["d"] for r in hist["reserve"]}
        for r in rows[1:]:
            if len(r) <= max(di, ri):
                continue
            ds = re.sub(r"\D", "", r[di])
            if len(ds) != 8:
                continue
            d = f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
            rate = num(r[ri])
            if rate is not None and d not in known:
                hist["reserve"].append({"d": d, "rate": round(rate, 2)})
        log(f"從開放資料 {fname} 補入備轉容量率，共 {len(hist['reserve'])} 天")
        if len(hist["reserve"]) >= 25:
            return


def update_counties(force=False):
    """各縣市用電：開放資料 d007012（每月、依用電性質：住宅／服務業／農林漁牧／工業的售電量）。"""
    cur = load_json("counties.json", {})
    age_days = (time.time() - cur.get("fetched", 0)) / 86400
    if not force and not cur.get("sample", True) and age_days < 7:
        return
    try:
        monthly = list(csv.DictReader(io.StringIO(fetch(OPEN + "d007012/001.csv"))))
    except Exception as e:  # noqa: BLE001
        errors.append(f"縣市月用電：{e}")
        return

    def col(row, key):
        for k in row:
            if k and key in k:
                return row[k]
        return None

    def norm(n):
        return (n or "").strip().replace("台", "臺")

    months = sorted({re.sub(r"\D", "", col(r, "年月") or "") for r in monthly} - {""})
    if not months:
        errors.append("縣市月用電：沒有年月欄位")
        return
    last = months[-1]
    use = {}
    for r in monthly:
        if re.sub(r"\D", "", col(r, "年月") or "") != last:
            continue
        c, kind, kwh = norm(col(r, "縣市")), col(r, "用電性質") or "", num(col(r, "售電量"))
        if not c or kwh is None:
            continue
        slot = "res" if "住宅" in kind else "ind" if "工業" in kind else "svc" if ("服務" in kind or "機關" in kind) else "oth"
        use.setdefault(c, {"res": 0.0, "svc": 0.0, "ind": 0.0, "oth": 0.0})
        use[c][slot] += kwh

    counties = {}
    for c, u in use.items():
        total = sum(u.values())
        if total <= 0:
            continue
        res, ind = round(u["res"] / total * 100), round(u["ind"] / total * 100)
        counties[c] = [round(total / 1e8, 2), res, 100 - res - ind, ind]  # 服務業＋農林漁牧＋其他併入中間欄
    if not counties:
        errors.append("縣市月用電：解析後沒有資料")
        return
    y, m = int(last[:-2]), int(last[-2:])
    if y < 1911:
        y += 1911
    save_json("counties.json", {
        "sample": False,
        "fetched": int(time.time()),
        "month": f"{y} 年 {m} 月",
        "note": "台電每月實際售電量（住宅、服務業、工業等合計）；來源：政府資料開放平臺。",
        "counties": counties,
    })


# ---------- 主程式 ----------
def main():
    now = dt.datetime.now(TZ)
    out = {"generated": now.strftime("%Y-%m-%d %H:%M"), "errors": errors}

    # 1. 即時用電與燈號（兩個來源都抓不到就整次放棄，保留舊資料）
    def open_loadpara():
        r = parse_loadpara(fetch(OPEN + "d006020/001.json"))
        if not r.get("publish_time") and not r.get("curr_load"):
            raise ValueError("內容不是預期的格式")
        return r

    try:
        src, rec = try_sources(
            "即時供需",
            ("開放資料 d006020", open_loadpara),
            ("台電網站 loadpara.json", lambda: parse_loadpara(fetch(BASE + "loadpara.json"))),
        )
    except Exception as e:  # noqa: BLE001
        log(str(e))
        sys.exit(1)
    use_base = src.startswith("台電網站")
    out["source"] = "open" if not use_base else "taipower"

    pub = rec.get("publish_time", "")
    pdate = roc_to_date(pub) or now.date()
    tm = re.search(r"(\d{1,2}:\d{2})\s*$", pub)
    hhmm_str = tm.group(1) if tm else now.strftime("%H:%M")
    out["asOf"] = f"{pdate.isoformat()} {hhmm_str}"
    out["supply"] = {
        "curLoad": num(rec.get("curr_load")),
        "util": num(rec.get("curr_util_rate")),
        "capacity": num(rec.get("fore_maxi_sply_capacity")),
        "peakForecast": num(rec.get("fore_peak_dema_load")),
        "peakTime": (rec.get("fore_peak_hour_range") or "").replace("-", "–"),
        "reserveRate": num(rec.get("fore_peak_resv_rate")),
        "reserveMW": num(rec.get("fore_peak_resv_capacity")),
        "indicator": rec.get("fore_peak_resv_indicator"),
        "ydayPeak": num(rec.get("yday_peak_dema_load")),
        "ydayRate": num(rec.get("yday_peak_resv_rate")),
        "realHrCap": num(rec.get("real_hr_maxi_sply_capacity")),
    }

    # 2. 各機組發電量 → 能源結構
    try:
        _src, (stamp, units) = try_sources(
            "機組發電量",
            ("開放資料 d006001", lambda: parse_open_genary(fetch(OPEN + "d006001/001.json"))),
            ("台電網站 genary.json", lambda: parse_genary(fetch(BASE + "genary.json"))),
        )
        mix = {k: 0.0 for k in MIX_KEYS}
        for f, _n, _cap, mw, _note in units:
            if f in mix and mw and mw > 0:
                mix[f] += mw
        out["mix"] = {k: round(v / 10, 1) for k, v in mix.items()}  # MW → 萬瓩
        out["units"] = units
        out["unitsAt"] = stamp
    except Exception as e:  # noqa: BLE001
        errors.append(str(e))

    # 3. 今日各能源發電曲線、今日用電曲線
    today = []
    if use_base:
        # 備援來源有完整的當日曲線
        try:
            out["stack"] = parse_fueltype(fetch(BASE + "loadfueltype.csv"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"loadfueltype.csv：{e}")
        try:
            today = parse_loadareas(fetch(BASE + "loadareas.csv"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"loadareas.csv：{e}")
    else:
        # 開放資料只有當下數值：把這一筆加進今天的曲線
        today, stack = accumulate_today(pdate, round(hour_of(hhmm_str), 4), out["supply"]["curLoad"], out.get("mix"))
        if stack:
            out["stack"] = stack

    # 4. 區域供需
    try:
        _src, out["regions"] = try_sources(
            "區域供需",
            ("開放資料 d006019", lambda: parse_open_areas(fetch(OPEN + "d006019/001.csv"))),
            ("台電網站 genloadareaperc.csv", lambda: parse_areaperc(fetch(BASE + "genloadareaperc.csv"))[1]),
        )
    except Exception as e:  # noqa: BLE001
        errors.append(str(e))

    # 5. 歷史：昨日曲線與每日備轉容量率
    hist = load_json("history.json", {"curve_date": None, "curve": [], "yday_date": None, "yday": [], "reserve": []})
    dstr = pdate.isoformat()
    if hist.get("curve_date") and hist["curve_date"] != dstr and hist.get("curve"):
        if hist["curve_date"] == (pdate - dt.timedelta(days=1)).isoformat():
            hist["yday_date"], hist["yday"] = hist["curve_date"], hist["curve"]
        hist["curve"] = []
    if today:
        hist["curve_date"], hist["curve"] = dstr, today
    yd = roc_to_date(rec.get("yday_date", ""))
    yrate = num(rec.get("yday_peak_resv_rate"))
    if yd and yrate is not None:
        hist["reserve"] = [r for r in hist["reserve"] if r["d"] != yd.isoformat()]
        hist["reserve"].append({"d": yd.isoformat(), "rate": round(yrate, 2)})
    if len(hist["reserve"]) < 25:
        seed_reserve_from_opendata(hist)
    hist["reserve"] = sorted(hist["reserve"], key=lambda r: r["d"])[-60:]

    out["load"] = {
        "today": today,
        "yday": hist.get("yday", []) if hist.get("yday_date") == (pdate - dt.timedelta(days=1)).isoformat() else [],
        "nowH": today[-1][0] if today else None,
    }
    out["reserve"] = [{"date": f"{int(r['d'][5:7])}/{int(r['d'][8:10])}", "rate": r["rate"]} for r in hist["reserve"][-30:]]

    # 昨日曲線只在 23 點後才需要存（減少 git 提交次數）；備轉容量率有新的一天時也存
    old = load_json("history.json", {})
    changed_days = [r["d"] for r in old.get("reserve", [])] != [r["d"] for r in hist["reserve"]]
    if now.hour >= 23 or changed_days or old.get("yday_date") != hist.get("yday_date") or not old:
        save_json("history.json", hist)

    # 6. 縣市用電（每週最多檢查一次）
    update_counties()

    save_json("latest.json", out)
    if errors:
        log("部分資料失敗（網頁其他區塊仍會更新）：")
        for e in errors:
            log("  - " + e)


if __name__ == "__main__":
    main()
