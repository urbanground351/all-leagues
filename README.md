# All Leagues - Football Data & Odds API

Bu repo; Süper Lig, Premier League, La Liga ve Bundesliga için resmi fikstür, puan durumu, takım formları ve güncel Kambi bahis oranlarını toplayarak JSON formatında sunar.

## Dosya Yapısı

- `super_lig.json`: Trendyol Süper Lig maç ve oran verileri
- `premier_league.json`: İngiltere Premier League maç ve oran verileri
- `la_liga.json`: İspanya La Liga maç ve oran verileri
- `bundesliga.json`: Almanya Bundesliga maç ve oran verileri
- `matches.json`: Tüm liglerin birleştirilmiş maç listesi
- `bot.py`: ESPN API ve Kambi servislerinden verileri çeken ana script
- `.github/workflows/update.yml`: GitHub Actions ile her 12 saatte bir verileri otomatik güncelleyen iş akışı

## Kurulum ve Çalıştırma

```bash
pip install -r requirements.txt
python bot.py
```
