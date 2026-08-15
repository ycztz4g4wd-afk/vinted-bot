import os
import json
import time
import random
import statistics
import smtplib
import re
import requests

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ============================================================
# CONFIGURATION
# ============================================================

DOMAINS = [
    "vinted.fr",
    "vinted.de",
    "vinted.es",
    "vinted.it",
    "vinted.co.uk",
    "vinted.be",
]

KEYWORDS = [
    "Nike Air Force 1",
    "Air Jordan sneakers",
    "Nike Nocta survet",
    "Nike Tech Fleece survet",
    "Nike Dunk Low",

    "Carhartt jacket",
    "Ralph Lauren polo",
    "The North Face jacket",
    "Patagonia fleece",
    "Stone Island jacket",
    "Stone Island survet",
    "Arc'teryx jacket",
    "Eastpak backpack",

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

    "Funko Pop",

    # fautes courantes
    "Ralf Lauren polo",
    "Arc'tery jacket",
    "Stussi hoodie",
    "Carhart jacket",
    "Fred Perri polo",
    "Addidas Originals",
    "Levis veste vintage",
]

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


# ============================================================
# BUDGET / RENTABILITE
# ============================================================

# Ton capital de départ.
# Le bot peut fonctionner avec n'importe quel montant.
STARTING_BUDGET = 20.0

PRICE_MIN = 0.50
PRICE_MAX = 40.0

# Frais estimés côté acheteur.
SHIPPING_COST_ESTIMATE = 5.0
BUYER_PROTECTION_PERCENT = 0.05
BUYER_PROTECTION_FIXED = 0.70

# Marge minimale que l'on veut réellement obtenir.
MIN_PROFIT_EUR = 6.0

# Marge prudente minimale pour classer "ACHETER".
MIN_SAFE_PROFIT_EUR = 8.0

# Nombre minimum de comparables.
MIN_COMPARABLES = 8

# Très important :
# on ne veut pas acheter quelque chose qui consomme presque tout
# le capital sauf si le potentiel est exceptionnel.
MAX_BUDGET_USAGE_NORMAL = 0.40
MAX_BUDGET_USAGE_EXCEPTIONAL = 0.65


# ============================================================
# TAILLES
# ============================================================

ACCEPTED_SIZES = {
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "2XL",
}

ACCEPTED_SHOE_SIZES = {
    "41",
    "42",
    "43",
}


SIZE_IDS_FILTER = [
    3, 4, 5, 6, 7,
    61, 62, 63,
]


# ============================================================
# ETATS
# ============================================================

POOR_CONDITION_KEYWORDS = [
    "satisf",
    "zufriedenstellend",
    "soddisf",
    "poor",
    "acceptable",
    "fair",
    "used",
]


def is_poor_condition(status_text):
    if not status_text:
        return False

    text = status_text.casefold()

    return any(
        keyword in text
        for keyword in POOR_CONDITION_KEYWORDS
    )


# ============================================================
# ENFANTS
# ============================================================

KIDS_INDICATOR_RE = re.compile(
    r"\b("
    r"\d+\s*(?:ans?|ann[ée]es?|years?|yrs?|mois|months?|"
    r"jahre?|jahr|anni|anno|años|meses|mes)"
    r"|enfant|b[ée]b[ée]s?|babys?|babies|kids?|"
    r"gar[cç]ons?|filles?|boys?|girls?|junior|toddler|"
    r"infant|child(?:ren)?|bambin[oa]?|ni[ñn][oa]s?|kind(?:er)?"
    r")\b",
    re.IGNORECASE,
)


def looks_like_kids_item(title, size_title=None):
    combined = f"{title or ''} {size_title or ''}"
    return bool(KIDS_INDICATOR_RE.search(combined))


# ============================================================
# CONTREFACONS
# ============================================================

REPLICA_KEYWORDS = [
    "dupe",
    "replica",
    "réplique",
    "repro ",
    "reproduction",
    "style of",
    "inspired by",
    "inspiré",
    "inspirée",
    "ispirato",
    "ispirata",
    "fake",
    "nicht original",
    "non original",
    "non originale",
    "sin original",
    "senza originale",
    "imitation",
    "imitación",
    "imitazione",
    "kopie",
    "copie",
    "copia",
    "1:1",
    "aaa quality",
    "reps ",
    "not original",
    "unofficial",
    "bootleg",
    "counterfeit",
]


