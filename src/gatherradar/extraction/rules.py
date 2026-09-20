"""The rule engine's vocabulary and weights, in one place.

Everything the deterministic discovery provider believes about Persian and English
event language is data in this module — no keyword list is allowed to live inside a
function elsewhere. Tuning the engine means editing values here, and a reviewer can
read what the engine knows without reading how it works.

Phrases are written the way a person writes them. `text.compile_vocabulary` folds
them the same way it folds observed captions, so "کافه‌گالری" and "کافه گالری" are
one entry, and matching happens on whole tokens: "رویدادهای" never counts as
"رویداد", and "کلاسیک" never counts as "کلاس".
"""

from __future__ import annotations

# --------------------------------------------------------------------------------------
# Event terminology
# --------------------------------------------------------------------------------------

# Words that name an occurrence directly. One of these alone is still not an event.
EVENT_TERMS_STRONG: tuple[str, ...] = (
    "رویداد",
    "ایونت",
    "ورکشاپ",
    "کارگاه",
    "افتتاحیه",
    "نمایشگاه",
    "کنسرت",
    "دورهمی",
    "نشست",
    "همایش",
    "جشنواره",
    "فستیوال",
    "بازارچه",
    "اکران",
    "سمینار",
    "وبینار",
    "کنفرانس",
    "رونمایی",
    "event",
    "workshop",
    "exhibition",
    "concert",
    "meetup",
    "conference",
    "festival",
    "screening",
    "webinar",
    "seminar",
    "opening night",
    "opening reception",
)

# Words that often accompany an event but also describe ordinary business: a venue
# has classes and performances every week. Worth less on their own.
EVENT_TERMS_WEAK: tuple[str, ...] = (
    "اجرا",
    "تور",
    "کلاس",
    "جلسه",
    "موسیقی زنده",
    "سخنرانی",
    "افتتاح",
    "talk",
    "class",
    "live music",
    "tour",
    "session",
    "opening",
)

# Category is provisional: the taxonomy is still an open product decision, so this
# maps only terms whose category wording is unambiguous.
EVENT_CATEGORIES: dict[str, str] = {
    "کارگاه": "workshop",
    "ورکشاپ": "workshop",
    "کلاس": "workshop",
    "workshop": "workshop",
    "class": "workshop",
    "نمایشگاه": "exhibition",
    "افتتاحیه": "exhibition",
    "رونمایی": "exhibition",
    "exhibition": "exhibition",
    "opening night": "exhibition",
    "opening reception": "exhibition",
    "کنسرت": "concert",
    "موسیقی زنده": "concert",
    "concert": "concert",
    "live music": "concert",
    "جشنواره": "festival",
    "فستیوال": "festival",
    "festival": "festival",
    "همایش": "conference",
    "سمینار": "conference",
    "کنفرانس": "conference",
    "وبینار": "conference",
    "conference": "conference",
    "seminar": "conference",
    "webinar": "conference",
    "سخنرانی": "talk",
    "نشست": "talk",
    "talk": "talk",
    "دورهمی": "meetup",
    "meetup": "meetup",
    "اکران": "screening",
    "screening": "screening",
    "بازارچه": "market",
    "تور": "tour",
    "tour": "tour",
}

PLACE_CATEGORIES: dict[str, str] = {
    "گالری": "gallery",
    "نگارخانه": "gallery",
    "کافه گالری": "gallery",
    "gallery": "gallery",
    "موزه": "museum",
    "museum": "museum",
    "فضای هنری": "art_space",
    "art space": "art_space",
    "art center": "art_space",
    "art centre": "art_space",
    "خانه هنرمندان": "cultural_center",
    "مرکز فرهنگی": "cultural_center",
    "فرهنگسرا": "cultural_center",
    "cultural center": "cultural_center",
    "cultural centre": "cultural_center",
}

# --------------------------------------------------------------------------------------
# Temporal signals — detected, never normalized. Jalali conversion is a later step.
# --------------------------------------------------------------------------------------

PERSIAN_WEEKDAYS: tuple[str, ...] = (
    "شنبه",
    "یکشنبه",
    "یک شنبه",
    "دوشنبه",
    "دو شنبه",
    "سه شنبه",
    "چهارشنبه",
    "چهار شنبه",
    "پنجشنبه",
    "پنج شنبه",
    "جمعه",
)

ENGLISH_WEEKDAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

JALALI_MONTHS: tuple[str, ...] = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)

GREGORIAN_MONTHS: tuple[str, ...] = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

