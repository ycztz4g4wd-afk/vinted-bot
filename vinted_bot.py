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
# VINTED RESALE SCANNER V7
# ============================================================
#
# SPECIALISATION :
#
#   ⚽ FOOTBALL VINTAGE EUROPEEN
#   👕 VETEMENTS HOMME - MARQUES A POTENTIEL
#   🧸 LOTS DE FUNKO POP
#
# SUPPRIME :
#   - NBA
#   - NFL
#   - MLB
#   - NHL
#   - streetwear général
#   - sneakers
#   - vêtements sans marque ciblée
#
# V7 :
#   - football vintage européen conservé
#   - NBA complètement supprimé
#   - ajout vêtements homme ciblés
#   - ajout lots Funko Pop
#   - vêtements uniquement tailles adultes
#   - états stricts
#   - achat limité à 18 €
#   - minimum 5 comparables
#   - diagnostic détaillé
#   - déduplication
#   - email / Discord
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

BRAND_SEARCHES_PER_DOMAIN = 18

FUNKO_SEARCHES_PER_DOMAIN = 8

SEARCH_ROTATION_MINUTES = 60

MAX_EMAIL_DEALS = 25

MAX_DISCORD_ALERTS = 15

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

SEARCH_PRICE_MIN = 0.50
SEARCH_PRICE_MAX = 40.0

MAX_ANALYSIS_PURCHASE_PRICE = 18.0

SHIPPING_COST_ESTIMATE = 5.0

BUYER_PROTECTION_PERCENT = 0.05
BUYER_PROTECTION_FIXED = 0.70

MIN_PROFIT_EUR = 6.0
MIN_SAFE_PROFIT_EUR = 8.0

MIN_COMPARABLES = 5

MAX_BUDGET_USAGE_NORMAL = 0.40
MAX_BUDGET_USAGE_EXCEPTIONAL = 0.65


# ============================================================
# DIAGNOSTIC DES REJETS
# ============================================================

REJECTION_STATS = Counter()


def record_rejection(reason, item=None):

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
            count / total * 100
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
# TAILLES HOMME
# ============================================================

ACCEPTED_SIZES = {
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "2XL",
    "3XL",
}

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

def contains_phrase(text, phrase):

    text = normalize_text(text)
    phrase = normalize_text(phrase)

    if not phrase:
        return False

    return re.search(
        rf"(?<!\w){re.escape(phrase)}(?!\w)",
        text,
    ) is not None


def contains_any_phrase(text, phrases):

    return any(
        contains_phrase(
            text,
            phrase,
        )
        for phrase in phrases
    )


# ============================================================
# VINTAGE
# ============================================================

VINTAGE_TERMS = [

    "vintage",
    "retro",
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

    "annees 80",
    "années 80",
    "annees 90",
    "années 90",
    "annees 2000",
    "années 2000",

    "anos 90",
    "anos 2000",
    "años 90",
    "años 2000",
]


VINTAGE_YEAR_RE = re.compile(
    r"\b("
    r"19[5-9]\d"
    r"|200\d"
    r"|2010"
    r")\b"
)


VINTAGE_SEASON_RE = re.compile(
    r"\b("
    r"(?:19[5-9]\d|200\d|201[0-2])"
    r"\s*[/\-]\s*\d{2,4}"
    r"|"
    r"\d{2}\s*[/\-]\s*\d{2}"
    r")\b"
)


def is_vintage_item(item):

    text = get_item_search_text(item)

    if contains_any_phrase(
        text,
        VINTAGE_TERMS,
    ):
        return True

    if VINTAGE_YEAR_RE.search(text):
        return True

    if VINTAGE_SEASON_RE.search(text):
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
# ENFANTS / JUNIOR
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
# TAILLES
# ============================================================

def size_is_accepted(size_title):

    if not size_title:
        return False

    normalized = normalize_text(
        size_title
    ).upper()

    if normalized in ACCEPTED_SIZES:
        return True

    tokens = re.findall(
        r"\b(?:S|M|L|XL|XXL|2XL|3XL)\b",
        normalized,
    )

    return any(
        token in ACCEPTED_SIZES
        for token in tokens
    )


# ============================================================
# CONTREFAÇONS / RISQUE
# ============================================================

