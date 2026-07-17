import importlib.util
import copy
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).parents[1] / "forgecode.py"
SPEC = importlib.util.spec_from_file_location("forgecode", MODULE_PATH)
forgecode = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["forgecode"] = forgecode
SPEC.loader.exec_module(forgecode)


class ConfigTests(unittest.TestCase):
    def test_ui_language_persists_and_localizes_core_interface(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            cfg = forgecode.Config(home)
            try:
                cfg.set_value("ui_language", "en")
                self.assertEqual(forgecode.Config(home).data["ui_language"], "en")
                output = io.StringIO()
                with mock.patch.object(sys, "stdout", output):
                    forgecode.print("Desteklenen sağlayıcılar")
                self.assertIn("Supported providers", output.getvalue())
                self.assertIn("Commands", forgecode.HELP_EN)
                with self.assertRaises(ValueError):
                    cfg.set_value("ui_language", "de")
            finally:
                cfg.set_value("ui_language", "tr")

    def test_first_run_language_selection_can_choose_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            try:
                with mock.patch.object(forgecode.builtins, "input", return_value="2"), mock.patch.object(
                    forgecode.builtins, "print"
                ):
                    forgecode.choose_language(cfg)
                self.assertEqual(cfg.data["ui_language"], "en")
                self.assertTrue(cfg.data["ui_language_selected"])
            finally:
                forgecode.set_ui_language("tr")

    def test_english_interface_guides_default_model_response_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            try:
                cfg.set_value("ui_language", "en")
                agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
                self.assertIn("interface language is English", agent.system())
            finally:
                forgecode.set_ui_language("tr")

    def test_windows_app_home_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = pathlib.Path(tmp) / "LocalAppData"
            with mock.patch.object(forgecode.os, "name", "nt"), mock.patch.dict(
                forgecode.os.environ, {"LOCALAPPDATA": str(local)}, clear=True
            ):
                self.assertEqual(forgecode.app_home(), local / "ForgeCode")

    def test_legacy_windows_settings_are_copied_to_app_data_without_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            legacy = base / "profile" / ".forgecode"
            destination = base / "appdata" / "ForgeCode"
            legacy.mkdir(parents=True)
            (legacy / "config.json").write_text(
                json.dumps({"setup_complete": True, "model": "legacy-model"}), encoding="utf-8"
            )
            (legacy / "usage.jsonl").write_text("legacy usage\n", encoding="utf-8")
            with mock.patch.object(forgecode.os, "name", "nt"), mock.patch.object(
                forgecode.pathlib.Path, "home", return_value=base / "profile"
            ), mock.patch.dict(forgecode.os.environ, {"LOCALAPPDATA": str(base / "appdata")}, clear=True):
                cfg = forgecode.Config()
            self.assertEqual(cfg.home, destination)
            self.assertEqual(cfg.data["model"], "legacy-model")
            self.assertTrue((destination / "usage.jsonl").exists())
            self.assertTrue((legacy / "config.json").exists())

    def test_temperature_defaults_to_one_and_validates_universal_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            self.assertEqual(cfg.data["temperature"], 1.0)
            cfg.set_value("temperature", "0.7")
            self.assertEqual(cfg.data["temperature"], 0.7)
            with self.assertRaises(ValueError):
                cfg.set_value("temperature", "1.1")

    def test_main_timeout_defaults_to_one_hundred_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            self.assertEqual(cfg.data["timeout_seconds"], 100)

    def test_typed_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.set_value("max_tokens", "2048")
            cfg.set_value("auto_approve_writes", "true")
            cfg.set_value("temperature", "0.4")
            reloaded = forgecode.Config(pathlib.Path(tmp))
            self.assertEqual(reloaded.data["max_tokens"], 2048)
            self.assertTrue(reloaded.data["auto_approve_writes"])
            self.assertEqual(reloaded.data["temperature"], 0.4)

    def test_rejects_invalid_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            with self.assertRaises(ValueError):
                cfg.set_value("provider", "mystery")

    def test_provider_preset_updates_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.select_provider("gemini")
            self.assertEqual(cfg.mode(), "chat")
            self.assertIn("generativelanguage.googleapis.com", cfg.base_url())
            self.assertEqual(cfg.data["model"], "gemini-3.5-flash")
            self.assertTrue(cfg.data["setup_complete"])

    def test_openrouter_defaults_to_free_router(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.select_provider("openrouter")
            self.assertEqual(cfg.data["model"], "openrouter/free")
            self.assertEqual(cfg.data["input_price_per_million"], 0.0)

    def test_local_provider_does_not_require_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.select_provider("ollama")
            self.assertFalse(cfg.requires_key())
            self.assertIsInstance(forgecode.make_provider(cfg), forgecode.OpenAIChatProvider)

    def test_kimchi_provider_preset_and_pricing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.select_provider("kimchi")
            self.assertEqual(cfg.base_url(), "https://llm.kimchi.dev/openai/v1")
            self.assertEqual(cfg.data["model"], "minimax-m3")
            self.assertEqual(cfg.data["input_price_per_million"], 0.30)
            self.assertEqual(cfg.data["output_price_per_million"], 1.20)
            self.assertTrue(cfg.requires_key())

    def test_advanced_modes_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.set_value("web_search_mode", "on")
            cfg.set_value("thinking_mode", "medium")
            cfg.set_value("efficiency_mode", "max")
            cfg.set_value("power_mode", "on")
            self.assertEqual((cfg.data["web_search_mode"], cfg.data["thinking_mode"], cfg.data["efficiency_mode"], cfg.data["power_mode"]), ("on", "medium", "max", "on"))
            with self.assertRaises(ValueError):
                cfg.set_value("efficiency_mode", "turbo")
            with self.assertRaises(ValueError):
                cfg.set_value("power_mode", "turbo")

    def test_power_mode_defaults_to_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            self.assertEqual(cfg.data["power_mode"], "auto")

    def test_new_provider_presets_keep_custom_at_number_nineteen(self):
        self.assertEqual(list(forgecode.PROVIDERS)[18], "custom")
        self.assertEqual(forgecode.PROVIDERS["github"]["url"], "https://models.github.ai/inference")
        self.assertEqual(forgecode.PROVIDERS["huggingface"]["url"], "https://router.huggingface.co/v1")
        self.assertIn("compatible-mode/v1", forgecode.PROVIDERS["dashscope"]["url"])

    def test_team_roles_are_typed_deduplicated_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.set_value("team_roles", "design, backend design")
            self.assertEqual(cfg.data["team_roles"], ["design", "backend"])
            with self.assertRaises(ValueError):
                cfg.set_value("team_roles", "design,wizard")

    def test_startup_prompt_redacts_accidentally_pasted_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            secret = "sk-accidental-secret-123456789"
            cfg.set_value("startup_prompt", "api_key=" + secret)
            self.assertNotIn(secret, cfg.data["startup_prompt"])
            self.assertIn("[REDACTED]", cfg.data["startup_prompt"])


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.cfg = forgecode.Config(self.root / "home")
        self.tools = forgecode.WorkspaceTools(self.root, self.cfg, lambda _: True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_blocks_path_escape(self):
        with self.assertRaises(ValueError):
            self.tools.safe_path("../secret.txt")

    def test_only_custom_claude_remaps_known_remote_workspace_paths(self):
        with self.assertRaises(ValueError):
            self.tools.safe_path("/tmp/proxy-hunter/index.html")
        self.cfg.select_provider("custom")
        self.cfg.data.update({"api_mode": "anthropic", "custom_protocol": "anthropic", "autopilot_mode": True})
        self.assertEqual(self.tools.safe_path("/tmp/proxy-hunter/index.html"), self.root / "index.html")
        self.assertEqual(self.tools.safe_path("/workspace/assets/css/site.css"), self.root / "assets/css/site.css")
        with self.assertRaises(ValueError):
            self.tools.safe_path("/etc/passwd")

    def test_custom_claude_remote_write_lands_in_local_project(self):
        self.cfg.select_provider("custom")
        self.cfg.data.update({"api_mode": "anthropic", "custom_protocol": "anthropic", "autopilot_mode": True})
        result = self.tools.execute("Write", {"file_path": "/tmp/proxy-hunter/assets/app.js", "content": "ready"})
        self.assertIn("OK: assets/app.js", result)
        self.assertEqual((self.root / "assets/app.js").read_text(encoding="utf-8"), "ready")

    def test_write_read_search_replace(self):
        self.assertIn("OK", self.tools.tool_write_file("src/a.txt", "hello world\nsecond"))
        self.assertIn("1 | hello world", self.tools.tool_read_file("src/a.txt"))
        self.assertIn("src/a.txt:1", self.tools.tool_search("WORLD"))
        self.assertIn("OK", self.tools.tool_replace_text("src/a.txt", "world", "agent"))
        self.assertEqual((self.root / "src/a.txt").read_text(), "hello agent\nsecond")

    def test_rejects_ambiguous_replace(self):
        (self.root / "x.txt").write_text("a a")
        with self.assertRaises(ValueError):
            self.tools.tool_replace_text("x.txt", "a", "b")

    def test_smart_autopilot_ai_approves_safe_write_without_question(self):
        self.cfg.data["smart_autopilot_mode"] = True
        confirmations = []
        assessments = []
        tools = forgecode.WorkspaceTools(
            self.root, self.cfg, lambda question: confirmations.append(question) or False,
            lambda operation, details: assessments.append((operation, details)) or ("safe", "Proje içi geri alınabilir dosya yazımı."),
        )
        result = tools.tool_write_file("site/index.html", "<h1>Safe</h1>")
        self.assertIn("OK", result)
        self.assertEqual(confirmations, [])
        self.assertEqual(assessments[0][0], "write")

    def test_smart_autopilot_asks_only_when_ai_finds_risk(self):
        self.cfg.data["smart_autopilot_mode"] = True
        confirmations = []
        tools = forgecode.WorkspaceTools(
            self.root, self.cfg, lambda question: confirmations.append(question) or True,
            lambda *_: ("ask", "Komut ağdan bağımlılık indirip kod çalıştırabilir."),
        )
        completed = mock.Mock(returncode=0, stdout="installed", stderr="")
        with mock.patch.object(forgecode.subprocess, "run", return_value=completed) as run:
            result = tools.tool_run_command("npm install")
        self.assertIn("exit_code=0", result)
        self.assertEqual(len(confirmations), 1)
        self.assertIn("ağdan bağımlılık", confirmations[0])
        run.assert_called_once()

    def test_smart_autopilot_hard_blocks_catastrophic_command_before_ai(self):
        self.cfg.data["smart_autopilot_mode"] = True
        assessor = mock.Mock(return_value=("safe", "safe"))
        confirmations = []
        tools = forgecode.WorkspaceTools(self.root, self.cfg, lambda value: confirmations.append(value) or True, assessor)
        with mock.patch.object(forgecode.subprocess, "run") as run:
            result = tools.tool_run_command("Remove-Item -Recurse -Force C:\\Users")
        self.assertIn("güvenlik engeli", result)
        assessor.assert_not_called()
        run.assert_not_called()
        self.assertEqual(confirmations, [])

    def test_run_command_handles_none_and_invalid_locale_bytes_without_secondary_error(self):
        self.cfg.data["auto_approve_commands"] = True
        completed = mock.Mock(returncode=1, stdout=None, stderr=b"bad-byte:\x8f")
        with mock.patch.object(forgecode.subprocess, "run", return_value=completed) as run:
            result = self.tools.tool_run_command('powershell -Command "[Console]::OpenStandardOutput().WriteByte(143)"')
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("1 çıkış koduyla", result)
        self.assertIn("bad-byte", result)
        self.assertNotIn("NoneType", result)
        self.assertFalse(run.call_args.kwargs["text"])

    def test_read_only_shell_file_views_use_internal_reader_without_security_ai_or_subprocess(self):
        self.cfg.data["smart_autopilot_mode"] = True
        (self.root / "index.html").write_text("one\ntwo\nthree", encoding="utf-8")
        assessor = mock.Mock(return_value=("ask", "should not be called"))
        tools = forgecode.WorkspaceTools(self.root, self.cfg, lambda _: False, assessor)
        commands = {
            "type index.html": "one\ntwo\nthree",
            "Get-Content index.html": "one\ntwo\nthree",
            'powershell -Command "Get-Content index.html -Tail 2"': "two\nthree",
            "cat index.html | head -2": "one\ntwo",
        }
        with mock.patch.object(forgecode.subprocess, "run") as run:
            for command, expected in commands.items():
                result = tools.tool_run_command(command)
                self.assertEqual(result, "exit_code=0\n" + expected)
        assessor.assert_not_called()
        run.assert_not_called()

    def test_file_tools_reject_empty_root_and_directory_paths(self):
        (self.root / "folder").mkdir()
        for path in ("", ".", "./", ".\\", "folder"):
            with self.subTest(path=path):
                result = self.tools.execute("write_file", {"path": path, "content": "x"})
                self.assertTrue(result.startswith("ERROR:"), result)
        self.assertFalse((self.root / "x").exists())

    def test_large_unicode_write_is_atomic_verified_utf8_without_bom(self):
        content = "\ufeff" + ("Türkçe içerik — 😀\n" * 10000)
        result = self.tools.tool_write_file("space folder/büyük.txt", content)
        target = self.root / "space folder" / "büyük.txt"
        raw = target.read_bytes()
        self.assertIn("UTF-8 doğrulandı", result)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.decode("utf-8"), content.lstrip("\ufeff"))
        self.assertEqual(list(target.parent.glob("*.forgecode-*.tmp")), [])

    def test_atomic_write_failure_preserves_existing_target_and_cleans_temp(self):
        target = self.root / "important.txt"
        target.write_text("old content", encoding="utf-8")
        with mock.patch.object(forgecode.os, "replace", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                self.tools.tool_write_file("important.txt", "new content")
        self.assertEqual(target.read_text(encoding="utf-8"), "old content")
        self.assertEqual(list(self.root.glob("*.forgecode-*.tmp")), [])

    def test_unquoted_spaced_file_view_uses_internal_reader(self):
        target = self.root / "force test zone" / "index.html"
        target.parent.mkdir(parents=True)
        target.write_text("one\ntwo\nthree", encoding="utf-8")
        self.cfg.data["auto_approve_commands"] = True
        with mock.patch.object(forgecode.subprocess, "run") as run:
            result = self.tools.tool_run_command("Get-Content force test zone/index.html -Tail 2")
        self.assertEqual(result, "exit_code=0\ntwo\nthree")
        run.assert_not_called()

    def test_agent_safety_classifier_uses_no_tools_and_parses_json(self):
        agent = forgecode.Agent(self.root, self.cfg, forgecode.GoalStore(self.root), lambda _: False)
        provider = mock.MagicMock()
        provider.request.return_value = forgecode.ModelReply(
            '{"decision":"SAFE","reason":"Sadece test çalıştırıyor."}', [], forgecode.Usage(4, 2), []
        )
        agent.provider = provider
        decision, reason = agent.assess_tool_risk("command", "python -m unittest")
        self.assertEqual(decision, "safe")
        self.assertIn("test", reason)
        self.assertEqual(provider.request.call_args.args[2], [])


class GoalAndHistoryTests(unittest.TestCase):
    def test_goal_persistence_and_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            goals = forgecode.GoalStore(root)
            goal = goals.add("tests pass")
            self.assertIn("tests pass", forgecode.GoalStore(root).active_text())
            self.assertTrue(goals.complete(goal["id"]))
            self.assertNotIn("tests pass", goals.active_text())

    def test_goal_find_resolves_oldest_active_id_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            goals = forgecode.GoalStore(pathlib.Path(tmp))
            first = goals.add("first")
            second = goals.add("second")
            self.assertEqual(goals.find()["id"], first["id"])
            self.assertEqual(goals.find("2")["id"], second["id"])
            goals.complete(first["id"])
            self.assertEqual(goals.find()["id"], second["id"])

    def test_goal_runner_retries_until_artifact_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["autopilot_mode"] = True
            goals = forgecode.GoalStore(root)
            goal = goals.add("Create a real demo file")
            agent = forgecode.Agent(root, cfg, goals, lambda _: False)
            calls = []

            def fake_ask(prompt, on_tool=None):
                calls.append(prompt)
                if len(calls) == 1:
                    return "Görev tamamlanmadı: henüz dosya yok."
                agent.tools.tool_write_file("demo.txt", "verified")
                return "Hedef tamamlandı ve dosya doğrulandı."

            with mock.patch.object(agent, "ask", side_effect=fake_ask):
                result = forgecode.run_goal_until_complete(agent, goals, goal, 3)
            self.assertTrue(result.completed)
            self.assertEqual(result.rounds, 2)
            self.assertEqual(result.changed_files, ["demo.txt"])
            self.assertTrue(goals.goals[0]["done"])
            self.assertIn("previous round", calls[1].lower())

    def test_unverified_goal_remains_active_after_round_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            goals = forgecode.GoalStore(root)
            goal = goals.add("Create a missing application")
            agent = forgecode.Agent(root, cfg, goals, lambda _: False)
            with mock.patch.object(agent, "ask", return_value="Görev tamamlanmadı: dosya yok.") as ask:
                result = forgecode.run_goal_until_complete(agent, goals, goal, 3)
            self.assertFalse(result.completed)
            self.assertEqual(result.rounds, 3)
            self.assertEqual(ask.call_count, 3)
            self.assertFalse(goals.goals[0]["done"])

    def test_history_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = forgecode.HistoryStore(pathlib.Path(tmp))
            history.record("hello", "world", forgecode.Usage(10, 2))
            self.assertEqual(history.recent()[0]["user"], "hello")

    def test_session_history_and_memory_survive_agent_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            first = forgecode.SessionStore(root, "main", cfg)
            first.record_turn("build the menu", "created files", forgecode.Usage(12, 4), ["site/index.html"])
            note = first.remember("Use a dark green visual identity")
            second = forgecode.SessionStore(root, "main", cfg)
            self.assertEqual(second.recent_turns()[0]["changed_files"], ["site/index.html"])
            self.assertEqual(second.memories()[0]["id"], note["id"])
            self.assertIn("dark green", second.context())

    def test_persistent_logs_redact_keys_and_never_claim_raw_thoughts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            store = forgecode.SessionStore(root, "main", cfg)
            secret = "sk-example-secret-1234567890"
            store.record_turn("api_key=" + secret, "safe", forgecode.Usage())
            store.log_event("activity", "authorization: bearer " + secret)
            stored = (root / ".forgecode" / "sessions" / "main.jsonl").read_text(encoding="utf-8")
            events = (root / ".forgecode" / "logs" / "events.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(secret, stored + events)
            self.assertIn("[REDACTED]", stored + events)

    def test_startup_prompt_and_memory_are_in_system_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["startup_prompt"] = "Always verify tests before finishing."
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent.session_store.remember("The public API must stay backwards compatible")
            system = agent.system()
            self.assertIn("Always verify tests", system)
            self.assertIn("backwards compatible", system)

    def test_agent_can_switch_between_named_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent.switch_session("frontend")
            self.assertEqual(agent.session_name, "frontend")
            self.assertEqual(cfg.data["session_name"], "frontend")
            with self.assertRaises(ValueError):
                agent.switch_session("bad session name")


class PortableInitTests(unittest.TestCase):
    def test_init_exports_redacted_context_goals_and_project_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "src").mkdir()
            (root / "src/app.py").write_text("print('ready')\n", encoding="utf-8")
            cfg = forgecode.Config(root / "home")
            cfg.data["startup_prompt"] = "Run tests before declaring completion"
            goals = forgecode.GoalStore(root)
            goals.add("Finish the portable handoff")
            agent = forgecode.Agent(root, cfg, goals, lambda _: False)
            agent.session_store.remember("Preserve the public CLI")
            secret = "sk-portable-secret-1234567890"
            agent.session_store.record_turn(
                "Implement export with api_key=" + secret + " via http://203.0.113.10:4000/v1",
                "Created the initial exporter",
                forgecode.Usage(10, 4),
                ["src/app.py"],
            )
            agent.history_store.record("Legacy request must remain available", "Legacy work completed", forgecode.Usage(3, 2))
            changed, stats = forgecode.initialize_portable_handoff(agent, cfg, goals, "Next AI should inspect the exporter")
            handoff = (root / "AI_HANDOFF.md").read_text(encoding="utf-8")
            self.assertEqual(changed, ["AI_HANDOFF.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md"])
            self.assertEqual(stats["instructions"], 2)
            self.assertIn("Run tests before", handoff)
            self.assertIn("Preserve the public CLI", handoff)
            self.assertIn("Finish the portable handoff", handoff)
            self.assertIn("Legacy request must remain available", handoff)
            self.assertIn("src/app.py", handoff)
            self.assertNotIn(secret, handoff)
            self.assertNotIn("203.0.113.10", handoff)
            self.assertIn("[REDACTED]", handoff)

    def test_init_preserves_existing_agent_instructions_and_updates_one_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "AGENTS.md").write_text("# Existing rules\n\nNever remove this.\n", encoding="utf-8")
            cfg = forgecode.Config(root / "home")
            goals = forgecode.GoalStore(root)
            agent = forgecode.Agent(root, cfg, goals, lambda _: False)
            forgecode.initialize_portable_handoff(agent, cfg, goals)
            first_agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            forgecode.initialize_portable_handoff(agent, cfg, goals, "updated")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(first_agents, agents)
            self.assertIn("Never remove this.", agents)
            self.assertEqual(agents.count(forgecode.HANDOFF_START), 1)
            self.assertEqual(agents.count(forgecode.HANDOFF_END), 1)

    def test_init_command_does_not_call_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            goals = forgecode.GoalStore(root)
            agent = forgecode.Agent(root, cfg, goals, lambda _: False)
            agent.provider = mock.MagicMock()
            output = io.StringIO()
            with mock.patch.object(sys, "stdout", output):
                self.assertTrue(forgecode.handle_command("/init hand this project to another AI", agent, cfg, goals))
            agent.provider.request.assert_not_called()
            self.assertTrue((root / "AI_HANDOFF.md").is_file())
            self.assertIn("Taşınabilir AI devri hazır", output.getvalue())


class ProviderTests(unittest.TestCase):
    def test_chinese_available_model_list_is_extracted(self):
        message = '你请求的模型 "claude-opus-4.8" 暂不支持。可用模型：claude-opus-4-7 / claude-haiku-4-5-20251001 / claude-sonnet-4-6 / claude-sonnet-5'
        self.assertEqual(forgecode.advertised_models_from_error(message), [
            "claude-opus-4-7", "claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-sonnet-5"
        ])

    def test_api_error_parser_accepts_string_and_list_shapes(self):
        self.assertEqual(forgecode.api_error_message('{"error":"Kimchi unavailable"}'), "Kimchi unavailable")
        self.assertEqual(forgecode.api_error_message('{"error":{"message":"route failed"}}'), "route failed")
        self.assertIn("first", forgecode.api_error_message('{"error":[{"message":"first"},"second"]}'))

    def test_http_string_error_becomes_api_error_instead_of_crash(self):
        error = forgecode.urllib.error.HTTPError(
            "https://llm.kimchi.dev/openai/v1/chat/completions", 503, "Unavailable", {},
            io.BytesIO(b'{"error":"Kimchi route unavailable"}'),
        )
        with mock.patch.object(forgecode.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(forgecode.ApiError, "Kimchi route unavailable"):
                forgecode.post_json("https://llm.kimchi.dev/openai/v1/chat/completions", {}, {}, 5)

    def test_unexpected_errors_are_written_to_crash_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            path = forgecode.write_crash_log(cfg, RuntimeError("boom"))
            self.assertTrue(path.is_file())
            self.assertIn("RuntimeError: boom", path.read_text(encoding="utf-8"))

    def test_http_client_sends_application_user_agent(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with mock.patch.object(forgecode.urllib.request, "urlopen", return_value=response) as opened:
            forgecode.post_json("https://example.test/v1", {}, {"ok": True}, 5)
        headers = {key.lower(): value for key, value in opened.call_args.args[0].headers.items()}
        self.assertIn("forgecode/", headers["user-agent"].lower())
        self.assertEqual(headers["accept"], "application/json")

    def test_model_discovery_is_sorted_and_cached(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("groq")
        cfg.data["groq_api_key"] = "gsk_test"
        fake = {"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "a-model"}]}
        with mock.patch.object(forgecode, "get_json", return_value=fake) as get:
            models = forgecode.fetch_models(cfg)
        self.assertEqual(models, ["a-model", "z-model"])
        self.assertEqual(forgecode.cached_models(cfg), models)
        self.assertTrue(get.call_args.args[0].endswith("/models"))
        self.assertEqual(get.call_args.args[1]["Authorization"], "Bearer gsk_test")

    def test_huggingface_catalog_reads_provider_prices_and_free_models(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("huggingface")
        cfg.data["huggingface_api_key"] = "hf_test_token_123"
        fake = [
            {"id": "vendor/paid", "providers": [{"provider": "fast", "status": "live", "pricing": {"input": 1.25, "output": 2.5}, "supports_tools": True, "context_length": 64000}]},
            {"id": "vendor/free", "providers": [{"provider": "community", "status": "live", "pricing": {"input": 0, "output": 0}, "is_free": True}]},
        ]
        with mock.patch.object(forgecode, "get_json", return_value=fake):
            models = forgecode.fetch_models(cfg)
        self.assertEqual(models[0], "vendor/free")
        paid = {item["id"]: item for item in forgecode.cached_catalog(cfg)}["vendor/paid"]
        self.assertEqual((paid["input_price"], paid["output_price"]), (1.25, 2.5))
        self.assertTrue(paid["tools"])
        forgecode.apply_model_pricing(cfg, "vendor/paid")
        self.assertEqual(cfg.data["output_price_per_million"], 2.5)

    def test_github_catalog_uses_official_catalog_route_and_headers(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("github")
        cfg.data["github_api_key"] = "github-token"
        with mock.patch.object(forgecode, "get_json", return_value=[{"id": "openai/gpt-test", "limits": {"max_input_tokens": 32000}}]) as get:
            self.assertEqual(forgecode.fetch_models(cfg), ["openai/gpt-test"])
        self.assertEqual(get.call_args.args[0], "https://models.github.ai/catalog/models")
        self.assertEqual(get.call_args.args[1]["Authorization"], "Bearer github-token")
        self.assertEqual(get.call_args.args[1]["X-GitHub-Api-Version"], "2026-03-10")

    def test_anthropic_model_discovery_uses_native_path(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("anthropic")
        cfg.data["anthropic_api_key"] = "sk-ant-test"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}), mock.patch.object(
            forgecode, "get_json", return_value={"data": [{"id": "claude-test"}]}
        ) as get:
            self.assertEqual(forgecode.fetch_models(cfg), ["claude-test"])
        self.assertTrue(get.call_args.args[0].endswith("/v1/models"))
        self.assertEqual(get.call_args.args[1]["x-api-key"], "sk-ant-test")

    def test_openrouter_catalog_puts_router_and_free_models_first(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("openrouter")
        cfg.data["openrouter_api_key"] = "sk-or-test"
        fake = {"data": [
            {"id": "vendor/expensive", "pricing": {"prompt": "0.000003", "completion": "0.000009"}, "supported_parameters": ["tools"]},
            {"id": "vendor/free:free", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"]},
            {"id": "vendor/cheap", "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}},
        ]}
        with mock.patch.object(forgecode, "get_json", return_value=fake):
            models = forgecode.fetch_models(cfg)
        self.assertEqual(models[:2], ["openrouter/free", "vendor/free:free"])
        self.assertEqual(models[2:], ["vendor/cheap", "vendor/expensive"])
        forgecode.apply_model_pricing(cfg, "vendor/expensive")
        self.assertEqual(cfg.data["input_price_per_million"], 3.0)
        self.assertEqual(cfg.data["output_price_per_million"], 9.0)

    def test_openrouter_web_and_reasoning_payload(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("openrouter")
        cfg.data["openrouter_api_key"] = "sk-or-test"
        cfg.data["thinking_mode"] = "low"
        fake = {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}}
        with mock.patch.object(forgecode, "post_json", return_value=fake) as post:
            forgecode.OpenAIChatProvider(cfg).request("s", [{"role": "user", "content": "latest"}], [], 1000, True)
        payload = post.call_args.args[2]
        self.assertIn({"type": "openrouter:web_search"}, payload["tools"])
        self.assertEqual(payload["reasoning"]["effort"], "low")

    def test_kimchi_uses_bearer_key_and_official_endpoint(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("kimchi")
        cfg.data["kimchi_api_key"] = "kimchi-secret"
        fake = {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}}
        with mock.patch.object(forgecode, "post_json", return_value=fake) as post:
            reply = forgecode.OpenAIChatProvider(cfg).request("s", [{"role": "user", "content": "hi"}], [])
        self.assertEqual(reply.text, "ok")
        self.assertEqual(post.call_args.args[0], "https://llm.kimchi.dev/openai/v1/chat/completions")
        self.assertEqual(post.call_args.args[1]["Authorization"], "Bearer kimchi-secret")

    def test_openai_responses_web_tool(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("openai")
        fake = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}], "usage": {}}
        with mock.patch.object(forgecode, "post_json", return_value=fake) as post:
            forgecode.OpenAIProvider(cfg).request("s", [], [], 1000, True)
        self.assertEqual(post.call_args.args[2]["tools"][0]["type"], "web_search")

    def test_custom_proxy_auto_detects_v1_models(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("custom")
        cfg.data["base_url"] = "http://proxy.test:4000"
        cfg.data["custom_api_key"] = "test-key"
        with mock.patch.object(forgecode, "get_json", side_effect=[forgecode.ApiError("404"), {"data": [{"id": "proxy-model"}]}]) as get:
            self.assertEqual(forgecode.fetch_models(cfg), ["proxy-model"])
        self.assertEqual(cfg.base_url(), "http://proxy.test:4000")
        self.assertEqual(cfg.data["last_model_endpoint"], "http://proxy.test:4000/v1/models")
        self.assertEqual(get.call_args_list[1].args[1]["Authorization"], "Bearer test-key")

    def test_custom_404_route_hint_recovers_test_without_manual_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "https://proxy.test",
                "model": "claude-sonnet-test",
                "custom_api_key": "test-key",
                "custom_auth_mode": "bearer",
                "custom_protocol": "openai",
                "custom_endpoint_path": "exact",
                "api_mode": "chat",
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            success = {"content": [{"type": "text", "text": "OK"}], "usage": {}}
            with mock.patch.object(forgecode, "post_json", side_effect=[
                forgecode.ApiError("API 404: Sadece /v1/messages desteklenmektedir."), success
            ]) as post:
                text, _, _ = agent.test_api()
            self.assertEqual(text, "OK")
            self.assertEqual(cfg.mode(), "anthropic")
            self.assertEqual(cfg.data["custom_endpoint_path"], "/v1/messages")
            self.assertEqual(post.call_args_list[0].args[0], "https://proxy.test")
            self.assertEqual(post.call_args_list[1].args[0], "https://proxy.test/v1/messages")

    def test_custom_non_json_root_auto_probes_claude_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "https://proxy.test",
                "model": "claude-sonnet-test",
                "custom_api_key": "test-key",
                "custom_auth_mode": "bearer",
                "custom_protocol": "anthropic",
                "custom_endpoint_path": "exact",
                "api_mode": "anthropic",
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            success = {"content": [{"type": "text", "text": "OK"}], "usage": {}}
            with mock.patch.object(forgecode, "post_json", side_effect=[
                forgecode.ApiError("API JSON olmayan yanıt döndürdü: 'welcome'"), success
            ]) as post:
                text, _, _ = agent.test_api()
            self.assertEqual(text, "OK")
            self.assertEqual(cfg.data["custom_endpoint_path"], "/v1/messages")
            self.assertEqual(post.call_args_list[0].args[0], "https://proxy.test")
            self.assertEqual(post.call_args_list[1].args[0], "https://proxy.test/v1/messages")

    def test_normal_chat_recovers_advertised_messages_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "https://proxy.test",
                "model": "claude-sonnet-test",
                "custom_api_key": "test-key",
                "custom_auth_mode": "bearer",
                "custom_protocol": "openai",
                "custom_endpoint_path": "exact",
                "api_mode": "chat",
                "auto_subagents": False,
                "streaming_enabled": False,
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            success = {"content": [{"type": "text", "text": "Merhaba"}], "usage": {}}
            with mock.patch.object(forgecode, "post_json", side_effect=[
                forgecode.ApiError("API 404: only /v1/messages is supported"), success
            ]) as post:
                answer = agent.ask("selam")
            self.assertEqual(answer, "Merhaba")
            self.assertEqual(post.call_count, 2)
            self.assertEqual(cfg.data["custom_protocol"], "anthropic")

    def test_custom_chat_auto_detects_x_api_key_auth(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("custom")
        cfg.data.update({
            "base_url": "https://proxy.test/v1",
            "model": "proxy-model",
            "custom_api_key": "test-key",
            "custom_auth_mode": "auto",
        })
        success = {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}}
        with mock.patch.object(forgecode, "post_json", side_effect=[forgecode.ApiError("API 401: invalid api key"), success]) as post:
            reply = forgecode.OpenAIChatProvider(cfg).request("s", [{"role": "user", "content": "hi"}], [])
        self.assertEqual(reply.text, "ok")
        self.assertIn("Authorization", post.call_args_list[0].args[1])
        self.assertEqual(post.call_args_list[1].args[1]["x-api-key"], "test-key")
        self.assertEqual(cfg.data["custom_auth_mode"], "x-api-key")

    def test_custom_unavailable_model_is_replaced_during_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "https://proxy.test/v1",
                "model": "3.5",
                "custom_api_key": "sk-test",
                "custom_auth_mode": "bearer",
                "retry_attempts": 1,
                "model_cache": {"custom": {"models": ["3.5", "opus-4.8", "sonnet-5"], "catalog": []}},
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            success = {"choices": [{"message": {"role": "assistant", "content": "OK"}}], "usage": {}}
            with mock.patch.object(forgecode, "post_json", side_effect=[forgecode.ApiError("API 503: 3.5 unavailable"), success]) as post:
                text, _, _ = agent.test_api()
            self.assertEqual(text, "OK")
            self.assertEqual(cfg.data["model"], "opus-4.8")
            self.assertEqual(post.call_count, 2)

    def test_normal_request_retries_after_custom_model_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "https://proxy.test/v1", "model": "3.5", "custom_api_key": "sk-test",
                "custom_auth_mode": "bearer", "auto_subagents": False, "retry_attempts": 1,
                "streaming_enabled": False,
                "model_cache": {"custom": {"models": ["3.5", "sonnet-5"], "catalog": []}},
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            probe = {"choices": [{"message": {"role": "assistant", "content": "OK"}}], "usage": {}}
            answer = {"choices": [{"message": {"role": "assistant", "content": "çalışıyor"}}], "usage": {}}
            with mock.patch.object(forgecode, "post_json", side_effect=[forgecode.ApiError("API 503: 3.5 unavailable"), probe, answer]) as post:
                result = agent.ask("selam")
            self.assertEqual(result, "çalışıyor")
            self.assertEqual(cfg.data["model"], "sonnet-5")
            self.assertEqual(post.call_count, 3)

    def test_simple_chat_falls_back_when_custom_tools_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "https://proxy.test/v1", "model": "chat-only", "custom_api_key": "sk-test",
                "custom_auth_mode": "bearer", "auto_subagents": False,
                "streaming_enabled": False,
                "model_cache": {"custom": {"models": ["chat-only"], "catalog": []}},
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            health = {"choices": [{"message": {"role": "assistant", "content": "OK"}}], "usage": {}}
            answer = {"choices": [{"message": {"role": "assistant", "content": "selam"}}], "usage": {}}
            with mock.patch.object(forgecode, "post_json", side_effect=[
                forgecode.ApiError("API 305: unavailable"), health,
                forgecode.ApiError("API 305: unavailable"), answer,
            ]) as post:
                result = agent.ask("selam")
            self.assertEqual(result, "selam")
            self.assertIn("chat-only", cfg.data["custom_no_tool_models"])
            self.assertEqual(post.call_count, 4)

    def test_api_305_is_reported_as_proxy_upstream_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "https://proxy.test/v1", "model": "model-a", "custom_api_key": "sk-test",
                "custom_auth_mode": "bearer",
                "model_cache": {"custom": {"models": ["model-a", "model-b"], "catalog": []}},
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            with mock.patch.object(forgecode, "post_json", side_effect=[
                forgecode.ApiError("API 305: unavailable"), forgecode.ApiError("API 305: unavailable")
            ]):
                with self.assertRaisesRegex(forgecode.ApiError, "proxy yönlendirmesi"):
                    agent.test_api()

    def test_305_recovery_learns_real_models_from_chinese_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "https://proxy.test/v1", "model": "claude-sonnet-5", "custom_api_key": "sk-test",
                "custom_auth_mode": "bearer", "custom_protocol": "openai",
                "model_cache": {"custom": {"models": ["claude-opus-4.8", "claude-sonnet-5"], "catalog": []}},
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            chinese = forgecode.ApiError('API 400: 你请求的模型 "claude-opus-4.8" 暂不支持。可用模型：claude-opus-4-7 / claude-haiku-4-5-20251001 / claude-sonnet-4-6 / claude-sonnet-5')
            success = {"choices": [{"message": {"role": "assistant", "content": "OK"}}], "usage": {}}
            with mock.patch.object(forgecode, "post_json", side_effect=[forgecode.ApiError("API 305: unavailable"), chinese, success]) as post:
                text, _, _ = agent.test_api()
            self.assertEqual(text, "OK")
            self.assertEqual(cfg.data["model"], "claude-opus-4-7")
            self.assertIn("claude-opus-4.8", cfg.data["custom_rejected_models"])
            self.assertIn("claude-sonnet-4-6", cfg.data["custom_model_hints"])
            self.assertEqual(post.call_count, 3)


class CommandAssistTests(unittest.TestCase):
    def test_explanatory_nouns_do_not_trigger_build_repair_requests(self):
        self.assertFalse(forgecode.Agent._requires_artifacts("Silme nedir, güvenli yöntemleri açıkla"))
        self.assertFalse(forgecode.Agent._requires_artifacts("Website nedir?"))
        self.assertFalse(forgecode.Agent._requires_artifacts("Bir uygulama hakkında bilgi ver"))
        self.assertFalse(forgecode.Agent._requires_artifacts("Do not edit any files"))
        self.assertTrue(forgecode.Agent._requires_artifacts("Gelişmiş bir web sitesi yap"))
        self.assertTrue(forgecode.Agent._requires_artifacts("Bu hatayı düzeltir misin?"))
        self.assertTrue(forgecode.Agent._requires_artifacts("Bu dosyayı silmeni istiyorum"))

    def test_explanation_gets_exactly_one_main_api_request_even_in_build_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"work_mode": "build", "auto_subagents": False, "power_mode": "off"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            provider = mock.MagicMock()
            provider.request.return_value = forgecode.ModelReply(
                "Silme, bir dosyanın kaldırılmasıdır.", [], forgecode.Usage(),
                {"role": "assistant", "content": "Silme, bir dosyanın kaldırılmasıdır."},
            )
            agent.provider = provider
            answer = agent.ask("Silme nedir, güvenli yöntemleri açıkla")
            self.assertIn("Silme", answer)
            self.assertEqual(provider.request.call_count, 1)
            self.assertEqual(agent.tools.changed_since({}), [])

    def test_dash_prefix_is_normalized(self):
        self.assertEqual(forgecode.normalize_command_text("/-g"), "/g")

    def test_spaced_slash_goal_is_normalized(self):
        self.assertEqual(forgecode.normalize_command_text("/ goal demo sitesi oluştur"), "/goal demo sitesi oluştur")

    def test_goal_is_first_ghost_suggestion(self):
        self.assertEqual(forgecode.command_suggestion("/g"), "/goal")

    def test_exact_and_plain_text_have_no_suggestion(self):
        self.assertEqual(forgecode.command_suggestion("/goal"), "")
        self.assertEqual(forgecode.command_suggestion("hello"), "")

    def test_activity_keeps_only_last_four_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            for number in range(6):
                agent._emit_activity(f"step-{number}")
            self.assertEqual(len(agent.activity_lines), 4)
            self.assertIn("step-2", agent.activity_lines[0])
            self.assertIn("step-5", agent.activity_lines[-1])

    def test_subagent_has_shorter_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"timeout_seconds": 120, "subagent_timeout_seconds": 17})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            seen = {}

            def fake_ask(child, *args, **kwargs):
                seen["timeout"] = child.cfg.data["timeout_seconds"]
                return "ok"

            with mock.patch.object(forgecode.Agent, "ask", fake_ask):
                report = agent.delegate("plan", "inspect")
            self.assertEqual(seen["timeout"], 17)
            self.assertIn("SUBAGENT (plan)", report)

    def test_legacy_silent_timeout_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            (home / "config.json").write_text('{"timeout_seconds": 120}', encoding="utf-8")
            cfg = forgecode.Config(home)
            self.assertEqual(cfg.data["timeout_seconds"], 100)
            self.assertEqual(cfg.data["config_version"], 18)
            self.assertEqual(cfg.data["max_agent_steps"], 0)
            self.assertEqual(cfg.data["temperature"], 1.0)

    def test_prompt_and_memory_commands_persist_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            goals = forgecode.GoalStore(root)
            output = io.StringIO()
            with mock.patch.object(sys, "stdout", output):
                forgecode.handle_command("/prompt Run focused tests before completion", agent, cfg, goals)
                forgecode.handle_command("/remember Keep the CLI backwards compatible", agent, cfg, goals)
                forgecode.handle_command("/memory", agent, cfg, goals)
            self.assertEqual(cfg.data["startup_prompt"], "Run focused tests before completion")
            self.assertIn("backwards compatible", agent.session_store.memories()[0]["text"])
            self.assertIn("Kalıcı proje hafızası", output.getvalue())

    def test_window_launcher_passes_same_project_and_new_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            process = mock.MagicMock(pid=4321)
            with mock.patch.object(forgecode.subprocess, "Popen", return_value=process) as popen:
                self.assertEqual(forgecode.launch_forgecode_window(agent, "backend"), 4321)
            command = popen.call_args.args[0]
            self.assertIn(str(root), command)
            self.assertEqual(command[-2:], ["--session", "backend"])

    def test_role_profile_routes_subagent_to_another_provider_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["connection_profiles"] = {
                "fast": {"provider": "groq", "model": "default-model", "api_mode": "chat", "base_url": "https://api.groq.com/openai/v1"}
            }
            cfg.data["agent_profiles"] = {"backend": {"profile": "fast", "model": "backend-model"}}
            parent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            seen = {}

            def fake_ask(child, *args, **kwargs):
                seen.update({"provider": child.cfg.data["provider"], "model": child.cfg.data["model"], "read_only": child.read_only})
                return "backend report"

            with mock.patch.object(forgecode.Agent, "ask", fake_ask):
                report = parent.delegate("backend", "inspect API")
            self.assertEqual(seen, {"provider": "groq", "model": "backend-model", "read_only": True})
            self.assertIn("groq/backend-model", report)

    def test_team_reports_keep_configured_role_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            with mock.patch.object(agent, "delegate", side_effect=lambda role, task, output_cap=1200: f"report-{role}"):
                reports = agent.run_team("build", ["design", "backend", "review"])
            self.assertEqual(reports, ["report-design", "report-backend", "report-review"])

    def test_f8_temperature_cycle_wraps(self):
        self.assertEqual(forgecode.next_temperature(1.0), 0.0)
        self.assertEqual(forgecode.next_temperature(0.2), 0.5)

    def test_api_endpoint_does_not_duplicate_v1(self):
        self.assertEqual(
            forgecode.api_endpoint("http://proxy.test/v1", "/v1/messages"),
            "http://proxy.test/v1/messages",
        )

    def test_base_url_normalization_accepts_full_api_endpoints(self):
        self.assertEqual(forgecode.normalize_api_base_url("https://x.test/v1/messages"), "https://x.test/v1")
        self.assertEqual(forgecode.normalize_api_base_url("https://x.test/v1/chat/completions"), "https://x.test/v1")
        self.assertEqual(forgecode.normalize_api_base_url("https://x.test/v1/models"), "https://x.test/v1")

    def test_custom_route_can_be_auto_exact_or_user_selected(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("custom")
        cfg.set_value("base_url", "http://proxy.test:40008")
        cfg.data.update({"api_mode": "anthropic", "custom_protocol": "anthropic"})
        cfg.set_value("custom_endpoint_path", "auto")
        self.assertEqual(forgecode.request_endpoint(cfg, "/v1/messages"), "http://proxy.test:40008/v1/messages")
        cfg.set_value("custom_endpoint_path", "exact")
        self.assertEqual(forgecode.request_endpoint(cfg, "/v1/messages"), "http://proxy.test:40008")
        cfg.set_value("custom_endpoint_path", "/claude/messages")
        self.assertEqual(forgecode.request_endpoint(cfg, "/v1/messages"), "http://proxy.test:40008/claude/messages")

    def test_custom_connection_url_needs_no_separate_route_command(self):
        self.assertEqual(forgecode.inferred_custom_route("https://proxy.test"), "exact")
        self.assertEqual(
            forgecode.inferred_custom_route("https://proxy.test/v1/messages"),
            "https://proxy.test/v1/messages",
        )
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("custom")
        cfg.set_value("base_url", "https://proxy.test/v1/messages")
        self.assertEqual(cfg.base_url(), "https://proxy.test/v1")
        self.assertEqual(cfg.data["custom_endpoint_path"], "https://proxy.test/v1/messages")

    def test_custom_auto_protocol_recognizes_claude_model(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("custom")
        cfg.data.update({"model": "claude-sonnet-test", "custom_protocol": "auto", "api_mode": "chat"})
        self.assertEqual(cfg.mode(), "anthropic")
        self.assertIsInstance(forgecode.make_provider(cfg), forgecode.AnthropicProvider)

    def test_endpoint_hint_is_read_from_proxy_error(self):
        self.assertEqual(
            forgecode.endpoint_hint_from_error("API 404: Sadece /v1/messages desteklenmektedir."),
            ("anthropic", "/v1/messages"),
        )

    def test_explicit_anthropic_base_url_wins_over_environment(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"ANTHROPIC_BASE_URL": "https://wrong.test"}
        ):
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.select_provider("anthropic")
            cfg.set_value("base_url", "https://chosen.test/v1")
            self.assertEqual(cfg.base_url(), "https://chosen.test/v1")
            self.assertEqual(forgecode.endpoint_plan(cfg)["request"], "https://chosen.test/v1/messages")

    def test_connection_profile_excludes_secret_and_restores_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.select_provider("custom")
            cfg.set_value("base_url", "https://proxy.test")
            cfg.set_value("custom_endpoint_path", "/api/messages")
            cfg.set_value("custom_api_key", "secret")
            profile = forgecode.save_connection_profile(cfg, "work")
            self.assertNotIn("custom_api_key", profile)
            cfg.select_provider("openai")
            forgecode.use_connection_profile(cfg, "work")
            self.assertEqual(cfg.data["provider"], "custom")
            self.assertEqual(cfg.data["custom_endpoint_path"], "/api/messages")
            self.assertEqual(cfg.base_url_source(), "profile")

    def test_transient_api_errors_retry_but_bad_requests_do_not(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.data.update({"retry_attempts": 2, "retry_backoff_seconds": 0})
        with mock.patch.object(
            forgecode, "post_json", side_effect=[forgecode.ApiError("API 503: busy"), {"ok": True}]
        ) as post:
            result = forgecode.post_json_with_retry(cfg, "https://api.test", {}, {}, 5)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(post.call_count, 2)
        with mock.patch.object(forgecode, "post_json", side_effect=forgecode.ApiError("API 400: invalid")) as post:
            with self.assertRaises(forgecode.ApiError):
                forgecode.post_json_with_retry(cfg, "https://api.test", {}, {}, 5)
        self.assertEqual(post.call_count, 1)

    def test_claude_models_prefer_native_anthropic_protocol(self):
        self.assertEqual(forgecode.preferred_custom_protocol("claude-sonnet-5"), "anthropic")
        self.assertEqual(forgecode.preferred_custom_protocol("CLAUDE-opus-test"), "anthropic")
        self.assertEqual(forgecode.preferred_custom_protocol("gpt-compatible"), "openai")

    def test_proxy_compat_tool_names_are_safely_normalized(self):
        self.assertEqual(forgecode.normalize_tool_name("CompatListFilesf027e6"), "list_files")
        self.assertEqual(forgecode.normalize_tool_name("CompatWriteFiles588b85"), "write_files")
        self.assertEqual(forgecode.normalize_tool_name("CompatWriteFile50e90c"), "write_file")
        self.assertEqual(forgecode.normalize_tool_name("CompatRunCommandb080f3"), "run_command")
        self.assertEqual(forgecode.normalize_tool_name("CompatSearchd1a346"), "search")
        self.assertEqual(forgecode.normalize_tool_name("CompatReadFile82b939"), "read_file")
        self.assertEqual(forgecode.normalize_tool_name("CompatDeleteEverythingabcdef"), "CompatDeleteEverythingabcdef")

    def test_claude_code_native_tool_names_are_normalized(self):
        expected = {
            "Bash": "run_command", "Read": "read_file", "Write": "write_file",
            "Edit": "replace_text", "Glob": "list_files", "Grep": "search", "Task": "delegate_task",
        }
        for native, local in expected.items():
            self.assertEqual(forgecode.normalize_tool_name(native), local)

    def test_claude_code_native_arguments_are_translated_and_filtered(self):
        self.assertEqual(
            forgecode.normalize_tool_arguments("read_file", {"file_path": "index.html", "offset": 5, "limit": 10, "pages": "1"}),
            {"path": "index.html", "start_line": 5, "end_line": 14},
        )
        self.assertEqual(
            forgecode.normalize_tool_arguments("write_file", {"file_path": "a.txt", "content": "ok", "extra": 1}),
            {"path": "a.txt", "content": "ok"},
        )
        self.assertEqual(
            forgecode.normalize_tool_arguments("run_command", {"command": "Get-ChildItem", "timeout": 30000, "description": "list"}),
            {"command": "Get-ChildItem", "timeout_seconds": 30},
        )

    def test_native_read_alias_executes_with_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "note.txt").write_text("one\ntwo\nthree", encoding="utf-8")
            cfg = forgecode.Config(root / "home")
            tools = forgecode.WorkspaceTools(root, cfg, lambda _: False)
            result = tools.execute("Read", {"file_path": "note.txt", "offset": 2, "limit": 1})
            self.assertIn("two", result)
            self.assertNotIn("three", result)

    def test_proxy_compat_write_file_reaches_real_workspace_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["autopilot_mode"] = True
            tools = forgecode.WorkspaceTools(root, cfg, lambda _: False)
            result = tools.execute("CompatWriteFile50e90c", {"path": "demo/index.html", "content": "<h1>OK</h1>"})
            self.assertTrue(result.startswith("OK:"))
            self.assertEqual((root / "demo/index.html").read_text(encoding="utf-8"), "<h1>OK</h1>")

    def test_anthropic_proxy_arguments_accept_alternate_shapes(self):
        self.assertEqual(forgecode.compatible_tool_arguments({"input": {"path": "a"}}), {"path": "a"})
        self.assertEqual(forgecode.compatible_tool_arguments({"arguments": '{"path":"b"}'}), {"path": "b"})
        self.assertEqual(
            forgecode.compatible_tool_arguments({"function": {"parameters": {"query": "x"}}}),
            {"query": "x"},
        )

    def test_custom_anthropic_proxy_uses_reliable_single_file_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({"api_mode": "anthropic", "custom_protocol": "anthropic", "efficiency_mode": "balanced"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            names = {tool["name"] for tool in agent._effective_tools("gelişmiş web sitesi oluştur")}
            self.assertIn("write_file", names)
            self.assertNotIn("write_files", names)
            self.assertIn("write_files is unavailable", agent.system())
            self.assertIn("Use RELATIVE file paths only", agent.system())
            normal_cfg = forgecode.Config(root / "other-home")
            normal_agent = forgecode.Agent(root, normal_cfg, forgecode.GoalStore(root), lambda _: True)
            self.assertLess(len(agent.system()), len(normal_agent.system()))

    def test_custom_claude_design_word_enables_mutating_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({"api_mode": "anthropic", "custom_protocol": "anthropic", "efficiency_mode": "balanced"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            names = {tool["name"] for tool in agent._effective_tools("Şık bir restoran sitesi tasarla ve hazırla")}
            self.assertIn("write_file", names)
            self.assertIn("replace_text", names)
            self.assertIn("run_command", names)
            self.assertNotIn("write_files", names)
            neutral_names = {tool["name"] for tool in agent._effective_tools("selam")}
            self.assertIn("write_file", neutral_names)
            self.assertIn("run_command", neutral_names)

    def test_max_efficiency_uses_same_build_intent_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["efficiency_mode"] = "max"
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            names = {tool["name"] for tool in agent._effective_tools("Yeni paneli tasarla")}
            self.assertIn("write_file", names)
            self.assertIn("write_files", names)
            self.assertIn("run_command", names)
            neutral_names = {tool["name"] for tool in agent._effective_tools("yalnızca kısa bir istek")}
            self.assertIn("write_file", neutral_names)
            self.assertIn("run_command", neutral_names)

    def test_windows_context_warns_against_unix_only_commands(self):
        if os.name == "nt":
            context = forgecode.project_context(pathlib.Path(tempfile.mkdtemp()), "max")
            self.assertIn("Windows PowerShell/CMD-compatible", context)

    def test_claude_bash_inspection_command_is_translated_for_windows(self):
        translated = forgecode.windows_shell_command('ls -la; echo "---"; cat package.json 2>/dev/null')
        self.assertIn("Get-ChildItem -Force", translated)
        self.assertIn("Get-Content -LiteralPath 'package.json' -Encoding UTF8", translated)
        self.assertIn("2>$null", translated)
        self.assertNotIn("ls -la", translated)

    def test_claude_cat_tail_pipeline_is_translated_for_powershell(self):
        translated = forgecode.windows_shell_command("cat index.html | tail -200")
        self.assertEqual(
            translated,
            "Get-Content -LiteralPath 'index.html' -Encoding UTF8 | Select-Object -Last 200",
        )
        self.assertNotIn("cat ", translated)
        self.assertNotIn("tail ", translated)

    def test_powershell_adapter_quotes_spaced_paths_and_preserves_chain_failure(self):
        translated = forgecode.windows_shell_command('cd force test zone && mkdir -p "assets css"')
        self.assertIn("Set-Location -LiteralPath 'force test zone'", translated)
        self.assertIn("if (-not $?) { exit 1 }", translated)
        self.assertIn("New-Item -ItemType Directory -Force -LiteralPath 'assets css'", translated)
        quoted = forgecode.windows_shell_command('Write-Output "a && b"')
        self.assertEqual(quoted, 'Write-Output "a && b"')

    def test_command_output_decoder_survives_cp1254_undefined_byte_and_none(self):
        decoded = forgecode.decode_subprocess_output(b"before\x8fafter")
        self.assertIn("before", decoded)
        self.assertIn("after", decoded)
        self.assertEqual(forgecode.decode_subprocess_output(None), "")

    def test_anthropic_base_url_environment_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"ANTHROPIC_BASE_URL": "http://proxy.test:40008", "ANTHROPIC_API_KEY": "test-key"},
        ):
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.select_provider("anthropic")
            self.assertEqual(cfg.base_url(), "http://proxy.test:40008")
            self.assertEqual(cfg.key(), "test-key")

    def test_multiple_command_suggestions_are_ranked(self):
        suggestions = forgecode.command_suggestions("/h")
        self.assertGreaterEqual(len(suggestions), 2)
        self.assertIn("/help", suggestions)
        self.assertIn("/history", suggestions)

    def test_long_prompt_uses_non_wrapping_horizontal_view(self):
        text = "çok uzun bir kullanıcı promptu " * 20
        view, cursor = forgecode.horizontal_input_view(text, len(text), 32)
        self.assertEqual(len(view), 32)
        self.assertTrue(view.startswith("‹"))
        self.assertLessEqual(cursor, len(view))
        middle_view, middle_cursor = forgecode.horizontal_input_view(text, 75, 24)
        self.assertEqual(len(middle_view), 24)
        self.assertEqual(middle_view[0], "‹")
        self.assertEqual(middle_view[-1], "›")
        self.assertGreaterEqual(middle_cursor, 1)

    def test_high_thinking_new_website_requires_multifile_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["thinking_mode"] = "high"
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            self.assertTrue(agent._requires_multifile_web("Gelişmiş restoran web sitesi oluştur", {}))
            self.assertFalse(agent._requires_multifile_web("Tek HTML dosyasında web sitesi oluştur", {}))

    def test_plan_mode_exposes_only_read_only_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.set_value("work_mode", "plan")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            names = {tool["name"] for tool in agent._effective_tools("site oluştur")}
            self.assertEqual(names, {"list_files", "read_file", "search", "get_diagnostics", "set_forgecode_setting", "delegate_task"})

    def test_status_footer_shows_modes_and_fixed_session_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"work_mode": "build", "thinking_mode": "high", "web_project_mode": "multi", "efficiency_mode": "max"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent.session_cost_usd = 0.012345
            footer = forgecode.input_status_line(agent, cfg)
            controls = forgecode.control_bar_line(cfg)
            self.assertIn("$0.012345", footer)
            self.assertIn("MOD:build", controls)
            self.assertIn("DÜŞÜN:high", controls)
            self.assertIn("KALİTE:multi", controls)
            self.assertIn("VERİM:max", controls)
            self.assertIn("TEMP:1", controls)
            self.assertNotIn("STREAM", footer + controls)
            self.assertIn("main", footer)

    def test_autopilot_writes_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["autopilot_mode"] = True
            confirmations = []
            tools = forgecode.WorkspaceTools(root, cfg, lambda question: confirmations.append(question) or False)
            result = tools.tool_write_file("auto.txt", "done")
            self.assertIn("OK", result)
            self.assertEqual(confirmations, [])
            self.assertEqual((root / "auto.txt").read_text(encoding="utf-8"), "done")

    def test_autopilot_command_selects_smart_full_and_off_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            goals = forgecode.GoalStore(root)
            with mock.patch.object(sys, "stdout", io.StringIO()):
                forgecode.handle_command("/autopilot smart", agent, cfg, goals)
                self.assertEqual(forgecode.autopilot_state(cfg), "akıllı")
                self.assertTrue(cfg.data["smart_autopilot_mode"])
                self.assertFalse(cfg.data["autopilot_mode"])
                forgecode.handle_command("/autopilot on", agent, cfg, goals)
                self.assertEqual(forgecode.autopilot_state(cfg), "tam")
                self.assertTrue(cfg.data["autopilot_mode"])
                self.assertFalse(cfg.data["smart_autopilot_mode"])
                forgecode.handle_command("/autopilot off", agent, cfg, goals)
                self.assertEqual(forgecode.autopilot_state(cfg), "kapalı")

    def test_request_cost_is_locked_when_price_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"input_price_per_million": 1.0, "output_price_per_million": 2.0, "auto_subagents": False})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            provider = mock.MagicMock()
            provider.request.return_value = forgecode.ModelReply("ok", [], forgecode.Usage(1_000_000, 1_000_000, 0, 1), [])
            agent.provider = provider
            agent.ask("selam")
            self.assertEqual(agent.session_cost_usd, 3.0)
            cfg.data.update({"input_price_per_million": 9.0, "output_price_per_million": 9.0})
            self.assertIn("$3.000000", forgecode.input_status_line(agent, cfg))

    def test_read_only_subagent_has_no_mutating_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False, read_only=True, role="review")
            names = {tool["name"] for tool in agent._effective_tools("fix everything")}
            self.assertEqual(names, {"list_files", "read_file", "search"})

    def test_proxy_cannot_force_bash_into_read_only_subagent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            child = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False, read_only=True, role="plan")
            provider = mock.MagicMock()
            provider.request.side_effect = [
                forgecode.ModelReply("", [{"id": "bash1", "name": "Bash", "arguments": {"command": "echo forbidden"}}], forgecode.Usage(), []),
                forgecode.ModelReply("Güvenli plan tamamlandı", [], forgecode.Usage(), []),
            ]
            child.provider = provider
            with mock.patch.object(forgecode.subprocess, "run") as run:
                answer = child.ask("Projeyi salt okunur incele", step_cap=2)
            run.assert_not_called()
            self.assertIn("Güvenli plan", answer)
            second_messages = provider.request.call_args_list[1].args[1]
            self.assertIn("Bu modda araç kullanılamaz: run_command", str(second_messages))

    def test_max_context_is_smaller(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "README.md").write_text("x" * 20000)
            self.assertLess(len(forgecode.project_context(root, "max")), len(forgecode.project_context(root, "off")))


class DynamicOrchestratorTests(unittest.TestCase):
    def test_plan_parser_accepts_fenced_json_aliases_and_enforces_three_unique_roles(self):
        raw = """Here is the plan:\n```json
        {"delegations":[
          {"role":"ux","task":"Develop visual and accessibility ideas"},
          {"role":"research","task":"Inspect project evidence"},
          {"role":"code-review","task":"Find compatibility risks"},
          {"role":"test","task":"This fourth task must be ignored"},
          {"role":"design","task":"Duplicate normalized role"}
        ]}
        ```"""
        plan = forgecode.parse_delegation_plan(raw, 3)
        self.assertEqual([item["role"] for item in plan], ["design", "research", "review"])
        self.assertEqual(len(plan), 3)
        self.assertEqual(forgecode.parse_delegation_plan(raw, 0), [])

    def test_active_ai_selects_roles_and_focused_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "app.py").write_text("print('ok')", encoding="utf-8")
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            provider = mock.MagicMock()
            provider.request.return_value = forgecode.ModelReply(
                '{"delegations":[{"role":"research","task":"Inspect requirements"},{"role":"design","task":"Create UX direction"},{"role":"review","task":"Review current code"}]}',
                [], forgecode.Usage(30, 12, 0, 1), [],
            )
            agent.provider = provider
            plan = agent.plan_delegations("Build a professional application and use subagents")
            self.assertEqual([item["role"] for item in plan], ["research", "design", "review"])
            self.assertEqual(agent.session_usage.input_tokens, 30)
            call = provider.request.call_args.args
            self.assertEqual(call[2], [])
            self.assertEqual(call[3], 420)
            self.assertIn("PROJECT FILE MAP", call[1][0]["content"])

    def test_ask_runs_live_ai_plan_then_injects_parallel_reports_into_main_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            planner = forgecode.ModelReply(
                '{"delegations":[{"role":"research","task":"Gather evidence"},{"role":"design","task":"Develop UX"}]}',
                [], forgecode.Usage(8, 4, 0, 1), [],
            )
            no_tool = forgecode.ModelReply("done", [], forgecode.Usage(5, 2, 0, 1), [])
            provider = mock.MagicMock()
            provider.request.side_effect = [planner, no_tool, no_tool, no_tool]
            agent.provider = provider
            with mock.patch.object(agent, "run_delegations", return_value=["evidence report", "design report"]) as run:
                answer = agent.ask("Profesyonel ve gelişmiş bir restoran web sitesi oluştur")
            self.assertIn("tamamlanmadı", answer)
            executed = run.call_args.args[0]
            self.assertEqual([item["role"] for item in executed], ["research", "design"])
            main_messages = provider.request.call_args_list[1].args[1]
            self.assertIn("AI-CHOSEN PARALLEL SUBAGENT REPORTS", str(main_messages))
            self.assertEqual(provider.request.call_count, 4)

    def test_explicit_subagent_request_gets_safe_fallback_if_planner_returns_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            provider = mock.MagicMock()
            provider.request.return_value = forgecode.ModelReply("I would use some agents", [], forgecode.Usage(), [])
            agent.provider = provider
            plan = agent.plan_delegations("Subagent kullanabilirsin; gelişmiş bir restoran sitesi yap")
            self.assertEqual([item["role"] for item in plan], ["research", "design", "review"])

    def test_distinct_assignments_run_in_parallel_but_reports_keep_plan_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            assignments = [
                {"role": "research", "task": "one"},
                {"role": "design", "task": "two"},
                {"role": "review", "task": "three"},
            ]
            with mock.patch.object(agent, "delegate", side_effect=lambda role, task, output_cap=1200: f"{role}:{task}"):
                reports = agent.run_delegations(assignments)
            self.assertEqual(reports, ["research:one", "design:two", "review:three"])

    def test_research_specialist_forces_web_only_when_web_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["web_search_mode"] = "auto"
            parent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            seen = {}

            def fake_ask(child, *args, **kwargs):
                seen[child.role] = kwargs.get("force_web")
                return "report"

            with mock.patch.object(forgecode.Agent, "ask", fake_ask):
                parent.delegate("research", "Find current evidence")
                parent.delegate("design", "Create UX ideas")
            self.assertTrue(seen["research"])
            self.assertFalse(seen["design"])

    def test_simple_chat_skips_orchestrator_but_large_audit_uses_it(self):
        self.assertFalse(forgecode.Agent._should_orchestrate("selam"))
        self.assertTrue(forgecode.Agent._should_orchestrate("Tüm projeyi güvenlik, mimari ve performans sorunları açısından ayrıntılı incele ve kanıtları listele"))


class SelfDiagnosticsTests(unittest.TestCase):
    def test_runtime_error_persists_and_is_visible_in_system_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent._current_prompt = "önceki istek"
            agent.record_runtime_error("api_error", "API 429: Too Many Requests", {"source": "test"})
            restarted = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            self.assertIn("API 429", restarted.system())
            self.assertIn("api_error", restarted.tools.tool_get_diagnostics())

    def test_ai_can_change_only_allowlisted_non_secret_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            tools = forgecode.WorkspaceTools(root, cfg, lambda _: False)
            result = tools.tool_set_forgecode_setting("efficiency_mode", "max", "Token tüketimini azalt")
            self.assertIn("önce", result)
            self.assertEqual(cfg.data["efficiency_mode"], "max")
            with self.assertRaisesRegex(ValueError, "değiştiremez"):
                tools.tool_set_forgecode_setting("custom_api_key", "secret", "bağlan")
            with self.assertRaisesRegex(ValueError, "değiştiremez"):
                tools.tool_set_forgecode_setting("base_url", "https://evil.test", "rota")

    def test_diagnostics_never_exposes_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            secret = "sk-diagnostic-secret-123456789"
            cfg.data["anthropic_api_key"] = secret
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            report = agent.diagnostics_report()
            self.assertNotIn(secret, report)
            self.assertNotIn("anthropic_api_key", report)

    def test_error_question_uses_diagnostics_tool_then_explains_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"auto_subagents": False, "power_mode": "off"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent.record_runtime_error("api_error", "API 429: Too Many Requests", {"source": "request"})
            provider = mock.MagicMock()
            provider.request.side_effect = [
                forgecode.ModelReply(
                    "", [{"id": "diag", "name": "get_diagnostics", "arguments": {}}], forgecode.Usage(),
                    [{"type": "tool_use", "id": "diag", "name": "get_diagnostics", "input": {}}],
                ),
                forgecode.ModelReply(
                    "429 hatası sağlayıcının hız sınırından geldi.", [], forgecode.Usage(),
                    [{"type": "text", "text": "429 hatası sağlayıcının hız sınırından geldi."}],
                ),
            ]
            agent.provider = provider
            answer = agent.ask("Az önceki hata neden oldu?")
            self.assertIn("429", answer)
            self.assertEqual(provider.request.call_count, 2)
            sent = json.dumps(provider.request.call_args_list[1].args[1], ensure_ascii=False)
            self.assertIn("Too Many Requests", sent)

    def test_optimization_changes_setting_without_project_file_repair_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"auto_subagents": False, "power_mode": "off", "efficiency_mode": "balanced"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            provider = mock.MagicMock()
            provider.request.side_effect = [
                forgecode.ModelReply(
                    "", [{"id": "set", "name": "set_forgecode_setting", "arguments": {"name": "efficiency_mode", "value": "max", "reason": "Daha az token"}}], forgecode.Usage(),
                    [{"type": "tool_use", "id": "set", "name": "set_forgecode_setting", "input": {}}],
                ),
                forgecode.ModelReply(
                    "Verimlilik balanced → max yapıldı.", [], forgecode.Usage(),
                    [{"type": "text", "text": "Verimlilik balanced → max yapıldı."}],
                ),
            ]
            agent.provider = provider
            answer = agent.ask("ForgeCode ayarlarını düzelt ve az token için optimize et")
            self.assertEqual(cfg.data["efficiency_mode"], "max")
            self.assertIn("balanced", answer)
            self.assertEqual(provider.request.call_count, 2)


class OutcomeGuardTests(unittest.TestCase):
    class NoToolProvider:
        def __init__(self):
            self.calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            return forgecode.ModelReply("Tamamlandı.", [], forgecode.Usage(10, 2, 0, 1), [])

    def test_build_cannot_claim_success_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"auto_subagents": False, "efficiency_mode": "max"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            provider = self.NoToolProvider()
            agent.provider = provider
            answer = agent.ask("Gelişmiş bir restoran web sitesi yap")
            self.assertIn("tamamlanmadı", answer)
            self.assertEqual(provider.calls, 3)
            self.assertEqual(list(root.glob("*.html")), [])

    def test_real_written_file_is_reported_as_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"auto_subagents": False, "auto_approve_writes": True, "power_mode": "off"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            replies = [
                forgecode.ModelReply("", [{"id": "t1", "name": "write_file", "arguments": {"path": "site/index.html", "content": "<h1>Restaurant</h1>"}}], forgecode.Usage(), [{"type": "tool_use", "id": "t1", "name": "write_file", "input": {"path": "site/index.html", "content": "<h1>Restaurant</h1>"}}]),
                forgecode.ModelReply("Site hazır.", [], forgecode.Usage(), [{"type": "text", "text": "Site hazır."}]),
            ]
            provider = mock.MagicMock()
            provider.request.side_effect = replies
            agent.provider = provider
            answer = agent.ask("Bir restoran web sitesi oluştur")
            self.assertTrue((root / "site/index.html").is_file())
            self.assertIn("site/index.html", answer)

    def test_bulk_write_uses_one_approval_for_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            approvals = []
            tools = forgecode.WorkspaceTools(root, cfg, lambda question: approvals.append(question) or True)
            result = tools.tool_write_files([
                {"path": "site/index.html", "content": "<link rel='stylesheet' href='assets/css/styles.css'>"},
                {"path": "site/assets/css/styles.css", "content": "body{margin:0}"},
                {"path": "site/assets/js/main.js", "content": "console.log('ready')"},
            ])
            self.assertEqual(len(approvals), 1)
            self.assertIn("Toplu yazma tamamlandı", result)
            self.assertTrue((root / "site/assets/js/main.js").is_file())

    def test_rejected_write_is_reported_as_error_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            tools = forgecode.WorkspaceTools(root, cfg, lambda _: False)
            result = tools.tool_write_file("blocked.txt", "must not exist")
            self.assertTrue(result.startswith("ERROR:"))
            self.assertFalse((root / "blocked.txt").exists())

    def test_truncated_write_call_recovers_with_full_budget_and_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("openrouter")
            cfg.data.update({
                "auto_subagents": False,
                "auto_approve_writes": True,
                "efficiency_mode": "max",
                "max_tokens": 8192,
                "timeout_seconds": 30,
                "streaming_enabled": True,
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            provider = mock.MagicMock()
            provider.request.side_effect = [
                forgecode.ModelReply(
                    "", [{"id": "cut", "name": "write_file", "arguments": {}, "parse_error": "tool arguments were cut off"}],
                    forgecode.Usage(), {"role": "assistant", "content": None, "tool_calls": [{"id": "cut", "type": "function", "function": {"name": "write_file", "arguments": "{}"}}]}, "length",
                ),
                forgecode.ModelReply(
                    "", [{"id": "write", "name": "write_file", "arguments": {"path": "created.txt", "content": "complete"}}],
                    forgecode.Usage(), {"role": "assistant", "content": None, "tool_calls": [{"id": "write", "type": "function", "function": {"name": "write_file", "arguments": "{\"path\":\"created.txt\",\"content\":\"complete\"}"}}]},
                ),
                forgecode.ModelReply("Created and verified.", [], forgecode.Usage(), {"role": "assistant", "content": "Created and verified."}),
            ]
            agent.provider = provider
            answer = agent.ask("Create created.txt with complete content")
            self.assertEqual((root / "created.txt").read_text(encoding="utf-8"), "complete")
            self.assertIn("created.txt", answer)
            self.assertEqual(provider.request.call_args_list[0].args[3], 4096)
            self.assertEqual(provider.request.call_args_list[1].args[3], 8192)
            self.assertTrue(callable(provider.request.call_args_list[0].args[5]))
            recovery_messages = json.dumps(provider.request.call_args_list[1].args[1], ensure_ascii=False)
            self.assertIn("Eksik/kesilmiş write_file", recovery_messages)

    def test_high_thinking_rejects_single_html_and_completes_multifile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"thinking_mode": "high", "auto_subagents": False, "auto_approve_writes": True})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            replies = [
                forgecode.ModelReply("", [{"id": "a", "name": "write_file", "arguments": {"path": "site/index.html", "content": "<link rel='stylesheet' href='assets/css/styles.css'><script src='assets/js/main.js'></script>"}}], forgecode.Usage(), [{"type": "tool_use", "id": "a", "name": "write_file", "input": {}}]),
                forgecode.ModelReply("Bitti", [], forgecode.Usage(), [{"type": "text", "text": "Bitti"}]),
                forgecode.ModelReply("", [{"id": "b", "name": "write_files", "arguments": {"files": [
                    {"path": "site/assets/css/styles.css", "content": ":root{--brand:#a00}body{margin:0}"},
                    {"path": "site/assets/js/main.js", "content": "document.documentElement.classList.add('ready')"},
                ]}}], forgecode.Usage(), [{"type": "tool_use", "id": "b", "name": "write_files", "input": {}}]),
                forgecode.ModelReply("Çoklu site hazır", [], forgecode.Usage(), [{"type": "text", "text": "Çoklu site hazır"}]),
                forgecode.ModelReply("", [{"id": "c", "name": "read_file", "arguments": {"path": "site/index.html"}}], forgecode.Usage(), [{"type": "tool_use", "id": "c", "name": "read_file", "input": {"path": "site/index.html"}}]),
                forgecode.ModelReply("Çoklu site hazır", [], forgecode.Usage(), [{"type": "text", "text": "Çoklu site hazır"}]),
            ]
            provider = mock.MagicMock()
            provider.request.side_effect = replies
            agent.provider = provider
            answer = agent.ask("Gelişmiş restoran web sitesi oluştur")
            self.assertIn("Çoklu site hazır", answer)
            self.assertTrue((root / "site/assets/css/styles.css").is_file())
            self.assertTrue((root / "site/assets/js/main.js").is_file())
            self.assertEqual(provider.request.call_count, 6)

    def test_complex_task_uses_ai_chosen_parallel_assignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["auto_subagents"] = True
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            agent.provider = self.NoToolProvider()
            assignments = [
                {"role": "research", "task": "Research project evidence"},
                {"role": "design", "task": "Propose the visual system"},
                {"role": "review", "task": "Inspect existing code risks"},
            ]
            with mock.patch.object(agent, "plan_delegations", return_value=assignments), mock.patch.object(agent, "run_delegations", return_value=["research report", "design report", "review report"]) as delegated:
                agent.ask("Profesyonel ve gelişmiş bir restoran web sitesi oluştur")
            executed = delegated.call_args.args[0]
            self.assertEqual([item["role"] for item in executed], ["research", "design", "review"])
            self.assertTrue(all("Overall user request" in item["task"] for item in executed))

    def test_custom_claude_proxy_can_use_ai_chosen_subagent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({"api_mode": "anthropic", "custom_protocol": "anthropic", "auto_subagents": True})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent.provider = self.NoToolProvider()
            assignment = [{"role": "research", "task": "Inspect project evidence"}]
            with mock.patch.object(agent, "plan_delegations", return_value=assignment), mock.patch.object(agent, "run_delegations", return_value=["report"]) as delegated:
                agent.ask("Profesyonel ve gelişmiş bir restoran web sitesi oluştur")
            self.assertEqual(delegated.call_args.args[0][0]["role"], "research")

    def test_anthropic_response_parsing(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        fake = {
            "content": [
                {"type": "text", "text": "working"},
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}},
            ],
            "usage": {"input_tokens": 12, "output_tokens": 7, "cache_read_input_tokens": 3},
        }
        with mock.patch.object(forgecode, "post_json", return_value=fake):
            reply = forgecode.AnthropicProvider(cfg).request("s", [{"role": "user", "content": "u"}], forgecode.TOOL_SCHEMAS)
        self.assertEqual(reply.text, "working")
        self.assertEqual(reply.tool_calls[0]["name"], "read_file")
        self.assertEqual(reply.usage.cached_tokens, 3)

    def test_custom_claude_code_proxy_uses_messages_protocol_and_x_api_key(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("custom")
        cfg.data.update({
            "base_url": "http://proxy.test:40008/v1",
            "model": "claude-sonnet-test",
            "api_mode": "anthropic",
            "custom_protocol": "anthropic",
            "custom_auth_mode": "auto",
            "custom_api_key": "secret-test-key",
        })
        fake = {"content": [{"type": "text", "text": "OK"}], "usage": {"input_tokens": 2, "output_tokens": 1}}
        with mock.patch.object(forgecode, "post_json", return_value=fake) as post:
            reply = forgecode.AnthropicProvider(cfg).request(
                "health", [{"role": "user", "content": "hello"}], [], 32
            )
        endpoint, headers, payload, timeout = post.call_args.args
        self.assertEqual(endpoint, "http://proxy.test:40008/v1/messages")
        self.assertEqual(headers["x-api-key"], "secret-test-key")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(payload["model"], "claude-sonnet-test")
        self.assertEqual(timeout, 100)
        self.assertEqual(reply.text, "OK")
        self.assertEqual(cfg.data["custom_auth_mode"], "x-api-key")
        self.assertEqual(cfg.data["custom_protocol"], "anthropic")

    def test_custom_claude_proxy_retries_without_unsupported_thinking(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("custom")
        cfg.data.update({
            "base_url": "https://proxy.test", "model": "claude-sonnet-test",
            "api_mode": "anthropic", "custom_protocol": "anthropic",
            "custom_auth_mode": "x-api-key", "custom_api_key": "test-key",
            "thinking_mode": "high", "thinking_budget_tokens": 2048,
        })
        success = {"content": [{"type": "text", "text": "OK"}], "usage": {}}
        with mock.patch.object(forgecode, "post_json", side_effect=[
            forgecode.ApiError("API 400: unknown parameter: thinking"), success,
        ]) as post:
            reply = forgecode.AnthropicProvider(cfg).request("system", [{"role": "user", "content": "hello"}], [], 4096)
        self.assertEqual(reply.text, "OK")
        self.assertIn("thinking", post.call_args_list[0].args[2])
        self.assertNotIn("thinking", post.call_args_list[1].args[2])
        self.assertEqual(post.call_args_list[1].args[2]["temperature"], cfg.data["temperature"])

    def test_custom_claude_proxy_creates_complete_multifile_site_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "base_url": "http://proxy.test:40008",
                "model": "claude-sonnet-test",
                "api_mode": "anthropic",
                "custom_protocol": "anthropic",
                "custom_auth_mode": "auto",
                "custom_api_key": "test-key",
                "autopilot_mode": True,
                "auto_subagents": True,
                "thinking_mode": "high",
                "efficiency_mode": "max",
                "timeout_seconds": 30,
                "streaming_enabled": False,
            })
            tool_reply = {
                "content": [
                    {
                        "type": "tool_use", "id": "html", "name": "CompatWriteFile50e90c",
                        "arguments": json.dumps({"path": "/tmp/proxy-hunter/index.html", "content": '<link rel="stylesheet" href="assets/css/styles.css"><script src="assets/js/main.js"></script>'}),
                    },
                    {
                        "type": "tool_use", "id": "css", "name": "CompatWriteFilea1b2c3",
                        "parameters": {"path": "/tmp/proxy-hunter/assets/css/styles.css", "content": "body{background:#111;color:#fff}"},
                    },
                    {
                        "type": "tool_use", "id": "js", "name": "CompatWriteFiled4e5f6",
                        "input": {"path": "/workspace/assets/js/main.js", "content": "document.body.dataset.ready='true'"},
                    },
                ],
                "usage": {"input_tokens": 20, "output_tokens": 30},
            }
            final_reply = {
                "content": [{"type": "text", "text": "Site tamamlandı."}],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            }
            verify_reply = {
                "content": [{"type": "tool_use", "id": "verify", "name": "read_file", "input": {"path": "index.html"}}],
                "usage": {"input_tokens": 8, "output_tokens": 3},
            }
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            seen_tools = []
            with mock.patch.object(agent, "plan_delegations", return_value=[]), mock.patch.object(forgecode, "post_json", side_effect=[tool_reply, final_reply, verify_reply, final_reply]) as post:
                answer = agent.ask("Gelişmiş restoran web sitesi oluştur", on_tool=lambda name, args: seen_tools.append((name, dict(args))))
            self.assertIn("Site tamamlandı", answer)
            self.assertTrue((root / "index.html").is_file())
            self.assertTrue((root / "assets/css/styles.css").is_file())
            self.assertTrue((root / "assets/js/main.js").is_file())
            sent_tool_names = {tool["name"] for tool in post.call_args_list[0].args[2]["tools"]}
            self.assertIn("write_file", sent_tool_names)
            self.assertNotIn("write_files", sent_tool_names)
            self.assertEqual(post.call_count, 4)
            self.assertTrue(all(call.args[3] == 30 for call in post.call_args_list))
            first_payload = post.call_args_list[0].args[2]
            self.assertEqual(first_payload["max_tokens"], 8192)
            self.assertIn("thinking", first_payload)
            self.assertIn("POWER MODE", first_payload["system"])
            self.assertEqual(seen_tools[0][1]["path"], "index.html")

    def test_custom_claude_design_request_can_write_a_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("custom")
            cfg.data.update({
                "api_mode": "anthropic", "custom_protocol": "anthropic",
                "efficiency_mode": "balanced", "auto_subagents": False,
                "auto_approve_writes": True,
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            provider = mock.MagicMock()
            provider.request.side_effect = [
                forgecode.ModelReply(
                    "", [{"id": "write-1", "name": "write_file", "arguments": {"path": "index.html", "content": "<h1>Hazır</h1>"}}],
                    forgecode.Usage(), [{"type": "tool_use", "id": "write-1", "name": "write_file", "input": {"path": "index.html", "content": "<h1>Hazır</h1>"}}],
                ),
                forgecode.ModelReply("Tasarım hazır.", [], forgecode.Usage(), [{"type": "text", "text": "Tasarım hazır."}]),
                forgecode.ModelReply(
                    "", [{"id": "read-1", "name": "read_file", "arguments": {"path": "index.html"}}],
                    forgecode.Usage(), [{"type": "tool_use", "id": "read-1", "name": "read_file", "input": {"path": "index.html"}}],
                ),
                forgecode.ModelReply("Tasarım hazır.", [], forgecode.Usage(), [{"type": "text", "text": "Tasarım hazır."}]),
            ]
            agent.provider = provider
            answer = agent.ask("Şık bir restoran ana sayfası tasarla ve hazırla")
            sent_names = {tool["name"] for tool in provider.request.call_args_list[0].args[2]}
            self.assertIn("write_file", sent_names)
            self.assertIn("run_command", sent_names)
            self.assertTrue((root / "index.html").is_file())
            self.assertIn("index.html", answer)
            self.assertEqual(provider.request.call_count, 4)
            self.assertEqual(provider.request.call_args_list[0].args[3], 8192)
            self.assertIn("POWER MODE", provider.request.call_args_list[0].args[0])

    def test_openai_response_parsing(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.data["provider"] = "openai"
        fake = {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "done"}]},
                {"type": "function_call", "call_id": "c1", "name": "list_files", "arguments": "{\"pattern\":\"*.py\"}"},
            ],
            "usage": {"input_tokens": 8, "output_tokens": 4, "input_tokens_details": {"cached_tokens": 2}},
        }
        with mock.patch.object(forgecode, "post_json", return_value=fake):
            reply = forgecode.OpenAIProvider(cfg).request("s", [], forgecode.TOOL_SCHEMAS)
        self.assertEqual(reply.text, "done")
        self.assertEqual(reply.tool_calls[0]["arguments"]["pattern"], "*.py")
        self.assertEqual(reply.usage.input_tokens, 8)

    def test_openai_compatible_chat_tool_parsing(self):
        cfg = forgecode.Config(pathlib.Path(tempfile.mkdtemp()))
        cfg.select_provider("openrouter")
        fake = {
            "choices": [{"message": {
                "role": "assistant",
                "content": "checking",
                "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\":\"main.py\"}"}}],
            }}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 6, "prompt_tokens_details": {"cached_tokens": 4}},
        }
        with mock.patch.object(forgecode, "post_json", return_value=fake) as post:
            reply = forgecode.OpenAIChatProvider(cfg).request("system", [{"role": "user", "content": "inspect"}], forgecode.TOOL_SCHEMAS)
        self.assertEqual(reply.tool_calls[0]["arguments"]["path"], "main.py")
        self.assertEqual(reply.usage.cached_tokens, 4)
        self.assertTrue(post.call_args.args[0].endswith("/chat/completions"))


