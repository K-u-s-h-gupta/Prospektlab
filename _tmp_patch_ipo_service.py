from pathlib import Path

path = Path('backend/finagent/ipo/service.py')
text = path.read_text(encoding='utf-8')

text = text.replace(
    'IPO_DASHBOARD_EXCHANGE_TIMEOUT_SECONDS = float(os.getenv("IPO_DASHBOARD_EXCHANGE_TIMEOUT_SECONDS", "6"))',
    'IPO_DASHBOARD_EXCHANGE_TIMEOUT_SECONDS = float(os.getenv("IPO_DASHBOARD_EXCHANGE_TIMEOUT_SECONDS", "1.5"))',
)

old = '''    def _nse_slug(self, record: NseIpoRecord) -> str:
        return slugify_company(self._clean_exchange_company_name(record.company_name))

    def _parse_exchange_date(self, value: Any) -> date | None:
'''
new = '''    def _nse_slug(self, record: NseIpoRecord) -> str:
        return slugify_company(self._clean_exchange_company_name(record.company_name))

    def _is_issue_postponed(self, value: Any) -> bool:
        if isinstance(value, dict):
            name = value.get("company_name") or value.get("name") or ""
        else:
            name = value
        return "issue postponed" in str(name or "").lower()

    def _positive_number(self, value: Any) -> bool:
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False

    def _has_official_exchange_data(self, row: dict[str, Any]) -> bool:
        source_url = str(row.get("source_url") or "").lower()
        source = str(row.get("source") or "").lower()
        return (
            "nseindia.com" in source_url
            or "bseindia.com" in source_url
            or source in {"nse_api", "bse_api"}
        )

    def _has_complete_live_exchange_metrics(self, row: dict[str, Any]) -> bool:
        return (
            not self._is_issue_postponed(row)
            and self._has_official_exchange_data(row)
            and self._is_subscription_live_today(row)
            and self._positive_number(row.get("price_band_high"))
            and self._positive_number(row.get("issue_size_cr"))
        )

    def _parse_exchange_date(self, value: Any) -> date | None:
'''
if old not in text:
    raise SystemExit('insert anchor not found')
text = text.replace(old, new)

old = '''    def _is_nse_live_today(self, record: NseIpoRecord) -> bool:
        if str(record.status or "").strip().lower() != "active":
            return False
        opened = self._parse_exchange_date(record.issue_start_date)
'''
new = '''    def _is_nse_live_today(self, record: NseIpoRecord) -> bool:
        if self._is_issue_postponed(record.company_name):
            return False
        if str(record.status or "").strip().lower() != "active":
            return False
        if not record.issue_price or not record.issue_size_shares:
            return False
        opened = self._parse_exchange_date(record.issue_start_date)
'''
if old not in text:
    raise SystemExit('_is_nse_live_today anchor not found')
text = text.replace(old, new)

old = '''        for row in filings:
            source_url = str(row.get("source_url") or "").lower()
            source = str(row.get("source") or "").lower()
            has_official_exchange_data = "nseindia.com" in source_url or "bseindia.com" in source_url or source in {"nse_api", "bse_api"}
            if not has_official_exchange_data:
                continue
            if self._is_subscription_live_today(row):
                slug = str(row.get("slug") or "").lower()
                if slug:
                    slugs.add(slug)
        return slugs

    def _start_exchange_refresh_background(self) -> None:
'''
new = '''        for row in filings:
            if not self._has_complete_live_exchange_metrics(row):
                continue
            slug = str(row.get("slug") or "").lower()
            if slug:
                slugs.add(slug)
        return slugs

    def _start_exchange_refresh_background(self) -> None:
'''
if old not in text:
    raise SystemExit('_live_exchange_slugs_from_store block not found')
text = text.replace(old, new)

