"""main.py — クーポン条件→検索帯逆算→楽天API在庫検索→Discord通知（Step 4結合版）"""
import os
import time
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

URL = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]


# ---------- Step 2: 逆算ロジック ----------

def calc_band(discount, min_spend, target_per_night=3000,
              target_rate=0.70, max_nights=3):
    """クーポン(割引額discount, 最低利用金額min_spend)から
    泊数ごとの検索帯 {n: (下限, 上限)} を返す。成立不能な泊数は除外。

    条件: n泊合計Pに対して
      - クーポン適用可能: P >= min_spend
      - 実質3000円/泊以下: P - discount <= target_per_night * n
      - 割引率70%以上:     discount / P >= target_rate
    """
    bands = {}
    for n in range(1, max_nights + 1):
        upper = min(
            target_per_night * n + discount,  # 実質単価の条件
            int(discount / target_rate),      # 割引率の条件
        )
        lower = min_spend
        if lower <= upper:
            bands[n] = (lower, upper)
    return bands


# ---------- Step 1: 楽天APIラッパー ----------

def search_vacant(middle, small, detail=None, checkin=None, checkout=None,
                  min_charge=None, max_charge=5000):
    """VacantHotelSearchを叩いてプラン一覧を返す。該当0件は空リスト。
    ※minCharge/maxChargeは「1泊あたり」の金額に掛かる。"""
    params = {
        "applicationId": os.environ["RAKUTEN_APP_ID"],
        "format": "json",
        "checkinDate": checkin,
        "checkoutDate": checkout,
        "largeClassCode": "japan",
        "middleClassCode": middle,
        "smallClassCode": small,
        "maxCharge": max_charge,
    }
    if detail:
        params["detailClassCode"] = detail
    if min_charge:
        params["minCharge"] = min_charge
    headers = {"accessKey": os.environ["RAKUTEN_ACCESS_KEY"]}
    r = requests.get(URL, params=params, headers=headers)
    if r.status_code == 404:  # Data Not Found = 0件
        return []
    r.raise_for_status()

    results = []
    for h in r.json().get("hotels", []):
        basic = h["hotel"][0]["hotelBasicInfo"]
        room_info = h["hotel"][1]["roomInfo"]
        # roomBasicInfoとdailyChargeが交互に並ぶのでペアで読む
        for i in range(0, len(room_info) - 1, 2):
            plan = room_info[i]["roomBasicInfo"]
            charge = room_info[i + 1]["dailyCharge"]
            results.append({
                "hotel": basic["hotelName"],
                "plan": plan["planName"] or plan["roomName"],
                "total": charge["total"],
                "reserve_url": plan["reserveUrl"],
                "review": basic.get("reviewAverage"),
            })
    return results


# ---------- Step 3: Discord通知 ----------

def notify(message):
    """Discord webhookに投稿。失敗しても本体処理は止めない。"""
    try:
        requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)
    except requests.RequestException as e:
        print(f"通知失敗: {e}")


def notify_deals(deals, coupon, checkin):
    """ディール一覧をDiscordの2,000文字制限に収まるよう分割送信。"""
    header = (f'🏨 **お宝検知！** クーポン: {coupon["discount"]:,}円引き'
              f'（最低利用 {coupon["min_spend"]:,}円）チェックイン {checkin}\n')
    chunk = header
    for d in sorted(deals, key=lambda x: x["effective"]):
        line = (f'\n**実質{d["effective"]:,}円**（{d["nights"]}泊合計{d["total"]:,}円・'
                f'割引率{d["rate"]:.0%}）｜{d["hotel"]}｜{d["plan"]}｜★{d["review"]}\n'
                f'[予約ページ](<{d["reserve_url"]}>)\n')
        if len(chunk) + len(line) > 1900:  # 2,000文字制限対策
            notify(chunk)
            chunk = ""
        chunk += line
    if chunk:
        notify(chunk)


# ---------- Step 4: 結合 ----------

def find_deals(coupon, areas, checkin, target_per_night=3000,
               target_rate=0.70, max_nights=3):
    """coupon = {"discount": 割引額, "min_spend": 最低利用金額}
    areas  = [(middleClassCode, smallClassCode, detailClassCode or None), ...]
    戻り値: 条件を満たすディールのリスト
    """
    bands = calc_band(coupon["discount"], coupon["min_spend"],
                      target_per_night, target_rate, max_nights)
    if not bands:
        print("このクーポンは目標条件と両立不能（検索不要で棄却）")
        return []

    deals = []
    for n, (lower, upper) in bands.items():
        checkout = (date.fromisoformat(checkin) + timedelta(days=n)).isoformat()
        for middle, small, detail in areas:
            plans = search_vacant(middle, small, detail,
                                  checkin=checkin, checkout=checkout,
                                  min_charge=lower // n,   # APIは1泊単価なのでnで割る
                                  max_charge=upper // n)
            time.sleep(1)  # レート制限対策（1リクエスト/秒）
            for p in plans:
                total = p["total"] * n  # ※本来はdailyChargeを日毎に合算する。簡易版。
                effective = total - coupon["discount"]
                rate = coupon["discount"] / total if total else 0
                if total < coupon["min_spend"]:
                    continue
                if effective > target_per_night * n:   # 実質3000円/泊超は除外
                    continue
                if rate < target_rate:                  # 割引率70%未満は除外
                    continue
                deals.append({**p, "nights": n, "total": total,
                              "effective": effective, "rate": rate})
    return deals


if __name__ == "__main__":
    # クーポン条件を手入力（Step 5〜6で自動取得に置き換え予定）
    coupon = {"discount": 10000, "min_spend": 10000}
    areas = [
        ("tokyo", "tokyo", "F"),  # 新宿・中野・荻窪・四谷
        ("tokyo", "tokyo", "I"),  # 上野・浅草・北千住
    ]
    checkin = (date.today() + timedelta(days=4)).isoformat()

    deals = find_deals(coupon, areas, checkin)
    print(f"ヒット: {len(deals)}件")
    if deals:
        notify_deals(deals, coupon, checkin)
        print("Discordに通知した")