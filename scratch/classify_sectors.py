import json
import re
from pathlib import Path

# Paths
REPO_ROOT = Path("d:/PROSPEKTLAB")
STOCKS_FILE = REPO_ROOT / "Frontend/app/src/data/indianStocks.ts"
SECTORS_FILE = REPO_ROOT / "finagent/data/nifty500_sectors.json"

# Load nifty500 sector lookup
nifty500 = {}
if SECTORS_FILE.exists():
    try:
        with open(SECTORS_FILE, "r", encoding="utf-8") as f:
            nifty500 = json.load(f)
    except Exception as e:
        print(f"Error loading nifty500 sectors: {e}")

# Build symbol/name to sector mapping from nifty500
nifty_sym_map = {}
for isin, data in nifty500.items():
    symbol = data.get("symbol", "").upper().strip()
    sector = data.get("sector", "").strip()
    if symbol and sector:
        nifty_sym_map[symbol] = sector

# Keyword rules for sector classification (expanded for higher coverage)
RULES = [
    # Financial Services
    (r"\b(bank|banking|hdfc|icici|sbi|pnb|uco|idbi|bob|rbl|kotak|axis|yesbank|indusind|canara|federal)\b", "Financial Services"),
    (r"\b(finance|fincorp|housing|finvest|capital|securities|wealth|investment|credit|insurance|general insurance|life insurance|asset management|mutual fund|brokerage|venture|leasing|underwriting|fintech|holding|holdings|microfinance|gold loan|micro finance|financiers|fintrade|amc|wam|chits|chit|microfinance|fin|investment|investments|commercial services|reinsurance)\b", "Financial Services"),
    
    # Healthcare / Pharma
    (r"\b(pharmaceuticals|pharma|therapeutics|drugs|lifesciences|remedies|laboratories|labs|healthcare|hospitals|diagnostics|biotech|biosciences|health|hospital|medica|apothecary|wellness|abbott|pharmalabs|clinic|clinics|biopharma|diagnostics|diagnostic|instruments)\b", "Healthcare"),
    
    # Information Technology
    (r"\b(software|technologies|tech|infotech|computers|systems|consultancy|digital|networks|internet|cyber|telecom|telecommunication|communications|towers|cellular|telephony|mobile|tele|knowledgeware|telecoms)\b", "Information Technology"),
    
    # Metals & Mining
    (r"\b(steel|iron|metals|mining|alloys|aluminum|copper|zinc|ores|minerals|metallurgical|refractories|forge|casting|forgings|ferro|mining|tata steel|jsw|vedanta|coal|exploration|wire|wires|cables|foil|foils|pipe|pipes|sheets)\b", "Metals & Mining"),
    
    # Construction Materials
    (r"\b(cement|concrete|aggregates|clinker|refractories|ceramics|tiles|sanitaryware|asbestos|pipe|pipes|cements|ply|decor|plywood|laminates)\b", "Construction Materials"),
    
    # Oil Gas & Consumable Fuels
    (r"\b(petroleum|gas|refineries|refinery|pipeline|oil|coal|fuels|lubricants|petrochemicals|hpcl|bpcl|iocl|gail|ongc|reliance industries|petro|fuels|lng)\b", "Oil Gas & Consumable Fuels"),
    
    # Power
    (r"\b(power|energy|electricity|generation|transmission|solar|wind|thermal|hydro|green energy|renewables|ntpc|tata power|adanipower|turbine|turbines|hydro)\b", "Power"),
    
    # Chemicals
    (r"\b(chemical|chemicals|petrochemicals|plastics|polymers|dyestuff|fertilizers|pesticides|agro-chemicals|alkalies|pigments|resins|catalysts|fertilisers|carbon|carbon black|organic|chem|surfactants|aether|chlorine|acids|salt|salts|alkali)\b", "Chemicals"),
    
    # Realty
    (r"\b(realty|real estate|properties|estates|developer|township|homes|dlf|prestige|oberoi|godrej prop|lodha|macrotech|estate|lands|land)\b", "Realty"),
    
    # Construction / Infrastructure
    (r"\b(construction|developers|infrastructure|infra|infratech|projects|engineering|housing|contracting|contractors|builders|road|roads|highways|bridges|pipeline|infrabuild|build|structural|concrete)\b", "Construction"),
    
    # Automobile and Auto Components
    (r"\b(motors|automotive|auto|cars|vehicles|tyres|tire|components|brakes|gear|transmissions|pistons|chassis|engine|autoparts|batteries|exide|amara raja|car|motorcycle|scooter|tractor|tractors|wheel|wheels|piston|piston rings|bearings)\b", "Automobile and Auto Components"),
    
    # Consumer Durables
    (r"\b(paints|coatings|jewellers|jewellery|watches|apparel|garments|textiles|clothing|wear|footwear|shoes|furniture|appliances|luggage|durables|crockery|silk|cottons|woollens|denim|retail|fashions|fashion|lifestyle|spintex|textile|cotspin|cotton|cottons|lifestyles|innerwear|yarn|yarns)\b", "Consumer Durables"),
    
    # Consumer Services
    (r"\b(hotel|hotels|resorts|restaurants|restaurant|hospitality|tourism|travel|catering|zomato|paytm|nykaa|delivery|delhivery|e-commerce|logistics|shipping|transport|courier|cargo|ports|port|warehousing|leisure|holidays|airlines|aviation|railways|terminals|terminal)\b", "Consumer Services"),
    
    # Fast Moving Consumer Goods (FMCG)
    (r"\b(foods|beverages|sugar|breweries|distilleries|dairy|agro|tea|coffee|rice|flour|oil|tobacco|cigarettes|fmcg|soap|detergent|shampoo|perfume|cosmetics|biscuits|confectionery|breweries|distillery|spirits|spices|salt|atta|wheat|grain|grains|consumer products|marico|britannia|itc|hul|colgate|distillers|blenders|distillery|distilleries|breweries|brewery|packaged foods|snacks|spices|oil|dairies|vanaspati)\b", "Fast Moving Consumer Goods"),
    
    # Media & Entertainment
    (r"\b(media|entertainment|films|broadcasting|television|tv|radio|music|publishing|news|print|multiplex|multiplexes|cinema|cinemas|theatres|pvr|inox|multiplex|broadcasters|amusement|theme park)\b", "Media & Entertainment"),
    
    # Capital Goods
    (r"\b(machinery|equipment|cables|wires|electricals|transformers|generators|pumps|valves|bearings|industrial|aerospace|defense|missiles|helicopters|turbines|shipbuilders|shipyard|heavy electricals|turbines|boilers|forgings|welding|valves|heaters|ventilation|furnaces|compressors|meters|metering|switchgears|panel|panels|gears|castings)\b", "Capital Goods")
]

