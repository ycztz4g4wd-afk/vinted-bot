import os
import json
import time
import statistics
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------- CONFIGURATION ----------
KEYWORDS = ["Nike", "Carhartt", "Ralph Lauren", "Funko Pop", "sneakers", "Longchamp"]
PRICE_MIN = 0
PRICE_MAX = 30
SEEN_FILE = "seen_items.json"

MAX_PRICE_RATIO = 0.6
MIN_PROFIT_EUR = 5
MIN_COMPARABLES = 4

# Frais réels à l'achat sur Vinted, pour un calcul de marge plus fiable
# Estimation moyenne (varie en réalité selon le pays du vendeur, affiché dans l'email pour ajuster)
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
        "per_page": 30,
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
        return None, 0

    prices = [
        float(c["price"]["amount"])
        for c in comparables
        if c.get("id") != item.get("id") and c.get("price", {}).get("amount")
    ]
    if len(prices) < MIN_COMPARABLES:
        return None, len(prices)

    return statistics.median(prices), len(prices)


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
    subject = f"{len(deals)} bonne(s) affaire(s) Vinted" if deals else f"{len(others)} nouvelle(s) annonce(s) Vinted"
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
        html += "<h2>Bonnes affaires potentielles</h2>"
        for item, market_price, comparables_count, total_cost, net_profit in deals:
            badge = (
                f"<div style='color:green;font-weight:bold;'>"
                f"Prix median du marche estime : {round(market_price,2)} EUR (sur {comparables_count} annonces)<br>"
                f"Cout total estime a l'achat (article + port + protection acheteur) : {total_cost} EUR<br>"
                f"Marge nette estimee : ~{net_profit} EUR"
                f"</div>"
            )
            html += render_item(item, badge)

    if others:
        html += "<h2>Autres nouvelles annonces</h2>"
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
        market_price, comparables_count = estimate_market_price(session, item)
        price = float(item["price"]["amount"])

        if market_price is not None:
            protection_fee = estimate_buyer_protection(price)
            total_cost = round(price + SHIPPING_COST_ESTIMATE + protection_fee, 2)
            net_profit = round(market_price - total_cost, 2)

            is_deal = (
                price <= market_price * MAX_PRICE_RATIO
                and net_profit >= MIN_PROFIT_EUR
            )
            if is_deal:
                deals.append((item, market_price, comparables_count, total_cost, net_profit))
            else:
                others.append(item)
        else:
            others.append(item)

        time.sleep(1)

    if deals or others:
        print(f"{len(deals)} bonne(s) affaire(s), {len(others)} autre(s) annonce(s).")
        send_email(deals, others)
    else:
        print("Aucune nouvelle annonce.")

    save_seen(seen)


if __name__ == "__main__":
    main()
