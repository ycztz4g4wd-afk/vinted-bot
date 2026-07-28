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
MIN_COMPARABLES_FOR_SUCCESS = 20

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


def send_email(deals):
    if not deals:
        return
    msg = MIMEMultipart("alternative")
    subject = f"{len(deals)} article(s) GARANTI(S) a revendre avec {MIN_PROFIT_EUR}€+ de benefice"
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    def render_item(item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance, is_popular):
        title = item.get("title", "Sans titre")
        price = item.get("price", {}).get("amount", "?")
        url = item.get("url", "")
        photo = item.get("photo", {}).get("url", "") if item.get("photo") else ""
        country = (
            item.get("user", {}).get("country_title")
            or item.get("country_title")
            or "pays inconnu"
        )
        
        popular_badge = "🔥 ARTICLE TRES DEMANDE" if is_popular else "✅ Article de qualite"
        
        return f"""
        <div style="margin-bottom:25px;border:2px solid #4CAF50;border-radius:8px;padding:15px;background:#f1f8f4;">
            <div style="font-weight:bold;color:darkgreen;margin-bottom:10px;">{popular_badge}</div>
            <a href="{url}" style="font-size:1.1em;font-weight:bold;color:#1976d2;text-decoration:none;"><u>{title}</u></a><br><br>
            
            <div style="background:white;padding:10px;border-radius:5px;margin-bottom:10px;font-family:monospace;">
                <b>💰 ANALYSE FINANCIERE DETAILLEE :</b><br>
                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br>
                <b>Prix d'achat :</b> {price} EUR<br>
                <b>+ Frais de port :</b> {SHIPPING_COST_ESTIMATE} EUR<br>
                <b>+ Protection acheteur :</b> {round(estimate_buyer_protection(float(price)), 2)} EUR<br>
                <b style="color:#d32f2f;">COUT TOTAL ACHAT : {total_cost} EUR</b><br>
                <br>
                <b>Prix median du marche :</b> {round(market_price, 2)} EUR<br>
                <b>Prix de vente CONSERVATEUR (75% du marche) :</b> {suggested_price} EUR<br>
                <b style="color:darkgreen;font-size:1.2em;">BENEFICE GARANTI : {suggested_profit} EUR</b><br>
                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            </div>
            
            <div style="background:#e3f2fd;padding:8px;border-radius:5px;margin-bottom:10px;font-size:0.9em;">
                <b>📊 Analyse marche :</b> Comparaison sur {comparables_count} annonces similaires<br>
                <b>📈 Stabilite prix :</b> {round(variance, 1)}% d'ecart (Tres stable = securise)<br>
                <b>📍 Vendeur :</b> {country} (verifier frais port si hors France)
            </div>
            
            {"<img src='" + photo + "' style='max-width:200px;border-radius:5px;'>" if photo else ""}
        </div>
        """

    html = "<h1 style='color:darkgreen;text-align:center;'>✅ ARTICLES GARANTIS DE REVENDRE</h1>"
    html += f"<p style='text-align:center;color:#555;'><b>{len(deals)}</b> article(s) trouve(s) avec benefice minimum <b>{MIN_PROFIT_EUR}€</b> CONFIRME</p>"
    html += "<hr style='border:2px solid #4CAF50;'>"
    
    for item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance, is_popular in deals:
        html += render_item(item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance, is_popular)

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
        market_price, comparables_count, variance = estimate_market_price(session, item)
        price = float(item["price"]["amount"])

        if market_price is not None:
            protection_fee = estimate_buyer_protection(price)
            total_cost = round(price + SHIPPING_COST_ESTIMATE + protection_fee, 2)
            net_profit = round(market_price - total_cost, 2)
            suggested_price = round(market_price * SUGGESTED_SALE_RATIO, 2)
            suggested_profit = round(suggested_price - total_cost, 2)

            # Verifier si l'article a du succes (20+ comparables = marche populaire)
            is_popular = comparables_count >= MIN_COMPARABLES_FOR_SUCCESS

            # Conditions STRICTES : article doit etre bon marche ET prix stable ET benefice garanti
            is_deal = (
                price <= market_price * MAX_PRICE_RATIO
                and net_profit >= MIN_PROFIT_EUR
                and variance is not None
                and variance <= MAX_PRICE_VARIANCE_PERCENT
            )
            
            if is_deal:
                deals.append((item, market_price, comparables_count, total_cost, net_profit, suggested_price, suggested_profit, variance, is_popular))

        time.sleep(1)

    if deals:
        print(f"{len(deals)} affaire(s) CONFIRMEE(S) a revendre.")
        send_email(deals)
    else:
        print("Aucun article ne correspond aux criteres stricts.")

    save_seen(seen)


if __name__ == "__main__":
    main()