RELATIVE_DATES: tuple[str, ...] = (
    "امروز",
    "امشب",
    "فردا",
    "فردا شب",
    "پس فردا",
    "آخر هفته",
    "آخر این هفته",
    "این هفته",
    "هفته آینده",
    "هفته جاری",
    "این جمعه",
    "این ماه",
    "ماه آینده",
    "امسال",
    "today",
    "tonight",
    "tomorrow",
    "this weekend",
    "next weekend",
    "this week",
    "next week",
)

DATE_TERMS: tuple[str, ...] = (
    *PERSIAN_WEEKDAYS,
    *ENGLISH_WEEKDAYS,
    *JALALI_MONTHS,
    *GREGORIAN_MONTHS,
    *RELATIVE_DATES,
)

# Words that are also ordinary vocabulary; a date reading needs an adjacent number.
MONTHS_NEEDING_A_NUMBER: frozenset[str] = frozenset({"دی", "may", "march"})

TIME_TERMS: tuple[str, ...] = ("ساعت", "از ساعت", "تا ساعت")

# Time expressions are shaped, not vocabulary, so they are regexes over the folded
# text: "18:30", "ساعت ۱۸", "از ساعت ۱۶ تا ۲۲", "7 pm".
TIME_PATTERNS: tuple[str, ...] = (
    r"\b\d{1,2}:\d{2}\b",
    r"ساعت\s*\d{1,2}",
    r"\b\d{1,2}\s*(?:am|pm)\b",
)

# Numeric date shapes: "1404/06/19", "19-06-1404", "9/25".
DATE_PATTERNS: tuple[str, ...] = (r"\b\d{1,4}[/\-]\d{1,2}(?:[/\-]\d{1,4})?\b",)

# --------------------------------------------------------------------------------------
# Place, attendance, retrospective, registration, and price vocabulary
# --------------------------------------------------------------------------------------

PLACE_TERMS: tuple[str, ...] = (
    "گالری",
    "نگارخانه",
    "موزه",
    "فضای هنری",
    "خانه هنرمندان",
    "مرکز فرهنگی",
    "فرهنگسرا",
    "کافه گالری",
    "gallery",
    "museum",
    "art space",
    "cultural center",
    "cultural centre",
    "art center",
    "art centre",
)

# Descriptive / visit context: how a place talks about itself when it is not
# announcing a dated occurrence.
PLACE_CONTEXT_TERMS: tuple[str, ...] = (
    "معرفی گالری",
    "معرفی موزه",
    "معرفی",
    "آشنایی با",
    "پیشنهاد برای بازدید",
    "فضایی برای",
    "یکی از گالری‌های",
    "یکی از موزه‌های",
    "ساعات کاری",
    "ساعت کاری",
    "ساعات بازدید",
    "ساعت بازدید",
    "همه روزه",
    "هر روز",
    "به جز روزهای تعطیل",
    "واقع در",
    "پذیرای شما",
    "پذیرای بازدیدکنندگان",
    "بازدید رایگان",
    "opening hours",
    "open daily",
    "open every day",
    "located in",
    "located at",
    "visiting hours",
    "introducing",
    "discover",
    "meet the gallery",
    "a gallery in",
    "a museum in",
    "worth visiting",
)

# A place head may follow one of these phrases at the start of its line and still
# form a defensible name: "معرفی گالری نگاه" names "گالری نگاه". Classification
# separately requires a recognized place term, so "معرفی محصول جدید" remains other.
PLACE_NAME_PREFIX_TERMS: tuple[str, ...] = (
    "معرفی",
    "آشنایی با",
    "introducing",
    "discover",
    "meet the",
)

OPENING_HOURS_TERMS: tuple[str, ...] = (
    "ساعات کاری",
    "ساعت کاری",
    "ساعات بازدید",
    "ساعت بازدید",
    "همه روزه",
    "هر روز",
    "opening hours",
    "open daily",
    "open every day",
    "visiting hours",
)

# These phrases are ordinary prose unless their own line also carries opening or
# clock evidence. Signal detection applies that context check before they can help
# classify a place or suppress an event date reading.
DAILY_SCHEDULE_TERMS: frozenset[str] = frozenset(
    {
        "همه روزه",
        "هر روز",
        "open daily",
        "open every day",
    }
)

# Being invited to show up. Never enough on its own to create an event.
ATTENDANCE_TERMS: tuple[str, ...] = (
    "منتظرتونن",
    "منتظرتون هستیم",
    "منتظر شما",
    "منتظر شماییم",
    "سر بزنید",
    "سر بزنین",
    "بیاید",
    "بیاین",
    "بیایید",
    "شرکت کنید",
    "شرکت کنین",
    "ثبت نام کنید",
    "حضور",
    "حضور به هم رسانید",
    "برگزار می شود",
    "برگزار میشود",
    "برگزار میشه",
    "برگزار می کنیم",
    "برگزار میکنیم",
    "میزبان",
    "همراه ما باشید",
    "join us",
    "come by",
    "visit us",
    "attend",
    "we are hosting",
    "takes place",
    "come join",
    "save the date",
)

