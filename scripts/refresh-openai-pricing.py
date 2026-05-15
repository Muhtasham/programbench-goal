#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

MODEL_DOCS = {
    "gpt-5.5": "https://developers.openai.com/api/docs/models/gpt-5.5",
    "gpt-5.4": "https://developers.openai.com/api/docs/models/gpt-5.4",
    "gpt-5": "https://developers.openai.com/api/docs/models/gpt-5",
}
PRICE_RE = re.compile(r"<div>(Input|Cached input|Output)</div><div class=\"text-2xl font-semibold\">\$([0-9.]+)</div>")
LONG_CONTEXT_RE = re.compile(
    r"prompts with &gt;([0-9]+)K input tokens are priced at ([0-9.]+)x input and ([0-9.]+)x output"
)


def fetch(url: str) -> str:
    with urlopen(Request(url, headers={"User-Agent": "goalbench/0.1"}), timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def parse_model_pricing(model: str, url: str) -> dict:
    html = fetch(url)
    index = html.find("Text tokens")
    if index == -1:
        raise ValueError(f"could not find Text tokens section for {model}")
    prices = {
        label.lower().replace(" ", "_"): float(value) for label, value in PRICE_RE.findall(html[index : index + 8000])
    }
    if {"input", "cached_input", "output"} - set(prices):
        raise ValueError(f"could not parse token prices for {model}: {prices}")
    pricing = {
        "source_url": url,
        "input_usd_per_mtok": prices["input"],
        "cached_input_usd_per_mtok": prices["cached_input"],
        "output_usd_per_mtok": prices["output"],
    }
    long_context = LONG_CONTEXT_RE.search(html)
    if long_context:
        pricing.update(
            {
                "long_context_input_threshold_tokens": int(long_context.group(1)) * 1000,
                "long_context_input_multiplier": float(long_context.group(2)),
                "long_context_cached_input_multiplier": float(long_context.group(2)),
                "long_context_output_multiplier": float(long_context.group(3)),
            }
        )
    return pricing


def refresh(args: argparse.Namespace) -> None:
    output = Path(args.output).expanduser()
    models = args.models or list(MODEL_DOCS)
    data = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "OpenAI model documentation pricing cards",
        "source_type": "official_docs_scrape",
        "pricing_api_endpoint": None,
        "models": {model: parse_model_pricing(model, MODEL_DOCS[model]) for model in models},
        "notes": [
            "OpenAI does not currently expose a supported structured pricing endpoint for these model price cards.",
            "Prices are standard API text token rates per 1M tokens.",
            "Codex subscription billing and fast-mode multipliers may differ from these API rates.",
            "Reasoning output tokens are diagnostic and are not added on top of output_tokens.",
            "When model docs expose a long-context threshold, costs apply that multiplier per Codex token_count call.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(output)
    for model, pricing in data["models"].items():
        print(
            ",".join(
                [
                    model,
                    str(pricing["input_usd_per_mtok"]),
                    str(pricing["cached_input_usd_per_mtok"]),
                    str(pricing["output_usd_per_mtok"]),
                    unescape(pricing["source_url"]),
                ]
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh local OpenAI token pricing from official model docs")
    parser.add_argument("--output", default="local_state/openai_pricing.json")
    parser.add_argument("--models", nargs="+", choices=sorted(MODEL_DOCS))
    refresh(parser.parse_args())


if __name__ == "__main__":
    main()