def looks_like_replica(title):
    text = f" {(title or '').casefold()} "

    return any(
        keyword.casefold() in text
        for keyword in REPLICA_KEYWORDS
    )


# ============================================================
# LOTS
# ============================================================

BUNDLE_INDICATOR_RE = re.compile(
    r"\b(lots?|bundle|pack(?:\s+de|\s+of)?|paquet)\b"
    r"|\b\d+\s*(?:x\b|polos?|t-?shirts?|tee\s*shirts?|"
    r"pulls?|paires?|chaussures?|shorts?|maillots?|"
    r"v[eê]tements?|pi[eè]ces?|items?)\b"
    r"|\bx\s*\d+\b",
    re.IGNORECASE,
)


def looks_like_actual_bundle(title):
    return bool(
        BUNDLE_INDICATOR_RE.search(title or "")
    )


# ============================================================
# TAILLES
# ============================================================

def size_is_accepted(size_title):
    if not size_title:
        return False

    upper = size_title.upper()

    letters = re.findall(
        r"[A-Z]+",
        upper,
    )

    if any(
        token in ACCEPTED_SIZES
        for token in letters
    ):
        return True

    numbers = re.findall(
        r"\d+(?:\.\d+)?",
        upper,
    )

    return any(
        number in ACCEPTED_SHOE_SIZES
        for number in numbers
    )


# ============================================================
# MARQUES / MODELES RISQUES
# ============================================================

HYPE_BRANDS = {
    "supreme",
    "yeezy",
    "stone island",
    "arcteryx",
    "arc'teryx",
    "moncler",
    "palace",
    "off-white",
    "bape",
}


HYPE_MODELS = {
    "dunk low",
    "air jordan",
    "jordan 1",
    "jordan 4",
    "2002r",
    "travis scott",
}


def is_hype_item(item):
    brand = (
        item.get("brand_title")
        or ""
    ).strip().casefold()

    if brand in HYPE_BRANDS:
        return True

    title = (
        item.get("title")
        or ""
    ).casefold()

    if any(
        brand in title
        for brand in HYPE_BRANDS
    ):
        return True

    return any(
        model in title
        for model in HYPE_MODELS
    )


# ============================================================
# MEDIANE / PERCENTILES
# ============================================================

def percentile(values, pct):
    if not values:
        return None

    values = sorted(values)

    if len(values) == 1:
        return values[0]

    position = (
        len(values) - 1
    ) * pct

    lower = int(position)
    upper = min(
        lower + 1,
        len(values) - 1,
    )

    if lower == upper:
        return values[lower]

    fraction = position - lower

    return (
        values[lower]
        * (1 - fraction)
        + values[upper]
        * fraction
    )


def remove_outliers(prices):
    if len(prices) < 8:
        return prices

    ordered = sorted(prices)

    q1 = percentile(
        ordered,
        0.25,
    )

    q3 = percentile(
        ordered,
        0.75,
    )

    iqr = q3 - q1

    if iqr <= 0:
        return prices

    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr

    filtered = [
        price
        for price in prices
        if low <= price <= high
    ]

    if len(filtered) < 8:
        return prices

    return filtered


# ============================================================
# SCORE DE VENTE
# ============================================================