STRONG_COUNTERFEIT_KEYWORDS = [

    "fake",
    "counterfeit",
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
    "inspiree",
    "inspire",
    "repro",
    "reproduction",
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

    "scotland": [
        "scotland",
        "ecosse",
        "tartan army",
    ],

    "wales": [
        "wales",
        "pays de galles",
        "cymru",
    ],

    "ireland": [
        "republic of ireland",
        "ireland",
        "irlande",
    ],

    "switzerland": [
        "switzerland",
        "suisse",
        "schweiz",
    ],

    "austria": [
        "austria",
        "autriche",
        "osterreich",
    ],

    "denmark": [
        "denmark",
        "danemark",
        "danmark",
    ],

    "sweden": [
        "sweden",
        "suede",
        "sverige",
    ],

    "norway": [
        "norway",
        "norvege",
        "norge",
    ],

    "poland": [
        "poland",
        "pologne",
        "polska",
    ],

    "czech republic": [
        "czech republic",
        "republique tcheque",
        "czechia",
    ],

    "romania": [
        "romania",
        "roumanie",
    ],

    "turkey": [
        "turkey",
        "turquie",
        "turkiye",
    ],
}


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

    "west ham": [
        "west ham",
        "west ham united",
        "whu",
    ],

    "everton": [
        "everton",
        "efc",
    ],

    "aston villa": [
        "aston villa",
        "avfc",
    ],

    "newcastle": [
        "newcastle",
        "newcastle united",
        "nufc",
    ],

    "leeds": [
        "leeds",
        "leeds united",
    ],

    "nottingham forest": [
        "nottingham forest",
        "nottm forest",
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
        "atletico de madrid",
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

    "fiorentina": [
        "fiorentina",
        "acf fiorentina",
    ],

    "lazio": [
        "lazio",
        "ss lazio",
    ],

    "atalanta": [
        "atalanta",
        "atalanta bergamo",
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

    "monaco": [
        "as monaco",
        "monaco",
    ],

    "bordeaux": [
        "bordeaux",
        "girondins bordeaux",
    ],

    "saint etienne": [
        "saint etienne",
        "asse",
        "st etienne",
    ],

    "lens": [
        "rc lens",
        "lens",
    ],

    "nantes": [
        "fc nantes",
        "nantes",
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

    "sporting": [
        "sporting cp",
        "sporting lisbon",
        "sporting portugal",
    ],

    "braga": [
        "sporting braga",
        "braga",
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

    "besiktas": [
        "besiktas",
        "besiktas jk",
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

    "sevilla": [
        "sevilla",
        "sevilla fc",
    ],

    "valencia": [
        "valencia",
        "valencia cf",
    ],
}


EUROPEAN_TEAM_ALIASES = {}

EUROPEAN_TEAM_ALIASES.update(
    EUROPEAN_NATIONAL_TEAMS
)

EUROPEAN_TEAM_ALIASES.update(
    EUROPEAN_CLUBS
)


def get_matching_football_teams(text):

    matches = set()

    for team_name, aliases in (
        EUROPEAN_TEAM_ALIASES.items()
    ):

        if contains_any_phrase(
            text,
            aliases,
        ):

            matches.add(
                team_name
            )

    return matches


def has_known_european_team(text):

    return bool(
        get_matching_football_teams(text)
    )


def has_football_garment(text):

    return contains_any_phrase(
        text,
        FOOTBALL_GARMENT_TERMS,
    )


def is_football_item(item):

    text = get_item_search_text(item)

    if not is_vintage_item(item):
        return False

    if not has_known_european_team(text):
        return False

    if not has_football_garment(text):
        return False

    return True


# ============================================================
# VETEMENTS HOMME
# ============================================================

TARGET_CLOTHING_BRANDS = {

    "ralph lauren": [
        "ralph lauren",
        "polo ralph lauren",
    ],

    "carhartt": [
        "carhartt",
        "carhartt wip",
    ],

    "nike": [
        "nike",
    ],

    "lacoste": [
        "lacoste",
    ],

    "burberry": [
        "burberry",
        "burberrys",
    ],

    "cp company": [
        "cp company",
        "c.p. company",
        "c.p company",
        "c p company",
    ],

    "stone island": [
        "stone island",
    ],

    "stussy": [
        "stussy",
        "stüssy",
    ],

    "patagonia": [
        "patagonia",
    ],

    "fred perry": [
        "fred perry",
    ],

    "the north face": [
        "the north face",
        "tnf",
    ],

    "adidas": [
        "adidas",
    ],
}


CLOTHING_GARMENT_TERMS = [

    "t shirt",
    "tee",
    "tshirt",

    "polo",

    "sweat",
    "sweatshirt",

    "hoodie",
    "hoody",

    "pull",
    "pull over",
    "pullover",

    "chemise",
    "shirt",

    "veste",
    "jacket",

    "blouson",
    "bomber",

    "manteau",
    "coat",

    "parka",

    "pantalon",
    "trousers",
    "pants",

    "cargo",

    "jean",
    "jeans",

    "short",
    "shorts",

    "gilet",
    "cardigan",

    "polaire",
    "fleece",

    "anorak",

    "windbreaker",

    "track jacket",

    "survetement",
    "tracksuit",

    "chemise",
]


CLOTHING_EXCLUDED_TERMS = [

    "femme",
    "women",
    "woman",
    "dame",
    "damen",

    "fille",
    "girl",
    "girls",

    "enfant",
    "enfants",
    "kids",
    "kid",
    "junior",

    "bébé",
    "bebe",
    "baby",

    "chaussure",
    "shoes",
    "sneaker",
    "sneakers",

    "sac",
    "bag",

    "casquette",
    "cap",

    "ceinture",
    "belt",

    "portefeuille",
    "wallet",

    "lunettes",
    "glasses",

    "parfum",
    "perfume",

    "montre",
    "watch",

    "accessoire",
    "accessories",
]


def get_matching_clothing_brands(text):

    matches = set()

    for brand, aliases in (
        TARGET_CLOTHING_BRANDS.items()
    ):

        if contains_any_phrase(
            text,
            aliases,
        ):

            matches.add(
                brand
            )

    return matches


def has_known_clothing_brand(text):

    return bool(
        get_matching_clothing_brands(text)
    )


def is_clothing_item(item):

    text = get_item_search_text(item)

    if not has_known_clothing_brand(text):
        return False

    if contains_any_phrase(
        text,
        CLOTHING_EXCLUDED_TERMS,
    ):
        return False

    if looks_like_kids_item(
        item.get("title", ""),
        item.get("size_title"),
    ):
        return False

    if not size_is_accepted(
        item.get("size_title")
    ):
        return False

    if not contains_any_phrase(
        text,
        CLOTHING_GARMENT_TERMS,
    ):
        return False

    return True


# ============================================================
# FUNKO POP LOTS
# ============================================================

FUNKO_SEARCHES = [

    "lot funko pop",
    "lot funko",
    "lots funko pop",
    "lot de funko pop",
    "lot 2 funko pop",
    "lot 3 funko pop",
    "lot 4 funko pop",
    "lot 5 funko pop",
    "bundle funko pop",
    "collection funko pop",
    "collection funko",
    "pack funko pop",
]


FUNKO_REQUIRED_TERMS = [

    "funko",
    "funko pop",
    "funko! pop",
]


FUNKO_LOT_TERMS = [

    "lot",
    "lots",
    "bundle",
    "collection",
    "pack",
    "set",
    "ensemble",
    "ensemble de",
    "lot de",
    "x2",
    "x3",
    "x4",
    "x5",
    "2x",
    "3x",
    "4x",
    "5x",
]


FUNKO_EXCLUDED_TERMS = [

    "protector",
    "protection",
    "protecteur",
    "protective case",

    "boite vide",
    "boîte vide",
    "empty box",
    "empty boxes",

    "box only",
    "case only",

    "display",
    "presentoir",
    "présentoir",

    "shelf",

    "pin",
    "pins",

    "porte cle",
    "porte-cle",
    "keychain",

    "key ring",

    "bitty",
    "bitty pop",

    "mini pop",

    "plush",
    "peluche",

    "sticker",
    "stickers",

    "poster",

    "tasse",
    "mug",

    "cartes",
    "cards",

    "support",
    "stands",
]


def looks_like_funko_lot(item):

    text = get_item_search_text(item)

    if not contains_any_phrase(
        text,
        FUNKO_REQUIRED_TERMS,
    ):
        return False

    if contains_any_phrase(
        text,
        FUNKO_EXCLUDED_TERMS,
    ):
        return False

    if not contains_any_phrase(
        text,
        FUNKO_LOT_TERMS,
    ):
        return False

    # Détection explicite d'une quantité.
    quantity_match = re.search(
        r"\b([2-9]|10|[1-9][0-9])\s*"
        r"(?:funko|funko pop|pops?)\b",
        text,
    )

    reverse_quantity_match = re.search(
        r"\b(?:funko|funko pop|pops?)\s*"
        r"(?:x|×)\s*([2-9]|10|[1-9][0-9])\b",
        text,
    )

    if quantity_match:
        try:
            return int(
                quantity_match.group(1)
            ) >= 2
        except Exception:
            pass

    if reverse_quantity_match:
        try:
            return int(
                reverse_quantity_match.group(1)
            ) >= 2
        except Exception:
            pass

    # Les mots "lot", "bundle", "collection", etc. restent
    # acceptés même si la quantité n'est pas écrite.
    return True


def is_funko_item(item):

    return looks_like_funko_lot(item)


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_category(item):

    if is_football_item(item):
        return "football"

    if is_clothing_item(item):
        return "clothing"

    if is_funko_item(item):
        return "funko"

    return None


# ============================================================
# EQUIVALENCE / COMPARABLES
# ============================================================

def get_category_brands(item):

    text = get_item_search_text(item)

    return get_matching_clothing_brands(text)


def comparable_matches_target(
    target,
    comparable,
    category,
):

    if classify_category(comparable) != category:
        return False

    if not is_accepted_condition(comparable):
        return False

    target_text = get_item_search_text(target)
    comparable_text = get_item_search_text(comparable)

    if category == "football":

        if not is_vintage_item(comparable):
            return False

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

    elif category == "clothing":

        target_brands = (
            get_matching_clothing_brands(
                target_text
            )
        )

        comparable_brands = (
            get_matching_clothing_brands(
                comparable_text
            )
        )

        if not (
            target_brands
            & comparable_brands
        ):
            return False

        if not size_is_accepted(
            comparable.get("size_title")
        ):
            return False

        if not contains_any_phrase(
            comparable_text,
            CLOTHING_GARMENT_TERMS,
        ):
            return False

    elif category == "funko":

        if not looks_like_funko_lot(
            comparable
        ):
            return False

    return True


def comparable_relevance_score(
    target,
    comparable,
    category,
):

    target_text = get_item_search_text(target)
    comp_text = get_item_search_text(comparable)

    score = 0.0

    if category == "football":

        tt = get_matching_football_teams(
            target_text
        )

        ct = get_matching_football_teams(
            comp_text
        )

        if tt and ct and tt & ct:
            score += 50

        elif tt and ct:
            return 0

    elif category == "clothing":

        tb = get_matching_clothing_brands(
            target_text
        )

        cb = get_matching_clothing_brands(
            comp_text
        )

        if tb and cb and tb & cb:
            score += 60

        else:
            return 0

        target_size = normalize_text(
            target.get("size_title") or ""
        )

        comparable_size = normalize_text(
            comparable.get("size_title") or ""
        )

        if (
            target_size
            and comparable_size
            and target_size == comparable_size
        ):
            score += 20

        elif (
            target_size
            and comparable_size
            and (
                target_size in {
                    "s",
                    "m",
                    "l",
                    "xl",
                    "xxl",
                    "2xl",
                    "3xl",
                }
                and comparable_size in {
                    "s",
                    "m",
                    "l",
                    "xl",
                    "xxl",
                    "2xl",
                    "3xl",
                }
            )
        ):
            score += 10

    elif category == "funko":

        score += 50

        # Une franchise/personnage commun dans le titre
        # renforce le comparable.
        stop = {
            "funko",
            "funko pop",
            "lot",
            "lots",
            "bundle",
            "collection",
            "pack",
            "set",
            "ensemble",
            "pop",
        }

        target_words = {
            w
            for w in re.findall(
                r"[a-z0-9]+",
                target_text,
            )
            if len(w) >= 4
            and w not in stop
        }

        comp_words = {
            w
            for w in re.findall(
                r"[a-z0-9]+",
                comp_text,
            )
            if len(w) >= 4
            and w not in stop
        }

        overlap = len(
            target_words
            & comp_words
        )

        score += min(
            35,
            overlap * 5,
        )

    # Correspondance de mots utile.
    stop_words = {
        "vintage",
        "retro",
        "shirt",
        "maillot",
        "football",
        "jersey",
        "funko",
        "pop",
        "lot",
        "bundle",
        "collection",
        "homme",
        "men",
        "mens",
    }

    target_words = {
        w
        for w in re.findall(
            r"[a-z0-9]+",
            target_text,
        )
        if len(w) >= 4
        and w not in stop_words
    }

    comp_words = {
        w
        for w in re.findall(
            r"[a-z0-9]+",
            comp_text,
        )
        if len(w) >= 4
        and w not in stop_words
    }

    overlap = len(
        target_words
        & comp_words
    )

    score += min(
        20,
        overlap * 3,
    )

    return min(
        100,
        score,
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


def remove_outliers(prices):

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
# CACHE COMPARABLES
# ============================================================

COMPARABLE_CACHE = {}


def get_comparable_cache_key(
    domain,
    item,
):

    category = classify_category(item)

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
        category,
        str(brand_id or ""),
        str(catalog_id or ""),
        title,
    )


# ============================================================
# RECHERCHE COMPARABLES
# ============================================================

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

    category = classify_category(item)

    if category is None:
        return []

    title = item.get(
        "title",
        "",
    )

    if category == "football":

        search_text = (
            f"{title} football jersey vintage"
        )

    elif category == "clothing":

        brands = get_category_brands(item)

        brand = (
            next(iter(brands))
            if brands
            else ""
        )

        search_text = (
            f"{brand} {title}"
        )

    else:

        search_text = (
            f"{title} Funko Pop lot"
        )

    params = {

        "order": "relevance",

        "per_page": 50,

        "currency": "EUR",

        "search_text": search_text,
    }

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
            category,
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

        relevance = (
            comparable_relevance_score(
                item,
                comparable,
                category,
            )
        )

        if relevance < 35:
            continue

        ranked.append(
            (
                relevance,
                price,
            )
        )

    ranked.sort(
        key=lambda x: (
            -x[0],
            x[1],
        )
    )

    prices = [
        price
        for _, price in ranked
    ]

    COMPARABLE_CACHE[
        cache_key
    ] = prices

    return prices


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

    category = classify_category(item)

    if category == "football":
        score += 8

    elif category == "clothing":
        score += 6

    elif category == "funko":
        score += 7

    if category == "football":

        text = get_item_search_text(item)

        if has_known_european_team(text):
            score += 5

    if category == "clothing":

        brands = get_category_brands(item)

        premium_brands = {
            "burberry",
            "cp company",
            "stone island",
            "stussy",
            "ralph lauren",
            "carhartt",
            "patagonia",
            "fred perry",
            "the north face",
        }

        if brands & premium_brands:
            score += 5

    if comparable_count >= 20 and variance <= 30:
        score += 5

    elif comparable_count >= 10 and variance <= 35:
        score += 3

    if probable_sale_price > 0:

        discount = (
            1
            - (
                purchase_price
                / probable_sale_price
            )
        )

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

    title_lower = get_item_search_text(item)

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

        "funko",
        "pop",

        "heritage",
        "historical",
        "classic",

        "90s",
        "2000s",
        "y2k",
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
# CLASSIFICATION DEAL
# ============================================================

def classify_deal(
    score,
    cautious_profit,
    probable_profit,
    authenticity_risk,
):

    if authenticity_risk:
        return "🔴 RISQUE"

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


def get_session(domain):

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
# REQUEST VINTED
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
# RECHERCHES FOOTBALL
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
    "fussball trikot vintage",
]


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
    ("football", "Sporting Lisbon vintage jersey"),

    ("football", "Celtic vintage jersey"),
    ("football", "Rangers vintage jersey"),

    ("football", "Galatasaray vintage jersey"),
    ("football", "Fenerbahce vintage jersey"),
    ("football", "Besiktas vintage jersey"),

    ("football", "Anderlecht vintage jersey"),
    ("football", "Club Brugge vintage jersey"),

    ("football", "Olympiacos vintage jersey"),

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
]


# ============================================================
# RECHERCHES VETEMENTS
# ============================================================

CLOTHING_SEARCHES = [

    ("clothing", "Ralph Lauren homme vintage"),
    ("clothing", "Polo Ralph Lauren homme"),
    ("clothing", "Carhartt homme vintage"),
    ("clothing", "Carhartt WIP homme"),
    ("clothing", "Nike homme vintage"),
    ("clothing", "Lacoste homme vintage"),
    ("clothing", "Burberry homme vintage"),
    ("clothing", "CP Company homme"),
    ("clothing", "Stone Island homme"),
    ("clothing", "Stussy homme vintage"),
    ("clothing", "Patagonia homme vintage"),
    ("clothing", "Fred Perry homme vintage"),
    ("clothing", "The North Face homme vintage"),
    ("clothing", "Adidas homme vintage"),

    ("clothing", "Ralph Lauren polo homme"),
    ("clothing", "Carhartt jacket homme"),
    ("clothing", "Stone Island sweatshirt homme"),
    ("clothing", "CP Company jacket homme"),
    ("clothing", "Stussy sweatshirt homme"),
    ("clothing", "Patagonia fleece homme"),
    ("clothing", "North Face jacket homme"),
    ("clothing", "Fred Perry polo homme"),
]


# ============================================================
# RECHERCHES FUNKO
# ============================================================

FUNKO_SEARCH_PLAN = [

    ("funko", "lot funko pop"),
    ("funko", "lot de funko pop"),
    ("funko", "lots funko pop"),
    ("funko", "bundle funko pop"),
    ("funko", "collection funko pop"),
    ("funko", "pack funko pop"),
    ("funko", "lot 2 funko pop"),
    ("funko", "lot 3 funko pop"),
    ("funko", "lot 4 funko pop"),
    ("funko", "lot 5 funko pop"),
    ("funko", "lot 6 funko pop"),
    ("funko", "lot 10 funko pop"),
]


# ============================================================
# PLAN GLOBAL
# ============================================================

def build_team_search_plan():

    football = FOOTBALL_TEAM_SEARCHES[:]

    return football


TEAM_SEARCH_PLAN = build_team_search_plan()


def select_search_plan(domain):

    plan = []

    # -------------------------
    # FOOTBALL GENERIQUE
    # -------------------------

    generic_football = [
        (
            "football",
            keyword,
        )
        for keyword in FOOTBALL_GENERIC_SEARCHES
    ]

    random.shuffle(
        generic_football
    )

    plan.extend(
        generic_football
    )

    # -------------------------
    # FOOTBALL EQUIPES
    # -------------------------

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

            plan.append(
                TEAM_SEARCH_PLAN[position]
            )

    # -------------------------
    # VETEMENTS
    # -------------------------

    clothing = CLOTHING_SEARCHES[:]

    random.shuffle(
        clothing
    )

    plan.extend(
        clothing[
            :BRAND_SEARCHES_PER_DOMAIN
        ]
    )

    # -------------------------
    # FUNKO
    # -------------------------

    funko = FUNKO_SEARCH_PLAN[:]

    random.shuffle(
        funko
    )

    plan.extend(
        funko[
            :FUNKO_SEARCHES_PER_DOMAIN
        ]
    )

    # -------------------------
    # DEDUP
    # -------------------------

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

        "price_to": SEARCH_PRICE_MAX,

        "price_from": SEARCH_PRICE_MIN,

        "order": "newest_first",

        "per_page": 20,

        "currency": "EUR",
    }

    # Filtre de taille pour les vêtements et maillots.
    # Funko n'utilise pas ce filtre.
    if category in {
        "football",
        "clothing",
    }:

        params["size_ids[]"] = (
            SIZE_IDS_FILTER
        )

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

def get_seller_identifier(item):

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


def get_photo_identifier(item):

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


def normalize_photo_identifier(value):

    if not value:
        return ""

    try:

        parsed = urlparse(value)

        path = parsed.path

        return normalize_text(path)

    except Exception:

        return normalize_text(value)


# ============================================================
# FINGERPRINT
# ============================================================

def get_stable_fingerprint(item):

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
            raw.encode(
                "utf-8"
            )
        ).hexdigest()
    )


