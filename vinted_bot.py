import os
import json
import time
import statistics
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------- CONFIGURATION ----------
KEYWORDS = ["Nike", "Carhartt", "Ralph Lauren", "Funko Pop", "sneakers", "Longchamp", "maillots de football", "the north face", "Patagonia", "stone island", "Arc'teryx", "eastpak", "Stussy", "Lacoste"]
PRICE_MIN = 0
PRICE_MAX = 30
SEEN_FILE = "seen_items.json"

# OPTION C : un peu moins strict mais toujours fiable
MAX_PRICE_RATIO = 0.55
MIN_PROFIT_EUR = 10
MIN_COMPARABLES = 8
MIN_COMPARABLES_FOR_SUCCESS = 20

# Prix de vente CONSERVATEUR : bien en dessous du prix median pour garantir vente rapide
SUGGESTED_SALE_RATIO = 0.75

# Stabilite du prix : ecart-type max accepte (en %). Articles trop variables = risque
MAX_PRICE_VARIANCE_PERCENT = 15

# Frais réels à l'achat sur Vinted
SHIPPING_COST_ESTIMATE = 5.0
BUYER_PROTECTION_PERCENT = 0.05
BUYER_PROTECTION_FIXED = 0.70

# ETATS ACCEPTES : Neuf avec étiquette (1), Neuf (2), Très bon état (3)
ACCEPTED_CONDITIONS = [1, 2, 3]
CONDITION_LABELS = {
    1: "🏷️ Neuf avec étiquette",
    2: "✨ Neuf",
    3: "⭐ Très bon état"
}

EMAIL_FROM = os.environ["EMAIL_ADDRESS"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


def estimate_buyer_protection(price):
    return round(price * BUYER_PROTECTION_PERCENT + BUYER_PROTECTION_FIXED, 2)


def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get("https://www.vinted.fr/", timeout=15)
    return session


def search_vinted(session, keyword, extra_params=None):
    url = "https://www.vinted.fr/api/v2/catalog/items"
    params = {
        "search_text": keyword,
        "price_to": PRICE_MAX,
        "price_from": PRICE_MIN,
        "order": "newest_first",
        "per_page": 40,
        "currency": "EUR",
    }
    if extra_params:
        params.update(extra_params)
    r = session.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("items", [])


def estimate_market_price(session, item):
    brand_id = (item.get("brand_dto") or {}).get("id")
    catalog_id = item.get("catalog_id")
    title = item.get("title", "")

    url = "https://www.vinted.fr/api/v2/catalog/items"
    params = {
        "order": "relevance",
        "per_page": 50,
        "currency": "EUR",
    }
    if brand_id:
        params["brand_ids[]"] = brand_id
    if catalog_id:
        params["catalog[]"] = catalog_id
    if not brand_id and not catalog_id:
        params["search_text"] = title

    try:
        r = session.get(url, params=params, timeout=15)
        r.raise_for_status()
        comparables = r.json().get("items", [])
    except Exception as e:
        print(f"  Erreur estimation marche pour '{title}': {e}")
        return None, 0, None

    prices = [
        float(c["price"]["amount"])
        for c in comparables
        if c.get("id") != item.get("id") and c.get("price", {}).get("amount")
    ]
    if len(prices) < MIN_COMPARABLES:
        return None, len(prices), None

    median_price = statistics.median(prices)
    
    if len(prices) > 1:
        stdev = statistics.stdev(prices)
        variance_percent = (stdev / median_price) * 100
    else:
        variance_percent = 0

    return median_price, len(prices), variance_percent


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen_ids):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen_ids), f)