def calculate_sale_score(
    purchase_price,
    cautious_sale_price,
    probable_sale_price,
    comparable_count,
    variance,
    engagement,
    title,
    item,
):
    score = 0.0

    # --------------------------------------------------------
    # 1. MARGE
    # --------------------------------------------------------

    if purchase_price <= 0:
        return 0

    profit_ratio = (
        cautious_sale_price
        - purchase_price
    ) / purchase_price

    if profit_ratio >= 3:
        score += 30
    elif profit_ratio >= 2:
        score += 27
    elif profit_ratio >= 1.5:
        score += 24
    elif profit_ratio >= 1:
        score += 20
    elif profit_ratio >= 0.7:
        score += 14
    elif profit_ratio >= 0.4:
        score += 8
    else:
        score += 2

    # --------------------------------------------------------
    # 2. NOMBRE DE COMPARABLES
    # --------------------------------------------------------

    if comparable_count >= 40:
        score += 15
    elif comparable_count >= 25:
        score += 13
    elif comparable_count >= 15:
        score += 10
    elif comparable_count >= 10:
        score += 7
    elif comparable_count >= 8:
        score += 4

    # --------------------------------------------------------
    # 3. STABILITE DU MARCHE
    # --------------------------------------------------------

    if variance is None:
        score += 0

    elif variance <= 20:
        score += 15

    elif variance <= 30:
        score += 12

    elif variance <= 40:
        score += 8

    elif variance <= 50:
        score += 4

    # --------------------------------------------------------
    # 4. ENGAGEMENT
    #
    # Faible engagement = article potentiellement encore
    # disponible et moins découvert.
    # --------------------------------------------------------

    if engagement <= 2:
        score += 10

    elif engagement <= 5:
        score += 8

    elif engagement <= 10:
        score += 6

    elif engagement <= 20:
        score += 3

    else:
        score += 0

    # --------------------------------------------------------
    # 5. MARQUE / MODELE
    # --------------------------------------------------------

    if is_hype_item(item):
        # Hype = potentiel élevé mais risque élevé.
        score += 3
    else:
        score += 8

    # --------------------------------------------------------
    # 6. PRIX D'ACHAT
    # --------------------------------------------------------

    if purchase_price <= 5:
        score += 7

    elif purchase_price <= 8:
        score += 5

    elif purchase_price <= 12:
        score += 3

    # --------------------------------------------------------
    # 7. TITRE
    #
    # Un titre très précis est généralement plus facile
    # à identifier/rechercher.
    # --------------------------------------------------------

    title_lower = title.casefold()

    useful_words = [
        "vintage",
        "original",
        "authentique",
        "authentic",
        "oversize",
        "rare",
        "archive",
        "1990",
        "2000",
    ]

    if any(
        word in title_lower
        for word in useful_words
    ):
        score += 2

    return min(
        100,
        round(score),
    )


# ============================================================
# CLASSEMENT
# ============================================================

def classify_deal(
    score,
    cautious_profit,
    probable_profit,
    purchase_price,
    budget,
    authenticity_risk,
):
    if authenticity_risk:
        return "🔴 RISQUE AUTHENTICITÉ"

    if cautious_profit < 4:
        return "⚫ À ÉVITER"

    if score >= 80 and cautious_profit >= MIN_SAFE_PROFIT_EUR:
        return "🟢 ACHETER"

    if score >= 68 and probable_profit >= MIN_PROFIT_EUR:
        return "🟡 BON PLAN"

    if score >= 55:
        return "🟠 À ÉTUDIER"

    return "⚫ À ÉVITER"


# ============================================================
# PRIX MAXIMUM D'ACHAT
# ============================================================

def calculate_max_purchase_price(
    cautious_sale_price,
    budget,
    score,
):
    if not cautious_sale_price:
        return 0

    # On veut garder une marge de sécurité.
    #
    # Exemple :
    # vente prudente = 15 €
    # prix max calculé ≈ 5-7 €
    #
    # Cela évite les faux bons plans.
    if score >= 85:
        target_ratio = 0.42

    elif score >= 75:
        target_ratio = 0.38

    elif score >= 65:
        target_ratio = 0.32

    else:
        target_ratio = 0.25

    max_price = (
        cautious_sale_price
        * target_ratio
    )

    # Ne jamais consommer tout le budget.
    max_budget_price = (
        budget
        * MAX_BUDGET_USAGE_NORMAL
    )

    max_price = min(
        max_price,
        max_budget_price,
    )

    return round(
        max(0, max_price),
        2,
    )


# ============================================================
# SESSION
# ============================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


def get_session(domain):
    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    try:
        session.get(
            f"https://www.{domain}/",
            timeout=15,
        )

    except Exception as exc:
        print(
            f"[{domain}] "
            f"Session initiale impossible: {exc}"
        )

    return session


# ============================================================
# REQUETE
# ============================================================

def request_vinted(
    session,
    url,
    params,
    domain,
    context,
):
    try:
        response = session.get(
            url,
            params=params,
            timeout=15,
        )

        if response.status_code == 429:
            print(
                f"[{domain}] "
                f"Rate limit sur {context}. "
                f"On arrête ce domaine pour ce run."
            )

            return None

        if response.status_code != 200:
            print(
                f"[{domain}] "
                f"{context}: HTTP "
                f"{response.status_code}"
            )

            return None

        return response

    except Exception as exc:
        print(
            f"[{domain}] "
            f"Erreur {context}: {exc}"
        )

        return None


