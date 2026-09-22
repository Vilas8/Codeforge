from app.services.agent import CodeForgeAgent


class AgentOrchestrator:
    """Runs bounded Plan -> Build -> Test -> Diagnose/Fix -> Retest workflows."""

    MAX_FIX_ITERATIONS = 2

    def __init__(self, user_id, project_id, stream_callback=None, model=None):
        self.user_id = user_id
        self.project_id = project_id
        self.stream_callback = stream_callback
        self.model = model
        self.total_tool_calls = 0
        self.total_file_changes = 0
        self.phases = []

    async def emit(self, event):
        if self.stream_callback:
            await self.stream_callback(event)

    async def _run_phase(self, phase, prompt, mode):
        await self.emit({"type": "workflow_phase", "phase": phase, "mode": mode, "status": "started"})
        holder = {"changes": []}

        async def callback(event):
            if event.get("type") == "file_change":
                holder["changes"].append(event)
            await self.emit(event)

        agent = CodeForgeAgent(
            self.user_id,
            self.project_id,
            stream_callback=callback,
            mode=mode,
            model=self.model,
        )
        try:
            result = await agent.run(prompt)
            status = "completed"
        except Exception:
            status = "failed"
            self.total_tool_calls += agent.tool_calls
            self.total_file_changes += agent.file_changes
            await self.emit({"type": "workflow_phase", "phase": phase, "mode": mode, "status": status})
            raise

        self.total_tool_calls += agent.tool_calls
        self.total_file_changes += agent.file_changes
        self.phases.append({
            "phase": phase,
            "mode": mode,
            "result": result or "",
            "file_changes": holder["changes"],
            "tool_calls": agent.tool_calls,
        })
        await self.emit({
            "type": "workflow_phase",
            "phase": phase,
            "mode": mode,
            "status": status,
            "tool_calls": agent.tool_calls,
            "file_changes": agent.file_changes,
        })
        return result or "", holder["changes"]

    @staticmethod
    def _test_failed(result: str) -> bool:
        text = result.upper()
        if "CODEFORGE_TEST_STATUS: PASS" in text:
            return False
        if "CODEFORGE_TEST_STATUS: FAIL" in text:
            return True
        failure_markers = (
            "TESTS FAILED", "FAILED", "FAILURES", "TRACEBACK",
            "EXCEPTION", "ERROR:", "ERROR ",
        )
        success_markers = ("ALL TESTS PASSED", "NO TESTS FAILED", "PASSED")
        if any(marker in text for marker in failure_markers):
            return True
        return not any(marker in text for marker in success_markers)

    async def run(self, user_prompt):
        plan, _ = await self._run_phase(
            "plan",
            user_prompt + "\n\nReturn a concise implementation plan that another agent can execute. Do not modify files.",
            "plan",
        )

        build_prompt = (
            user_prompt
            + "\n\nIMPLEMENTATION PLAN FROM PLANNER:\n"
            + plan[:18000]
            + "\n\nImplement the request now. Validate your changes where possible."
        )
        await self._run_phase("build", build_prompt, "build")

        test_prompt = (
            "Validate the current workspace after an AI build. Run the most relevant tests, "
            "type checks, linters, builds or targeted commands. Diagnose failures but do not "
            "modify files. End your response with exactly one marker: "
            "CODEFORGE_TEST_STATUS: PASS or CODEFORGE_TEST_STATUS: FAIL.\n\n"
            "Original request:\n" + user_prompt
        )
        test_result, _ = await self._run_phase("test", test_prompt, "test")

        for iteration in range(1, self.MAX_FIX_ITERATIONS + 1):
            if not self._test_failed(test_result):
                await self.emit({
                    "type": "workflow_complete",
                    "status": "passed",
                    "iterations": iteration - 1,
                })
                return (
                    "Autopilot completed successfully.\n\n"
                    + test_result
                )

            await self.emit({
                "type": "workflow_phase",
                "phase": "diagnose",
                "mode": "debug",
                "status": "started",
                "iteration": iteration,
            })
            debug_prompt = (
                "Diagnose and fix the current test/validation failures. "
                "Make only changes needed to resolve the failures, then validate the fix.\n\n"
                "Original request:\n" + user_prompt
                + "\n\nLatest test report:\n" + test_result[:18000]
            )
            await self._run_phase("fix", debug_prompt, "debug")

            test_result, _ = await self._run_phase(
                "retest",
                test_prompt + "\n\nThis is retest iteration " + str(iteration) + ".",
                "test",
            )

        await self.emit({
            "type": "workflow_complete",
            "status": "needs_attention",
            "iterations": self.MAX_FIX_ITERATIONS,
        })
        return "Autopilot stopped after the maximum fix iterations.\n\n" + test_result
