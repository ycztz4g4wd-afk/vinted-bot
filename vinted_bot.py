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
    # PISTE 3 : mots-clés affinés pour réduire l'hétérogénéité des comparables
    # (les anciens "Stussy hoodie" / "Fred Perry polo" / "Champion sweatshirt vintage" /
    # "Adidas Originals veste" mélangeaient des pièces trop différentes en prix -> forte variance)
    "Stussy hoodie vintage",
    "Lacoste polo",
    "Supreme hoodie",
    "Champion sweatshirt college vintage",
    "Adidas Originals veste trefoil",
    "New Balance 2002R",
    "New Balance 550",
    "Tommy Hilfiger vintage",
    "Levi's veste vintage",
    "Fred Perry polo vintage",
    "Dickies jacket",
    "Moncler doudoune",
    "Burberry vintage",
    "Yeezy sneakers",
    # Collectibles
    "Funko Pop",
]

# PISTE 10 : "lots" groupés. Ces annonces ne listent pas chaque pièce
# individuellement dans le titre -> l'algorithme de recherche Vinted les
# classe plus bas, donc moins de vues, moins de concurrence, prix bradés.
# Le prix d'un lot n'est PAS comparable à la médiane d'un article seul :
# ces items sont traités à part (pas de calcul de marge automatique),
# juste remontés pour vérification manuelle.
LOT_KEYWORDS = [
    "lot Nike",
    "lot Carhartt",
    "lot Ralph Lauren",
    "lot Adidas Originals",
    "lot streetwear vintage",
    "lot Nike Jordan",
    "lot Lacoste",
    "lot Tommy Hilfiger",
    "lot sneakers",
]

# PISTE 10 (suite) : fautes d'orthographe / variantes courantes des marques.
# Les acheteurs tapent l'orthographe correcte -> ces annonces mal orthographiées
# sont sous-indexées par la recherche des autres acheteurs, donc moins de
# concurrence sur les mêmes articles (déjà observé dans nos logs : "Ralf Lauren",
# "Arc'tery", "Nike Sir air force"...).
MISSPELLED_KEYWORDS = [
    "Ralf Lauren polo",
    "Arc'tery jacket",
    "Stussi hoodie",
    "Carhart jacket",
    "Fred Perri polo",
    "Addidas Originals",
    "Levis veste vintage",
]

KEYWORDS = KEYWORDS + LOT_KEYWORDS + MISSPELLED_KEYWORDS

PRICE_MIN, PRICE_MAX, SEEN_FILE = 0, 40, "seen_items.json"
MAX_PRICE_RATIO, MIN_PROFIT_EUR, MIN_COMPARABLES = 0.55, 8, 8
MIN_COMPARABLES_FOR_SUCCESS, SUGGESTED_SALE_RATIO, MAX_PRICE_VARIANCE_PERCENT = 20, 0.75, 50
SHIPPING_COST_ESTIMATE, BUYER_PROTECTION_PERCENT, BUYER_PROTECTION_FIXED = 5.0, 0.05, 0.70
CONDITION_LABELS = {1: "Neuf avec étiquette", 2: "Neuf", 3: "Très bon état"}

# PISTE 2 : seuil de comparables plus strict pour les mots-clés génériques,
# qui ramènent des panels de prix très hétérogènes (basique récent vs. pièce
# vintage rare vendue 3-5x plus cher sous le même intitulé de recherche).
GENERIC_KEYWORDS_MIN_COMPARABLES = {
    "Fred Perry polo vintage": 14,
    "Champion sweatshirt college vintage": 14,
    "Stussy hoodie vintage": 14,
    "Adidas Originals veste trefoil": 14,
    "Lacoste polo": 12,
    "Tommy Hilfiger vintage": 12,
    # marques hype (PISTE 6) : plus de points nécessaires pour que le
    # percentile bas soit fiable et pas juste tiré par 1-2 valeurs basses
    "Supreme hoodie": 14,
    "Stone Island jacket": 12,
    "Stone Island survet": 12,
    "Arc'teryx jacket": 12,
}

# Tailles homme acceptées : S, M, L, XL, XXL (lettres) pour les vêtements,
# et 41/42/43 (pointures EU) pour les chaussures.
ACCEPTED_SIZES = {"S", "M", "L", "XL", "XXL", "2XL"}
ACCEPTED_SHOE_SIZES = {"41", "42", "43"}

import re