# ============================================================
# RECHERCHE
# ============================================================

def search_vinted(
    session,
    domain,
    keyword,
):
    params = {
        "search_text": keyword,
        "price_to": PRICE_MAX,
        "price_from": PRICE_MIN,
        "order": "newest_first",
        "per_page": 20,
        "currency": "EUR",
    }

    if keyword not in LOT_KEYWORDS:
        params[
            "size_ids[]"
        ] = SIZE_IDS_FILTER

    response = request_vinted(
        session,
        f"https://www.{domain}/api/v2/catalog/items",
        params,
        domain,
        f"recherche {keyword}",
    )

    if response is None:
        return []

    try:
        data = response.json()

        return data.get(
            "items",
            [],
        )

    except Exception as exc:
        print(
            f"[{domain}] "
            f"JSON invalide: {exc}"
        )

        return []


# ============================================================
# COMPARABLES
# ============================================================

def get_comparables(
    session,
    domain,
    item,
):
    brand_id = (
        item.get("brand_dto") or {}
    ).get("id")

    catalog_id = item.get(
        "catalog_id"
    )

    title = item.get(
        "title",
        "",
    )

    params = {
        "order": "relevance",
        "per_page": 50,
        "currency": "EUR",
        "search_text": title,
    }

    if brand_id:
        params[
            "brand_ids[]"
        ] = brand_id

    if catalog_id:
        params[
            "catalog[]"
        ] = catalog_id

    response = request_vinted(
        session,
        f"https://www.{domain}/api/v2/catalog/items",
        params,
        domain,
        f"comparables {title[:40]}",
    )

    if response is None:
        return []

    try:
        data = response.json()

    except Exception:
        return []

    prices = []

    for comparable in data.get(
        "items",
        [],
    ):
        if comparable.get(
            "id"
        ) == item.get("id"):
            continue

        price_data = comparable.get(
            "price",
            {},
        )

        amount = price_data.get(
            "amount"
        )

        if amount is None:
            continue

        try:
            price = float(amount)

        except Exception:
            continue

        if price <= 0:
            continue

        prices.append(price)

    return prices


# ============================================================
# ANALYSE D'UN ARTICLE
# ============================================================

