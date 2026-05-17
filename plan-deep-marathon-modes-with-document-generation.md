# 🎯 Deep & Marathon Modes with Document Generation

Replace any legacy `Standard Analysis` behavior with two explicit research modes: `Deep Mode` and `Marathon Mode`. `Deep Mode` becomes the default UI selection and the new baseline in-depth analysis path. `Marathon Mode` is a slower, more exhaustive research path that also enables post-response document generation.

Key decisions confirmed:
- Default UI mode: `Deep Mode`
- Document generation strategy: frontend-first export attempt, backend fallback later if needed
- If no format specified after Marathon: ask the user which format they want
- `Deep Mode` does not auto-generate documents unless explicitly requested

## Backend changes

### Intent/routing
Introduce an explicit analysis depth/mode dimension independent from intent classification:
- `deep`
- `marathon`

Keep finance/Indian-market query intent detection as primary, then combine with requested mode.

Add request schema support in `Backend/api.py`:
- extend `ChatRequest` with optional fields:
  - `analysis_mode: Literal["deep", "marathon"] | None`
  - `requested_export_format: Literal["pdf", "xlsx", "docx"] | str | None`
- propagate `analysis_mode` through `_execute_graph`, `_stream_graph_run`, and prompt augmentation

Add helper in `Backend/intent.py`:
- `detect_analysis_mode(message: str, explicit_mode: str | None) -> str`
  - explicit UI mode wins
  - message phrases like `marathon mode`, `full marathon research`, `full company research`, `investor-grade report`, `export to pdf/excel/word` can imply `marathon`
  - otherwise default to `deep`

### Prompting
Update `Backend/graph.py` supervisor prompt to treat depth as a first-class instruction:
- `Deep Mode`
  - fast but still in-depth
  - include ratios, sector context, risks, recent events/news, forward-looking insights
  - structured sections, concise but comprehensive
- `Marathon Mode`
  - exhaustive research
  - include historical performance, moat, management quality, valuation models, SEBI/regulatory context, competition, investor-grade risk assessment
  - completeness prioritized over brevity

Inject a mode suffix into routed message in `Backend/api.py` or graph prompt context:
- `ANALYSIS_MODE=deep`
- `ANALYSIS_MODE=marathon`
- `REQUESTED_EXPORT_FORMAT=...` when present

### Rich output metadata
Extend `Backend/rich_builder.py` / `RichResponse` to carry:
- `analysis_mode: str | None`
- `document_generation_suggested: bool = False`
- `document_prompt_needed: bool = False`
- `available_export_formats: list[str] = []`
- `manual_export_instructions: dict[str, str] | None = None`

Set behavior:
- `Deep Mode`
  - rich output as usual for finance/visual intents
  - no auto doc generation unless explicitly requested
- `Marathon Mode`
  - richer/denser content blocks allowed
  - set `document_generation_suggested=True`
  - if user did not request format, set `document_prompt_needed=True`

## Frontend changes

### Mode selector
Update `Frontend/app/page.tsx`:
- add UI selector buttons/tabs:
  - `[Deep Mode]`
  - `[Marathon Mode]`
- default selected mode: `Deep Mode`
- include selected mode in both SSE and fallback JSON requests:
  - `{ message, analysis_mode }`

Message model additions:
- `analysis_mode?: "deep" | "marathon"`
- `requested_export_format?: "pdf" | "xlsx" | "docx" | string`

### Marathon indicator
Add visible indicator in chat UI when `Marathon Mode` is active:
- badge on outgoing user message or top toolbar
- longer-running generation label such as `Marathon research in progress`

### Export flow
Create frontend export utilities/components under `Frontend/app/_components/exports/`:
- `ExportPrompt.tsx` — asks user which format they want after Marathon if none supplied
- `ExportActions.tsx` — buttons for `PDF`, `Excel`, `Word`
- `exportPdf.ts` — frontend-first PDF generation (use `jspdf` or `pdfmake`)
- `exportExcel.ts` — Excel generation (use `xlsx` / SheetJS)
- `exportDocx.ts` — Word generation (use `docx`)
- `manualInstructions.ts` — fallback instructions per format

Suggested new deps in `Frontend/package.json`:
- `jspdf`
- `xlsx`
- `docx`

Generation logic:
1. Marathon response completes
2. If format already requested in message, attempt generation immediately
3. Otherwise render prompt asking for desired format
4. On generation failure:
   - do not silently fail
   - show full structured content in chat
   - render clear manual instructions block for requested format

### Rich rendering additions
Update `Frontend/app/_components/lib/types.ts` to mirror new backend fields:
- `analysis_mode`
- `document_generation_suggested`
- `document_prompt_needed`
- `available_export_formats`
- `manual_export_instructions`

Update `RichResponse.tsx` / view components to show:
- Deep/Marathon badge
- export prompt/actions for Marathon responses
- manual instruction block when generation fails

## Remove Standard Analysis references
Search and remove or rename any `Standard Analysis` references across:
- UI labels
- API request payloads
- prompt text
- any selector logic
- documentation strings if directly user-facing

## Validation
1. Frontend lint/build
2. Focused backend tests for new mode detection
3. Add tests:
   - `detect_analysis_mode(..., explicit_mode="deep") -> deep`
   - `detect_analysis_mode(..., explicit_mode="marathon") -> marathon`
   - Marathon response sets `document_generation_suggested`
   - event/explainer queries remain text-first even in Deep Mode unless visuals explicitly requested
4. Manual flows:
   - `Give me a deep analysis of Reliance Industries`
   - `Run a full Marathon research on Tata Motors and give me a PDF report`
   - `Compare HDFC Bank and ICICI Bank in Marathon Mode, export to Excel`

**Last Updated**: 2026-05-17 17:40:32

## 📝 Plan Steps
-  **Extend `Backend/api.py` request/stream models — add `analysis_mode` and `requested_export_format` handling.**
-  **Add mode detection to `Backend/intent.py` — implement `detect_analysis_mode` and export constants.**
-  **Update backend routing/prompt context — pass selected analysis mode into execution and supervisor context.**
-  **Update `Backend/graph.py` prompts — add Deep vs Marathon behavior requirements.**
-  **Extend `Backend/rich_builder.py` schema — include analysis/document-generation metadata.**
-  **Remove any `Standard Analysis` references — clean labels, prompts, and routing strings.**
-  **Update `Frontend/package.json` — add `jspdf`, `xlsx`, and `docx`.**
-  **Add frontend mode selector in `Frontend/app/page.tsx` — default to `Deep Mode` and send mode in requests.**
-  **Add Marathon progress indicator — show visible badge/status during long research runs.**
-  **Add export utility modules under `Frontend/app/_components/exports/` — PDF, Excel, DOCX generation.**
-  **Add export prompt/actions UI — ask for format after Marathon when not provided.**
-  **Add manual fallback instructions rendering — show content + format-specific recovery steps on export failure.**
-  **Update rich-response TS types and renderers — support new analysis/document metadata.**
-  **Validate frontend — run lint and build.**
-  **Add focused backend tests — mode detection and Marathon metadata behavior.**
-  **Validate manual user flows — Deep analysis, Marathon PDF, Marathon Excel comparison.**

