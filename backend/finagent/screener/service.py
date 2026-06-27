"""High-signal stock screener service.

This module centralizes:
  - identifier resolution (symbol/ISIN/CIN/name)
  - live market + fundamentals aggregation
  - technical and governance synthesis
  - natural-language screener query execution
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from finagent.ikg.company_provenance import ProvenanceLookupError, get_company_provenance
from finagent.ikg.director_network import NetworkLookupError, get_director_network_explorer
from finagent.ikg.entity_resolver import EntityLookupError, ResolvedCorporateEntity, get_entity_resolver
from finagent.ikg.governance_score import GovernanceLookupError, get_governance_scorer, result_to_dict
from finagent.ikg.graph_client import get_graph_client
from finagent.ikg.graph_health import GraphHealthError, get_graph_health
from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers.financial_data import fetch_screener_financials, fetch_yfinance_financials
from finagent.ikg.staleness import get_staleness_checker
from finagent.news.sources.nse_announcements import fetch_nse_announcements
from finagent.news.scorer import parse_published_at
from finagent.tools.data import (
    fetch_india_snapshot,
    fetch_news,
    fetch_nse_delivery_snapshot,
    fetch_shareholding_pattern,
    fetch_yahoo_chart,
    fetch_yahoo_quote,
)

from .scoring import (
    check_filter_match,
    compute_scores,
    compute_technicals,
    detect_contradictions,
    parse_nl_filters,
    safe_float,
    summarize_positive_negative,
)

logger = logging.getLogger("finagent.screener.service")

_HISTORY_PERIODS = {"1M", "3M", "6M", "YTD", "1Y", "MAX"}

_KNOWN_ISIN_SYMBOLS = {
    "INE002A01018": "RELIANCE",
    "INE467B01029": "TCS",
    "INE009A01021": "INFY",
    "INE040A01034": "HDFCBANK",
    "INE154A01025": "ITC",
    "INE021A01026": "ASIANPAINT",
    "INE155A01022": "TATAMOTORS",
    "INE758T01015": "ETERNAL",
}

_SYMBOL_ALIASES = {
    # Zomato rebranded to Eternal
    "ZOMATO": "ETERNAL",
    # Companies whose common name / full name != NSE ticker
    "INFOSYS": "INFY",
    "INFOSYS LIMITED": "INFY",
    "INFOSYS LTD": "INFY",
    "TATA MOTORS": "TATAMOTORS",
    "TATA MOTORS LIMITED": "TATAMOTORS",
    "TATA MOTORS LTD": "TATAMOTORS",
    "HDFC BANK": "HDFCBANK",
    "HDFC BANK LIMITED": "HDFCBANK",
    "HDFC BANK LTD": "HDFCBANK",
    "ICICI BANK": "ICICIBANK",
    "ICICI BANK LIMITED": "ICICIBANK",
    "KOTAK BANK": "KOTAKBANK",
    "KOTAK MAHINDRA BANK": "KOTAKBANK",
    "KOTAK MAHINDRA": "KOTAKBANK",
    "STATE BANK OF INDIA": "SBIN",
    "STATE BANK": "SBIN",
    "SBI": "SBIN",
    "BHARTI AIRTEL": "BHARTIARTL",
    "BHARTI AIRTEL LIMITED": "BHARTIARTL",
    "AIRTEL": "BHARTIARTL",
    "ASIAN PAINTS": "ASIANPAINT",
    "ASIAN PAINTS LIMITED": "ASIANPAINT",
    "MARUTI SUZUKI": "MARUTI",
    "MARUTI SUZUKI INDIA": "MARUTI",
    "SUN PHARMACEUTICAL": "SUNPHARMA",
    "SUN PHARMA": "SUNPHARMA",
    "SUN PHARMACEUTICALS": "SUNPHARMA",
    "ULTRATECH CEMENT": "ULTRACEMCO",
    "ULTRATECH": "ULTRACEMCO",
    "BAJAJ FINANCE": "BAJFINANCE",
    "BAJAJ FINSERV": "BAJAJFINSV",
    "HINDUSTAN UNILEVER": "HINDUNILVR",
    "HINDUSTAN UNILEVER LIMITED": "HINDUNILVR",
    "HUL": "HINDUNILVR",
    "HCL TECHNOLOGIES": "HCLTECH",
    "HCL TECH": "HCLTECH",
    "HCL TECHNOLOGIES LIMITED": "HCLTECH",
    "TECH MAHINDRA": "TECHM",
    "TECH MAHINDRA LIMITED": "TECHM",
    "OIL AND NATURAL GAS": "ONGC",
    "OIL AND NATURAL GAS CORPORATION": "ONGC",
    "COAL INDIA": "COALINDIA",
    "COAL INDIA LIMITED": "COALINDIA",
    "ADANI ENTERPRISES": "ADANIENT",
    "ADANI PORTS": "ADANIPORTS",
    "ADANI PORTS AND SEZ": "ADANIPORTS",
    "GRASIM INDUSTRIES": "GRASIM",
    "JSW STEEL": "JSWSTEEL",
    "JSW STEEL LIMITED": "JSWSTEEL",
    "TATA STEEL": "TATASTEEL",
    "TATA STEEL LIMITED": "TATASTEEL",
    "INDUSIND BANK": "INDUSINDBK",
    "INDUSIND BANK LIMITED": "INDUSINDBK",
    "HERO MOTOCORP": "HEROMOTOCO",
    "HERO MOTOR": "HEROMOTOCO",
    "HERO MOTORCORP": "HEROMOTOCO",
    "MAHINDRA AND MAHINDRA": "M&M",
    "MAHINDRA & MAHINDRA": "M&M",
    "MAHINDRA": "M&M",
    "EICHER MOTORS": "EICHERMOT",
    "EICHER MOTORS LIMITED": "EICHERMOT",
    "BAJAJ AUTO": "BAJAJ-AUTO",
    "BAJAJ AUTO LIMITED": "BAJAJ-AUTO",
    "DR REDDYS": "DRREDDY",
    "DR REDDY": "DRREDDY",
    "DR REDDYS LABORATORIES": "DRREDDY",
    "DR REDDYS LAB": "DRREDDY",
    "APOLLO HOSPITALS": "APOLLOHOSP",
    "APOLLO HOSPITALS ENTERPRISE": "APOLLOHOSP",
    "BRITANNIA INDUSTRIES": "BRITANNIA",
    "PIDILITE INDUSTRIES": "PIDILITIND",
    "PIDILITE": "PIDILITIND",
    "DABUR INDIA": "DABUR",
    "GODREJ CONSUMER PRODUCTS": "GODREJCP",
    "GODREJ CONSUMER": "GODREJCP",
    "LARSEN AND TOUBRO": "LT",
    "LARSEN & TOUBRO": "LT",
    "L&T": "LT",
    "L AND T": "LT",
    "AXIS BANK": "AXISBANK",
    "AXIS BANK LIMITED": "AXISBANK",
    "POWER GRID": "POWERGRID",
    "POWER GRID CORPORATION": "POWERGRID",
    "POWERGRID CORPORATION": "POWERGRID",
    "NTPC LIMITED": "NTPC",
    "NESTLE INDIA": "NESTLEIND",
    "NESTLE": "NESTLEIND",
    "TATA CONSULTANCY SERVICES": "TCS",
    "TATA CONSULTANCY": "TCS",
    "RELIANCE INDUSTRIES": "RELIANCE",
    "RELIANCE INDUSTRIES LIMITED": "RELIANCE",
    "WIPRO LIMITED": "WIPRO",
    "TITAN COMPANY": "TITAN",
    "TITAN COMPANY LIMITED": "TITAN",
    "BAJAJ ELECTRICALS": "BAJAJELEC",
    "DIVI S LABORATORIES": "DIVISLAB",
    "DIVIS LABORATORIES": "DIVISLAB",
    "DIVIS LAB": "DIVISLAB",
    "CIPLA LIMITED": "CIPLA",
    "SIEMENS INDIA": "SIEMENS",
    "HAL": "HAL",
    "HINDUSTAN AERONAUTICS": "HAL",
    "BEL": "BEL",
    "BHARAT ELECTRONICS": "BEL",
    "TRENT LIMITED": "TRENT",
    "HDFC LIFE": "HDFCLIFE",
    "HDFC LIFE INSURANCE": "HDFCLIFE",
    "SBI LIFE": "SBILIFE",
    "SBI LIFE INSURANCE": "SBILIFE",
    "ICICI PRUDENTIAL": "ICICIPRULI",
    "ICICI LOMBARD": "ICICIGI",
    "LTI MINDTREE": "LTIM",
    "LTIMINDTREE": "LTIM",
    "MINDTREE": "LTIM",
    "MPHASIS": "MPHASIS",
    "PERSISTENT SYSTEMS": "PERSISTENT",
    "MARICO": "MARICO",
    "HAVELLS INDIA": "HAVELLS",
    "VOLTAS": "VOLTAS",
    "JUBILANT FOODWORKS": "JUBLFOOD",
    "JUBILANT FOOD": "JUBLFOOD",
    "DOMINOS": "JUBLFOOD",
    "ZOMATO LIMITED": "ETERNAL",
    "ETERNAL LIMITED": "ETERNAL",
    "SWIGGY": "SWIGGY",
    "NYKAA": "FSN",
    "FSN ECOMMERCE": "FSN",
    "PAYTM": "PAYTM",
    "ONE97 COMMUNICATIONS": "PAYTM",
    "DMART": "DMART",
    "AVENUE SUPERMARTS": "DMART",
    "AVENUE SUPERMART": "DMART",
    "PNB": "PNB",
    "PUNJAB NATIONAL BANK": "PNB",
    "BANK OF BARODA": "BANKBARODA",
    "CANARA BANK": "CANBK",
    "UNION BANK": "UNIONBANK",
}

_KNOWN_SYMBOL_ISIN = {symbol: isin for isin, symbol in _KNOWN_ISIN_SYMBOLS.items()}

# Static lookup table for the most common NSE-listed companies.
# Allows the search path to return instant results without any network call.
# Format: NSE_SYMBOL → (company_name, sector, isin)
_KNOWN_COMPANIES: dict[str, tuple[str, str, str | None]] = {
    "RELIANCE":    ("Reliance Industries Ltd",         "Energy",                      "INE002A01018"),
    "TCS":         ("Tata Consultancy Services Ltd",   "Information Technology",      "INE467B01029"),
    "INFY":        ("Infosys Ltd",                     "Information Technology",      "INE009A01021"),
    "HDFCBANK":    ("HDFC Bank Ltd",                   "Financial Services",          "INE040A01034"),
    "ICICIBANK":   ("ICICI Bank Ltd",                  "Financial Services",          "INE090A01021"),
    "ITC":         ("ITC Ltd",                         "FMCG",                        "INE154A01025"),
    "LT":          ("Larsen & Toubro Ltd",             "Capital Goods",               "INE018A01030"),
    "AXISBANK":    ("Axis Bank Ltd",                   "Financial Services",          "INE238A01034"),
    "KOTAKBANK":   ("Kotak Mahindra Bank Ltd",         "Financial Services",          "INE237A01028"),
    "SBIN":        ("State Bank of India",             "Financial Services",          "INE062A01020"),
    "BHARTIARTL":  ("Bharti Airtel Ltd",               "Telecom",                     "INE397D01024"),
    "ASIANPAINT":  ("Asian Paints Ltd",                "Consumer Durables",           "INE021A01026"),
    "TATAMOTORS":  ("Tata Motors Ltd",                 "Automobile",                  "INE155A01022"),
    "MARUTI":      ("Maruti Suzuki India Ltd",         "Automobile",                  "INE585B01010"),
    "SUNPHARMA":   ("Sun Pharmaceutical Industries",   "Pharma",                      "INE044A01036"),
    "ULTRACEMCO":  ("UltraTech Cement Ltd",            "Cement",                      "INE481G01011"),
    "BAJFINANCE":  ("Bajaj Finance Ltd",               "Financial Services",          "INE296A01024"),
    "BAJAJFINSV":  ("Bajaj Finserv Ltd",               "Financial Services",          "INE918I01026"),
    "TITAN":       ("Titan Company Ltd",               "Consumer Durables",           "INE280A01028"),
    "NESTLEIND":   ("Nestle India Ltd",                "FMCG",                        "INE239A01016"),
    "POWERGRID":   ("Power Grid Corporation of India", "Utilities",                   "INE752E01010"),
    "NTPC":        ("NTPC Ltd",                        "Utilities",                   "INE733E01010"),
    "HINDUNILVR":  ("Hindustan Unilever Ltd",          "FMCG",                        "INE030A01027"),
    "HCLTECH":     ("HCL Technologies Ltd",            "Information Technology",      "INE860A01027"),
    "TECHM":       ("Tech Mahindra Ltd",               "Information Technology",      "INE669C01036"),
    "ONGC":        ("Oil and Natural Gas Corporation", "Energy",                      "INE213A01029"),
    "COALINDIA":   ("Coal India Ltd",                  "Mining",                      "INE522F01014"),
    "ADANIENT":    ("Adani Enterprises Ltd",           "Diversified",                 "INE423A01024"),
    "ADANIPORTS":  ("Adani Ports & SEZ Ltd",           "Infrastructure",              "INE742F01042"),
    "WIPRO":       ("Wipro Ltd",                       "Information Technology",      "INE075A01022"),
    "GRASIM":      ("Grasim Industries Ltd",           "Diversified",                 "INE047A01021"),
    "JSWSTEEL":    ("JSW Steel Ltd",                   "Metals",                      "INE019A01038"),
    "TATASTEEL":   ("Tata Steel Ltd",                  "Metals",                      "INE081A01020"),
    "INDUSINDBK":  ("IndusInd Bank Ltd",               "Financial Services",          "INE095A01012"),
    "HEROMOTOCO":  ("Hero MotoCorp Ltd",               "Automobile",                  "INE158A01026"),
    "M&M":         ("Mahindra & Mahindra Ltd",         "Automobile",                  "INE101A01026"),
    "EICHERMOT":   ("Eicher Motors Ltd",               "Automobile",                  "INE066A01021"),
    "BAJAJ-AUTO":  ("Bajaj Auto Ltd",                  "Automobile",                  "INE917I01010"),
    "DIVISLAB":    ("Divi's Laboratories Ltd",         "Pharma",                      "INE361B01024"),
    "DRREDDY":     ("Dr. Reddy's Laboratories Ltd",   "Pharma",                      "INE089A01023"),
    "APOLLOHOSP":  ("Apollo Hospitals Enterprise Ltd", "Healthcare",                  "INE437A01024"),
    "CIPLA":       ("Cipla Ltd",                       "Pharma",                      "INE059A01026"),
    "BRITANNIA":   ("Britannia Industries Ltd",        "FMCG",                        "INE216A01030"),
    "PIDILITIND":  ("Pidilite Industries Ltd",         "Chemicals",                   "INE318A01026"),
    "DABUR":       ("Dabur India Ltd",                 "FMCG",                        "INE016A01026"),
    "GODREJCP":    ("Godrej Consumer Products Ltd",    "FMCG",                        "INE102D01028"),
    "SIEMENS":     ("Siemens Ltd",                     "Capital Goods",               "INE003A01024"),
    "BEL":         ("Bharat Electronics Ltd",          "Defence",                     "INE263A01024"),
    "HAL":         ("Hindustan Aeronautics Ltd",       "Defence",                     "INE066F01012"),
    "TRENT":       ("Trent Ltd",                       "Retail",                      "INE849A01020"),
    "HDFCLIFE":    ("HDFC Life Insurance Company Ltd", "Insurance",                   "INE795G01014"),
    "SBILIFE":     ("SBI Life Insurance Company Ltd",  "Insurance",                   "INE123W01016"),
    "ICICIPRULI":  ("ICICI Prudential Life Insurance", "Insurance",                   "INE726G01019"),
    "ICICIGI":     ("ICICI Lombard General Insurance", "Insurance",                   "INE765G01017"),
    "LTIM":        ("LTIMindtree Ltd",                 "Information Technology",      "INE214T01019"),
    "ETERNAL":     ("Eternal Ltd (formerly Zomato)",   "Consumer Services",           "INE758T01015"),
    "PAYTM":       ("One97 Communications Ltd",        "Fintech",                     "INE982J01020"),
    "DMART":       ("Avenue Supermarts Ltd",           "Retail",                      "INE192R01011"),
    "SWIGGY":      ("Swiggy Ltd",                      "Consumer Services",           None),
    "FSN":         ("FSN E-Commerce Ventures (Nykaa)", "E-Commerce",                  "INE388Y01029"),
    "PNB":         ("Punjab National Bank",            "Financial Services",          "INE160A01022"),
    "BANKBARODA":  ("Bank of Baroda",                  "Financial Services",          "INE028A01039"),
    "CANBK":       ("Canara Bank",                     "Financial Services",          "INE476A01014"),
    "PERSISTENT":  ("Persistent Systems Ltd",          "Information Technology",      "INE262H01021"),
    "MPHASIS":     ("Mphasis Ltd",                     "Information Technology",      "INE356A01018"),
    "MARICO":      ("Marico Ltd",                      "FMCG",                        "INE196A01026"),
    "HAVELLS":     ("Havells India Ltd",               "Consumer Durables",           "INE176B01034"),
    "JUBLFOOD":    ("Jubilant FoodWorks Ltd",          "Consumer Services",           "INE797F01020"),
}

# Known CINs for high-traffic symbols so governance/network resolve even when
# the entity-resolver DB is briefly unavailable. Extend as needed.
_KNOWN_SYMBOL_CIN = {
    "RELIANCE": "L17110MH1973PLC019786",
    "TCS": "L22210MH1995PLC084781",
    "INFY": "L85110KA1981PLC013115",
    "HDFCBANK": "L65920MH1994PLC080618",
    "ICICIBANK": "L65190GJ1994PLC021012",
    "ITC": "L16005WB1910PLC001985",
    "SBIN": "L65190MH2007GOI168702",
    "LT": "L99999MH1946PLC004768",
    "AXISBANK": "L65110GJ1993PLC020769",
    "KOTAKBANK": "L65110MH1985PLC038137",
    "BHARTIARTL": "L74899HR1995PLC095967",
    "ASIANPAINT": "L24220MH1945PLC004598",
    "TATAMOTORS": "L28920MH1945PLC004520",
    "MARUTI": "L34103DL1981PLC011375",
    "HINDUNILVR": "L15140MH1933PLC002030",
}

_DEFAULT_UNIVERSE = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "ITC",
    "LT",
    "AXISBANK",
    "KOTAKBANK",
    "SBIN",
    "BHARTIARTL",
    "ASIANPAINT",
    "TATAMOTORS",
    "MARUTI",
    "SUNPHARMA",
    "ULTRACEMCO",
    "BAJFINANCE",
    "BAJAJFINSV",
    "TITAN",
    "NESTLEIND",
    "POWERGRID",
    "NTPC",
    "HINDUNILVR",
    "HCLTECH",
    "TECHM",
    "ONGC",
    "COALINDIA",
    "ADANIENT",
    "ADANIPORTS",
    "WIPRO",
    "GRASIM",
    "JSWSTEEL",
    "TATASTEEL",
    "INDUSINDBK",
    "HEROMOTOCO",
    "M&M",
    "EICHERMOT",
    "BAJAJ-AUTO",
    "DIVISLAB",
    "DRREDDY",
    "APOLLOHOSP",
    "CIPLA",
    "BRITANNIA",
    "PIDILITIND",
    "DABUR",
    "GODREJCP",
    "SIEMENS",
    "BEL",
    "HAL",
    "TRENT",
]

_PEER_HINTS_BY_SYMBOL: dict[str, list[str]] = {
    "RELIANCE": ["ONGC", "IOC", "BPCL", "GAIL"],
    "TCS": ["INFY", "HCLTECH", "WIPRO", "TECHM"],
    "INFY": ["TCS", "HCLTECH", "WIPRO", "TECHM"],
    "HDFCBANK": ["ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN"],
    "ICICIBANK": ["HDFCBANK", "KOTAKBANK", "AXISBANK", "SBIN"],
    "SBIN": ["HDFCBANK", "ICICIBANK", "AXISBANK", "BANKBARODA"],
    "TATAMOTORS": ["MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO"],
    "MARUTI": ["TATAMOTORS", "M&M", "EICHERMOT", "HEROMOTOCO"],
}

_PEER_HINTS_BY_SECTOR: dict[str, list[str]] = {
    "energy": ["ONGC", "IOC", "BPCL", "GAIL", "COALINDIA", "NTPC", "POWERGRID"],
    "oil": ["ONGC", "IOC", "BPCL", "GAIL"],
    "information technology": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "technology": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "bank": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN"],
    "financial": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "BAJFINANCE", "BAJAJFINSV"],
    "automobile": ["TATAMOTORS", "MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO", "HEROMOTOCO"],
    "auto": ["TATAMOTORS", "MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO", "HEROMOTOCO"],
    "pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB"],
    "fmcg": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "GODREJCP"],
}

_SNAPSHOT_CACHE_TTL_S = 120.0
_SNAPSHOT_CACHE_STALE_TTL_S = 900.0
_QUOTE_TARGET_FRESHNESS_S = 15.0
_MAX_NEWS_ITEMS = 60
_MAX_CORPORATE_ITEMS = 250
_MAX_ENFORCEMENT_ITEMS = 120
_QUERY_SCREEN_MAX_CANDIDATES = 20  # Reduced from 60 for performance
_QUERY_SCREEN_CONCURRENCY = 6  # Reduced from 8 to match lower candidates
_QUERY_SCREEN_SYMBOL_TIMEOUT_S = 3.4
_QUERY_SCREEN_TOTAL_TIMEOUT_S = 14.0
_QUERY_SCREEN_YAHOO_TIMEOUT_S = 2.5
_SNAPSHOT_PROVIDER_TIMEOUT_S = 6.0
_SNAPSHOT_QUOTE_REFRESH_TIMEOUT_S = 2.8
_IDENTITY_CACHE_TTL_S = 3600.0
_FINANCIALS_CACHE_TTL_S = 900.0

_MONEY_TO_CRORE = 10_000_000.0
_FINANCIAL_STALENESS_DAYS = 550

_SOURCE_PRECEDENCE = {
    "official_xbrl": 0,
    "company_financials_cache": 1,
    "screener_in": 2,
    "yfinance": 3,
}

_SOURCE_LABELS = {
    "official_xbrl": "BSE/NSE XBRL filings",
    "company_financials_cache": "company_financials cache",
    "screener_in": "Screener.in",
    "yfinance": "Yahoo Finance",
}

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_STATEMENT_CONFIG: dict[str, list[dict[str, Any]]] = {
    "income_statement": [
        {"key": "revenue", "label": "Revenue / Sales", "aliases": ("revenue from operations", "total revenue", "sales", "revenue", "total income"), "kind": "money"},
        {"key": "expenses", "label": "Expenses", "aliases": ("total expenses", "expenses", "expenditure"), "kind": "money"},
        {"key": "operating_profit", "label": "Operating Profit", "aliases": ("operating profit", "operating income"), "kind": "money"},
        {"key": "ebitda", "label": "EBITDA", "aliases": ("ebitda",), "kind": "money"},
        {"key": "depreciation", "label": "Depreciation", "aliases": ("depreciation and amortisation", "depreciation and amortization", "depreciation"), "kind": "money"},
        {"key": "interest", "label": "Interest", "aliases": ("finance cost", "finance costs", "interest expense", "interest"), "kind": "money"},
        {"key": "profit_before_tax", "label": "Profit Before Tax", "aliases": ("profit before tax", "pbt"), "kind": "money"},
        {"key": "tax", "label": "Tax", "aliases": ("tax expense", "tax"), "kind": "money"},
        {"key": "net_income", "label": "PAT / Net Income", "aliases": ("profit after tax", "net profit", "net income", "pat"), "kind": "money"},
        {"key": "eps", "label": "EPS", "aliases": ("eps in rs", "basic eps", "diluted eps", "eps"), "kind": "eps"},
    ],
    "balance_sheet": [
        {"key": "equity_capital", "label": "Equity Capital", "aliases": ("equity share capital", "share capital", "equity capital"), "kind": "money"},
        {"key": "reserves_equity", "label": "Reserves / Equity", "aliases": ("reserves and surplus", "reserves", "stockholders equity", "shareholders funds", "total equity"), "kind": "money"},
        {"key": "borrowings_debt", "label": "Borrowings / Debt", "aliases": ("total debt", "borrowings", "debt"), "kind": "money"},
        {"key": "other_liabilities", "label": "Other Liabilities", "aliases": ("other liabilities", "non current liabilities"), "kind": "money"},
        {"key": "fixed_assets", "label": "Fixed Assets", "aliases": ("property plant equipment", "net ppe", "fixed assets", "net block"), "kind": "money"},
        {"key": "investments", "label": "Investments", "aliases": ("investments and advances", "investments"), "kind": "money"},
        {"key": "current_assets", "label": "Current Assets", "aliases": ("current assets", "current asset"), "kind": "money"},
        {"key": "current_liabilities", "label": "Current Liabilities", "aliases": ("current liabilities",), "kind": "money"},
        {"key": "total_assets", "label": "Total Assets", "aliases": ("total assets",), "kind": "money"},
        {"key": "total_liabilities", "label": "Total Liabilities", "aliases": ("total liabilities",), "kind": "money"},
    ],
    "cash_flow": [
        {"key": "cash_from_operations", "label": "Cash From Operations", "aliases": ("cash flow from operating", "operating cash flow", "cash from operations"), "kind": "money"},
        {"key": "cash_from_investing", "label": "Investing Cash Flow", "aliases": ("cash flow from investing", "investing cash flow"), "kind": "money"},
        {"key": "cash_from_financing", "label": "Financing Cash Flow", "aliases": ("cash flow from financing", "financing cash flow"), "kind": "money"},
        {"key": "net_cash_flow", "label": "Net Cash Flow", "aliases": ("net cash flow", "net increase in cash"), "kind": "money"},
        {"key": "capex", "label": "Capex", "aliases": ("capital expenditure", "capex"), "kind": "money"},
        {"key": "free_cash_flow", "label": "Free Cash Flow", "aliases": ("free cash flow",), "kind": "money"},
    ],
}


def _coerce_json(value: Any) -> dict[str, Any] | list[Any] | None:
    if value in (None, "", "null"):
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            return None
    return None


def _clean_financial_label(raw: str) -> str:
    text = html.unescape(str(raw or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = text.replace("+", " ")
    text = text.replace("&", " ")
    text = text.replace("%", " ")
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _parse_number(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if value == value else None
    text = str(raw).strip()
    if not text or text.lower() in {"na", "n/a", "none", "-", "--"}:
        return None
    neg = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace(",", "")
    text = text.replace("Rs.", "").replace("Rs", "").replace("INR", "").replace("₹", "")
    text = text.replace("Cr", "").replace("crore", "")
    text = text.replace("%", "")
    text = re.sub(r"[^0-9eE.+-]", "", text)
    if not text or text in {"+", "-", ".", "+.", "-."}:
        return None
    try:
        value = float(text)
    except Exception:
        return None
    if neg:
        value *= -1
    return value if value == value else None


def _normalize_percent(value: Any, *, decimal_hint: bool = False) -> float | None:
    parsed = safe_float(value)
    if parsed is None:
        return None
    if decimal_hint and abs(parsed) <= 1.0:
        return round(parsed * 100.0, 4)
    return round(parsed, 4)


def _normalize_debt_to_equity(value: Any) -> float | None:
    parsed = safe_float(value)
    if parsed is None:
        return None
    if parsed > 10.0:
        return round(parsed / 100.0, 4)
    return round(parsed, 4)


def _normalize_dividend_yield(value: Any) -> float | None:
    parsed = safe_float(value)
    if parsed is None:
        return None
    # Yahoo often reports yield in decimal form (0.0045 => 0.45%), while
    # India sources usually report direct percent values (e.g., 0.45).
    if 0 <= parsed <= 0.2:
        return round(parsed * 100.0, 4)
    return round(parsed, 4)


def _normalize_numeric_metric(key: str, value: Any) -> float | None:
    if key in {"roe", "roce"}:
        return _normalize_percent(value, decimal_hint=True)
    if key == "dividend_yield":
        return _normalize_dividend_yield(value)
    if key in {
        "promoter_holding_pct",
        "promoter_pledge_pct",
        "fii_holding_pct",
        "dii_holding_pct",
        "public_holding_pct",
        "revenue_growth_pct",
        "net_income_growth_pct",
    }:
        return _normalize_percent(value)
    if key == "debt_to_equity":
        return _normalize_debt_to_equity(value)
    return safe_float(value)


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10,13}", text):
        try:
            num = int(text)
            if len(text) == 13:
                num = num // 1000
            return datetime.fromtimestamp(num, tz=timezone.utc)
        except Exception:
            return None
    if re.fullmatch(r"\d{4}", text):
        try:
            return datetime(int(text), 3, 31, tzinfo=timezone.utc)
        except Exception:
            return None
    month_match = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b[\s,/-]*(\d{4})", text.lower())
    if month_match:
        month = _MONTHS.get(month_match.group(1))
        year = int(month_match.group(2))
        if month:
            return datetime(year, month, 1, tzinfo=timezone.utc)
    clean = text.replace("/", "-").replace("Z", "+00:00")
    if len(clean) >= 10:
        try:
            dt = datetime.fromisoformat(clean[:10])
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _period_parts(raw: Any) -> tuple[str, datetime] | None:
    dt = _parse_dt(raw)
    if dt is None:
        return None
    return str(dt.year), dt


def _select_periods(period_map: dict[str, datetime], limit: int = 3) -> list[str]:
    if not period_map:
        return []
    ordered = sorted(period_map.items(), key=lambda item: item[1])
    labels = [label for label, _dt in ordered]
    return labels[-limit:]


def _metric_config(statement: str) -> list[dict[str, Any]]:
    return _STATEMENT_CONFIG.get(statement, [])


def _match_metric(statement: str, raw_label: str) -> dict[str, Any] | None:
    label = _clean_financial_label(raw_label)
    if not label:
        return None
    for config in _metric_config(statement):
        for alias in config.get("aliases") or []:
            alias_norm = _clean_financial_label(alias)
            if not alias_norm:
                continue
            if re.search(rf"\b{re.escape(alias_norm)}\b", label):
                return config
    return None


def _convert_financial_value(value: float, *, source_unit: str, kind: str) -> float:
    if kind == "eps":
        return value
    if source_unit == "inr":
        return value / _MONEY_TO_CRORE
    return value


def _add_candidate(
    candidates: list[dict[str, Any]],
    period_map: dict[str, datetime],
    *,
    statement: str,
    metric_key: str,
    metric_kind: str,
    period: str,
    period_dt: datetime,
    value: float,
    source: str,
    source_unit: str,
    confidence: float,
) -> None:
    period_map[period] = max(period_map.get(period, period_dt), period_dt)
    candidates.append(
        {
            "statement": statement,
            "metric_key": metric_key,
            "metric_kind": metric_kind,
            "period": period,
            "period_dt": period_dt,
            "value": value,
            "source": source,
            "source_unit": source_unit,
            "priority": _SOURCE_PRECEDENCE.get(source, 99),
            "confidence": confidence,
        }
    )


def _collect_from_rows(
    rows: Any,
    *,
    statement: str,
    source: str,
    confidence: float,
    source_unit: str,
    candidates: list[dict[str, Any]],
    period_map: dict[str, datetime],
) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        label_raw = str(row.get("label") or "")
        config = _match_metric(statement, label_raw)
        if config is None:
            continue
        if config["key"] == "tax" and "%" in label_raw:
            continue
        for key, raw_value in row.items():
            if key == "label":
                continue
            period_info = _period_parts(key)
            if period_info is None:
                continue
            value = _parse_number(raw_value)
            if value is None:
                continue
            period, period_dt = period_info
            _add_candidate(
                candidates,
                period_map,
                statement=statement,
                metric_key=config["key"],
                metric_kind=config["kind"],
                period=period,
                period_dt=period_dt,
                value=value,
                source=source,
                source_unit=source_unit,
                confidence=confidence,
            )


def _collect_from_json_statement(
    payload: Any,
    *,
    statement: str,
    source: str,
    confidence: float,
    candidates: list[dict[str, Any]],
    period_map: dict[str, datetime],
) -> None:
    data = _coerce_json(payload)
    if not isinstance(data, dict):
        return

    for outer_key, outer_value in data.items():
        if not isinstance(outer_value, dict):
            continue
        outer_period = _period_parts(outer_key)
        if outer_period is not None:
            period, period_dt = outer_period
            for metric_name, raw_value in outer_value.items():
                config = _match_metric(statement, str(metric_name))
                if config is None:
                    continue
                value = _parse_number(raw_value)
                if value is None:
                    continue
                _add_candidate(
                    candidates,
                    period_map,
                    statement=statement,
                    metric_key=config["key"],
                    metric_kind=config["kind"],
                    period=period,
                    period_dt=period_dt,
                    value=value,
                    source=source,
                    source_unit="inr",
                    confidence=confidence,
                )
            continue

        config = _match_metric(statement, str(outer_key))
        if config is None:
            continue
        for period_key, raw_value in outer_value.items():
            period_info = _period_parts(period_key)
            if period_info is None:
                continue
            value = _parse_number(raw_value)
            if value is None:
                continue
            period, period_dt = period_info
            _add_candidate(
                candidates,
                period_map,
                statement=statement,
                metric_key=config["key"],
                metric_kind=config["kind"],
                period=period,
                period_dt=period_dt,
                value=value,
                source=source,
                source_unit="inr",
                confidence=confidence,
            )


def _collect_from_official_rows(
    rows: list[dict[str, Any]],
    *,
    candidates: list[dict[str, Any]],
    period_map: dict[str, datetime],
) -> None:
    if not rows:
        return
    for row in rows:
        period_info = _period_parts(row.get("period_end") or row.get("as_of_date") or row.get("announced_at"))
        if period_info is None:
            continue
        period, period_dt = period_info
        mapping = {
            "revenue": row.get("revenue_from_operations") or row.get("total_income"),
            "profit_before_tax": row.get("profit_before_tax"),
            "net_income": row.get("profit_after_tax"),
            "eps": row.get("eps_basic") or row.get("eps_diluted"),
            "reserves_equity": row.get("net_worth"),
        }
        for metric_key, raw_value in mapping.items():
            value = _parse_number(raw_value)
            if value is None:
                continue
            statement = "income_statement" if metric_key in {"revenue", "profit_before_tax", "net_income", "eps"} else "balance_sheet"
            kind = "eps" if metric_key == "eps" else "money"
            _add_candidate(
                candidates,
                period_map,
                statement=statement,
                metric_key=metric_key,
                metric_kind=kind,
                period=period,
                period_dt=period_dt,
                value=value,
                source="official_xbrl",
                source_unit="inr",
                confidence=0.92,
            )


def _collect_from_snapshot(snapshot: dict[str, Any], *, candidates: list[dict[str, Any]], period_map: dict[str, datetime]) -> None:
    fundamentals = (snapshot.get("fundamentals") or {}).get("financial_trends") or {}
    rev = (fundamentals.get("annual_revenue") or {})
    ni = (fundamentals.get("annual_net_income") or {})
    for date_text, raw in zip(rev.get("dates") or [], rev.get("values") or []):
        period_info = _period_parts(date_text)
        value = _parse_number(raw)
        if period_info is None or value is None:
            continue
        period, period_dt = period_info
        _add_candidate(
            candidates,
            period_map,
            statement="income_statement",
            metric_key="revenue",
            metric_kind="money",
            period=period,
            period_dt=period_dt,
            value=value,
            source="yfinance",
            source_unit="inr",
            confidence=0.52,
        )
    for date_text, raw in zip(ni.get("dates") or [], ni.get("values") or []):
        period_info = _period_parts(date_text)
        value = _parse_number(raw)
        if period_info is None or value is None:
            continue
        period, period_dt = period_info
        _add_candidate(
            candidates,
            period_map,
            statement="income_statement",
            metric_key="net_income",
            metric_kind="money",
            period=period,
            period_dt=period_dt,
            value=value,
            source="yfinance",
            source_unit="inr",
            confidence=0.52,
        )


def _merge_statement_rows(
    *,
    statement: str,
    periods: list[str],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    configs = _metric_config(statement)
    rows: list[dict[str, Any]] = []
    source_counter: dict[str, int] = {}
    confidence_values: list[float] = []

    for config in configs:
        values: dict[str, float | None] = {}
        source_by_period: dict[str, str] = {}
        row_confidence: list[float] = []
        for period in periods:
            matching = [
                cand for cand in candidates
                if cand["statement"] == statement
                and cand["metric_key"] == config["key"]
                and cand["period"] == period
            ]
            if not matching:
                values[period] = None
                continue
            matching.sort(key=lambda item: (item["priority"], -item["confidence"]))
            pick = matching[0]
            converted = _convert_financial_value(
                float(pick["value"]),
                source_unit=pick["source_unit"],
                kind=config["kind"],
            )
            values[period] = round(converted, 2)
            source_by_period[period] = pick["source"]
            source_counter[pick["source"]] = source_counter.get(pick["source"], 0) + 1
            row_confidence.append(float(pick["confidence"]))

        confidence = round(sum(row_confidence) / len(row_confidence), 3) if row_confidence else 0.0
        confidence_values.extend(row_confidence)
        dominant_source = max(source_by_period.values(), key=lambda src: list(source_by_period.values()).count(src)) if source_by_period else ""
        rows.append(
            {
                "key": config["key"],
                "label": config["label"],
                "unit": "INR/share" if config["kind"] == "eps" else "INR crore",
                "values": values,
                "source": _SOURCE_LABELS.get(dominant_source, dominant_source),
                "source_code": dominant_source,
                "confidence": confidence,
            }
        )

    primary_source = max(source_counter, key=source_counter.get) if source_counter else ""
    statement_confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
    return rows, {"primary_source": primary_source, "confidence": statement_confidence}


def _normalize_ratio_metric(value: Any, *, as_percent: bool = False, as_crore: bool = False) -> tuple[float | None, str]:
    parsed = _parse_number(value)
    if parsed is None:
        return None, "N/A"
    if as_crore:
        converted = parsed / _MONEY_TO_CRORE
        return round(converted, 2), f"{converted:,.2f} Cr"
    if as_percent:
        return round(parsed, 2), f"{parsed:.2f}%"
    return round(parsed, 3), f"{parsed:.3f}"


def _build_ratio_groups(snapshot: dict[str, Any], cache_row: dict[str, Any] | None, analytics: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    fundamentals = snapshot.get("fundamentals") or {}
    metrics = dict(fundamentals.get("metrics") or {})
    cached_metrics = _coerce_json((cache_row or {}).get("validated_metrics_json")) or {}
    if analytics:
        for key, raw in (analytics.get("metrics") or {}).items():
            # Prefer statement-derived value, but never overwrite a good
            # snapshot value with None when the derivation came up empty.
            if raw is not None or metrics.get(key) is None:
                metrics[key] = raw
    if isinstance(cached_metrics, dict):
        for key, raw in cached_metrics.items():
            if key in metrics:
                continue
            if isinstance(raw, dict):
                metrics[key] = raw.get("value")
            else:
                metrics[key] = raw

    source_hint = str((fundamentals.get("sources") or {}).get("snapshot") or "market data")

    def _item(key: str, label: str, *, unit: str = "", percent: bool = False, crore: bool = False) -> dict[str, Any]:
        value, display = _normalize_ratio_metric(metrics.get(key), as_percent=percent, as_crore=crore)
        return {
            "key": key,
            "label": label,
            "value": value,
            "display": display if value is not None else "Unavailable",
            "unit": unit,
            "source": source_hint,
        }

    return {
        "valuation": [
            _item("pe_ratio", "P/E"),
            _item("pb_ratio", "P/B"),
            _item("market_cap", "Market Cap", unit="INR crore", crore=False),
            _item("dividend_yield", "Dividend Yield", unit="%", percent=True),
        ],
        "profitability": [
            _item("roe", "ROE", unit="%", percent=True),
            _item("roce", "ROCE", unit="%", percent=True),
            _item("return_on_assets_pct", "ROA", unit="%", percent=True),
            _item("gross_margin_pct", "Gross Margin", unit="%", percent=True),
            _item("operating_margin_pct", "Operating Margin", unit="%", percent=True),
        ],
        "growth": [
            _item("revenue_growth_pct", "Revenue Growth", unit="%", percent=True),
            _item("net_income_growth_pct", "Net Income Growth", unit="%", percent=True),
        ],
        "leverage": [
            _item("debt_to_equity", "Debt / Equity"),
        ],
        "ownership": [
            _item("promoter_holding_pct", "Promoter Holding", unit="%", percent=True),
            _item("promoter_pledge_pct", "Promoter Pledge", unit="%", percent=True),
            _item("fii_holding_pct", "FII Holding", unit="%", percent=True),
            _item("dii_holding_pct", "DII Holding", unit="%", percent=True),
            _item("public_holding_pct", "Public Holding", unit="%", percent=True),
            _item("institutional_holding_pct", "Institutional Holding", unit="%", percent=True),
        ],
        "liquidity": [
            _item("current_ratio", "Current Ratio"),
            _item("quick_ratio", "Quick Ratio"),
        ],
        "cash_flow": [
            _item("operating_cashflow", "Operating Cash Flow", unit="INR crore", crore=True),
            _item("free_cashflow", "Free Cash Flow", unit="INR crore", crore=True),
        ],
        "advanced": [
            _item("earnings_yield_pct", "Earnings Yield", unit="%", percent=True),
            _item("fcf_yield_pct", "FCF Yield", unit="%", percent=True),
            _item("price_to_sales", "Price / Sales"),
            _item("ev_to_ebitda", "EV / EBITDA"),
            _item("peg_ratio_proxy", "PEG (Proxy)"),
            _item("net_margin_pct", "Net Margin", unit="%", percent=True),
            _item("dcf_fair_value_per_share", "DCF Fair Value / Share", unit="INR"),
            _item("dcf_upside_pct", "DCF Upside", unit="%", percent=True),
            _item("piotroski_f_score", "Piotroski F-Score"),
            _item("piotroski_f_score_proxy", "Piotroski F (Proxy)"),
            _item("dupont_net_margin_pct", "DuPont Net Margin", unit="%", percent=True),
            _item("dupont_equity_multiplier", "DuPont Equity Multiplier"),
            _item("dupont_asset_turnover", "DuPont Asset Turnover"),
        ],
    }



def _row_period_value(rows: list[dict[str, Any]], key: str, period: str | None) -> float | None:
    if not period:
        return None
    for row in rows or []:
        if row.get("key") == key:
            return safe_float((row.get("values") or {}).get(period))
    return None


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den


def _derive_public_financial_analytics(*, snapshot: dict[str, Any], periods: list[str], income_rows: list[dict[str, Any]], balance_rows: list[dict[str, Any]], cash_rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = dict(((snapshot.get("fundamentals") or {}).get("metrics") or {}))
    latest = periods[-1] if periods else None
    prior = periods[-2] if len(periods) >= 2 else None
    revenue = _row_period_value(income_rows, "revenue", latest)
    revenue_prev = _row_period_value(income_rows, "revenue", prior)
    net_income = _row_period_value(income_rows, "net_income", latest)
    net_income_prev = _row_period_value(income_rows, "net_income", prior)
    operating_profit = _row_period_value(income_rows, "operating_profit", latest)
    operating_profit_prev = _row_period_value(income_rows, "operating_profit", prior)
    cfo = _row_period_value(cash_rows, "cash_from_operations", latest)
    fcf = _row_period_value(cash_rows, "free_cash_flow", latest)
    capex = _row_period_value(cash_rows, "capex", latest)
    assets = _row_period_value(balance_rows, "total_assets", latest)
    assets_prev = _row_period_value(balance_rows, "total_assets", prior)
    equity = _row_period_value(balance_rows, "reserves_equity", latest)
    debt = _row_period_value(balance_rows, "borrowings_debt", latest)
    debt_prev = _row_period_value(balance_rows, "borrowings_debt", prior)
    current_assets = _row_period_value(balance_rows, "current_assets", latest)
    current_assets_prev = _row_period_value(balance_rows, "current_assets", prior)
    current_liabilities = _row_period_value(balance_rows, "current_liabilities", latest)
    current_liabilities_prev = _row_period_value(balance_rows, "current_liabilities", prior)
    equity_capital = _row_period_value(balance_rows, "equity_capital", latest)
    equity_capital_prev = _row_period_value(balance_rows, "equity_capital", prior)
    if fcf is None and cfo is not None and capex is not None:
        fcf = cfo - abs(capex)
    nm_raw = _safe_div(net_income, revenue)
    opm_raw = _safe_div(operating_profit, revenue)
    net_margin = (nm_raw * 100.0) if nm_raw is not None else metrics.get("net_margin_pct")
    operating_margin = (opm_raw * 100.0) if opm_raw is not None else metrics.get("operating_margin_pct")
    asset_turnover = _safe_div(revenue, assets)
    asset_turnover_prev = _safe_div(revenue_prev, assets_prev)
    equity_multiplier = _safe_div(assets, equity) or metrics.get("dupont_equity_multiplier")
    dupont_roe = (net_margin / 100.0) * asset_turnover * equity_multiplier * 100.0 if net_margin is not None and asset_turnover is not None and equity_multiplier is not None else None
    current_ratio = _safe_div(current_assets, current_liabilities)
    current_ratio_prev = _safe_div(current_assets_prev, current_liabilities_prev)
    roa = _safe_div(net_income, assets)
    roa_prev = _safe_div(net_income_prev, assets_prev)
    opm_prev_raw = _safe_div(operating_profit_prev, revenue_prev)
    operating_margin_prev = (opm_prev_raw * 100.0) if opm_prev_raw is not None else None
    signals = {
        "positive_net_income": bool(net_income is not None and net_income > 0),
        "positive_operating_cash_flow": bool(cfo is not None and cfo > 0),
        "roa_improving": bool(roa is not None and roa_prev is not None and roa > roa_prev),
        "cash_flow_exceeds_profit": bool(cfo is not None and net_income is not None and cfo > net_income),
        "lower_debt": bool(debt is not None and debt_prev is not None and debt <= debt_prev),
        "current_ratio_improving": bool(current_ratio is not None and current_ratio_prev is not None and current_ratio > current_ratio_prev),
        "no_equity_dilution": bool(equity_capital is not None and equity_capital_prev is not None and equity_capital <= equity_capital_prev),
        "margin_improving_proxy": bool(operating_margin is not None and operating_margin_prev is not None and operating_margin > operating_margin_prev),
        "asset_turnover_improving": bool(asset_turnover is not None and asset_turnover_prev is not None and asset_turnover > asset_turnover_prev),
    }
    piotroski_score = sum(1 for value in signals.values() if value)
    dcf = {"status": "unavailable", "reason": "requires_positive_public_fcf_price_and_market_cap"}
    price = safe_float(metrics.get("price"))
    market_cap_cr = safe_float(metrics.get("market_cap"))
    if fcf is not None and fcf > 0 and price and market_cap_cr and market_cap_cr > 0:
        growth = max(0.02, min(0.08, ((revenue / revenue_prev) - 1.0))) if revenue is not None and revenue_prev and revenue_prev > 0 else 0.04
        discount = 0.12
        terminal = 0.04
        pv = sum((fcf * ((1 + growth) ** year)) / ((1 + discount) ** year) for year in range(1, 6))
        terminal_value = (fcf * ((1 + growth) ** 5) * (1 + terminal)) / (discount - terminal)
        equity_value_cr = pv + terminal_value / ((1 + discount) ** 5)
        shares_cr = market_cap_cr / price
        fair = _safe_div(equity_value_cr, shares_cr)
        upside = ((fair - price) / price * 100.0) if fair is not None else None
        dcf = {"status": "derived", "fair_value_per_share": round(fair, 2) if fair is not None else None, "equity_value_cr": round(equity_value_cr, 2), "upside_pct": round(upside, 2) if upside is not None else None, "assumptions": {"growth_pct": round(growth * 100, 2), "discount_pct": 12.0, "terminal_growth_pct": 4.0}, "source": "Derived from public cash-flow statements and market cap"}
    # Statement-derived ratios — used as a fallback when live Yahoo `info`
    # is unavailable, so the ratio panel is not riddled with "Unavailable".
    revenue_growth_pct = ((revenue / revenue_prev - 1.0) * 100.0) if (revenue is not None and revenue_prev and revenue_prev > 0) else None
    net_income_growth_pct = ((net_income / net_income_prev - 1.0) * 100.0) if (net_income is not None and net_income_prev and net_income_prev > 0) else None
    derived = {
        "dcf_fair_value_per_share": dcf.get("fair_value_per_share"),
        "dcf_upside_pct": dcf.get("upside_pct"),
        "piotroski_f_score": piotroski_score,
        "dupont_net_margin_pct": round(net_margin, 3) if net_margin is not None else metrics.get("dupont_net_margin_pct"),
        "dupont_asset_turnover": round(asset_turnover, 4) if asset_turnover is not None else metrics.get("dupont_asset_turnover_proxy"),
        "dupont_equity_multiplier": round(equity_multiplier, 3) if equity_multiplier is not None else metrics.get("dupont_equity_multiplier"),
        "dupont_roe_pct": round(dupont_roe, 3) if dupont_roe is not None else None,
        "operating_margin_pct": round(operating_margin, 3) if operating_margin is not None else metrics.get("operating_margin_pct"),
        "net_margin_pct": round(net_margin, 3) if net_margin is not None else None,
        "current_ratio": round(current_ratio, 3) if current_ratio is not None else None,
        "return_on_assets_pct": round(roa * 100.0, 3) if roa is not None else None,
        "revenue_growth_pct": round(revenue_growth_pct, 3) if revenue_growth_pct is not None else None,
        "net_income_growth_pct": round(net_income_growth_pct, 3) if net_income_growth_pct is not None else None,
    }
    return {"status": "derived" if periods else "unavailable", "source": "public filings/Screener/Yahoo normalized statements", "latest_period": latest, "metrics": derived, "dcf": dcf, "piotroski": {"score": piotroski_score, "signals": signals, "source": "public statement-derived"}, "dupont": {"net_margin_pct": derived.get("dupont_net_margin_pct"), "asset_turnover": derived.get("dupont_asset_turnover"), "equity_multiplier": derived.get("dupont_equity_multiplier"), "roe_pct": derived.get("dupont_roe_pct")}}

def _compute_quality(
    *,
    periods: list[str],
    rows_by_statement: dict[str, list[dict[str, Any]]],
    source_meta: dict[str, dict[str, Any]],
    discrepancies: list[str],
) -> dict[str, Any]:
    missing_fields: list[str] = []
    total_fields = 0
    filled_fields = 0

    for statement, rows in rows_by_statement.items():
        for row in rows:
            total_fields += 1
            values = row.get("values") or {}
            usable = [values.get(period) for period in periods]
            if any(value is not None for value in usable):
                filled_fields += 1
            else:
                missing_fields.append(f"{statement}.{row.get('key')}")

    stale_fields: list[str] = []
    now = _now_utc()
    for code, meta in source_meta.items():
        dt = _parse_dt(meta.get("as_of") or meta.get("fetched_at"))
        if dt is None:
            continue
        age_days = (now - dt).total_seconds() / 86400.0
        if age_days > _FINANCIAL_STALENESS_DAYS:
            stale_fields.append(f"{code}:{int(age_days)}d")

    coverage = (filled_fields / total_fields) if total_fields else 0.0
    base_conf = 0.45
    if "official_xbrl" in source_meta:
        base_conf = 0.88
    elif "company_financials_cache" in source_meta:
        base_conf = 0.78
    elif "screener_in" in source_meta:
        base_conf = 0.66
    elif "yfinance" in source_meta:
        base_conf = 0.55
    confidence = round(max(0.1, min(0.99, base_conf * (0.5 + 0.5 * coverage))), 3)

    return {
        "missing_fields": missing_fields,
        "stale_fields": stale_fields,
        "discrepancies": discrepancies[:20],
        "confidence": confidence,
    }


def _normalize_financial_payload(
    *,
    symbol: str,
    snapshot: dict[str, Any],
    cache_row: dict[str, Any] | None,
    official_rows: list[dict[str, Any]],
    screener_live: dict[str, Any] | None,
    yfinance_live: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    period_map: dict[str, datetime] = {}
    source_meta: dict[str, dict[str, Any]] = {}

    if official_rows:
        _collect_from_official_rows(official_rows, candidates=candidates, period_map=period_map)
        latest_official = official_rows[0] if official_rows else {}
        source_meta["official_xbrl"] = {
            "name": _SOURCE_LABELS["official_xbrl"],
            "url": latest_official.get("source_url") or latest_official.get("attachment_url") or "",
            "basis": "official filing",
            "unit": "INR (normalized to INR crore)",
            "fetched_at": latest_official.get("announced_at"),
            "as_of": latest_official.get("period_end") or latest_official.get("as_of_date"),
        }

    if cache_row:
        source_meta["company_financials_cache"] = {
            "name": _SOURCE_LABELS["company_financials_cache"],
            "url": "",
            "basis": "cache",
            "unit": "mixed (normalized to INR crore)",
            "fetched_at": cache_row.get("updated_at") or cache_row.get("fetched_at"),
            "as_of": cache_row.get("updated_at") or cache_row.get("fetched_at"),
        }
        _collect_from_rows(
            (cache_row or {}).get("income_statement_json"),
            statement="income_statement",
            source="company_financials_cache",
            confidence=0.76,
            source_unit="inr_crore",
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_rows(
            (cache_row or {}).get("balance_sheet_json"),
            statement="balance_sheet",
            source="company_financials_cache",
            confidence=0.76,
            source_unit="inr_crore",
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_rows(
            (cache_row or {}).get("cashflow_json"),
            statement="cash_flow",
            source="company_financials_cache",
            confidence=0.76,
            source_unit="inr_crore",
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_json_statement(
            (cache_row or {}).get("income_statement_json"),
            statement="income_statement",
            source="company_financials_cache",
            confidence=0.72,
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_json_statement(
            (cache_row or {}).get("balance_sheet_json"),
            statement="balance_sheet",
            source="company_financials_cache",
            confidence=0.72,
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_json_statement(
            (cache_row or {}).get("cashflow_json"),
            statement="cash_flow",
            source="company_financials_cache",
            confidence=0.72,
            candidates=candidates,
            period_map=period_map,
        )

    if screener_live:
        source_meta["screener_in"] = {
            "name": _SOURCE_LABELS["screener_in"],
            "url": f"https://www.screener.in/company/{symbol.upper()}/",
            "basis": "parsed table",
            "unit": "INR crore",
            "fetched_at": _iso_now(),
            "as_of": None,
        }
        _collect_from_rows(
            screener_live.get("income_statement"),
            statement="income_statement",
            source="screener_in",
            confidence=0.64,
            source_unit="inr_crore",
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_rows(
            screener_live.get("balance_sheet"),
            statement="balance_sheet",
            source="screener_in",
            confidence=0.64,
            source_unit="inr_crore",
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_rows(
            screener_live.get("cash_flow"),
            statement="cash_flow",
            source="screener_in",
            confidence=0.64,
            source_unit="inr_crore",
            candidates=candidates,
            period_map=period_map,
        )

    if yfinance_live:
        source_meta["yfinance"] = {
            "name": _SOURCE_LABELS["yfinance"],
            "url": str(((snapshot.get("fundamentals") or {}).get("sources") or {}).get("yahoo_url") or ""),
            "basis": "fallback",
            "unit": "INR (normalized to INR crore)",
            "fetched_at": _iso_now(),
            "as_of": None,
            "note": "Uses Yahoo public APIs; not affiliated, endorsed, or vetted by Yahoo.",
        }
        _collect_from_json_statement(
            yfinance_live.get("financials_json"),
            statement="income_statement",
            source="yfinance",
            confidence=0.52,
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_json_statement(
            yfinance_live.get("balance_sheet_json"),
            statement="balance_sheet",
            source="yfinance",
            confidence=0.52,
            candidates=candidates,
            period_map=period_map,
        )
        _collect_from_json_statement(
            yfinance_live.get("cashflow_json"),
            statement="cash_flow",
            source="yfinance",
            confidence=0.52,
            candidates=candidates,
            period_map=period_map,
        )

    _collect_from_snapshot(snapshot, candidates=candidates, period_map=period_map)
    if "yfinance" not in source_meta and any(c["source"] == "yfinance" for c in candidates):
        source_meta["yfinance"] = {
            "name": _SOURCE_LABELS["yfinance"],
            "url": str(((snapshot.get("fundamentals") or {}).get("sources") or {}).get("yahoo_url") or ""),
            "basis": "fallback",
            "unit": "INR (normalized to INR crore)",
            "fetched_at": _iso_now(),
            "as_of": None,
            "note": "Uses Yahoo public APIs; not affiliated, endorsed, or vetted by Yahoo.",
        }

    periods = _select_periods(period_map, limit=3)
    period_rows = [{"id": period, "label": f"FY {period}", "end_date": period_map.get(period).date().isoformat() if period in period_map else None} for period in periods]

    income_rows, income_meta = _merge_statement_rows(statement="income_statement", periods=periods, candidates=candidates)
    balance_rows, balance_meta = _merge_statement_rows(statement="balance_sheet", periods=periods, candidates=candidates)
    cash_rows, cash_meta = _merge_statement_rows(statement="cash_flow", periods=periods, candidates=candidates)

    def _statement_source(meta: dict[str, Any]) -> dict[str, Any]:
        code = str(meta.get("primary_source") or "")
        details = source_meta.get(code, {})
        return {
            "code": code,
            "name": details.get("name") or _SOURCE_LABELS.get(code, code) or "Unavailable",
            "basis": details.get("basis") or "",
            "as_of": details.get("as_of") or details.get("fetched_at"),
            "unit": details.get("unit") or "INR crore",
            "confidence": meta.get("confidence") or 0.0,
        }

    discrepancies = list((_coerce_json((cache_row or {}).get("discrepancies_json")) or []))
    if not discrepancies and not periods:
        discrepancies = ["No statement periods detected from official, cache, screener, or yfinance sources."]

    rows_by_statement = {
        "income_statement": income_rows,
        "balance_sheet": balance_rows,
        "cash_flow": cash_rows,
    }
    quality = _compute_quality(
        periods=periods,
        rows_by_statement=rows_by_statement,
        source_meta=source_meta,
        discrepancies=[str(item) for item in discrepancies],
    )
    analytics = _derive_public_financial_analytics(
        snapshot=snapshot,
        periods=periods,
        income_rows=income_rows,
        balance_rows=balance_rows,
        cash_rows=cash_rows,
    )

    return {
        "periods": period_rows,
        "ratios": _build_ratio_groups(snapshot, cache_row, analytics=analytics),
        "analytics": analytics,
        "income_statement": {
            "unit": "INR crore",
            "rows": income_rows,
            "source": _statement_source(income_meta),
        },
        "balance_sheet": {
            "unit": "INR crore",
            "rows": balance_rows,
            "source": _statement_source(balance_meta),
        },
        "cash_flow": {
            "unit": "INR crore",
            "rows": cash_rows,
            "source": _statement_source(cash_meta),
        },
        "sources": [source_meta[key] | {"code": key} for key in source_meta.keys()],
        "quality": quality,
        "filings_as_of": period_rows[-1]["end_date"] if period_rows else None,
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now_utc().isoformat()


def _clean_symbol(symbol: str) -> str:
    value = (symbol or "").strip().upper()
    value = value.removesuffix(".NS").removesuffix(".BO").removesuffix(".NSE").removesuffix(".BSE")
    mapped = _KNOWN_ISIN_SYMBOLS.get(value, value)
    return _SYMBOL_ALIASES.get(mapped, mapped)


def _history_candidates(symbol: str) -> list[str]:
    clean = _clean_symbol(symbol)
    if not clean:
        return []
    if clean.startswith("^") or clean.endswith((".NS", ".BO")):
        return [clean]
    if "=" in clean or "-" in clean:
        return [clean]
    return [f"{clean}.NS", f"{clean}.BO", clean]


def _period_cutoff(period: str, latest: datetime) -> datetime | None:
    if period == "MAX":
        return None
    if period == "YTD":
        return datetime(latest.year, 1, 1, tzinfo=latest.tzinfo)
    days = {
        "1M": 31,
        "3M": 93,
        "6M": 186,
        "1Y": 366,
    }.get(period)
    if not days:
        return None
    return latest - timedelta(days=days)


def _filter_history_period(dates: list[str], prices: list[float], period: str) -> tuple[list[str], list[float]]:
    rows: list[tuple[datetime, str, float]] = []
    for date_text, price in zip(dates or [], prices or []):
        try:
            parsed = datetime.fromisoformat(str(date_text)[:10]).replace(tzinfo=timezone.utc)
            price_f = float(price)
        except Exception:
            continue
        if price_f > 0:
            rows.append((parsed, parsed.date().isoformat(), price_f))

    rows.sort(key=lambda item: item[0])
    if not rows:
        return [], []

    cutoff = _period_cutoff(period, rows[-1][0])
    if cutoff is not None:
        rows = [row for row in rows if row[0] >= cutoff]

    return [row[1] for row in rows], [row[2] for row in rows]


def _calc_growth_pct(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    first = safe_float(values[0])
    last = safe_float(values[-1])
    if first is None or last is None or first <= 0:
        return None
    return ((last - first) / first) * 100.0


def _extract_sentences(text: str, limit: int = 3) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = re.split(r"(?<=[.!?])\s+", raw)
    cleaned = [p.strip() for p in parts if p.strip()]
    return cleaned[:limit]


def _event_sentiment(text: str) -> dict[str, Any]:
    lower = (text or "").lower()
    positive_terms = (
        "beats", "beat", "growth", "wins", "order", "approval", "upgrade", "raises",
        "dividend", "bonus", "buyback", "record profit", "expansion", "commissioned",
        "acquisition", "partnership", "robust", "strong", "higher", "surges",
    )
    negative_terms = (
        "miss", "falls", "decline", "downgrade", "penalty", "fine", "probe",
        "investigation", "resigns", "default", "fraud", "loss", "weak", "lower",
        "cuts", "delay", "suspended", "pledge", "litigation", "show cause",
    )
    pos = sum(1 for term in positive_terms if term in lower)
    neg = sum(1 for term in negative_terms if term in lower)
    raw_score = pos - neg
    score = 0.0 if raw_score == 0 else max(-1.0, min(1.0, raw_score / 3.0))
    label = "positive" if score > 0.15 else ("negative" if score < -0.15 else "neutral")
    return {"label": label, "score": round(score, 3), "method": "keyword_v1"}


def _normalize_news_item(item: dict[str, Any], idx: int) -> dict[str, Any]:
    title = str(item.get("title") or item.get("headline") or item.get("subject") or "").strip()
    if not title:
        title = str(item.get("description") or item.get("snippet") or "Market update").strip()[:160]
    link = str(item.get("link") or item.get("url") or "").strip()
    source = str(item.get("source") or item.get("publisher") or "News").strip() or "News"
    published = str(item.get("published") or "")
    published_dt = parse_published_at({"published": published})
    age_label = "recent"
    if published_dt is not None:
        if published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=timezone.utc)
        delta_h = max(0.0, (_now_utc() - published_dt).total_seconds() / 3600.0)
        if delta_h < 1:
            age_label = "just now"
        elif delta_h < 24:
            age_label = f"{int(delta_h)}h ago"
        else:
            age_label = f"{int(delta_h // 24)}d ago"
    description = str(item.get("description") or "")
    return {
        "id": f"news-{idx}",
        "headline": title,
        "source": source,
        "url": link,
        "published": published,
        "age": age_label,
        "description": description,
        "image": str(item.get("image") or ""),
        "sentiment": _event_sentiment(f"{title} {description}"),
    }

def _classify_corporate_event(title: str, category: str, snippet: str) -> dict[str, Any]:
    text = f"{title} {category} {snippet}".lower()

    def has(*terms: str) -> bool:
        return any(term in text for term in terms)

    event_type = "corporate_disclosure"
    is_action = False
    is_insider = False

    if has("dividend", "record date", "book closure"):
        event_type = "dividend"
        is_action = True
    if has("bonus"):
        event_type = "bonus"
        is_action = True
    if has("split", "sub-division", "sub division", "face value"):
        event_type = "stock_split"
        is_action = True
    if has("rights issue", "right issue"):
        event_type = "rights_issue"
        is_action = True
    if has("buyback", "buy back"):
        event_type = "buyback"
        is_action = True
    if has("board meeting"):
        event_type = "board_meeting"
        is_action = True
    if has("financial results", "audited results", "unaudited results", "quarterly results"):
        event_type = "financial_results"
        is_action = True
    if has("agm", "annual general meeting", "egm", "postal ballot"):
        event_type = "shareholder_meeting"
        is_action = True
    if has("scheme of arrangement", "merger", "amalgamation", "acquisition", "slump sale"):
        event_type = "merger_acquisition"
        is_action = True
    if has("pledge", "encumbrance", "release of encumbrance", "revocation of pledge"):
        event_type = "promoter_pledge"
        is_action = True
        is_insider = True
    if has(
        "insider trading",
        "trading window",
        "pit regulations",
        "regulation 7(2)",
        "regulation 29(2)",
        "sast",
        "promoter group",
        "disposal of shares",
        "acquisition of shares",
        "continual disclosure",
    ):
        event_type = "insider_trade_disclosure" if event_type == "corporate_disclosure" else event_type
        is_insider = True

    return {
        "event_type": event_type,
        "is_corporate_action": bool(is_action),
        "is_insider_trade": bool(is_insider),
    }

def _normalize_announcement(item: dict[str, Any], idx: int) -> dict[str, Any]:
    title = str(
        item.get("title")
        or item.get("headline")
        or item.get("subject")
        or item.get("description")
        or item.get("snippet")
        or "Corporate disclosure"
    ).strip()
    category = str(item.get("category") or item.get("type") or "corporate_action").strip() or "corporate_action"
    source = str(item.get("source") or item.get("exchange") or item.get("publisher") or "nseindia.com").strip() or "nseindia.com"
    snippet = str(item.get("snippet") or item.get("description") or "")
    classification = _classify_corporate_event(title, category, snippet)
    return {
        "id": f"corp-{idx}",
        "title": title,
        "category": category,
        "source": source,
        "url": str(item.get("url") or item.get("link") or ""),
        "published": str(item.get("published") or item.get("pubDate") or item.get("date") or ""),
        "snippet": snippet,
        "event_type": classification["event_type"],
        "is_corporate_action": classification["is_corporate_action"],
        "is_insider_trade": classification["is_insider_trade"],
        "sentiment": _event_sentiment(f"{title} {category} {snippet}"),
    }


def _profile_from_summary(summary: str | None) -> dict[str, Any]:
    text = (summary or "").strip()
    sentences = _extract_sentences(text, limit=6)
    overview = " ".join(sentences[:2]).strip() if sentences else ""
    product_hints: list[str] = []
    client_hints: list[str] = []
    mission = None
    vision = None

    lower = text.lower()
    if "mission" in lower:
        match = re.search(r"(mission[^.]{0,180}\.)", text, flags=re.IGNORECASE)
        if match:
            mission = match.group(1).strip()
    if "vision" in lower:
        match = re.search(r"(vision[^.]{0,180}\.)", text, flags=re.IGNORECASE)
        if match:
            vision = match.group(1).strip()

    for token in re.split(r"[;,]", text):
        chunk = token.strip()
        if len(chunk) < 12:
            continue
        low = chunk.lower()
        if any(word in low for word in ("manufacture", "product", "service", "platform", "solution", "software", "segment")):
            product_hints.append(chunk)
        if any(word in low for word in ("customer", "client", "consumer", "enterprise", "retail", "institution")):
            client_hints.append(chunk)
        if len(product_hints) >= 4 and len(client_hints) >= 3:
            break

    # NOTE: products/clients via naive comma-split produced noisy fragments
    # (e.g. whole sentences, "vision channels"). Only mission/vision matched by
    # an explicit keyword regex are reliable enough to surface; structured
    # products/clients are filled from provenance facts when available.
    return {
        "overview": overview or (sentences[0] if sentences else ""),
        "mission": mission,
        "vision": vision,
        "products_services": [],
        "clients": [],
        "business_summary": text,
    }


def _company_facts(
    *,
    identity: "_ResolvedIdentity",
    india_snap: Any,
    yahoo_quote: Any,
    metrics: dict[str, Any],
) -> list[dict[str, str]]:
    """Detailed, reliable company facts for the overview panel.

    Pulls from the India snapshot + Yahoo profile (sector, industry, HQ,
    employees, website) and the already-computed numeric metrics.
    """
    info = dict((getattr(yahoo_quote, "company_info", None) or {}))
    facts: list[dict[str, str]] = []

    def add(label: str, value: Any) -> None:
        if value in (None, "", []):
            return
        facts.append({"label": label, "value": str(value)})

    def add_money_cr(label: str, value: Any) -> None:
        n = safe_float(value)
        if n is None:
            return
        facts.append({"label": label, "value": f"Rs {n:,.0f} Cr"})

    def add_inr(label: str, value: Any, digits: int = 2) -> None:
        n = safe_float(value)
        if n is None:
            return
        facts.append({"label": label, "value": f"Rs {n:,.{digits}f}"})

    def add_pct(label: str, value: Any, digits: int = 2) -> None:
        n = safe_float(value)
        if n is None:
            return
        facts.append({"label": label, "value": f"{n:.{digits}f}%"})

    sector = identity.sector or getattr(india_snap, "sector", None) or info.get("sector")
    industry = getattr(india_snap, "industry", None) or info.get("industry")
    exchange = getattr(india_snap, "exchange", None) or info.get("exchange_name")
    employees = info.get("employees")
    hq = " ".join(
        str(part).strip()
        for part in (info.get("city"), info.get("state"), info.get("country"))
        if part
    ).strip()
    website = info.get("website")

    add("Sector", sector)
    add("Industry", industry)
    add("Listed On", exchange)
    add("ISIN", identity.isin or getattr(india_snap, "isin", None))
    add("CIN", identity.cin or getattr(india_snap, "cin", None))
    add_money_cr("Market Cap", metrics.get("market_cap"))
    add_inr("52W High", getattr(india_snap, "week_52_high", None))
    add_inr("52W Low", getattr(india_snap, "week_52_low", None))
    add_inr("Face Value", getattr(india_snap, "face_value", None))
    add_inr("Book Value", metrics.get("book_value"))
    add_inr("EPS (TTM)", getattr(india_snap, "eps", None))
    add_pct("Dividend Yield", metrics.get("dividend_yield"))
    add("Beta", round(metrics["beta"], 2) if safe_float(metrics.get("beta")) is not None else None)
    if employees is not None:
        try:
            add("Employees", f"{int(float(employees)):,}")
        except (TypeError, ValueError):
            add("Employees", employees)
    add("Headquarters", hq)
    add("Website", website)
    return facts


def _metric(
    label: str,
    value: float | None,
    *,
    unit: str = "",
    precision: int = 2,
    source: str = "",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "label": label,
        "value": value,
        "unit": unit,
        "source": source,
    }
    if value is None:
        out["display"] = "N/A"
    elif unit == "%":
        out["display"] = f"{value:.{precision}f}%"
    elif unit == "INR":
        out["display"] = f"Rs {value:,.{precision}f}"
    else:
        out["display"] = f"{value:.{precision}f}"
    return out


@dataclass(slots=True)
class _ResolvedIdentity:
    query: str
    symbol: str
    cin: str | None = None
    isin: str | None = None
    company_name: str | None = None
    sector: str | None = None
    confidence: float | None = None
    source: str = ""


class ScreenerService:
    """High-level screener orchestration layer."""

    def __init__(self) -> None:
        self._resolver = get_entity_resolver()
        self._governance = get_governance_scorer()
        self._network = get_director_network_explorer()
        self._provenance = get_company_provenance()
        self._health = get_graph_health()
        self._graph = get_graph_client()
        self._staleness = get_staleness_checker()
        self._snapshot_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._snapshot_refresh_tasks: dict[str, asyncio.Task[Any]] = {}
        self._identity_cache: dict[str, tuple[float, _ResolvedIdentity]] = {}
        self._financials_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        
        # In-flight request deduplication
        self._inflight_india_snapshot: dict[str, asyncio.Task[Any]] = {}
        
        # Cache limits for memory control
        self._snapshot_cache_max = 500
        self._identity_cache_max = 1000
        self._financials_cache_max = 300

    async def _fetch_india_snapshot_deduped(self, symbol: str) -> Any:
        """Deduplicate concurrent fetch_india_snapshot calls for same symbol."""
        key = symbol.upper()
        
        # If already in-flight, wait for existing task
        if key in self._inflight_india_snapshot:
            existing_task = self._inflight_india_snapshot[key]
            if not existing_task.done():
                try:
                    return await existing_task
                except Exception:
                    pass  # Fall through to retry
        
        # Create new task
        task = asyncio.create_task(fetch_india_snapshot(symbol))
        self._inflight_india_snapshot[key] = task
        
        def _cleanup(_task: asyncio.Task[Any]) -> None:
            self._inflight_india_snapshot.pop(key, None)
        
        task.add_done_callback(_cleanup)
        
        try:
            return await task
        except Exception:
            raise

    def _evict_lru_cache(self, cache: dict[str, tuple[float, Any]], max_size: int) -> None:
        """Evict least recently used entries when cache exceeds max_size."""
        if len(cache) <= max_size:
            return
        # Sort by timestamp (oldest first) and remove 20% of entries
        to_remove = max(1, len(cache) - max_size + max_size // 5)
        sorted_keys = sorted(cache.keys(), key=lambda k: cache[k][0])
        for key in sorted_keys[:to_remove]:
            cache.pop(key, None)
            # Also clean up refresh tasks for snapshot cache
            if key in self._snapshot_refresh_tasks:
                task = self._snapshot_refresh_tasks.pop(key, None)
                if task and not task.done():
                    task.cancel()

    async def _safe_async(
        self,
        coro: Any,
        *,
        timeout_s: float,
        default: Any,
        label: str,
    ) -> Any:
        task = asyncio.ensure_future(coro)
        done, pending = await asyncio.wait({task}, timeout=timeout_s)
        if task in done:
            try:
                return task.result()
            except Exception as exc:
                logger.warning("%s failed: %s", label, exc)
                return default

        task.cancel()

        def _consume_result(done_task: asyncio.Future[Any]) -> None:
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        task.add_done_callback(_consume_result)
        logger.warning("%s timed out after %.2fs", label, timeout_s)
        return default

    def _quote_payload(
        self,
        *,
        india_snap: Any,
        yahoo_quote: Any,
        current_quote: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        india_price = safe_float(india_snap.current_price if india_snap else None)
        yahoo_price = safe_float(yahoo_quote.price if yahoo_quote else None)

        quote_price = india_price if india_price is not None else yahoo_price
        quote_source = (
            (india_snap.source if india_snap and india_price is not None else None)
            or ("Yahoo Finance" if yahoo_price is not None else None)
            or str((current_quote or {}).get("source") or "")
            or "Unavailable"
        )
        quote_source_url = (
            (india_snap.source_url if india_snap and india_price is not None else None)
            or (yahoo_quote.source_url if yahoo_quote and yahoo_price is not None else None)
            or str((current_quote or {}).get("source_url") or "")
        )

        change_pct = safe_float(
            (india_snap.change_pct if india_snap and india_price is not None else None)
            or (yahoo_quote.change_pct if yahoo_quote and yahoo_price is not None else None)
            or (current_quote or {}).get("change_pct")
        )

        return {
            "price": quote_price,
            "change_pct": change_pct,
            "currency": (yahoo_quote.currency if yahoo_quote else None) or str((current_quote or {}).get("currency") or "INR") or "INR",
            "source": quote_source,
            "source_url": quote_source_url,
        }

    def _annotate_cache_freshness(
        self,
        snapshot: dict[str, Any],
        *,
        cache_age_s: float,
        cache_state: str,
    ) -> dict[str, Any]:
        freshness = dict(snapshot.get("freshness") or {})
        freshness["cache"] = {
            "state": cache_state,
            "age_seconds": round(max(0.0, cache_age_s), 2),
            "ttl_seconds": _SNAPSHOT_CACHE_TTL_S,
            "stale_ttl_seconds": _SNAPSHOT_CACHE_STALE_TTL_S,
        }
        freshness.setdefault("quote_target_seconds", _QUOTE_TARGET_FRESHNESS_S)
        freshness.setdefault("quote_age_seconds", round(max(0.0, cache_age_s), 2))
        snapshot["freshness"] = freshness
        return snapshot

    async def _refresh_quote_if_needed(
        self,
        snapshot: dict[str, Any],
        *,
        symbol: str,
        cache_age_s: float,
    ) -> dict[str, Any]:
        if not symbol:
            return snapshot

        freshness = dict(snapshot.get("freshness") or {})
        freshness["quote_target_seconds"] = _QUOTE_TARGET_FRESHNESS_S

        if cache_age_s <= _QUOTE_TARGET_FRESHNESS_S:
            freshness["quote_age_seconds"] = round(max(0.0, cache_age_s), 2)
            snapshot["freshness"] = freshness
            return snapshot

        india_snap = await self._safe_async(
            fetch_india_snapshot(symbol),
            timeout_s=_SNAPSHOT_QUOTE_REFRESH_TIMEOUT_S,
            default=None,
            label=f"quote_refresh_india:{symbol}",
        )
        yahoo_quote = None
        if india_snap is None:
            yahoo_quote = await self._safe_async(
                self._fetch_yahoo_best(symbol, timeout_s=max(1.2, _SNAPSHOT_QUOTE_REFRESH_TIMEOUT_S)),
                timeout_s=max(1.2, _SNAPSHOT_QUOTE_REFRESH_TIMEOUT_S),
                default=None,
                label=f"quote_refresh_yahoo:{symbol}",
            )

        quote = self._quote_payload(
            india_snap=india_snap,
            yahoo_quote=yahoo_quote,
            current_quote=snapshot.get("quote") if isinstance(snapshot.get("quote"), dict) else None,
        )
        if safe_float(quote.get("price")) is not None:
            snapshot["quote"] = quote
            freshness["quote_age_seconds"] = 0.0
            freshness["quote_refresh"] = "live"
        else:
            freshness["quote_age_seconds"] = round(max(0.0, cache_age_s), 2)
            freshness["quote_refresh"] = "cache"

        snapshot["freshness"] = freshness
        return snapshot

    def _schedule_snapshot_refresh(self, cache_key: str, identifier: str, period: str) -> None:
        existing = self._snapshot_refresh_tasks.get(cache_key)
        if existing is not None and not existing.done():
            return

        async def _refresh() -> None:
            try:
                await self.company_snapshot(identifier, period=period, _force_refresh=True)
            except Exception as exc:
                logger.debug("snapshot refresh failed for %s: %s", cache_key, exc)

        task = asyncio.create_task(_refresh())
        self._snapshot_refresh_tasks[cache_key] = task

        def _cleanup(_task: asyncio.Task[Any]) -> None:
            self._snapshot_refresh_tasks.pop(cache_key, None)

        task.add_done_callback(_cleanup)

    async def search(self, query: str, limit: int = 8) -> dict[str, Any]:
        text = (query or "").strip()
        if not text:
            return {"query": "", "items": [], "as_of": _iso_now()}

        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        # ── Step 0: fast alias / common-name lookup ──────────────────────────
        # Check _SYMBOL_ALIASES first, then confirm against _KNOWN_COMPANIES for
        # an instant result with zero network overhead.  This resolves common
        # names such as "tata motors" → "TATAMOTORS" and "infosys" → "INFY"
        # even when the IKG database is empty or slow.
        alias_sym = _SYMBOL_ALIASES.get(text.upper().strip())
        if alias_sym and alias_sym not in seen:
            known = _KNOWN_COMPANIES.get(alias_sym)
            if known:
                seen.add(alias_sym)
                items.append(
                    {
                        "symbol": alias_sym,
                        "cin": _KNOWN_SYMBOL_CIN.get(alias_sym),
                        "isin": _KNOWN_SYMBOL_ISIN.get(alias_sym) or known[2],
                        "name": known[0],
                        "sector": known[1],
                        "confidence": 0.90,
                        "source": "name_alias_lookup",
                    }
                )
            else:
                # Unknown company in alias but not in known-companies table —
                # fall back to a quick market snapshot to confirm it exists.
                snap = await self._safe_async(
                    fetch_india_snapshot(alias_sym),
                    timeout_s=max(2.0, _SNAPSHOT_QUOTE_REFRESH_TIMEOUT_S),
                    default=None,
                    label=f"search_alias:{alias_sym}",
                )
                if snap is not None:
                    seen.add(alias_sym)
                    items.append(
                        {
                            "symbol": alias_sym,
                            "cin": None,
                            "isin": snap.isin or None,
                            "name": snap.company_name or alias_sym,
                            "sector": snap.sector or snap.industry or "",
                            "confidence": 0.85,
                            "source": snap.source or "alias_lookup",
                        }
                    )

        entity: ResolvedCorporateEntity | None = None
        try:
            entity = await asyncio.wait_for(
                asyncio.to_thread(self._resolver.resolve, text),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            logger.debug("screener search resolver timeout for %s", text)
        except EntityLookupError as exc:
            logger.debug("screener search resolver error for %s: %s", text, exc)
        except Exception as exc:
            logger.debug("screener search resolver failure for %s: %s", text, exc)

        if entity is not None:
            sym = _clean_symbol(entity.nse_symbol or entity.bse_scrip_code or text)
            if sym and sym not in seen:
                seen.add(sym)
                items.append(
                    {
                        "symbol": sym,
                        "cin": entity.cin,
                        "isin": entity.isin,
                        "name": entity.name or sym,
                        "sector": entity.sector or "",
                        "confidence": entity.confidence,
                        "source": entity.source,
                    }
                )

        if len(items) < limit:
            fallback_symbol = _clean_symbol(text)
            if fallback_symbol and fallback_symbol not in seen:
                # Check static known-companies table first (instant, zero network)
                known_fb = _KNOWN_COMPANIES.get(fallback_symbol)
                if known_fb:
                    seen.add(fallback_symbol)
                    items.append(
                        {
                            "symbol": fallback_symbol,
                            "cin": _KNOWN_SYMBOL_CIN.get(fallback_symbol),
                            "isin": _KNOWN_SYMBOL_ISIN.get(fallback_symbol) or known_fb[2],
                            "name": known_fb[0],
                            "sector": known_fb[1],
                            "confidence": 0.80,
                            "source": "known_company_lookup",
                        }
                    )
                else:
                    snap = await self._safe_async(
                        fetch_india_snapshot(fallback_symbol),
                        timeout_s=max(2.0, _SNAPSHOT_QUOTE_REFRESH_TIMEOUT_S),
                        default=None,
                        label=f"search_snapshot:{fallback_symbol}",
                    )
                    if snap is not None:
                        seen.add(fallback_symbol)
                        items.append(
                            {
                                "symbol": fallback_symbol,
                                "cin": None,
                                "isin": snap.isin or None,
                                "name": snap.company_name or fallback_symbol,
                                "sector": snap.sector or snap.industry or "",
                                "confidence": 0.65,
                                "source": snap.source or "market_data",
                            }
                        )

        if len(items) < limit:
            try:
                name_hits = await asyncio.wait_for(
                    asyncio.to_thread(self._resolver.resolve_by_name, text, max(3, limit)),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                logger.debug("screener search name resolver timeout for %s", text)
                name_hits = []
            except EntityLookupError:
                name_hits = []
            except Exception as exc:
                logger.debug("screener search name resolver failure for %s: %s", text, exc)
                name_hits = []
            for hit in name_hits:
                sym = _clean_symbol(hit.nse_symbol or hit.bse_scrip_code or "")
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                items.append(
                    {
                        "symbol": sym,
                        "cin": hit.cin,
                        "isin": hit.isin,
                        "name": hit.name or sym,
                        "sector": hit.sector or "",
                        "confidence": hit.confidence,
                        "source": hit.source,
                    }
                )
                if len(items) >= limit:
                    break

        return {"query": text, "items": items[:limit], "as_of": _iso_now()}

    async def company_snapshot(
        self,
        identifier: str,
        *,
        period: str = "1Y",
        _force_refresh: bool = False,
        _allow_supplemental: bool = True,
    ) -> dict[str, Any]:
        period_u = (period or "1Y").strip().upper()
        if period_u not in _HISTORY_PERIODS:
            period_u = "1Y"

        identity = await self._resolve_identity(identifier)
        cache_key = f"{identity.symbol}:{period_u}:{identity.cin or ''}"
        cached = self._snapshot_cache.get(cache_key)

        if cached and not _force_refresh:
            cache_age_s = max(0.0, time.time() - cached[0])
            cached_snapshot = deepcopy(cached[1])
            cached_snapshot = await self._refresh_quote_if_needed(
                cached_snapshot,
                symbol=identity.symbol,
                cache_age_s=cache_age_s,
            )
            if cache_age_s <= _SNAPSHOT_CACHE_TTL_S:
                return self._annotate_cache_freshness(
                    cached_snapshot,
                    cache_age_s=cache_age_s,
                    cache_state="fresh",
                )
            if cache_age_s <= _SNAPSHOT_CACHE_STALE_TTL_S:
                self._schedule_snapshot_refresh(cache_key, identifier, period_u)
                return self._annotate_cache_freshness(
                    cached_snapshot,
                    cache_age_s=cache_age_s,
                    cache_state="stale",
                )

        if not identity.symbol:
            empty_snapshot = {
                "as_of": _iso_now(),
                "identifier": identifier,
                "resolved": {
                    "symbol": "",
                    "cin": identity.cin,
                    "isin": identity.isin,
                    "company_name": identity.company_name or (identifier or "").strip(),
                    "sector": identity.sector,
                    "confidence": identity.confidence,
                    "resolver_source": identity.source,
                },
                "quote": {
                    "price": None,
                    "change_pct": None,
                    "currency": "INR",
                    "source": "Unavailable",
                    "source_url": None,
                },
                "fundamentals": {"profile": {}, "metrics": {}, "cards": [], "sources": {}},
                "technicals": {
                    "status": "unavailable",
                    "reason": "unresolved_symbol",
                    "period": period_u,
                    "history_points": 0,
                    "history": {"dates": [], "prices": []},
                },
                "governance": {"status": "unavailable", "reason": "unresolved_symbol"},
                "promoter_chain": {},
                "insiders": {"directors": [], "facts": [], "counts": {"directors": 0, "insider_facts": 0}},
                "network": {},
                "provenance": {},
                "graph_health": {},
                "staleness": {},
                "events": {"news": [], "corporate": [], "corporate_actions": [], "insider_trades": [], "enforcement": []},
                "risk_signals": {"enforcement_count": 0, "graph_staleness_band": None, "governance_band": None},
                "score": compute_scores({"fundamentals": {"metrics": {}}, "technicals": {}, "governance": {}, "ikg": {"coverage": {}}, "risk_signals": {}}),
                "contradictions": [],
                "summary": {"positives": ["No strong quality edge is confirmed from the current data snapshot."], "negatives": ["No major red flags are currently evident from the tracked signals."]},
                "freshness": {
                    "generated_at": _iso_now(),
                    "history_as_of": None,
                    "latest_news_at": None,
                    "latest_corporate_at": None,
                    "age_hours": {"history": None, "news": None, "corporate": None},
                    "sections": {
                        "quote": {"status": "unavailable", "age_seconds": None, "target_seconds": _QUOTE_TARGET_FRESHNESS_S},
                        "technicals": {"status": "unavailable", "age_hours": None},
                        "governance": {"status": "unavailable", "age_hours": None},
                        "news": {"status": "unavailable", "age_hours": None},
                        "corporate": {"status": "unavailable", "age_hours": None},
                    },
                },
            }
            return self._annotate_cache_freshness(empty_snapshot, cache_age_s=0.0, cache_state="unresolved")

        provider_timeout_s = _SNAPSHOT_PROVIDER_TIMEOUT_S if _allow_supplemental else 4.5
        india_timeout_s = 8.5 if _allow_supplemental else _SNAPSHOT_PROVIDER_TIMEOUT_S
        delivery_timeout_s = 3.8 if _allow_supplemental else 2.5

        india_task = asyncio.create_task(
            self._safe_async(
                fetch_india_snapshot(identity.symbol),
                timeout_s=india_timeout_s,
                default=None,
                label=f"india_snapshot:{identity.symbol}",
            )
        )
        shareholding_task = asyncio.create_task(
            self._safe_async(
                fetch_shareholding_pattern(identity.symbol),
                timeout_s=provider_timeout_s,
                default=None,
                label=f"shareholding:{identity.symbol}",
            )
        )
        delivery_task = asyncio.create_task(
            self._safe_async(
                fetch_nse_delivery_snapshot(identity.symbol),
                timeout_s=delivery_timeout_s,
                default={"status": "unavailable", "reason": "timeout_or_error", "source": "NSE public archives"},
                label=f"delivery:{identity.symbol}",
            )
        )
        news_task = asyncio.create_task(
            self._safe_async(
                fetch_news(f"{identity.symbol} India stock", limit=14),
                timeout_s=provider_timeout_s,
                default=[],
                label=f"news:{identity.symbol}",
            )
        )
        official_task = asyncio.create_task(
            self._safe_async(
                asyncio.to_thread(fetch_nse_announcements, identity.isin or identity.symbol, 14),
                timeout_s=provider_timeout_s,
                default=[],
                label=f"official_announcements:{identity.symbol}",
            )
        )
        yahoo_task = asyncio.create_task(
            self._safe_async(
                self._fetch_yahoo_best(identity.symbol, timeout_s=max(3.0, provider_timeout_s)),
                timeout_s=max(3.0, provider_timeout_s),
                default=None,
                label=f"yahoo:{identity.symbol}",
            )
        )
        governance_task = asyncio.create_task(
            self._safe_async(
                self._governance_payload(identity.cin),
                timeout_s=provider_timeout_s,
                default={"status": "unavailable", "reason": "timeout_or_error"},
                label=f"governance:{identity.cin or identity.symbol}",
            )
        )
        network_task = asyncio.create_task(
            self._safe_async(
                self._network_payload(identity.cin),
                timeout_s=provider_timeout_s,
                default={"status": "unavailable", "reason": "timeout_or_error"},
                label=f"network:{identity.cin or identity.symbol}",
            )
        )
        provenance_task = asyncio.create_task(
            self._safe_async(
                self._provenance_payload(identity.cin),
                timeout_s=provider_timeout_s,
                default={"status": "unavailable", "reason": "timeout_or_error"},
                label=f"provenance:{identity.cin or identity.symbol}",
            )
        )
        health_task = asyncio.create_task(
            self._safe_async(
                self._health_payload(identity.cin),
                timeout_s=provider_timeout_s,
                default={"status": "unavailable", "reason": "timeout_or_error"},
                label=f"graph_health:{identity.cin or identity.symbol}",
            )
        )
        staleness_task = asyncio.create_task(
            self._safe_async(
                self._staleness_payload(identity.cin),
                timeout_s=provider_timeout_s,
                default={"status": "unavailable", "reason": "timeout_or_error"},
                label=f"staleness:{identity.cin or identity.symbol}",
            )
        )
        promoter_chain_task = asyncio.create_task(
            self._safe_async(
                self._promoter_chain_payload(identity.cin),
                timeout_s=provider_timeout_s,
                default={},
                label=f"promoter_chain:{identity.cin or identity.symbol}",
            )
        )
        enforcement_task = asyncio.create_task(
            self._safe_async(
                self._enforcement_payload(identity.cin),
                timeout_s=provider_timeout_s,
                default=[],
                label=f"enforcement:{identity.cin or identity.symbol}",
            )
        )

        (
            india_snap,
            shareholding,
            delivery_data,
            news_rows,
            official_rows,
            yahoo_quote,
            governance,
            network,
            provenance,
            health,
            staleness,
            promoter_chain,
            enforcement_actions,
        ) = await asyncio.gather(
            india_task,
            shareholding_task,
            delivery_task,
            news_task,
            official_task,
            yahoo_task,
            governance_task,
            network_task,
            provenance_task,
            health_task,
            staleness_task,
            promoter_chain_task,
            enforcement_task,
        )

        dates: list[str] = []
        prices: list[float] = []
        chart_quote = None
        if yahoo_quote is not None and yahoo_quote.series_dates and yahoo_quote.series_closes:
            dates, prices = _filter_history_period(
                list(yahoo_quote.series_dates),
                list(yahoo_quote.series_closes),
                period_u,
            )
        elif india_snap is not None and getattr(india_snap, "series_dates", None) and getattr(india_snap, "series_closes", None):
            dates, prices = _filter_history_period(
                list(getattr(india_snap, "series_dates", []) or []),
                list(getattr(india_snap, "series_closes", []) or []),
                period_u,
            )

        supplemental_tasks: dict[str, asyncio.Task[Any]] = {}
        if not news_rows:
            retry_query = (
                (india_snap.company_name if india_snap and getattr(india_snap, "company_name", None) else None)
                or identity.company_name
                or identity.symbol
            )
            if retry_query:
                supplemental_tasks["news_retry"] = asyncio.create_task(
                    self._safe_async(
                        fetch_news(f"{retry_query} India stock", limit=14),
                        timeout_s=max(3.5, _SNAPSHOT_PROVIDER_TIMEOUT_S * 0.75),
                        default=[],
                        label=f"news_retry:{identity.symbol}",
                    )
                )

        if not official_rows and identity.symbol:
            supplemental_tasks["official_retry"] = asyncio.create_task(
                self._safe_async(
                    asyncio.to_thread(fetch_nse_announcements, identity.symbol, 14),
                    timeout_s=max(3.5, _SNAPSHOT_PROVIDER_TIMEOUT_S * 0.75),
                    default=[],
                    label=f"official_retry:{identity.symbol}",
                )
            )

        if not dates:
            supplemental_tasks["chart_quote"] = asyncio.create_task(
                self._safe_async(
                    self._fetch_yahoo_chart_best(identity.symbol, timeout_s=3.5),
                    timeout_s=3.8,
                    default=None,
                    label=f"yahoo_chart:{identity.symbol}",
                )
            )

        if _allow_supplemental:
            supplemental_tasks["peers"] = asyncio.create_task(
                self._safe_async(
                    self._peer_comparison(
                        identity=identity,
                        sector=identity.sector or (getattr(india_snap, "sector", "") if india_snap else ""),
                        limit=4,
                    ),
                    timeout_s=3.5,
                    default={"status": "unavailable", "reason": "timeout_or_error", "items": []},
                    label=f"peers:{identity.symbol}",
                )
            )

        supplemental_results: dict[str, Any] = {}
        if supplemental_tasks:
            task_keys = list(supplemental_tasks.keys())
            task_values = await asyncio.gather(*supplemental_tasks.values(), return_exceptions=True)
            supplemental_results = {
                key: (None if isinstance(value, Exception) else value)
                for key, value in zip(task_keys, task_values)
            }

        if not news_rows:
            news_rows = supplemental_results.get("news_retry") or []
        if not official_rows:
            official_rows = supplemental_results.get("official_retry") or []

        chart_quote = supplemental_results.get("chart_quote")
        if chart_quote is not None and chart_quote.series_dates and chart_quote.series_closes:
            dates, prices = _filter_history_period(
                list(chart_quote.series_dates),
                list(chart_quote.series_closes),
                period_u,
            )

        peers = supplemental_results.get("peers") or {
            "status": "deferred" if not _allow_supplemental else "unavailable",
            "reason": "background_refresh_scheduled" if not _allow_supplemental else "timeout_or_error",
            "items": [],
        }

        technicals = compute_technicals(dates, prices)
        if chart_quote is not None and technicals.get("status") == "ok":
            technicals["source"] = "Yahoo Finance chart"

        fundamentals = self._build_fundamentals(
            identity=identity,
            india_snap=india_snap,
            yahoo_quote=yahoo_quote,
            shareholding=shareholding,
            provenance=provenance,
            promoter_chain=promoter_chain,
            delivery_data=delivery_data if isinstance(delivery_data, dict) else None,
        )

        news_rows_limited = list(news_rows or [])[:_MAX_NEWS_ITEMS]
        official_rows_limited = list(official_rows or [])[:_MAX_CORPORATE_ITEMS]
        enforcement_actions = list(enforcement_actions or [])[:_MAX_ENFORCEMENT_ITEMS]

        news: list[dict[str, Any]] = []
        for idx, row in enumerate(news_rows_limited):
            row_is_dict = isinstance(row, dict)
            row_dict = row if row_is_dict else {}
            news.append(
                _normalize_news_item(
                    {
                        "title": row_dict.get("title") if row_is_dict else getattr(row, "title", None),
                        "link": row_dict.get("link") if row_is_dict else getattr(row, "link", None),
                        "source": row_dict.get("source") if row_is_dict else getattr(row, "source", None),
                        "published": row_dict.get("published") if row_is_dict else getattr(row, "published", None),
                        "description": row_dict.get("description") if row_is_dict else getattr(row, "description", None),
                        "image": row_dict.get("image") if row_is_dict else getattr(row, "image", None),
                    },
                    idx,
                )
            )

        corporate: list[dict[str, Any]] = []
        for idx, row in enumerate(official_rows_limited):
            row_is_dict = isinstance(row, dict)
            row_dict = row if row_is_dict else {}
            corporate.append(
                _normalize_announcement(
                    {
                        "title": row_dict.get("title") if row_is_dict else getattr(row, "title", None),
                        "headline": row_dict.get("headline") if row_is_dict else getattr(row, "headline", None),
                        "subject": row_dict.get("subject") if row_is_dict else getattr(row, "subject", None),
                        "category": row_dict.get("category") if row_is_dict else getattr(row, "category", None),
                        "source": row_dict.get("source") if row_is_dict else getattr(row, "source", None),
                        "exchange": row_dict.get("exchange") if row_is_dict else getattr(row, "exchange", None),
                        "url": row_dict.get("url") if row_is_dict else getattr(row, "url", None),
                        "link": row_dict.get("link") if row_is_dict else getattr(row, "link", None),
                        "published": row_dict.get("published") if row_is_dict else getattr(row, "published", None),
                        "pubDate": row_dict.get("pubDate") if row_is_dict else getattr(row, "pubDate", None),
                        "snippet": row_dict.get("snippet") if row_is_dict else getattr(row, "snippet", None),
                        "description": row_dict.get("description") if row_is_dict else getattr(row, "description", None),
                    },
                    idx,
                )
            )

        if not news and corporate:
            news = [
                _normalize_news_item(
                    {
                        "title": row.get("title"),
                        "link": row.get("url"),
                        "source": row.get("source"),
                        "published": row.get("published"),
                        "description": row.get("snippet"),
                    },
                    idx,
                )
                for idx, row in enumerate(corporate[: min(12, len(corporate))])
            ]

        if not corporate and news:
            corporate = [
                _normalize_announcement(
                    {
                        "title": row.get("headline"),
                        "source": row.get("source"),
                        "url": row.get("url"),
                        "published": row.get("published"),
                        "category": "market_news",
                        "snippet": row.get("description"),
                    },
                    idx,
                )
                for idx, row in enumerate(news[: min(12, len(news))])
            ]

        insider_trades = [row for row in corporate if row.get("is_insider_trade")]
        corporate_actions = [row for row in corporate if row.get("is_corporate_action")]
        public_depth = fundamentals.setdefault("public_data_depth", {})
        public_depth["insider_trades"] = {
            "status": "ok" if insider_trades else "not_detected",
            "count": len(insider_trades),
            "source": "NSE/BSE exchange announcements",
            "items": insider_trades[:8],
        }
        public_depth["corporate_actions"] = {
            "status": "ok" if corporate_actions else "not_detected",
            "count": len(corporate_actions),
            "source": "NSE/BSE exchange announcements",
            "items": corporate_actions[:10],
        }
        quote_payload = self._quote_payload(india_snap=india_snap, yahoo_quote=yahoo_quote or chart_quote)
        identity_name = str(identity.company_name or "").strip()
        market_name = (india_snap.company_name if india_snap and getattr(india_snap, "company_name", None) else None) or (yahoo_quote.name if yahoo_quote else None)
        if identity_name and identity_name.upper() not in {identity.symbol.upper(), str(identifier).upper()}:
            resolved_company_name = identity_name
        else:
            resolved_company_name = market_name or identity_name or identity.symbol
        has_shareholding = bool(shareholding) or any(
            (fundamentals.get("metrics") or {}).get(key) is not None
            for key in ("promoter_holding_pct", "fii_holding_pct", "dii_holding_pct", "public_holding_pct")
        )

        snapshot = {
            "as_of": _iso_now(),
            "identifier": identifier,
            "resolved": {
                "symbol": identity.symbol,
                "cin": identity.cin,
                "isin": identity.isin or (india_snap.isin if india_snap else None),
                "company_name": resolved_company_name,
                "sector": identity.sector or (india_snap.sector if india_snap else None) or (india_snap.industry if india_snap else None),
                "confidence": identity.confidence,
                "resolver_source": identity.source,
            },
            "quote": quote_payload,
            "fundamentals": fundamentals,
            "technicals": {
                **technicals,
                "period": period_u,
                "history_points": len(dates),
                "history": {"dates": dates, "prices": prices},
            },
            "governance": governance,
            "promoter_chain": promoter_chain,
            "insiders": self._extract_insiders(network=network, provenance=provenance),
            "network": network,
            "provenance": provenance,
            "graph_health": health,
            "staleness": staleness,
            "events": {
                "news": news,
                "corporate": corporate,
                "corporate_actions": corporate_actions,
                "insider_trades": insider_trades,
                "enforcement": enforcement_actions,
            },
            "peers": peers,
            "source_health": {
                "india_snapshot": {"status": "ok" if india_snap is not None else "unavailable"},
                "yahoo_quote": {"status": "ok" if yahoo_quote is not None else "unavailable"},
                "yahoo_chart": {"status": "ok" if chart_quote is not None else "unavailable"},
                "shareholding": {"status": "ok" if has_shareholding else "unavailable"},
                "news": {"status": "ok" if news else "unavailable", "count": len(news)},
                "corporate": {"status": "ok" if corporate else "unavailable", "count": len(corporate)},
                "corporate_actions": {"status": "ok" if corporate_actions else "not_detected", "count": len(corporate_actions)},
                "insider_trades": {"status": "ok" if insider_trades else "not_detected", "count": len(insider_trades)},
                "delivery": {"status": str(((fundamentals.get("public_data_depth") or {}).get("delivery_pct") or {}).get("status") or "unavailable")},
                "annual_reports": {"status": str(((fundamentals.get("public_data_depth") or {}).get("annual_reports") or {}).get("status") or "unavailable"), "count": len((((fundamentals.get("public_data_depth") or {}).get("annual_reports") or {}).get("items") or []))},
                "governance": {"status": str((governance or {}).get("status") or ("ok" if governance else "unavailable"))},
                "peers": {"status": str((peers or {}).get("status") or "unavailable"), "count": len((peers or {}).get("items") or [])},
                "segments": {"status": str((((fundamentals.get("public_data_depth") or {}).get("segments") or {}).get("status") or "unavailable") )},
                "rpt": {"status": str((((fundamentals.get("public_data_depth") or {}).get("related_party_transactions") or {}).get("status") or "unavailable") )},
            },
            "risk_signals": {
                "enforcement_count": len(enforcement_actions or []),
                "graph_staleness_band": (staleness or {}).get("band"),
                "governance_band": (governance or {}).get("band"),
            },
        }

        score = compute_scores(snapshot)
        snapshot["score"] = score
        snapshot["contradictions"] = detect_contradictions(snapshot)
        snapshot["summary"] = summarize_positive_negative(snapshot)
        snapshot["freshness"] = self._freshness(
            news=news,
            corporate=corporate,
            technicals=technicals,
            quote=quote_payload,
            governance=governance,
        )

        self._evict_lru_cache(self._snapshot_cache, self._snapshot_cache_max)
        self._snapshot_cache[cache_key] = (time.time(), snapshot)

        out = deepcopy(snapshot)
        out = self._annotate_cache_freshness(out, cache_age_s=0.0, cache_state="live")
        return out

    async def company_financials(self, identifier: str) -> dict[str, Any]:
        snapshot = await self.company_snapshot(identifier, period="1Y")
        resolved = snapshot.get("resolved") or {}
        symbol = _clean_symbol(str(resolved.get("symbol") or identifier or ""))
        cin = str(resolved.get("cin") or "")

        financials_cache_key = f"{symbol}:{cin}"
        cached_financials = self._financials_cache.get(financials_cache_key)
        if cached_financials is not None:
            financials_cache_age_s = max(0.0, time.time() - cached_financials[0])
            if financials_cache_age_s <= _FINANCIALS_CACHE_TTL_S:
                cached_out = deepcopy(cached_financials[1])
                freshness_cached = dict(cached_out.get("freshness") or {})
                freshness_cached["financials_cache"] = {
                    "state": "fresh",
                    "age_seconds": round(financials_cache_age_s, 2),
                    "ttl_seconds": _FINANCIALS_CACHE_TTL_S,
                }
                cached_out["freshness"] = freshness_cached
                return cached_out

        cache_task = asyncio.create_task(
            self._safe_async(
                asyncio.to_thread(self._load_company_financials_cache, symbol=symbol, cin=cin),
                timeout_s=_SNAPSHOT_PROVIDER_TIMEOUT_S,
                default=None,
                label=f"financial_cache:{symbol or cin}",
            )
        )
        official_task = asyncio.create_task(
            self._safe_async(
                asyncio.to_thread(self._load_official_financial_rows, symbol=symbol, cin=cin),
                timeout_s=_SNAPSHOT_PROVIDER_TIMEOUT_S,
                default=[],
                label=f"financial_official:{symbol or cin}",
            )
        )
        cache_row, official_rows = await asyncio.gather(cache_task, official_task)

        needs_live_pull = not (
            cache_row
            and (
                _coerce_json(cache_row.get("income_statement_json"))
                or _coerce_json(cache_row.get("balance_sheet_json"))
                or _coerce_json(cache_row.get("cashflow_json"))
            )
        )

        screener_live_task = None
        yfinance_live_task = None
        if needs_live_pull and symbol:
            screener_live_task = asyncio.create_task(
                self._safe_async(
                    asyncio.to_thread(fetch_screener_financials, symbol, 14.0),
                    timeout_s=14.0,
                    default=None,
                    label=f"financial_screener_live:{symbol}",
                )
            )
            yfinance_live_task = asyncio.create_task(
                self._safe_async(
                    asyncio.to_thread(fetch_yfinance_financials, symbol),
                    timeout_s=14.0,
                    default=None,
                    label=f"financial_yfinance_live:{symbol}",
                )
            )

        screener_live: dict[str, Any] | None = None
        yfinance_live: dict[str, Any] | None = None
        if screener_live_task is not None and yfinance_live_task is not None:
            screener_live, yfinance_live = await asyncio.gather(screener_live_task, yfinance_live_task)

        normalized = _normalize_financial_payload(
            symbol=symbol,
            snapshot=snapshot,
            cache_row=cache_row,
            official_rows=official_rows,
            screener_live=screener_live,
            yfinance_live=yfinance_live,
        )

        fundamentals = snapshot.get("fundamentals") or {}
        freshness = {
            **(snapshot.get("freshness") or {}),
            "filings_as_of": normalized.get("filings_as_of"),
        }
        sections = dict(freshness.get("sections") or {})
        filings_as_of = normalized.get("filings_as_of")
        filings_state = "unavailable"
        filings_age_days = None
        filings_dt = _parse_dt(filings_as_of)
        if filings_dt is not None:
            if filings_dt.tzinfo is None:
                filings_dt = filings_dt.replace(tzinfo=timezone.utc)
            filings_age_days = round(max(0.0, (_now_utc() - filings_dt).total_seconds() / 86400.0), 2)
            if filings_age_days <= 140:
                filings_state = "live"
            elif filings_age_days <= _FINANCIAL_STALENESS_DAYS:
                filings_state = "stale"
            else:
                filings_state = "aging"
        sections["fundamentals"] = {
            "status": filings_state,
            "filings_as_of": filings_as_of,
            "age_days": filings_age_days,
        }
        freshness["sections"] = sections

        freshness["financials_cache"] = {
            "state": "live",
            "age_seconds": 0.0,
            "ttl_seconds": _FINANCIALS_CACHE_TTL_S,
        }

        result = {
            "as_of": snapshot.get("as_of"),
            "resolved": snapshot.get("resolved"),
            "fundamentals": fundamentals,
            "periods": normalized.get("periods") or [],
            "ratios": normalized.get("ratios") or {},
            "income_statement": normalized.get("income_statement") or {"unit": "INR crore", "rows": []},
            "balance_sheet": normalized.get("balance_sheet") or {"unit": "INR crore", "rows": []},
            "cash_flow": normalized.get("cash_flow") or {"unit": "INR crore", "rows": []},
            "sources": normalized.get("sources") or [],
            "analytics": normalized.get("analytics") or {},
            "quality": normalized.get("quality") or {},
            "score": snapshot.get("score"),
            "summary": snapshot.get("summary"),
            "freshness": freshness,
        }
        self._evict_lru_cache(self._financials_cache, self._financials_cache_max)
        self._financials_cache[financials_cache_key] = (time.time(), deepcopy(result))
        return result

    async def company_technicals(self, identifier: str, *, period: str = "1Y") -> dict[str, Any]:
        snapshot = await self.company_snapshot(identifier, period=period)
        return {
            "as_of": snapshot.get("as_of"),
            "resolved": snapshot.get("resolved"),
            "quote": snapshot.get("quote"),
            "technicals": snapshot.get("technicals"),
            "contradictions": snapshot.get("contradictions"),
            "freshness": snapshot.get("freshness"),
        }

    async def company_events(self, identifier: str, *, limit: int = 25) -> dict[str, Any]:
        snapshot = await self.company_snapshot(identifier, period="3M")
        events = snapshot.get("events") or {}
        news = list(events.get("news") or [])[: max(0, limit)]
        corporate = list(events.get("corporate") or [])[: max(0, limit)]
        corporate_actions = list(events.get("corporate_actions") or [])[: max(0, limit)]
        insider_trades = list(events.get("insider_trades") or [])[: max(0, limit)]
        enforcement = list(events.get("enforcement") or [])[: max(0, limit)]
        return {
            "as_of": snapshot.get("as_of"),
            "resolved": snapshot.get("resolved"),
            "events": {
                "news": news,
                "corporate": corporate,
                "corporate_actions": corporate_actions,
                "insider_trades": insider_trades,
                "enforcement": enforcement,
            },
            "freshness": snapshot.get("freshness"),
        }

    async def analyze(self, identifier: str) -> dict[str, Any]:
        snapshot = await self.company_snapshot(identifier, period="1Y")
        fundamentals = snapshot.get("fundamentals") or {}
        profile = fundamentals.get("profile") or {}
        score = snapshot.get("score") or {}
        positives = (snapshot.get("summary") or {}).get("positives") or []
        negatives = (snapshot.get("summary") or {}).get("negatives") or []
        contradictions = snapshot.get("contradictions") or []

        narrative_parts: list[str] = []
        name = ((snapshot.get("resolved") or {}).get("company_name") or (snapshot.get("resolved") or {}).get("symbol") or "This company")
        grade = score.get("grade", "N/A")
        p_score = score.get("prospekt_score")
        if p_score is not None:
            narrative_parts.append(f"{name} currently scores {p_score}/100 (grade {grade}) on the multi-pillar screener model.")
        if profile.get("overview"):
            narrative_parts.append(str(profile.get("overview")))
        if positives:
            narrative_parts.append(f"Strengths: {positives[0]}")
        if negatives:
            narrative_parts.append(f"Risks: {negatives[0]}")
        if contradictions:
            narrative_parts.append(f"Watchpoint: {contradictions[0].get('title')}.")

        return {
            "as_of": snapshot.get("as_of"),
            "resolved": snapshot.get("resolved"),
            "analysis": {
                "narrative": " ".join(part.strip() for part in narrative_parts if part).strip(),
                "positives": positives,
                "negatives": negatives,
                "contradictions": contradictions,
                "score": score,
            },
            "snapshot": snapshot,
        }

    async def query_screen(
        self,
        query: str,
        *,
        limit: int = 25,
        universe: list[str] | None = None,
    ) -> dict[str, Any]:
        parsed = parse_nl_filters(query)
        safe_limit = max(1, int(limit))
        candidate_budget = min(_QUERY_SCREEN_MAX_CANDIDATES, max(12, safe_limit * 2))
        candidate_symbols = await self._candidate_universe(parsed.keywords, universe=universe, limit=candidate_budget)

        requires_technicals = bool(
            parsed.require_above_200dma
            or parsed.min_rsi is not None
            or parsed.max_rsi is not None
        )

        sem = asyncio.Semaphore(_QUERY_SCREEN_CONCURRENCY)

        async def _evaluate(symbol: str) -> dict[str, Any] | None:
            async with sem:
                try:
                    return await asyncio.wait_for(
                        self._screen_symbol(
                            symbol,
                            parsed,
                            resolve_identity=False,
                            yahoo_timeout_s=_QUERY_SCREEN_YAHOO_TIMEOUT_S,
                            include_yahoo=requires_technicals,
                        ),
                        timeout=_QUERY_SCREEN_SYMBOL_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    logger.debug("query_screen timed out evaluating %s", symbol)
                    return None
                except Exception as exc:
                    logger.debug("query_screen failed evaluating %s: %s", symbol, exc)
                    return None

        matches: list[dict[str, Any]] = []
        tasks = [asyncio.create_task(_evaluate(sym)) for sym in candidate_symbols]
        try:
            for completed in asyncio.as_completed(tasks, timeout=_QUERY_SCREEN_TOTAL_TIMEOUT_S):
                try:
                    row = await completed
                except asyncio.TimeoutError:
                    break
                if isinstance(row, dict):
                    matches.append(row)
        except asyncio.TimeoutError:
            logger.debug("query_screen total time budget reached for query=%s", query)
        finally:
            pending_symbols = []
            for i, task in enumerate(tasks):
                if not task.done():
                    task.cancel()
                    if i < len(candidate_symbols):
                        pending_symbols.append(candidate_symbols[i])
            if pending_symbols:
                logger.info("query_screen cancelled %d pending tasks for symbols: %s", len(pending_symbols), ", ".join(pending_symbols[:10]))

        matches.sort(key=lambda item: safe_float((item.get("score") or {}).get("prospekt_score")) or -1.0, reverse=True)
        return {
            "as_of": _iso_now(),
            "query": query,
            "parsed_filter": parsed.to_dict(),
            "universe_size": len(candidate_symbols),
            "match_count": len(matches),
            "matches": matches[:safe_limit],
        }

    async def _resolve_identity(self, identifier: str) -> _ResolvedIdentity:
        query = (identifier or "").strip()
        if not query:
            return _ResolvedIdentity(query="", symbol="")

        cache_lookup = query.upper()
        cached_identity = self._identity_cache.get(cache_lookup)
        if cached_identity is not None and (time.time() - cached_identity[0]) <= _IDENTITY_CACHE_TTL_S:
            return cached_identity[1]

        symbol = _clean_symbol(query)
        normalized_query = query.upper().removesuffix(".NS").removesuffix(".BO").removesuffix(".NSE").removesuffix(".BSE")
        symbol_like = bool(symbol) and _clean_symbol(normalized_query) == symbol and len(symbol) <= 14

        entity: ResolvedCorporateEntity | None = None
        if not symbol_like:
            entity = await self._safe_async(
                asyncio.to_thread(self._resolver.resolve, query),
                timeout_s=1.5,
                default=None,
                label=f"resolver:{query}",
            )

        cin = None
        isin = None
        company_name = None
        sector = None
        confidence = None
        source = "symbol_guess"

        if entity is not None:
            symbol = _clean_symbol(entity.nse_symbol or entity.bse_scrip_code or symbol)
            cin = entity.cin
            isin = entity.isin
            company_name = entity.name
            sector = entity.sector
            confidence = entity.confidence
            source = entity.source

        if not symbol and isin:
            symbol = _KNOWN_ISIN_SYMBOLS.get(isin.upper(), "")
        if not symbol and cin:
            symbol = cin
        if symbol and not isin:
            isin = _KNOWN_SYMBOL_ISIN.get(symbol.upper(), isin)

        # Exact ticker lookup is cheap and the main path to a CIN for plain
        # symbol queries (e.g. "RELIANCE") — do not gate it on symbol_like.
        ticker_entity: ResolvedCorporateEntity | None = None
        if symbol:
            ticker_entity = await self._safe_async(
                asyncio.to_thread(self._resolver.resolve_by_ticker, symbol),
                timeout_s=1.5,
                default=None,
                label=f"ticker_resolver:{symbol}",
            )

        if ticker_entity is not None:
            cin = cin or ticker_entity.cin
            isin = isin or ticker_entity.isin
            company_name = company_name or ticker_entity.name
            sector = sector or ticker_entity.sector
            confidence = confidence if confidence is not None else ticker_entity.confidence
            if source == "symbol_guess":
                source = ticker_entity.source

        isin_entity: ResolvedCorporateEntity | None = None
        if isin and not cin:
            isin_entity = await self._safe_async(
                asyncio.to_thread(self._resolver.resolve_by_isin, isin),
                timeout_s=1.5,
                default=None,
                label=f"isin_resolver:{isin}",
            )

        if isin_entity is not None:
            symbol = symbol or _clean_symbol(isin_entity.nse_symbol or isin_entity.bse_scrip_code or "")
            cin = cin or isin_entity.cin
            company_name = company_name or isin_entity.name
            sector = sector or isin_entity.sector
            confidence = confidence if confidence is not None else isin_entity.confidence
            if source == "symbol_guess":
                source = isin_entity.source

        if symbol and not symbol_like:
            snap = await self._safe_async(
                fetch_india_snapshot(symbol),
                timeout_s=max(2.5, _SNAPSHOT_QUOTE_REFRESH_TIMEOUT_S),
                default=None,
                label=f"identity_snapshot:{symbol}",
            )
            if snap is not None:
                company_name = company_name or snap.company_name or symbol
                sector = sector or snap.sector or snap.industry or None
                isin = isin or (snap.isin or None)
                cin = cin or (getattr(snap, "cin", None) or None)

        if not cin and symbol:
            cin = _KNOWN_SYMBOL_CIN.get(symbol.upper())
        if not isin and symbol:
            isin = isin or _KNOWN_SYMBOL_ISIN.get(symbol.upper())

        resolved = _ResolvedIdentity(
            query=query,
            symbol=symbol,
            cin=cin,
            isin=isin,
            company_name=company_name or symbol or query,
            sector=sector,
            confidence=confidence,
            source=source,
        )
        self._evict_lru_cache(self._identity_cache, self._identity_cache_max)
        self._identity_cache[cache_lookup] = (time.time(), resolved)
        return resolved

    def _load_company_financials_cache(self, *, symbol: str, cin: str) -> dict[str, Any] | None:
        db_url = get_database_url()
        if not db_url:
            return None
        try:
            from psycopg.rows import dict_row

            with connect_postgres(db_url, row_factory=dict_row, connect_timeout=6) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select
                          cin,
                          nse_symbol,
                          sources_used,
                          validated_metrics_json,
                          discrepancies_json,
                          income_statement_json,
                          balance_sheet_json,
                          cashflow_json,
                          fetched_at,
                          updated_at
                        from company_financials
                        where
                          (%s <> '' and upper(nse_symbol) = upper(%s))
                          or (%s <> '' and cin = %s)
                        order by updated_at desc nulls last, fetched_at desc nulls last
                        limit 1
                        """,
                        (symbol, symbol, cin, cin),
                    )
                    row = cur.fetchone()
            return dict(row) if row else None
        except Exception as exc:
            logger.debug("company_financials cache lookup unavailable for %s: %s", symbol, exc)
            return None

    def _load_official_financial_rows(self, *, symbol: str, cin: str) -> list[dict[str, Any]]:
        db_url = get_database_url()
        if not db_url:
            return []
        try:
            from psycopg.rows import dict_row

            with connect_postgres(db_url, row_factory=dict_row, connect_timeout=6) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select
                          exchange,
                          source_uid,
                          cin,
                          symbol,
                          company_name,
                          announced_at,
                          period_start,
                          period_end,
                          as_of_date,
                          revenue_from_operations,
                          total_income,
                          profit_before_tax,
                          profit_after_tax,
                          eps_basic,
                          eps_diluted,
                          net_worth,
                          source_url,
                          attachment_url
                        from financial_results_xbrl
                        where
                          (%s <> '' and upper(symbol) = upper(%s))
                          or (%s <> '' and cin = %s)
                        order by period_end desc nulls last, as_of_date desc nulls last, announced_at desc nulls last
                        limit 12
                        """,
                        (symbol, symbol, cin, cin),
                    )
                    rows = cur.fetchall()
            return [dict(row) for row in rows] if rows else []
        except Exception as exc:
            logger.debug("official financial rows lookup unavailable for %s: %s", symbol, exc)
            return []

    async def _fetch_yahoo_best(self, symbol: str, *, timeout_s: float = 18.0):
        for candidate in _history_candidates(symbol):
            quote = await fetch_yahoo_quote(candidate, timeout_s=timeout_s, cache_ttl_s=60.0)
            if quote is not None:
                return quote
        return None

    async def _fetch_yahoo_chart_best(self, symbol: str, *, timeout_s: float = 4.0):
        for candidate in _history_candidates(symbol):
            quote = await fetch_yahoo_chart(candidate, timeout_s=timeout_s, cache_ttl_s=90.0)
            if quote is not None and quote.series_closes:
                return quote
        return None

    async def _governance_payload(self, cin: str | None) -> dict[str, Any]:
        if not cin:
            return {"status": "unavailable", "reason": "cin_missing"}
        try:
            result = await asyncio.to_thread(self._governance.score_company, cin)
            if result is None:
                return {}
            return result_to_dict(result)
        except GovernanceLookupError as exc:
            logger.debug("governance lookup error for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "lookup_error"}
        except Exception as exc:
            logger.debug("governance failure for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "runtime_error"}

    async def _network_payload(self, cin: str | None) -> dict[str, Any]:
        if not cin:
            return {"status": "unavailable", "reason": "cin_missing"}
        try:
            result = await asyncio.to_thread(self._network.network, cin)
            return result or {}
        except NetworkLookupError as exc:
            logger.debug("network lookup error for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "lookup_error"}
        except Exception as exc:
            logger.debug("network failure for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "runtime_error"}

    async def _provenance_payload(self, cin: str | None) -> dict[str, Any]:
        if not cin:
            return {"status": "unavailable", "reason": "cin_missing"}
        try:
            result = await asyncio.to_thread(self._provenance.page, cin)
            return result or {}
        except ProvenanceLookupError as exc:
            logger.debug("provenance lookup error for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "lookup_error"}
        except Exception as exc:
            logger.debug("provenance failure for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "runtime_error"}

    async def _health_payload(self, cin: str | None) -> dict[str, Any]:
        if not cin:
            return {"status": "unavailable", "reason": "cin_missing"}
        try:
            result = await asyncio.to_thread(self._health.company, cin)
            return result or {}
        except GraphHealthError as exc:
            logger.debug("graph health error for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "lookup_error"}
        except Exception as exc:
            logger.debug("graph health failure for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "runtime_error"}

    async def _staleness_payload(self, cin: str | None) -> dict[str, Any]:
        if not cin:
            return {"status": "unavailable", "reason": "cin_missing"}
        try:
            verdict = await asyncio.to_thread(self._staleness.check_company, cin)
            return {
                "band": verdict.band,
                "needs_refresh": verdict.needs_refresh,
                "age_days": verdict.age_days,
                "last_updated": verdict.last_updated,
                "sources_checked": verdict.sources_checked,
                "reason": verdict.reason,
            }
        except Exception as exc:
            logger.debug("staleness failure for %s: %s", cin, exc)
            return {"status": "unavailable", "reason": "runtime_error"}

    async def _promoter_chain_payload(self, cin: str | None) -> dict[str, Any]:
        if not cin:
            return {"status": "unavailable", "reason": "cin_missing", "promoter_chain": []}
        try:
            return await self._graph.get_promoter_chain(cin)
        except Exception as exc:
            logger.debug("promoter chain unavailable for %s: %s", cin, exc)
            return {}

    async def _enforcement_payload(self, cin: str | None) -> list[dict[str, Any]]:
        if not cin:
            return []
        try:
            rows = await self._graph.get_enforcement_actions(cin)
            return rows or []
        except Exception as exc:
            logger.debug("enforcement payload unavailable for %s: %s", cin, exc)
            return []

    def _extract_insiders(self, *, network: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
        directors: list[dict[str, Any]] = []
        for node in (network or {}).get("nodes") or []:
            if str(node.get("label") or "").lower() != "person":
                continue
            directors.append(
                {
                    "id": node.get("id"),
                    "name": node.get("name"),
                    "degree": node.get("degree"),
                }
            )

        insider_facts: list[dict[str, Any]] = []
        for section in (provenance or {}).get("sections") or []:
            label = str(section.get("label") or "").lower()
            if "director" not in label and "insider" not in label:
                continue
            for fact in section.get("facts") or []:
                insider_facts.append(
                    {
                        "label": section.get("label"),
                        "value": fact.get("value"),
                        "as_of": fact.get("as_of"),
                        "confidence": fact.get("confidence"),
                    }
                )

        return {
            "directors": directors[:40],
            "facts": insider_facts[:50],
            "counts": {
                "directors": len(directors),
                "insider_facts": len(insider_facts),
            },
        }

    def _build_fundamentals(
        self,
        *,
        identity: _ResolvedIdentity,
        india_snap: Any,
        yahoo_quote: Any,
        shareholding: dict[str, Any] | None,
        provenance: dict[str, Any] | None,
        promoter_chain: dict[str, Any] | None,
        delivery_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        yahoo_metrics = dict((yahoo_quote.financial_metrics if yahoo_quote else {}) or {})

        profile_text = (yahoo_quote.business_summary if yahoo_quote else None) or (getattr(india_snap, "business_summary", "") if india_snap else "")
        profile_summary = _profile_from_summary(profile_text)

        provenance_sections = (provenance or {}).get("sections") or []
        for section in provenance_sections:
            label = str(section.get("label") or "").lower()
            values = [str((fact or {}).get("value") or "").strip() for fact in section.get("facts") or []]
            values = [v for v in values if v]
            if not values:
                continue
            if "mission" in label and not profile_summary.get("mission"):
                profile_summary["mission"] = values[0]
            elif "vision" in label and not profile_summary.get("vision"):
                profile_summary["vision"] = values[0]
            elif any(key in label for key in ("product", "service", "segment")):
                profile_summary["products_services"] = list(
                    dict.fromkeys((profile_summary.get("products_services") or []) + values)
                )[:6]
            elif any(key in label for key in ("client", "customer")):
                profile_summary["clients"] = list(
                    dict.fromkeys((profile_summary.get("clients") or []) + values)
                )[:6]

        if india_snap is not None:
            profile_summary["overview"] = profile_summary.get("overview") or f"{india_snap.company_name} operates in {india_snap.sector or india_snap.industry or 'its sector'}."

        promoter_holding = safe_float(
            (india_snap.promoter_holding if india_snap else None)
            or ((shareholding or {}).get("promoter"))
        )
        promoter_pledge = safe_float(india_snap.promoter_pledge_pct if india_snap else None)

        if promoter_pledge is None:
            chain_rows = (promoter_chain or {}).get("promoter_chain") or []
            if chain_rows:
                weighted = 0.0
                total = 0.0
                for row in chain_rows:
                    hold = safe_float(row.get("holding_pct")) or 0.0
                    pledge = safe_float(row.get("pledge_pct_of_holding")) or 0.0
                    total += hold
                    weighted += hold * (pledge / 100.0)
                if total > 0:
                    promoter_pledge = (weighted / total) * 100.0

        annual_revenue = list((yahoo_quote.annual_revenue if yahoo_quote else []) or [])
        annual_revenue_dates = list((yahoo_quote.annual_revenue_dates if yahoo_quote else []) or [])
        annual_income = list((yahoo_quote.annual_net_income if yahoo_quote else []) or [])
        annual_income_dates = list((yahoo_quote.annual_net_income_dates if yahoo_quote else []) or [])

        revenue_growth_pct = _calc_growth_pct(annual_revenue)
        net_income_growth_pct = _calc_growth_pct(annual_income)

        market_cap_inr = safe_float(((india_snap.market_cap_cr if india_snap else None) or 0.0) * _MONEY_TO_CRORE) or safe_float(yahoo_metrics.get("market_cap"))
        market_cap_cr = safe_float(india_snap.market_cap_cr if india_snap else None)
        if market_cap_cr is None and market_cap_inr is not None:
            market_cap_cr = market_cap_inr / _MONEY_TO_CRORE

        total_revenue = safe_float(yahoo_metrics.get("total_revenue"))
        net_income_latest = safe_float(annual_income[-1] if annual_income else None)
        pe_ratio = safe_float((india_snap.pe_ratio if india_snap else None) or yahoo_metrics.get("trailing_pe"))
        pb_ratio = safe_float((india_snap.pb_ratio if india_snap else None) or yahoo_metrics.get("price_to_book"))
        roe_value = _normalize_numeric_metric("roe", (india_snap.roe if india_snap else None) or yahoo_metrics.get("return_on_equity"))
        roce_value = _normalize_numeric_metric("roce", (india_snap.roce if india_snap else None))
        debt_to_equity_value = _normalize_numeric_metric("debt_to_equity", (india_snap.debt_to_equity if india_snap else None) or yahoo_metrics.get("debt_to_equity"))
        dividend_yield_value = _normalize_numeric_metric("dividend_yield", (india_snap.dividend_yield if india_snap else None) or yahoo_metrics.get("dividend_yield"))

        revenue_growth_norm = _normalize_numeric_metric("revenue_growth_pct", revenue_growth_pct)
        net_income_growth_norm = _normalize_numeric_metric("net_income_growth_pct", net_income_growth_pct)
        promoter_holding_norm = _normalize_numeric_metric("promoter_holding_pct", promoter_holding)
        promoter_pledge_norm = _normalize_numeric_metric("promoter_pledge_pct", promoter_pledge)
        fii_holding_norm = _normalize_numeric_metric("fii_holding_pct", (india_snap.fii_holding if india_snap else None) or ((shareholding or {}).get("fii")))
        dii_holding_norm = _normalize_numeric_metric("dii_holding_pct", (india_snap.dii_holding if india_snap else None) or ((shareholding or {}).get("dii")))
        public_holding_norm = _normalize_numeric_metric("public_holding_pct", (india_snap.public_holding if india_snap else None) or ((shareholding or {}).get("public")))

        earnings_yield_pct = (100.0 / pe_ratio) if pe_ratio and pe_ratio > 0 else None
        price_to_sales = (market_cap_inr / total_revenue) if (market_cap_inr is not None and total_revenue and total_revenue > 0) else None
        fcf_value = safe_float(yahoo_metrics.get("free_cashflow"))
        fcf_yield_pct = ((fcf_value / market_cap_inr) * 100.0) if (fcf_value is not None and market_cap_inr and market_cap_inr > 0) else None
        net_margin_pct = ((net_income_latest / total_revenue) * 100.0) if (net_income_latest is not None and total_revenue and total_revenue > 0) else _normalize_percent(yahoo_metrics.get("profit_margins"), decimal_hint=True)
        gross_margin_pct = _normalize_percent(yahoo_metrics.get("gross_margins"), decimal_hint=True)
        operating_margin_pct = _normalize_percent(yahoo_metrics.get("operating_margins"), decimal_hint=True)
        return_on_assets_pct = _normalize_percent(yahoo_metrics.get("return_on_assets"), decimal_hint=True)
        ebitda_value = safe_float(yahoo_metrics.get("ebitda"))
        enterprise_value = safe_float(yahoo_metrics.get("enterprise_value"))
        ev_to_ebitda = (enterprise_value / ebitda_value) if (enterprise_value is not None and ebitda_value and ebitda_value > 0) else None
        peg_ratio_proxy = (pe_ratio / max(revenue_growth_norm, 1.0)) if (pe_ratio is not None and revenue_growth_norm is not None and revenue_growth_norm > 0) else None
        institutional_holding_pct = None
        if fii_holding_norm is not None or dii_holding_norm is not None:
            institutional_holding_pct = (fii_holding_norm or 0.0) + (dii_holding_norm or 0.0)
        equity_multiplier = (1.0 + debt_to_equity_value) if debt_to_equity_value is not None else None
        dupont_asset_turnover_proxy = None
        if roe_value is not None and net_margin_pct and equity_multiplier and net_margin_pct != 0 and equity_multiplier != 0:
            dupont_asset_turnover_proxy = roe_value / (net_margin_pct * equity_multiplier)

        piotroski_proxy = 0
        if net_income_latest is not None and net_income_latest > 0:
            piotroski_proxy += 1
        if fcf_value is not None and fcf_value > 0:
            piotroski_proxy += 1
        if revenue_growth_norm is not None and revenue_growth_norm > 0:
            piotroski_proxy += 1
        if debt_to_equity_value is not None and debt_to_equity_value < 1:
            piotroski_proxy += 1
        if safe_float(yahoo_metrics.get("current_ratio")) is not None and safe_float(yahoo_metrics.get("current_ratio")) > 1:
            piotroski_proxy += 1
        if roe_value is not None and roe_value > 10:
            piotroski_proxy += 1
        if operating_margin_pct is not None and operating_margin_pct > 10:
            piotroski_proxy += 1
        if net_income_latest is not None and fcf_value is not None and fcf_value > net_income_latest:
            piotroski_proxy += 1
        piotroski_proxy = min(9, piotroski_proxy)

        metrics = {
            "price": safe_float((india_snap.current_price if india_snap else None) or yahoo_metrics.get("current_price")),
            "market_cap": market_cap_cr,
            "market_cap_inr": market_cap_inr,
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "roe": roe_value,
            "roce": roce_value,
            "debt_to_equity": debt_to_equity_value,
            "dividend_yield": dividend_yield_value,
            "book_value": safe_float((india_snap.book_value if india_snap else None) or yahoo_metrics.get("book_value")),
            "current_ratio": safe_float(yahoo_metrics.get("current_ratio")),
            "quick_ratio": safe_float(yahoo_metrics.get("quick_ratio")),
            "free_cashflow": fcf_value,
            "operating_cashflow": safe_float(yahoo_metrics.get("operating_cashflow")),
            "total_revenue": total_revenue,
            "net_income": net_income_latest,
            "revenue_growth_pct": revenue_growth_norm,
            "net_income_growth_pct": net_income_growth_norm,
            "promoter_holding_pct": promoter_holding_norm,
            "promoter_pledge_pct": promoter_pledge_norm,
            "fii_holding_pct": fii_holding_norm,
            "dii_holding_pct": dii_holding_norm,
            "public_holding_pct": public_holding_norm,
            "earnings_yield_pct": round(earnings_yield_pct, 3) if earnings_yield_pct is not None else None,
            "price_to_sales": round(price_to_sales, 4) if price_to_sales is not None else None,
            "fcf_yield_pct": round(fcf_yield_pct, 3) if fcf_yield_pct is not None else None,
            "net_margin_pct": round(net_margin_pct, 3) if net_margin_pct is not None else None,
            "gross_margin_pct": round(gross_margin_pct, 3) if gross_margin_pct is not None else None,
            "operating_margin_pct": round(operating_margin_pct, 3) if operating_margin_pct is not None else None,
            "return_on_assets_pct": round(return_on_assets_pct, 3) if return_on_assets_pct is not None else None,
            "ev_to_ebitda": round(ev_to_ebitda, 4) if ev_to_ebitda is not None else None,
            "peg_ratio_proxy": round(peg_ratio_proxy, 4) if peg_ratio_proxy is not None else None,
            "institutional_holding_pct": round(institutional_holding_pct, 3) if institutional_holding_pct is not None else None,
            "beta": safe_float(yahoo_metrics.get("beta")),
            "target_mean_price": safe_float(yahoo_metrics.get("target_mean_price")),
            "piotroski_f_score_proxy": piotroski_proxy,
            "dupont_net_margin_pct": round(net_margin_pct, 3) if net_margin_pct is not None else None,
            "dupont_equity_multiplier": round(equity_multiplier, 3) if equity_multiplier is not None else None,
            "dupont_asset_turnover_proxy": round(dupont_asset_turnover_proxy, 4) if dupont_asset_turnover_proxy is not None else None,
        }

        quote_source_name = (india_snap.source if india_snap else None) or "Yahoo Finance"

        cards = [
            _metric("P/E", metrics.get("pe_ratio"), source=quote_source_name),
            _metric("P/B", metrics.get("pb_ratio"), source=quote_source_name),
            _metric("ROE", metrics.get("roe"), unit="%", precision=1, source=quote_source_name),
            _metric("ROCE", metrics.get("roce"), unit="%", precision=1, source=quote_source_name),
            _metric("Debt/Equity", metrics.get("debt_to_equity"), source=quote_source_name),
            _metric("Current Ratio", metrics.get("current_ratio"), source="Yahoo Finance"),
            _metric("Quick Ratio", metrics.get("quick_ratio"), source="Yahoo Finance"),
            _metric("Dividend Yield", metrics.get("dividend_yield"), unit="%", precision=2, source=quote_source_name),
            _metric("Earnings Yield", metrics.get("earnings_yield_pct"), unit="%", precision=2, source="Derived"),
            _metric("FCF Yield", metrics.get("fcf_yield_pct"), unit="%", precision=2, source="Derived"),
            _metric("Price/Sales", metrics.get("price_to_sales"), precision=3, source="Derived"),
            _metric("Revenue Growth", metrics.get("revenue_growth_pct"), unit="%", precision=2, source="Yahoo annual"),
            _metric("Net Income Growth", metrics.get("net_income_growth_pct"), unit="%", precision=2, source="Yahoo annual"),
            _metric("Promoter Holding", metrics.get("promoter_holding_pct"), unit="%", precision=2, source="NSE shareholding"),
            _metric("Promoter Pledge", metrics.get("promoter_pledge_pct"), unit="%", precision=2, source="Screener/IKG"),
        ]

        annual_reports = list(getattr(india_snap, "annual_reports", []) or []) if india_snap is not None else []
        latest_report = annual_reports[0] if annual_reports else {}
        annual_report_depth = {
            "status": "ok" if annual_reports else "unavailable",
            "count": len(annual_reports),
            "latest_year": latest_report.get("year"),
            "latest_url": latest_report.get("url"),
            "source": "Screener public annual-report links",
            "items": annual_reports[:8],
        }
        auditor_depth = {
            "status": "annual_report_available" if annual_reports else "requires_annual_report_text",
            "source": "public annual reports / exchange filings",
            "source_url": latest_report.get("url") if annual_reports else None,
            "reason": "latest annual report linked; PDF text audit is deferred from the snapshot path" if annual_reports else "annual report text not available in current public snapshot",
        }
        delivery_depth = dict(delivery_data or {}) if isinstance(delivery_data, dict) else {"status": "unavailable"}
        delivery_depth.setdefault("source", "NSE public archives")

        company_facts = _company_facts(
            identity=identity,
            india_snap=india_snap,
            yahoo_quote=yahoo_quote,
            metrics=metrics,
        )

        return {
            "profile": {
                "company_name": identity.company_name or (india_snap.company_name if india_snap else None) or (yahoo_quote.name if yahoo_quote else None) or identity.symbol,
                "symbol": identity.symbol,
                "cin": identity.cin,
                "isin": identity.isin or (india_snap.isin if india_snap else None),
                "sector": identity.sector or (india_snap.sector if india_snap else None) or (india_snap.industry if india_snap else None),
                "industry": (india_snap.industry if india_snap else None) or (getattr(yahoo_quote, "company_info", {}) or {}).get("industry"),
                "facts": company_facts,
                **profile_summary,
            },
            "metrics": metrics,
            "cards": cards,
            "public_data_depth": {
                "segments": getattr(india_snap, "segment_data", {}) if india_snap is not None else {"status": "unavailable"},
                "related_party_transactions": getattr(india_snap, "related_party_data", {}) if india_snap is not None else {"status": "unavailable"},
                "annual_reports": annual_report_depth,
                "auditor_remarks": auditor_depth,
                "delivery_pct": delivery_depth,
                "corporate_actions": {"status": "pending_exchange_classification", "source": "NSE/BSE announcements", "count": 0, "items": []},
                "insider_trades": {"status": "pending_exchange_classification", "source": "NSE/BSE announcements", "count": 0, "items": []},
            },
            "financial_trends": {
                "annual_revenue": {
                    "dates": annual_revenue_dates,
                    "values": annual_revenue,
                },
                "annual_net_income": {
                    "dates": annual_income_dates,
                    "values": annual_income,
                },
            },
            "sources": {
                "snapshot": india_snap.source if india_snap else None,
                "snapshot_url": india_snap.source_url if india_snap else None,
                "yahoo_url": yahoo_quote.source_url if yahoo_quote else None,
                "shareholding_as_of": (shareholding or {}).get("as_of"),
                "shareholding": "NSE shareholding" if shareholding else ("Screener shareholding table" if any(v is not None for v in (promoter_holding_norm, fii_holding_norm, dii_holding_norm, public_holding_norm)) else None),
                "quote_source": quote_source_name,
            },
        }

    def _freshness(
        self,
        *,
        news: list[dict[str, Any]],
        corporate: list[dict[str, Any]],
        technicals: dict[str, Any],
        quote: dict[str, Any] | None = None,
        governance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def _age_hours(dt: datetime | None) -> float | None:
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return round(max(0.0, (_now_utc() - dt).total_seconds() / 3600.0), 2)

        def _state_by_age(age_hours: float | None, *, live_h: float, stale_h: float) -> str:
            if age_hours is None:
                return "unavailable"
            if age_hours <= live_h:
                return "live"
            if age_hours <= stale_h:
                return "stale"
            return "aging"

        news_latest = None
        for row in news:
            parsed = parse_published_at({"published": str(row.get("published") or "")})
            if parsed and (news_latest is None or parsed > news_latest):
                news_latest = parsed

        corp_latest = None
        for row in corporate:
            parsed = parse_published_at({"published": str(row.get("published") or "")})
            if parsed and (corp_latest is None or parsed > corp_latest):
                corp_latest = parsed

        technical_as_of = technicals.get("as_of")
        tech_dt = parse_published_at({"published": str(technical_as_of)}) if technical_as_of else None

        history_age = _age_hours(tech_dt)
        news_age = _age_hours(news_latest)
        corporate_age = _age_hours(corp_latest)

        quote_price = safe_float((quote or {}).get("price"))
        quote_source = str((quote or {}).get("source") or "")
        quote_status = "live" if quote_price is not None else "unavailable"
        if quote_status == "live" and quote_source.lower().strip() in {"", "unavailable"}:
            quote_status = "stale"

        governance_status = str((governance or {}).get("status") or "").lower().strip()
        if governance_status in {"", "ok"}:
            governance_section_state = "available" if governance else "unavailable"
        elif governance_status in {"unavailable", "error", "timeout"}:
            governance_section_state = "unavailable"
        else:
            governance_section_state = governance_status

        return {
            "generated_at": _iso_now(),
            "history_as_of": technical_as_of,
            "latest_news_at": news_latest.isoformat() if news_latest else None,
            "latest_corporate_at": corp_latest.isoformat() if corp_latest else None,
            "age_hours": {
                "history": history_age,
                "news": news_age,
                "corporate": corporate_age,
            },
            "quote_age_seconds": 0.0 if quote_price is not None else None,
            "quote_target_seconds": _QUOTE_TARGET_FRESHNESS_S,
            "sections": {
                "quote": {
                    "status": quote_status,
                    "age_seconds": 0.0 if quote_price is not None else None,
                    "target_seconds": _QUOTE_TARGET_FRESHNESS_S,
                    "source": quote_source or "Unavailable",
                },
                "technicals": {
                    "status": _state_by_age(history_age, live_h=24.0, stale_h=96.0),
                    "age_hours": history_age,
                },
                "governance": {
                    "status": governance_section_state,
                    "age_hours": None,
                },
                "news": {
                    "status": _state_by_age(news_age, live_h=24.0, stale_h=72.0),
                    "age_hours": news_age,
                },
                "corporate": {
                    "status": _state_by_age(corporate_age, live_h=72.0, stale_h=168.0),
                    "age_hours": corporate_age,
                },
            },
        }

    def _peer_symbol_hints(self, symbol: str, sector: str | None, *, limit: int = 4) -> list[str]:
        clean_symbol = _clean_symbol(symbol)
        seen: set[str] = {clean_symbol} if clean_symbol else set()
        peers: list[str] = []

        def _push(candidate: str) -> None:
            clean = _clean_symbol(candidate)
            if clean and clean not in seen and len(peers) < limit:
                seen.add(clean)
                peers.append(clean)

        for candidate in _PEER_HINTS_BY_SYMBOL.get(clean_symbol, []):
            _push(candidate)

        sector_l = str(sector or "").lower()
        for key, candidates in _PEER_HINTS_BY_SECTOR.items():
            if key not in sector_l:
                continue
            for candidate in candidates:
                _push(candidate)
            if len(peers) >= limit:
                break

        return peers[:limit]

    async def _peer_comparison(self, *, identity: _ResolvedIdentity, sector: str | None, limit: int = 4) -> dict[str, Any]:
        symbols = self._peer_symbol_hints(identity.symbol, sector, limit=limit)
        if not symbols:
            return {
                "status": "unavailable",
                "reason": "peer_seed_unavailable",
                "source": "curated_peer_seed",
                "items": [],
            }

        async def _fetch_peer(symbol: str) -> dict[str, Any] | None:
            snap = await self._safe_async(
                fetch_india_snapshot(symbol),
                timeout_s=2.8,
                default=None,
                label=f"peer_snapshot:{symbol}",
            )
            if snap is None:
                return None
            return {
                "symbol": symbol,
                "company_name": getattr(snap, "company_name", "") or symbol,
                "sector": getattr(snap, "sector", "") or getattr(snap, "industry", ""),
                "price": safe_float(getattr(snap, "current_price", None)),
                "market_cap_cr": safe_float(getattr(snap, "market_cap_cr", None)),
                "pe_ratio": safe_float(getattr(snap, "pe_ratio", None)),
                "pb_ratio": safe_float(getattr(snap, "pb_ratio", None)),
                "roe": _normalize_numeric_metric("roe", getattr(snap, "roe", None)),
                "roce": _normalize_numeric_metric("roce", getattr(snap, "roce", None)),
                "debt_to_equity": _normalize_numeric_metric("debt_to_equity", getattr(snap, "debt_to_equity", None)),
                "promoter_holding_pct": _normalize_numeric_metric("promoter_holding_pct", getattr(snap, "promoter_holding", None)),
                "source": getattr(snap, "source", "") or "market_data",
                "source_url": getattr(snap, "source_url", "") or "",
            }

        tasks = [asyncio.create_task(_fetch_peer(symbol)) for symbol in symbols]
        done, pending = await asyncio.wait(tasks, timeout=2.8)
        for task in pending:
            task.cancel()
            task.add_done_callback(lambda done_task: done_task.exception() if not done_task.cancelled() else None)

        rows: list[Any] = []
        for task in done:
            try:
                rows.append(task.result())
            except Exception as exc:
                logger.debug("peer comparison row failed for %s: %s", identity.symbol, exc)
        items = [row for row in rows if isinstance(row, dict)]

        numeric_fields = ("pe_ratio", "pb_ratio", "roe", "roce", "debt_to_equity")
        medians: dict[str, float] = {}
        for field in numeric_fields:
            vals = sorted(safe_float(item.get(field)) for item in items if safe_float(item.get(field)) is not None)
            if not vals:
                continue
            mid = len(vals) // 2
            medians[field] = round(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0, 4)

        return {
            "status": "available" if items else "unavailable",
            "source": "curated_peer_seed + public market snapshots",
            "requested_symbols": symbols,
            "items": items,
            "median": medians,
        }

    async def _candidate_universe(
        self,
        keywords: list[str],
        *,
        universe: list[str] | None,
        limit: int,
    ) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []

        def _push(symbol: str) -> None:
            clean = _clean_symbol(symbol)
            if clean and clean not in seen and len(out) < limit:
                seen.add(clean)
                out.append(clean)

        if universe:
            for sym in universe:
                _push(sym)
            return out[:limit]

        for keyword in keywords[:6]:
            if len(out) >= limit:
                break
            try:
                hits = await asyncio.to_thread(self._resolver.resolve_by_name, keyword, 18)
            except Exception as exc:
                logger.debug("candidate universe lookup failed for keyword %s: %s", keyword, exc)
                hits = []
            for hit in hits:
                _push(hit.nse_symbol or hit.bse_scrip_code or "")
                if len(out) >= limit:
                    break

        # Add symbol-shaped keywords directly so user-entered queries are never
        # constrained to only the baked-in default list.
        for keyword in keywords:
            if len(out) >= limit:
                break
            if len(keyword) <= 12 and keyword.replace("-", "").replace("&", "").isalnum():
                _push(keyword)

        for sym in _DEFAULT_UNIVERSE:
            if len(out) >= limit:
                break
            _push(sym)

        return out[:limit]

    async def _screen_symbol(
        self,
        symbol: str,
        parsed_filter: Any,
        *,
        resolve_identity: bool = True,
        yahoo_timeout_s: float = 18.0,
        include_yahoo: bool = True,
    ) -> dict[str, Any] | None:
        if resolve_identity:
            identity = await self._resolve_identity(symbol)
        else:
            clean_symbol = _clean_symbol(symbol)
            if not clean_symbol:
                return None
            identity = _ResolvedIdentity(
                query=symbol,
                symbol=clean_symbol,
                company_name=clean_symbol,
                source="query_universe",
            )
        if not identity.symbol:
            return None

        india_task = asyncio.create_task(fetch_india_snapshot(identity.symbol))
        yahoo_task = asyncio.create_task(self._fetch_yahoo_best(identity.symbol, timeout_s=yahoo_timeout_s)) if include_yahoo else None

        india: Any = None
        yahoo: Any = None
        if yahoo_task is None:
            try:
                india = await india_task
            except Exception as exc:
                logger.debug("snapshot fetch failed for %s: %s", identity.symbol, exc)
                india = None
        else:
            india_result, yahoo_result = await asyncio.gather(india_task, yahoo_task, return_exceptions=True)
            if isinstance(india_result, Exception):
                logger.debug("snapshot fetch failed for %s: %s", identity.symbol, india_result)
                india = None
            else:
                india = india_result
            if isinstance(yahoo_result, Exception):
                logger.debug("yahoo fetch failed for %s: %s", identity.symbol, yahoo_result)
                yahoo = None
            else:
                yahoo = yahoo_result

        if india is None and yahoo is None:
            return None

        dates: list[str] = []
        prices: list[float] = []
        if yahoo is not None and yahoo.series_dates and yahoo.series_closes:
            dates, prices = _filter_history_period(
                list(yahoo.series_dates),
                list(yahoo.series_closes),
                "1Y",
            )
        elif india is not None and getattr(india, "series_dates", None) and getattr(india, "series_closes", None):
            dates, prices = _filter_history_period(
                list(getattr(india, "series_dates", []) or []),
                list(getattr(india, "series_closes", []) or []),
                "1Y",
            )
        technicals = compute_technicals(dates, prices)

        metrics = {
            "roce": _normalize_numeric_metric("roce", india.roce if india else None),
            "roe": _normalize_numeric_metric(
                "roe",
                (india.roe if india else None) or ((yahoo.financial_metrics or {}).get("return_on_equity") if yahoo else None),
            ),
            "pe_ratio": safe_float((india.pe_ratio if india else None) or ((yahoo.financial_metrics or {}).get("trailing_pe") if yahoo else None)),
            "debt_to_equity": _normalize_numeric_metric(
                "debt_to_equity",
                (india.debt_to_equity if india else None) or ((yahoo.financial_metrics or {}).get("debt_to_equity") if yahoo else None),
            ),
            "promoter_holding_pct": _normalize_numeric_metric("promoter_holding_pct", india.promoter_holding if india else None),
            "promoter_pledge_pct": _normalize_numeric_metric("promoter_pledge_pct", india.promoter_pledge_pct if india else None),
            "revenue_growth_pct": _normalize_numeric_metric("revenue_growth_pct", _calc_growth_pct(list((yahoo.annual_revenue if yahoo else []) or []))),
            "free_cashflow": safe_float((yahoo.financial_metrics or {}).get("free_cashflow") if yahoo else None),
            "net_income": safe_float((list((yahoo.annual_net_income if yahoo else []) or []) or [None])[-1]),
        }

        last_price = safe_float((india.current_price if india else None) or (yahoo.price if yahoo else None))
        passed, reasons = check_filter_match(
            parsed_filter,
            price=last_price,
            metrics=metrics,
            technicals=technicals,
        )
        if not passed:
            return None

        snapshot = {
            "fundamentals": {"metrics": metrics},
            "technicals": technicals,
            "governance": {},
            "ikg": {"coverage": {}},
            "risk_signals": {},
        }
        score = compute_scores(snapshot)
        summary = summarize_positive_negative(snapshot)

        return {
            "symbol": identity.symbol,
            "company_name": (india.company_name if india else None) or (yahoo.name if yahoo else None) or identity.symbol,
            "price": last_price,
            "metrics": metrics,
            "technicals": {
                "trend_bias": technicals.get("trend_bias"),
                "rsi14": technicals.get("rsi14"),
                "above_200dma": technicals.get("above_200dma"),
                "return_1m_pct": technicals.get("return_1m_pct"),
            },
            "score": score,
            "positives": summary.get("positives"),
            "negatives": summary.get("negatives"),
            "match_reasons": reasons,
            "sources": {
                "snapshot": india.source if india else None,
                "history": yahoo.source_url if yahoo else None,
            },
        }


_SERVICE: ScreenerService | None = None


def get_screener_service() -> ScreenerService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ScreenerService()
    return _SERVICE