def analyse_item(
    session,
    domain,
    item,
    budget,
):
    title = item.get(
        "title",
        "",
    )

    price_data = item.get(
        "price",
        {},
    )

    try:
        purchase_price = float(
            price_data.get(
                "amount",
                0,
            )
        )

    except Exception:
        return None

    if purchase_price <= 0:
        return None

    status = (
        item.get("status")
        or ""
    )

    size = item.get(
        "size_title"
    )

    # --------------------------------------------------------
    # FILTRES
    # --------------------------------------------------------

    if is_poor_condition(status):
        return None

    if looks_like_replica(title):
        return None

    if looks_like_kids_item(
        title,
        size,
    ):
        return None

    if not size_is_accepted(size):
        return None

    # --------------------------------------------------------
    # COMPARABLES
    # --------------------------------------------------------

    prices = get_comparables(
        session,
        domain,
        item,
    )

    if len(prices) < MIN_COMPARABLES:
        return None

    prices = remove_outliers(
        prices
    )

    if len(prices) < MIN_COMPARABLES:
        return None

    prices = sorted(prices)

    # --------------------------------------------------------
    # TROIS SCENARIOS
    #
    # prudent = 25e percentile
    # probable = 40e percentile
    # optimiste = médiane
    #
    # On évite volontairement d'utiliser un prix très haut.
    # --------------------------------------------------------

    cautious_sale_price = percentile(
        prices,
        0.25,
    )

    probable_sale_price = percentile(
        prices,
        0.40,
    )

    optimistic_sale_price = percentile(
        prices,
        0.50,
    )

    if not cautious_sale_price:
        return None

    # --------------------------------------------------------
    # VARIANCE
    # --------------------------------------------------------

    median_price = statistics.median(
        prices
    )

    if len(prices) > 1 and median_price:
        variance = (
            statistics.stdev(prices)
            / median_price
            * 100
        )

    else:
        variance = 0

    # --------------------------------------------------------
    # FRAIS
    # --------------------------------------------------------

    real_fee = (
        item.get("service_fee") or {}
    ).get("amount")

    try:
        if real_fee:
            buyer_fee = float(
                real_fee
            )
        else:
            buyer_fee = round(
                purchase_price
                * BUYER_PROTECTION_PERCENT
                + BUYER_PROTECTION_FIXED,
                2,
            )

    except Exception:
        buyer_fee = round(
            purchase_price
            * BUYER_PROTECTION_PERCENT
            + BUYER_PROTECTION_FIXED,
            2,
        )

    total_cost = round(
        purchase_price
        + SHIPPING_COST_ESTIMATE
        + buyer_fee,
        2,
    )

    # --------------------------------------------------------
    # BENEFICES
    # --------------------------------------------------------

    cautious_profit = round(
        cautious_sale_price
        - total_cost,
        2,
    )

    probable_profit = round(
        probable_sale_price
        - total_cost,
        2,
    )

    optimistic_profit = round(
        optimistic_sale_price
        - total_cost,
        2,
    )

    # --------------------------------------------------------
    # ENGAGEMENT
    # --------------------------------------------------------

    views = (
        item.get("view_count")
        or 0
    )

    favourites = (
        item.get(
            "favourite_count"
        )
        or 0
    )

    engagement = (
        views
        + favourites
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = calculate_sale_score(
        purchase_price,
        cautious_sale_price,
        probable_sale_price,
        len(prices),
        variance,
        engagement,
        title,
        item,
    )

    # --------------------------------------------------------
    # RISQUE AUTHENTICITE
    # --------------------------------------------------------

    authenticity_risk = (
        is_hype_item(item)
        and purchase_price
        < cautious_sale_price * 0.25
    )

    # --------------------------------------------------------
    # PRIX MAX D'ACHAT
    # --------------------------------------------------------

    max_purchase = calculate_max_purchase_price(
        cautious_sale_price,
        budget,
        score,
    )

    # --------------------------------------------------------
    # CLASSEMENT
    # --------------------------------------------------------

    classification = classify_deal(
        score,
        cautious_profit,
        probable_profit,
        purchase_price,
        budget,
        authenticity_risk,
    )

    # --------------------------------------------------------
    # CONDITIONS POUR ÊTRE UNE VRAIE ALERTE
    # --------------------------------------------------------

    # On ne veut pas recevoir 300 faux deals.
    if classification == "⚫ À ÉVITER":
        return None

    # Si même le scénario prudent ne laisse pas assez de marge,
    # ce n'est pas intéressant avec seulement 20 €.
    if cautious_profit < MIN_PROFIT_EUR:
        if classification != "🟡 BON PLAN":
            return None

    return {
        "item": item,
        "domain": domain,

        "purchase_price": purchase_price,

        "cautious_sale_price": round(
            cautious_sale_price,
            2,
        ),

        "probable_sale_price": round(
            probable_sale_price,
            2,
        ),

        "optimistic_sale_price": round(
            optimistic_sale_price,
            2,
        ),

        "total_cost": total_cost,

        "cautious_profit": cautious_profit,

        "probable_profit": probable_profit,

        "optimistic_profit": optimistic_profit,

        "comparables": len(prices),

        "variance": round(
            variance,
            1,
        ),

        "views": views,

        "favourites": favourites,

        "engagement": engagement,

        "score": score,

        "max_purchase": max_purchase,

        "classification": classification,

        "authenticity_risk": authenticity_risk,
    }


# ============================================================
# SCAN D'UN DOMAINE
# ============================================================

def scan_domain(
    domain,
    seen,
    budget,
):
    print(
        f"\n========== {domain} =========="
    )

    session = get_session(
        domain
    )

    new_items = []

    # Mélange des recherches pour ne pas toujours commencer
    # par les mêmes catégories.
    keywords = KEYWORDS[:]

    random.shuffle(
        keywords
    )

    for keyword in keywords:
        results = search_vinted(
            session,
            domain,
            keyword,
        )

        for item in results:
            item_id = str(
                item.get("id")
            )

            if not item_id:
                continue

            if item_id in seen:
                continue

            seen.add(
                item_id
            )

            item[
                "_search_keyword"
            ] = keyword

            new_items.append(
                item
            )

        # Pause normale entre recherches.
        time.sleep(
            random.uniform(
                1.5,
                3.0,
            )
        )

    print(
        f"[{domain}] "
        f"{len(new_items)} nouveaux articles."
    )

    deals = []
    bundles = []

    for item in new_items:

        title = item.get(
            "title",
            "",
        )

        keyword = item.get(
            "_search_keyword",
            "",
        )

        # ----------------------------------------------------
        # LOT
        # ----------------------------------------------------

        if (
            keyword in LOT_KEYWORDS
            and looks_like_actual_bundle(
                title
            )
        ):
            try:
                price = float(
                    item.get(
                        "price",
                        {},
                    ).get(
                        "amount",
                        0,
                    )
                )

            except Exception:
                price = 0

            if price > 0:
                bundles.append(
                    {
                        "item": item,
                        "domain": domain,
                        "price": price,
                    }
                )

            continue

        # ----------------------------------------------------
        # ARTICLE NORMAL
        # ----------------------------------------------------

        result = analyse_item(
            session,
            domain,
            item,
            budget,
        )

        if result:
            deals.append(
                result
            )

    return deals, bundles


# ============================================================
# DEDUPLICATION
# ============================================================

def dedupe_deals(deals):
    best = {}

    for deal in deals:
        item = deal["item"]

        item_id = item.get(
            "id"
        )

        if (
            item_id not in best
            or deal["score"]
            > best[item_id]["score"]
        ):
            best[item_id] = deal

    return list(
        best.values()
    )


# ============================================================
# EMAIL
# ============================================================

EMAIL_FROM = os.environ.get(
    "EMAIL_ADDRESS"
)

EMAIL_PASSWORD = os.environ.get(
    "EMAIL_PASSWORD"
)

EMAIL_TO = os.environ.get(
    "EMAIL_TO"
)

DISCORD_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL"
)


