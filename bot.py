import requests
import json
from datetime import datetime, timedelta

def fetch_matches():
    url = "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/turkey.json?lang=tr_TR&market=TR"
    
    final_data = {
        "last_updated": datetime.now().isoformat(),
        "source": "Kambi CDN (Filtresiz Tam Veri)",
        "matches": []
    }
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            # FİLTRE YOK: Gelen tüm maçları listeye ekliyoruz
            for event_data in data.get("events", []):
                event = event_data.get("event", {})
                
                # Kambi'nin lige tam olarak ne isim verdiğini yakalıyoruz
                path_names = [p.get("name", "") for p in event.get("path", [])]
                league_name = " > ".join(path_names) if path_names else "Bilinmeyen Lig"

                home = event.get("homeName", "Ev Sahibi")
                away = event.get("awayName", "Deplasman")
                
                start_time_str = event.get("start", "")
                if start_time_str:
                    utc_time = datetime.strptime(start_time_str[:19], "%Y-%m-%dT%H:%M:%S")
                    tr_time = utc_time + timedelta(hours=3)
                    match_time = tr_time.strftime("%H:%M")
                    match_date = tr_time.strftime("%d.%m.%Y")
                else:
                    match_time, match_date = "Belirsiz", "Belirsiz"
                    
                odds_info = "Oran Yok"
                for bet in event_data.get("betOffers", []):
                    criterion = bet.get("criterion", {}).get("name", "")
                    if bet.get("betOfferType", {}).get("name") == "Match" or "Full Time" in criterion:
                        outcomes = bet.get("outcomes", [])
                        if len(outcomes) >= 3:
                            ms1 = outcomes[0].get("odds", 0) / 1000
                            ms0 = outcomes[1].get("odds", 0) / 1000
                            ms2 = outcomes[2].get("odds", 0) / 1000
                            odds_info = f"MS1: {ms1:.2f} | X: {ms0:.2f} | MS2: {ms2:.2f}"
                        break
                        
                final_data["matches"].append({
                    "league": league_name,
                    "home": home,
                    "away": away,
                    "time": match_time,
                    "date": match_date,
                    "odds": odds_info
                })
    except Exception as e:
        print(f"Hata: {e}")

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    fetch_matches()
