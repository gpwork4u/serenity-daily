#!/usr/bin/env python3
"""Build full-market static data for the Serenity daily site.

Pulls aggregate (whole-market, one-shot) endpoints — no per-stock API calls:
  TW 上市: TWSE openapi  STOCK_DAY_ALL / BWIBBU_ALL / t187ap05_L (月營收) / t187ap06_L_* (季損益,含金融業)
  TW 上櫃: TPEx openapi  daily_close_quotes / peratio_analysis / t187ap05_O / t187ap06_O_* (英文鍵!)
  US     : Nasdaq screener (price / change / mktcap / sector / industry)

Outputs (repo-relative):
  data/market/tw.json   {"asof", "rows":[...]}
  data/market/us.json   {"asof", "rows":[...]}
  data/market/meta.json {"tw_asof", "us_asof", counts..., "generated"}

設計要點（由 review 修正而來）:
  - 金額欄一律「千元」：a(成交值)/rev_*/q_* 同單位，前端 fmtYi 統一 /1e5 顯示億。
  - TPEx 季損益端點用英文鍵 SecuritiesCompanyCode/Year/Season → 雙鍵 fallback。
  - 季損益除一般業 _ci 外，加抓金融業 _basi/_bd/_fh/_ins/_mim（金控/銀行/保險才有 EPS）。
  - US 失敗不可拖垮 TW：TW 先寫檔；US 失敗保留舊 us.json、exit 0。
  - us asof = 美東「最近一個已收盤交易日」，不是台北今天。
  - 無變化（rows+asof 相同）不重寫檔 → workflow 的 no-change guard 才有效。
  - 停牌/無成交 p=0 正規化為 null。
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TPE = timezone(timedelta(hours=8))
ET = ZoneInfo("America/New_York")
OUT_DIR = "data/market"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get_json(url, retries=3, timeout=60, headers=None):
    hdrs = {"User-Agent": UA, "accept": "application/json"}
    if headers:
        hdrs.update(headers)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"fetch failed after {retries}: {url}: {last}")


def num(s):
    """Parse a number-ish string ('1,234', '-0.20 ', '', '--', 'N/A') -> float|None."""
    if s is None:
        return None
    s = str(s).replace(",", "").replace("+", "").strip()
    if s in ("", "--", "-", "N/A", "NA", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def kntd(x):
    """元 -> 千元 (int)。"""
    return None if x is None else round(x / 1000)


def roc_date(s):
    s = str(s).strip()
    m = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", s)
    if not m:
        return None
    return f"{int(m.group(1)) + 1911}-{m.group(2)}-{m.group(3)}"


def classify(code):
    code = str(code).strip()
    if re.fullmatch(r"\d{4}", code) and not code.startswith("0"):
        return "stock"
    if code.startswith("0") and re.fullmatch(r"0\d{3,5}[A-Z]?", code):
        return "etf"
    return None


def r2(x):
    return None if x is None else round(x, 2)


# ---------------- TW ----------------

# 季損益：一般業 _ci ＋ 金融業（銀行 _basi/券商 _bd/金控 _fh/保險 _ins/投信 _mim）
TW_Q_URLS = [f"https://openapi.twse.com.tw/v1/opendata/t187ap06_L_{k}"
             for k in ("ci", "basi", "bd", "fh", "ins", "mim")] + \
            [f"https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_{k}"
             for k in ("ci", "basi", "bd", "fh", "ins", "mim")]


def build_tw():
    rows = {}
    asof = None

    # 上市日行情
    for r in get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"):
        t = classify(r.get("Code", ""))
        if not t:
            continue
        code = r["Code"].strip()
        close = num(r.get("ClosingPrice")) or None  # 0 = 停牌/無成交 → null
        chg = num(r.get("Change")) if close is not None else None
        prev = close - chg if (close is not None and chg is not None) else None
        asof = asof or roc_date(r.get("Date"))
        rows[code] = {
            "c": code, "n": r.get("Name", "").strip(), "mk": "上市", "t": t,
            "p": close, "chg": chg,
            "chgp": r2(chg / prev * 100) if (chg is not None and prev) else None,
            "v": num(r.get("TradeVolume")), "a": kntd(num(r.get("TradeValue"))),
        }

    # 上櫃日行情
    for r in get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"):
        code = str(r.get("SecuritiesCompanyCode", "")).strip()
        t = classify(code)
        if not t:
            continue
        close = num(r.get("Close")) or None
        chg = num(r.get("Change")) if close is not None else None
        prev = close - chg if (close is not None and chg is not None) else None
        asof = asof or roc_date(r.get("Date"))
        rows[code] = {
            "c": code, "n": r.get("CompanyName", "").strip(), "mk": "上櫃", "t": t,
            "p": close, "chg": chg,
            "chgp": r2(chg / prev * 100) if (chg is not None and prev) else None,
            "v": num(r.get("TradingShares")), "a": kntd(num(r.get("TransactionAmount"))),
        }

    # 估值
    for r in get_json("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"):
        code = str(r.get("Code", "")).strip()
        if code in rows:
            rows[code].update(pe=num(r.get("PEratio")), pb=num(r.get("PBratio")), yld=num(r.get("DividendYield")))
    for r in get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"):
        code = str(r.get("SecuritiesCompanyCode", "")).strip()
        if code in rows:
            rows[code].update(pe=num(r.get("PriceEarningRatio")), pb=num(r.get("PriceBookRatio")), yld=num(r.get("YieldRatio")))

    # 月營收 (千元)
    for url in ("https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"):
        for r in get_json(url):
            code = str(r.get("公司代號", "") or r.get("SecuritiesCompanyCode", "")).strip()
            if code not in rows:
                continue
            cur = num(r.get("營業收入-當月營收"))
            cum = num(r.get("累計營業收入-當月累計營收"))
            rows[code].update(
                ind=r.get("產業別", "").strip() or rows[code].get("ind"),
                rev_ym=str(r.get("資料年月", "")).strip(),
                rev_m=cur,
                rev_mom=r2(num(r.get("營業收入-上月比較增減(%)"))),
                rev_yoy=r2(num(r.get("營業收入-去年同月增減(%)"))),
                rev_cum=cum,
            )
            prev_cum = num(r.get("累計營業收入-去年累計營收"))
            rows[code]["rev_cum_yoy"] = r2((cum - prev_cum) / abs(prev_cum) * 100) if (cum is not None and prev_cum) else None

    # 季損益 (千元, EPS 元) — TWSE 用中文鍵、TPEx 用英文鍵 SecuritiesCompanyCode/Year/Season
    for url in TW_Q_URLS:
        try:
            data = get_json(url)
        except Exception as e:  # noqa: BLE001 — 個別金融資料集缺席不致命
            print(f"WARN quarterly dataset skipped: {url}: {e}", file=sys.stderr)
            continue
        for r in data:
            code = str(r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
            if code not in rows:
                continue
            yr = str(r.get("年度") or r.get("Year") or "").strip()
            sq = str(r.get("季別") or r.get("Season") or "").strip()
            rev = num(r.get("營業收入"))
            gp = num(r.get("營業毛利（毛損）淨額"))
            if gp is None:
                gp = num(r.get("營業毛利（毛損）"))
            op = num(r.get("營業利益（損失）"))
            ni = num(r.get("淨利（淨損）歸屬於母公司業主"))
            if ni is None:
                ni = num(r.get("本期淨利（淨損）"))
            rows[code].update(
                q=f"{yr}Q{sq}" if yr and sq else rows[code].get("q"),
                q_rev=rev, q_gp=gp, q_op=op, q_ni=ni,
                q_eps=num(r.get("基本每股盈餘（元）")),
                gm=r2(gp / rev * 100) if (gp is not None and rev) else None,
                om=r2(op / rev * 100) if (op is not None and rev) else None,
                nm=r2(ni / rev * 100) if (ni is not None and rev) else None,
            )

    out = sorted(rows.values(), key=lambda x: x["c"])
    return {"asof": asof, "rows": out}


# ---------------- US ----------------

def us_asof():
    """美東「最近一個已收盤交易日」（16:00 ET 收盤；週末回推到週五）。"""
    now = datetime.now(ET)
    d = now.date()
    if now.hour < 16:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def build_us():
    d = get_json(
        "https://api.nasdaq.com/api/screener/stocks?limit=25000&download=true",
        headers={
            "accept-language": "en-US,en;q=0.9",
            "referer": "https://www.nasdaq.com/market-activity/stocks/screener",
            "origin": "https://www.nasdaq.com",
        },
    )
    data = d.get("data") or {}
    raw = data.get("rows") or (data.get("table") or {}).get("rows") or []
    if not raw:
        raise RuntimeError(f"nasdaq screener returned no rows (keys={list(d)[:5]})")
    out = []
    for r in raw:
        sym = str(r.get("symbol", "")).strip()
        if not sym or "^" in sym:
            continue
        out.append({
            "s": sym, "n": str(r.get("name", "")).strip(),
            "p": num(str(r.get("lastsale", "")).replace("$", "")),
            "chg": num(r.get("netchange")),
            "chgp": num(str(r.get("pctchange", "")).replace("%", "")),
            "v": num(r.get("volume")),
            "mc": num(r.get("marketCap")),
            "sec": str(r.get("sector", "")).strip(),
            "ind": str(r.get("industry", "")).strip(),
            "co": str(r.get("country", "")).strip(),
            "ipo": str(r.get("ipoyear", "")).strip(),
        })
    out.sort(key=lambda x: -(x["mc"] or 0))
    return {"asof": us_asof(), "rows": out}


# ---------------- write helpers ----------------

def load_existing(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def write_if_changed(path, payload):
    """rows+asof 沒變就不重寫（避免只有時間戳差異的無意義 commit）。回傳是否有寫。"""
    old = load_existing(path)
    if old is not None and old.get("rows") == payload["rows"] and old.get("asof") == payload["asof"]:
        print(f"unchanged, skip write: {path}")
        return False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    json.load(open(path, encoding="utf-8"))  # round-trip validate
    print(f"wrote: {path} ({len(payload['rows'])} rows, asof {payload['asof']})")
    return True


def _rank_pct(sorted_xs, v):
    """v 在已排序 sorted_xs 中的百分位 0..1（含 ties 取平均秩）。"""
    import bisect
    n = len(sorted_xs)
    if n <= 1:
        return 0.5
    lo = bisect.bisect_left(sorted_xs, v)
    hi = bisect.bisect_right(sorted_xs, v)
    return ((lo + hi - 1) / 2) / (n - 1)


def _pct_fn(stocks, key, transform=None, lo=None, hi=None):
    """回傳 (ind, val) -> 百分位；產業內 >=8 檔用產業分佈，否則用全市場。transform 先套用。"""
    from collections import defaultdict
    def val(r):
        x = r.get(key)
        if x is None:
            return None
        if transform:
            x = transform(x)
        if x is None:
            return None
        if lo is not None and x < lo:
            x = lo
        if hi is not None and x > hi:
            x = hi
        return x
    mkt = sorted(v for v in (val(r) for r in stocks) if v is not None)
    ind_vals = defaultdict(list)
    for r in stocks:
        v = val(r)
        if v is not None:
            ind_vals[r.get("ind") or "其他"].append(v)
    ind_sorted = {k: sorted(vs) for k, vs in ind_vals.items() if len(vs) >= 8}

    def fn(r):
        v = val(r)
        if v is None:
            return None
        ind = r.get("ind") or "其他"
        xs = ind_sorted.get(ind, mkt)
        return _rank_pct(xs, v)
    return fn, val


def score_tw(rows):
    """綜合多因子購入評分（透明規則化，教育用途，非投資建議）。就地在每檔 stock 加欄位。"""
    stocks = [r for r in rows if r.get("t") == "stock" and r.get("p") is not None]
    for r in stocks:
        pe, pb = r.get("pe"), r.get("pb")
        r["_roe"] = round(pb / pe * 100, 1) if (pe and pe > 0 and pb and pb > 0) else None

    # 因子百分位函式（產業相對）
    pe_pct, _ = _pct_fn(stocks, "pe", lo=0.1, hi=100)      # 低者佳 → 用 1-pct
    pb_pct, _ = _pct_fn(stocks, "pb", lo=0.01, hi=30)      # 低者佳
    yl_pct, _ = _pct_fn(stocks, "yld", lo=0, hi=20)        # 高者佳
    roe_pct, _ = _pct_fn(stocks, "_roe", lo=-10, hi=50)    # 高者佳
    nm_pct, _ = _pct_fn(stocks, "nm", lo=-30, hi=40)       # 高者佳
    pe_hi_pct, _ = _pct_fn(stocks, "pe", lo=0.1, hi=200)   # 判定估值過熱

    def wavg(pairs):  # pairs: [(score0_100, weight), ...] 忽略 None
        num = den = 0.0
        for s, w in pairs:
            if s is not None:
                num += s * w
                den += w
        return (num / den) if den else None

    dist = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "—": 0}
    for r in stocks:
        # 價值
        vpe = pe_pct(r); vpb = pb_pct(r); vyl = yl_pct(r)
        value = wavg([(None if vpe is None else (1 - vpe) * 100, 0.45),
                      (None if vpb is None else (1 - vpb) * 100, 0.30),
                      (None if vyl is None else vyl * 100, 0.25)])
        # 品質
        rp = roe_pct(r); npv = nm_pct(r)
        quality = wavg([(None if rp is None else rp * 100, 0.55),
                        (None if npv is None else npv * 100, 0.45)])
        if quality is not None:
            if (r.get("q_eps") or 0) > 0 and (r.get("om") or -1) > 0:
                quality = min(100, quality + 5)  # 實際獲利小獎勵
        # 成長（低基期防呆）
        g = r.get("rev_cum_yoy")
        if g is None:
            g = r.get("rev_yoy")
        # 低基期防呆：單月或「累計」YoY 暴衝都算（完工認列/近零基期）
        lowbase = ((r.get("rev_yoy") is not None and r.get("rev_yoy") > 300) or
                   (r.get("rev_cum_yoy") is not None and r.get("rev_cum_yoy") > 300))
        ind_s = r.get("ind") or ""
        fin = ("金融" in ind_s) or ("保險" in ind_s) or ("證券" in ind_s) or ("銀行" in ind_s)
        growth = None
        if g is not None:
            gg = max(-30.0, min(40.0, g))
            growth = (gg + 30) / 70 * 100
            if lowbase:
                growth = min(growth, 62)  # 低基期尖峰不可進頂級
            if fin:
                growth = min(growth, 60)  # 金融保險「營收」YoY 屬定義性跳動，不予放大
        # 業外撐獲利：淨利>0 但本業虧損(qop<=0)、或淨利遠大於營業利益 → 獲利品質存疑
        qop, qni = r.get("q_op"), r.get("q_ni")
        waigai = (qop is not None and qni is not None and qni > 0 and not fin
                  and (qop <= 0 or qni > qop * 1.8))
        if waigai and quality is not None:
            quality = quality * 0.82  # 品質打折（獲利非本業）
        # 風險扣分
        pen = 0
        dn = []
        if waigai:
            pen += 4; dn.append("獲利多來自業外")
        if r.get("om") is not None and r["om"] < 0:
            pen += 10; dn.append("本業虧損")
        if (r.get("q_ni") is not None and r["q_ni"] < 0) or (r.get("q_eps") is not None and r["q_eps"] < 0):
            pen += 8; dn.append("單季淨損")
        if r.get("rev_cum_yoy") is not None and r["rev_cum_yoy"] < -15:
            pen += 6; dn.append("營收明顯衰退")
        ph = pe_hi_pct(r)
        if ph is not None and ph > 0.95 and (r.get("pe") or 0) > 40:
            pen += 5; dn.append("估值偏高")
        # 景氣循環尖峰防呆：極低 trailing PE + 高毛利 + 高營收YoY 常是循環頂點，
        # 此時 pe 被壓低 → value 與 ROE(=pb/pe) 同源被雙重灌頂，屬 value trap。
        cyc = ((r.get("nm") or 0) >= 20 and (r.get("rev_cum_yoy") or 0) >= 50
               and (r.get("pe") or 99) < 10 and not fin)
        if cyc:
            if quality is not None:
                quality = min(quality, 70)  # 尖峰 ROE 不可獨立進頂級
            pen += 6; dn.append("疑似循環獲利尖峰")
        pen = min(pen, 25)

        # 覆蓋度
        cov = sum(1 for x in (value, quality, growth) if x is not None)
        core = sum(1 for x in (vpe, vpb, vyl, rp, npv, growth) if x is not None)
        if cov < 2 or core < 2:
            r.update(sc=None, gr="—", sv=None, sq=None, sg=None, roe=r.get("_roe"), up=[], dn=[])
            dist["—"] += 1
            r.pop("_roe", None)
            continue

        base = wavg([(value, 0.35), (quality, 0.35), (growth, 0.30)])
        total = max(0, min(100, round((base or 0) - pen)))
        gr = "A" if total >= 76 else "B" if total >= 62 else "C" if total >= 46 else "D" if total >= 30 else "E"

        loss_flag = ((r.get("om") is not None and r["om"] < 0)
                     or (r.get("q_ni") is not None and r["q_ni"] < 0)
                     or (r.get("q_eps") is not None and r["q_eps"] < 0))
        up = []
        if value is not None and value >= 70 and not loss_flag:
            up.append("估值偏低")  # 不對虧損股（低 PB 常是財務困境定價）掛此標
        if r["_roe"] is not None and r["_roe"] >= 15 and not waigai and not loss_flag:
            up.append(f"高ROE≈{r['_roe']:.0f}%")
        if r.get("nm") is not None and r["nm"] >= 10 and (r.get("om") or -1) > 0 and not waigai:
            up.append("獲利穩健")
        if r.get("yld") is not None and r["yld"] >= 4.5:
            up.append(f"殖利率{r['yld']:.1f}%")
        if r.get("rev_cum_yoy") is not None and r["rev_cum_yoy"] >= 15 and not lowbase:
            up.append("營收成長")
        if lowbase:
            dn.append("低基期成長")

        r.update(sc=total, gr=gr,
                 sv=None if value is None else round(value),
                 sq=None if quality is None else round(quality),
                 sg=None if growth is None else round(growth),
                 roe=r["_roe"], up=up[:4], dn=dn[:4])
        r.pop("_roe", None)
        dist[gr] += 1

    # 非 stock / 停牌：標 N/A
    for r in rows:
        if "sc" not in r:
            r.update(sc=None, gr="—", sv=None, sq=None, sg=None, roe=None, up=[], dn=[])
    print("rating dist:", dist, file=sys.stderr)
    return dist


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    changed = False

    # ---- TW（失敗就整體 fail：台股是主體）----
    tw = build_tw()
    tw_stock = sum(1 for r in tw["rows"] if r["t"] == "stock")
    if tw_stock < 1500:
        sys.exit(f"SANITY FAIL: tw stock rows {tw_stock} < 1500")
    for mk, label in (("上市", "TWSE"), ("上櫃", "TPEx")):
        stocks = [r for r in tw["rows"] if r["t"] == "stock" and r["mk"] == mk]
        with_q = sum(1 for r in stocks if r.get("q"))
        if stocks and with_q / len(stocks) < 0.5:
            sys.exit(f"SANITY FAIL: {label} quarterly coverage {with_q}/{len(stocks)} < 50% (端點 schema 變了?)")
    rdist = score_tw(tw["rows"])
    rated = sum(v for k, v in rdist.items() if k != "—")
    if rated < 1000:
        sys.exit(f"SANITY FAIL: rated stocks {rated} < 1000 (評分因子可能大量缺失)")
    changed |= write_if_changed(f"{OUT_DIR}/tw.json", tw)

    # ---- US（失敗不拖垮 TW：保留舊檔、exit 0）----
    us = None
    try:
        us = build_us()
        if len(us["rows"]) < 5000:
            raise RuntimeError(f"us rows {len(us['rows'])} < 5000")
        changed |= write_if_changed(f"{OUT_DIR}/us.json", us)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: US build failed, keeping previous us.json: {e}", file=sys.stderr)
        us = load_existing(f"{OUT_DIR}/us.json")

    # ---- meta（僅在有變化時重寫）----
    if changed:
        meta = {
            "tw_asof": tw["asof"],
            "us_asof": (us or {}).get("asof"),
            "tw_rows": len(tw["rows"]), "tw_stocks": tw_stock,
            "tw_etfs": len(tw["rows"]) - tw_stock,
            "us_rows": len((us or {}).get("rows", [])),
            "generated": datetime.now(TPE).isoformat(timespec="seconds"),
        }
        with open(f"{OUT_DIR}/meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        print(json.dumps(meta, ensure_ascii=False, indent=1))
    else:
        print("no data changes at all — nothing to commit")


if __name__ == "__main__":
    main()
