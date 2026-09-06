"""Exercise every Azure code path with a stub client -- no key, no network.

This is the part of "first contact" that can be de-risked in advance:
everything except the socket.

    python tests/test_azure.py
"""
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import main  # noqa: E402
from main import Product  # noqa: E402


def reply(content):
    message = types.SimpleNamespace(content=content, tool_calls=None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class Stub:
    """Mimics azure_client.chat.completions.create."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return reply(item)


GOOD = ('{"category":"bottles","materials":["PET plastic"],'
        '"eco_score":18,"reason":"Single-use PET bottles."}')
SAMPLE = Product(title="Disposable Plastic Water Bottles, 24 Pack", price=12.99)

results = []


def run(name, script, expect):
    main.azure_client = Stub(script)
    main.AGENT_ENABLED = False  # this file covers the single-call path
    main.azure_status.update(
        {"calls": 0, "failures": 0, "last_error": None, "json_mode": True}
    )
    result = main.estimate_with_ai(SAMPLE)
    stub = main.azure_client
    ok = expect(result, stub)
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"        score={result['eco_score']} cat={result['category']} "
          f"calls={len(stub.calls)} err={main.azure_status['last_error']}")


run("clean JSON", [GOOD],
    lambda r, s: r["eco_score"] == 18 and r["category"] == "bottles")

run("markdown-fenced JSON", ["```json\n" + GOOD + "\n```"],
    lambda r, s: r["eco_score"] == 18)

run("JSON wrapped in prose", ["Here you go:\n" + GOOD + "\nHope that helps!"],
    lambda r, s: r["eco_score"] == 18)

run("response_format unsupported -> retries without JSON mode",
    [Exception("400 Unsupported parameter: 'response_format' is not supported"), GOOD],
    lambda r, s: r["eco_score"] == 18 and len(s.calls) == 2
    and "response_format" in s.calls[0] and "response_format" not in s.calls[1])

run("eco_score as text -> cautious default",
    ['{"category":"bottles","eco_score":"very low","reason":"x"}'],
    lambda r, s: r["eco_score"] == 40)

run("eco_score out of range -> clamped",
    ['{"category":"bottles","eco_score":900,"reason":"x"}'],
    lambda r, s: r["eco_score"] == 100)

run("bogus category -> keyword fallback",
    ['{"category":"beverages","eco_score":20,"reason":"x"}'],
    lambda r, s: r["category"] == "bottles")

run("materials as string -> coerced to list",
    ['{"category":"bottles","materials":"plastic","eco_score":20,"reason":"x"}'],
    lambda r, s: r["materials"] == ["plastic"])

run("empty reason -> filled in",
    ['{"category":"bottles","eco_score":20,"reason":""}'],
    lambda r, s: len(r["reason"]) > 10)

run("total garbage -> cautious default, error recorded",
    ["I'm sorry, I can't help with that."],
    lambda r, s: r["eco_score"] == 40 and main.azure_status["last_error"] is not None)

run("401 auth error -> offline fallback, error recorded",
    [Exception("Error code: 401 - Access denied due to invalid subscription key")],
    lambda r, s: r["eco_score"] == 40 and "401" in main.azure_status["last_error"])

run("404 deployment error -> offline fallback",
    [Exception("Error code: 404 - DeploymentNotFound")],
    lambda r, s: r["eco_score"] == 40 and "404" in main.azure_status["last_error"])

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