def make_item_url(
    item,
    domain,
):
    if item.get("url"):
        return item["url"]

    if item.get("path"):
        return (
            f"https://www.{domain}"
            f"{item['path']}"
        )

    if item.get("id"):
        return (
            f"https://www.{domain}"
            f"/items/{item['id']}"
        )

    return ""


def send_email(
    deals,
    bundles,
    budget,
):
    if not EMAIL_FROM:
        print(
            "EMAIL_ADDRESS absent."
        )
        return

    if not EMAIL_PASSWORD:
        print(
            "EMAIL_PASSWORD absent."
        )
        return

    if not EMAIL_TO:
        print(
            "EMAIL_TO absent."
        )
        return

    deals = sorted(
        deals,
        key=lambda x: (
            -x["score"],
            x["purchase_price"],
        ),
    )

    message = MIMEMultipart(
        "alternative"
    )

    message["Subject"] = (
        f"Vinted Scanner — "
        f"{len(deals)} opportunités"
    )

    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO

    html = """
    <html>
    <body style="font-family:Arial,sans-serif">
    """

    html += (
        f"<h1>Scanner Vinted</h1>"
        f"<p>Budget disponible : "
        f"<b>{budget:.2f} €</b></p>"
    )

    html += (
        "<p>"
        "Les prix de vente sont des estimations. "
        "Vinted ne fournit pas ici la confirmation "
        "qu'un article comparable a réellement été vendu."
        "</p>"
    )

    if deals:

        html += (
            "<h2>🔥 Opportunités</h2>"
        )

        for deal in deals:

            item = deal["item"]
            domain = deal["domain"]

            title = item.get(
                "title",
                "",
            )

            url = make_item_url(
                item,
                domain,
            )

            classification = deal[
                "classification"
            ]

            html += """
            <div style="
                border:1px solid #ccc;
                padding:15px;
                margin:15px 0;
                border-radius:8px;
            ">
            """

            html += (
                f"<h3>{classification} "
                f"— Score {deal['score']}/100</h3>"
            )

            html += (
                f"<b>{title}</b><br>"
                f"Pays : {domain}<br><br>"
            )

            html += (
                f"💰 Achat : "
                f"<b>{deal['purchase_price']:.2f} €</b><br>"
            )

            html += (
                f"🎯 Prix de revente prudent : "
                f"<b>{deal['cautious_sale_price']:.2f} €</b><br>"
            )

            html += (
                f"📊 Prix probable : "
                f"<b>{deal['probable_sale_price']:.2f} €</b><br>"
            )

            html += (
                f"🚀 Prix optimiste : "
                f"{deal['optimistic_sale_price']:.2f} €<br>"
            )

            html += (
                f"📦 Coût total estimé : "
                f"{deal['total_cost']:.2f} €<br><br>"
            )

            html += (
                f"🛡️ Bénéfice prudent : "
                f"<b>{deal['cautious_profit']:.2f} €</b><br>"
            )

            html += (
                f"💵 Bénéfice probable : "
                f"<b>{deal['probable_profit']:.2f} €</b><br>"
            )

            html += (
                f"📈 Bénéfice optimiste : "
                f"{deal['optimistic_profit']:.2f} €<br><br>"
            )

            html += (
                f"🧮 Comparables : "
                f"{deal['comparables']}<br>"
                f"📉 Variance : "
                f"{deal['variance']:.1f}%<br>"
                f"👀 Vues : "
                f"{deal['views']}<br>"
                f"❤️ Favoris : "
                f"{deal['favourites']}<br><br>"
            )

            html += (
                f"🛒 <b>Prix maximum conseillé : "
                f"{deal['max_purchase']:.2f} €</b><br><br>"
            )

            if url:
                html += (
                    f'<a href="{url}">'
                    f"Voir l'annonce"
                    f"</a>"
                )

            html += "</div>"

    if bundles:

        html += (
            "<h2>📦 Lots à vérifier manuellement</h2>"
        )

        for bundle in bundles:

            item = bundle["item"]
            domain = bundle["domain"]

            url = make_item_url(
                item,
                domain,
            )

            html += (
                "<div style="
                "'border:1px solid #ccc;"
                "padding:10px;"
                "margin:10px 0'>"
            )

            html += (
                f"<b>{item.get('title','')}</b><br>"
                f"Prix : {bundle['price']:.2f} €<br>"
                f"Pays : {domain}<br>"
            )

            if url:
                html += (
                    f'<a href="{url}">'
                    f"Voir le lot"
                    f"</a>"
                )

            html += "</div>"

    if not deals and not bundles:
        html += (
            "<h2>Aucune opportunité "
            "suffisamment intéressante.</h2>"
        )

    html += "</body></html>"

    message.attach(
        MIMEText(
            html,
            "html",
        )
    )

    try:
        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465,
        ) as server:

            server.login(
                EMAIL_FROM,
                EMAIL_PASSWORD,
            )

            server.sendmail(
                EMAIL_FROM,
                EMAIL_TO,
                message.as_string(),
            )

        print(
            "Email envoyé."
        )

    except Exception as exc:
        print(
            f"Erreur email : {exc}"
        )