class BackupApiTests(unittest.TestCase):
    class FailingProvider:
        def __init__(self, message):
            self.message = message
            self.calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            raise forgecode.ApiError(self.message)

    class SuccessChatProvider:
        def __init__(self, text="yedekten devam"):
            self.text = text
            self.calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            return forgecode.ModelReply(
                self.text,
                [],
                forgecode.Usage(7, 3, 0, 1),
                {"role": "assistant", "content": self.text},
            )

    def test_only_limit_and_quota_errors_are_failover_eligible(self):
        self.assertTrue(forgecode.is_limit_or_quota_error("API 429: rate limit exceeded"))
        self.assertTrue(forgecode.is_limit_or_quota_error("API 402: insufficient credit balance"))
        self.assertTrue(forgecode.is_limit_or_quota_error("RESOURCE_EXHAUSTED: quota"))
        self.assertFalse(forgecode.is_limit_or_quota_error("API 400: invalid model"))
        self.assertFalse(forgecode.is_limit_or_quota_error("API 401: invalid API key"))

    def test_backup_target_accepts_provider_or_saved_custom_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            groq = forgecode.backup_connection_for(cfg, "groq", "llama-backup")
            self.assertEqual((groq["provider"], groq["model"]), ("groq", "llama-backup"))
            cfg.data["connection_profiles"] = {
                "proxy": {
                    "provider": "custom", "model": "claude-backup", "api_mode": "anthropic",
                    "base_url": "https://proxy.test", "custom_protocol": "anthropic",
                    "custom_auth_mode": "x-api-key", "custom_endpoint_path": "/v1/messages",
                }
            }
            proxy = forgecode.backup_connection_for(cfg, "proxy")
            self.assertEqual(proxy["provider"], "custom")
            self.assertEqual(proxy["custom_endpoint_path"], "/v1/messages")

    def test_backup_runtime_key_is_used_but_runtime_override_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            cfg = forgecode.Config(home)
            cfg.data["backup_connection"] = forgecode.backup_connection_for(cfg, "groq")
            cfg.data["backup_api_key"] = "backup-secret"
            cfg.save()
            backup_cfg = forgecode.make_backup_config(cfg)
            self.assertEqual(backup_cfg.key(), "backup-secret")
            backup_cfg.save()
            saved = json.loads((home / "config.json").read_text(encoding="utf-8"))
            self.assertNotIn("_runtime_api_key_override", saved)
            self.assertEqual(saved["provider"], "anthropic")

    def test_messages_are_converted_between_provider_protocols(self):
        messages = [
            {"role": "user", "content": "inspect"},
            {"role": "assistant", "content": [{"type": "text", "text": "working"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "done"}]},
        ]
        chat = forgecode.convert_messages_for_mode(messages, "chat")
        self.assertEqual([item["role"] for item in chat], ["user", "assistant", "user"])
        self.assertIn("Tool result", chat[-1]["content"])
        responses = forgecode.convert_messages_for_mode(messages, "responses")
        self.assertEqual(responses[0]["content"][0]["type"], "input_text")
        self.assertIn("ASSISTANT", responses[0]["content"][0]["text"])

    def test_ask_switches_to_backup_on_quota_and_can_restore_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("anthropic")
            cfg.data.update({
                "auto_subagents": False,
                "backup_enabled": True,
                "backup_connection": forgecode.backup_connection_for(cfg, "groq", "llama-backup"),
                "backup_api_key": "backup-secret",
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            primary = self.FailingProvider("API 429: quota exceeded")
            backup = self.SuccessChatProvider()
            agent.provider = primary
            with mock.patch.object(forgecode, "make_provider", return_value=backup):
                answer = agent.ask("selam")
            self.assertEqual(answer, "yedekten devam")
            self.assertEqual(primary.calls, 1)
            self.assertEqual(backup.calls, 1)
            self.assertTrue(cfg.data["backup_active"])
            self.assertEqual(cfg.data["provider"], "groq")
            self.assertEqual(cfg.key(), "backup-secret")
            reloaded = forgecode.Config(root / "home")
            self.assertTrue(reloaded.data["backup_active"])
            self.assertEqual(reloaded.data["provider"], "groq")
            self.assertEqual(reloaded.key(), "backup-secret")
            restored = self.SuccessChatProvider("primary")
            with mock.patch.object(forgecode, "make_provider", return_value=restored):
                self.assertTrue(agent.restore_primary_connection())
            self.assertEqual(cfg.data["provider"], "anthropic")
            self.assertFalse(cfg.data["backup_active"])
            self.assertNotIn("_runtime_api_key_override", cfg.data)

    def test_identical_connection_needs_a_separate_backup_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("groq")
            cfg.data.update({
                "backup_enabled": True,
                "backup_connection": forgecode.connection_state(cfg),
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            self.assertFalse(agent.activate_backup(forgecode.ApiError("API 429: quota")))
            cfg.data["backup_api_key"] = "second-key"
            with mock.patch.object(forgecode, "make_provider", return_value=self.SuccessChatProvider()):
                self.assertTrue(agent.activate_backup(forgecode.ApiError("API 429: quota")))
            self.assertEqual(cfg.key(), "second-key")

    def test_bad_request_does_not_switch_to_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.select_provider("anthropic")
            cfg.data.update({
                "auto_subagents": False,
                "backup_enabled": True,
                "backup_connection": forgecode.backup_connection_for(cfg, "groq"),
            })
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent.provider = self.FailingProvider("API 400: invalid model")
            with mock.patch.object(forgecode, "make_provider") as factory:
                with self.assertRaises(forgecode.ApiError):
                    agent.ask("selam")
            factory.assert_not_called()
            self.assertFalse(cfg.data["backup_active"])
            self.assertEqual(cfg.data["provider"], "anthropic")

    def test_backup_command_sets_target_and_keeps_key_out_of_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            goals = forgecode.GoalStore(root)
            agent = forgecode.Agent(root, cfg, goals, lambda _: False)
            output = io.StringIO()
            with mock.patch.object(forgecode.getpass, "getpass", return_value="very-secret-backup-key"), mock.patch.object(sys, "stdout", output):
                forgecode.handle_command("/backup set groq llama-backup", agent, cfg, goals)
                forgecode.handle_command("/backup key", agent, cfg, goals)
                forgecode.handle_command("/backup", agent, cfg, goals)
            self.assertTrue(cfg.data["backup_enabled"])
            self.assertEqual(cfg.data["backup_connection"]["model"], "llama-backup")
            self.assertEqual(cfg.data["backup_api_key"], "very-secret-backup-key")
            self.assertNotIn("very-secret-backup-key", output.getvalue())
            self.assertIn("Yedek API", output.getvalue())


class CancellationQueueTests(unittest.TestCase):
    def test_queued_prompt_editor_collects_lines_and_backspace(self):
        queue = forgecode.QueuedPromptInput(render=False)
        for char in "sonraki prompx":
            queue.feed_char(char)
        queue.feed_char("\b")
        queue.feed_char("t")
        queued = queue.feed_char("\r")
        self.assertEqual(queued, "sonraki prompt")
        self.assertTrue(queue)
        self.assertEqual(queue.peek(), "sonraki prompt")
        self.assertEqual(queue.pop(), "sonraki prompt")
        with self.assertRaises(KeyboardInterrupt):
            queue.feed_char("\x03")

    def test_ctrl_c_does_not_wait_for_blocking_api_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            release = forgecode.threading.Event()
            provider = mock.MagicMock()
            provider.request.side_effect = lambda *args: release.wait(2) or forgecode.ModelReply("late", [], forgecode.Usage(), [])
            agent.provider = provider
            polls = {"count": 0}

            def cancel_on_poll():
                polls["count"] += 1
                raise KeyboardInterrupt

            agent.input_poller = cancel_on_poll
            started = forgecode.time.monotonic()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    agent._request_with_heartbeat([], 32, False)
                self.assertLess(forgecode.time.monotonic() - started, 0.75)
                self.assertGreaterEqual(polls["count"], 1)
            finally:
                release.set()

    def test_live_input_steers_immediately_but_queue_prefix_waits(self):
        queue = forgecode.QueuedPromptInput(render=False)
        queue.live_mode = True
        for char in "burada sorun var mı kontrol et":
            queue.feed_char(char)
        with self.assertRaises(forgecode.SteeringInterrupt) as caught:
            queue.feed_char("\r")
        self.assertEqual(caught.exception.prompt, "burada sorun var mı kontrol et")
        self.assertFalse(queue)

        for char in "/queue bitince testleri çalıştır":
            queue.feed_char(char)
        queued = queue.feed_char("\r")
        self.assertEqual(queued, "bitince testleri çalıştır")
        self.assertEqual(queue.pop(), "bitince testleri çalıştır")

    def test_live_steering_does_not_wait_for_blocking_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            release = forgecode.threading.Event()
            provider = mock.MagicMock()
            provider.request.side_effect = lambda *args: release.wait(2) or forgecode.ModelReply("late", [], forgecode.Usage(), [])
            agent.provider = provider
            agent.input_poller = lambda: (_ for _ in ()).throw(forgecode.SteeringInterrupt("yeni talimat"))
            started = forgecode.time.monotonic()
            try:
                with self.assertRaises(forgecode.SteeringInterrupt):
                    agent._request_with_heartbeat([], 32, False)
                self.assertLess(forgecode.time.monotonic() - started, 0.75)
            finally:
                release.set()

    def test_interrupted_progress_is_injected_into_next_prompt_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["auto_subagents"] = False
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            agent._current_baseline = agent.tools.snapshot()
            (root / "index.html").write_text("partial", encoding="utf-8")
            agent._emit_activity("Araç tamamlandı: write_file")
            summary = agent.remember_interruption("restoran sitesi yap", "önce durumu özetle")
            self.assertIn("index.html", summary)
            self.assertIn("önce durumu özetle", summary)
            self.assertIn("İstek durduruldu", agent.session_store.recent_turns(1)[0]["assistant"])
            restarted = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            self.assertIn("İstek durduruldu", restarted.system())

            seen = {}
            provider = mock.MagicMock()

            def reply(system, messages, tools, *args):
                seen["messages"] = copy.deepcopy(messages)
                return forgecode.ModelReply("devam edildi", [], forgecode.Usage(), [{"type": "text", "text": "devam edildi"}])

            provider.request.side_effect = reply
            agent.provider = provider
            answer = agent.ask("önce durumu özetle")
            sent = json.dumps(seen["messages"], ensure_ascii=False)
            self.assertIn("ÖNCEKİ TUR KULLANICI TARAFINDAN", sent)
            self.assertIn("ŞİMDİKİ KULLANICI TALİMATI", sent)
            self.assertEqual(answer, "devam edildi")

    def test_steering_context_includes_visible_partial_not_hidden_thoughts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["auto_subagents"] = False
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            agent._current_baseline = agent.tools.snapshot()
            summary = agent.remember_interruption(
                "siteyi düzelt", "önce hatayı açıkla", "Görünür kısmi cevap", reason="steer"
            )
            self.assertIn("CANLI KULLANICI YÖNLENDİRMESİYLE", summary)
            self.assertIn("Görünür kısmi cevap", summary)
            self.assertIn("gizli düşünce zinciri değildir", summary)
            self.assertIn("Canlı yönlendirme talimatı: önce hatayı açıkla", summary)
            event = agent.session_store.recent_events(1)[0]
            self.assertEqual(event["kind"], "steer")
            seen = {}

            def respond(system, messages, tools, *args):
                seen["messages"] = copy.deepcopy(messages)
                return forgecode.ModelReply("sorun açıklandı", [], forgecode.Usage(), [{"type": "text", "text": "sorun açıklandı"}])

            provider = mock.MagicMock()
            provider.request.side_effect = respond
            agent.provider = provider
            self.assertEqual(agent.ask("önce hatayı açıkla"), "sorun açıklandı")
            sent = json.dumps(seen["messages"], ensure_ascii=False)
            self.assertIn("Görünür kısmi cevap", sent)
            self.assertIn("önce hatayı açıkla", sent)


class StreamingAndModelMenuTests(unittest.TestCase):
    def test_streaming_is_enabled_by_default_and_typed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            self.assertTrue(cfg.data["streaming_enabled"])
            cfg.set_value("streaming_enabled", "off")
            self.assertFalse(cfg.data["streaming_enabled"])

    def test_chat_stream_joins_text_tool_arguments_and_usage(self):
        chunks = []
        events = [
            {"choices": [{"delta": {"content": "Mer"}}]},
            {"choices": [{"delta": {"content": "haba", "tool_calls": [{"index": 0, "id": "c1", "function": {"name": "write_", "arguments": "{\"path\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "file", "arguments": "\"a.txt\"}"}}]}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}},
        ]
        data = forgecode.consume_chat_stream(iter(events), chunks.append)
        self.assertEqual("".join(chunks), "Merhaba")
        message = data["choices"][0]["message"]
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "write_file")
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"path": "a.txt"})
        self.assertEqual(data["usage"]["completion_tokens"], 4)

    def test_chat_provider_marks_and_sanitizes_truncated_tool_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.select_provider("openrouter")
            fake = {"choices": [{"finish_reason": "length", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "cut", "type": "function", "function": {
                    "name": "write_file", "arguments": "{\"path\":\"index.html\",\"content\":\"cut"
                }}],
            }}], "usage": {}}
            with mock.patch.object(forgecode, "post_json", return_value=fake):
                reply = forgecode.OpenAIChatProvider(cfg).request("s", [], forgecode.TOOL_SCHEMAS)
            self.assertIn("cut off", reply.tool_calls[0]["parse_error"])
            self.assertEqual(reply.native_output["tool_calls"][0]["function"]["arguments"], "{}")
            self.assertEqual(reply.finish_reason, "length")

    def test_anthropic_stream_rebuilds_tool_input(self):
        chunks = []
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Tamam"}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "write_file", "input": {}}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"path\":\"x\"}"}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "usage": {"output_tokens": 2}},
        ]
        data = forgecode.consume_anthropic_stream(iter(events), chunks.append)
        self.assertEqual(chunks, ["Tamam"])
        self.assertEqual(data["content"][1]["input"], {"path": "x"})
        self.assertEqual(data["usage"], {"input_tokens": 5, "output_tokens": 2})

    def test_anthropic_stream_marks_truncated_tool_json(self):
        events = [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "t1", "name": "write_file", "input": {}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{\"path\":\"cut"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
        ]
        data = forgecode.consume_anthropic_stream(iter(events), lambda _: None)
        self.assertIn("_forgecode_parse_error", data["content"][0])
        self.assertEqual(data["stop_reason"], "max_tokens")

    def test_streaming_transport_is_used_without_ui_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: True)
            seen = {}

            class Provider:
                def request(self, *args):
                    seen["on_text"] = args[5]
                    args[5]("progress")
                    return forgecode.ModelReply("done", [], forgecode.Usage(), [])

            agent.provider = Provider()
            reply = agent._request_with_heartbeat([], 128, False)
            self.assertEqual(reply.text, "done")
            self.assertTrue(callable(seen["on_text"]))
            self.assertEqual(agent.last_streamed_reply, "progress")

    def test_responses_stream_uses_completed_response(self):
        chunks = []
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Hi"}]}], "usage": {"input_tokens": 1, "output_tokens": 1}}
        data = forgecode.consume_responses_stream(iter([
            {"type": "response.output_text.delta", "delta": "Hi"},
            {"type": "response.completed", "response": response},
        ]), chunks.append)
        self.assertEqual(chunks, ["Hi"])
        self.assertEqual(data, response)

    def test_model_menu_uses_arrows_and_enter(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.data["model"] = "one"
            keys = iter(["down", "down", "enter"])
            selected = forgecode.choose_model_menu(cfg, ["one", "two", "three"], lambda: next(keys), render=False)
            self.assertEqual(selected, "three")

    def test_model_menu_can_filter_by_typing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            keys = iter(["s", "o", "n", "enter"])
            selected = forgecode.choose_model_menu(cfg, ["haiku", "sonnet", "opus"], lambda: next(keys), render=False)
            self.assertEqual(selected, "sonnet")

    def test_non_tty_renderer_buffers_draft_without_printing_it(self):
        queue = forgecode.QueuedPromptInput(render=False)
        output = io.StringIO()
        with mock.patch.object(sys, "stdout", output):
            renderer = forgecode.LiveStreamTerminal(queue)
            renderer.write("Mer")
            renderer.write("haba")
            renderer.finish()
        self.assertEqual(output.getvalue(), "")

    def test_each_model_round_resets_previous_streaming_draft(self):
        queue = forgecode.QueuedPromptInput(render=False)
        output = io.StringIO()
        with mock.patch.object(sys, "stdout", output):
            renderer = forgecode.LiveStreamTerminal(queue)
            renderer.begin_request()
            renderer.write("old english draft")
            self.assertIn("old english", renderer._current)
            renderer.reset_draft()
            renderer.write("new verified response")
            self.assertNotIn("old english", renderer._current)
            self.assertIn("new verified", renderer._current)

    def test_agent_requests_a_stream_draft_reset_for_every_tool_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "index.html").write_text("ready", encoding="utf-8")
            cfg = forgecode.Config(root / "home")
            cfg.data.update({"auto_subagents": False, "power_mode": "off"})
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            resets = []
            agent.stream_reset_callback = lambda: resets.append("reset")
            provider = mock.MagicMock()
            provider.request.side_effect = [
                forgecode.ModelReply(
                    "", [{"id": "read", "name": "read_file", "arguments": {"path": "index.html"}}], forgecode.Usage(),
                    [{"type": "tool_use", "id": "read", "name": "read_file", "input": {"path": "index.html"}}],
                ),
                forgecode.ModelReply("İncelendi.", [], forgecode.Usage(), [{"type": "text", "text": "İncelendi."}]),
            ]
            agent.provider = provider
            agent.ask("index dosyasını incele")
            self.assertEqual(resets, ["reset", "reset"])

    def test_interactive_stream_uses_distinct_thinking_label(self):
        class TtyBuffer(io.StringIO):
            def isatty(self):
                return True

        queue = forgecode.QueuedPromptInput(render=False)
        output = TtyBuffer()
        with mock.patch.object(forgecode, "ANSI", True), mock.patch.object(sys, "stdout", output):
            renderer = forgecode.LiveStreamTerminal(queue)
            renderer.begin_request()
            renderer.write("geçici taslak")
            renderer.finish()
        self.assertIn("düşünme ›", output.getvalue())

    def test_system_prompt_reserves_one_final_response_after_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            self.assertIn("one self-contained final response", agent.system())

    def test_stream_preview_never_wraps_accumulated_paragraph(self):
        text = "Proje tamamlandı: " + ("çok uzun streaming cevabı " * 40)
        preview = forgecode.single_line_stream_preview(text, 36)
        self.assertLessEqual(len(preview), 36)
        self.assertNotIn("\n", preview)
        self.assertTrue(preview.startswith("‹"))
        self.assertTrue(preview.endswith(text[-1]))

    def test_stream_renderer_sanitizes_cursor_control_characters(self):
        cleaned = forgecode.safe_terminal_text("normal\x1b[2Jmetin\rdevam")
        self.assertNotIn("\x1b", cleaned)
        self.assertNotIn("\r", cleaned)
        self.assertIn("normal�[2Jmetindevam", cleaned)

    def test_cancelled_request_ignores_late_stream_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            release = forgecode.threading.Event()
            chunks = []

            class SlowProvider:
                def request(self, *args):
                    callback = args[-1]
                    release.wait(1)
                    callback("geç")
                    return forgecode.ModelReply("geç", [], forgecode.Usage(), [])

            agent.provider = SlowProvider()
            agent.stream_callback = chunks.append
            agent.input_poller = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
            with self.assertRaises(KeyboardInterrupt):
                agent._request_with_heartbeat([], 10, False)
            release.set()
            forgecode.time.sleep(0.05)
            self.assertEqual(chunks, [])

    def test_unsupported_streaming_falls_back_without_read_timeout_before_emitting_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            consumer = mock.Mock(side_effect=forgecode.ApiError("API 400: stream unsupported"))
            with mock.patch.object(forgecode, "iter_sse_json", return_value=iter(())), mock.patch.object(
                forgecode, "post_json_with_retry", return_value={"ok": True}
            ) as fallback:
                result = forgecode.stream_or_json(cfg, "https://x.test", {}, {"stream": True}, 10, consumer, lambda _: None)
            self.assertEqual(result, {"ok": True})
            self.assertNotIn("stream", fallback.call_args.args[3])
            self.assertIsNone(fallback.call_args.args[4])

    def test_sse_stream_uses_no_socket_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            with mock.patch.object(forgecode, "iter_sse_json", return_value=iter(())) as sse:
                result = forgecode.stream_or_json(
                    cfg, "https://x.test", {}, {"stream": True}, 100,
                    lambda events, emit: {"ok": True}, lambda _: None,
                )
            self.assertEqual(result, {"ok": True})
            self.assertIsNone(sse.call_args.args[3])

    def test_stream_status_explains_unlimited_and_normal_timeout_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            self.assertIn("zaman aşımı yok", forgecode.stream_status_text(cfg))
            self.assertIn("Ctrl+C", forgecode.stream_status_text(cfg))
            cfg.set_value("streaming_enabled", "off")
            self.assertIn("normal API timeout: 100 sn", forgecode.stream_status_text(cfg))


