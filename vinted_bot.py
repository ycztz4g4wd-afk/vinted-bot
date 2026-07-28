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

MAX_PRICE_RATIO = 0.5
MIN_PROFIT_EUR = 10
MIN_COMPARABLES = 10

# Prix de vente CONSERVATEUR : bien en dessous du prix median pour garantir vente rapide
SUGGESTED_SALE_RATIO = 0.75

# Stabilite du prix : ecart-type max accepte (en %). Articles trop variables = risque
MAX_PRICE_VARIANCE_PERCENT = 15

# Frais réels à l'achat sur Vinted
SHIPPING_COST_ESTIMATE = 5.0
BUYER_PROTECTION_PERCENT = 0.05
BUYER_PROTECTION_FIXED = 0.70

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
        "per_page": 20,
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
    
    # Calculer l'écart-type pour évaluer la stabilité des prix
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


def send_email(deals, others):
    if not deals and not others:
        return
    msg = MIMEMultipart("alternative")
    subject = f"{len(deals)} bonne(s) affaire(s) SURE Vinted" if deals else f"{len(others)} nouvelle(s) annonce(s) Vinted"
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    def render_item(item, badge=""):
        title = item.get("title", "Sans titre")
        price = item.get("price", {}).get("amount", "?")
        url = item.get("url", "")
        photo = item.get("photo", {}).get("url", "") if item.get("photo") else ""
        country = (
            item.get("user", {}).get("country_title")
            or item.get("country_title")
            or "pays inconnu"
        )
        return f"""
        <div style="margin-bottom:20px;border-bottom:1px solid #ddd;padding-bottom:10px;">
            {badge}
            <a href="{url}"><b>{title}</b></a><br>
            Prix affiche : {price} EUR<br>
            Vendeur : {country} (frais de port reels a verifier si hors France)<br>
            {"<img src='" + photo + "' width='150'>" if photo else ""}
        </div>
        """

    html = ""
    if deals:
        html += "<h2>✅ BONNES AFFAIRES CONFIRMEES (Analyse sure a 100%)</h2>"
        for item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance in deals:
            badge = (
                f"<div style='color:darkgreen;font-weight:bold;background:#e8f5e9;padding:10px;border-radius:5px;'>"
                f"✅ ANALYSE MARKET CONFIRMEE<br>"
                f"Prix median du marche (sur {comparables_count} annonces) : {round(market_price,2)} EUR<br>"
                f"Stabilite des prix : {round(variance,1)}% d'ecart-type (tres stable = securise)<br>"
                f"Cout total achat (article + port + protection) : {total_cost} EUR<br>"
                f"<b>Prix de vente conservateur : {suggested_price} EUR</b><br>"
                f"<b style='color:darkgreen;font-size:1.1em;'>Benefice GARANTI : ~{suggested_profit} EUR</b>"
                f"</div>"
            )
            html += render_item(item, badge)

    if others:
        html += "<h2>Autres annonces (analyse insuffisante ou risque)</h2>"
        for item in others:
            html += render_item(item)

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
    others = []

    for item in new_items_all:
        market_price, comparables_count, variance = estimate_market_price(session, item)
        price = float(item["price"]["amount"])

        if market_price is not None:
            protection_fee = estimate_buyer_protection(price)
            total_cost = round(price + SHIPPING_COST_ESTIMATE + protection_fee, 2)
            net_profit = round(market_price - total_cost, 2)
            suggested_price = round(market_price * SUGGESTED_SALE_RATIO, 2)
            suggested_profit = round(suggested_price - total_cost, 2)

            # Conditions STRICTES : article doit etre bon marche ET prix stable sur le marche
            is_deal = (
                price <= market_price * MAX_PRICE_RATIO
                and net_profit >= MIN_PROFIT_EUR
                and variance is not None
                and variance <= MAX_PRICE_VARIANCE_PERCENT
            )
            if is_deal:
                deals.append((item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance))
            else:
                others.append(item)
        else:
            others.append(item)

        time.sleep(1)

    if deals or others:
        print(f"{len(deals)} affaire(s) CONFIRMEE(S), {len(others)} autre(s) annonce(s).")
        send_email(deals, others)
    else:
        print("Aucune nouvelle annonce.")

    save_seen(seen)


if __name__ == "__main__":
    main()
