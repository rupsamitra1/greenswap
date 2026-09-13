"""Verification agent.

The single-call estimator answers "how green is this?" from a title, which is
guesswork wearing a number. This module runs a short research loop instead: the
model may look products up in the certified database, consult the certification
programmes, and search the catalog for cheaper greener options, then must
justify its verdict with citations.

The important rule is enforced here, not in the prompt: a product is labelled
"certified" only if a TOOL actually returned that certification. The model
cannot talk its way into a verification badge, because every citation is checked
against recorded tool output before it reaches the shopper. A prompt instruction
not to invent certifications is a request; this is a guarantee.
"""

import json

MAX_STEPS = 6  # bounds both latency and spend per uncached product

# Official programme references, so a certification name becomes something the
# shopper can click and check for themselves.
CERTIFICATION_PROGRAMS = {
    "epa safer choice": {
        "name": "EPA Safer Choice",
        "url": "https://www.epa.gov/saferchoice/products",
        "about": "US EPA programme certifying products whose ingredients are on "
                 "the Safer Chemical Ingredients List.",
    },
    "energy star": {
        "name": "ENERGY STAR",
        "url": "https://www.energystar.gov/productfinder",
        "about": "US EPA/DOE programme certifying energy-efficient products.",
    },
    "climate pledge friendly": {
        "name": "Climate Pledge Friendly",
        "url": "https://www.amazon.com/climatepledgefriendly",
        "about": "Amazon programme aggregating third-party sustainability "
                 "certifications.",
    },
    "usda biopreferred": {
        "name": "USDA BioPreferred",
        "url": "https://www.biopreferred.gov/BioPreferred/",
        "about": "USDA programme certifying bio-based product content.",
    },
}

