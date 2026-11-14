# -*- coding: utf-8 -*-
"""
A股 + 港股「宽基指数 PE 近 10 年分位」数据抓取

数据源：蛋卷基金
  - index_eva/dj                     当前 PE / PB / ROE / 股息率
  - index_eva/pe_history/{code}?day=all   近 10 年周频 PE 序列（蛋卷最多提供 10 年）

口径：
  - 10 年分位 = 当前 PE 在近 10 年历史 PE 序列中的百分位
    （即「历史上有百分之多少的时间 PE 比现在更低」）。分位越低越便宜。
  - 上市不足 10 年的指数按可得全部历史计算，并标注实际年限。
  - 走势序列按月频降采样（每月最后一个采样点），用于前端迷你走势图。
"""
import json
import os
import time
import datetime
import requests

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://danjuanfunds.com/",
    "Accept": "application/json, text/plain, */*",
}
DJ_URL = "https://danjuanfunds.com/djapi/index_eva/dj"
HIST_URL = "https://danjuanfunds.com/djapi/index_eva/pe_history/{code}?day=all"

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


def get_json(url, retry=3):
    for i in range(retry):
        try:
            r = requests.get(url, headers=UA, timeout=20)
            if r.status_code == 200:
                return r.json()
            print("    HTTP", r.status_code)
        except Exception as e:
            print("    retry", i + 1, type(e).__name__, str(e)[:70])
        time.sleep(1.5)
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


def main():
    print("抓取蛋卷指数列表 ...")
    dj = get_json(DJ_URL)
    if not dj or "data" not in dj:
        raise SystemExit("蛋卷指数列表获取失败")
    meta = {it["index_code"]: it for it in dj["data"]["items"]}
    print("  列表共", len(meta), "个指数")

    indices = []
    for code, name, market, group in BROAD:
        print("  抓 PE 历史:", code, name)
        j = get_json(HIST_URL.format(code=code))
        if not j or "data" not in j or not j.get("data"):
            print("    !! 失败，跳过")
            continue
        arr = j["data"]["index_eva_pe_growths"]
        points = []
        for x in arr:
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
        lo, hi = round(min(pes), 2), round(max(pes), 2)
        srt = sorted(pes)
        median = round(srt[len(srt) // 2], 2)
        d0, d1 = points[0][0], points[-1][0]
        years = round((d1 - d0).days / 365.25, 1)
        lv, lv_cls = level_of(pct)
        m = meta.get(code, {})

        indices.append({
            "code": code,
            "name": name,
            "market": market,
            "group": group,
            "pe": cur,
            "pct": pct,
            "lo": lo,
            "hi": hi,
            "median": median,
            "years": years,
            "start": str(d0),
            "end": str(d1),
            "enough10y": years >= 9.5,
            "level": lv,
            "levelCls": lv_cls,
            "pb": round(float(m.get("pb") or 0), 2) or None,
            "roe": round(float(m.get("roe") or 0) * 100, 1) or None,
            "series": month_series(points),
        })
        print(f"    PE={cur} 分位={pct}% 区间={lo}~{hi} 年限={years}年 {lv}")
        time.sleep(0.3)

    a = [r for r in indices if r["market"] == "A"]
    hk = [r for r in indices if r["market"] == "HK"]
    now = datetime.datetime.now(TZ8)
    out = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M") + " (北京时间)",
        "date": max((r["end"] for r in indices), default=str(now.date())),
        "source": "蛋卷基金",
        "method": "当前 PE 在近 10 年（上市不足 10 年者按可得全部历史）周频 PE 序列中的百分位；分位越低越便宜",
        "markets": {
            "all": summarize(indices),
            "a": summarize(a),
            "hk": summarize(hk),
        },
        "indices": indices,
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("已写出", path, "共", len(indices), "个宽基")


if __name__ == "__main__":
    main()
