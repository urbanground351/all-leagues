import difflib
import json
import random
import re
import time
import unicodedata
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

# 4 Majör Lig Kambi CDN Endpoint'leri
KAMBI_LEAGUES = {
    "Premier League": "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/england/premier_league.json?lang=tr_TR&market=TR",
    "La Liga": "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/spain/la_liga.json?lang=tr_TR&market=TR",
    "Serie A": "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/italy/serie_a.json?lang=tr_TR&market=TR",
    "Bundesliga": "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/germany/bundesliga.json?lang=tr_TR&market=TR"
}

# FBref Karşılık Gelen Lig URL'leri
FBREF_LEAGUE_URLS = {
    "Premier League": "https://fbref.com/en/comps/9/Premier-League-Stats",
    "La Liga": "https://fbref.com/en/comps/12/La-Liga-Stats",
    "Serie A": "https://fbref.com/en/comps/11/Serie-A-Stats",
    "Bundesliga": "https://fbref.com/en/comps/20/Bundesliga-Stats"
}

# İsteklerde kullanılacak User-Agent listesi
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
]

# Bilinen Takım Adı Eşleşmeleri
KNOWN_ALIASES = {
    "man city": "manchester city",
    "man utd": "manchester united",
    "manchester utd": "manchester united",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers",
    "inter": "internazionale",
    "inter milan": "internazionale",
    "ac milan": "milan",
    "atletico": "atletico madrid",
    "atl madrid": "atletico madrid",
    "athletic club": "athletic bilbao",
    "bilbao": "athletic bilbao",
    "koln": "cologne",
    "cologne": "cologne",
    "1 fc koln": "cologne",
    "fc koln": "cologne",
    "stuttgart": "vfb stuttgart",
    "leverkusen": "bayer leverkusen",
    "dortmund": "borussia dortmund",
    "bvb": "borussia dortmund",
    "gladbach": "borussia monchengladbach",
    "psg": "paris saint germain",
    "bayern": "bayern munich",
    "bayern munchen": "bayern munich"
}


def normalize_name(text: str) -> str:
    """Takım isimlerini karşılaştırma için temizler ve standartlaştırır."""
    if not text:
        return ""
    text = text.lower().strip()
    # Aksanları ve özel harfleri dönüştür (ç, ğ, ı, ö, ş, ü, é, ä, vb.)
    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    # Noktalama işaretlerini boşlukla değiştir
    text = re.sub(r"[^\w\s]", " ", text)
    # Gürültü kelimeleri ayıkla
    noise_tokens = {"fc", "cf", "afc", "ac", "sc", "1", "fk", "sk", "as", "ss", "rc", "de", "del", "la"}
    words = [w for w in text.split() if w not in noise_tokens]
    cleaned = " ".join(words)
    return KNOWN_ALIASES.get(cleaned, cleaned)


def match_team_stats(team_name: str, league_stats: dict) -> dict:
    """Kambi'den gelen takım ismini FBref istatistikleriyle akıllıca eşleştirir."""
    default_stats = {
        "team_matched": team_name,
        "xg": None,
        "xga": None,
        "form": "N/A"
    }

    if not league_stats or not team_name:
        return default_stats

    norm_target = normalize_name(team_name)

    # 1. Birebir veya Normalize Doğrudan Eşleşme
    for fb_name, stats in league_stats.items():
        if team_name.lower() == fb_name.lower() or norm_target == normalize_name(fb_name):
            res = stats.copy()
            res["team_matched"] = fb_name
            return res

    # 2. Alt Dize (Substring) Eşleşmesi
    for fb_name, stats in league_stats.items():
        norm_fb = normalize_name(fb_name)
        if norm_target and norm_fb and (norm_target in norm_fb or norm_fb in norm_target):
            res = stats.copy()
            res["team_matched"] = fb_name
            return res

    # 3. Benzerlik Oranı (Fuzzy Similarity >= 0.65)
    best_match = None
    best_score = 0.0
    for fb_name, stats in league_stats.items():
        norm_fb = normalize_name(fb_name)
        score = difflib.SequenceMatcher(None, norm_target, norm_fb).ratio()
        if score > best_score and score >= 0.65:
            best_score = score
            best_match = (fb_name, stats)

    if best_match:
        res = best_match[1].copy()
        res["team_matched"] = best_match[0]
        return res

    return default_stats


