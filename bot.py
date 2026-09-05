import difflib
import json
import re
import unicodedata
import os
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    TR_ZONE = ZoneInfo("Europe/Istanbul")
except ZoneInfoNotFoundError:
    # Türkiye yıl boyunca UTC+3 kullanır; Windows'ta tzdata paketi yoksa bu eşdeğerdir.
    TR_ZONE = timezone(timedelta(hours=3))


def build_http_session():
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    # ESPN bazı ortamlarda özel User-Agent başlıklarını 403 ile reddediyor;
    # requests'in varsayılan başlıklarını kullanmak daha uyumlu.
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


HTTP = build_http_session()


def season_window(now=None):
    now = now or datetime.now(TR_ZONE)
    season_start_year = now.year if now.month >= 7 else now.year - 1
    start = datetime(season_start_year, 7, 1, tzinfo=TR_ZONE)
    end = datetime(season_start_year + 1, 6, 30, tzinfo=TR_ZONE)
    return start, end


def upcoming_window(now=None, days=14):
    now = now or datetime.now(TR_ZONE)
    start = now.date()
    end = (now + timedelta(days=days)).date()
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def safe_int(value, default=0):
    try:
        return int(float(value)) if value is not None else default
    except (TypeError, ValueError):
        return default

# 4 Aktif Lig Konfigürasyonu (Süper Lig + Premier Lig + La Liga + Bundesliga)
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


def load_existing_matches_map() -> dict:
    """Mevcut lig dosyalarından maçların açılış oranlarını ve zaman damgalı geçmişini yükler."""
    matches_map = {}
    files = ["super_lig.json", "premier_league.json", "la_liga.json", "bundesliga.json"]
    for fname in files:
        try:
            with open(fname, "r", encoding="utf-8") as f:
                data = json.load(f)
                mlist = data.get("upcoming_matches", [])
                for m in mlist:
                    h = normalize_name(m.get("home", ""))
                    a = normalize_name(m.get("away", ""))
                    if not h or not a:
                        continue
                    key = f"{h}_vs_{a}"
                    if key not in matches_map:
                        matches_map[key] = m
        except Exception:
            continue
    return matches_map


