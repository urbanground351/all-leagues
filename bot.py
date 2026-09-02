import difflib
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

# 4 Majör Lig Konfigürasyonu (Aktif 2026-2027 Sezonu)
LEAGUES_CONFIG = {
    "super_lig": {
        "name": "Trendyol Süper Lig",
        "kambi_url": "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/turkey/super_lig.json?lang=tr_TR&market=TR",
        "espn_standings_url": "https://site.api.espn.com/apis/v2/sports/soccer/tur.1/standings?season=2026",
        "espn_league_id": "tur.1",
        "output_file": "super_lig.json"
    },
    "premier_league": {
        "name": "English Premier League",
        "kambi_url": "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/england/premier_league.json?lang=tr_TR&market=TR",
        "espn_standings_url": "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings?season=2026",
        "espn_league_id": "eng.1",
        "output_file": "premier_league.json"
    },
    "la_liga": {
        "name": "Spanish LALIGA",
        "kambi_url": "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/spain/la_liga.json?lang=tr_TR&market=TR",
        "espn_standings_url": "https://site.api.espn.com/apis/v2/sports/soccer/esp.1/standings?season=2026",
        "espn_league_id": "esp.1",
        "output_file": "la_liga.json"
    },
    "bundesliga": {
        "name": "German Bundesliga",
        "kambi_url": "https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/football/germany/bundesliga.json?lang=tr_TR&market=TR",
        "espn_standings_url": "https://site.api.espn.com/apis/v2/sports/soccer/ger.1/standings?season=2026",
        "espn_league_id": "ger.1",
        "output_file": "bundesliga.json"
    }
}

def normalize_name(text: str) -> str:
    """Takım isimlerini karşılaştırma için temizler ve standartlaştırır."""
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    text = re.sub(r"[^\w\s]", " ", text)
    noise = {
        "fc", "cf", "afc", "ac", "sc", "1", "fk", "sk", "as", "ss", "rc",
        "de", "del", "la", "bb", "sfk", "belediyesi", "belediyespor", "kulubu"
    }
    tokens = [w for w in text.split() if w not in noise]
    cleaned = " ".join(tokens)
    aliases = {
        "koln": "cologne",
        "cologne": "cologne",
        "man city": "manchester city",
        "man utd": "manchester united",
        "spurs": "tottenham hotspur",
        "tottenham": "tottenham hotspur",
        "wolves": "wolverhampton wanderers",
        "atletico": "atletico madrid",
        "bilbao": "athletic club",
        "stuttgart": "vfb stuttgart",
        "leverkusen": "bayer leverkusen",
        "dortmund": "borussia dortmund",
        "gladbach": "borussia monchengladbach",
        "bayern": "bayern munich",
        "istanbul buyuksehir": "istanbul basaksehir",
        "basaksehir": "istanbul basaksehir",
        "amed sportif faaliyetler": "amed",
        "brighton": "brighton hove albion",
        "deportivo a coruna": "deportivo"
    }
    return aliases.get(cleaned, cleaned)


def match_team(kambi_name: str, espn_teams: dict) -> dict:
    """Kambi takım adını ligin resmi ESPN takımlarıyla eşleştirir."""
    if not kambi_name or not espn_teams:
        return None
    norm_k = normalize_name(kambi_name)

    # 1. Birebir veya normalize eşleşme
    for name, data in espn_teams.items():
        if norm_k == normalize_name(name):
            return data

    # 2. En yüksek benzerlik oranı
    best_match = None
    best_score = 0.0
    for name, data in espn_teams.items():
        score = difflib.SequenceMatcher(None, norm_k, normalize_name(name)).ratio()
        if score > best_score and score >= 0.70:
            best_score = score
            best_match = data

    return best_match