def get_listing_id(item):

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
# ANALYSE ARTICLE
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

    category = classify_category(item)

    # -------------------------
    # CLASSIFICATION
    # -------------------------

    if category is None:

        text = get_item_search_text(item)

        if looks_like_kids_item(
            title,
            item.get("size_title"),
        ):

            record_rejection(
                "article enfant / junior",
                item,
            )

        elif contains_any_phrase(
            text,
            CLOTHING_EXCLUDED_TERMS,
        ):

            record_rejection(
                "article/accessoire exclu",
                item,
            )

        elif not is_accepted_condition(item):

            condition = (
                get_item_condition_text(item)
            )

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

        else:

            record_rejection(
                "catégorie non autorisée",
                item,
            )

        return None

    # -------------------------
    # ETAT
    # -------------------------

    if not is_accepted_condition(item):

        record_rejection(
            "état non accepté",
            item,
        )

        return None

    # -------------------------
    # CONTREFAÇON
    # -------------------------

    if looks_like_replica(
        title,
        get_description(item),
    ):

        record_rejection(
            "risque contrefaçon / replica suspecte",
            item,
        )

        return None

    # -------------------------
    # VETEMENTS / FOOT
    # -------------------------

    if category in {
        "football",
        "clothing",
    }:

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

    # -------------------------
    # FUNKO
    # -------------------------

    if category == "funko":

        if not looks_like_funko_lot(item):

            record_rejection(
                "Funko individuel / accessoire / lot non confirmé",
                item,
            )

            return None

    # -------------------------
    # PRIX
    # -------------------------

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

    if (
        purchase_price
        > MAX_ANALYSIS_PURCHASE_PRICE
    ):

        record_rejection(
            "prix supérieur à 18 €",
            item,
        )

        return None

    # -------------------------
    # COMPARABLES
    # -------------------------

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

    prices = remove_outliers(
        prices
    )

    if len(prices) < MIN_COMPARABLES:

        record_rejection(
            "pas assez de comparables après filtrage",
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

    median_price = statistics.median(
        prices
    )

    if len(prices) > 1:

        variance = (
            statistics.stdev(prices)
            / median_price
            * 100
            if median_price
            else 0
        )

    else:

        variance = 0

    # -------------------------
    # FRAIS
    # -------------------------

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

    # -------------------------
    # ENGAGEMENT
    # -------------------------

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

    # -------------------------
    # SCORE
    # -------------------------

    score = calculate_sale_score(
        purchase_price,
        cautious_sale_price,
        probable_sale_price,
        len(prices),
        variance,
        engagement,
        item,
    )

    # -------------------------
    # RISQUE AUTHENTICITE
    # -------------------------

    authenticity_risk = False

    # Très forte anomalie prix / marché.
    if (
        purchase_price < 3
        and cautious_sale_price >= 20
    ):

        authenticity_risk = True

    # Marques très contrefaites.
    text = get_item_search_text(item)

    high_risk_brand = (
        category == "clothing"
        and bool(
            get_category_brands(item)
            & {
                "stone island",
                "cp company",
                "burberry",
            }
        )
    )

    if (
        high_risk_brand
        and purchase_price
        < cautious_sale_price * 0.20
    ):

        authenticity_risk = True

    # -------------------------
    # PRIX MAX
    # -------------------------

    max_purchase = (
        calculate_max_purchase_price(
            cautious_sale_price,
            budget,
            score,
        )
    )

    classification = classify_deal(
        score,
        cautious_profit,
        probable_profit,
        authenticity_risk,
    )

    if classification == "⚫ À ÉVITER":

        record_rejection(
            "score / rentabilité insuffisants",
            item,
        )

        return None

    if cautious_profit < MIN_PROFIT_EUR:

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

        "category": category,

        "sport": category,

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
    }


