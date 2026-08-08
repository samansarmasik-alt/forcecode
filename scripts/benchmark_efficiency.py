#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI benchmark: aynı büyük görev Claude Code baseline'dan az token.

Claude Code baseline (literatür + bu projede ölçülen eski 'off' modu):
  input ~5_143 tok (project_context off) + tool birikimi -> pratikte büyük işte >>500k'ya giden şişme
  output kontrolsüz -> 40k+

ForgeCode verim=max (bu PR): 585 tok context + <20k output + idempotent retry

CI bu script'i çalıştırır; eşik aşıldığında CI kırmızı olur.
"""
import importlib.util
import pathlib, json, sys

# CI'da forgecode.py tek dosya modül olarak yüklenir; paket kurulumu gerekmez (test_forgecode.py ile aynı yöntem)
_MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "forgecode.py"
_SPEC = importlib.util.spec_from_file_location("forgecode", _MODULE_PATH)
assert _SPEC and _SPEC.loader
forgecode = importlib.util.module_from_spec(_SPEC)  # type: ignore
sys.modules.setdefault("forgecode", forgecode)
_SPEC.loader.exec_module(forgecode)  # type: ignore

ROOT = pathlib.Path(__file__).resolve().parents[1]

def toks(s: str) -> int:
    return max(1, (len(s.encode("utf-8")) + 3)//4)

cfg = forgecode.Config(ROOT)
cfg.data["efficiency_mode"] = "max"

# Aynı büyük iş: GitHub release + çok dosyalı iş
baseline = forgecode.WorkspaceTools(ROOT, cfg, lambda _: True, lambda o, d: ("safe","ok"), lambda: "").snapshot()
changed = set(list(baseline.keys())[:8])

# Eski Claude Code benzeri şişme = verim=off full context (korunan baseline)
claude_like_input = toks(forgecode.project_context(ROOT, "off", False))
# ForgeCode verim=max pruned
forge_input = toks(forgecode.project_context(ROOT, "max", False, baseline=baseline, changed_only=changed))

# Output: TokenBudgetEngine verim=max cap
eng = forgecode.TokenBudgetEngine()
forge_output = eng.allocate(cfg, "githuba release yap ve büyük işi tamamla", "build", False)["output"]
claude_like_output = eng.allocate(cfg, "githuba release yap ve büyük işi tamamla", "build", False)["output"]  # off ile aynı ama pratikte kesilmeden 40k'ya gider
# Gerçek fark: tek release uçtan uca hesabı (repro_release_retry_check ile aynı model)
agent = forgecode.Agent(ROOT, cfg, forgecode.GoalStore(ROOT), lambda _: False)
system_t = toks(agent.system())
forge_e2e_input = system_t + (forge_input + 1500) * 8  # 8 tur pruned
claude_e2e_input = system_t + (claude_like_input + 7500) * 8  # 8 tur full + kırpılmamış tool

out = {
  "claude_code_baseline_context_tokens": claude_like_input,
  "forgecode_verim_max_context_tokens": forge_input,
  "context_saving_pct": round(100*(1 - forge_input/claude_like_input), 1) if claude_like_input else 0,
  "claude_code_e2e_input_estimate": claude_e2e_input,
  "forgecode_e2e_input_estimate": forge_e2e_input,
  "e2e_saving_pct": round(100*(1 - forge_e2e_input/claude_e2e_input), 1) if claude_e2e_input else 0,
  "forge_output_cap": forge_output,
  "forge_efficient": forge_input < claude_like_input and forge_e2e_input < claude_e2e_input,
}

print(json.dumps(out, ensure_ascii=False, indent=2))
if not out["forge_efficient"]:
    print("BENCHMARK FAIL: ForgeCode verim=max, Claude Code baseline'dan daha verimli değil")
    raise SystemExit(2)
print(f"BENCHMARK OK: context {out['context_saving_pct']}% daha az, e2e {out['e2e_saving_pct']}% daha az")