class ProviderLatencyTests(unittest.TestCase):
    def test_latency_uses_rolling_average_and_first_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            forgecode.record_provider_latency(cfg, 1.0, 0.2)
            forgecode.record_provider_latency(cfg, 3.0, 0.6)
            stats = cfg.data["latency_stats"]["anthropic"]
            self.assertEqual(stats["samples"], 2)
            self.assertEqual(stats["avg_ms"], 1600)
            self.assertEqual(stats["first_avg_ms"], 320)
            self.assertEqual(stats["best_ms"], 1000)

    def test_provider_list_shows_speed_rank_and_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.data["latency_stats"] = {
                "openai": {"samples": 2, "first_avg_ms": 400, "avg_ms": 1000},
                "groq": {"samples": 1, "first_avg_ms": 120, "avg_ms": 500},
            }
            output = io.StringIO()
            with mock.patch.object(sys, "stdout", output):
                forgecode.print_providers(cfg)
            text = output.getvalue()
            self.assertIn("#1 ilk 120 ms", text)
            self.assertIn("#2 ilk 400 ms", text)
            self.assertIn("anahtar yok", text)

    def test_successful_agent_request_records_latency_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)

            class Provider:
                def request(self, *args):
                    callback = args[-1]
                    callback("ok")
                    return forgecode.ModelReply("ok", [], forgecode.Usage(), [])

            agent.provider = Provider()
            agent.stream_callback = lambda _: None
            agent._request_with_heartbeat([], 10, False)
            stats = cfg.data["latency_stats"]["anthropic"]
            self.assertEqual(stats["samples"], 1)
            self.assertIn("first_avg_ms", stats)


