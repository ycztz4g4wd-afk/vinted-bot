import os
import json
import time
import random
import statistics
import smtplib
import re
import html
import hashlib
from collections import Counter
from urllib.parse import urlparse

import requests

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ============================================================
# VINTED RESALE SCANNER V6
# ============================================================
#
# SPECIALISATION :
#
#   ⚽ FOOTBALL VINTAGE EUROPEEN
#   🏀 NBA VINTAGE
#
# Le bot NE cherche plus :
#   - Ralph Lauren
#   - Nike général
#   - sneakers
#   - streetwear général
#   - NFL
#   - MLB
#   - NHL
#   - basket non-NBA
#
# Le classement est volontairement strict.
#
# V6 :
#   - recherches jusqu'à 40 € pour conserver un marché large
#   - analyse / achat limitée à 18 €
#   - minimum 5 comparables
#   - diagnostic détaillé des rejets
#   - filtres vintage renforcés
#   - déduplication conservée
#   - email / Discord conservés
#
# ============================================================


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

TEAM_SEARCHES_PER_DOMAIN = 20

SEARCH_ROTATION_MINUTES = 60

MAX_EMAIL_DEALS = 25

MAX_DISCORD_ALERTS = 15

# Affiche chaque rejet individuellement si activé.
# Par défaut, seuls les compteurs de diagnostic sont affichés.
DIAGNOSTIC_VERBOSE = (
    os.environ.get(
        "VINTED_DIAGNOSTIC_VERBOSE",
        "0",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)


# ============================================================
# BUDGET / RENTABILITE
# ============================================================

STARTING_BUDGET = 20.0

# IMPORTANT :
# Ces prix concernent les RECHERCHES Vinted.
# On garde volontairement 40 € pour récupérer des comparables
# et avoir une meilleure vision du marché.
SEARCH_PRICE_MIN = 0.50
SEARCH_PRICE_MAX = 40.0

# Prix maximum d'un article que le bot accepte d'analyser
# comme opportunité d'achat.
MAX_ANALYSIS_PURCHASE_PRICE = 18.0

SHIPPING_COST_ESTIMATE = 5.0

BUYER_PROTECTION_PERCENT = 0.05
BUYER_PROTECTION_FIXED = 0.70

MIN_PROFIT_EUR = 6.0
MIN_SAFE_PROFIT_EUR = 8.0

# V5 : 5 comparables minimum au lieu de 8.
MIN_COMPARABLES = 5

# V6 : les comparables sont pondérés par proximité (équipe, joueur, année, variante).
MIN_RELEVANT_COMPARABLES = 5

MAX_BUDGET_USAGE_NORMAL = 0.40
MAX_BUDGET_USAGE_EXCEPTIONAL = 0.65


# ============================================================
# DIAGNOSTIC DES REJETS
# ============================================================

REJECTION_STATS = Counter()


def record_rejection(
    reason,
    item=None,
):

    REJECTION_STATS[reason] += 1

    if DIAGNOSTIC_VERBOSE and item:

        title = str(
            item.get(
                "title",
                "",
            )
        )

        print(
            f"[REJET] {reason} | "
            f"{title[:100]}"
        )


def reset_rejection_stats():

    REJECTION_STATS.clear()


def print_rejection_diagnostics():

    print(
        "\n"
        "=================================================="
    )

    print(
        "DIAGNOSTIC DES REJETS"
    )

    print(
        "=================================================="
    )

    if not REJECTION_STATS:

        print(
            "Aucun rejet enregistré."
        )

        return

    total = sum(
        REJECTION_STATS.values()
    )

    print(
        f"Total rejets analysés : {total}"
    )

    for reason, count in (
        REJECTION_STATS.most_common()
    ):

        percentage = (
            count
            / total
            * 100
            if total
            else 0
        )

        print(
            f"- {reason}: "
            f"{count} "
            f"({percentage:.1f}%)"
        )

    print(
        "=================================================="
    )


# ============================================================
# TAILLES
# ============================================================

ACCEPTED_SIZES = {
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "2XL",
    "3XL",
}

ACCEPTED_SHOE_SIZES = set()

SIZE_IDS_FILTER = [
    3,
    4,
    5,
    6,
    7,
    61,
    62,
    63,
]


# ============================================================
# ETATS ACCEPTES
# ============================================================

ACCEPTED_CONDITION_KEYWORDS = [

    # Français
    "très bon état",
    "tres bon etat",
    "neuf sans étiquette",
    "neuf sans etiquette",
    "neuf avec étiquette",
    "neuf avec etiquette",

    # Anglais
    "very good",
    "new without tags",
    "new with tags",

    # Allemand
    "sehr gut",
    "neu ohne etikett",
    "neu mit etikett",

    # Espagnol
    "muy bueno",
    "nuevo sin etiquetas",
    "nuevo con etiquetas",

    # Italien
    "molto buono",
    "nuovo senza etichette",
    "nuovo con etichette",

    # Néerlandais
    "zeer goed",
    "nieuw zonder label",
    "nieuw met label",
]


# ============================================================
# NORMALISATION
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = str(text).casefold().strip()

    replacements = {
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "à": "a",
        "â": "a",
        "ä": "a",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ö": "o",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ç": "c",
        "á": "a",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "ß": "ss",
    }

    for old, new in replacements.items():
        text = text.replace(
            old,
            new,
        )

    # Uniformisation de quelques séparateurs.
    text = text.replace(
        "–",
        "-",
    )
    text = text.replace(
        "—",
        "-",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text


NORMALIZED_ACCEPTED_CONDITIONS = {
    normalize_text(condition)
    for condition in ACCEPTED_CONDITION_KEYWORDS
}


# ============================================================
# VINTAGE
# ============================================================

VINTAGE_TERMS = [

    "vintage",
    "retro",
    "rétro",
    "old school",
    "oldschool",
    "classic",
    "archive",
    "archival",
    "throwback",
    "heritage",
    "historical",
    "classic jersey",
    "classic shirt",
    "retro shirt",
    "retro jersey",
    "old jersey",
    "old shirt",

    "90s",
    "90's",
    "90 s",

    "00s",
    "00's",
    "00 s",

    "2000s",
    "2000's",

    "80s",
    "80's",
    "80 s",

    "70s",
    "70's",
    "70 s",

    "60s",
    "60's",

    "années 80",
    "annees 80",
    "années 90",
    "annees 90",
    "années 2000",
    "annees 2000",

    "anos 90",
    "anos 2000",
    "años 90",
    "años 2000",
]


# Années explicites historiquement plausibles pour du vintage.
VINTAGE_YEAR_RE = re.compile(
    r"\b("
    r"19[5-9]\d"
    r"|200\d"
    r"|2010"
    r")\b"
)


# Formats de saisons fréquents :
# 98/99, 1998/99, 99-00, 2000-01, etc.
VINTAGE_SEASON_RE = re.compile(
    r"\b("
    r"(?:19[5-9]\d|200\d|201[0-2])"
    r"\s*[/\-]\s*\d{2,4}"
    r"|"
    r"\d{2}\s*[/\-]\s*\d{2}"
    r")\b"
)


def is_vintage_item(item):

    text = get_item_search_text(
        item
    )

    if contains_any_phrase(
        text,
        VINTAGE_TERMS,
    ):
        return True

    if VINTAGE_YEAR_RE.search(
        text
    ):
        return True

    if VINTAGE_SEASON_RE.search(
        text
    ):
        return True

    return False


# ============================================================
# ETAT
# ============================================================

def get_item_condition_text(item):

    fields = [
        "status",
        "status_title",
        "condition",
        "condition_title",
        "condition_name",
    ]

    values = []

    for field in fields:

        value = item.get(field)

        if value:
            values.append(
                str(value)
            )

    return " ".join(values)


def is_accepted_condition(item):

    condition_text = get_item_condition_text(
        item
    )

    if not condition_text:
        return False

    normalized = normalize_text(
        condition_text
    )

    return any(
        accepted == normalized
        or accepted in normalized
        for accepted in NORMALIZED_ACCEPTED_CONDITIONS
    )


# ============================================================
# ENFANTS
# ============================================================

KIDS_INDICATOR_RE = re.compile(
    r"\b("
    r"\d+\s*(?:ans?|annees?|years?|yrs?|"
    r"mois|months?|jahre?|jahr|anni|anno|"
    r"anos?|años|meses|mes)"
    r"|enfant|enfants|bebe|bebes|baby|babys|"
    r"babies|kids?|"
    r"garcon|garcons|fille|filles|"
    r"boys?|girls?|junior|toddler|"
    r"infant|child|children|"
    r"bambino|bambina|nino|nina|"
    r"ninos|ninas|kind|kinder"
    r")\b",
    re.IGNORECASE,
)


def looks_like_kids_item(
    title,
    size_title=None,
):

    combined = (
        f"{title or ''} "
        f"{size_title or ''}"
    )

    normalized = normalize_text(
        combined
    )

    return bool(
        KIDS_INDICATOR_RE.search(
            normalized
        )
    )


# ============================================================
# CONTREFAÇONS
# ============================================================

STRONG_COUNTERFEIT_KEYWORDS = [

    "fake",
    "counterfeit",
    "counterfeit jersey",
    "counterfeit shirt",

    "1:1",
    "aaa quality",
    "aaa replica",

    "thai quality",
    "thai version",
    "thai jersey",

    "not original",
    "not authentic",

    "nicht original",
    "non original",
    "non originale",

    "sin original",
    "senza originale",

    "unofficial",

    "imitation",
    "imitacion",
    "imitazione",

    "kopie",
    "copie",
    "copia",

    "dupe",

    "inspired by",
    "inspire",
    "inspiré",
    "inspirée",

    "repro",
    "reproduction",

    "bootleg",
]


def looks_like_replica(
    title,
    description="",
):

    text = normalize_text(
        f"{title or ''} {description or ''}"
    )

    return any(
        normalize_text(keyword) in text
        for keyword in STRONG_COUNTERFEIT_KEYWORDS
    )


# ============================================================
# TEXTE ARTICLE
# ============================================================

def get_item_search_text(item):

    fields = [
        "title",
        "brand_title",
        "catalog_title",
    ]

    values = []

    for field in fields:

        value = item.get(field)

        if value:
            values.append(
                str(value)
            )

    return normalize_text(
        " ".join(values)
    )


def get_description(item):

    return str(
        item.get("description")
        or item.get("description_text")
        or ""
    )


# ============================================================
# PHRASES
# ============================================================

def contains_phrase(
    text,
    phrase,
):

    text = normalize_text(text)
    phrase = normalize_text(phrase)

    if not phrase:
        return False

    return re.search(
        rf"(?<!\w){re.escape(phrase)}(?!\w)",
        text,
    ) is not None


def contains_any_phrase(
    text,
    phrases,
):

    return any(
        contains_phrase(
            text,
            phrase,
        )
        for phrase in phrases
    )


# ============================================================
# FOOTBALL
# ============================================================

FOOTBALL_GARMENT_TERMS = [

    "maillot",
    "maillot de foot",
    "maillot football",

    "jersey",
    "shirt",
    "football shirt",
    "football jersey",
    "soccer jersey",
    "soccer shirt",
    "football kit",

    "camiseta futbol",
    "camiseta de futbol",

    "maglia calcio",
    "maglia da calcio",

    "trikot",

    "voetbalshirt",
]


FOOTBALL_CONTEXT_TERMS = [

    "football",
    "soccer",
    "futbol",
    "calcio",
    "trikot",
    "voetbal",
    "premier league",
    "la liga",
    "ligue 1",
    "serie a",
    "bundesliga",
    "champions league",
    "uefa",
    "europa league",
]


# ============================================================
# EQUIPES NATIONALES EUROPEENNES
# ============================================================

EUROPEAN_NATIONAL_TEAMS = {

    "france": [
        "france",
        "edf",
        "les bleus",
    ],

    "italy": [
        "italy",
        "italie",
        "azzurri",
    ],

    "germany": [
        "germany",
        "allemagne",
        "deutschland",
    ],

    "spain": [
        "spain",
        "espagne",
        "la roja",
    ],

    "england": [
        "england",
        "angleterre",
        "three lions",
    ],

    "netherlands": [
        "netherlands",
        "pays bas",
        "holland",
        "oranje",
    ],

    "portugal": [
        "portugal",
    ],

    "belgium": [
        "belgium",
        "belgique",
        "red devils",
    ],

    "croatia": [
        "croatia",
        "croatie",
    ],
    "scotland": ["scotland", "ecosse", "tartan army"],
    "wales": ["wales", "pays de galles", "cymru"],
    "ireland": ["republic of ireland", "ireland", "irlande"],
    "switzerland": ["switzerland", "suisse", "schweiz"],
    "austria": ["austria", "autriche", "osterreich"],
    "denmark": ["denmark", "danemark", "danmark"],
    "sweden": ["sweden", "suede", "sverige"],
    "norway": ["norway", "norvege", "norge"],
    "poland": ["poland", "pologne", "polska"],
    "czech republic": ["czech republic", "republique tcheque", "czechia"],
    "romania": ["romania", "roumanie"],
    "turkey": ["turkey", "turquie", "turkiye"],
}

# ============================================================
# CLUBS EUROPEENS CONNUS
# ============================================================

EUROPEAN_CLUBS = {

    "manchester united": [
        "manchester united",
        "man utd",
        "man united",
        "mufc",
    ],

    "manchester city": [
        "manchester city",
        "man city",
        "mcfc",
    ],

    "liverpool": [
        "liverpool",
        "lfc",
    ],

    "arsenal": [
        "arsenal",
    ],

    "chelsea": [
        "chelsea",
    ],

    "tottenham": [
        "tottenham",
        "spurs",
    ],

    "real madrid": [
        "real madrid",
    ],

    "barcelona": [
        "barcelona",
        "barcelone",
        "fc barcelona",
        "barca",
    ],

    "atletico madrid": [
        "atletico madrid",
        "atlético madrid",
    ],

    "bayern munich": [
        "bayern munich",
        "bayern munchen",
        "bayern",
    ],

    "borussia dortmund": [
        "borussia dortmund",
        "dortmund",
        "bvb",
    ],

    "bayer leverkusen": [
        "bayer leverkusen",
        "leverkusen",
    ],

    "ac milan": [
        "ac milan",
        "milan ac",
    ],

    "inter milan": [
        "inter milan",
        "internazionale",
    ],

    "juventus": [
        "juventus",
        "juve",
    ],

    "roma": [
        "as roma",
        "roma",
    ],

    "napoli": [
        "napoli",
    ],

    "psg": [
        "psg",
        "paris saint germain",
        "paris sg",
    ],

    "marseille": [
        "marseille",
        "olympique marseille",
        "om",
    ],

    "lyon": [
        "lyon",
        "olympique lyonnais",
        "ol",
    ],

    "ajax": [
        "ajax",
        "afc ajax",
    ],

    "psv": [
        "psv",
        "psv eindhoven",
    ],

    "feyenoord": [
        "feyenoord",
    ],

    "benfica": [
        "benfica",
        "sl benfica",
    ],

    "porto": [
        "porto",
        "fc porto",
    ],

    "celtic": [
        "celtic",
    ],

    "rangers": [
        "rangers",
        "glasgow rangers",
    ],

    "galatasaray": [
        "galatasaray",
    ],

    "fenerbahce": [
        "fenerbahce",
        "fenerbahçe",
    ],

    "anderlecht": [
        "anderlecht",
    ],

    "club brugge": [
        "club brugge",
    ],

    "olympiacos": [
        "olympiacos",
        "olympiakos",
    ],

    "west ham": ["west ham", "west ham united", "whu"],
    "everton": ["everton", "efc"],
    "aston villa": ["aston villa", "avfc"],
    "newcastle": ["newcastle", "newcastle united", "nufc"],
    "leeds": ["leeds", "leeds united"],
    "nottingham forest": ["nottingham forest", "nottm forest"],
    "ac milan": ["ac milan", "milan ac", "milan"],
    "fiorentina": ["fiorentina", "acf fiorentina"],
    "lazio": ["lazio", "ss lazio"],
    "atalanta": ["atalanta", "atalanta bergamo"],
    "sevilla": ["sevilla", "sevilla fc"],
    "valencia": ["valencia", "valencia cf"],
    "villarreal": ["villarreal", "villarreal cf"],
    "athletic bilbao": ["athletic bilbao", "athletic club"],
    "monaco": ["as monaco", "monaco"],
    "bordeaux": ["bordeaux", "girondins bordeaux"],
    "saint etienne": ["saint etienne", "asse", "st etienne"],
    "lens": ["rc lens", "lens"],
    "nantes": ["fc nantes", "nantes"],
    "psv": ["psv", "psv eindhoven"],
    "sporting": ["sporting cp", "sporting lisbon", "sporting portugal"],
    "braga": ["sporting braga", "braga"],
    "besiktas": ["besiktas", "besiktas jk"],
    "fenerbahce": ["fenerbahce", "fenerbahçe"],
    "dinamo zagreb": ["dinamo zagreb"],
    "red star": ["red star belgrade", "etoile rouge", "crvena zvezda"],
    "shakhtar": ["shakhtar donetsk", "shakhtar"],
}


EUROPEAN_TEAM_ALIASES = {}

EUROPEAN_TEAM_ALIASES.update(
    EUROPEAN_NATIONAL_TEAMS
)

EUROPEAN_TEAM_ALIASES.update(
    EUROPEAN_CLUBS
)


# ============================================================
# SPORTS NON AUTORISES
# ============================================================

NON_FOOTBALL_SPORTS = [

    "nfl",
    "american football",
    "football americain",

    "nba",
    "basketball",

    "mlb",
    "baseball",

    "nhl",
    "hockey",
]


# ============================================================
# EQUIPE DETECTEE
# ============================================================

def get_matching_football_teams(
    text,
):

    matches = set()

    for team_name, aliases in EUROPEAN_TEAM_ALIASES.items():

        if contains_any_phrase(
            text,
            aliases,
        ):
            matches.add(
                team_name
            )

    return matches


def has_known_european_team(
    text,
):

    return bool(
        get_matching_football_teams(
            text
        )
    )


# ============================================================
# MAILLOT FOOT
# ============================================================

def has_football_garment(
    text,
):

    return contains_any_phrase(
        text,
        FOOTBALL_GARMENT_TERMS,
    )


def has_football_context(
    text,
):

    return contains_any_phrase(
        text,
        FOOTBALL_CONTEXT_TERMS,
    )


def is_football_item(
    item,
):

    text = get_item_search_text(
        item
    )

    if contains_any_phrase(
        text,
        NON_FOOTBALL_SPORTS,
    ):
        return False

    if not is_vintage_item(item):
        return False

    if not has_known_european_team(text):
        return False

    if not has_football_garment(text):
        return False

    return True


# ============================================================
# NBA
# ============================================================

NBA_GARMENT_TERMS = [

    "nba jersey",
    "nba maillot",

    "basketball jersey",
    "basket jersey",

    "jersey",
    "maillot",
]


NBA_TEAM_ALIASES = {

    "lakers": [
        "los angeles lakers",
        "la lakers",
        "lakers",
    ],

    "bulls": [
        "chicago bulls",
        "bulls",
    ],

    "celtics": [
        "boston celtics",
        "celtics",
    ],

    "warriors": [
        "golden state warriors",
        "warriors",
    ],

    "nets": [
        "brooklyn nets",
        "nets",
    ],

    "knicks": [
        "new york knicks",
        "knicks",
    ],

    "heat": [
        "miami heat",
        "heat",
    ],

    "spurs": [
        "san antonio spurs",
        "spurs",
    ],

    "mavericks": [
        "dallas mavericks",
        "mavericks",
        "dallas mavs",
    ],

    "pistons": [
        "detroit pistons",
        "pistons",
    ],

    "raptors": [
        "toronto raptors",
        "raptors",
    ],

    "76ers": [
        "philadelphia 76ers",
        "76ers",
        "sixers",
    ],

    "rockets": [
        "houston rockets",
        "rockets",
    ],

    "suns": [
        "phoenix suns",
        "suns",
    ],

    "supersonics": [
        "seattle supersonics",
        "supersonics",
    ],

    "bulls_90s": [
        "chicago bulls",
        "bulls",
    ],

    "cavaliers": ["cleveland cavaliers", "cavaliers"],
    "bucks": ["milwaukee bucks", "bucks"],
    "blazers": ["portland trail blazers", "portland blazers", "blazers"],
    "jazz": ["utah jazz", "jazz"],
    "nuggets": ["denver nuggets", "nuggets"],
    "grizzlies": ["memphis grizzlies", "grizzlies"],
    "hawks": ["atlanta hawks", "hawks"],
    "pacers": ["indiana pacers", "pacers"],
    "hornets": ["charlotte hornets", "hornets"],
    "kings": ["sacramento kings", "kings", "kansas city kings"],
    "clippers": ["los angeles clippers", "la clippers", "clippers", "san diego clippers"],
    "magic": ["orlando magic", "magic"],
    "timberwolves": ["minnesota timberwolves", "timberwolves"],
    "wizards": ["washington wizards", "wizards", "washington bullets"],
    "bullets": ["washington bullets", "bullets"],
    "supersonics_old": ["seattle supersonics", "supersonics"],
}


def get_matching_nba_teams(
    text,
):

    matches = set()

    for team_name, aliases in NBA_TEAM_ALIASES.items():

        if contains_any_phrase(
            text,
            aliases,
        ):
            matches.add(
                team_name
            )

    return matches


def has_known_nba_team(
    text,
):

    return bool(
        get_matching_nba_teams(
            text
        )
    )


def is_nba_item(
    item,
):

    text = get_item_search_text(
        item
    )

    if not is_vintage_item(item):
        return False

    if contains_any_phrase(
        text,
        [
            "nfl",
            "american football",
            "football americain",
            "mlb",
            "baseball",
            "nhl",
            "hockey",
        ],
    ):
        return False

    team = has_known_nba_team(
        text
    )

    nba = contains_phrase(
        text,
        "nba",
    )

    garment = contains_any_phrase(
        text,
        NBA_GARMENT_TERMS,
    )

    if not garment:
        return False

    if team:
        return True

    if nba:
        return True

    return False


# ============================================================
# CLASSIFICATION SPORT
# ============================================================

def classify_sport(
    item,
):

    football = is_football_item(
        item
    )

    nba = is_nba_item(
        item
    )

    if football and not nba:
        return "football"

    if nba and not football:
        return "nba"

    return None


# ============================================================
# MARQUES / RISQUE
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
    "travis scott",
}


def is_hype_item(
    item,
):

    brand = normalize_text(
        item.get(
            "brand_title"
        )
        or ""
    )

    normalized_brands = {
        normalize_text(value)
        for value in HYPE_BRANDS
    }

    if brand in normalized_brands:
        return True

    title = get_item_search_text(
        item
    )

    if any(
        normalize_text(brand_name) in title
        for brand_name in HYPE_BRANDS
    ):
        return True

    return any(
        normalize_text(model) in title
        for model in HYPE_MODELS
    )


# ============================================================
# PERCENTILES
# ============================================================

def percentile(
    values,
    pct,
):

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

    fraction = (
        position - lower
    )

    return (
        values[lower] * (1 - fraction)
        + values[upper] * fraction
    )


def remove_outliers(
    prices,
):

    if len(prices) < 5:
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

    if len(filtered) < 5:
        return prices

    return filtered


# ============================================================
# SCORE
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

    if comparable_count >= 40:
        score += 15

    elif comparable_count >= 25:
        score += 13

    elif comparable_count >= 15:
        score += 10

    elif comparable_count >= 10:
        score += 7

    elif comparable_count >= 5:
        score += 4

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

    if engagement <= 2:
        score += 10

    elif engagement <= 5:
        score += 8

    elif engagement <= 10:
        score += 6

    elif engagement <= 20:
        score += 3

    sport = classify_sport(item)

    if sport == "football":
        score += 8

    elif sport == "nba":
        score += 8

    text = get_item_search_text(item)

    if (
        sport == "football"
        and has_known_european_team(text)
    ):
        score += 5

    if (
        sport == "nba"
        and has_known_nba_team(text)
    ):
        score += 5

    if is_hype_item(item):
        score += 3
    else:
        score += 6

    # V6 : bonus de confiance quand le marché est fourni et cohérent.
    if comparable_count >= 20 and variance <= 30:
        score += 5
    elif comparable_count >= 10 and variance <= 35:
        score += 3

    # V6 : forte décote par rapport au marché = signal de deal, sans
    # laisser une décote extrême gonfler le score sans limite.
    if probable_sale_price > 0:
        discount = 1 - (purchase_price / probable_sale_price)
        if discount >= 0.65:
            score += 6
        elif discount >= 0.50:
            score += 4
        elif discount >= 0.35:
            score += 2

    if purchase_price <= 5:
        score += 7

    elif purchase_price <= 8:
        score += 5

    elif purchase_price <= 12:
        score += 3

    title_lower = normalize_text(title)

    useful_words = [
        "vintage",
        "original",
        "authentique",
        "authentic",
        "oversize",
        "rare",
        "archive",
        "retro",
        "football",
        "jersey",
        "maillot",
        "nba",
        "basketball",
        "throwback",
    "heritage",
    "historical",
    "classic jersey",
    "classic shirt",
    "retro shirt",
    "retro jersey",
    "old jersey",
    "old shirt",
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

    if (
        score >= 80
        and cautious_profit >= MIN_SAFE_PROFIT_EUR
    ):
        return "🟢 ACHETER"

    if (
        score >= 68
        and probable_profit >= MIN_PROFIT_EUR
    ):
        return "🟡 BON PLAN"

    if score >= 55:
        return "🟠 À ÉTUDIER"

    return "⚫ À ÉVITER"


# ============================================================
# PRIX MAXIMUM
# ============================================================

def calculate_max_purchase_price(
    cautious_sale_price,
    budget,
    score,
):

    if not cautious_sale_price:
        return 0

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

    max_budget_price = (
        budget
        * MAX_BUDGET_USAGE_NORMAL
    )

    max_price = min(
        max_price,
        max_budget_price,
    )

    return round(
        max(
            0,
            max_price,
        ),
        2,
    )


# ============================================================
# SESSION
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def get_session(
    domain,
):

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    session.vinted_rate_limited = False

    try:

        session.get(
            f"https://www.{domain}/",
            timeout=15,
        )

    except Exception as exc:

        print(
            f"[{domain}] "
            f"Session initiale impossible: "
            f"{exc}"
        )

    return session


# ============================================================
# REQUETE VINTED
# ============================================================

def request_vinted(
    session,
    url,
    params,
    domain,
    context,
):

    for attempt in range(2):

        try:

            response = session.get(
                url,
                params=params,
                timeout=15,
            )

            if response.status_code == 429:

                session.vinted_rate_limited = True

                print(
                    f"[{domain}] "
                    f"Rate limit sur {context}. "
                    f"Arrêt de ce domaine pour ce run."
                )

                return None

            if (
                response.status_code >= 500
                and attempt == 0
            ):

                time.sleep(
                    random.uniform(
                        2,
                        4,
                    )
                )

                continue

            if response.status_code != 200:

                print(
                    f"[{domain}] "
                    f"{context}: HTTP "
                    f"{response.status_code}"
                )

                return None

            return response

        except Exception as exc:

            if attempt == 0:

                time.sleep(
                    random.uniform(
                        2,
                        4,
                    )
                )

                continue

            print(
                f"[{domain}] "
                f"Erreur {context}: "
                f"{exc}"
            )

            return None

    return None


# ============================================================
# RECHERCHES GENERIQUES
# ============================================================

FOOTBALL_GENERIC_SEARCHES = [

    "maillot foot vintage",
    "maillot football vintage",
    "maillot de foot vintage",
    "football shirt vintage",
    "football jersey vintage",
    "vintage football shirt",
    "maillot foot retro",
    "maillot football retro",

    "camiseta futbol vintage",
    "maglia calcio vintage",
    "fußball trikot vintage",
]


NBA_GENERIC_SEARCHES = [

    "NBA vintage jersey",
    "NBA maillot vintage",
    "NBA basketball jersey vintage",
    "basketball jersey vintage NBA",
    "NBA jersey retro",
]


# ============================================================
# RECHERCHES EQUIPES EUROPEENNES
# ============================================================

FOOTBALL_TEAM_SEARCHES = [

    ("football", "France vintage jersey"),
    ("football", "Italy vintage jersey"),
    ("football", "Germany vintage jersey"),
    ("football", "Spain vintage jersey"),
    ("football", "England vintage jersey"),
    ("football", "Netherlands vintage jersey"),
    ("football", "Portugal vintage jersey"),
    ("football", "Belgium vintage jersey"),
    ("football", "Croatia vintage jersey"),

    ("football", "Manchester United vintage jersey"),
    ("football", "Manchester City vintage jersey"),
    ("football", "Liverpool vintage jersey"),
    ("football", "Arsenal vintage jersey"),
    ("football", "Chelsea vintage jersey"),
    ("football", "Tottenham vintage jersey"),

    ("football", "Real Madrid vintage jersey"),
    ("football", "Barcelona vintage jersey"),
    ("football", "Atletico Madrid vintage jersey"),

    ("football", "Bayern Munich vintage jersey"),
    ("football", "Borussia Dortmund vintage jersey"),
    ("football", "Bayer Leverkusen vintage jersey"),

    ("football", "AC Milan vintage jersey"),
    ("football", "Inter Milan vintage jersey"),
    ("football", "Juventus vintage jersey"),
    ("football", "AS Roma vintage jersey"),
    ("football", "Napoli vintage jersey"),

    ("football", "PSG vintage jersey"),
    ("football", "Marseille vintage jersey"),
    ("football", "Lyon vintage jersey"),

    ("football", "Ajax vintage jersey"),
    ("football", "PSV vintage jersey"),
    ("football", "Feyenoord vintage jersey"),

    ("football", "Benfica vintage jersey"),
    ("football", "Porto vintage jersey"),

    ("football", "Celtic vintage jersey"),
    ("football", "Rangers vintage jersey"),

    ("football", "Galatasaray vintage jersey"),
    ("football", "Fenerbahce vintage jersey"),

    ("football", "Anderlecht vintage jersey"),
    ("football", "Club Brugge vintage jersey"),

    ("football", "Olympiacos vintage jersey"),
]


# ============================================================
# RECHERCHES NBA
# ============================================================

NBA_TEAM_SEARCHES = [

    ("nba", "Los Angeles Lakers vintage jersey"),
    ("nba", "Chicago Bulls vintage jersey"),
    ("nba", "Boston Celtics vintage jersey"),
    ("nba", "Golden State Warriors vintage jersey"),
    ("nba", "New York Knicks vintage jersey"),
    ("nba", "Miami Heat vintage jersey"),
    ("nba", "San Antonio Spurs vintage jersey"),
    ("nba", "Dallas Mavericks vintage jersey"),
    ("nba", "Detroit Pistons vintage jersey"),
    ("nba", "Toronto Raptors vintage jersey"),
    ("nba", "Philadelphia 76ers vintage jersey"),
    ("nba", "Houston Rockets vintage jersey"),
    ("nba", "Phoenix Suns vintage jersey"),
    ("nba", "Seattle Supersonics vintage jersey"),
    ("nba", "Brooklyn Nets vintage jersey"),
]


# ============================================================
# PLAN DE RECHERCHE
# ============================================================

def build_team_search_plan():

    football = FOOTBALL_TEAM_SEARCHES[:]
    nba = NBA_TEAM_SEARCHES[:]

    plan = []

    max_length = max(
        len(football),
        len(nba),
    )

    for index in range(
        max_length
    ):

        if index < len(football):
            plan.append(
                football[index]
            )

        if index < len(nba):
            plan.append(
                nba[index]
            )

    return plan


TEAM_SEARCH_PLAN = build_team_search_plan()

# V6 : pool élargi de recherches pour réduire les "équipes inconnues".
FOOTBALL_TEAM_SEARCHES.extend([
    ("football", "West Ham vintage jersey"),
    ("football", "Everton vintage jersey"),
    ("football", "Newcastle vintage jersey"),
    ("football", "Leeds United vintage jersey"),
    ("football", "Aston Villa vintage jersey"),
    ("football", "Fiorentina vintage jersey"),
    ("football", "Lazio vintage jersey"),
    ("football", "Sevilla vintage jersey"),
    ("football", "Valencia vintage jersey"),
    ("football", "AS Monaco vintage jersey"),
    ("football", "Saint Etienne vintage jersey"),
    ("football", "Sporting Lisbon vintage jersey"),
    ("football", "Besiktas vintage jersey"),
])

NBA_TEAM_SEARCHES.extend([
    ("nba", "Cleveland Cavaliers vintage jersey"),
    ("nba", "Milwaukee Bucks vintage jersey"),
    ("nba", "Portland Trail Blazers vintage jersey"),
    ("nba", "Utah Jazz vintage jersey"),
    ("nba", "Denver Nuggets vintage jersey"),
    ("nba", "Atlanta Hawks vintage jersey"),
    ("nba", "Indiana Pacers vintage jersey"),
    ("nba", "Sacramento Kings vintage jersey"),
    ("nba", "Washington Bullets vintage jersey"),
    ("nba", "Los Angeles Clippers vintage jersey"),
])


# Rebuild after extension.
TEAM_SEARCH_PLAN = build_team_search_plan()


def select_search_plan(
    domain,
):

    plan = []

    generic = []

    for keyword in FOOTBALL_GENERIC_SEARCHES:

        generic.append(
            (
                "football",
                keyword,
            )
        )

    for keyword in NBA_GENERIC_SEARCHES:

        generic.append(
            (
                "nba",
                keyword,
            )
        )

    random.shuffle(
        generic
    )

    plan.extend(
        generic
    )

    if TEAM_SEARCH_PLAN:

        current_slot = int(
            time.time()
            / (
                SEARCH_ROTATION_MINUTES
                * 60
            )
        )

        domain_hash = int(
            hashlib.sha1(
                domain.encode(
                    "utf-8"
                )
            ).hexdigest(),
            16,
        )

        offset = (
            domain_hash
            + current_slot
            * TEAM_SEARCHES_PER_DOMAIN
        ) % len(
            TEAM_SEARCH_PLAN
        )

        for index in range(
            TEAM_SEARCHES_PER_DOMAIN
        ):

            position = (
                offset
                + index
            ) % len(
                TEAM_SEARCH_PLAN
            )

            category, keyword = (
                TEAM_SEARCH_PLAN[position]
            )

            plan.append(
                (
                    category,
                    keyword,
                )
            )

    result = []
    seen = set()

    for category, keyword in plan:

        key = (
            category,
            normalize_text(keyword),
        )

        if key in seen:
            continue

        seen.add(key)

        result.append(
            (
                category,
                keyword,
            )
        )

    return result


# ============================================================
# RECHERCHE VINTED
# ============================================================

def search_vinted(
    session,
    domain,
    keyword,
    category,
):

    params = {

        "search_text": keyword,

        # IMPORTANT :
        # on garde 40 € pour récupérer les comparables.
        "price_to": SEARCH_PRICE_MAX,

        "price_from": SEARCH_PRICE_MIN,

        "order": "newest_first",

        "per_page": 20,

        "currency": "EUR",
    }

    params["size_ids[]"] = SIZE_IDS_FILTER

    response = request_vinted(
        session,
        f"https://www.{domain}/api/v2/catalog/items",
        params,
        domain,
        f"recherche [{category}] {keyword}",
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
            f"JSON invalide: "
            f"{exc}"
        )

        return []


# ============================================================
# IDENTITE / PHOTO / VENDEUR
# ============================================================

def get_seller_identifier(
    item,
):

    possible_user_fields = [
        "user",
        "user_dto",
    ]

    for field in possible_user_fields:

        user = item.get(field)

        if isinstance(
            user,
            dict,
        ):

            value = (
                user.get("id")
                or user.get("login")
                or user.get("username")
            )

            if value:
                return str(value)

    value = (
        item.get("user_id")
        or item.get("seller_id")
        or ""
    )

    return str(value)


def get_photo_identifier(
    item,
):

    photo = item.get("photo")

    if isinstance(
        photo,
        dict,
    ):

        value = (
            photo.get("url")
            or photo.get("full_size_url")
            or photo.get("high_resolution_url")
        )

        if value:
            return str(value)

    photos = item.get("photos")

    if isinstance(
        photos,
        list,
    ):

        for photo_data in photos:

            if not isinstance(
                photo_data,
                dict,
            ):
                continue

            value = (
                photo_data.get("url")
                or photo_data.get("full_size_url")
                or photo_data.get("high_resolution_url")
            )

            if value:
                return str(value)

    return ""


def normalize_photo_identifier(
    value,
):

    if not value:
        return ""

    try:

        parsed = urlparse(value)

        path = parsed.path

        return normalize_text(path)

    except Exception:

        return normalize_text(value)


# ============================================================
# FINGERPRINT STABLE
# ============================================================

def get_stable_fingerprint(
    item,
):

    title = normalize_text(
        item.get("title")
        or ""
    )

    brand = normalize_text(
        item.get("brand_title")
        or ""
    )

    size = normalize_text(
        item.get("size_title")
        or ""
    )

    seller = normalize_text(
        get_seller_identifier(item)
    )

    photo = normalize_photo_identifier(
        get_photo_identifier(item)
    )

    if photo and seller:

        raw = "|".join(
            [
                "photo",
                photo,
                seller,
                size,
            ]
        )

    elif photo:

        raw = "|".join(
            [
                "photo",
                photo,
                title,
                brand,
                size,
            ]
        )

    else:

        raw = "|".join(
            [
                "text",
                title,
                brand,
                size,
                seller,
            ]
        )

    return (
        "stable:"
        + hashlib.sha1(
            raw.encode("utf-8")
        ).hexdigest()
    )


# ============================================================
# ID LISTING
# ============================================================

def get_listing_id(
    item,
):

    item_id = str(
        item.get("id")
        or ""
    ).strip()

    if item_id:
        return "id:" + item_id

    url = str(
        item.get("url")
        or item.get("path")
        or ""
    ).strip()

    if url:
        return (
            "url:"
            + normalize_text(url)
        )

    return get_stable_fingerprint(item)


# ============================================================
# COMPARABLES CACHE
# ============================================================

COMPARABLE_CACHE = {}


def get_comparable_cache_key(
    domain,
    item,
):

    sport = classify_sport(item)

    brand_id = (
        item.get("brand_dto") or {}
    ).get("id")

    catalog_id = item.get(
        "catalog_id"
    )

    title = normalize_text(
        item.get(
            "title",
            "",
        )
    )

    return (
        domain,
        sport,
        str(brand_id or ""),
        str(catalog_id or ""),
        title,
    )


# ============================================================
# COMPARABLES
# ============================================================

def comparable_matches_target(
    target,
    comparable,
    sport,
):

    if classify_sport(comparable) != sport:
        return False

    if not is_vintage_item(comparable):
        return False

    comparable_condition = (
        get_item_condition_text(comparable)
    )

    if (
        comparable_condition
        and not is_accepted_condition(comparable)
    ):
        return False

    target_text = get_item_search_text(target)
    comparable_text = get_item_search_text(comparable)

    if sport == "football":

        target_teams = (
            get_matching_football_teams(
                target_text
            )
        )

        comparable_teams = (
            get_matching_football_teams(
                comparable_text
            )
        )

        if target_teams:

            if not (
                target_teams
                & comparable_teams
            ):
                return False

    if sport == "nba":

        target_teams = (
            get_matching_nba_teams(
                target_text
            )
        )

        comparable_teams = (
            get_matching_nba_teams(
                comparable_text
            )
        )

        if target_teams:

            if not (
                target_teams
                & comparable_teams
            ):
                return False

    return True


def comparable_relevance_score(target, comparable, sport):
    """Score 0-100 de proximité entre une annonce et un comparable."""
    target_text = get_item_search_text(target)
    comp_text = get_item_search_text(comparable)
    score = 0.0

    if sport == "football":
        tt = get_matching_football_teams(target_text)
        ct = get_matching_football_teams(comp_text)
    else:
        tt = get_matching_nba_teams(target_text)
        ct = get_matching_nba_teams(comp_text)

    if tt and ct and tt & ct:
        score += 45
    elif tt and ct:
        return 0

    # Année/saison : un écart faible est préférable.
    ty = [int(x) for x in VINTAGE_YEAR_RE.findall(target_text)]
    cy = [int(x) for x in VINTAGE_YEAR_RE.findall(comp_text)]
    if ty and cy:
        gap = min(abs(a-b) for a in ty for b in cy)
        if gap == 0: score += 30
        elif gap <= 2: score += 24
        elif gap <= 5: score += 16
        elif gap <= 10: score += 7
    else:
        score += 5

    # Joueur : une correspondance explicite dans le titre apporte de la valeur.
    stop = {"vintage","jersey","shirt","maillot","football","soccer","nba","basketball","retro","home","away","third","shirt"}
    target_words = {w for w in re.findall(r"[a-z0-9]+", target_text) if len(w) >= 4 and w not in stop}
    comp_words = {w for w in re.findall(r"[a-z0-9]+", comp_text) if len(w) >= 4 and w not in stop}
    overlap = len(target_words & comp_words)
    score += min(15, overlap * 3)

    # Variante domicile/extérieur/third.
    for variant in ("home", "away", "third", "goalkeeper", "goalie"):
        if contains_phrase(target_text, variant) and contains_phrase(comp_text, variant):
            score += 5
            break

    return min(100, score)


def get_comparables(
    session,
    domain,
    item,
):

    cache_key = get_comparable_cache_key(
        domain,
        item,
    )

    if cache_key in COMPARABLE_CACHE:

        return COMPARABLE_CACHE[cache_key]

    sport = classify_sport(item)

    if sport is None:
        return []

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

    if sport == "football":

        search_text = (
            f"{title} football jersey vintage"
        )

    else:

        search_text = (
            f"{title} NBA jersey vintage"
        )

    params = {

        "order": "relevance",

        "per_page": 50,

        "currency": "EUR",

        "search_text": search_text,
    }

    if brand_id:

        params["brand_ids[]"] = brand_id

    if catalog_id:

        params["catalog[]"] = catalog_id

    # IMPORTANT :
    # aucun price_to ici : les comparables peuvent dépasser
    # le prix d'achat et rester utiles pour estimer le marché.

    response = request_vinted(
        session,
        f"https://www.{domain}/api/v2/catalog/items",
        params,
        domain,
        f"comparables {title[:40]}",
    )

    if response is None:

        COMPARABLE_CACHE[cache_key] = []

        return []

    try:

        data = response.json()

    except Exception:

        COMPARABLE_CACHE[cache_key] = []

        return []

    ranked = []

    for comparable in data.get(
        "items",
        [],
    ):

        if (
            comparable.get("id")
            == item.get("id")
        ):
            continue

        if not comparable_matches_target(
            item,
            comparable,
            sport,
        ):
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

        if price > SEARCH_PRICE_MAX:
            continue

        relevance = comparable_relevance_score(item, comparable, sport)
        if relevance < 35:
            continue
        ranked.append((relevance, price))

    ranked.sort(key=lambda x: (-x[0], x[1]))
    prices = [price for _, price in ranked]

    COMPARABLE_CACHE[cache_key] = prices

    return prices


# ============================================================
# TAILLES
# ============================================================

def size_is_accepted(
    size_title,
):

    if not size_title:
        return False

    normalized = normalize_text(
        size_title
    ).upper()

    if normalized in ACCEPTED_SIZES:
        return True

    tokens = re.findall(
        r"\b(?:XS|S|M|L|XL|XXL|2XL|3XL)\b",
        normalized,
    )

    return any(
        token in ACCEPTED_SIZES
        for token in tokens
    )


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

    sport = classify_sport(item)

    if sport not in {
        "football",
        "nba",
    }:

        text = get_item_search_text(item)

        if contains_any_phrase(
            text,
            NON_FOOTBALL_SPORTS,
        ):
            record_rejection(
                "sport non autorisé",
                item,
            )

        elif not is_vintage_item(item):

            record_rejection(
                "pas assez vintage",
                item,
            )

        elif (
            not has_known_european_team(text)
            and not has_known_nba_team(text)
        ):

            record_rejection(
                "équipe européenne/NBA inconnue",
                item,
            )

        elif not (
            has_football_garment(text)
            or contains_any_phrase(
                text,
                NBA_GARMENT_TERMS,
            )
        ):

            record_rejection(
                "pas un maillot/jersey",
                item,
            )

        else:

            record_rejection(
                "catégorie sport ambiguë",
                item,
            )

        return None

    if not is_vintage_item(item):

        record_rejection(
            "pas assez vintage",
            item,
        )

        return None

    if not is_accepted_condition(item):

        condition = get_item_condition_text(item)

        if not condition:

            record_rejection(
                "état absent",
                item,
            )

        else:

            record_rejection(
                "état non accepté",
                item,
            )

        return None

    if looks_like_replica(
        title,
        get_description(item),
    ):

        record_rejection(
            "risque contrefaçon / replica suspecte",
            item,
        )

        return None

    size = item.get(
        "size_title"
    )

    if looks_like_kids_item(
        title,
        size,
    ):

        record_rejection(
            "article enfant / junior",
            item,
        )

        return None

    if not size_is_accepted(size):

        record_rejection(
            "taille non acceptée ou absente",
            item,
        )

        return None

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

        record_rejection(
            "prix illisible",
            item,
        )

        return None

    if purchase_price <= 0:

        record_rejection(
            "prix invalide",
            item,
        )

        return None

    # IMPORTANT :
    # Les recherches vont jusqu'à 40 €, mais on ne calcule
    # une opportunité d'achat que jusqu'à 18 €.
    if purchase_price > MAX_ANALYSIS_PURCHASE_PRICE:

        record_rejection(
            "prix supérieur à 18 €",
            item,
        )

        return None

    prices = get_comparables(
        session,
        domain,
        item,
    )

    if len(prices) < MIN_COMPARABLES:

        record_rejection(
            f"pas assez de comparables (< {MIN_COMPARABLES})",
            item,
        )

        return None

    prices = remove_outliers(prices)

    if len(prices) < MIN_COMPARABLES:

        record_rejection(
            f"pas assez de comparables après filtrage (< {MIN_COMPARABLES})",
            item,
        )

        return None

    prices = sorted(prices)

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

        record_rejection(
            "prix de revente prudent invalide",
            item,
        )

        return None

    median_price = statistics.median(prices)

    if (
        len(prices) > 1
        and median_price
    ):

        variance = (
            statistics.stdev(prices)
            / median_price
            * 100
        )

    else:

        variance = 0

    real_fee = (
        item.get("service_fee") or {}
    ).get("amount")

    try:

        if real_fee:

            buyer_fee = float(real_fee)

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

    views = (
        item.get("view_count")
        or 0
    )

    favourites = (
        item.get("favourite_count")
        or 0
    )

    engagement = (
        views + favourites
    )

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

    authenticity_risk = False

    if (
        purchase_price < 3
        and cautious_sale_price >= 20
    ):

        authenticity_risk = True

    if (
        is_hype_item(item)
        and purchase_price
        < cautious_sale_price * 0.25
    ):

        authenticity_risk = True

    max_purchase = calculate_max_purchase_price(
        cautious_sale_price,
        budget,
        score,
    )

    classification = classify_deal(
        score,
        cautious_profit,
        probable_profit,
        purchase_price,
        budget,
        authenticity_risk,
    )

    if classification == "⚫ À ÉVITER":

        record_rejection(
            "score / rentabilité insuffisants",
            item,
        )

        return None

    if cautious_profit < MIN_PROFIT_EUR:

        if classification != "🟡 BON PLAN":

            record_rejection(
                f"bénéfice prudent inférieur à {MIN_PROFIT_EUR:.0f} €",
                item,
            )

            return None

    item["_stable_fingerprint"] = (
        get_stable_fingerprint(item)
    )

    return {

        "item": item,

        "domain": domain,

        "sport": sport,

        "purchase_price": purchase_price,

        "condition": (
            get_item_condition_text(item)
        ),

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

        "football_item": sport == "football",

        "nba_item": sport == "nba",
    }


# ============================================================
# SCAN D'UN DOMAINE
# ============================================================

def scan_domain(
    domain,
    run_seen,
    budget,
):

    print(
        f"\n========== {domain} =========="
    )

    session = get_session(domain)

    new_items = []

    search_plan = select_search_plan(domain)

    print(
        f"[{domain}] "
        f"{len(search_plan)} recherches prévues."
    )

    for category, keyword in search_plan:

        results = search_vinted(
            session,
            domain,
            keyword,
            category,
        )

        for item in results:

            stable_key = (
                get_stable_fingerprint(item)
            )

            listing_id = (
                get_listing_id(item)
            )

            if stable_key in run_seen:
                continue

            if listing_id in run_seen:
                continue

            run_seen.add(stable_key)
            run_seen.add(listing_id)

            item["_search_keyword"] = keyword
            item["_search_category"] = category
            item["_stable_fingerprint"] = stable_key

            new_items.append(item)

        if session.vinted_rate_limited:
            break

        time.sleep(
            random.uniform(
                1.3,
                2.5,
            )
        )

    print(
        f"[{domain}] "
        f"{len(new_items)} articles uniques récupérés."
    )

    deals = []

    for item in new_items:

        result = analyse_item(
            session,
            domain,
            item,
            budget,
        )

        if result:
            deals.append(result)

    return deals


# ============================================================
# DEDUP DEALS
# ============================================================

def deal_dedupe_key(
    deal,
):

    item = deal["item"]

    key = item.get(
        "_stable_fingerprint"
    )

    if key:
        return key

    return get_stable_fingerprint(item)


def dedupe_deals(
    deals,
):

    best = {}

    for deal in deals:

        key = deal_dedupe_key(deal)

        if key not in best:

            best[key] = deal

            continue

        current = best[key]

        current_rank = (
            current["score"],
            current["comparables"],
            current["probable_profit"],
        )

        new_rank = (
            deal["score"],
            deal["comparables"],
            deal["probable_profit"],
        )

        if new_rank > current_rank:

            best[key] = deal

    return list(best.values())


# ============================================================
# NOTIFICATIONS PERSISTANTES
# ============================================================

NOTIFIED_FILE = "notified_items.json"

RENOTIFY_DAYS = 30

RENOTIFY_PRICE_DROP_PERCENT = 0.10

RENOTIFY_SCORE_IMPROVEMENT = 10


def load_notification_state():

    try:

        with open(
            NOTIFIED_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if not isinstance(
            data,
            dict,
        ):
            return {}

        return data

    except Exception:

        return {}


def save_notification_state(
    state,
):

    with open(
        NOTIFIED_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )


def should_notify_deal(
    deal,
    notification_state,
):

    key = deal_dedupe_key(deal)

    state = notification_state.get(key)

    if not state:
        return True

    current_price = float(
        deal["purchase_price"]
    )

    old_price = state.get(
        "purchase_price"
    )

    if old_price is not None:

        try:

            old_price = float(old_price)

            if (
                current_price
                <= old_price
                * (
                    1
                    - RENOTIFY_PRICE_DROP_PERCENT
                )
            ):
                return True

        except Exception:
            pass

    old_score = state.get("score")

    if old_score is not None:

        try:

            if (
                deal["score"]
                >= int(old_score)
                + RENOTIFY_SCORE_IMPROVEMENT
            ):
                return True

        except Exception:
            pass

    last_notification = state.get(
        "timestamp",
        0,
    )

    try:

        elapsed = (
            time.time()
            - float(last_notification)
        )

        if (
            elapsed
            >= RENOTIFY_DAYS
            * 24
            * 60
            * 60
        ):
            return True

    except Exception:

        return True

    return False


def mark_deal_notified(
    deal,
    notification_state,
):

    key = deal_dedupe_key(deal)

    notification_state[key] = {

        "timestamp": time.time(),

        "purchase_price": (
            deal["purchase_price"]
        ),

        "score": deal["score"],

        "sport": deal["sport"],

        "title": (
            deal["item"].get(
                "title",
                "",
            )
        ),
    }


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
    budget,
):

    if not EMAIL_FROM:

        print(
            "EMAIL_ADDRESS absent."
        )

        return False

    if not EMAIL_PASSWORD:

        print(
            "EMAIL_PASSWORD absent."
        )

        return False

    if not EMAIL_TO:

        print(
            "EMAIL_TO absent."
        )

        return False

    deals = sorted(
        deals,
        key=lambda x: (
            -x["score"],
            x["purchase_price"],
        ),
    )

    deals = deals[:MAX_EMAIL_DEALS]

    message = MIMEMultipart("alternative")

    message["Subject"] = (
        "Vinted Scanner — "
        "⚽ Foot Vintage / 🏀 NBA Vintage — "
        f"{len(deals)} opportunités"
    )

    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO

    html_body = """
    <html>
    <body style="font-family:Arial,sans-serif">
    """

    html_body += (
        "<h1>"
        "Vinted Scanner"
        " — ⚽ Foot Vintage / 🏀 NBA Vintage"
        "</h1>"
    )

    html_body += (
        f"<p>"
        f"Budget disponible : "
        f"<b>{budget:.2f} €</b>"
        f"</p>"
    )

    html_body += (
        "<p>"
        "<b>Recherche spécialisée :</b><br>"
        "⚽ Maillots vintage d'équipes européennes connues<br>"
        "🏀 Maillots NBA vintage"
        "</p>"
    )

    html_body += (
        "<p>"
        "<b>Prix :</b> recherches jusqu'à "
        f"{SEARCH_PRICE_MAX:.2f} €, "
        "mais analyse d'achat limitée à "
        f"{MAX_ANALYSIS_PURCHASE_PRICE:.2f} €."
        "</p>"
    )

    html_body += (
        "<p>"
        "<b>Etats acceptés :</b> "
        "Très bon état / Neuf sans étiquette / "
        "Neuf avec étiquette."
        "</p>"
    )

    html_body += (
        "<p>"
        f"Minimum {MIN_COMPARABLES} comparables pour "
        "retenir une opportunité."
        "</p>"
    )

    html_body += (
        "<p>"
        "Les doublons sont filtrés entre les différents "
        "domaines Vinted grâce à une empreinte basée notamment "
        "sur la photo, le vendeur, le titre, la marque et la taille."
        "</p>"
    )

    html_body += (
        "<p>"
        "Les prix de revente sont des estimations basées sur "
        "les annonces comparables disponibles. Ils ne garantissent "
        "pas qu'un article sera vendu à ce prix."
        "</p>"
    )

    if deals:

        html_body += "<h2>🔥 Opportunités</h2>"

        for deal in deals:

            item = deal["item"]
            domain = deal["domain"]

            title = html.escape(
                item.get(
                    "title",
                    "",
                )
            )

            url = make_item_url(
                item,
                domain,
            )

            classification = deal[
                "classification"
            ]

            if deal["sport"] == "football":

                sport_badge = (
                    "⚽ FOOT VINTAGE"
                )

            else:

                sport_badge = (
                    "🏀 NBA VINTAGE"
                )

            html_body += """
            <div style="
                border:1px solid #ccc;
                padding:15px;
                margin:15px 0;
                border-radius:8px;
            ">
            """

            html_body += (
                f"<h3>"
                f"{classification} — "
                f"{sport_badge} — "
                f"Score {deal['score']}/100"
                f"</h3>"
            )

            html_body += (
                f"<b>{title}</b><br>"
                f"Pays : "
                f"{html.escape(domain)}"
                f"<br>"
                f"Etat : <b>"
                f"{html.escape(deal['condition'])}"
                f"</b>"
                f"<br><br>"
            )

            html_body += (
                f"💰 Achat : "
                f"<b>"
                f"{deal['purchase_price']:.2f} €"
                f"</b>"
                f"<br>"
            )

            html_body += (
                f"🎯 Revente prudente : "
                f"<b>"
                f"{deal['cautious_sale_price']:.2f} €"
                f"</b>"
                f"<br>"
            )

            html_body += (
                f"📊 Revente probable : "
                f"<b>"
                f"{deal['probable_sale_price']:.2f} €"
                f"</b>"
                f"<br>"
            )

            html_body += (
                f"🚀 Revente optimiste : "
                f"{deal['optimistic_sale_price']:.2f} €"
                f"<br>"
            )

            html_body += (
                f"📦 Coût total estimé : "
                f"{deal['total_cost']:.2f} €"
                f"<br><br>"
            )

            html_body += (
                f"🛡️ Bénéfice prudent : "
                f"<b>"
                f"{deal['cautious_profit']:.2f} €"
                f"</b>"
                f"<br>"
            )

            html_body += (
                f"💵 Bénéfice probable : "
                f"<b>"
                f"{deal['probable_profit']:.2f} €"
                f"</b>"
                f"<br>"
            )

            html_body += (
                f"📈 Bénéfice optimiste : "
                f"{deal['optimistic_profit']:.2f} €"
                f"<br><br>"
            )

            html_body += (
                f"🧮 Comparables : "
                f"{deal['comparables']}"
                f"<br>"
                f"📉 Variance : "
                f"{deal['variance']:.1f}%"
                f"<br>"
                f"👀 Vues : "
                f"{deal['views']}"
                f"<br>"
                f"❤️ Favoris : "
                f"{deal['favourites']}"
                f"<br><br>"
            )

            html_body += (
                f"🛒 "
                f"<b>"
                f"Prix maximum conseillé : "
                f"{deal['max_purchase']:.2f} €"
                f"</b>"
                f"<br><br>"
            )

            if url:

                safe_url = html.escape(
                    url,
                    quote=True,
                )

                html_body += (
                    f'<a href="{safe_url}">'
                    f"Voir l'annonce"
                    f"</a>"
                )

            html_body += "</div>"

    else:

        html_body += (
            "<h2>"
            "Aucune nouvelle opportunité."
            "</h2>"
        )

    html_body += (
        "</body>"
        "</html>"
    )

    message.attach(
        MIMEText(
            html_body,
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

        return True

    except Exception as exc:

        print(
            f"Erreur email : "
            f"{exc}"
        )

        return False


# ============================================================
# DISCORD
# ============================================================

def notify_discord(
    deal,
):

    if not DISCORD_WEBHOOK_URL:
        return False

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

    if deal["sport"] == "football":

        sport_label = (
            "⚽ FOOT VINTAGE"
        )

    else:

        sport_label = (
            "🏀 NBA VINTAGE"
        )

    description = (

        f"{sport_label}\n"

        f"{deal['classification']}\n\n"

        f"Etat : "
        f"{deal['condition']}\n"

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

        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10,
        )

        return response.status_code in {
            200,
            204,
        }

    except Exception as exc:

        print(
            f"Discord erreur : "
            f"{exc}"
        )

        return False


# ============================================================
# RAPPORT TERMINAL
# ============================================================

def print_deal(
    deal,
):

    item = deal["item"]

    print(
        "\n"
        + "=" * 70
    )

    print(
        deal["classification"],
        f"SCORE {deal['score']}/100",
    )

    if deal["sport"] == "football":

        print(
            "⚽ FOOT VINTAGE EUROPEEN"
        )

    else:

        print(
            "🏀 NBA VINTAGE"
        )

    print(
        item.get(
            "title",
            "",
        )
    )

    print(
        f"Etat        : "
        f"{deal['condition']}"
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
        "==================================================\n"
        "      VINTED RESALE SCANNER V5\n"
        "      ⚽ FOOT VINTAGE EUROPEEN\n"
        "      🏀 NBA VINTAGE\n"
        "==================================================\n"
    )

    print(
        f"Budget simulé : "
        f"{STARTING_BUDGET:.2f} €"
    )

    print(
        "Recherche : "
        "⚽ maillots vintage européens connus "
        "+ "
        "🏀 maillots NBA vintage"
    )

    print(
        "Prix de recherche : "
        f"{SEARCH_PRICE_MIN:.2f} € → "
        f"{SEARCH_PRICE_MAX:.2f} €"
    )

    print(
        "Prix maximum analysé comme achat : "
        f"{MAX_ANALYSIS_PURCHASE_PRICE:.2f} €"
    )

    print(
        f"Minimum comparables : "
        f"{MIN_COMPARABLES}"
    )

    print(
        "Pas de streetwear général."
    )

    print(
        "Pas de NFL / MLB / NHL."
    )

    print(
        "Pas de maillots sud-américains."
    )

    print(
        "Pas de t-shirts génériques."
    )

    print(
        "Pas d'enfants."
    )

    print(
        "Etats acceptés : "
        "Très bon état / "
        "Neuf sans étiquette / "
        "Neuf avec étiquette"
    )

    print(
        f"Rotation : "
        f"{TEAM_SEARCHES_PER_DOMAIN} recherches équipes "
        f"par domaine."
    )

    COMPARABLE_CACHE.clear()

    reset_rejection_stats()

    notification_state = (
        load_notification_state()
    )

    run_seen = set()

    all_deals = []

    domains = DOMAINS[:]

    random.shuffle(domains)

    for domain in domains:

        deals = scan_domain(
            domain,
            run_seen,
            STARTING_BUDGET,
        )

        all_deals.extend(deals)

        time.sleep(
            random.uniform(
                2,
                4,
            )
        )

    all_deals = dedupe_deals(
        all_deals
    )

    fresh_deals = []

    already_notified_count = 0

    for deal in all_deals:

        if should_notify_deal(
            deal,
            notification_state,
        ):

            fresh_deals.append(deal)

        else:

            already_notified_count += 1

    all_deals = fresh_deals

    all_deals.sort(
        key=lambda deal: (
            -deal["score"],
            deal["purchase_price"],
        )
    )

    print(
        "\n\n"
        "=================================================="
    )

    print(
        f"{len(all_deals)} "
        f"nouvelles opportunités retenues."
    )

    print(
        f"{already_notified_count} "
        f"opportunités déjà notifiées ignorées."
    )

    print(
        "=================================================="
    )

    for deal in all_deals[:20]:

        print_deal(deal)

    email_deals = all_deals[:MAX_EMAIL_DEALS]

    email_sent = False

    if email_deals:

        email_sent = send_email(
            email_deals,
            STARTING_BUDGET,
        )

    if email_sent:

        for deal in email_deals:

            mark_deal_notified(
                deal,
                notification_state,
            )

    discord_count = 0

    for deal in all_deals:

        if discord_count >= MAX_DISCORD_ALERTS:
            break

        if deal["score"] < 70:
            continue

        sent = notify_discord(deal)

        if sent:

            discord_count += 1

        time.sleep(
            random.uniform(
                1,
                2,
            )
        )

    save_notification_state(
        notification_state
    )

    print_rejection_diagnostics()

    print(
        "\n"
        "=================================================="
    )

    print(
        "SCAN TERMINE."
    )

    print(
        f"Opportunités nouvelles : "
        f"{len(all_deals)}"
    )

    print(
        f"Discord envoyés : "
        f"{discord_count}"
    )

    print(
        "Doublons filtrés : "
        "ACTIFS"
    )

    print(
        "Notification répétée : "
        "uniquement si baisse de prix importante, "
        "forte amélioration du score ou après "
        f"{RENOTIFY_DAYS} jours."
    )

    print(
        "=================================================="
    )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    main()
