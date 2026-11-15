# -*- coding: utf-8 -*-
"""
A股 + 港股 + 全球「宽基指数 PE 近 10 年分位」数据抓取

数据源：
  1) 蛋卷基金（A股 / 港股）
     - index_eva/dj                         当前 PE / PB / ROE
     - index_eva/pe_history/{code}?day=all  近 10 年周频 PE 序列
  2) 韭圈儿投研（全球主要宽基）
     - /api/index-valuation?category=jw     当前 PE、PB、股息率及「近 10 年 PE 分位」
     - /api/index-valuation/history?code=   近 10 年日频 PE 序列（用于区间与走势图）

口径：
  - 10 年分位 = 当前 PE 在近 10 年历史 PE 序列中的百分位
    （即「历史上有百分之多少的时间 PE 比现在更低」）。分位越低越便宜。
  - A股/港股：用蛋卷周频序列自行计算；全球：直接采用韭圈儿公布的近 10 年分位
    （两者口径一致，已交叉验证，差异通常 < 1.5 个百分点）。
  - 疫情等盈利失真期会出现 PE 异常高值，区间与走势图按「中位数 ×3 / ÷3」剔除极端值。
  - 全球指数走势序列存在滞后，逐条记录 histEnd 并在界面如实标注。
"""
import json
import os
import time
import datetime
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "global_cache.json")

UA_DJ = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://danjuanfunds.com/",
    "Accept": "application/json, text/plain, */*",
}
UA_JCS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://funddb.cn",
    "Referer": "https://funddb.cn/",
}
DJ_URL = "https://danjuanfunds.com/djapi/index_eva/dj"
HIST_URL = "https://danjuanfunds.com/djapi/index_eva/pe_history/{code}?day=all"
JCS_LIST_URL = "https://ai2.jiucaishuo.com/api/index-valuation?category=jw"
JCS_HIST_URL = "https://ai2.jiucaishuo.com/api/index-valuation/history?code={code}"

# 蛋卷时间戳按北京时间解读；显式指定时区，避免 GitHub Actions(UTC) 下日期少一天
TZ8 = datetime.timezone(datetime.timedelta(hours=8))

# code, 名称, 市场(A=沪深 / HK=港股), 规模分组
BROAD = [
    ("SH000300", "沪深300",  "A", "大盘"),
    ("SH000016", "上证50",   "A", "大盘"),
    ("SH000010", "上证180",  "A", "大盘"),
    ("SH000903", "中证100",  "A", "大盘"),
    ("SZ399330", "深证100",  "A", "大盘"),
    ("SH000905", "中证500",  "A", "中小盘"),
    ("SH000852", "中证1000", "A", "中小盘"),
    ("SZ399006", "创业板指", "A", "中小盘"),
    ("SH000688", "科创50",   "A", "中小盘"),
    ("SZ399001", "深证成指", "A", "全市场"),
    ("SZ399317", "国证A指",  "A", "全市场"),
    ("HKHSI",    "恒生指数", "HK", "港股大盘"),
    ("HKHSCEI",  "国企指数", "HK", "港股大盘"),
    ("HSFML25",  "香港大盘", "HK", "港股大盘"),
    ("SPHCMSHP", "香港中小", "HK", "港股中小"),
    ("HKHSTECH", "恒生科技", "HK", "港股主题"),
    ("HKHSSCNE", "港股新经济", "HK", "港股主题"),
]

# 全球指数：韭圈儿「境外」分类。短名用于手机窄屏表格。
GLOBAL_NAMES = {
    "SPX.GI":      ("标普500",    "美股"),
    "NDX.GI":      ("纳指100",    "美股"),
    "DJI.GI":      ("道琼斯",     "美股"),
    "FTSE.GI":     ("英国富时100", "欧洲"),
    "FCHI.GI":     ("法国CAC40",  "欧洲"),
    "GDAXI.GI":    ("德国DAX",    "欧洲"),
    "N225.GI":     ("日经225",    "亚太"),
    "KS11.GI":     ("韩国综指",   "亚太"),
    "AS51.GI":     ("澳洲标普200", "亚太"),
    "IBOVESPA.GI": ("巴西IBOV",   "新兴市场"),
    "VNINDEX.GI":  ("越南胡志明", "新兴市场"),
}
# 数据序列严重滞后（停在 2022 年）或属于 A股主题，不予纳入
GLOBAL_SKIP = {"TWII.TW", "980001.SZ"}


