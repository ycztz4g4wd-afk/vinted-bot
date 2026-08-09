import os, json, time, statistics, smtplib, requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

KEYWORDS = ["Nike", "Carhartt", "Ralph Lauren", "Funko Pop", "sneakers", "Longchamp", "maillots de football", "the north face", "Patagonia", "stone island", "Arc'teryx", "eastpak", "Stussy", "Lacoste"]
PRICE_MIN, PRICE_MAX, SEEN_FILE = 0, 30, "seen_items.json"
MAX_PRICE_RATIO, MIN_PROFIT_EUR, MIN_COMPARABLES = 0.55, 10, 8
MIN_COMPARABLES_FOR_SUCCESS, SUGGESTED_SALE_RATIO, MAX_PRICE_VARIANCE_PERCENT = 20, 0.75, 15
SHIPPING_COST_ESTIMATE, BUYER_PROTECTION_PERCENT, BUYER_PROTECTION_FIXED = 5.0, 0.05, 0.70
CONDITION_LABELS = {1: "Neuf avec étiquette", 2: "Neuf", 3: "Très bon état"}
EMAIL_FROM = os.environ["EMAIL_ADDRESS"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

def get_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get("https://www.vinted.fr/", timeout=15)
    return s

def search_vinted(s, kw):
    r = s.get("https://www.vinted.fr/api/v2/catalog/items", params={"search_text": kw, "price_to": PRICE_MAX, "price_from": PRICE_MIN, "order": "newest_first", "per_page": 40, "currency": "EUR"}, timeout=15)
    return r.json().get("items", [])

def estimate_price(s, item):
    bid = (item.get("brand_dto") or {}).get("id")
    cid = item.get("catalog_id")
    try:
        p = s.get("https://www.vinted.fr/api/v2/catalog/items", params={"order": "relevance", "per_page": 50, "currency": "EUR", "brand_ids[]": bid if bid else "", "catalog[]": cid if cid else "", "search_text": item.get("title", "")}, timeout=15).json().get("items", [])
        prices = [float(x["price"]["amount"]) for x in p if x.get("id") != item.get("id") and x.get("price", {}).get("amount")]
        if len(prices) < MIN_COMPARABLES:
            return None, len(prices), None
        med = statistics.median(prices)
        var = (statistics.stdev(prices) / med * 100) if len(prices) > 1 else 0
        return med, len(prices), var
    except:
        return None, 0, None

def load_seen():
    try:
        return set(json.load(open(SEEN_FILE)))
    except:
        return set()

def save_seen(s):
    json.dump(list(s), open(SEEN_FILE, "w"))

def send_email(deals):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = str(len(deals)) + " articles"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    html = "<h1>ARTICLES</h1>"
    for d in deals:
        item, mp, cc, tc, np, sp, spr, v, pop, cl = d
        html += "<div style='border:1px solid #999;padding:10px;margin:10px 0'>"
        html += "<b>" + item.get("title", "") + "</b><br>"
        html += "Prix: " + str(item.get("price", {}).get("amount", "")) + " | Coûts: " + str(tc) + " | Bénéfice: " + str(spr) + "<br>"
        html += cl + "</div>"
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(EMAIL_FROM, EMAIL_PASSWORD)
        srv.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

def main():
    seen, items, s = load_seen(), [], get_session()
    for kw in KEYWORDS:
        try:
            for itm in search_vinted(s, kw):
                iid = str(itm.get("id"))
                if iid not in seen:
                    seen.add(iid)
                    items.append(itm)
        except:
            pass
        time.sleep(2)
    deals = []
    for itm in items:
        cond = itm.get("status_id") or itm.get("condition_id")
        if cond not in [1, 2, 3]:
            continue
        mp, cc, var = estimate_price(s, itm)
        price = float(itm["price"]["amount"])
        if mp:
            pf = round(price * BUYER_PROTECTION_PERCENT + BUYER_PROTECTION_FIXED, 2)
            tc = round(price + SHIPPING_COST_ESTIMATE + pf, 2)
            np = round(mp - tc, 2)
            sp = round(mp * SUGGESTED_SALE_RATIO, 2)
            spr = round(sp - tc, 2)
            if price <= mp * MAX_PRICE_RATIO and np >= MIN_PROFIT_EUR and var and var <= MAX_PRICE_VARIANCE_PERCENT:
                deals.append((itm, mp, cc, tc, np, sp, spr, var, cc >= MIN_COMPARABLES_FOR_SUCCESS, CONDITION_LABELS.get(cond, "")))
        time.sleep(1)
    if deals:
        send_email(deals)
    save_seen(seen)

if __name__ == "__main__":
    main()