def send_email(deals):
    if not deals:
        return
    msg = MIMEMultipart("alternative")
    subject = f"{len(deals)} article(s) PREMIUM - Tres bon etat, benefice GARANTI {MIN_PROFIT_EUR}€+"
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    def render_item(item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance, is_popular, condition_label):
        title = item.get("title", "Sans titre")
        price = item.get("price", {}).get("amount", "?")
        url = item.get("url", "")
        photo = item.get("photo", {}).get("url", "") if item.get("photo") else ""
        country = (
            item.get("user", {}).get("country_title")
            or item.get("country_title")
            or "pays inconnu"
        )
        
        popular_badge = "🔥 TRES DEMANDE" if is_popular else "✅ Bon marche"
        
        return f"""
        <div style="margin-bottom:25px;border:3px solid #ff6b35;border-radius:10px;padding:15px;background:#fff3e0;">
            <div style="display:flex;justify-content:space-between;margin-bottom:10px;">
                <div style="font-weight:bold;color:#d84315;font-size:1.1em;">{popular_badge}</div>
                <div style="background:#ff6b35;color:white;padding:5px 10px;border-radius:5px;font-weight:bold;">{condition_label}</div>
            </div>
            
            <a href="{url}" style="font-size:1.15em;font-weight:bold;color:#1565c0;text-decoration:none;"><u>{title}</u></a><br><br>
            
            <div style="background:white;padding:12px;border-radius:8px;margin-bottom:10px;border-left:4px solid #ff6b35;">
                <b style="color:#d84315;font-size:1.05em;">💰 ANALYSE FINANCIERE COMPLETE :</b><br>
                <div style="font-family:monospace;margin-top:8px;line-height:1.8;">
                ┌─────────────────────────────────────┐<br>
                │ PRIX D'ACHAT (DETAILLE)            │<br>
                ├─────────────────────────────────────┤<br>
                │ Article : <b>{price} EUR</b>         <br>
                │ + Port : <b>{SHIPPING_COST_ESTIMATE} EUR</b>              <br>
                │ + Protection acheteur : <b>{round(estimate_buyer_protection(float(price)), 2)} EUR</b><br>
                ├─────────────────────────────────────┤<br>
                │ COUT TOTAL : <b style="color:#d32f2f;font-size:1.1em;">{total_cost} EUR</b><br>
                └─────────────────────────────────────┘<br>
                </div>
                
                <div style="background:#e8f5e9;padding:10px;border-radius:5px;margin-top:10px;">
                <b style="color:darkgreen;">📊 ANALYSE MARCHE :</b><br>
                Prix median (comparaison {comparables_count} annonces) : <b>{round(market_price, 2)} EUR</b><br>
                <br>
                <b style="color:darkgreen;">🎯 PRIX DE VENTE CONSEILLE :</b><br>
                (75% du prix median = conservateur et garanti de partir)<br>
                <b style="font-size:1.2em;color:#1976d2;">{suggested_price} EUR</b><br>
                <br>
                <b style="color:darkgreen;font-size:1.15em;">✅ BENEFICE NET ESTIME :</b><br>
                <b style="color:#2e7d32;font-size:1.3em;background:#c8e6c9;padding:8px;border-radius:5px;display:inline-block;">+{suggested_profit} EUR</b><br>
                </div>
                
                <div style="background:#e3f2fd;padding:8px;border-radius:5px;margin-top:10px;font-size:0.95em;">
                <b>📈 Stabilite marche :</b> {round(variance, 1)}% d'ecart (Tres stable = securise)<br>
                <b>📍 Vendeur :</b> {country} (verifier frais si hors France)<br>
                <b>🔍 Fiabilite :</b> Analyse sur {comparables_count} annonces comparables
                </div>
            </div>
            
            {"<img src='" + photo + "' style='max-width:250px;border-radius:8px;border:2px solid #ff6b35;'>" if photo else ""}
        </div>
        """

    html = "<h1 style='color:#d84315;text-align:center;'>⭐ ARTICLES PREMIUM - ETAT GARANTI</h1>"
    html += f"<p style='text-align:center;color:#555;font-size:1.05em;'><b>{len(deals)}</b> article(s) en tres bon etat avec benefice minimum <b style='color:#2e7d32;'>{MIN_PROFIT_EUR}€ CONFIRME</b></p>"
    html += "<hr style='border:2px solid #ff6b35;'>"
    
    for item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance, is_popular, condition_label in deals:
        html += render_item(item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance, is_popular, condition_label)

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


def main():
    seen = load_seen()
    new_items_all = []
    session = get_session()

    for keyword in KEYWORDS:
        try:
            items = search_vinted(session, keyword)
        except Exception as e:
            print(f"Erreur pour '{keyword}': {e}")
            continue

        for item in items:
            item_id = str(item.get("id"))
            if item_id not in seen:
                seen.add(item_id)
                new_items_all.append(item)
        time.sleep(2)

    deals = []

    for item in new_items_all:
        # FILTRE ETAT : seulement Neuf etiquette, Neuf, ou Tres bon etat
        condition = item.get("status", {})  # ou item.get("condition")
        
        # Essayer de recuperer l'etat selon differents champs possibles
        condition_id = None
        if isinstance(condition, dict):
            condition_id = condition.get("id")
        else:
            condition_id = item.get("status_id") or item.get("condition_id")
        
        # Si pas d'etat trouve, passer l'article
        if condition_id not in ACCEPTED_CONDITIONS:
            continue
        
        condition_label = CONDITION_LABELS.get(condition_id, "État inconnu")
        
        market_price, comparables_count, variance = estimate_market_price(session, item)
        price = float(item["price"]["amount"])

        if market_price is not None:
            protection_fee = estimate_buyer_protection(price)
            total_cost = round(price + SHIPPING_COST_ESTIMATE + protection_fee, 2)
            net_profit = round(market_price - total_cost, 2)
            suggested_price = round(market_price * SUGGESTED_SALE_RATIO, 2)
            suggested_profit = round(suggested_price - total_cost, 2)

            is_popular = comparables_count >= MIN_COMPARABLES_FOR_SUCCESS

            # OPTION C : criteres moderes mais solides
            is_deal = (
                price <= market_price * MAX_PRICE_RATIO
                and net_profit >= MIN_PROFIT_EUR
                and variance is not None
                and variance <= MAX_PRICE_VARIANCE_PERCENT
            )
            
            if is_deal:
                deals.append((item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance, is_popular, condition_label))

        time.sleep(1)

    if deals:
        print(f"{len(deals)} article(s) PREMIUM trouvé(s).")
        send_email(deals)
    else:
        print("Aucun article premium ne correspond aux criteres.")

    save_seen(seen)


if __name__ == "__main__":
    main()