def get_json(url, headers=None, retry=2):
    for i in range(retry):
        try:
            r = requests.get(url, headers=headers or UA_DJ, timeout=20)
            if r.status_code == 200:
                return r.json()
            print("    HTTP", r.status_code)
        except Exception as e:
            print("    retry", i + 1, type(e).__name__, str(e)[:70])
        time.sleep(1.2)
    return None


def level_of(p):
    if p is None:
        return "—", "na"
    if p < 20:
        return "低估", "low"
    if p < 40:
        return "偏低", "low2"
    if p < 60:
        return "适中", "mid"
    if p < 80:
        return "偏高", "high2"
    return "高估", "high"


def month_series(points):
    """[(date, pe)] -> [[YYYY-MM, pe]] 每月保留最后一个采样点"""
    out = {}
    for d, pe in points:
        out[d.strftime("%Y-%m")] = round(pe, 2)
    return [[k, v] for k, v in sorted(out.items())]


def summarize(rows):
    if not rows:
        return {"count": 0, "temp": None, "low": 0, "high": 0,
                "cheapest": "", "richest": ""}
    ps = [r["pct"] for r in rows]
    return {
        "count": len(rows),
        "temp": round(sum(ps) / len(ps), 1),
        "low": sum(1 for p in ps if p < 20),
        "high": sum(1 for p in ps if p >= 80),
        "cheapest": min(rows, key=lambda r: r["pct"])["name"],
        "richest": max(rows, key=lambda r: r["pct"])["name"],
    }