# Evidence that the occurrence is already over. Penalties, not vetoes.
RETROSPECTIVE_TERMS: tuple[str, ...] = (
    "برگزار شد",
    "برگزار شده",
    "برگزار گردید",
    "هفته گذشته",
    "ماه گذشته",
    "سال گذشته",
    "هفته پیش",
    "ماه پیش",
    "سال پیش",
    "پارسال",
    "گزارش تصویری",
    "تصاویر رویداد",
    "عکس های رویداد",
    "مروری بر",
    "خاطره",
    "خاطرات",
    "پشت صحنه",
    "به پایان رسید",
    "تمام شد",
    "تموم شد",
    "last week",
    "last month",
    "last year",
    "behind the scenes",
    "recap",
    "throwback",
    "wrapped up",
    "came to an end",
    "was held",
)

REGISTRATION_TERMS: tuple[str, ...] = (
    "ثبت نام",
    "لینک ثبت نام",
    "رزرو",
    "خرید بلیت",
    "خرید بلیط",
    "تهیه بلیت",
    "تهیه بلیط",
    "بلیت",
    "بلیط",
    "register",
    "registration",
    "booking",
    "rsvp",
    "book your spot",
    "tickets",
    "ticket",
    "sign up",
)

PRICE_TERMS: tuple[str, ...] = (
    "رایگان",
    "ورودی",
    "هزینه",
    "قیمت",
    "تومان",
    "ریال",
    "بدون هزینه",
    "free",
    "price",
    "ticket price",
    "entry",
    "fee",
)

PRICE_LABELS: tuple[str, ...] = (
    "قیمت بلیت",
    "قیمت بلیط",
    "هزینه شرکت",
    "ticket price",
    "ورودی",
    "هزینه",
    "قیمت",
    "price",
    "entry",
    "fee",
)

ONLINE_TERMS: tuple[str, ...] = ("آنلاین", "آن لاین", "انلاین", "online", "virtual")
IN_PERSON_TERMS: tuple[str, ...] = ("حضوری", "in person", "onsite", "on site")
HYBRID_TERMS: tuple[str, ...] = ("حضوری و آنلاین", "آنلاین و حضوری", "hybrid")

# Cities are only ever read from the text itself. A neighborhood never implies one.
KNOWN_CITIES: tuple[str, ...] = (
    "تهران",
    "کرج",
    "کاشان",
    "اصفهان",
    "شیراز",
    "مشهد",
    "تبریز",
    "یزد",
    "رشت",
    "اهواز",
    "کرمان",
    "قم",
    "tehran",
    "karaj",
    "isfahan",
    "esfahan",
    "shiraz",
    "mashhad",
    "tabriz",
    "yazd",
    "rasht",
)

# A map-pin line is accepted as a structured location only when the following
# text contains explicit geographic/address wording (or a written known city).
LOCATION_DETAIL_TERMS: tuple[str, ...] = (
    "خیابان",
    "خ",
    "بلوار",
    "کوچه",
    "بن بست",
    "پلاک",
    "طبقه",
    "واحد",
    "میدان",
    "شهرک",
    "جاده",
    "بزرگراه",
    "محدوده",
    "چهارراه",
    "سه راه",
    "تقاطع",
    "street",
    "st",
    "road",
    "rd",
    "avenue",
    "ave",
    "boulevard",
    "blvd",
    "square",
    "plaza",
    "alley",
    "no",
    "number",
)

# --------------------------------------------------------------------------------------
# Labelled fields
# --------------------------------------------------------------------------------------

ADDRESS_LABELS: tuple[str, ...] = ("آدرس", "ادرس", "نشانی", "address", "location")
VENUE_LABELS: tuple[str, ...] = ("محل برگزاری", "مکان برگزاری", "مکان", "محل", "venue")
AMBIGUOUS_VENUE_LABELS: frozenset[str] = frozenset(
    {"محل برگزاری", "مکان برگزاری", "مکان", "محل"}
)
DATE_LABELS: tuple[str, ...] = ("زمان برگزاری", "تاریخ", "زمان", "date", "time", "when")
CITY_LABELS: tuple[str, ...] = ("شهر", "city")

# Characters an operator writes between a label and its value.
LABEL_SEPARATORS: str = ":：–—-="

# --------------------------------------------------------------------------------------
# Named-event construction
# --------------------------------------------------------------------------------------

