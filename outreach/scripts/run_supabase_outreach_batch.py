from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from send_outreach_batch import (
    append_sent_log,
    build_message,
    choose_sender,
    load_json,
    load_template,
    resolve_setting,
    send_acs_email,
    senders_from_config,
    validate_config,
    validate_lead,
)


INDIA_STATES = {
    "ANDHRA PRADESH",
    "ARUNACHAL PRADESH",
    "ASSAM",
    "BIHAR",
    "CHANDIGARH",
    "CHHATTISGARH",
    "DADRA AND NAGAR HAVELI",
    "DAMAN AND DIU",
    "DELHI",
    "GOA",
    "GUJARAT",
    "HARYANA",
    "HIMACHAL PRADESH",
    "JAMMU AND KASHMIR",
    "JHARKHAND",
    "KARNATAKA",
    "KERALA",
    "LADAKH",
    "LAKSHADWEEP",
    "MADHYA PRADESH",
    "MAHARASHTRA",
    "MANIPUR",
    "MEGHALAYA",
    "MIZORAM",
    "NAGALAND",
    "NEW DELHI",
    "ODISHA",
    "PUDUCHERRY",
    "PUNJAB",
    "RAJASTHAN",
    "SIKKIM",
    "TAMIL NADU",
    "TELANGANA",
    "TRIPURA",
    "UTTAR PRADESH",
    "UTTARAKHAND",
    "WEST BENGAL",
}

SOURCE_PRIORITY = {
    "sebi-ra": 0,
    "sebi-ria": 1,
    "sebi-merchant-banker": 2,
    "sebi-portfolio-manager": 3,
    "sebi-aif": 4,
    "sebi-broker-equity": 5,
    "sebi-broker-debt": 6,
    "sebi-broker-interest-deriv": 7,
    "bse": 8,
}

ALLOWED_SOURCES = set(SOURCE_PRIORITY)
ROLE_KEYWORDS = (
    "research",
    "analyst",
    "advisor",
    "adviser",
    "investment",
    "merchant",
    "portfolio",
    "wealth",
    "capital",
    "security",
    "broker",
    "broking",
    "asset",
    "fund",
    "market",
    "equity",
    "finance",
)
INDIA_DOMAIN_SUFFIXES = (
    ".in",
    ".co.in",
    ".org.in",
    ".ac.in",
    ".gov.in",
    ".nic.in",
)
SHARED_TOKENS = {
    "accounts",
    "admin",
    "billing",
    "career",
    "careers",
    "contact",
    "enquiry",
    "enquiries",
    "feedback",
    "grievance",
    "hello",
    "help",
    "hr",
    "info",
    "investorrelations",
    "legal",
    "mail",
    "marketing",
    "noreply",
    "office",
    "ops",
    "operation",
    "operations",
    "sales",
    "secretarial",
    "service",
    "support",
    "team",
}
SHARED_FRAGMENTS = (
    "compliance",
    "customercare",
    "customerservice",
    "grievance",
    "investorrelation",
    "regulatory",
    "secretarial",
)
CORP_NAME_TERMS = {
    "advisors",
    "adviser",
    "advisory",
    "broker",
    "brokers",
    "broking",
    "capital",
    "company",
    "finance",
    "finserv",
    "fund",
    "investments",
    "limited",
    "llp",
    "pvt",
    "private",
    "research",
    "securities",
    "services",
}


def _load_env_file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (Path("finagent/.env"), Path(".env")):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in values:
                values[key] = value
    return values


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _smart_title(text: str) -> str:
    cleaned = _normalized(text)
    if not cleaned:
        return ""
    if cleaned.isupper():
        return cleaned.title()
    return cleaned


