"""Reference tables for the ships layer. Edit freely; a missing entry just means a blank in the panel."""

# The first three digits of a ship's MMSI number (the "MID") say which country registered the radio.
MID = {}
for _c, _mids in {
    "Albania": [201], "Andorra": [202], "Austria": [203], "Portugal (Azores)": [204], "Belgium": [205], "Belarus": [206], "Bulgaria": [207], "Vatican": [208],
    "Cyprus": [209, 210, 212], "Germany": [211, 218], "Georgia": [213], "Moldova": [214], "Malta": [215, 229, 248, 249, 256], "Armenia": [216],
    "Denmark": [219, 220], "Spain": [224, 225], "France": [226, 227, 228], "Finland": [230], "Faroe Islands": [231], "United Kingdom": [232, 233, 234, 235],
    "Gibraltar": [236], "Greece": [237, 239, 240, 241], "Croatia": [238], "Morocco": [242], "Hungary": [243], "Netherlands": [244, 245, 246], "Italy": [247],
    "Ireland": [250], "Iceland": [251], "Liechtenstein": [252], "Luxembourg": [253], "Monaco": [254], "Portugal (Madeira)": [255], "Norway": [257, 258, 259],
    "Poland": [261], "Montenegro": [262], "Portugal": [263], "Romania": [264], "Sweden": [265, 266], "Slovakia": [267], "San Marino": [268], "Switzerland": [269],
    "Czechia": [270], "Turkey": [271], "Ukraine": [272], "Russia": [273], "North Macedonia": [274], "Latvia": [275], "Estonia": [276], "Lithuania": [277],
    "Slovenia": [278], "Serbia": [279], "Anguilla": [301], "United States": [303, 338, 366, 367, 368, 369], "Antigua and Barbuda": [304, 305],
    "Cura\u00e7ao / Sint Maarten": [306], "Aruba": [307], "Bahamas": [308, 309, 311], "Bermuda": [310], "Belize": [312], "Barbados": [314], "Canada": [316],
    "Cayman Islands": [319], "Costa Rica": [321], "Cuba": [323], "Dominica": [325], "Dominican Republic": [327], "Guadeloupe": [329], "Grenada": [330],
    "Greenland": [331], "Guatemala": [332], "Honduras": [334], "Haiti": [336], "Jamaica": [339], "Saint Kitts and Nevis": [341], "Saint Lucia": [343],
    "Mexico": [345], "Martinique": [347], "Montserrat": [348], "Nicaragua": [350], "Panama": [351, 352, 353, 354, 355, 356, 357, 370, 371, 372, 373, 374],
    "Puerto Rico": [358], "El Salvador": [359], "Trinidad and Tobago": [362], "Turks and Caicos": [364], "Saint Vincent and the Grenadines": [375, 376, 377],
    "British Virgin Islands": [378], "US Virgin Islands": [379], "Afghanistan": [401], "Saudi Arabia": [403], "Bangladesh": [405], "Bahrain": [408],
    "China": [412, 413, 414], "Taiwan": [416], "Sri Lanka": [417], "India": [419], "Iran": [422], "Azerbaijan": [423], "Iraq": [425], "Israel": [428],
    "Japan": [431, 432], "Turkmenistan": [434], "Kazakhstan": [436], "Uzbekistan": [437], "Jordan": [438], "South Korea": [440, 441], "Palestine": [443],
    "North Korea": [445], "Kuwait": [447], "Lebanon": [450], "Macao": [453], "Maldives": [455], "Mongolia": [457], "Nepal": [459], "Oman": [461], "Pakistan": [463],
    "Qatar": [466], "Syria": [468], "United Arab Emirates": [470, 471], "Yemen": [473, 475], "Hong Kong": [477], "Bosnia and Herzegovina": [478],
    "Australia": [503], "Myanmar": [506], "Brunei": [508], "Micronesia": [510], "Palau": [511], "New Zealand": [512], "Cambodia": [514, 515], "Cook Islands": [518],
    "Fiji": [520], "Indonesia": [525], "Kiribati": [529], "Laos": [531], "Malaysia": [533], "Marshall Islands": [538], "New Caledonia": [540], "Nauru": [544],
    "French Polynesia": [546], "Philippines": [548], "Papua New Guinea": [553], "Solomon Islands": [557], "Samoa": [561], "Singapore": [563, 564, 565, 566],
    "Thailand": [567], "Tonga": [570], "Tuvalu": [572], "Vietnam": [574], "Vanuatu": [576, 577], "South Africa": [601], "Angola": [603], "Algeria": [605],
    "Benin": [610], "Botswana": [611], "Cameroon": [613], "Congo": [615], "Comoros": [616, 620], "Cabo Verde": [617], "C\u00f4te d'Ivoire": [619], "Djibouti": [621],
    "Egypt": [622], "Ethiopia": [624], "Eritrea": [625], "Gabon": [626], "Ghana": [627], "Gambia": [629], "Guinea-Bissau": [630], "Equatorial Guinea": [631],
    "Guinea": [632], "Kenya": [634], "Liberia": [636, 637], "Libya": [642], "Mauritius": [645], "Madagascar": [647], "Mozambique": [650], "Mauritania": [654],
    "Nigeria": [657], "Namibia": [659], "Senegal": [663], "Seychelles": [664], "Somalia": [666], "Sierra Leone": [667], "Sudan": [662], "Tunisia": [672],
    "Tanzania": [674, 677], "DR Congo": [676], "Zambia": [678], "Zimbabwe": [679], "Argentina": [701], "Brazil": [710], "Bolivia": [720], "Chile": [725],
    "Colombia": [730], "Ecuador": [735], "Falkland Islands": [740], "Guyana": [750], "Paraguay": [755], "Peru": [760], "Suriname": [765], "Uruguay": [770],
    "Venezuela": [775],
}.items():
    for _m in _mids:
        MID[_m] = _c

