import os
import requests
from dotenv import load_dotenv

load_dotenv()

URL = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"

def search_vacant(middle, small, detail=None, checkin="2026-08-08",
                  checkout="2026-08-09", max_charge=5000):
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

if __name__ == "__main__":
    for x in search_vacant("tokyo", "tokyo", "F"):
        print(f'{x["total"]}円｜{x["hotel"]}｜{x["plan"]}｜★{x["review"]}')