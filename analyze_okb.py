# -*- coding: utf-8 -*-
"""临时分析：逐日重算 OKB/BTC 五因子信号，定位 0.0017 附近区间及邮件触发情况"""
import datetime
import numpy as np
import check_signal as cs

# GitHub Actions 在美国，优先原始 okx.com，失败再镜像
BASES = ["https://www.okx.com", "https://www.oyigwcn.biz"]


def fetch(inst, days=1095):
    last_err = None
    for base in BASES:
        cs.API_BASE = base
        try:
            rows = cs.fetch_candles(inst, "1D", days)
            print(f"  数据源 {base} 成功，{len(rows)} 天")
            return rows
        except Exception as e:
            last_err = e
            print(f"  数据源 {base} 失败: {e}")
    raise last_err


print("拉取数据...")
okb = fetch("OKB-BTC")
btc = fetch("BTC-USDT")
n = len(okb)
print("范围:", okb[0]["ts"].date(), "~", okb[-1]["ts"].date())

# 逐日重算（从第 250 天开始，保证 MA200 可用）
records = []
for i in range(250, n):
    o_slice = okb[: i + 1]
    b_slice = btc[: i + 1]
    # 对齐 BTC 长度（用 min）
    lb = len(b_slice)
    factors = {
        "valuation": cs.factor_valuation(o_slice),
        "event": {"score": 40.0, "desc": "无事件(固定)"},
        "technical": cs.factor_technical(o_slice),
        "trend": cs.factor_trend(b_slice),
        "sentiment": cs.factor_sentiment(0.0001),  # 中性费率
    }
    total, action, position, color = cs.combine(factors)
    records.append({
        "date": okb[i]["ts"].date(),
        "close": okb[i]["close"],
        "high": okb[i]["high"],
        "val": factors["valuation"]["score"],
        "tech": factors["technical"]["score"],
        "trend": factors["trend"]["score"],
        "total": total,
        "action": action,
    })

# 1. 2026年8月以来 close>=0.00155 或 high>=0.0016
print("\n=== 2026-08以来 close>=0.00155 或 high>=0.0016 ===")
cut = datetime.date(2026, 8, 1)
for r in records:
    if r["date"] >= cut and (r["close"] >= 0.00155 or r["high"] >= 0.0016):
        flag = "  <<<" if r["close"] >= 0.0016 else ""
        print(f"{r['date']} close={r['close']:.6f} high={r['high']:.6f} "
              f"val={r['val']:.0f} tech={r['tech']:.0f} trend={r['trend']:.0f} "
              f"total={r['total']:.1f} [{r['action']}]{flag}")

# 2. 信号变化序列（收盘层面），看是否曾进入减仓/卖出，以及是否满足邮件触发
print("\n=== 2026年以来 收盘信号变化序列 ===")
prev = None
for r in records:
    if r["date"].year < 2026:
        prev = r["action"]
        continue
    if r["action"] != prev:
        is_alert = ("买入" in r["action"]) or ("卖出" in r["action"]) or ("减仓" in r["action"])
        mark = "★会发邮件" if is_alert else "（不发邮件）"
        print(f"{r['date']} {prev} → {r['action']} ({r['total']:.1f}) {mark}")
        prev = r["action"]
print("最终信号:", records[-1]["action"], f"({records[-1]['total']:.1f})")

# 3. 全段是否出现过减仓/卖出收盘信号
warn = [r for r in records if r["action"] in ("减仓", "卖出")]
print(f"\n=== 回测段内收盘进入减仓/卖出的天数: {len(warn)} ===")
for r in warn:
    print(f"  {r['date']} close={r['close']:.6f} total={r['total']:.1f} [{r['action']}]")