def scrape_fbref_league_stats(league_name: str, url: str) -> dict:
    """
    BeautifulSoup kullanarak FBref üzerinden lig puan durumundaki
    takımların xG (Gol Beklentisi), xGA ve son 5 maçlık form durumlarını çeker.
    Ban yememek için istekler arasına rastgele sleep ekler.
    """
    print(f"[{league_name}] FBref istatistikleri çekiliyor...")
    
    # Ban koruması: İstekler arasında rastgele gecikme
    sleep_seconds = round(random.uniform(2.5, 4.5), 2)
    time.sleep(sleep_seconds)

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
        "Referer": "https://www.google.com/"
    }

    team_stats = {}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"  [UYARI] FBref HTTP {response.status_code} yanıtı verdi ({league_name}).")
            return team_stats

        soup = BeautifulSoup(response.text, "html.parser")

        # Puan durumu tablosunu bul (stats_table sınıfı veya results id kalıbı)
        table = soup.find("table", {"class": lambda c: c and "stats_table" in c})
        if not table:
            table = soup.find("table", {"id": re.compile(r"results.*overall")})

        if not table:
            print(f"  [UYARI] {league_name} için FBref tablosu ayrıştırılamadı.")
            return team_stats

        tbody = table.find("tbody") or table

        for row in tbody.find_all("tr"):
            if row.get("class") and "thead" in row.get("class"):
                continue

            # Takım adı hücresi
            team_cell = row.find(["th", "td"], {"data-stat": ["team", "squad"]})
            if not team_cell:
                continue

            team_link = team_cell.find("a")
            team_name = team_link.get_text(strip=True) if team_link else team_cell.get_text(strip=True)
            if not team_name:
                continue

            # xG (Atılan Gol Beklentisi)
            xg_cell = row.find("td", {"data-stat": ["xg", "xg_for"]})
            try:
                xg_val = float(xg_cell.get_text(strip=True)) if xg_cell and xg_cell.get_text(strip=True) else None
            except ValueError:
                xg_val = None

            # xGA (Yenilen Gol Beklentisi)
            xga_cell = row.find("td", {"data-stat": ["xg_against", "xga"]})
            try:
                xga_val = float(xga_cell.get_text(strip=True)) if xga_cell and xga_cell.get_text(strip=True) else None
            except ValueError:
                xga_val = None

            # Son 5 maç (Form Durumu)
            last5_cell = row.find("td", {"data-stat": "last_5"})
            if last5_cell:
                form_items = [tag.get_text(strip=True) for tag in last5_cell.find_all(["a", "span", "div"])]
                form_str = " ".join([item for item in form_items if item]) if form_items else last5_cell.get_text(strip=True)
                form_str = " ".join(form_str.split()) if form_str else "N/A"
            else:
                form_str = "N/A"

            team_stats[team_name] = {
                "xg": xg_val,
                "xga": xga_val,
                "form": form_str
            }

        print(f"  [BİLGİ] {league_name}: {len(team_stats)} takım istatistiği başarıyla çekildi.")

    except Exception as e:
        print(f"  [HATA] FBref {league_name} çekilirken istisna oluştu: {e}")

    return team_stats