# ============================================================
# SCAN DOMAINE
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

    search_plan = select_search_plan(
        domain
    )

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

            run_seen.add(
                stable_key
            )

            run_seen.add(
                listing_id
            )

            item["_search_keyword"] = (
                keyword
            )

            item["_search_category"] = (
                category
            )

            item["_stable_fingerprint"] = (
                stable_key
            )

            new_items.append(
                item
            )

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
# DEDUPLICATION
# ============================================================

def deal_dedupe_key(deal):

    item = deal["item"]

    key = item.get(
        "_stable_fingerprint"
    )

    if key:
        return key

    return get_stable_fingerprint(item)


def dedupe_deals(deals):

    best = {}

    for deal in deals:

        key = deal_dedupe_key(
            deal
        )

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

    return list(
        best.values()
    )


# ============================================================
# NOTIFICATIONS
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

    key = deal_dedupe_key(
        deal
    )

    state = notification_state.get(
        key
    )

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

            old_price = float(
                old_price
            )

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

    old_score = state.get(
        "score"
    )

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
            - float(
                last_notification
            )
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

    key = deal_dedupe_key(
        deal
    )

    notification_state[key] = {

        "timestamp": time.time(),

        "purchase_price": (
            deal["purchase_price"]
        ),

        "score": deal["score"],

        "category": deal["category"],

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


def get_category_label(deal):

    category = deal["category"]

    if category == "football":
        return "⚽ FOOT VINTAGE"

    if category == "clothing":
        return "👕 VÊTEMENT HOMME"

    if category == "funko":
        return "🧸 LOT FUNKO POP"

    return "ARTICLE"


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

    message = MIMEMultipart(
        "alternative"
    )

    message["Subject"] = (
        "Vinted Scanner V7 — "
        "⚽ Foot / 👕 Marques / 🧸 Funko — "
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
        "Vinted Scanner V7"
        "</h1>"
    )

    html_body += (
        "<p>"
        "⚽ Foot vintage européen<br>"
        "👕 Vêtements homme de marques ciblées<br>"
        "🧸 Lots de Funko Pop"
        "</p>"
    )

    html_body += (
        f"<p>"
        f"Budget disponible : "
        f"<b>{budget:.2f} €</b>"
        f"</p>"
    )

    html_body += (
        "<p>"
        "<b>Prix maximum analysé : "
        f"{MAX_ANALYSIS_PURCHASE_PRICE:.2f} €</b>"
        "</p>"
    )

    html_body += (
        "<p>"
        "<b>Vêtements :</b> "
        "S / M / L / XL / XXL / 2XL / 3XL "
        "et uniquement états acceptés."
        "</p>"
    )

    html_body += (
        "<p>"
        "<b>Funko :</b> uniquement les lots, "
        "avec exclusion des protections, "
        "boîtes vides, accessoires, pins, "
        "Bitty Pop et produits similaires."
        "</p>"
    )

    html_body += (
        f"<p>"
        f"Minimum {MIN_COMPARABLES} comparables."
        f"</p>"
    )

    if deals:

        html_body += (
            "<h2>🔥 Opportunités</h2>"
        )

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

            safe_url = html.escape(
                url,
                quote=True,
            )

            category_label = (
                get_category_label(deal)
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
                f"{deal['classification']} — "
                f"{category_label} — "
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

            if deal["category"] == "clothing":

                size = html.escape(
                    str(
                        item.get(
                            "size_title",
                            "",
                        )
                    )
                )

                html_body += (
                    f"Taille : <b>{size}</b>"
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

                html_body += (
                    f'<a href="{safe_url}">'
                    f"Voir l'annonce"
                    f"</a>"
                )

            html_body += (
                "</div>"
            )

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

def notify_discord(deal):

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

    category_label = (
        get_category_label(deal)
    )

    description = (

        f"{category_label}\n"

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

    if deal["category"] == "clothing":

        description += (
            f"\nTaille : "
            f"{item.get('size_title', '')}"
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

def print_deal(deal):

    item = deal["item"]

    print(
        "\n"
        + "=" * 70
    )

    print(
        deal["classification"],
        f"SCORE {deal['score']}/100",
    )

    print(
        get_category_label(deal)
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

    if deal["category"] == "clothing":

        print(
            f"Taille      : "
            f"{item.get('size_title', '')}"
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
        "      VINTED RESALE SCANNER V7\n"
        "      ⚽ FOOT VINTAGE EUROPEEN\n"
        "      👕 VETEMENTS HOMME MARQUES\n"
        "      🧸 LOTS FUNKO POP\n"
        "==================================================\n"
    )

    print(
        f"Budget simulé : "
        f"{STARTING_BUDGET:.2f} €"
    )

    print(
        "CATEGORIES :"
    )

    print(
        "⚽ Football vintage européen"
    )

    print(
        "👕 Vêtements homme : "
        "Ralph Lauren / Carhartt / Nike / "
        "Lacoste / Burberry / C.P. Company / "
        "Stone Island / Stüssy / Patagonia / "
        "Fred Perry / The North Face / Adidas"
    )

    print(
        "🧸 Lots Funko Pop uniquement"
    )

    print(
        "🏀 NBA : SUPPRIME"
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
        "Vêtements : tailles adultes "
        "S / M / L / XL / XXL / 2XL / 3XL"
    )

    print(
        "Etats acceptés : "
        "Très bon état / "
        "Neuf sans étiquette / "
        "Neuf avec étiquette"
    )

    print(
        "Pas d'enfants / juniors."
    )

    print(
        "Pas de sneakers."
    )

    print(
        "Pas de streetwear général."
    )

    print(
        "Pas de NBA / NFL / MLB / NHL."
    )

    print(
        "Pas de Funko individuelles."
    )

    print(
        "Pas de protections / boîtes vides / accessoires Funko."
    )

    COMPARABLE_CACHE.clear()

    reset_rejection_stats()

    notification_state = (
        load_notification_state()
    )

    run_seen = set()

    all_deals = []

    domains = DOMAINS[:]

    random.shuffle(
        domains
    )

    for domain in domains:

        deals = scan_domain(
            domain,
            run_seen,
            STARTING_BUDGET,
        )

        all_deals.extend(
            deals
        )

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

            fresh_deals.append(
                deal
            )

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

        print_deal(
            deal
        )

    email_deals = all_deals[
        :MAX_EMAIL_DEALS
    ]

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

        if (
            discord_count
            >= MAX_DISCORD_ALERTS
        ):
            break

        if deal["score"] < 70:
            continue

        sent = notify_discord(
            deal
        )

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
        "Doublons filtrés : ACTIFS"
    )

    print(
        "NBA : DESACTIVE"
    )

    print(
        "Football vintage : ACTIF"
    )

    print(
        "Vêtements homme : ACTIF"
    )

    print(
        "Lots Funko Pop : ACTIF"
    )

    print(
        "Notification répétée : "
        "baisse de prix importante, "
        "forte amélioration du score "
        "ou après "
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