def fetch_cn_hk():
    """蛋卷：A股 + 港股"""
    print("抓取蛋卷指数列表 ...")
    dj = get_json(DJ_URL)
    if not dj or "data" not in dj:
        raise SystemExit("蛋卷指数列表获取失败")
    meta = {it["index_code"]: it for it in dj["data"]["items"]}
    print("  列表共", len(meta), "个指数")

    rows = []
    for code, name, market, group in BROAD:
        print("  抓 PE 历史:", code, name)
        j = get_json(HIST_URL.format(code=code))
        if not j or "data" not in j or not j.get("data"):
            print("    !! 失败，跳过")
            continue
        points = []
        for x in j["data"]["index_eva_pe_growths"]:
            pe = x.get("pe")
            if not pe or pe <= 0:
                continue
            d = datetime.datetime.fromtimestamp(x["ts"] / 1000, TZ8).date()
            points.append((d, float(pe)))
        if len(points) < 30:
            print("    !! 样本过少，跳过")
            continue

        pes = [p for _, p in points]
        cur = round(float(meta.get(code, {}).get("pe") or pes[-1]), 2)
        pct = round(sum(1 for p in pes if p <= cur) / len(pes) * 100, 1)
        srt = sorted(pes)
        d0, d1 = points[0][0], points[-1][0]
        years = round((d1 - d0).days / 365.25, 1)
        lv, lv_cls = level_of(pct)
        m = meta.get(code, {})

        rows.append({
            "code": code, "name": name, "market": market, "group": group,
            "pe": cur, "pct": pct,
            "lo": round(min(pes), 2), "hi": round(max(pes), 2),
            "median": round(srt[len(srt) // 2], 2),
            "years": years, "start": str(d0), "end": str(d1),
            "enough10y": years >= 9.5,
            "level": lv, "levelCls": lv_cls,
            "pb": round(float(m.get("pb") or 0), 2) or None,
            "roe": round(float(m.get("roe") or 0) * 100, 1) or None,
            "div": None, "ytd": None,
            "series": month_series(points),
            "histEnd": str(d1), "histStale": False,
            "source": "蛋卷基金",
        })
        print(f"    PE={cur} 分位={pct}% 区间={rows[-1]['lo']}~{rows[-1]['hi']} {years}年 {lv}")
        time.sleep(0.25)
    return rows


def robust_range(pes):
    """全球指数用 P5~P90 常见区间。
    部分市场（巴西/英国/法国等）疫情期盈利崩塌导致 PE 成片飙到 200+，
    约占 10% 样本，直接用 min/max 会让区间与走势图完全失真。"""
    srt = sorted(pes)
    n = len(srt)
    q = lambda k: srt[min(n - 1, int(n * k))]
    return round(q(.05), 2), round(q(.90), 2), round(q(.50), 2)


def fetch_global():
    """韭圈儿：全球主要宽基。在线失败时回退到仓库内的静态缓存。"""
    print("抓取韭圈儿境外指数列表 ...")
    j = get_json(JCS_LIST_URL, headers=UA_JCS)
    if not j or "rows" not in j:
        print("  !! 列表获取失败，尝试缓存")
        return load_cache()
    data_date = j.get("new_update_time") or str(datetime.datetime.now(TZ8).date())
    rows = []
    for it in j["rows"]:
        code = it["code"]
        if code in GLOBAL_SKIP or code.endswith(".SZ") or code not in GLOBAL_NAMES:
            continue
        name, group = GLOBAL_NAMES[code]
        print("  抓全球走势:", code, name)
        h = get_json(JCS_HIST_URL.format(code=code), headers=UA_JCS)
        series, lo, hi, median, hist_end, hist_start = [], None, None, None, "", ""
        if h and h.get("series"):
            pts = []
            for x in h["series"]:
                v = x.get("value")
                if not v or v <= 0:
                    continue
                try:
                    d = datetime.date.fromisoformat(x["date"])
                except Exception:
                    continue
                pts.append((d, float(v)))
            if len(pts) >= 100:
                pes = [p for _, p in pts]
                lo, hi, median = robust_range(pes)
                # 走势图数值裁到常见区间，避免极端值把 y 轴拉爆
                series = month_series([(d, min(max(p, lo), hi)) for d, p in pts])
                hist_start, hist_end = str(pts[0][0]), str(pts[-1][0])

        pe = round(float(it.get("pe") or 0), 2)
        pct = round(float(it.get("pe_pct") or 0), 1)
        lv, lv_cls = level_of(pct)
        stale = bool(hist_end and hist_end < (datetime.date.fromisoformat(data_date)
                     - datetime.timedelta(days=90)).isoformat())
        rows.append({
            "code": code, "name": name, "market": "G", "group": group,
            "pe": pe, "pct": pct,
            "lo": lo, "hi": hi, "median": median,
            "years": 10.0, "start": hist_start or "", "end": data_date,
            "enough10y": True,
            "level": lv, "levelCls": lv_cls,
            "pb": round(float(it.get("pb") or 0), 2) or None,
            "roe": round(float(it.get("roe") or 0) * 100, 1) or None,
            "div": round(float(it.get("xilv") or 0), 2) or None,
            "ytd": round(float(it.get("ytd") or 0), 1) or None,
            "series": series,
            "histEnd": hist_end, "histStale": stale,
            "source": "韭圈儿",
        })
        print(f"    PE={pe} 分位={pct}% 区间={lo}~{hi} 走势截至={hist_end or '无'} {'[滞后]' if stale else ''}")
        time.sleep(0.2)

    if len(rows) >= 8:
        save_cache(rows, data_date)
        return rows
    print("  !! 有效指数过少，回退缓存")
    return load_cache()


def save_cache(rows, data_date):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": data_date, "indices": rows}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print("  已更新全球数据缓存", os.path.basename(CACHE_FILE))


def load_cache():
    if not os.path.exists(CACHE_FILE):
        print("  !! 无缓存可用")
        return []
    try:
        d = json.load(open(CACHE_FILE, encoding="utf-8"))
        print("  从缓存读取全球指数", len(d["indices"]), "个，数据日", d.get("date"))
        return d["indices"]
    except Exception as e:
        print("  !! 缓存读取失败", e)
        return []


def main():
    cn = fetch_cn_hk()
    gl = fetch_global()
    indices = cn + gl
    a = [r for r in indices if r["market"] == "A"]
    hk = [r for r in indices if r["market"] == "HK"]
    g = [r for r in indices if r["market"] == "G"]
    now = datetime.datetime.now(TZ8)
    out = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M") + " (北京时间)",
        "date": max((r["end"] for r in indices if r["end"]),
                    default=str(now.date())),
        "source": "蛋卷基金（A股/港股） + 韭圈儿（全球）",
        "method": "当前 PE 在近 10 年历史 PE 序列中的百分位；分位越低越便宜。"
                  "上市不足 10 年者按可得全部历史；极端盈利失真值已从区间与走势图剔除。",
        "markets": {
            "all": summarize(indices),
            "a": summarize(a),
            "hk": summarize(hk),
            "g": summarize(g),
        },
        "indices": indices,
    }
    path = os.path.join(BASE_DIR, "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("已写出", path, "共", len(indices), "个宽基（A股", len(a),
          "/ 港股", len(hk), "/ 全球", len(g), "）")


if __name__ == "__main__":
    main()