# Only terms that can actually head a proper event name. "ایونت" heads one too, and
# the stopword list below is what stops "ایونت نیست" from becoming a name.
NAMED_EVENT_HEAD_TERMS: tuple[str, ...] = (
    "رویداد",
    "ایونت",
    "افتتاحیه",
    "رونمایی",
    "نمایشگاه",
    "کارگاه",
    "ورکشاپ",
    "کنسرت",
    "جشنواره",
    "فستیوال",
    "همایش",
    "سمینار",
    "دورهمی",
    "اکران",
    "بازارچه",
    "نشست",
)

NAMED_PLACE_HEAD_TERMS: tuple[str, ...] = (
    "کافه گالری",
    "گالری",
    "نگارخانه",
    "موزه",
    "فضای هنری",
    "مرکز فرهنگی",
    "فرهنگسرا",
    "gallery",
    "museum",
)

# Grammatical continuations that prove the event term was used inside a sentence
# rather than as the head of a name. "رویداد میتونید" and "رویداد جزو" were the
# observed false positives; this list covers the shape they belong to — verb forms,
# particles, quantifiers, prepositions, pronouns — not just those two phrases.
NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        # verb prefixes and common verb forms
        "می",
        "نمی",
        "میتوانید",
        "میتونید",
        "میتونی",
        "میشه",
        "میشود",
        "میکنیم",
        "میکنه",
        "میاد",
        "دارد",
        "داره",
        "دارند",
        "دارن",
        "داریم",
        "است",
        "هست",
        "هستش",
        "هستند",
        "هستیم",
        "نیست",
        "نیستند",
        "بود",
        "بودند",
        "باشد",
        "باشه",
        "باشید",
        "شد",
        "شده",
        "شود",
        "گردید",
        "خواهد",
        "باید",
        "توانید",
        "تونید",
        "کنید",
        "کنیم",
        "برگزار",
        # classifiers and quantifiers
        "جزو",
        "یکی",
        "یک",
        "چند",
        "همه",
        "هر",
        "خیلی",
        "کلی",
        "بعضی",
        "تعدادی",
        # plural and demonstrative particles left over after folding
        "ها",
        "های",
        "هایی",
        "این",
        "آن",
        "همین",
        "همان",
        # prepositions, conjunctions, pronouns
        "که",
        "برای",
        "در",
        "از",
        "با",
        "به",
        "تا",
        "را",
        "یا",
        "و",
        "هم",
        "بر",
        "روی",
        "طی",
        "توسط",
        "بدون",
        "ما",
        "شما",
        "او",
        "آنها",
        "اونها",
        "من",
        "تو",
        # English equivalents
        "is",
        "was",
        "are",
        "were",
        "will",
        "can",
        "could",
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "and",
        "or",
        "but",
        "not",
        "our",
        "your",
        "their",
        "we",
        "you",
        "they",
        "it",
        "its",
    }
)

# Closed-class words that carry no subject on their own. Used only by the
# meaningful-content guard, which decides whether an observation is worth
# classifying at all.
FUNCTION_WORDS: frozenset[str] = NAME_STOPWORDS | frozenset(
    {
        "اما",
        "ولی",
        "پس",
        "چون",
        "اگر",
        "نیز",
        "so",
        "if",
        "then",
        "because",
        "as",
        "by",
        "from",
        "into",
        "out",
    }
)

MAX_NAME_TOKENS: int = 4
MIN_NAME_TOKEN_LENGTH: int = 2
QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ("«", "»"),
    ("“", "”"),
    ("‘", "’"),
    (""", """),
)

# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------

WEIGHT_EVENT_TERM_STRONG = 2.0
WEIGHT_EVENT_TERM_STRONG_EXTRA = 0.5
MAX_EVENT_TERM_STRONG_EXTRA = 1.0
WEIGHT_EVENT_TERM_WEAK = 1.0
MAX_EVENT_TERM_WEAK = 1.0
WEIGHT_NAMED_EVENT = 2.0
WEIGHT_DATE = 1.5
WEIGHT_TIME = 1.0
WEIGHT_REGISTRATION = 1.5
WEIGHT_ATTENDANCE = 1.0
WEIGHT_PRICE = 0.5
WEIGHT_LOCATION = 0.5

WEIGHT_PLACE_TERM = 2.0
WEIGHT_PLACE_TERM_EXTRA = 0.5
MAX_PLACE_TERM_EXTRA = 1.0
WEIGHT_PLACE_CONTEXT = 1.5
WEIGHT_PLACE_LOCATION = 0.5

WEIGHT_RETROSPECTIVE = 2.0

EVENT_SCORE_THRESHOLD = 3.0
PLACE_SCORE_THRESHOLD = 3.0