old = '''    def _start_exchange_refresh_background(self) -> None:
        """Kick off exchange enrichment without blocking the dashboard response."""
        if self._last_exchange_refresh_task and not self._last_exchange_refresh_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._last_exchange_refresh_task = loop.create_task(self._refresh_exchange_for_dashboard(force=True))

    async def _refresh_exchange_for_dashboard(self, *, force: bool = False) -> None:
'''
new = '''    def _start_exchange_refresh_background(self) -> None:
        """Kick off exchange enrichment without blocking the dashboard response."""
        if self._last_exchange_refresh_task and not self._last_exchange_refresh_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._last_exchange_refresh_task = loop.create_task(self._refresh_exchange_for_dashboard(force=True))

    async def _dashboard_official_live_slugs(self) -> set[str]:
        """Return current official live slugs without blocking on exchange HTTP."""
        live_slugs = await self._live_exchange_slugs_from_store()
        self._last_exchange_current_slugs = live_slugs

        now = datetime.now(timezone.utc)
        refresh_stale = (
            not self._last_exchange_refresh_at
            or (now - self._last_exchange_refresh_at).total_seconds() >= IPO_EXCHANGE_REFRESH_TTL_SECONDS
        )
        if refresh_stale:
            self._start_exchange_refresh_background()
            if self._last_exchange_refresh_task and not self._last_exchange_refresh_task.done():
                self._last_exchange_error = "Exchange refresh running in background; showing cached official exchange data."
        return live_slugs

    async def _refresh_exchange_for_dashboard(self, *, force: bool = False) -> None:
'''
if old not in text:
    raise SystemExit('_start_exchange_refresh_background block not found')
text = text.replace(old, new)

old = '''        all_nse = nse_data.get("current", []) + nse_data.get("upcoming", [])
        
        if not all_nse:
'''
new = '''        all_nse = [
            record for record in (nse_data.get("current", []) + nse_data.get("upcoming", []))
            if not self._is_issue_postponed(record.company_name)
        ]
        
        if not all_nse:
'''
if old not in text:
    raise SystemExit('all_nse block not found')
text = text.replace(old, new)

old = '''            nse_status = extra.get("nse_status")
            if nse_status == "live" and updated.get("status") != "live":
                updated["status"] = "live"
                changed = True
            elif nse_status == "forthcoming" and updated.get("status") not in ("live", "listed"):
'''
new = '''            nse_status = extra.get("nse_status")
            has_complete_offer_metrics = self._positive_number(extra.get("price_band_high")) and self._positive_number(extra.get("issue_size_cr"))
            if nse_status == "live" and has_complete_offer_metrics and updated.get("status") != "live":
                updated["status"] = "live"
                changed = True
            elif nse_status == "forthcoming" and updated.get("status") not in ("live", "listed"):
'''
if old not in text:
    raise SystemExit('nse status block not found')
text = text.replace(old, new)

old = '''        await self.ensure_seed_data()
        try:
            await asyncio.wait_for(
                self._refresh_exchange_for_dashboard(),
                timeout=IPO_DASHBOARD_EXCHANGE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self._last_exchange_error = f"Exchange refresh timed out after {IPO_DASHBOARD_EXCHANGE_TIMEOUT_SECONDS:g}s; showing cached exchange data."
            self._last_exchange_current_slugs = await self._live_exchange_slugs_from_store()
            self._last_exchange_refresh_at = datetime.now(timezone.utc)
            self._start_exchange_refresh_background()
        except Exception as exc:
            self._last_exchange_error = f"Exchange refresh failed: {exc}; showing cached exchange data."
            self._last_exchange_current_slugs = await self._live_exchange_slugs_from_store()
            self._last_exchange_refresh_at = datetime.now(timezone.utc)
            self._start_exchange_refresh_background()

        filings = await self.store.list_filings(limit=200)
        official_live_slugs = set(self._last_exchange_current_slugs)
        if not official_live_slugs:
            official_live_slugs = await self._live_exchange_slugs_from_store()
'''
new = '''        await self.ensure_seed_data()
        official_live_slugs = await self._dashboard_official_live_slugs()
        filings = await self.store.list_filings(limit=200)
'''
if old not in text:
    raise SystemExit('pipeline refresh block not found')
text = text.replace(old, new)

old = '''            if status == "live":
                slug = str(enriched.get("slug") or "").lower()
                if slug not in official_live_slugs or not self._is_subscription_live_today(enriched):
                    continue
'''
new = '''            if status == "live":
                slug = str(enriched.get("slug") or "").lower()
                if slug not in official_live_slugs or not self._has_complete_live_exchange_metrics(enriched):
                    continue
'''
if old not in text:
    raise SystemExit('live filter block not found')
text = text.replace(old, new)

path.write_text(text, encoding='utf-8')
