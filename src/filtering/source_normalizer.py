"""Modulo per la canonicalizzazione e normalizzazione dei nomi fonte (RF-02, RF-08).

Fornisce la funzione `normalize_source_name(raw_source: str) -> str` per uniformare
varianti minuscole/maiuscole, suffissi di dominio (.it, .com) ed equivalenze tra
brand editoriali e domini estratti.
"""

# Mappa delle equivalenze tra varianti di nome/dominio e il nome brand canonico
CANONICAL_SOURCE_MAP: dict[str, str] = {
    # Testate mirate ed equivalenti generalisti
    "ansa": "ansa_salute",
    "ansa.it": "ansa_salute",
    "ansa_salute": "ansa_salute",
    "adnkronos": "adnkronos_salute",
    "adnkronos.com": "adnkronos_salute",
    "adnkronos_salute": "adnkronos_salute",
    
    # Gruppo Citynews / Today
    "latinatoday": "LatinaToday",
    "latinatoday.it": "LatinaToday",
    "cagliaritoday": "CagliariToday",
    "cagliaritoday.it": "CagliariToday",
    "trevisotoday": "TrevisoToday",
    "trevisotoday.it": "TrevisoToday",
    "padovaoggi": "PadovaOggi",
    "padovaoggi.it": "PadovaOggi",
    "vicenzatoday": "VicenzaToday",
    "vicenzatoday.it": "VicenzaToday",
    "veneziatoday": "VeneziaToday",
    "veneziatoday.it": "VeneziaToday",
    "veronatoday": "VeronaToday",
    "veronatoday.it": "VeronaToday",
    "roma-today": "RomaToday",
    "romatoday.it": "RomaToday",

    # Sardiniapost
    "sardiniapost": "Sardiniapost.it",
    "sardiniapost.it": "Sardiniapost.it",

    # Mondosanità
    "mondosanita": "Mondosanità",
    "mondosanita.it": "Mondosanità",
    "mondosanità": "Mondosanità",

    # RaiNews
    "rainews": "RaiNews",
    "rainews.it": "RaiNews",

    # Casteddu Online
    "castedduonline": "Casteddu On Line",
    "castedduonline.it": "Casteddu On Line",
    "casteddu on line": "Casteddu On Line",

    # Corriere della Sera & edizioni locali
    "corriere": "Corriere della Sera",
    "corriere.it": "Corriere della Sera",
    "corriere della sera": "Corriere della Sera",
    "corrieredelveneto.corriere.it": "Corriere del Veneto",
    "corriere del veneto": "Corriere del Veneto",

    # L'Unione Sarda
    "unionesarda.it": "L'Unione Sarda",
    "lunionesarda.it": "L'Unione Sarda",
    "l'unione sarda": "L'Unione Sarda",
    "l'unione sarda.it": "L'Unione Sarda",

    # h24 notizie
    "h24notizie.com": "h24 notizie",
    "h24 notizie": "h24 notizie",

    # FNOB / Biologi
    "fnob.it": "Federazione Nazionale degli Ordini dei Biologi",
    "federazione nazionale degli ordini dei biologi": "Federazione Nazionale degli Ordini dei Biologi",
    "federazione nazionale ordini dei biologi": "Federazione Nazionale degli Ordini dei Biologi",

    # Altri media noti
    "vietnam.vn": "Vietnam.vn",
    "kalaritana": "Kalaritana Media",
    "kalaritana media": "Kalaritana Media",
    "kalaritana.it": "Kalaritana Media",
    "telefriuli": "Telefriuli",
    "telefriuli.it": "Telefriuli",
    "venetouno": "VenetoUno",
    "venetouno.it": "VenetoUno",
    "la repubblica": "la Repubblica",
    "repubblica.it": "la Repubblica",
    "il post": "ilpost",
    "ilpost.it": "ilpost",
    "ilpost": "ilpost",
    "il sole 24 ore": "Il Sole 24 Ore",
    "ilsole24ore.com": "Il Sole 24 Ore",
    "il gazzettino": "Il Gazzettino",
    "gazzettino.it": "Il Gazzettino",
    "la nuova sardegna": "La Nuova Sardegna",
    "lanuovasardegna.it": "La Nuova Sardegna",
    "sky tg24": "Sky TG24",
    "tg24.sky.it": "Sky TG24",
}


def normalize_source_name(raw_source: str | None) -> str:
    """Normalizza e canonicalizza il nome di una fonte giornalistica.

    1. Rimuove spazi vuoti iniziali/finali.
    2. Converte la stringa in minuscolo per il confronto case-insensitive.
    3. Cerca nella mappa `CANONICAL_SOURCE_MAP` la forma canonica associata.
    4. Se non presente in mappa e se si tratta di un dominio (es. "sito.it"), rimuove il prefisso "www."
       e verifica nuovamente la mappa.
    5. Se non riconosciuto, restituisce il valore grezzo ripulito dagli spazi.
    """
    if not raw_source:
        return "google_news"

    cleaned = raw_source.strip()
    if not cleaned:
        return "google_news"

    key = cleaned.lower()

    # Match diretto nella mappa
    if key in CANONICAL_SOURCE_MAP:
        return CANONICAL_SOURCE_MAP[key]

    # Se la chiave inizia con www., tenta senza www.
    if key.startswith("www."):
        key_no_www = key.removeprefix("www.")
        if key_no_www in CANONICAL_SOURCE_MAP:
            return CANONICAL_SOURCE_MAP[key_no_www]

    # Valore di riserva: mantiene il dato grezzo ripulito dagli spazi
    return cleaned