def size_is_accepted(size_title):
    if not size_title:
        return False
    upper = size_title.upper()
    # Tokens alphabétiques (ex: "M (38)" -> "M", "S/36" -> "S", "XL" -> "XL")
    letter_tokens = re.findall(r"[A-Za-z]+", upper)
    if any(t in ACCEPTED_SIZES for t in letter_tokens):
        return True
    # Tokens numériques (ex: "42", "EU 42", "42.5") pour les pointures
    number_tokens = re.findall(r"\d+(?:\.\d+)?", upper)
    return any(n in ACCEPTED_SHOE_SIZES for n in number_tokens)


def filter_price_outliers(prices):
    """
    PISTE 1 : filtrage IQR avant de calculer médiane/variance.
    Écarte les comparables aberrants (ex: une pièce vintage rare à 100€ au
    milieu de basiques à 15-20€) pour que la variance reflète la vraie
    dispersion du marché plutôt que le bruit d'un seul outlier.
    Ne filtre que si on a assez de points pour que Q1/Q3 aient un sens,
    et ne retourne jamais un panel plus petit que MIN_COMPARABLES.
    """
    if len(prices) < 5:
        return prices
    s = sorted(prices)
    n = len(s)
    q1 = statistics.median(s[: n // 2])
    q3 = statistics.median(s[(n + 1) // 2 :])
    iqr = q3 - q1
    if iqr <= 0:
        return prices
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    filtered = [p for p in prices if low <= p <= high]
    return filtered if len(filtered) >= MIN_COMPARABLES else prices


# PISTE 6 : l'API Vinted ne renvoie que des annonces ACTIVES (prix demandés),
# jamais des prix de vente réels. Sur les marques hype, une part importante
# des annonces sont postées à des prix aspirationnels qui ne se vendent
# jamais ("au cas où") -> la médiane de ces prix surestime largement ce
# qu'on peut réellement obtenir en vendant rapidement. Pour ces marques,
# on utilise un percentile bas plutôt que la médiane, pour se rapprocher
# d'un prix de vente rapide réaliste plutôt que du prix affiché optimiste.
HYPE_BRANDS = {
    "Supreme", "Yeezy", "Stone Island", "Arc'teryx", "Arcteryx",
    "Moncler", "Palace", "Off-White", "BAPE",
}
HYPE_BRANDS_PERCENTILE = 0.35
_HYPE_BRANDS_NORM = {b.strip().casefold() for b in HYPE_BRANDS}


def is_hype_item(item):
    """
    BUGFIX : le champ brand_title de Vinted est parfois vide, mal casé,
    ou absent (vendeur qui n'a pas tagué la marque) -> une comparaison
    stricte "in HYPE_BRANDS" ratait silencieusement l'item et retombait
    sur la médiane brute (prix gonflés). On compare en casefold/strip,
    ET on vérifie aussi si le nom de la marque apparaît dans le titre en
    filet de sécurité.
    """
    brand = (item.get("brand_title") or "").strip().casefold()
    if brand in _HYPE_BRANDS_NORM:
        return True
    title = (item.get("title") or "").casefold()
    return any(b.casefold() in title for b in HYPE_BRANDS)


# PISTE 7 : détection des répliques / contrefaçons / "dupes".
# Ces annonces (le vendeur l'annonce souvent lui-même : "non originale",
# "dupe", "style", "inspired by"...) ne doivent JAMAIS être comparées aux
# prix du marché de l'article authentique -> ça produit une marge fantôme
# énorme et pousserait à acheter un faux en pensant avoir une bonne affaire.
REPLICA_KEYWORDS = [
    "dupe", "replica", "réplique", "repro ", "reproduction",
    "style of", "inspired by", "inspiré", "inspirée", "ispirato", "ispirata",
    "fake", "nicht original", "non original", "non originale",
    "sin original", "senza originale", "senza originali",
    "imitation", "imitación", "imitazione",
    "kopie", "copie", "copia", "1:1", "aaa quality", "reps ",
    "not original", "unofficial", "bootleg", "counterfeit",
]


def looks_like_replica(title):
    t = " " + (title or "").casefold() + " "
    return any(kw in t for kw in REPLICA_KEYWORDS)


def percentile(sorted_prices, pct):
    if not sorted_prices:
        return None
    if len(sorted_prices) == 1:
        return sorted_prices[0]
    k = (len(sorted_prices) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(sorted_prices) - 1)
    if f == c:
        return sorted_prices[f]
    return sorted_prices[f] * (c - k) + sorted_prices[c] * (k - f)


EMAIL_FROM = os.environ["EMAIL_ADDRESS"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]
PROXY_URL = os.environ.get("PROXY_URL")  # optionnel, proxy résidentiel
# PISTE 9 : webhook Discord optionnel pour une alerte quasi instantanée dès
# qu'un deal est détecté, en plus du récap email en fin de run. Facultatif :
# si le secret n'est pas défini, le bot continue de fonctionner comme avant
# (email uniquement), rien ne casse.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

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


def request_with_backoff(s, url, params, domain, context, timeout=15):
    """
    PISTE 5 : sur un 429 (rate limit), on attend et on retente une fois au
    lieu d'abandonner direct — évite de perdre des scans entiers quand
    Vinted throttle temporairement, sans pour autant marteler l'API.
    """
    r = s.get(url, params=params, timeout=timeout)
    if r.status_code == 429:
        wait = random.uniform(20, 40)
        print(f"[{domain}] 429 rate limit sur {context}, pause {wait:.0f}s puis 1 nouvel essai")
        time.sleep(wait)
        r = s.get(url, params=params, timeout=timeout)
    return r


def search_vinted(s, domain, kw):
    try:
        r = request_with_backoff(
            s,
            f"https://www.{domain}/api/v2/catalog/items",
            {
                "search_text": kw,
                "price_to": PRICE_MAX,
                "price_from": PRICE_MIN,
                "order": "newest_first",
                "per_page": 10,  # réduit de 40 à 10 pour limiter le volume de requêtes
                "currency": "EUR",
            },
            domain,
            f"recherche '{kw}'",
        )
        if r.status_code != 200:
            print(f"[{domain}] {kw}: status {r.status_code}")
            return []
        return r.json().get("items", [])
    except Exception as e:
        print(f"[{domain}] Erreur recherche '{kw}': {e}")
        return []


def estimate_price(s, domain, item, min_comparables):
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
        r = request_with_backoff(
            s,
            f"https://www.{domain}/api/v2/catalog/items",
            params,
            domain,
            f"estimation '{item.get('title','')[:30]}'",
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
        raw_count = len(prices)
        if raw_count < min_comparables:
            return None, raw_count, None
        # PISTE 1 : on nettoie le panel des outliers avant médiane/variance
        clean_prices = filter_price_outliers(prices)
        sorted_clean = sorted(clean_prices)

        brand = (item.get("brand_title") or "").strip()
        if is_hype_item(item):
            # PISTE 6 (corrigée) : percentile bas plutôt que médiane pour ces marques
            # (annonces "aspirationnelles" qui gonflent la médiane sans jamais se vendre)
            est = percentile(sorted_clean, HYPE_BRANDS_PERCENTILE)
        else:
            est = statistics.median(sorted_clean)

        var = (statistics.stdev(sorted_clean) / statistics.median(sorted_clean) * 100) if len(sorted_clean) > 1 else 0
        return est, raw_count, var
    except Exception as e:
        print(f"[{domain}] Erreur estimation prix: {e}")
        return None, 0, None


def load_seen():
    """
    PISTE 4 : suivi global (et non plus par domaine).
    Les IDs Vinted sont uniques sur TOUTE la plateforme : le même article
    ressort sous le même id sur vinted.fr, vinted.de, vinted.it, etc.
    Avec un seen par domaine, le même article était rescanné et pouvait
    remonter comme deal sur chaque pays (5-6x plus d'appels API, et le
    même deal dupliqué dans l'email). On migre automatiquement l'ancien
    format {domaine: [...]} vers un set global si besoin.
    """
    try:
        data = json.load(open(SEEN_FILE))
        if isinstance(data, list):
            return set(data)
        if isinstance(data, dict):
            # ancien format {domaine: [ids]} -> fusion en un seul set global
            print("Ancien format de seen_items.json (par domaine) détecté, fusion en set global.")
            merged = set()
            for ids in data.values():
                merged.update(ids)
            return merged
        return set()
    except Exception:
        return set()


def save_seen(seen):
    json.dump(list(seen), open(SEEN_FILE, "w"))


def send_email(deals, bundles=None):
    bundles = bundles or []
    # PISTE 8 : on sépare les deals selon leur fiabilité plutôt que de tout
    # mettre au même niveau. Un deal est "à vérifier" quand il repose sur
    # un ratio prix/marché très élevé (>4x) avec relativement peu de
    # comparables, OU sur une marque hype (marché volatile, prix affichés
    # peu fiables) -> on le signale au lieu de le présenter comme une
    # certitude, pour éviter les achats sur de faux positifs.
    reliable = [d for d in deals if not d[8]]
    review = [d for d in deals if d[8]]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{len(reliable)} deals fiables + {len(review)} à vérifier + {len(bundles)} lots"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    def render_section(title, items, note):
        html = f"<h2>{title}</h2><p>{note}</p>"
        for d in items:
            item, mp, cc, tc, np, sp, spr, v, needs_review, cl, domain = d
            item_id = item.get("id")
            link = item.get("url") or (f"https://www.{domain}{item.get('path')}" if item.get("path") else "") or (f"https://www.{domain}/items/{item_id}" if item_id else "")
            html += "<div style='border:1px solid #999;padding:10px;margin:10px 0'>"
            html += f"<b>[{domain}] " + item.get("title", "") + "</b><br>"
            brand = item.get("brand_title") or ""
            if brand:
                html += f"Marque: {brand}<br>"
            html += "Prix: " + str(item.get("price", {}).get("amount", "")) + " | Coûts: " + str(tc) + " | Bénéfice: " + str(spr) + "<br>"
            html += "Prix marché estimé: " + str(round(mp, 2)) + " | Comparables: " + str(cc) + "<br>"
            html += cl + "<br>"
            if link:
                html += f'<a href="{link}">Voir l\'annonce sur Vinted</a>'
            html += "</div>"
        return html

    def render_bundles(items):
        html = (
            "<h2>🎁 Lots groupés à examiner</h2>"
            "<p>Ces annonces contiennent plusieurs articles non détaillés individuellement dans le titre -"
            " l'algorithme Vinted les classe plus bas, donc moins de concurrence, mais le prix affiché est celui du LOT entier,"
            " pas d'un article seul. Regarde le contenu détaillé avant d'acheter, aucune marge n'est calculée automatiquement.</p>"
        )
        for item, price, domain in items:
            item_id = item.get("id")
            link = item.get("url") or (f"https://www.{domain}{item.get('path')}" if item.get("path") else "") or (f"https://www.{domain}/items/{item_id}" if item_id else "")
            html += "<div style='border:1px solid #999;padding:10px;margin:10px 0'>"
            html += f"<b>[{domain}] " + item.get("title", "") + "</b><br>"
            html += f"Prix du lot: {price}€<br>"
            if link:
                html += f'<a href="{link}">Voir l\'annonce sur Vinted</a>'
            html += "</div>"
        return html

    html = "<h1>ARTICLES</h1>"
    html += render_section(
        "✅ Deals fiables", reliable,
        "Ratio prix/marché raisonnable et/ou assez de comparables pour être confiant.",
    )
    html += render_section(
        "⚠️ À vérifier manuellement avant d'acheter", review,
        "Marque volatile (hype) et/ou marge qui repose sur peu de comparables -"
        " vérifie l'annonce à l'œil (photos, description, prix réels d'articles similaires déjà vendus) avant d'acheter.",
    )
    if bundles:
        html += render_bundles(bundles)
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(EMAIL_FROM, EMAIL_PASSWORD)
        srv.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


def notify_discord(deal_tuple, domain):
    """
    PISTE 9 : alerte quasi instantanée dès qu'un deal est trouvé, au lieu
    d'attendre la fin du scan des 6 pays (~15-20 min avec les pauses
    anti-détection) pour un seul email groupé. N'échoue jamais bruyamment :
    si le webhook n'est pas configuré ou si l'appel échoue, on log et on
    continue le scan (une notif ratée ne doit jamais interrompre le bot).
    """
    if not DISCORD_WEBHOOK_URL:
        return
    item, mp, cc, tc, np, sp, spr, var, needs_review, cl, _domain = deal_tuple
    item_id = item.get("id")
    link = item.get("url") or (f"https://www.{domain}{item.get('path')}" if item.get("path") else "") or (f"https://www.{domain}/items/{item_id}" if item_id else "")
    price = item.get("price", {}).get("amount", "")
    title = item.get("title", "")
    photo_url = ((item.get("photo") or {}).get("url")) or None

    embed = {
        "title": f"[{domain}] {title}"[:256],
        "url": link or None,
        "description": (
            f"{'⚠️ À vérifier (marque hype / peu de comparables)' if needs_review else '✅ Deal fiable'}\n"
            f"Prix: {price}€ | Marché estimé: {round(mp, 2)}€ | Bénéfice: {spr}€\n"
            f"Comparables: {cc} | État: {cl}"
        ),
        "color": 0xFFA500 if needs_review else 0x2ECC71,
    }
    if photo_url:
        embed["thumbnail"] = {"url": photo_url}

    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
    except Exception as e:
        print(f"[{domain}] Erreur notification Discord: {e}")


def scan_domain(domain, seen):
    s = get_session(domain)
    items = []

    for kw in KEYWORDS:
        for itm in search_vinted(s, domain, kw):
            iid = str(itm.get("id"))
            if iid not in seen:
                seen.add(iid)
                # on garde le mot-clé qui a trouvé l'item pour ajuster
                # le seuil de comparables plus loin (PISTE 2)
                itm["_search_kw"] = kw
                items.append(itm)
        pause_longue()

    deals = []
    bundles = []  # PISTE 10 : lots groupés, jamais passés au calcul de marge automatique
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

        full_title = itm.get("title", "")
        if looks_like_replica(full_title):
            print(f"[{domain}] REJET '{title}': réplique/fake suspecté(e) dans le titre")
            continue

        is_lot = itm.get("_search_kw") in LOT_KEYWORDS
        if is_lot:
            # Un lot n'a pas une taille unique -> on ne filtre pas dessus.
            # Le prix d'un lot n'est pas comparable à la médiane d'un article
            # seul -> pas de calcul de marge automatique, juste remonté pour
            # vérification manuelle (regarder combien de pièces, lesquelles,
            # état, avant de se décider).
            price = float(itm["price"]["amount"])
            print(f"[{domain}] LOT '{title}': prix {price}€ | url={itm.get('url')!r} path={itm.get('path')!r} id={itm.get('id')}")
            bundles.append((itm, price, domain))
            pause_courte()
            continue

        size_title = itm.get("size_title")
        if not size_is_accepted(size_title):
            print(f"[{domain}] REJET '{title}': taille non retenue ({size_title!r})")
            continue

        min_comp = GENERIC_KEYWORDS_MIN_COMPARABLES.get(itm.get("_search_kw"), MIN_COMPARABLES)
        mp, cc, var = estimate_price(s, domain, itm, min_comp)
        price = float(itm["price"]["amount"])
        if not mp:
            print(f"[{domain}] REJET '{title}': pas assez de comparables ({cc} trouvés, {min_comp} requis)")
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
            # PISTE 8 : fiabilité du deal. Un deal est "à vérifier" si la
            # marque est volatile (hype, prix affichés peu fiables) OU si
            # le ratio prix/marché est très élevé (>4x) sans un panel de
            # comparables large pour l'étayer (cc >= seuil de confiance).
            ratio = (mp / price) if price else 0
            hype = is_hype_item(itm)
            needs_review = hype or (ratio > 4 and cc < MIN_COMPARABLES_FOR_SUCCESS)
            tag = "DEAL(à vérifier)" if needs_review else "DEAL"
            print(f"[{domain}] {tag} '{title}': prix {price}€, médian {mp}€, marge {np}€ | url={itm.get('url')!r} path={itm.get('path')!r} id={itm.get('id')}")
            deal_tuple = (
                itm, mp, cc, tc, np, sp, spr, var,
                needs_review,
                CONDITION_LABELS.get(cond, ""),
                domain,
            )
            deals.append(deal_tuple)
            # PISTE 9 : notif immédiate au lieu d'attendre la fin du scan
            # des 6 pays pour un seul email groupé.
            notify_discord(deal_tuple, domain)
        pause_courte()

    return deals, bundles


def dedupe_deals(all_deals):
    """
    PISTE 4 (suite) : filet de sécurité en plus du seen global — au cas où
    un même article serait quand même vu deux fois dans le même run (ex.
    deux mots-clés différents le trouvent avant que 'seen' soit mis à jour).
    On garde la version avec la meilleure marge nette (np, index 4 du tuple).
    """
    best_by_id = {}
    for d in all_deals:
        item_id = d[0].get("id")
        if item_id not in best_by_id or d[4] > best_by_id[item_id][4]:
            best_by_id[item_id] = d
    return list(best_by_id.values())


def main():
    seen = load_seen()
    all_deals = []
    all_bundles = []

    # on mélange l'ordre des pays a chaque run pour varier le pattern
    domains_order = DOMAINS[:]
    random.shuffle(domains_order)

    for domain in domains_order:
        print(f"--- Scan {domain} ---")
        deals, bundles = scan_domain(domain, seen)
        all_deals.extend(deals)
        all_bundles.extend(bundles)
        pause_longue()

    all_deals = dedupe_deals(all_deals)
    # dédup simple des lots par id (même logique que dedupe_deals mais sans marge à comparer)
    all_bundles = list({b[0].get("id"): b for b in all_bundles}.values())

    if all_deals or all_bundles:
        send_email(all_deals, all_bundles)
        print(f"{len(all_deals)} bonnes affaires + {len(all_bundles)} lots trouvés, email envoyé.")
    else:
        print("Aucune bonne affaire cette fois.")

    save_seen(seen)


if __name__ == "__main__":
    main()
