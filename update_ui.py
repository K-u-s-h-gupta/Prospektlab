"""
Cleanly rewrites widget.html:
- Keeps: <head> + tailwind config + fonts + the big JS <script> block
- Replaces: everything between </style> and the big <script> at the end
"""

with open('finagent/gateway/widget.html', 'r', encoding='utf-8') as f:
    content = f.read()

# The head ends at the first </style> tag
style_end = content.find('</style>') + len('</style>')

# The big JS script block starts at the LAST <script> tag before </body>
# It contains "App state machine" marker
js_start = content.find('// App state machine')
# Walk back to the opening <script> tag
js_script_open = content.rfind('<script>', 0, js_start)
js_block = content[js_script_open:]   # from <script> to end of file

# Build the new middle (new body HTML)
new_body = r"""
</head>
<body class="flex flex-col h-screen bg-[#0f1115] text-[#d1d5db]">

  <!-- ═══ TOP BAR ═══════════════════════════════════════════════════ -->
  <header class="h-14 flex items-center justify-between px-5 border-b border-white/[0.07] shrink-0 bg-[#0c0e12]">
    <div class="font-bold text-base text-white tracking-widest uppercase">FIN-OS INTEL</div>
    <div class="flex items-center gap-5 text-gray-400">
      <span class="material-symbols-outlined text-[18px] cursor-pointer hover:text-white transition-colors">notifications</span>
      <span class="material-symbols-outlined text-[18px] cursor-pointer hover:text-white transition-colors">settings</span>
      <span class="material-symbols-outlined text-[18px] cursor-pointer hover:text-white transition-colors">account_circle</span>
    </div>
  </header>

  <!-- ═══ MAIN 3-COLUMN LAYOUT ════════════════════════════════════════ -->
  <main class="flex-1 flex overflow-hidden">

    <!-- ── LEFT SIDEBAR ────────────────────────────────────────────── -->
    <aside class="w-56 border-r border-white/[0.07] flex flex-col shrink-0 bg-[#0c0e12]">
      <div class="p-3">
        <button onclick="location.reload()" class="w-full flex items-center justify-center gap-2 py-2 bg-[#1e2129] hover:bg-[#272b34] text-xs text-gray-300 rounded border border-white/[0.07] transition-colors">
          <span class="material-symbols-outlined text-[14px]">add</span> New Thread
        </button>
      </div>
      <div class="px-3 py-2 flex-1 overflow-y-auto scroll-thin">
        <div class="text-[9px] font-bold text-gray-600 mb-2 uppercase tracking-widest">Recent Intelligence</div>
        <div class="flex flex-col gap-0.5" id="recentThreadsList">
          <!-- Populated dynamically by memo library loader -->
        </div>
      </div>
    </aside>

    <!-- ── CENTER COLUMN ────────────────────────────────────────────── -->
    <section class="flex-1 flex flex-col relative overflow-hidden">

      <!-- STATE: COMMAND (Initial empty state) -->
      <div id="stateCommand" class="flex-1 flex items-center justify-center">
        <div class="text-center px-8">
          <div class="text-xl font-bold text-white mb-2">FIN-OS System Ready</div>
          <div class="text-sm text-gray-500">Initialize a query below to begin analysis.</div>
        </div>
      </div>

      <!-- STATE: PROCESSING (Live activity while research runs) -->
      <div id="stateProcessing" class="hidden flex-1 overflow-y-auto scroll-thin p-6">
        <div class="max-w-3xl mx-auto w-full">
          <div class="text-xl font-bold text-white mb-1">Analyzing <span id="processingTarget"></span></div>
          <div class="text-xs text-gray-500 mb-5">Synthesizing intelligence streams…</div>
          <div id="processingTitle" class="hidden"></div>
          <div id="processingPhaseLabel" class="text-[11px] text-gray-400 uppercase tracking-widest mb-2">Connecting…</div>
          <div class="h-0.5 bg-[#1e2129] rounded overflow-hidden mb-1">
            <div id="processingBar" class="h-full bg-gray-500 w-0 transition-all duration-500 rounded"></div>
          </div>
          <div id="processingPercent" class="text-[10px] text-gray-600 text-right"></div>
        </div>
      </div>

      <!-- STATE: RESULT (Memo output) -->
      <div id="stateResult" class="hidden flex-1 flex-col overflow-hidden">
        <div class="flex-1 overflow-y-auto scroll-thin p-6 pb-32">
          <div class="max-w-3xl mx-auto w-full">
            <h1 id="resultTitle" class="text-2xl font-bold text-white mb-1"></h1>
            <p id="resultBreadcrumb" class="text-xs text-gray-500 mb-6"></p>

            <div class="flex gap-3">
              <div class="shrink-0 mt-0.5">
                <div class="w-7 h-7 rounded bg-[#1e2129] flex items-center justify-center border border-white/[0.07]">
                  <span class="material-symbols-outlined text-[13px] text-gray-400">graphic_eq</span>
                </div>
              </div>
              <div class="flex-1 memo-prose" id="memoBody"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── BOTTOM INPUT BAR (always visible, floats above content) ── -->
      <div class="absolute bottom-4 left-0 right-0 px-6 z-20">
        <div class="max-w-3xl mx-auto bg-[#1a1c23] border border-white/[0.09] rounded-xl p-3 shadow-2xl">
          <input type="text" id="targetInput"
            class="w-full bg-transparent text-white text-sm outline-none px-2 py-1.5 placeholder-gray-600"
            placeholder="Query intelligence matrix…" autocomplete="off">
          <!-- Hidden inputs required by JS -->
          <input type="text" id="activeInput" class="hidden">
          <input type="text" id="heroSearchInput" class="hidden">

          <div class="flex items-center justify-between mt-2 px-1">
            <div class="flex items-center gap-3 text-gray-500">
              <span class="material-symbols-outlined text-[14px] cursor-pointer hover:text-gray-300 transition-colors">attach_file</span>
              <span class="material-symbols-outlined text-[14px] cursor-pointer hover:text-gray-300 transition-colors">code</span>
              <button id="modeDeep"
                class="mode-toggle ml-2 text-[9px] uppercase font-mono px-2 py-1 border border-white/[0.09] rounded hover:text-white hover:border-white/20 transition-colors tracking-widest">
                Deep Mode
              </button>
            </div>
            <button id="executeBtn"
              class="flex items-center gap-1 bg-[#272b34] hover:bg-[#323742] text-[11px] font-mono text-gray-300 px-3 py-1.5 rounded border border-white/[0.09] transition-colors">
              Execute <span class="material-symbols-outlined text-[12px]">play_arrow</span>
            </button>
            <!-- Hidden buttons required by JS -->
            <button id="activeExecuteBtn" class="hidden"></button>
            <button id="heroExecuteBtn" class="hidden"></button>
          </div>
        </div>
      </div>

    </section><!-- end center -->

    <!-- ── RIGHT SIDEBAR ────────────────────────────────────────────── -->
    <aside class="w-[320px] border-l border-white/[0.07] flex flex-col shrink-0 bg-[#0c0e12] overflow-y-auto scroll-thin">

      <!-- Search activity -->
      <div class="p-4 border-b border-white/[0.07]">
        <div class="flex items-center gap-1 text-xs text-gray-400 mb-3">
          <span class="material-symbols-outlined text-[14px]">travel_explore</span>
          Searched the web
        </div>
        <div id="queryGrid" class="flex flex-col gap-3 text-[11px]">
          <!-- Query rows injected here by upsertQuery() -->
        </div>
        <!-- Activity stream shown below queries -->
        <div id="activityStream" class="flex flex-col gap-1 mt-3 text-[10px]"></div>
      </div>

      <!-- Verified data streams -->
      <div class="p-4">
        <div class="flex items-center gap-2 mb-3">
          <span class="material-symbols-outlined text-[13px] text-gray-500">verified_user</span>
          <span class="text-[9px] font-bold text-gray-600 uppercase tracking-widest">Verified Data Streams</span>
        </div>
        <div id="liveSourcesList" class="flex flex-wrap gap-1.5 text-[10px]">
          <!-- Pill badges injected by pushLiveSource() -->
        </div>
      </div>

    </aside><!-- end right sidebar -->

  </main><!-- end main -->

  <!-- ═══ BOTTOM STATUS BAR ═══════════════════════════════════════════ -->
  <footer class="h-7 bg-[#090b0e] border-t border-white/[0.05] flex items-center justify-between px-4 shrink-0 text-[9px] font-mono text-gray-600 uppercase tracking-widest">
    <div>INTEL-FEED // SYSTEM ACTIVE</div>
    <div class="flex items-center gap-6">
      <span>Market Sentiment: Bullish</span>
      <span id="footerLatency">Latency: —</span>
      <span>Live Alerts (4)</span>
    </div>
  </footer>

  <!-- ═══ STUB IDs — required by the JS engine so it doesn't crash ════ -->
  <div class="hidden" aria-hidden="true">
    <div id="mainSidebar"></div>
    <div id="topAppBar"></div>
    <div id="ctrSources"></div>
    <div id="ctrPrimary"></div>
    <div id="agentGrid"></div>
    <div id="agentGridPill"></div>
    <div id="agentGridPanel"></div>
    <div id="verifierPanel"></div>
    <div id="verifierBody"></div>
    <div id="blindspotPanel"></div>
    <div id="blindspotBody"></div>
    <div id="playbookPanel"></div>
    <div id="playbookTitle"></div>
    <div id="playbookPill"></div>
    <div id="memoryPanel"></div>
    <div id="memoryBody"></div>
    <div id="qualityPanel"></div>
    <div id="qualityBody"></div>
    <div id="qualityGaps"></div>
    <div id="reflectionPanel"></div>
    <div id="reflectionRounds"></div>
    <div id="chartContainer"></div>
    <div id="chartMetrics"></div>
    <div id="chartTooltip"></div>
    <div id="brandText"></div>
    <div id="memoViaPill"></div>
    <div id="modeStandard"></div>
    <div id="communityPanel"></div>
    <div id="communityBadge"></div>
    <div id="communityBody"></div>
    <div id="heroTitle"></div>
    <div id="landingView"></div>
    <div id="activeInputBar"></div>
    <div id="apiSources"></div>
    <div id="backToLanding"></div>
  </div>

"""

# Reassemble: head (up to end of </style>) + new body HTML + JS block
new_file = content[:style_end] + new_body + js_block

with open('finagent/gateway/widget.html', 'w', encoding='utf-8') as f:
    f.write(new_file)

print(f"Done! New file is {len(new_file)} bytes")