def classify_sector(symbol, name):
    symbol = symbol.upper().strip()
    name = name.lower().strip()
    
    # 1) Check if we have a hardcoded nifty500 match
    if symbol in nifty_sym_map:
        return nifty_sym_map[symbol]
        
    # Special cases
    if "physicswallah" in name or symbol == "PWL":
        return "Education Services"
    if "momf" in symbol.lower() or "motilal oswal manufacturing" in name:
        return "Thematic - Manufacturing"
        
    # 2) Run keyword rules
    for pattern, sector in RULES:
        if re.search(pattern, name):
            return sector
            
    # 3) Heuristic: if name ends in "fin" or "bank"
    if name.endswith("bank") or name.endswith("finance"):
        return "Financial Services"
    if name.endswith("pharma") or name.endswith("pharmaceuticals"):
        return "Healthcare"
        
    return "Other"

# Read indianStocks.ts
content = STOCKS_FILE.read_text(encoding="utf-8")

# Extract the array definition block
match = re.search(r"export const INDIAN_STOCKS: StockItem\[\] = \[(.*?)^\s*\];", content, re.DOTALL | re.MULTILINE)
if not match:
    print("Could not find INDIAN_STOCKS array definition")
    exit(1)

array_content = match.group(1)

# Parse entries
entries = re.findall(r"\{\s*\"symbol\":\s*\"([^\"]+)\",\s*\"name\":\s*\"([^\"]+)\",\s*\"sector\":\s*\"([^\"]+)\",\s*\"exchange\":\s*\"([^\"]+)\"\s*\}", array_content)
print(f"Found {len(entries)} stocks in indianStocks.ts")

# Classify and count
stats = {}
modified_entries = []
for symbol, name, sector, exchange in entries:
    new_sector = classify_sector(symbol, name)
    if new_sector == "Other" and sector != "Other" and sector != "General":
        new_sector = sector  # Keep old if classified as Other but had something
    stats[new_sector] = stats.get(new_sector, 0) + 1
    
    # Re-build entry
    entry_str = f'  {{\n    "symbol": "{symbol}",\n    "name": "{name}",\n    "sector": "{new_sector}",\n    "exchange": "{exchange}"\n  }}'
    modified_entries.append(entry_str)

# Print stats
print("Sector distribution after classification:")
for sec, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
    print(f"- {sec}: {count}")

# Replace array block in indianStocks.ts
new_array_block = ",\n".join(modified_entries)
new_content = content.replace(match.group(1), "\n" + new_array_block + "\n")

STOCKS_FILE.write_text(new_content, encoding="utf-8")
print("Successfully classified and updated indianStocks.ts")
