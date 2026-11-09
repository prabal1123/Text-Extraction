import re

LAYOUT_MAPPING = {
    'Time Trial': 'timed',
    'Ind. Pursuit': 'timed',
    'Individual Pursuit': 'timed',
    'Team Sprint': 'team',
    'Team Pursuit': 'team',
    'Sprint': 'placing',
    'Keirin': 'placing',
    'Scratch': 'placing',
    'Elimination': 'placing',
    'Madison': 'points',
    'Point Race': 'points',
    'Points Race': 'points',
    'Omnium': 'points'
}

def classify_communique(header_text):
    data = {
        'number': None, 'race_type': 'Unknown', 'category': 'Unknown',
        'age_group': 'Unknown', 'gender': 'Unknown', 'stage': None,
        'distance': None, 'layout_family': 'unknown', 'race_date': None
    }
    
    # 1. Communique Number (Handles "Communique No. 22", "No: 64", "Communique - 7", "Last Communique 61")
    num_match = re.search(r'(?:Communique|No\.?|No\s*[:\-]|Comm\.)\s*[\-\–]?\s*(\d+(?:\s*\(?Revised\)?|\s*Rev)?)', header_text, re.IGNORECASE)
    if num_match:
        data['number'] = num_match.group(1).strip()
        
    # 2. Race Date 
    date_match = re.search(r'([A-Za-z]+,\s*[A-Za-z]+\.?\s*\d{1,2},?\s*\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})', header_text)
    if date_match:
        data['race_date'] = date_match.group(1).strip()

    # 3. Distance
    dist_match = re.search(r'(?:Distance|Race Distance)\s*:\s*(\d+\s*(?:Km|Mtrs|Laps)\.?)', header_text, re.IGNORECASE)
    if dist_match:
        data['distance'] = dist_match.group(1).strip()

    # 4. Gender & Age Group
    if re.search(r'\b(Men|Boys)\b', header_text, re.IGNORECASE):
        data['gender'] = 'Men'
    elif re.search(r'\b(Women|Girls)\b', header_text, re.IGNORECASE):
        data['gender'] = 'Women'
        
    if re.search(r'\bElite\b', header_text, re.IGNORECASE):
        data['age_group'] = 'Elite'
    elif re.search(r'\bSub\s*Junior\b', header_text, re.IGNORECASE):
        data['age_group'] = 'Sub Junior'
    elif re.search(r'\bJunior\b', header_text, re.IGNORECASE):
        data['age_group'] = 'Junior'
    elif re.search(r'\bYouth\b', header_text, re.IGNORECASE):
        data['age_group'] = 'Youth'
        
    if data['gender'] != 'Unknown' and data['age_group'] != 'Unknown':
        data['category'] = f"{data['gender']} {data['age_group']}"
    elif data['gender'] != 'Unknown':
         data['category'] = f"{data['gender']} (Implied)"
        
    # 5. Race Type & Layout Family
    for race_key in sorted(LAYOUT_MAPPING.keys(), key=lambda k: (k != 'Omnium', -len(k))):
        if re.search(r'\b' + re.escape(race_key) + r'\b', header_text, re.IGNORECASE):
            data['race_type'] = race_key
            data['layout_family'] = LAYOUT_MAPPING[race_key]
            break

    # Standardize names
    if data['race_type'] in ['Ind. Pursuit', 'Individual Pursuit']:
        data['race_type'] = 'Individual Pursuit'
    if data['race_type'] == 'Point Race':
        data['race_type'] = 'Points Race'

    # 6. Stage
    stage_match = re.search(r'(Qualifying|Final|Heats|Round \d+)', header_text, re.IGNORECASE)
    if stage_match:
        data['stage'] = stage_match.group(1).capitalize()

    return data
