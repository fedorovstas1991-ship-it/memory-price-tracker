BRAND_PATTERNS = {
    'Samsung': ['K4', 'K9', 'KLM', 'KLU', 'KLD', 'K4F', 'K4A', 'K4R', 'K4U'],
    'Micron': ['MT', 'MTFC'],
    'SK Hynix': ['H5', 'H9', 'HY'],
    'Kioxia': ['TH', 'TC58'],
    'Winbond': ['W25Q', 'W29N'],
    'GigaDevice': ['GD25', 'GD5F'],
    'Macronix': ['MX25', 'MX29'],
    'ISSI': ['IS61', 'IS62', 'IS66'],
    'Nanya': ['NT5'],
    'Alliance': ['AS4C'],
}


def extract_brand(part_number: str, description: str = '') -> str:
    pn = part_number.upper()
    for brand, prefixes in BRAND_PATTERNS.items():
        for prefix in prefixes:
            if pn.startswith(prefix):
                return brand
    # Try description
    desc_upper = description.upper()
    for brand in BRAND_PATTERNS:
        if brand.upper() in desc_upper:
            return brand
    return 'Other'