def process_league(league_key: str, cfg: dict, existing_matches_map: dict):
    """Bir ligin puan durumunu, tamamlanmış maçlarını (şut ve gol verileriyle) ve Kambi maçlarını işler (Saf Veri)."""
    print(f"\n[{cfg['name']}] Bilgileri toplanıyor...")
    now_iso = datetime.now(TR_ZONE).isoformat()

    # 1. Lig Puan Durumu ve Tüm Takımlar (ESPN)
    espn_teams = {}
    teams_list = []
    try:
        r = HTTP.get(cfg["espn_standings_url"], timeout=20)
        if r.status_code == 200:
            entries = r.json().get("children", [{}])[0].get("standings", {}).get("entries", [])
            for e in entries:
                t_obj = e.get("team", {})
                t_id = t_obj.get("id")
                t_name = t_obj.get("displayName")
                s = {st["name"]: st.get("value", 0) for st in e.get("stats", [])}

                gp = safe_int(s.get("gamesPlayed"))
                gf = safe_int(s.get("pointsFor"))
                ga = safe_int(s.get("pointsAgainst"))
                wins = safe_int(s.get("wins"))

                team_data = {
                    "name": t_name,
                    "id": t_id,
                    "rank": safe_int(s.get("rank")),
                    "points": safe_int(s.get("points")),
                    "played": gp,
                    "wins": wins,
                    "draws": safe_int(s.get("ties")),
                    "losses": safe_int(s.get("losses")),
                    "goals_for": gf,
                    "goals_against": ga,
                    "goal_diff": safe_int(s.get("pointDifferential")),
                    "avg_scored": round(gf / gp, 2) if gp > 0 else 0.0,
                    "avg_conceded": round(ga / gp, 2) if gp > 0 else 0.0,
                    "win_rate": round((wins / gp) * 100, 1) if gp > 0 else 0.0,
                    "matches": []
                }
                espn_teams[t_name] = team_data
                teams_list.append(team_data)

            print(f"  -> {len(teams_list)} takım puan durumu yüklendi.")
    except Exception as e:
        print(f"  [Hata] Puan durumu alınamadı: {e}")

    if not teams_list:
        raise RuntimeError("ESPN puan durumu boş döndü; mevcut JSON korunuyor")

    # 2. Ligin Tamamlanmış Maçlarını ve İsabetli Şut Verilerini Çek (ESPN Scoreboard)
    try:
        season_start, season_end = season_window()
        sb_url = (
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
            f"{cfg['espn_league_id']}/scoreboard?dates={season_start:%Y%m%d}-"
            f"{season_end:%Y%m%d}&limit=1000"
        )
        r_sb = HTTP.get(sb_url, timeout=25)
        if r_sb.status_code == 200:
            events = r_sb.json().get('events', [])
            completed_events = [
                ev for ev in events
                if ev.get('competitions', [{}])[0].get('status', {}).get('type', {}).get('completed')
            ]
            print(f"  -> {len(completed_events)} tamamlanmış lig maçı ve şut istatistikleri işleniyor.")

            def extract_sot(comp):
                for s in comp.get('statistics', []):
                    if s.get('name') == 'shotsOnTarget':
                        try:
                            return float(s.get('displayValue', 0))
                        except Exception:
                            return 0.0
                return 0.0

            for ev in completed_events:
                comp = ev.get('competitions', [{}])[0]
                comps = comp.get('competitors', [])
                if len(comps) < 2:
                    continue
                c0, c1 = comps[0], comps[1]
                t0 = match_team(c0.get('team', {}).get('displayName'), espn_teams)
                t1 = match_team(c1.get('team', {}).get('displayName'), espn_teams)
                if not t0 or not t1:
                    continue

                try:
                    sc0 = int(c0.get('score', 0))
                    sc1 = int(c1.get('score', 0))
                except (ValueError, TypeError):
                    continue

                sot0 = extract_sot(c0)
                sot1 = extract_sot(c1)
                date_str = ev.get('date', '')[:10]
                is_c0_home = (c0.get('homeAway') == 'home')

                # t0 için maç kaydı
                res0 = 'W' if sc0 > sc1 else ('D' if sc0 == sc1 else 'L')
                t0['matches'].append({
                    "opponent": t1['name'],
                    "score": f"{sc0} - {sc1}",
                    "result": res0,
                    "venue": "home" if is_c0_home else "away",
                    "goals_for": sc0,
                    "goals_against": sc1,
                    "sot_for": sot0,
                    "sot_against": sot1,
                    "date": date_str
                })

                # t1 için maç kaydı
                res1 = 'W' if sc1 > sc0 else ('D' if sc1 == sc0 else 'L')
                t1['matches'].append({
                    "opponent": t0['name'],
                    "score": f"{sc1} - {sc0}",
                    "result": res1,
                    "venue": "away" if is_c0_home else "home",
                    "goals_for": sc1,
                    "goals_against": sc0,
                    "sot_for": sot1,
                    "sot_against": sot0,
                    "date": date_str
                })
    except Exception as e:
        print(f"  [Uyarı] Scoreboard maçları alınamadı: {e}")

    # 3. Her Takımın İstenen 8 ESPN Metriğini Hesapla
    for t_name, t in espn_teams.items():
        t['matches'].sort(key=lambda m: m.get('date', ''))
        h_m = [m for m in t['matches'] if m['venue'] == 'home']
        a_m = [m for m in t['matches'] if m['venue'] == 'away']

        # home_avg_scored & home_avg_conceded
        t['home_avg_scored'] = round(sum(m['goals_for'] for m in h_m) / len(h_m), 2) if h_m else t['avg_scored']
        t['home_avg_conceded'] = round(sum(m['goals_against'] for m in h_m) / len(h_m), 2) if h_m else t['avg_conceded']

        # away_avg_scored & away_avg_conceded
        t['away_avg_scored'] = round(sum(m['goals_for'] for m in a_m) / len(a_m), 2) if a_m else t['avg_scored']
        t['away_avg_conceded'] = round(sum(m['goals_against'] for m in a_m) / len(a_m), 2) if a_m else t['avg_conceded']

        # shots_on_target_for & shots_on_target_against
        sot_matches = [m for m in t['matches'] if m.get('sot_for') is not None and m.get('sot_against') is not None]
        t['shots_on_target_for'] = round(sum(m['sot_for'] for m in sot_matches) / len(sot_matches), 2) if sot_matches else None
        t['shots_on_target_against'] = round(sum(m['sot_against'] for m in sot_matches) / len(sot_matches), 2) if sot_matches else None
        t['shots_on_target_sample'] = len(sot_matches)

        # Son 5 maç formu & Son 5 maç gol ortalaması
        recent = t['matches'][-5:]
        t['form'] = [m['result'] for m in recent]
        t['recent_goals_avg'] = round(sum(m['goals_for'] + m['goals_against'] for m in recent) / len(recent), 2) if recent else round(t['home_avg_scored'] + t['home_avg_conceded'], 2)
        t['recent_matches'] = recent

    print(f"  -> {len(espn_teams)} takım için iç/dış saha gol, isabetli şut ve son 5 maç metrikleri hesaplandı.")

    # 4. Kambi'den Gelecek Maçları ve 1X2 Oranlarını Çek
    upcoming_matches = []
    kambi_events = []
    kambi_ok = False
    try:
        r_kambi = HTTP.get(cfg["kambi_url"] + "&limit=300", timeout=25)
        if r_kambi.status_code == 200:
            r_kambi.encoding = "utf-8"
            kambi_events = r_kambi.json().get("events", [])
            kambi_ok = True
    except Exception as e:
        print(f"  [Hata] Kambi verisi alınamadı: {e}")

    if not kambi_ok:
        try:
            with open(cfg["output_file"], "r", encoding="utf-8") as f:
                upcoming_matches = json.load(f).get("upcoming_matches", [])
            print(f"  -> Kambi başarısız; önceki {len(upcoming_matches)} maç korunuyor.")
        except (OSError, ValueError):
            pass

    valid_events = []
    today = datetime.now(TR_ZONE).date()
    window_end = today + timedelta(days=14)
    for ev_data in kambi_events:
        event = ev_data.get("event", {})
        home_raw = event.get("homeName", "")
        away_raw = event.get("awayName", "")

        # Sadece bugünden itibaren 14 günlük gelecek maç penceresi.
        start_raw = event.get("start", "")
        try:
            event_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            event_date = event_dt.astimezone(TR_ZONE).date()
        except (ValueError, TypeError, AttributeError):
            continue
        if event_date < today or event_date > window_end:
            continue

        home_t = match_team(home_raw, espn_teams)
        away_t = match_team(away_raw, espn_teams)

        if home_t and away_t:
            valid_events.append((ev_data, home_t, away_t))

    print(f"  -> {len(valid_events)} geçerli lig maçı filtrelendi.")

    # 5. Saf Veri Olarak Maçları ve Kambi Oran Geçmişini İşle
    for item in valid_events:
        ev_data, home_t, away_t = item
        event = ev_data.get("event", {})

        start_iso = event.get("start", "")
        if start_iso:
            try:
                parsed = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                tr_time = parsed.astimezone(TR_ZONE)
                match_time = tr_time.strftime("%H:%M")
                match_date = tr_time.strftime("%d.%m.%Y")
            except Exception:
                match_time, match_date = "Belirsiz", "Belirsiz"
        else:
            match_time, match_date = "Belirsiz", "Belirsiz"

        # 1X2 Güncel Oranları
        ms1, ms0, ms2 = None, None, None
        for bet in ev_data.get("betOffers", []):
            bet_type = bet.get("betOfferType", {}).get("name", "")
            crit = (bet.get("criterion", {}).get("name", "") + " " + bet.get("criterion", {}).get("label", "")).lower()
            if bet_type == "Match" or "full time" in crit or "maç" in crit or "1x2" in crit:
                for oc in bet.get("outcomes", []):
                    lbl = str(oc.get("label", ""))
                    typ = oc.get("type", "")
                    raw_odds = oc.get("odds")
                    if raw_odds is None:
                        continue
                    val = float(raw_odds) / 1000.0
                    if lbl == "1" or typ == "OT_ONE":
                        ms1 = round(val, 2)
                    elif lbl.upper() == "X" or typ == "OT_CROSS":
                        ms0 = round(val, 2)
                    elif lbl == "2" or typ == "OT_TWO":
                        ms2 = round(val, 2)
                if ms1 is not None and ms0 is not None and ms2 is not None:
                    break

        current_odds = {"ms1": ms1, "x": ms0, "ms2": ms2}
        odds_available = all(v is not None for v in current_odds.values())
        odds_summary = (
            f"MS1: {ms1:.2f} | X: {ms0:.2f} | MS2: {ms2:.2f}"
            if odds_available else "Oran yok"
        )

        # Açılış oranları ve zaman damgalı oran geçmişi eşleştirmesi
        match_lookup_key = f"{normalize_name(home_t['name'])}_vs_{normalize_name(away_t['name'])}"
        prev_match = existing_matches_map.get(match_lookup_key, {})

        opening_odds = prev_match.get("opening_odds") or (
            current_odds if odds_available else {"ms1": None, "x": None, "ms2": None}
        )
        odds_history = list(prev_match.get("odds_history") or [])

        # Geçmiş boşsa ilk kayıt, oran değiştiyse yeni zaman damgalı kayıt ekle
        current_history_entry = {
            "timestamp": now_iso,
            "ms1": ms1,
            "x": ms0,
            "ms2": ms2
        }
        if not odds_available:
            odds_history = odds_history
        elif not odds_history:
            odds_history.append(current_history_entry)
        else:
            last_entry = odds_history[-1]
            if (last_entry.get("ms1") != ms1 or last_entry.get("x") != ms0 or last_entry.get("ms2") != ms2):
                odds_history.append(current_history_entry)

        # Oran değişim yüzdesi: ((current - opening) / opening) * 100
        op_ms1 = opening_odds.get("ms1")
        op_x = opening_odds.get("x")
        op_ms2 = opening_odds.get("ms2")
        odds_change_pct = {
            "ms1": round(((ms1 - op_ms1) / op_ms1) * 100, 2) if ms1 is not None and op_ms1 else None,
            "x": round(((ms0 - op_x) / op_x) * 100, 2) if ms0 is not None and op_x else None,
            "ms2": round(((ms2 - op_ms2) / op_ms2) * 100, 2) if ms2 is not None and op_ms2 else None,
        }

        # SADECE SAF VERİ (İSTATİSTİK VE ORAN BİLGİSİ - TAHMİN KESİNLİKLE YOK)
        match_obj = {
            "league": cfg["name"],
            "event_id": event.get("id") or event.get("eventId"),
            "home": home_t["name"],
            "away": away_t["name"],
            "date": match_date,
            "time": match_time,
            "odds": odds_summary,
            "odds_detail": current_odds,
            "odds_available": odds_available,
            "opening_odds": opening_odds,
            "current_odds": current_odds,
            "odds_change_pct": odds_change_pct,
            "odds_history": odds_history,
            "home_stats": {
                "name": home_t["name"],
                "home_avg_scored": home_t["home_avg_scored"],
                "home_avg_conceded": home_t["home_avg_conceded"],
                "shots_on_target_for": home_t["shots_on_target_for"],
                "shots_on_target_against": home_t["shots_on_target_against"],
                "form": home_t["form"],
                "recent_goals_avg": home_t["recent_goals_avg"],
                "played": home_t["played"],
                "rank": home_t.get("rank", 0),
                "points": home_t.get("points", 0),
                "recent_matches": home_t["recent_matches"]
            },
            "away_stats": {
                "name": away_t["name"],
                "away_avg_scored": away_t["away_avg_scored"],
                "away_avg_conceded": away_t["away_avg_conceded"],
                "shots_on_target_for": away_t["shots_on_target_for"],
                "shots_on_target_against": away_t["shots_on_target_against"],
                "form": away_t["form"],
                "recent_goals_avg": away_t["recent_goals_avg"],
                "played": away_t["played"],
                "rank": away_t.get("rank", 0),
                "points": away_t.get("points", 0),
                "recent_matches": away_t["recent_matches"]
            }
        }

        upcoming_matches.append(match_obj)

    # Maçları tarihe göre sırala
    upcoming_matches.sort(key=lambda m: (m.get("date", "").split(".")[::-1], m.get("time", "")))

    # 6. Lig JSON Dosyasını Kaydet
    league_payload = {
        "league": cfg["name"],
        "season": f"{season_window()[0].year}-{season_window()[1].year}",
        "upcoming_window_days": 14,
        "last_updated": now_iso,
        "total_teams": len(teams_list),
        "teams": teams_list,
        "upcoming_matches": upcoming_matches
    }

    # Dosyayı doğrudan ezmek yerine aynı klasöre geçici yazıp atomik değiştir.
    output_dir = os.path.dirname(os.path.abspath(cfg["output_file"])) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".league_", suffix=".json", dir=output_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(league_payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, cfg["output_file"])
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    print(f"  [BAŞARILI] {cfg['output_file']} kaydedildi ({len(teams_list)} takım, {len(upcoming_matches)} maç).")
    return upcoming_matches


def main():
    print("=== Çoklu Lig Spor Saf Veri & İstatistik Toplayıcı ===")

    # Mevcut lig dosyalarından açılış oranlarını ve geçmişini yükle
    existing_matches_map = load_existing_matches_map()
    print(f"[Hafıza] Daha önce kaydedilmiş {len(existing_matches_map)} maçın oran geçmişi yüklendi.")

    total_matches = 0
    for key, cfg in LEAGUES_CONFIG.items():
        try:
            matches = process_league(key, cfg, existing_matches_map)
            total_matches += len(matches)
        except Exception as exc:
            # Bir ligin API'si çökerse diğer ligleri güncelle; bozuk/boş JSON yazma.
            print(f"  [KRİTİK HATA] {cfg['name']} güncellenemedi: {exc}")

    print(f"\n[TAMAMLANDI] 4 lig dosyası başarıyla güncellendi! (Toplam {total_matches} maç)")


if __name__ == "__main__":
    main()