# ============================================================
# DISCORD
# ============================================================

def notify_discord(
    deal,
):
    if not DISCORD_WEBHOOK_URL:
        return

    item = deal["item"]
    domain = deal["domain"]

    url = make_item_url(
        item,
        domain,
    )

    title = item.get(
        "title",
        "",
    )

    classification = deal[
        "classification"
    ]

    description = (
        f"{classification}\n\n"
        f"Prix achat : "
        f"{deal['purchase_price']:.2f} €\n"
        f"Prix prudent : "
        f"{deal['cautious_sale_price']:.2f} €\n"
        f"Prix probable : "
        f"{deal['probable_sale_price']:.2f} €\n"
        f"Bénéfice prudent : "
        f"{deal['cautious_profit']:.2f} €\n"
        f"Bénéfice probable : "
        f"{deal['probable_profit']:.2f} €\n\n"
        f"Prix max conseillé : "
        f"{deal['max_purchase']:.2f} €\n"
        f"Score : "
        f"{deal['score']}/100\n"
        f"Comparables : "
        f"{deal['comparables']}"
    )

    payload = {
        "embeds": [
            {
                "title": title[:256],
                "url": url or None,
                "description": description,
            }
        ]
    }

    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10,
        )

    except Exception as exc:
        print(
            f"Discord erreur : {exc}"
        )