class UnlimitedAgentAndDelegationPolicyTests(unittest.TestCase):
    def test_fixed_agent_step_limit_cannot_be_reenabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = forgecode.Config(pathlib.Path(tmp))
            cfg.set_value("max_agent_steps", "0")
            with self.assertRaises(ValueError):
                cfg.set_value("max_agent_steps", "12")

    def test_explicit_no_agent_phrases_have_priority(self):
        blocked = [
            "Agent çalıştırma, bu işi kendin yap",
            "Subagent kullanma",
            "Ajanları açma",
            "Alt ajan olmadan incele",
            "Do not use agents",
            "Without subagents, fix this",
        ]
        for prompt in blocked:
            with self.subTest(prompt=prompt):
                self.assertTrue(forgecode.Agent._forbids_subagents(prompt))
                self.assertFalse(forgecode.Agent._should_orchestrate(prompt))
        self.assertFalse(forgecode.Agent._forbids_subagents("Subagent çalıştırıp çalıştırmayacağına kendin karar ver"))
        self.assertTrue(forgecode.Agent._should_orchestrate("Subagent çalıştırıp çalıştırmayacağına kendin karar ver"))

    def test_forbidden_turn_neither_plans_nor_exposes_delegate_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            provider = mock.MagicMock(return_value=None)
            provider.request.return_value = forgecode.ModelReply("İnceledim", [], forgecode.Usage(), [{"type": "text", "text": "İnceledim"}])
            agent.provider = provider
            with mock.patch.object(agent, "plan_delegations") as planner, mock.patch.object(agent, "run_delegations") as runner:
                answer = agent.ask("Tüm projeyi ayrıntılı incele ama agent çalıştırma")
            self.assertEqual(answer, "İnceledim")
            planner.assert_not_called()
            runner.assert_not_called()
            offered = {tool["name"] for tool in provider.request.call_args.args[2]}
            self.assertNotIn("delegate_task", offered)

    def test_agents_off_removes_automatic_delegate_tool_globally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["auto_subagents"] = False
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            names = {tool["name"] for tool in agent._effective_tools("Projeyi incele")}
            self.assertNotIn("delegate_task", names)

    def test_concrete_work_lets_orchestrator_ai_decide_zero_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent.provider = mock.MagicMock()
            agent.provider.request.return_value = forgecode.ModelReply("done", [], forgecode.Usage(), [{"type": "text", "text": "done"}])
            with mock.patch.object(agent, "plan_delegations", return_value=[]) as planner:
                agent.ask("README dosyasını düzelt")
            planner.assert_called_once()

    def test_main_agent_can_continue_beyond_old_twelve_step_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["auto_subagents"] = False
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            replies = []
            for index in range(13):
                call = {"id": f"t{index}", "name": "list_files", "arguments": {"pattern": f"file-{index}*"}}
                replies.append(forgecode.ModelReply("", [call], forgecode.Usage(), [{"type": "tool_use", **call, "input": call["arguments"]}]))
            replies.append(forgecode.ModelReply("On üç araç turundan sonra tamamlandı", [], forgecode.Usage(), [{"type": "text", "text": "tamam"}]))
            provider = mock.MagicMock()
            provider.request.side_effect = replies
            agent.provider = provider
            answer = agent.ask("Dosyaları sırayla incele")
            self.assertIn("On üç", answer)
            self.assertEqual(provider.request.call_count, 14)
            self.assertNotIn("Azami ajan", answer)

    def test_identical_tool_loop_stops_without_a_numeric_turn_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            cfg.data["auto_subagents"] = False
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            call = {"id": "same", "name": "list_files", "arguments": {"pattern": "*"}}
            provider = mock.MagicMock()
            provider.request.return_value = forgecode.ModelReply("", [call], forgecode.Usage(), [{"type": "tool_use", **call, "input": call["arguments"]}])
            agent.provider = provider
            answer = agent.ask("Dosyaları incele")
            self.assertIn("aynı araç çağrısını", answer)
            self.assertEqual(provider.request.call_count, 3)


