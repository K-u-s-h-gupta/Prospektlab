"""Smoke test — NSE sector mapping and MCA CSV loading."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv("finagent/.env")

NIFTY_10 = ['RELIANCE','TCS','HDFCBANK','INFY','ICICIBANK','BHARTIARTL','ITC','SBIN','LT','BAJFINANCE']

print("=== NSE Sector Mapping ===")
from finagent.ikg.scrapers.nse_index import _fetch_nse_nifty500, parse_nse_companies
raw = _fetch_nse_nifty500(timeout_s=20)
companies = parse_nse_companies(raw)
for co in companies:
    if co['nse_symbol'] in NIFTY_10:
        print(f"  {co['nse_symbol']:<15} sector={co.get('sector',''):<28} industry={co.get('industry','')}")
print(f"  Total Nifty500: {len(companies)} companies\n")

print("=== MCA CSV spot check (first 5 Nifty10 CINs) ===")
from finagent.ikg.scrapers.mca_companies import stream_mca_records
NIFTY10_CINS = {
    "L17110MH1973PLC019786", "L22210MH1995PLC084781", "L65920MH1994PLC080618",
    "L85110KA1981PLC013115", "L65190GJ1994PLC021012", "L74899DL1995PLC070609",
    "L16005WB1910PLC001985", "L65110MH1955GOI089726", "L99999MH1946PLC004768",
    "L65910MH1987PLC042961",
}
found = 0
for rec in stream_mca_records("data/company_master_data_2026-06-01.csv", filter_cins=NIFTY10_CINS):
    print(f"  CIN={rec.cin} | Name={rec.name[:40]} | State={rec.state} | Status={rec.status}")
    found += 1
print(f"  Found {found}/{len(NIFTY10_CINS)} Nifty10 CINs in MCA CSV\n")

print("=== BSE EOD quick check ===")
from finagent.ikg.scrapers.bse_eod import download_bse_eod_csv, parse_bse_eod_csv
from datetime import date, timedelta
d = date.today() - timedelta(days=1)
while d.weekday() >= 5:
    d -= timedelta(days=1)
data = download_bse_eod_csv(d)
if data:
    records = parse_bse_eod_csv(data)
    scrip_codes = {'500325','532540','500180','500209','532174'}
    print(f"  Records: {len(records)}, checking Nifty10 scrips...")
    for r in records:
        if r.get('scrip_code') in scrip_codes:
            print(f"  {r.get('scrip_code')} {r.get('name','')[:20]:<20} close={r.get('close')} vol={r.get('volume')}")
else:
    print("  No EOD data (weekend/holiday?)")

print("\nSmoke test PASSED")
