"""Exercise the verification agent's tool loop with a stub client.

The case that matters most: a model that claims a certification no tool
returned must NOT reach the shopper as verified.
"""
import json, pathlib, sys, types, unittest

if __name__ != "__main__":
    raise unittest.SkipTest("standalone agent verification script")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import main, agent as A
from main import Product

def tool_call(cid, name, args):
    return types.SimpleNamespace(
        id=cid, type="function",
        function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))

def msg(content=None, tool_calls=None):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=content, tool_calls=tool_calls))])

class Stub:
    def __init__(self, script):
        self.script = list(script); self.seen = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._c))
    def _c(self, **kw):
        self.seen.append(kw)
        item = self.script.pop(0)
        return item() if callable(item) else item

def fixture_certified(title):
    if "Plant-Based Dish Soap" in str(title):
        return {"name": "Plant-Based Dish Soap, 40oz", "category": "cleaning",
                "eco_score": 93, "certification": "EPA Safer Choice",
                "reason": "Fixture verified for citation enforcement tests."}
    return None


DEPS = {"lookup_certified": fixture_certified,
        "find_alternatives": main.find_alternatives}

def run(script):
    return A.run_agent(Stub(script), "dep", "Title: x", DEPS, main.parse_model_json)

results = []
def check(name, cond, detail=""):
    results.append(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if detail: print(f"        {detail}")

# --- 1. honest path: tool finds nothing, model correctly says estimate -------
r = run([
    msg(tool_calls=[tool_call("1", "search_certifications",
                              {"product_name": "Ultra Clean Dish Soap, 40oz"})]),
    msg(content=json.dumps({
        "category": "cleaning", "materials": ["surfactants", "PET"],
        "eco_score": 24, "reason": "Single-use plastic bottle.",
        "certification": None, "citations": []})),
])
check("uncertified product stays an estimate",
      r["verified"] is False and r["certification"] is None,
      f"verified={r['verified']} steps={len(r['tool_calls'])}")

# --- 2. THE ATTACK: model invents a certification it never received ----------
r = run([
    msg(tool_calls=[tool_call("1", "search_certifications", {"product_name": "Ultra Clean Dish Soap"})]),
    msg(content=json.dumps({
        "category": "cleaning", "materials": ["plant surfactants"],
        "eco_score": 91, "reason": "Certified safe.",
        "certification": "EPA Safer Choice",
        "citations": [{"claim": "EPA certified", "source": "EPA",
                       "url": "https://www.epa.gov/saferchoice/products"}]})),
])
check("INVENTED certification is refused",
      r["verified"] is False and r["certification"] is None
      and r.get("unsupported_claim") == "EPA Safer Choice",
      f"refused claim={r.get('unsupported_claim')!r}")

check("fabricated citation is stripped",
      r["citations"] == [],
      f"citations={r['citations']}")

# --- 3. hallucinated URL removed even when certification is real ------------
r = run([
    msg(tool_calls=[tool_call("1", "search_certifications", {"product_name": "Plant-Based Dish Soap, 40oz"})]),
    msg(content=json.dumps({
        "category": "cleaning", "materials": ["plant surfactants"], "eco_score": 93,
        "reason": "All ingredients on the EPA list.",
        "certification": "EPA Safer Choice",
        "citations": [
            {"claim": "listed by EPA", "source": "EPA Safer Choice",
             "url": "https://www.epa.gov/saferchoice/products"},
            {"claim": "made of bamboo", "source": "Totally Real Site",
             "url": "https://not-a-real-source.example.com/proof"}]})),
])
main_cert_ok = r["verified"] is True and r["certification"] == "EPA Safer Choice"
check("real certification is honoured", main_cert_ok, f"cert={r['certification']}")
check("only the tool-provided URL survives",
      len(r["citations"]) == 1 and "epa.gov" in r["citations"][0]["url"],
      f"kept={[c['url'] for c in r['citations']]}")

# --- 4. multi-step research loop --------------------------------------------
r = run([
    msg(tool_calls=[tool_call("1", "search_certifications", {"product_name": "Plant-Based Dish Soap, 40oz"})]),
    msg(tool_calls=[tool_call("2", "lookup_certification_program", {"program": "EPA Safer Choice"})]),
    msg(tool_calls=[tool_call("3", "search_alternatives", {"category": "cleaning", "max_price": 4.49})]),
    msg(content=json.dumps({
        "category": "cleaning", "materials": ["plant surfactants"], "eco_score": 93,
        "reason": "Ingredients appear on the EPA Safer Chemical Ingredients List.",
        "certification": "EPA Safer Choice",
        "citations": [{"claim": "Listed by EPA Safer Choice", "source": "US EPA",
                       "url": "https://www.epa.gov/saferchoice/products"}]})),
])
check("three-tool research loop completes",
      len(r["tool_calls"]) == 3 and r["verified"] and len(r["citations"]) == 1,
      f"tools used: {[t['tool'] for t in r['tool_calls']]}")

# --- 5. runaway loop is bounded ---------------------------------------------
never_finishes = [msg(tool_calls=[tool_call(str(i), "search_certifications", {"product_name": "x"})])
                  for i in range(12)]
try:
    A.run_agent(Stub(never_finishes), "dep", "Title: x", DEPS, main.parse_model_json, max_steps=4)
    check("runaway loop bounded", False, "no exception raised")
except RuntimeError as e:
    check("runaway loop bounded", "within 4 steps" in str(e), str(e))

# --- 6. end to end through /analyze, agent failure falls back ----------------
from fastapi.testclient import TestClient
main._memory_cache.clear()
main.llm_client = Stub([
    msg(tool_calls=[tool_call("1", "search_certifications", {"product_name": "Ultra Clean Dish Soap, 40oz"})]),
    msg(content=json.dumps({
        "category": "cleaning", "materials": ["synthetic surfactants"], "eco_score": 22,
        "reason": "Petroleum surfactants in a single-use bottle.",
        "certification": None, "citations": []})),
])
d = TestClient(main.app).post("/analyze", json={
    "title": "Ultra Clean Dish Soap, 40oz", "price": 4.49}).json()
check("/analyze uses the agent",
      d["original"]["eco_score"] == 22 and d["original"]["trust"] == "ai_estimated",
      f"score={d['original']['eco_score']} alts={len(d['alternatives'])} "
      f"agent_runs={main.llm_status['agent_runs']}")

main._memory_cache.clear()
main.llm_client = Stub([Exception("agent blew up"),  # agent path dies
                          msg(content='{"category":"cleaning","eco_score":30,"reason":"fallback"}')])
d = TestClient(main.app).post("/analyze", json={"title": "Some Soap", "price": 4.49}).json()
check("agent failure falls back to single call",
      d["original"]["eco_score"] == 30 and main.llm_status["agent_failures"] >= 1,
      f"score={d['original']['eco_score']} failures={main.llm_status['agent_failures']}")

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