# ============================================================
# SEEN
# ============================================================

SEEN_FILE = "seen_items.json"


def load_seen():
    try:
        with open(
            SEEN_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        if isinstance(
            data,
            list,
        ):
            return set(
                data
            )

        if isinstance(
            data,
            dict,
        ):
            result = set()

            for values in data.values():
                if isinstance(
                    values,
                    list,
                ):
                    result.update(
                        values
                    )

            return result

    except Exception:
        pass

    return set()


def save_seen(seen):
    with open(
        SEEN_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            list(seen),
            file,
        )


# ============================================================
# RAPPORT TERMINAL
# ============================================================

def print_deal(deal):
    item = deal["item"]

    print("\n" + "=" * 70)

    print(
        deal["classification"],
        f"SCORE {deal['score']}/100",
    )

    print(
        item.get(
            "title",
            "",
        )
    )

    print(
        f"Achat       : "
        f"{deal['purchase_price']:.2f} €"
    )

    print(
        f"Prudent     : "
        f"{deal['cautious_sale_price']:.2f} €"
    )

    print(
        f"Probable    : "
        f"{deal['probable_sale_price']:.2f} €"
    )

    print(
        f"Optimiste   : "
        f"{deal['optimistic_sale_price']:.2f} €"
    )

    print(
        f"Bénéfice prudent : "
        f"{deal['cautious_profit']:.2f} €"
    )

    print(
        f"Bénéfice probable : "
        f"{deal['probable_profit']:.2f} €"
    )

    print(
        f"Prix MAX conseillé : "
        f"{deal['max_purchase']:.2f} €"
    )

    print(
        f"Comparables : "
        f"{deal['comparables']}"
    )

    print(
        f"Variance    : "
        f"{deal['variance']:.1f}%"
    )

    print(
        f"Vues        : "
        f"{deal['views']}"
    )

    print(
        f"Favoris     : "
        f"{deal['favourites']}"
    )

    print(
        make_item_url(
            item,
            deal["domain"],
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "\n"
        "============================================\n"
        "       VINTED RESALE SCANNER V2\n"
        "============================================\n"
    )

    print(
        f"Budget simulé : "
        f"{STARTING_BUDGET:.2f} €"
    )

    seen = load_seen()

    all_deals = []
    all_bundles = []

    domains = DOMAINS[:]

    random.shuffle(
        domains
    )

    for domain in domains:

        deals, bundles = scan_domain(
            domain,
            seen,
            STARTING_BUDGET,
        )

        all_deals.extend(
            deals
        )

        all_bundles.extend(
            bundles
        )

        time.sleep(
            random.uniform(
                2,
                4,
            )
        )

    # --------------------------------------------------------
    # DEDUP
    # --------------------------------------------------------

    all_deals = dedupe_deals(
        all_deals
    )

    bundle_by_id = {}

    for bundle in all_bundles:

        item_id = bundle[
            "item"
        ].get("id")

        bundle_by_id[
            item_id
        ] = bundle

    all_bundles = list(
        bundle_by_id.values()
    )

    # --------------------------------------------------------
    # TRI
    # --------------------------------------------------------

    all_deals.sort(
        key=lambda deal: (
            -deal["score"],
            deal["purchase_price"],
        )
    )

    # --------------------------------------------------------
    # TERMINAL
    # --------------------------------------------------------

    print(
        "\n\n"
        "============================================"
    )

    print(
        f"{len(all_deals)} opportunités "
        f"retenues."
    )

    print(
        f"{len(all_bundles)} lots à vérifier."
    )

    print(
        "============================================"
    )

    for deal in all_deals[:20]:
        print_deal(
            deal
        )

    # --------------------------------------------------------
    # DISCORD
    # --------------------------------------------------------

    for deal in all_deals:

        if deal["score"] >= 70:
            notify_discord(
                deal
            )

    # --------------------------------------------------------
    # EMAIL
    # --------------------------------------------------------

    if (
        all_deals
        or all_bundles
    ):
        send_email(
            all_deals,
            all_bundles,
            STARTING_BUDGET,
        )

    # --------------------------------------------------------
    # SAUVEGARDE
    # --------------------------------------------------------

    save_seen(
        seen
    )

    print(
        "\nScan terminé."
    )


if __name__ == "__main__":
    main()
