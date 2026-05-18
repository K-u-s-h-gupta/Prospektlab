import os

file_path = "finagent/gateway/run.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

old_deep_runner = '''    async def _deep_runner() -> None:
        total_passes = req.passes
        completed_passes = 0
        started_at = asyncio.get_running_loop().time()
        chat_history = _MEMORY_MANAGER.get_history(req.user_email, master_session)
        
        try:
            for i in range(total_passes):
                remaining = None
                if req.max_wall_seconds is not None:
                    remaining = req.max_wall_seconds - (asyncio.get_running_loop().time() - started_at)
                    if remaining <= 0:
                        BUS.emit(
                            master_session,
                            "phase",
                            phase="stopped",
                            reason="time_budget",
                            note="Deep research wall-clock budget reached.",
                        )
                        break
                objective = _DEEP_PASS_OBJECTIVES[i % len(_DEEP_PASS_OBJECTIVES)]
                pass_label = f"Pass {i+1}/{total_passes}"
                BUS.emit(
                    master_session, "phase",
                    phase="deep_research",
                    note=f"{pass_label}: {objective[:60]}…",
                )
                BUS.emit(
                    master_session, "deep_pass",
                    pass_number=i + 1,
                    total_passes=total_passes,
                    objective=objective,
                    status="running",
                )

                # Each pass is a full research session that reads+writes memory
                pass_objective = f"{raw_query}\\n\\n{pass_label} - {objective}"
                await run_research_session(
                    target,
                    pass_objective,
                    loop_config=AgentLoopConfig(
                        max_steps=req.pass_depth,
                        session_id=master_session,
                        auto_depth=False,
                        enable_memory=True,
                        reflection_max_rounds=3,
                        quality_threshold=65.0,
                        synth_model="gpt-4o",
                        response_depth=("deep" if i == total_passes - 1 else "standard"),
                        output_mode=("deep_research_report" if i == total_passes - 1 else None),
                        emit_memo=(i == total_passes - 1),
                        close_bus_on_finish=False,
                        chat_history=chat_history if i == 0 else None,
                        breadth_search_timeout=180.0,
                        followup_search_timeout=75.0,
                        reflection_per_query_timeout=60.0,
                        blindspot_per_query_timeout=50.0,
                        news_timeout=45.0,
                    ),
                )

                BUS.emit(
                    master_session, "deep_pass",
                    pass_number=i + 1,
                    total_passes=total_passes,
                    objective=objective,
                    status="done",
                )
                completed_passes += 1

                # Brief pause between passes to let memory persist
                if i < total_passes - 1:
                    await asyncio.sleep(2)

            BUS.emit(master_session, "deep_complete", passes=completed_passes, requested_passes=total_passes)
        except Exception as exc:
            logger.exception("deep research %s crashed on pass", master_session)
            BUS.emit(master_session, "error", message=f"Deep research failed: {exc}")
        finally:
            BUS.close(master_session)'''

new_deep_runner = '''    async def _deep_runner() -> None:
        total_passes = req.passes
        completed_passes = 0
        started_at = asyncio.get_running_loop().time()
        chat_history = _MEMORY_MANAGER.get_history(req.user_email, master_session)
        
        try:
            async def _run_pass(i: int) -> bool:
                remaining = None
                if req.max_wall_seconds is not None:
                    remaining = req.max_wall_seconds - (asyncio.get_running_loop().time() - started_at)
                    if remaining <= 0:
                        return False
                
                is_last = (i == total_passes - 1)
                objective = _DEEP_PASS_OBJECTIVES[i % len(_DEEP_PASS_OBJECTIVES)]
                pass_label = f"Synthesis Pass {i+1}/{total_passes}" if is_last else f"Pass {i+1}/{total_passes}"
                
                BUS.emit(master_session, "phase", phase="deep_research", note=f"{pass_label}: {objective[:60]}…")
                BUS.emit(master_session, "deep_pass", pass_number=i+1, total_passes=total_passes, objective=objective, status="running")
                
                pass_objective = f"{raw_query}\\n\\n{pass_label} - {objective}"
                await run_research_session(
                    target,
                    pass_objective,
                    loop_config=AgentLoopConfig(
                        max_steps=req.pass_depth,
                        session_id=master_session,
                        auto_depth=False,
                        enable_memory=True,
                        reflection_max_rounds=3,
                        quality_threshold=65.0,
                        synth_model="gpt-4o",
                        response_depth=("deep" if is_last else "standard"),
                        output_mode=("deep_research_report" if is_last else None),
                        emit_memo=is_last,
                        close_bus_on_finish=False,
                        chat_history=chat_history if (i == 0 or is_last) else None,
                        breadth_search_timeout=180.0,
                        followup_search_timeout=75.0,
                        reflection_per_query_timeout=60.0,
                        blindspot_per_query_timeout=50.0,
                        news_timeout=45.0,
                    ),
                )
                
                BUS.emit(master_session, "deep_pass", pass_number=i+1, total_passes=total_passes, objective=objective, status="done")
                return True

            # Phase 1: Run all enrichment/research passes in parallel (Marathon mode parallel pass execution)
            BUS.emit(master_session, "phase", phase="deep_research", note=f"Executing passes 1 to {total_passes-1} in parallel")
            parallel_tasks = [_run_pass(i) for i in range(total_passes - 1)]
            results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
            for res in results:
                if res is True:
                    completed_passes += 1
            
            # Brief pause to let memory sync (SQLite WAL handles it concurrently, but safe measure)
            await asyncio.sleep(1.0)
            
            # Phase 2: Run final synthesis pass serially
            if await _run_pass(total_passes - 1):
                completed_passes += 1
            
            BUS.emit(master_session, "deep_complete", passes=completed_passes, requested_passes=total_passes)
        except Exception as exc:
            logger.exception("deep research %s crashed on pass", master_session)
            BUS.emit(master_session, "error", message=f"Deep research failed: {exc}")
        finally:
            BUS.close(master_session)'''

if old_deep_runner in content:
    content = content.replace(old_deep_runner, new_deep_runner)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Replaced successfully")
else:
    print("Could not find old deep runner exact match.")