# AIS ship type code -> (our category, plain description)
CATEGORIES = ["cargo", "tanker", "passenger", "fishing", "service", "pleasure", "highspeed", "military", "other"]
CATEGORY_LABEL = {"cargo": "Cargo ships", "tanker": "Tankers", "passenger": "Passenger ships", "fishing": "Fishing", "service": "Tugs and service vessels",
                  "pleasure": "Sailing and pleasure craft", "highspeed": "High-speed craft", "military": "Military and law enforcement", "other": "Other"}
SPECIAL = {30: ("fishing", "Fishing vessel"), 31: ("service", "Towing vessel"), 32: ("service", "Towing vessel (large)"), 33: ("service", "Dredger or underwater works"),
           34: ("service", "Diving support vessel"), 35: ("military", "Military vessel"), 36: ("pleasure", "Sailing vessel"), 37: ("pleasure", "Pleasure craft"),
           50: ("service", "Pilot vessel"), 51: ("service", "Search and rescue vessel"), 52: ("service", "Tug"), 53: ("service", "Port tender"),
           54: ("service", "Anti-pollution vessel"), 55: ("military", "Law enforcement vessel"), 58: ("service", "Medical transport"), 59: ("service", "Special craft")}
HOLD = {0: "", 1: "Carrying dangerous goods, category X", 2: "Carrying dangerous goods, category Y", 3: "Carrying dangerous goods, category Z", 4: "Carrying dangerous goods, category OS"}


def category_of(code):
    code = int(code or 0)
    if code in SPECIAL:
        return SPECIAL[code][0]
    if 60 <= code <= 69:
        return "passenger"
    if 70 <= code <= 79:
        return "cargo"
    if 80 <= code <= 89:
        return "tanker"
    if 20 <= code <= 29 or 40 <= code <= 49:
        return "highspeed"
    return "other"