def fetch_kambi_league_matches(league_name: str, url: str) -> list:
    """Kambi CDN'den belirtilen ligin maçlarını ve 1X2 oranlarını çeker."""
    print(f"[{league_name}] Kambi maç verileri çekiliyor...")
    matches = []
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"  [UYARI] Kambi HTTP {response.status_code} ({league_name})")
            return matches

        data = response.json()
        for event_data in data.get("events", []):
            event = event_data.get("event", {})
            home = event.get("homeName", "Ev Sahibi")
            away = event.get("awayName", "Deplasman")

            # Saat & Tarih (TSİ / UTC+3 Dönüşümü)
            start_iso = event.get("start", "")
            if start_iso:
                try:
                    utc_time = datetime.strptime(start_iso[:19], "%Y-%m-%dT%H:%M:%S")
                    tr_time = utc_time + timedelta(hours=3)
                    match_time = tr_time.strftime("%H:%M")
                    match_date = tr_time.strftime("%d.%m.%Y")
                except Exception:
                    match_time, match_date = "Belirsiz", "Belirsiz"
            else:
                match_time, match_date = "Belirsiz", "Belirsiz"

            # Oranları ayrıştır (1X2 / Match Result)
            ms1, ms0, ms2 = None, None, None
            for bet in event_data.get("betOffers", []):
                bet_type = bet.get("betOfferType", {}).get("name", "")
                crit_name = bet.get("criterion", {}).get("name", "")
                crit_label = bet.get("criterion", {}).get("label", "")
                criteria = f"{crit_name} {crit_label}".lower()

                if bet_type == "Match" or "full time" in criteria or "maç" in criteria or "1x2" in criteria:
                    for outcome in bet.get("outcomes", []):
                        label = str(outcome.get("label", ""))
                        typ = outcome.get("type", "")
                        val = outcome.get("odds", 0) / 1000.0

                        if label == "1" or typ == "OT_ONE":
                            ms1 = round(val, 2)
                        elif label.upper() == "X" or typ == "OT_CROSS":
                            ms0 = round(val, 2)
                        elif label == "2" or typ == "OT_TWO":
                            ms2 = round(val, 2)

                    if ms1 is not None and ms0 is not None and ms2 is not None:
                        break

            if ms1 is not None and ms0 is not None and ms2 is not None:
                odds_summary = f"MS1: {ms1:.2f} | X: {ms0:.2f} | MS2: {ms2:.2f}"
            else:
                odds_summary = "Oran Yok"

            matches.append({
                "league": league_name,
                "home": home,
                "away": away,
                "date": match_date,
                "time": match_time,
                "timestamp": start_iso,
                "odds": {
                    "ms1": ms1,
                    "x": ms0,
                    "ms2": ms2,
                    "summary": odds_summary
                }
            })

        print(f"  [BİLGİ] {league_name}: {len(matches)} maç ayrıştırıldı.")
    except Exception as e:
        print(f"  [HATA] Kambi {league_name} çekilirken hata: {e}")

    return matches


def generate_api_data():
    """
    Tüm liglerin Kambi oranlarını ve FBref istatistiklerini toplar,
    birleştirir ve veritabanı yerine api.json dosyasına statik olarak yazar.
    """
    print("=== Spor Analiz Veri Toplama Başlatıldı ===")

    # 1. FBref İstatistiklerini Çek
    all_league_stats = {}
    for league_name, fbref_url in FBREF_LEAGUE_URLS.items():
        stats = scrape_fbref_league_stats(league_name, fbref_url)
        all_league_stats[league_name] = stats

    # 2. Kambi Oranlarını Çek ve İstatistiklerle Eşleştir
    all_matches = []
    for league_name, kambi_url in KAMBI_LEAGUES.items():
        league_matches = fetch_kambi_league_matches(league_name, kambi_url)
        league_stats = all_league_stats.get(league_name, {})

        for match in league_matches:
            home_stats = match_team_stats(match["home"], league_stats)
            away_stats = match_team_stats(match["away"], league_stats)

            match["stats"] = {
                "home": home_stats,
                "away": away_stats
            }
            all_matches.append(match)

    # 3. Statik JSON Çıktısı (api.json ve matches.json)
    output_data = {
        "last_updated": datetime.now().isoformat(),
        "source": "Kambi CDN + FBref Stats",
        "total_matches": len(all_matches),
        "leagues": list(KAMBI_LEAGUES.keys()),
        "matches": all_matches
    }

    for output_filename in ["api.json", "matches.json"]:
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n[BAŞARILI] Toplam {len(all_matches)} maç 'api.json' ve 'matches.json' dosyalarına kaydedildi!")


if __name__ == "__main__":
    generate_api_data()