def _extract_name_parts(name: str) -> tuple[str, str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z'`-]+", name or "")
    if not tokens:
        return "", ""
    first = _smart_title(tokens[0])
    last = _smart_title(tokens[-1]) if len(tokens) > 1 else ""
    return first, last


def _source_label(source: str) -> str:
    mapping = {
        "sebi-ra": "SEBI research analyst",
        "sebi-ria": "SEBI investment adviser",
        "sebi-merchant-banker": "SEBI merchant banker",
        "sebi-portfolio-manager": "SEBI portfolio manager",
        "sebi-aif": "SEBI AIF",
        "sebi-broker-equity": "SEBI broker",
        "sebi-broker-debt": "SEBI broker",
        "sebi-broker-interest-deriv": "SEBI broker",
        "bse": "BSE member directory",
    }
    return mapping.get((source or "").strip().lower(), "Indian markets directory")


def _build_source_url(contact: dict[str, Any]) -> str:
    website = _normalized(str(contact.get("website") or ""))
    if website:
        if website.startswith(("http://", "https://")):
            return website
        return "https://" + website.lstrip("/")
    linkedin = _normalized(str(contact.get("linkedin_url") or ""))
    if linkedin:
        return linkedin
    source = (contact.get("primary_source") or "").strip().lower()
    if source == "bse":
        return "https://www.bseindia.com/"
    if source.startswith("sebi-"):
        return "https://www.sebi.gov.in/"
    return ""


def _is_high_confidence(contact: dict[str, Any], min_confidence: float) -> bool:
    email = _normalized(str(contact.get("email") or ""))
    if not email or contact.get("opted_out"):
        return False
    status = str(contact.get("email_status") or "").strip().lower()
    confidence = float(contact.get("email_confidence") or 0.0)
    return status.startswith("verified") or status in {"valid", "deliverable"} or confidence >= min_confidence


def _is_india_contact(contact: dict[str, Any]) -> bool:
    source = str(contact.get("primary_source") or "").strip().lower()
    if source in ALLOWED_SOURCES:
        return True
    state = str(contact.get("state") or "").strip().upper()
    if state in INDIA_STATES:
        return True
    address = " ".join(
        str(contact.get(field) or "").upper()
        for field in ("address", "city", "state")
    )
    if any(marker in address for marker in INDIA_STATES):
        return True
    if " INDIA" in address or address.endswith("INDIA"):
        return True
    return bool(re.search(r"\b\d{6}\b", address))


def _extract_hostname(value: str) -> str:
    text = _normalized(value).lower()
    if not text:
        return ""
    candidate = text
    if not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate.lstrip("/")
    try:
        hostname = urllib.parse.urlsplit(candidate).hostname or ""
    except ValueError:
        return ""
    return hostname.lower().removeprefix("www.")


def _is_india_contact_broad(contact: dict[str, Any]) -> bool:
    if _is_india_contact(contact):
        return True
    source = str(contact.get("primary_source") or "").strip().lower()
    email = _normalized(str(contact.get("email") or "")).lower()
    email_domain = email.split("@", 1)[1] if "@" in email else ""
    website_host = _extract_hostname(str(contact.get("website") or ""))
    linkedin_host = _extract_hostname(str(contact.get("linkedin_url") or ""))
    organisation = _normalized(str(contact.get("organisation") or "")).lower()
    candidates = [source, email_domain, website_host, linkedin_host]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.endswith(INDIA_DOMAIN_SUFFIXES):
            return True
        if "india" in candidate:
            return True
    return "india" in organisation


def _is_shared_mailbox(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    tokens = [token for token in re.split(r"[^a-z]+", local) if token]
    if any(token in SHARED_TOKENS for token in tokens):
        return True
    compact = "".join(tokens)
    return any(fragment in compact for fragment in SHARED_FRAGMENTS)


def _has_person_name(name: str) -> bool:
    tokens = [token for token in re.findall(r"[A-Za-z][A-Za-z'`-]+", name or "")]
    if len(tokens) < 2:
        return False
    return not any(token.lower() in CORP_NAME_TERMS for token in tokens)


def _is_role_fit(contact: dict[str, Any]) -> bool:
    source = str(contact.get("primary_source") or "").strip().lower()
    if source in SOURCE_PRIORITY and source != "bse":
        return True
    text = " ".join(
        str(contact.get(field) or "")
        for field in ("designation", "organisation", "sebi_reg_type", "primary_source")
    ).lower()
    return any(keyword in text for keyword in ROLE_KEYWORDS)


def _priority_key(contact: dict[str, Any]) -> tuple[Any, ...]:
    source = str(contact.get("primary_source") or "").strip().lower()
    confidence = float(contact.get("email_confidence") or 0.0)
    has_website = bool(_build_source_url(contact))
    has_state = bool(_normalized(str(contact.get("state") or "")))
    return (
        SOURCE_PRIORITY.get(source, 99),
        -confidence,
        0 if has_website else 1,
        0 if has_state else 1,
        _normalized(str(contact.get("organisation") or "")).lower(),
        _normalized(str(contact.get("email") or "")).lower(),
    )


def _stable_variant_index(contact: dict[str, Any], count: int) -> int:
    if count <= 1:
        return 0
    fingerprint = "|".join(
        _normalized(str(contact.get(field) or "")).lower()
        for field in ("email", "name", "organisation", "designation", "primary_source", "state")
    )
    if not fingerprint:
        return 0
    return sum(ord(ch) for ch in fingerprint) % count


def _is_broker_like(contact: dict[str, Any]) -> bool:
    text = " ".join(
        str(contact.get(field) or "")
        for field in ("designation", "organisation", "sebi_reg_type", "primary_source")
    ).lower()
    return any(token in text for token in ("broker", "broking", "dealer", "equity", "capital market"))


def _subject_for(contact: dict[str, Any]) -> str:
    source = str(contact.get("primary_source") or "").strip().lower()
    if source.startswith("sebi-"):
        options = [
            "Would value your take on a better Indian markets research workflow",
            "Open to a quick look at ProspektLab?",
            "Could I get your blunt feedback on ProspektLab?",
        ]
        return options[_stable_variant_index(contact, len(options))]
    if source == "bse" or _is_broker_like(contact):
        options = [
            "Could ProspektLab fit your Indian markets workflow?",
            "Open to trying ProspektLab for 10 minutes?",
            "Would value your take on a broker-side research workflow",
        ]
        return options[_stable_variant_index(contact, len(options))]
    options = [
        "Would value your take on ProspektLab",
        "Open to a quick look at ProspektLab?",
        "Could I get your blunt feedback on ProspektLab?",
    ]
    return options[_stable_variant_index(contact, len(options))]


def _hook_for(contact: dict[str, Any]) -> str:
    source = str(contact.get("primary_source") or "").strip().lower()
    organisation = _smart_title(str(contact.get("organisation") or "")) or "your firm"
    designation = _smart_title(str(contact.get("designation") or "")) or "your role"
    label = _source_label(source)
    if source == "bse" or _is_broker_like(contact):
        options = [
            (
                f"I came across {organisation} while mapping active broker and market-participant firms in India, "
                f"and your role as {designation} looked especially relevant to the product feedback we need."
            ),
            (
                f"I found {organisation} while reviewing Indian broker-side firms worth reaching out to, "
                f"and your work as {designation} felt closely aligned with the workflow we are trying to improve."
            ),
            (
                f"I was looking through active Indian broker and market-participant firms and paused at {organisation} "
                f"because people in {designation} roles usually know very quickly whether a research tool is genuinely useful."
            ),
        ]
        return options[_stable_variant_index(contact, len(options))]
    options = [
        (
            f"I came across your {label} listing while shortlisting serious Indian market professionals, "
            f"and your work as {designation} at {organisation} stood out right away."
        ),
        (
            f"I found your {label} listing while mapping people close to Indian research workflows, "
            f"and your role at {organisation} felt especially relevant to what we are building."
        ),
        (
            f"I was reviewing {label} listings and stopped at {organisation} because people in {designation} roles "
            f"tend to know very quickly whether a research product is actually helpful."
        ),
    ]
    return options[_stable_variant_index(contact, len(options))]


def _compliment_for(contact: dict[str, Any]) -> str:
    organisation = _smart_title(str(contact.get("organisation") or "")) or "your organization"
    designation = _smart_title(str(contact.get("designation") or "")) or "your work"
    state = _smart_title(str(contact.get("state") or ""))
    expertise = _normalized(str(contact.get("areas_of_expertise") or ""))
    if expertise:
        options = [
            (
                f"People working this close to {expertise.lower()} usually spot very quickly whether a tool is saving real "
                f"research time or just adding another layer, which is why your perspective would matter."
            ),
            (
                f"When someone spends their day around {expertise.lower()}, they usually see the gaps in research workflows "
                f"much faster than product teams do."
            ),
        ]
        return options[_stable_variant_index(contact, len(options))]
    if state:
        options = [
            (
                f"People in {designation} roles at {organisation} from {state} usually have a grounded view on whether "
                f"a research workflow genuinely saves time or just creates one more layer."
            ),
            (
                f"Because you are in a {designation} role at {organisation} from {state}, I felt you would have a practical "
                f"read on whether this is genuinely useful in the flow of work."
            ),
        ]
        return options[_stable_variant_index(contact, len(options))]
    options = [
        (
            f"People in {designation} roles at {organisation} usually have a fast read on whether a research tool actually "
            f"saves time or just adds another tab."
        ),
        (
            f"That is why your perspective would be valuable here: people in {designation} roles at {organisation} usually "
            f"notice the real workflow friction immediately."
        ),
    ]
    return options[_stable_variant_index(contact, len(options))]


def _platform_intro_for(contact: dict[str, Any]) -> str:
    source = str(contact.get("primary_source") or "").strip().lower()
    if source.startswith("sebi-"):
        return (
            "We are building ProspektLab as a research workspace for Indian market professionals who want filings, news, "
            "portfolio context, and market data in one place instead of across scattered tabs and notes."
        )
    if source == "bse" or _is_broker_like(contact):
        return (
            "We are building ProspektLab to make broker and investor research workflows less fragmented by keeping filings, "
            "market context, and working notes in one place."
        )
    return (
        "We are building ProspektLab as a research workspace that brings filings, news, portfolio context, and market data "
        "into one place so the work feels less scattered."
    )


def _cta_for(contact: dict[str, Any]) -> str:
    options = [
        (
            "If you are open to it, I would love to get your honest reaction after a quick 10-minute look. Even a short "
            "reply on what feels useful, missing, or unnecessary would help us shape it."
        ),
        (
            "If this sounds relevant, would you be open to trying it once and replying with the bluntest feedback you have? "
            "That kind of signal is exactly what we need right now."
        ),
        (
            "If you have a few minutes this week, I would really value a quick spin and an honest note on whether this would "
            "ever deserve a place in your actual workflow."
        ),
    ]
    return options[_stable_variant_index(contact, len(options))]


def _contact_to_lead(contact: dict[str, Any], index: int, sender_keys: list[str]) -> dict[str, str]:
    first_name, _ = _extract_name_parts(str(contact.get("name") or ""))
    return {
        "email": _normalized(str(contact.get("email") or "")).lower(),
        "first_name": first_name or "there",
        "company": _smart_title(str(contact.get("organisation") or "")),
        "role": _smart_title(str(contact.get("designation") or "")),
        "hook": _hook_for(contact),
        "compliment": _compliment_for(contact),
        "subject": _subject_for(contact),
        "platform_intro": _platform_intro_for(contact),
        "cta_line": _cta_for(contact),
        "sender": sender_keys[index % len(sender_keys)] if sender_keys else "",
        "source_url": _build_source_url(contact),
    }


def _query_string(params: dict[str, Any] | None) -> str:
    if not params:
        return ""
    filtered = {key: value for key, value in params.items() if value is not None and value != ""}
    if not filtered:
        return ""
    return "?" + urllib.parse.urlencode(filtered, doseq=True)


def _supabase_request(
    *,
    base_url: str,
    api_key: str,
    table: str,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    payload: Any | None = None,
    prefer: str | None = None,
    range_header: tuple[int, int] | None = None,
) -> tuple[Any, dict[str, str]]:
    url = f"{base_url.rstrip('/')}/rest/v1/{table}{_query_string(params)}"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    if range_header is not None:
        headers["Range-Unit"] = "items"
        headers["Range"] = f"{range_header[0]}-{range_header[1]}"

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as response:
        body = response.read().decode("utf-8")
        parsed: Any = None
        if body:
            parsed = json.loads(body)
        return parsed, dict(response.headers.items())


def _paginate_table(
    *,
    base_url: str,
    api_key: str,
    table: str,
    params: dict[str, Any],
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        data, _headers = _supabase_request(
            base_url=base_url,
            api_key=api_key,
            table=table,
            params=params,
            range_header=(start, start + page_size - 1),
        )
        chunk = data if isinstance(data, list) else []
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        start += page_size
    return rows


def _get_supabase_credentials(config: dict[str, Any]) -> tuple[str, str]:
    sync_config = config.get("suppression_sync", {})
    env_values = _load_env_file_values()
    base_url = (
        str(sync_config.get("supabase_url", "")).strip()
        or resolve_setting(config, env_values, "OUTREACH_SUPABASE_URL", "SUPABASE_URL")
    )
    api_key = (
        str(sync_config.get("supabase_key", "")).strip()
        or resolve_setting(config, env_values, "OUTREACH_SUPABASE_KEY", "SUPABASE_KEY")
    )
    if not base_url or not api_key:
        raise ValueError("Outreach Supabase credentials are not configured.")
    return base_url, api_key


def _fetch_contacts(base_url: str, api_key: str) -> list[dict[str, Any]]:
    return _paginate_table(
        base_url=base_url,
        api_key=api_key,
        table="contacts",
        params={
            "select": (
                "id,name,email,email_status,email_confidence,email_normalized,linkedin_url,"
                "website,designation,organisation,address,city,state,validity,areas_of_expertise,"
                "sebi_reg_type,priority_score,extraction_confidence,opted_out,data_basis,primary_source"
            ),
            "order": "created_at.asc",
        },
    )


def _fetch_existing_sent(base_url: str, api_key: str, owner_email: str) -> set[str]:
    rows = _paginate_table(
        base_url=base_url,
        api_key=api_key,
        table="outreach_messages",
        params={
            "owner_email": f"eq.{owner_email}",
            "select": "to_email,status",
        },
    )
    sent_statuses = {"queued", "sent", "delivered", "opened", "clicked"}
    return {
        _normalized(str(row.get("to_email") or "")).lower()
        for row in rows
        if str(row.get("status") or "").strip().lower() in sent_statuses
    }


def _fetch_suppressed(base_url: str, api_key: str, owner_email: str) -> set[str]:
    suppressed = set()
    for table, params in (
        ("outreach_unsubscribes", {"select": "email"}),
        ("outreach_suppressions", {"owner_email": f"eq.{owner_email}", "select": "email"}),
    ):
        rows = _paginate_table(
            base_url=base_url,
            api_key=api_key,
            table=table,
            params=params,
        )
        suppressed.update(
            _normalized(str(row.get("email") or "")).lower()
            for row in rows
            if _normalized(str(row.get("email") or ""))
        )
    return suppressed


def _get_or_create_campaign(
    *,
    base_url: str,
    api_key: str,
    owner_email: str,
    campaign_name: str,
    default_sender: dict[str, Any],
) -> int:
    data, _headers = _supabase_request(
        base_url=base_url,
        api_key=api_key,
        table="outreach_campaigns",
        params={
            "owner_email": f"eq.{owner_email}",
            "name": f"eq.{campaign_name}",
            "select": "id",
            "limit": 1,
        },
    )
    if isinstance(data, list) and data:
        return int(data[0]["id"])

    payload = {
        "owner_email": owner_email,
        "name": campaign_name,
        "sender_profile": default_sender["key"],
        "sender_address": default_sender["email"],
        "reply_to_email": default_sender["reply_to"],
        "status": "running",
        "audience_query": "india_finance_personal_v1",
        "subject_template": "dynamic",
        "body_template": "prospektlab_feedback",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }
    created, _headers = _supabase_request(
        base_url=base_url,
        api_key=api_key,
        table="outreach_campaigns",
        method="POST",
        payload=payload,
        prefer="return=representation",
    )
    if not isinstance(created, list) or not created:
        raise ValueError("Failed to create outreach campaign.")
    return int(created[0]["id"])


def _upsert_outreach_lead(
    *,
    base_url: str,
    api_key: str,
    owner_email: str,
    contact: dict[str, Any],
    sender_key: str,
) -> int:
    first_name, last_name = _extract_name_parts(str(contact.get("name") or ""))
    personalization = {
        "primary_source": _normalized(str(contact.get("primary_source") or "")),
        "city": _normalized(str(contact.get("city") or "")),
        "state": _normalized(str(contact.get("state") or "")),
        "designation": _normalized(str(contact.get("designation") or "")),
        "organisation": _normalized(str(contact.get("organisation") or "")),
        "source_url": _build_source_url(contact),
    }
    payload = {
        "owner_email": owner_email,
        "email": _normalized(str(contact.get("email") or "")).lower(),
        "first_name": first_name,
        "last_name": last_name,
        "company_name": _smart_title(str(contact.get("organisation") or "")),
        "title": _smart_title(str(contact.get("designation") or "")),
        "linkedin_url": _normalized(str(contact.get("linkedin_url") or "")),
        "website_url": _normalized(str(contact.get("website") or "")),
        "personalization_json": json.dumps(personalization, ensure_ascii=False),
        "status": "staged",
        "assigned_profile": sender_key,
    }
    existing_rows, _headers = _supabase_request(
        base_url=base_url,
        api_key=api_key,
        table="outreach_leads",
        params={
            "owner_email": f"eq.{owner_email}",
            "email": f"eq.{payload['email']}",
            "select": "id",
            "limit": 1,
        },
    )
    if isinstance(existing_rows, list) and existing_rows:
        lead_id = int(existing_rows[0]["id"])
        _supabase_request(
            base_url=base_url,
            api_key=api_key,
            table="outreach_leads",
            method="PATCH",
            params={
                "owner_email": f"eq.{owner_email}",
                "email": f"eq.{payload['email']}",
            },
            payload=payload,
            prefer="return=minimal",
        )
        return lead_id

    rows, _headers = _supabase_request(
        base_url=base_url,
        api_key=api_key,
        table="outreach_leads",
        method="POST",
        payload=payload,
        prefer="return=representation",
    )
    if not isinstance(rows, list) or not rows:
        raise ValueError("Failed to insert outreach lead.")
    return int(rows[0]["id"])


def _update_outreach_lead_status(
    *,
    base_url: str,
    api_key: str,
    owner_email: str,
    email: str,
    sender_key: str,
    status: str,
    contacted_at: str | None,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "assigned_profile": sender_key,
    }
    if contacted_at:
        payload["last_contacted_at"] = contacted_at
    _supabase_request(
        base_url=base_url,
        api_key=api_key,
        table="outreach_leads",
        method="PATCH",
        params={
            "owner_email": f"eq.{owner_email}",
            "email": f"eq.{email}",
        },
        payload=payload,
        prefer="return=minimal",
    )


def _insert_outreach_message(
    *,
    base_url: str,
    api_key: str,
    owner_email: str,
    campaign_id: int,
    lead_id: int,
    sender_profile: str,
    sender_address: str,
    reply_to_email: str,
    to_email: str,
    subject_rendered: str,
    body_rendered: str,
    provider_message_id: str,
    status: str,
    last_error: str,
    sent_at: str | None,
) -> None:
    payload = {
        "owner_email": owner_email,
        "campaign_id": campaign_id,
        "lead_id": lead_id,
        "sender_profile": sender_profile,
        "sender_address": sender_address,
        "reply_to_email": reply_to_email,
        "to_email": to_email,
        "subject_rendered": subject_rendered,
        "body_rendered": body_rendered,
        "provider": "azure_communication_services",
        "provider_message_id": provider_message_id,
        "status": status,
        "last_error": last_error,
        "sent_at": sent_at,
    }
    _supabase_request(
        base_url=base_url,
        api_key=api_key,
        table="outreach_messages",
        method="POST",
        payload=payload,
        prefer="return=minimal",
    )


def _should_throttle_stop(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in ("429", "too many requests", "rate limit", "quota", "throttle")
    )


def _is_domain_not_linked_error(message: str) -> bool:
    lowered = message.lower()
    return "domainnotlinked" in lowered or "sender domain has not been linked" in lowered


def _eligible_contacts(
    contacts: list[dict[str, Any]],
    *,
    min_confidence: float,
    allow_shared_inboxes: bool,
    sent_emails: set[str],
    suppressed_emails: set[str],
) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for contact in contacts:
        email = _normalized(str(contact.get("email") or "")).lower()
        if not email or email in deduped or email in sent_emails or email in suppressed_emails:
            continue
        if not _is_high_confidence(contact, min_confidence):
            continue
        if not _is_india_contact(contact):
            continue
        if not _is_role_fit(contact):
            continue
        if not allow_shared_inboxes and _is_shared_mailbox(email):
            continue
        if not _has_person_name(str(contact.get("name") or "")):
            continue
        deduped[email] = contact
    return sorted(deduped.values(), key=_priority_key)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Supabase-backed India-only outreach batch.")
    parser.add_argument("--config", type=Path, default=Path("outreach/config.local.json"))
    parser.add_argument("--template", type=Path, default=Path("outreach/templates/prospektlab_feedback.md"))
    parser.add_argument("--sent-log", type=Path, default=Path("outreach/state/sent_log.csv"))
    parser.add_argument("--owner-email", default="aryan@prospektlab.com")
    parser.add_argument("--campaign-name", default="India Finance Outreach")
    parser.add_argument("--max-send", type=int, default=25)
    parser.add_argument("--delay-seconds", type=float, default=42.0)
    parser.add_argument("--min-email-confidence", type=float, default=0.85)
    parser.add_argument("--allow-shared-inboxes", action="store_true")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    config = load_json(args.config)
    senders = senders_from_config(config)
    sender_keys = list(senders)
    template_subject, template_body = load_template(args.template)
    config_issues = validate_config(config, sending=args.send, allow_managed_domain=False)
    if config_issues:
        print("Configuration is not ready for live sending:")
        for issue in config_issues:
            print(f"- {issue}")
        return 2

    base_url, api_key = _get_supabase_credentials(config)
    contacts = _fetch_contacts(base_url, api_key)
    sent_emails = _fetch_existing_sent(base_url, api_key, args.owner_email)
    suppressed_emails = _fetch_suppressed(base_url, api_key, args.owner_email)
    strict_india_contacts = sum(1 for contact in contacts if _is_india_contact(contact))
    broad_india_contacts = sum(1 for contact in contacts if _is_india_contact_broad(contact))
    eligible = _eligible_contacts(
        contacts,
        min_confidence=args.min_email_confidence,
        allow_shared_inboxes=args.allow_shared_inboxes,
        sent_emails=sent_emails,
        suppressed_emails=suppressed_emails,
    )

    print(
        f"Supabase contacts={len(contacts)} india_strict={strict_india_contacts} "
        f"india_broad={broad_india_contacts} eligible={len(eligible)} "
        f"already_sent={len(sent_emails)} suppressed={len(suppressed_emails)}"
    )
    if not eligible:
        print("No eligible India-only outreach leads remain.")
        return 0

    default_sender = {
        "key": sender_keys[0],
        "email": senders[sender_keys[0]].email,
        "reply_to": senders[sender_keys[0]].reply_to,
    }
    campaign_id = _get_or_create_campaign(
        base_url=base_url,
        api_key=api_key,
        owner_email=args.owner_email,
        campaign_name=args.campaign_name,
        default_sender=default_sender,
    )
    print(f"Campaign id={campaign_id}")

    sent_count = 0
    processed_count = 0
    consecutive_failures = 0
    skipped = 0
    hard_failure = False
    for index, contact in enumerate(eligible):
        if processed_count >= args.max_send:
            break

        lead = _contact_to_lead(contact, index, sender_keys)
        issues = validate_lead(lead)
        if issues:
            skipped += 1
            print(f"SKIP quality: {lead['email']} -> {', '.join(issues)}")
            continue

        sender = choose_sender(lead, senders, index)
        lead_id = _upsert_outreach_lead(
            base_url=base_url,
            api_key=api_key,
            owner_email=args.owner_email,
            contact=contact,
            sender_key=sender.key,
        )
        message = build_message(
            row=lead,
            sender=sender,
            config=config,
            template_subject=template_subject,
            template_body=template_body,
        )

        if not args.send:
            print("")
            print(f"DRY RUN -> {lead['email']}")
            print(f"From: {sender.name} <{sender.email}>")
            print(f"Reply-To: {sender.reply_to}")
            print(f"Subject: {message['subject']}")
            print(message["text"])
            sent_count += 1
            processed_count += 1
            continue

        try:
            message_id = send_acs_email(
                connection_string=str(config.get("azure", {}).get("connection_string", "")).strip(),
                sender=sender,
                to_email=lead["email"],
                subject=message["subject"],
                text=message["text"],
                html_body=message["html"],
            )
            sent_at = datetime.now(timezone.utc).isoformat()
            append_sent_log(
                args.sent_log,
                {
                    "sent_at": sent_at,
                    "email": lead["email"],
                    "sender": sender.email,
                    "subject": message["subject"],
                    "message_id": message_id,
                    "source_url": lead.get("source_url", ""),
                },
            )
            _insert_outreach_message(
                base_url=base_url,
                api_key=api_key,
                owner_email=args.owner_email,
                campaign_id=campaign_id,
                lead_id=lead_id,
                sender_profile=sender.key,
                sender_address=sender.email,
                reply_to_email=sender.reply_to,
                to_email=lead["email"],
                subject_rendered=message["subject"],
                body_rendered=message["text"],
                provider_message_id=message_id,
                status="sent",
                last_error="",
                sent_at=sent_at,
            )
            _update_outreach_lead_status(
                base_url=base_url,
                api_key=api_key,
                owner_email=args.owner_email,
                email=lead["email"],
                sender_key=sender.key,
                status="sent",
                contacted_at=sent_at,
            )
            sent_count += 1
            processed_count += 1
            consecutive_failures = 0
            print(f"SENT {sent_count}: {lead['email']} via {sender.email} ({message_id or 'no message id'})")
            if processed_count < args.max_send:
                time.sleep(max(0.0, args.delay_seconds))
        except Exception as exc:
            error_text = str(exc)
            _insert_outreach_message(
                base_url=base_url,
                api_key=api_key,
                owner_email=args.owner_email,
                campaign_id=campaign_id,
                lead_id=lead_id,
                sender_profile=sender.key,
                sender_address=sender.email,
                reply_to_email=sender.reply_to,
                to_email=lead["email"],
                subject_rendered=message["subject"],
                body_rendered=message["text"],
                provider_message_id="",
                status="failed",
                last_error=error_text[:1000],
                sent_at=None,
            )
            _update_outreach_lead_status(
                base_url=base_url,
                api_key=api_key,
                owner_email=args.owner_email,
                email=lead["email"],
                sender_key=sender.key,
                status="failed",
                contacted_at=None,
            )
            processed_count += 1
            consecutive_failures += 1
            skipped += 1
            print(f"FAIL send: {lead['email']} -> {error_text}")
            if _is_domain_not_linked_error(error_text):
                hard_failure = True
                print("Stopping batch because ACS sender domain is not linked. Fix the ACS job secret or domain linkage before retrying.")
                break
            if _should_throttle_stop(error_text) or consecutive_failures >= 3:
                print("Stopping batch because provider throttling or quota was hit.")
                hard_failure = True
                break

    mode = "sent" if args.send else "previewed"
    print("")
    print(f"Done: {sent_count} {mode}, {skipped} skipped.")
    if hard_failure:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