def type_text(code):
    code = int(code or 0)
    if code in SPECIAL:
        return SPECIAL[code][1]
    base = {6: "Passenger ship", 7: "Cargo ship", 8: "Tanker", 4: "High-speed craft", 2: "Wing-in-ground craft"}.get(code // 10)
    if base:
        extra = HOLD.get(code % 10, "")
        return base + (" \u00b7 " + extra if extra else "")
    return "Not reported" if code in (0, 90) else "Other vessel"


NAV_STATUS = {0: "Under way using engine", 1: "At anchor", 2: "Not under command", 3: "Restricted manoeuvrability", 4: "Constrained by draught", 5: "Moored",
              6: "Aground", 7: "Engaged in fishing", 8: "Under way sailing", 11: "Towing astern", 12: "Pushing or towing alongside", 14: "Emergency beacon active", 15: "Not defined"}

# Busy ports that the UN/LOCODE list gives no position for: (code, name, latitude, longitude). Used only when the list has none.
PORT_EXTRAS = [
    ("CNSHA", "Shanghai", 31.38, 121.50), ("CNNGB", "Ningbo", 29.94, 121.85), ("CNSZX", "Shenzhen", 22.57, 114.27), ("CNTAO", "Qingdao", 36.07, 120.32),
    ("CNTSN", "Tianjin", 38.98, 117.75), ("CNGZG", "Guangzhou", 23.00, 113.50), ("CNXMN", "Xiamen", 24.45, 118.07), ("CNDLC", "Dalian", 38.93, 121.65),
    ("CNZOS", "Zhoushan", 30.00, 122.10), ("CNRZH", "Rizhao", 35.40, 119.55), ("CNLYG", "Lianyungang", 34.75, 119.40), ("HKHKG", "Hong Kong", 22.31, 114.12),
    ("TWKHH", "Kaohsiung", 22.60, 120.28), ("KRPUS", "Busan", 35.10, 129.04), ("JPTYO", "Tokyo", 35.62, 139.78), ("JPNGO", "Nagoya", 35.05, 136.85),
    ("JPOSA", "Osaka", 34.65, 135.43), ("JPUKB", "Kobe", 34.67, 135.20), ("AEJEA", "Jebel Ali", 25.01, 55.06), ("AEDXB", "Dubai", 25.27, 55.30),
    ("AEAUH", "Abu Dhabi", 24.50, 54.38), ("AEFJR", "Fujairah", 25.17, 56.36), ("AEKHL", "Khalifa Port", 24.80, 54.65), ("SAJED", "Jeddah", 21.48, 39.17),
    ("SADMM", "Dammam", 26.45, 50.20), ("SAJUB", "Jubail", 27.00, 49.70), ("SARTA", "Ras Tanura", 26.65, 50.15), ("OMSLL", "Salalah", 16.95, 54.00),
    ("OMSOH", "Sohar", 24.50, 56.60), ("KWKWI", "Kuwait", 29.37, 47.97), ("IRBND", "Bandar Abbas", 27.15, 56.25), ("IQBSR", "Basra", 30.50, 47.80),
    ("INNSA", "Nhava Sheva", 18.95, 72.95), ("INMUN", "Mundra", 22.74, 69.70), ("INMAA", "Chennai", 13.09, 80.30), ("INCOK", "Cochin", 9.97, 76.27),
    ("LKCMB", "Colombo", 6.95, 79.85), ("MYPKG", "Port Klang", 3.00, 101.38), ("MYTPP", "Tanjung Pelepas", 1.36, 103.55), ("IDJKT", "Jakarta", -6.10, 106.88),
    ("IDSUB", "Surabaya", -7.20, 112.73), ("THLCH", "Laem Chabang", 13.08, 100.90), ("VNSGN", "Ho Chi Minh City", 10.77, 106.79), ("VNHPH", "Haiphong", 20.85, 106.68),
    ("PHMNL", "Manila", 14.58, 120.97), ("AUSYD", "Sydney", -33.85, 151.20), ("AUMEL", "Melbourne", -37.83, 144.92), ("AUBNE", "Brisbane", -27.38, 153.17),
    ("AUFRE", "Fremantle", -32.05, 115.74), ("NZAKL", "Auckland", -36.84, 174.77), ("ZADUR", "Durban", -29.87, 31.03), ("ZACPT", "Cape Town", -33.91, 18.43),
    ("NGAPP", "Apapa", 6.45, 3.37), ("NGLOS", "Lagos", 6.45, 3.38), ("GHTEM", "Tema", 5.63, 0.02), ("EGPSD", "Port Said", 31.26, 32.30), ("EGALY", "Alexandria", 31.18, 29.88),
    ("EGSUZ", "Suez", 29.95, 32.55), ("MAPTM", "Tanger Med", 35.89, -5.50), ("ESVLC", "Valencia", 39.45, -0.32), ("ESALG", "Algeciras", 36.13, -5.43),
    ("ESBCN", "Barcelona", 41.35, 2.17), ("ITGOA", "Genoa", 44.40, 8.92), ("ITGIT", "Gioia Tauro", 38.43, 15.90), ("FRMRS", "Marseille", 43.33, 5.35),
    ("FRLEH", "Le Havre", 49.48, 0.11), ("BEANR", "Antwerp", 51.27, 4.35), ("BEZEE", "Zeebrugge", 51.33, 3.20), ("DEHAM", "Hamburg", 53.53, 9.97),
    ("DEBRV", "Bremerhaven", 53.55, 8.55), ("GBFXT", "Felixstowe", 51.95, 1.30), ("GBSOU", "Southampton", 50.90, -1.40), ("GBLGP", "London Gateway", 51.50, 0.50),
    ("NLAMS", "Amsterdam", 52.40, 4.85), ("PLGDN", "Gdansk", 54.40, 18.67), ("GRPIR", "Piraeus", 37.94, 23.63), ("TRMER", "Mersin", 36.78, 34.63),
    ("TRIST", "Istanbul", 41.02, 28.97), ("RULED", "St Petersburg", 59.88, 30.20), ("RUNVS", "Novorossiysk", 44.72, 37.78), ("USLAX", "Los Angeles", 33.73, -118.26),
    ("USLGB", "Long Beach", 33.75, -118.21), ("USOAK", "Oakland", 37.80, -122.30), ("USSEA", "Seattle", 47.60, -122.34), ("USSAV", "Savannah", 32.08, -81.09),
    ("USCHS", "Charleston", 32.78, -79.93), ("USMIA", "Miami", 25.77, -80.17), ("USMSY", "New Orleans", 29.93, -90.06), ("USORF", "Norfolk", 36.85, -76.30),
    ("USBAL", "Baltimore", 39.27, -76.58), ("CAVAN", "Vancouver", 49.29, -123.11), ("CAMTR", "Montreal", 45.50, -73.55), ("CAHAL", "Halifax", 44.65, -63.57),
    ("MXZLO", "Manzanillo", 19.05, -104.32), ("MXVER", "Veracruz", 19.20, -96.13), ("PABLB", "Balboa", 8.95, -79.57), ("PAONX", "Cristobal", 9.35, -79.90),
    ("BRRIO", "Rio de Janeiro", -22.90, -43.17), ("ARBUE", "Buenos Aires", -34.60, -58.37), ("CLVAP", "Valparaiso", -33.03, -71.63), ("CLSAI", "San Antonio", -33.59, -71.62),
    ("PECLL", "Callao", -12.05, -77.15), ("COCTG", "Cartagena", 10.42, -75.53), ("ECGYE", "Guayaquil", -2.28, -79.92), ("NOMON", "Mongstad", 60.81, 5.03),
]
