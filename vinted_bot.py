import os, json, time, random, statistics, smtplib, requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===== PAYS A SCANNER =====
# Ajoute ou retire des domaines ici pour couvrir plus ou moins de pays.
# Un seul script gere tous les pays de la liste.
DOMAINS = [
    "vinted.fr",
    "vinted.de",
    "vinted.es",
    "vinted.it",
    "vinted.co.uk",
    "vinted.be",
    "vinted.pl",
    "vinted.nl",
    "vinted.pt",
]

KEYWORDS = [
    # Nike / Jordan - mots-clés resserrés pour éviter le bruit (bébé, PSG, etc.)
    "Nike Air Force 1",
    "Air Jordan sneakers",
    "Nike Nocta survet",
    "Nike Tech Fleece survet",
    "Nike Dunk Low",
    # Streetwear / logo brands
    "Carhartt jacket",
    "Ralph Lauren polo",
    "The North Face jacket",
    "Patagonia fleece",
    "Stone Island jacket",
    "Stone Island survet",
    "Arc'teryx jacket",
    "Eastpak backpack",
    "Stussy hoodie",
    "Lacoste polo",
    "Supreme hoodie",
    "Champion sweatshirt vintage",
    "Adidas Originals veste",
    "New Balance 2002R",
    "New Balance 550",
    "Tommy Hilfiger vintage",
    "Levi's veste vintage",
    "Fred Perry polo",
    "Dickies jacket",
    "Moncler doudoune",
    "Burberry vintage",
    "Yeezy sneakers",
    # Collectibles
    "Funko Pop"
]

PRICE_MIN, PRICE_MAX, SEEN_FILE = 0, 40, "seen_items.json"
MAX_PRICE_RATIO, MIN_PROFIT_EUR, MIN_COMPARABLES = 0.55, 8, 8
MIN_COMPARABLES_FOR_SUCCESS, SUGGESTED_SALE_RATIO, MAX_PRICE_VARIANCE_PERCENT = 20, 0.75, 50
SHIPPING_COST_ESTIMATE, BUYER_PROTECTION_PERCENT, BUYER_PROTECTION_FIXED = 5.0, 0.05, 0.70
CONDITION_LABELS = {1: "Neuf avec étiquette", 2: "Neuf", 3: "Très bon état"}

# Tailles homme acceptées : S, M, L, XL, XXL (lettres uniquement).
# Les tailles chaussures (numériques, ex: "42") ne matchent pas ce filtre.
ACCEPTED_SIZES = {"S", "M", "L", "XL", "XXL", "2XL"}

import re

def size_is_accepted(size_title):
    if not size_title:
        return False
    # Extrait les tokens alphabétiques du texte de taille Vinted
    # (ex: "M (38)" -> "M", "S/36" -> "S", "XL" -> "XL")
    tokens = re.findall(r"[A-Za-z]+", size_title.upper())
    return any(t in ACCEPTED_SIZES for t in tokens)

EMAIL_FROM = os.environ["EMAIL_ADDRESS"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]
PROXY_URL = os.environ.get("PROXY_URL")  # optionnel, proxy résidentiel

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# ===== PAUSES ALEATOIRES =====
# Remplace les délais fixes par des délais aléatoires pour ne pas avoir
# un rythme parfaitement régulier (signal de bot).
def pause_courte():
    time.sleep(random.uniform(2, 4))

def pause_longue():
    time.sleep(random.uniform(3, 7))


def get_session(domain):
    s = requests.Session()
    s.headers.update(HEADERS)
    if PROXY_URL:
        s.proxies.update({"http": PROXY_URL, "https": PROXY_URL})
    try:
        s.get(f"https://www.{domain}/", timeout=15)
    except Exception as e:
        print(f"[{domain}] Erreur de session initiale: {e}")
    return s