class ForceContextV2Tests(unittest.TestCase):
    def make_store(self, root):
        return forgecode.ForceContext(root, root / ".force" / "user.json")

    def test_memory_requires_explicit_initialization_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            store = self.make_store(root)
            self.assertFalse(store.enabled())
            self.assertFalse((root / ".force").exists())
            store.initialize()
            self.assertTrue(store.enabled())
            store.set_enabled(False)
            self.assertEqual(store.select("remember my style"), "")

    def test_global_force_launcher_shape_accepts_context_commands_after_project_path(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            root = pathlib.Path(tmp)
            output = io.StringIO()
            with mock.patch.dict(os.environ, {"FORGECODE_HOME": home}), mock.patch("sys.stdout", output):
                self.assertEqual(forgecode.main([str(root), "force-context-init"]), 0)
                self.assertEqual(forgecode.main([str(root), "force-context-update", "project", "rule", "Use typed errors"]), 0)
            self.assertTrue((root / ".force" / "config.json").is_file())
            self.assertIn("Updated:", output.getvalue())

    def test_context_pipeline_selects_relevant_cards_with_receipt_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            store = self.make_store(root)
            store.initialize()
            relevant = store.update("project", "api-rule", "API errors use typed exceptions.",
                                    ["api", "errors"], source="AGENTS.md:20", status="verified",
                                    confidence=1.0, memory_type="rule")
            store.update("project", "css-note", "Buttons are purple.", ["css"], source="user")
            context, receipt = store.compile("Fix the API error handling", "max")
            self.assertIn(relevant["id"], context)
            self.assertNotIn("Buttons are purple", context)
            self.assertLessEqual(receipt["estimated_tokens"], receipt["budget"])
            self.assertEqual(receipt["selected"][0]["source"], "AGENTS.md:20")
            self.assertTrue((root / ".force" / "receipts" / "latest.json").exists())

    def test_private_values_are_redacted_before_context_is_compiled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            store = self.make_store(root)
            store.initialize()
            store.update("project", "api-secret", "API key=sk-example123456789012345", ["api"])
            context = store.select("check api secret")
            self.assertIn("[REDACTED]", context)
            self.assertNotIn("sk-example", context)

    def test_response_analyzer_keeps_unverified_decisions_as_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            store = self.make_store(root)
            store.initialize()
            suggested = store.analyze_response("design", "Architecture updated to use a service layer.")
            verified = store.analyze_response("fix", "Implemented typed errors and tests passed.", ["api.py"], True)
            self.assertEqual(suggested[0]["status"], "suggested")
            self.assertEqual(verified[0]["status"], "verified")
            self.assertIn("api.py", verified[0]["source"])
            context, _ = store.compile("service layer architecture")
            self.assertNotIn(suggested[0]["id"], context)
            self.assertIn(verified[0]["id"], store.compile("typed errors tests")[0])

    def test_selected_context_is_injected_into_agent_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = forgecode.Config(root / "home")
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            agent.force_context = self.make_store(root)
            agent.force_context.initialize()
            card = agent.force_context.update("project", "error-rule", "Use typed errors in API code.",
                                              ["api", "error"], source="AGENTS.md:10", status="verified",
                                              confidence=1.0, memory_type="rule")
            agent._force_context_text = agent.force_context.select("fix api error")
            agent._system_cache = ""
            system = agent.system()
            self.assertIn("FORCECONTEXT SELECTED MEMORY", system)
            self.assertIn(card["id"], system)

    def test_incremental_scan_respects_forceignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "app.py").write_text("# TODO: test this\n", encoding="utf-8")
            (root / "secret.txt").write_text("hidden", encoding="utf-8")
            (root / ".forceignore").write_text("secret.txt\n", encoding="utf-8")
            store = self.make_store(root)
            store.initialize()
            first = store.scan()
            second = store.scan()
            index = forgecode.load_json(root / ".force" / "index.json", {})
            self.assertNotIn("secret.txt", index["files"])
            self.assertGreaterEqual(first["todos"], 1)
            self.assertTrue(second["incremental"])
            self.assertEqual(second["changed"], 0)