def fetch_team_recent_matches(espn_league_id: str, team_id: str, team_name: str) -> list:
    """Takımın bu aktif sezon (2026) tamamlanmış maçlarını çeker."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn_league_id}/teams/{team_id}/schedule?season=2026"
    try:
        r = requests.get(url, timeout=6)
        if r.status_code != 200:
            return []
        events = r.json().get("events", [])
        completed = [
            ev for ev in events
            if ev.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed")
        ]
        recent = []
        for ev in completed[-5:]:
            comp = ev.get("competitions", [{}])[0]
            comps = comp.get("competitors", [])
            if len(comps) < 2:
                continue
            c0, c1 = comps[0], comps[1]
            if team_name.lower() in c0.get("team", {}).get("displayName", "").lower():
                my_c, opp_c, venue = c0, c1, "home"
            else:
                my_c, opp_c, venue = c1, c0, "away"

            try:
                my_sc = int(my_c.get("score", {}).get("value", 0))
                opp_sc = int(opp_c.get("score", {}).get("value", 0))
            except (ValueError, TypeError):
                continue

            res = "W" if my_sc > opp_sc else ("D" if my_sc == opp_sc else "L")
            recent.append({
                "opponent": opp_c.get("team", {}).get("displayName", "Bilinmeyen"),
                "score": f"{my_sc} - {opp_sc}",
                "result": res,
                "venue": venue,
                "date": ev.get("date", "")[:10]
            })
        return recent
    except Exception:
        return []



def process_league(league_key: str, cfg: dict):
    """Bir ligin puan durumunu, tüm takımlarını, son maçlarını ve Kambi maçlarını işler."""
    print(f"\n[{cfg['name']}] Bilgileri toplanıyor...")

    # 1. Lig Puan Durumu ve Tüm Takımlar (ESPN)
    espn_teams = {}
    teams_list = []
    try:
        r = requests.get(cfg["espn_standings_url"], timeout=10)
        if r.status_code == 200:
            entries = r.json().get("children", [{}])[0].get("standings", {}).get("entries", [])
            for e in entries:
                t_obj = e.get("team", {})
                t_id = t_obj.get("id")
                t_name = t_obj.get("displayName")
                s = {st["name"]: st.get("value", 0) for st in e.get("stats", [])}

                gp = int(s.get("gamesPlayed", 0))
                gf = int(s.get("pointsFor", 0))
                ga = int(s.get("pointsAgainst", 0))
                wins = int(s.get("wins", 0))

                team_data = {
                    "name": t_name,
                    "id": t_id,
                    "rank": int(s.get("rank", 0)),
                    "points": int(s.get("points", 0)),
                    "played": gp,
                    "wins": wins,
                    "draws": int(s.get("ties", 0)),
                    "losses": int(s.get("losses", 0)),
                    "goals_for": gf,
                    "goals_against": ga,
                    "goal_diff": int(s.get("pointDifferential", 0)),
                    "avg_scored": round(gf / gp, 2) if gp > 0 else 0.0,
                    "avg_conceded": round(ga / gp, 2) if gp > 0 else 0.0,
                    "win_rate": round((wins / gp) * 100, 1) if gp > 0 else 0.0,
                    "recent_matches": []
                }
                espn_teams[t_name] = team_data
                teams_list.append(team_data)

            print(f"  -> {len(teams_list)} takım puan durumu yüklendi.")
    except Exception as e:
        print(f"  [Hata] Puan durumu alınamadı: {e}")

    # 2. Takımların Son 5 Maçını Paralel Olarak Çek
    def load_sched(t):
        recent = fetch_team_recent_matches(cfg["espn_league_id"], t["id"], t["name"])
        t["recent_matches"] = recent

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(load_sched, teams_list))

    print(f"  -> {len(teams_list)} takımın son maç geçmişleri tamamlandı.")

    # 3. Kambi'den Maçları ve 1X2 Oranlarını Çek
    upcoming_matches = []
    kambi_events = []
    try:
        r_kambi = requests.get(cfg["kambi_url"] + "&limit=100", timeout=15)
        if r_kambi.status_code == 200:
            r_kambi.encoding = "utf-8"
            kambi_events = r_kambi.json().get("events", [])
    except Exception as e:
        print(f"  [Hata] Kambi verisi alınamadı: {e}")

    # Alt ligleri filtrele: Sadece resmi lig takımları arasındaki maçlar
    valid_events = []
    for ev_data in kambi_events:
        event = ev_data.get("event", {})
        home_raw = event.get("homeName", "")
        away_raw = event.get("awayName", "")

        home_t = match_team(home_raw, espn_teams)
        away_t = match_team(away_raw, espn_teams)

        if home_t and away_t:
            valid_events.append((ev_data, home_t, away_t))

    print(f"  -> {len(valid_events)} geçerli lig maçı filtrelendi.")

    # 4. Kambi Maç Detaylarından 2.5 Alt/Üst ve KG Oranlarını Paralel Çek
    def process_match(item):
        ev_data, home_t, away_t = item
        event = ev_data.get("event", {})
        event_id = event.get("id")

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

        # 1X2 Oranları
        ms1, ms0, ms2 = None, None, None
        for bet in ev_data.get("betOffers", []):
            bet_type = bet.get("betOfferType", {}).get("name", "")
            crit = (bet.get("criterion", {}).get("name", "") + " " + bet.get("criterion", {}).get("label", "")).lower()
            if bet_type == "Match" or "full time" in crit or "maç" in crit or "1x2" in crit:
                for oc in bet.get("outcomes", []):
                    lbl = str(oc.get("label", ""))
                    typ = oc.get("type", "")
                    val = oc.get("odds", 0) / 1000.0
                    if lbl == "1" or typ == "OT_ONE":
                        ms1 = round(val, 2)
                    elif lbl.upper() == "X" or typ == "OT_CROSS":
                        ms0 = round(val, 2)
                    elif lbl == "2" or typ == "OT_TWO":
                        ms2 = round(val, 2)
                if ms1 and ms0 and ms2:
                    break

        odds_summary = f"MS1: {ms1:.2f} | X: {ms0:.2f} | MS2: {ms2:.2f}" if (ms1 and ms0 and ms2) else "Oran Yok"

        # Form dizilimleri
        home_form = [m["result"] for m in home_t.get("recent_matches", [])[-5:]]
        away_form = [m["result"] for m in away_t.get("recent_matches", [])[-5:]]

        match_obj = {
            "league": cfg["name"],
            "home": home_t["name"],
            "away": away_t["name"],
            "date": match_date,
            "time": match_time,
            "odds": odds_summary,
            "odds_detail": {
                "ms1": ms1,
                "x": ms0,
                "ms2": ms2
            },
            "home_stats": {
                "rank": home_t["rank"],
                "points": home_t["points"],
                "played": home_t["played"],
                "avg_scored": home_t["avg_scored"],
                "avg_conceded": home_t["avg_conceded"],
                "form": home_form
            },
            "away_stats": {
                "rank": away_t["rank"],
                "points": away_t["points"],
                "played": away_t["played"],
                "avg_scored": away_t["avg_scored"],
                "avg_conceded": away_t["avg_conceded"],
                "form": away_form
            }
        }
        return match_obj

    with ThreadPoolExecutor(max_workers=8) as executor:
        upcoming_matches = list(executor.map(process_match, valid_events))

    # Maçları başlama tarihine ve saatine göre kronolojik sırala
    upcoming_matches.sort(key=lambda m: (m.get("date", "").split(".")[::-1], m.get("time", "")))

    # 5. Bu Lig İçin Özel JSON Dosyasını Kaydet
    league_payload = {
        "league": cfg["name"],
        "season": "2026-2027",
        "last_updated": datetime.now().isoformat(),
        "total_teams": len(teams_list),
        "teams": teams_list,
        "upcoming_matches": upcoming_matches
    }

    with open(cfg["output_file"], "w", encoding="utf-8") as f:
        json.dump(league_payload, f, ensure_ascii=False, indent=2)

    print(f"  [BAŞARILI] {cfg['output_file']} kaydedildi ({len(teams_list)} takım, {len(upcoming_matches)} maç).")
    return upcoming_matches


def main():
    print("=== Çoklu Lig Spor Analiz & Tahmin Veri Toplayıcı ===")
    all_matches_combined = []

    for key, cfg in LEAGUES_CONFIG.items():
        matches = process_league(key, cfg)
        all_matches_combined.extend(matches)

    # Genel matches.json dosyasını da güncelle (Mevcut sitenizle geriye dönük tam uyum için)
    combined_payload = {
        "last_updated": datetime.now().isoformat(),
        "source": "Kambi CDN + ESPN Resmi API",
        "total_matches": len(all_matches_combined),
        "leagues": [cfg["name"] for cfg in LEAGUES_CONFIG.values()],
        "matches": all_matches_combined
    }
    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(combined_payload, f, ensure_ascii=False, indent=2)

    print(f"\n[TAMAMLANDI] Tüm ligler ayrı JSON dosyalarına ve 'matches.json'a kaydedildi!")


if __name__ == "__main__":
    main()