def search_vinted(s, domain, kw):
    try:
        r = s.get(
            f"https://www.{domain}/api/v2/catalog/items",
            params={
                "search_text": kw,
                "price_to": PRICE_MAX,
                "price_from": PRICE_MIN,
                "order": "newest_first",
                "per_page": 10,  # réduit de 40 à 10 pour limiter le volume de requêtes
                "currency": "EUR",
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[{domain}] {kw}: status {r.status_code}")
            return []
        return r.json().get("items", [])
    except Exception as e:
        print(f"[{domain}] Erreur recherche '{kw}': {e}")
        return []


def estimate_price(s, domain, item):
    bid = (item.get("brand_dto") or {}).get("id")
    cid = item.get("catalog_id")
    params = {
        "order": "relevance",
        "per_page": 50,
        "currency": "EUR",
        "search_text": item.get("title", ""),
    }
    # On n'ajoute le filtre que s'il existe vraiment : une chaîne vide
    # envoyée à l'API Vinted est interprétée comme "aucune marque" et
    # renvoie 0 résultat au lieu d'ignorer le filtre.
    if bid:
        params["brand_ids[]"] = bid
    if cid:
        params["catalog[]"] = cid
    try:
        r = s.get(
            f"https://www.{domain}/api/v2/catalog/items",
            params=params,
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[{domain}] Estimation: status {r.status_code} pour '{item.get('title','')[:30]}'")
            return None, 0, None
        p = r.json().get("items", [])
        prices = [
            float(x["price"]["amount"])
            for x in p
            if x.get("id") != item.get("id") and x.get("price", {}).get("amount")
        ]
        if len(prices) < MIN_COMPARABLES:
            return None, len(prices), None
        med = statistics.median(prices)
        var = (statistics.stdev(prices) / med * 100) if len(prices) > 1 else 0
        return med, len(prices), var
    except Exception as e:
        print(f"[{domain}] Erreur estimation prix: {e}")
        return None, 0, None


def load_seen():
    try:
        data = json.load(open(SEEN_FILE))
        if not isinstance(data, dict):
            # ancien format (liste simple) -> on repart sur un dict propre
            print("Ancien format de seen_items.json détecté, réinitialisation.")
            return {}
        return data
    except Exception:
        return {}


def save_seen(seen):
    json.dump(seen, open(SEEN_FILE, "w"))


def send_email(deals):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = str(len(deals)) + " articles"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    html = "<h1>ARTICLES</h1>"
    for d in deals:
        item, mp, cc, tc, np, sp, spr, v, pop, cl, domain = d
        # priorité: url complet fourni par Vinted, sinon path + domaine,
        # sinon on reconstruit à partir de l'ID (toujours présent et toujours valide)
        item_id = item.get("id")
        link = item.get("url") or (f"https://www.{domain}{item.get('path')}" if item.get("path") else "") or (f"https://www.{domain}/items/{item_id}" if item_id else "")
        html += "<div style='border:1px solid #999;padding:10px;margin:10px 0'>"
        html += f"<b>[{domain}] " + item.get("title", "") + "</b><br>"
        html += "Prix: " + str(item.get("price", {}).get("amount", "")) + " | Coûts: " + str(tc) + " | Bénéfice: " + str(spr) + "<br>"
        html += "Prix médian marché: " + str(mp) + " | Comparables: " + str(cc) + "<br>"
        html += cl + "<br>"
        if link:
            html += f'<a href="{link}">Voir l\'annonce sur Vinted</a>'
        html += "</div>"
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(EMAIL_FROM, EMAIL_PASSWORD)
        srv.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


def scan_domain(domain, seen):
    s = get_session(domain)
    seen_domain = set(seen.get(domain, []))
    items = []

    for kw in KEYWORDS:
        for itm in search_vinted(s, domain, kw):
            iid = str(itm.get("id"))
            if iid not in seen_domain:
                seen_domain.add(iid)
                items.append(itm)
        pause_longue()

    seen[domain] = list(seen_domain)

    deals = []
    print(f"[{domain}] {len(items)} nouveaux articles à analyser.")
    if items:
        # Affiche les champs bruts du premier article pour identifier le bon nom de champ
        print(f"[{domain}] Exemple de champs disponibles: {list(items[0].keys())}")
        print(f"[{domain}] Exemple status/condition: status_id={items[0].get('status_id')}, condition_id={items[0].get('condition_id')}, status={items[0].get('status')}, condition={items[0].get('condition')}")

    for itm in items:
        title = itm.get("title", "")[:40]
        cond = itm.get("status_id") or itm.get("condition_id")
        # On ne rejette plus si le champ est absent (None) - on filtre seulement
        # si Vinted a bien renvoyé une valeur ET qu'elle n'est pas dans la liste acceptée.
        if cond is not None and cond not in [1, 2, 3]:
            print(f"[{domain}] REJET '{title}': état non accepté ({cond})")
            continue
        mp, cc, var = estimate_price(s, domain, itm)
        price = float(itm["price"]["amount"])
        if not mp:
            print(f"[{domain}] REJET '{title}': pas assez de comparables ({cc} trouvés, {MIN_COMPARABLES} requis)")
            pause_courte()
            continue
        pf = round(price * BUYER_PROTECTION_PERCENT + BUYER_PROTECTION_FIXED, 2)
        tc = round(price + SHIPPING_COST_ESTIMATE + pf, 2)
        np = round(mp - tc, 2)
        sp = round(mp * SUGGESTED_SALE_RATIO, 2)
        spr = round(sp - tc, 2)

        raisons = []
        if price > mp * MAX_PRICE_RATIO:
            raisons.append(f"prix {price}€ > {round(mp * MAX_PRICE_RATIO, 2)}€ (ratio max)")
        if np < MIN_PROFIT_EUR:
            raisons.append(f"marge {np}€ < {MIN_PROFIT_EUR}€ requis")
        if not var or var > MAX_PRICE_VARIANCE_PERCENT:
            raisons.append(f"variance {var} > {MAX_PRICE_VARIANCE_PERCENT}% (prix marché instable)")

        if raisons:
            print(f"[{domain}] REJET '{title}': " + " | ".join(raisons))
        else:
            print(f"[{domain}] DEAL '{title}': prix {price}€, médian {mp}€, marge {np}€ | url={itm.get('url')!r} path={itm.get('path')!r} id={itm.get('id')}")
            deals.append((
                itm, mp, cc, tc, np, sp, spr, var,
                cc >= MIN_COMPARABLES_FOR_SUCCESS,
                CONDITION_LABELS.get(cond, ""),
                domain,
            ))
        pause_courte()

    return deals


def main():
    seen = load_seen()
    all_deals = []

    # on mélange l'ordre des pays a chaque run pour varier le pattern
    domains_order = DOMAINS[:]
    random.shuffle(domains_order)

    for domain in domains_order:
        print(f"--- Scan {domain} ---")
        deals = scan_domain(domain, seen)
        all_deals.extend(deals)
        pause_longue()

    if all_deals:
        send_email(all_deals)
        print(f"{len(all_deals)} bonnes affaires trouvées, email envoyé.")
    else:
        print("Aucune bonne affaire cette fois.")

    save_seen(seen)


if __name__ == "__main__":
    main()
