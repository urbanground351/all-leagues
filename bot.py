import requests
import json
from datetime import datetime, timedelta

def fetch_matches():
    # Türkiye'deki tüm futbol maçlarını çeken ana link
    url = "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/turkey.json?lang=tr_TR&market=TR"
    
    final_data = {
        "last_updated": datetime.now().isoformat(),
        "source": "Kambi CDN (Genişletilmiş Türkiye Ağı)",
        "matches": []
    }
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for event_data in data.get("events", []):
                event = event_data.get("event", {})
                
                # FİLTRE DÜZELTİLDİ: Büyük/küçük harf ve Türkçe karakter sorunu kaldırıldı
                path_names = [str(p.get("name", "")).lower() for p in event.get("path", [])]
                is_super_lig = any("super" in p or "süper" in p for p in path_names)
                
                if not is_super_lig:
                    continue

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
                    "league": "Türkiye Süper Lig",
                    "home": home,
                    "away": away,
                    "time": match_time,
                    "date": match_date,
                    "odds": odds_info
                })
    except Exception as e:
        print(f"Bağlantı Hatası: {e}")

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
        print(f"İşlem Tamam! {len(final_data['matches'])} Süper Lig maçı başarıyla çekildi.")

if __name__ == "__main__":
    fetch_matches()