SYSTEM_PROMPT = """You are a sustainability analyst working inside a shopping
assistant. Given a product listing, determine how sustainable it is and back
your verdict with evidence.

Use the tools available to you:
- search_certifications: check whether this exact product is in our verified
  certification database. Always try this first.
- lookup_certification_program: get the official reference for a certification
  programme so the shopper can check it themselves.
- search_alternatives: find greener products in the same category.

Score against this rubric so that scores mean the same thing across products:
  0-30   Single-use or disposable; virgin plastic; harsh chemistry.
  31-60  Mixed: partly recyclable, or durable but high-impact materials.
  61-85  Durable and reusable, or plant-derived and biodegradable.
  86-100 Reusable or refillable AND recycled or renewable material.

When you have enough information, reply with ONLY this JSON:
{
  "category": "cleaning | bottles | personal_care | kitchen | other",
  "materials": ["likely", "materials"],
  "eco_score": 0-100,
  "reason": "one plain sentence a shopper would understand",
  "certification": "exact programme name, or null if none was FOUND BY A TOOL",
  "citations": [
    {"claim": "what this source supports", "source": "name", "url": "https://..."}
  ]
}

Rules:
- Only cite URLs that a tool actually returned to you. Never write a URL from
  memory.
- Set "certification" only when search_certifications returned one for THIS
  product. If it did not, the honest answer is null and an estimate.
- When the listing does not say, assume the commonplace version of the product
  rather than the best case, and say so in "reason"."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_certifications",
            "description": "Look this product up in the verified certification "
                           "database (EPA Safer Choice, ENERGY STAR and similar). "
                           "The only source that can establish a product as "
                           "certified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string"},
                    "brand": {"type": "string"},
                },
                "required": ["product_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_certification_program",
            "description": "Get the official reference URL and description for a "
                           "certification programme by name.",
            "parameters": {
                "type": "object",
                "properties": {"program": {"type": "string"}},
                "required": ["program"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_alternatives",
            "description": "Find greener products in a category, optionally at or "
                           "below a price.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["cleaning", "bottles", "personal_care",
                                 "kitchen", "other"],
                    },
                    "max_price": {"type": "number"},
                },
                "required": ["category"],
            },
        },
    },
]


class Evidence:
    """Everything the tools actually returned, so citations can be checked."""

    def __init__(self):
        self.urls: set[str] = set()
        self.certifications: set[str] = set()
        self.tool_calls: list[dict] = []

    def record_url(self, url):
        if url:
            self.urls.add(str(url).strip())

    def record_certification(self, name):
        if name:
            self.certifications.add(str(name).strip().lower())


def execute_tool(name: str, args: dict, deps: dict, evidence: Evidence) -> dict:
    """Run one tool and record what it produced as admissible evidence."""
    evidence.tool_calls.append({"tool": name, "args": args})

    if name == "search_certifications":
        row = deps["lookup_certified"](args.get("product_name", ""))
        if not row:
            return {
                "found": False,
                "note": "Not in the certification database. Any verdict must be "
                        "labelled an estimate, not a verification.",
            }
        cert = row.get("certification")
        evidence.record_certification(cert)
        program = CERTIFICATION_PROGRAMS.get((cert or "").lower())
        if program:
            evidence.record_url(program["url"])
        return {
            "found": True,
            "name": row.get("name"),
            "certification": cert,
            "eco_score": row.get("eco_score"),
            "category": row.get("category"),
            "reason": row.get("reason"),
            "reference_url": program["url"] if program else None,
        }

    if name == "lookup_certification_program":
        key = str(args.get("program", "")).strip().lower()
        program = CERTIFICATION_PROGRAMS.get(key)
        if not program:
            return {
                "found": False,
                "known_programs": [p["name"] for p in CERTIFICATION_PROGRAMS.values()],
            }
        evidence.record_url(program["url"])
        return {"found": True, **program}

    if name == "search_alternatives":
        rows = deps["find_alternatives"](
            category=args.get("category", "other"),
            min_score=0,
            max_price=args.get("max_price"),
        )
        for row in rows:
            evidence.record_certification(row.get("certification"))
        return {
            "count": len(rows),
            "alternatives": [
                {
                    "name": r["name"],
                    "price": r.get("price"),
                    "eco_score": r["eco_score"],
                    "certification": r.get("certification"),
                    "trust": r.get("trust"),
                }
                for r in rows
            ],
        }

    return {"error": f"unknown tool {name}"}


def verify_claims(result: dict, evidence: Evidence) -> dict:
    """Strip anything the tools did not actually support.

    This is the guarantee behind the verified badge. A model that hallucinates a
    certification, or cites a plausible-looking URL it never received, is quietly
    downgraded to an estimate rather than shown to a shopper as verified.
    """
    citations = []
    for citation in result.get("citations") or []:
        if not isinstance(citation, dict):
            continue
        url = str(citation.get("url", "")).strip()
        if url and url in evidence.urls:
            citations.append({
                "claim": str(citation.get("claim", ""))[:200],
                "source": str(citation.get("source", ""))[:100],
                "url": url,
            })
    result["citations"] = citations[:4]

    claimed = str(result.get("certification") or "").strip()
    if claimed and claimed.lower() not in evidence.certifications:
        # The model asserted a certification no tool returned. Refuse it.
        result["certification"] = None
        result["unsupported_claim"] = claimed

    result["verified"] = bool(result.get("certification"))
    return result


def run_agent(client, deployment: str, listing: str, deps: dict, parse_json,
              max_steps: int = MAX_STEPS) -> dict:
    """Research loop. Returns the verdict plus its evidence trail."""
    evidence = Evidence()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": listing},
    ]

    for _ in range(max_steps):
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            tools=TOOLS,
            temperature=0,
        )
        message = response.choices[0].message
        calls = getattr(message, "tool_calls", None)

        if not calls:
            result = verify_claims(parse_json(message.content), evidence)
            result["tool_calls"] = evidence.tool_calls
            return result

        # Resend the assistant turn VERBATIM. Gemini 3.x attaches an encrypted
        # thought_signature to each function call (under extra_content.google)
        # and rejects the next request if it is missing -- reconstructing the
        # message by hand silently drops it. model_dump keeps provider-specific
        # fields; the manual branch is for clients that do not provide it.
        if hasattr(message, "model_dump"):
            assistant = message.model_dump(exclude_none=True)
            assistant.pop("function_call", None)  # deprecated, and rejected
            messages.append(assistant)
        else:
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.function.name,
                            "arguments": c.function.arguments,
                        },
                    }
                    for c in calls
                ],
            })

        for call in calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            output = execute_tool(call.function.name, args, deps, evidence)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(output),
            })

    raise RuntimeError(f"agent did not conclude within {max_steps} steps")