class ExecutionKernelTests(unittest.TestCase):
    def make_cfg(self, root):
        cfg = forgecode.Config(root / "home")
        cfg.data["auto_subagents"] = False
        return cfg

    def test_planning_engine_builds_evidence_steps_without_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = self.make_cfg(root)
            engine = forgecode.ExecutionKernel(root, cfg)
            state = engine.begin("Traceback hatasını düzelt", True, False, False, {})
            self.assertEqual(state.plan.task_type, "debug")
            self.assertEqual([step.id for step in state.plan.steps], ["inspect", "reproduce", "change", "verify", "report"])
            self.assertIn("evidence:", state.plan.prompt_contract())

    def test_token_budget_engine_reduces_max_efficiency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = self.make_cfg(root)
            engine = forgecode.TokenBudgetEngine()
            cfg.data["efficiency_mode"] = "off"
            large = engine.allocate(cfg, "refactor", "refactor", False)
            cfg.data["efficiency_mode"] = "max"
            small = engine.allocate(cfg, "refactor", "refactor", False)
            self.assertLess(small["context"], large["context"])
            self.assertLessEqual(small["output"], large["output"])

    def test_debugging_engine_classifies_and_deduplicates_failures(self):
        engine = forgecode.DebuggingEngine()
        first = engine.diagnose("run_command", "ERROR: API 429 rate limit")
        second = engine.diagnose("run_command", "ERROR: API 429 rate limit")
        self.assertEqual(first.category, "rate-limit")
        self.assertTrue(first.retryable)
        self.assertEqual(first.signature, second.signature)
        self.assertEqual(second.occurrences, 2)

    def test_verification_and_confidence_are_evidence_based(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = self.make_cfg(root)
            kernel = forgecode.ExecutionKernel(root, cfg)
            state = kernel.begin("Fix API error", True, False, False, {})
            missing = kernel.verifier.evaluate(state, [], "done", True, False)
            low, _ = kernel.confidence.score(state, [], "done", True)
            kernel.observe_tool(state, "write_file", "OK")
            kernel.observe_tool(state, "run_command", "exit_code=0\npassed")
            complete = kernel.verifier.evaluate(state, ["api.py"], "fixed", True, False)
            high, _ = kernel.confidence.score(state, ["api.py"], "fixed", True)
            self.assertIn("no project artifact was created or changed", missing)
            self.assertEqual(complete, [])
            self.assertGreater(high, low)

    def test_execution_report_is_persisted_without_hidden_reasoning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = self.make_cfg(root)
            kernel = forgecode.ExecutionKernel(root, cfg)
            state = kernel.begin("Create app", True, False, False, {})
            kernel.observe_tool(state, "write_file", "OK")
            report = kernel.finish(state, ["app.py"], "Created app", True, False)
            persisted = forgecode.load_json(root / ".forgecode" / "last-run.json", {})
            self.assertEqual(report["run_id"], persisted["run_id"])
            self.assertNotIn("thought", json.dumps(persisted).lower())
            self.assertIn("confidence_breakdown", persisted)

    def test_agent_injects_execution_contract_and_exposes_last_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = self.make_cfg(root)
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            provider = mock.MagicMock()
            provider.request.return_value = forgecode.ModelReply("Açıklama tamamlandı", [], forgecode.Usage(), [])
            agent.provider = provider
            answer = agent.ask("Bu modülün ne yaptığını açıkla")
            sent_messages = provider.request.call_args.args[1]
            self.assertIn("FORGECODE EXECUTION CONTRACT", json.dumps(sent_messages, ensure_ascii=False))
            self.assertIn("Açıklama", answer)
            self.assertIn("confidence", agent.last_execution_report)

    def test_terminal_api_failure_is_preserved_for_debug_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = self.make_cfg(root)
            agent = forgecode.Agent(root, cfg, forgecode.GoalStore(root), lambda _: False)
            provider = mock.MagicMock()
            provider.request.side_effect = forgecode.ApiError("API 429: rate limit")
            agent.provider = provider
            with self.assertRaises(forgecode.ApiError):
                agent.ask("Explain this module")
            report = forgecode.load_json(root / ".forgecode" / "last-run.json", {})
            self.assertEqual(report["errors"][0]["category"], "rate-limit")
            self.assertFalse(report["verification_passed"])


if __name__ == "__main__":
    unittest.main()
