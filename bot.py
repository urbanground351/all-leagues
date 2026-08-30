import requests
import json
import urllib.parse
from datetime import datetime, timedelta

def fetch_matches():
    final_data = {
        "last_updated": datetime.now().isoformat(),
        "source": "FotMob (Proxy Kamuflajı + Oranlar)",
        "matches": []
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        # Önümüzdeki 7 günü tarıyoruz
        for i in range(7):
            current_date = datetime.now() + timedelta(days=i)
            date_str = current_date.strftime("%Y%m%d")
            
            # FotMob linkini şifreleyip Proxy sunucusunun arkasına saklıyoruz
            target_url = f"https://www.fotmob.com/api/matches?date={date_str}"
            proxy_url = f"https://api.allorigins.win/raw?url={urllib.parse.quote(target_url)}"
            
            response = requests.get(proxy_url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                data = response.json()
                for league in data.get("leagues", []):
                    # 71 = Türkiye Süper Lig
                    if league.get("primaryId") == 71 or league.get("id") == 71:
                        for match in league.get("matches", []):
                            match_id = match.get("id")
                            home = match.get("home", {}).get("name", "Ev")
                            away = match.get("away", {}).get("name", "Deplasman")
                            match_time = match.get("status", {}).get("startTimeStr", "Belirsiz")
                            
                            odds_info = "Oran Yok"
                            
                            try:
                                # Detay sayfasını da aynı şekilde Proxy üzerinden çekiyoruz
                                detail_target = f"https://www.fotmob.com/api/matchDetails?matchId={match_id}"
                                detail_proxy = f"https://api.allorigins.win/raw?url={urllib.parse.quote(detail_target)}"
                                detail_res = requests.get(detail_proxy, headers=headers, timeout=15)
                                
                                if detail_res.status_code == 200:
                                    detail_data = detail_res.json()
                                    odds_array = detail_data.get("content", {}).get("odds", {}).get("data", [])
                                    if odds_array:
                                        for odd_type in odds_array:
                                            # İddaa MS tablosunu bul
                                            if odd_type.get("title") == "1x2" or "Maç Sonucu" in odd_type.get("title", ""):
                                                choices = odd_type.get("choices", [])
                                                if len(choices) >= 3:
                                                    ms1 = choices[0].get("odds", "-")
                                                    ms0 = choices[1].get("odds", "-")
                                                    ms2 = choices[2].get("odds", "-")
                                                    odds_info = f"MS1: {ms1} | X: {ms0} | MS2: {ms2}"
                                                break
                            except Exception:
                                pass
                                
                            final_data["matches"].append({
                                "league": "Türkiye Süper Lig",
                                "home": home,
                                "away": away,
                                "time": match_time,
                                "date": current_date.strftime("%d.%m.%Y"),
                                "odds": odds_info
                            })
    except Exception as e:
        print(f"Hata: {e}")

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    fetch_matches()
