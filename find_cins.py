"""Find exact CINs for SBI and Bharti Airtel (listed entities)."""
import csv, sys

targets = {
    "SBIN": ["state bank of india", "sbi"],
    "BHARTIARTL": ["bharti airtel limited", "bharti airtel ltd"],
}
found = {}

with open("data/company_master_data_2026-06-01.csv", encoding="utf-8", errors="replace") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        name = row.get("Company Name", "").strip()
        name_lower = name.lower()
        cin = (row.get("\ufeffCIN") or row.get("CIN") or "").strip()
        listing = row.get("Listing Status", "").strip()
        status = row.get("Company Status", "").strip()
        
        for sym, keywords in targets.items():
            if sym in found:
                continue
            if any(kw == name_lower for kw in keywords):
                print(f"EXACT: {sym}: CIN={cin} | Name={name} | Listing={listing} | Status={status}")
                found[sym] = cin
        
        if len(found) == len(targets):
            break
        if i % 500000 == 0 and i > 0:
            print(f"Scanned {i} rows...")

# If exact not found, try partial for listed ones
if len(found) < len(targets):
    print("\nTrying partial match for Listed companies...")
    with open("data/company_master_data_2026-06-01.csv", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Company Name", "").strip()
            name_lower = name.lower()
            cin = (row.get("\ufeffCIN") or row.get("CIN") or "").strip()
            listing = row.get("Listing Status", "").strip().lower()
            status = row.get("Company Status", "").strip()
            
            if listing != "listed":
                continue
                
            for sym, keywords in targets.items():
                if sym in found:
                    continue
                if sym == "SBIN" and "state bank of india" in name_lower and "regional" not in name_lower:
                    print(f"PARTIAL: {sym}: CIN={cin} | Name={name} | Status={status}")
                    found[sym] = cin
                elif sym == "BHARTIARTL" and "bharti airtel" in name_lower and "services" not in name_lower and "holdings" not in name_lower:
                    print(f"PARTIAL: {sym}: CIN={cin} | Name={name} | Status={status}")
                    found[sym] = cin
                    
            if len(found) == len(targets):
                break

print(f"\nFinal: {found}")
