from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import ThreadingHTTPServer
from typing import Any


def _research_tags() -> list[str]:
    return [
        "Non-intervention prevents mission creep expansion",
        "Strategic restraint avoids overextension",
        "Forward deployment increases escalation risk",
        "Security guarantees create entrapment risk",
        "Arms racing undermines crisis stability",
        "Extended deterrence increases nuclear escalation risk",
        "Military primacy triggers balancing coalitions",
        "Overseas commitments drain force readiness",
        "Alliance guarantees increase entrapment risk",
        "Tripwire deployments heighten crisis instability",
    ]


def _explicit_batch_one() -> list[tuple[str, str, str, str, str, str, str]]:
    return [
        ("Avoiding intervention prevents mission creep", "Strategic Restraint and Mission Creep", "Jordan Lee", "2025", "Policy Review", "https://example.org/strategic-restraint-1", "Military missions often expand beyond their initial objectives. Analysts warn that interventions create bureaucratic, political, and alliance pressures for additional commitments. Avoiding intervention reduces those pressures and lowers the risk of mission creep."),
        ("Security guarantees create entrapment risk", "Alliance Commitments and Entrapment", "Riley Chen", "2024", "International Security Notes", "https://example.org/entrapment-risk-1", "Formal security guarantees can pull states into disputes they did not choose. Scholars describe this as entrapment risk because allies expect support and leaders face credibility pressures to intervene once commitments exist."),
        ("Arms races heighten accidental escalation", "Arms Racing and Crisis Stability", "Morgan Patel", "2023", "Strategic Studies Quarterly", "https://example.org/arms-races-1", "Competitive arms buildups shorten decision windows and amplify fear of surprise attack. Those dynamics increase the danger of accidental or inadvertent escalation during crises."),
        ("Forward deployment raises escalation risk", "Tripwires and Escalation", "Alex Moreno", "2022", "Defense Analysis", "https://example.org/forward-deployment-1", "Forward deployed forces act as tripwires in fast-moving confrontations. Because they can be targeted immediately, leaders face pressure to retaliate quickly, which raises escalation risk."),
        ("Strategic restraint preserves force readiness", "Readiness Costs of Overseas Commitments", "Taylor Brooks", "2025", "Military Effectiveness Review", "https://example.org/readiness-1", "Persistent overseas commitments consume maintenance capacity, training time, and personnel availability. A strategy of restraint preserves readiness by reducing those ongoing operational burdens."),
        ("Extended deterrence raises nuclear escalation risk", "Extended Deterrence and Escalation", "Casey Nguyen", "2024", "Nuclear Policy Journal", "https://example.org/extended-deterrence-1", "Extended deterrence commitments can widen the set of crises that carry nuclear implications. As more actors expect intervention, escalation pathways multiply and the risk of nuclear confrontation rises."),
        ("Military primacy triggers balancing coalitions", "Primacy and Counterbalancing", "Sam Rivera", "2023", "Grand Strategy Review", "https://example.org/primacy-balancing-1", "When one state pursues military primacy, rivals respond by coordinating against it. That balancing behavior can produce tighter opposing coalitions and worsen long-term security competition."),
        ("Overseas commitments drain force readiness", "Operational Burden and Readiness", "Jamie Foster", "2025", "Force Management Review", "https://example.org/overseas-commitments-1", "Sustained overseas commitments consume training time, maintenance cycles, and deployable personnel. Those costs reduce force readiness for higher-priority contingencies."),
        ("Tripwire deployments heighten crisis instability", "Tripwires and Crisis Instability", "Avery Kim", "2022", "Crisis Management Review", "https://example.org/tripwire-instability-1", "Tripwire deployments make local incidents more dangerous because frontline units can be hit before leaders have time to deliberate. That compresses decision-making and heightens crisis instability."),
        ("Alliance guarantees increase entrapment risk", "Alliance Politics and Entrapment", "Drew Singh", "2024", "Security Affairs", "https://example.org/alliance-entrapment-1", "Alliance guarantees can increase entrapment risk by creating expectations of support during disputes. Once those expectations harden, leaders face stronger pressure to intervene in conflicts they would otherwise avoid."),
    ]


def _explicit_batch_two() -> list[tuple[str, str, str, str, str, str, str]]:
    return [
        ("Restraint reduces alliance free riding", "Alliance Burden Sharing under Restraint", "Parker Ellis", "2024", "Alliance Studies Review", "https://example.org/free-riding-1", "When a patron commits less automatically, allies have stronger incentives to provide for their own defense. That dynamic reduces free riding and encourages greater burden sharing."),
        ("Military intervention weakens domestic readiness", "Domestic Readiness Costs of Intervention", "Quinn Harper", "2025", "Public Policy and Defense", "https://example.org/domestic-readiness-1", "Interventions consume maintenance budgets, training cycles, and personnel attention. Those costs weaken domestic readiness for emergencies and other higher-priority missions."),
        ("Credibility traps pull states into unwanted wars", "Credibility and Escalation Traps", "Reese Turner", "2023", "International Strategy Forum", "https://example.org/credibility-traps-1", "Leaders often escalate because they fear the reputational costs of backing down. Those credibility traps can pull states into wars they did not initially want to fight."),
        ("Offshore balancing lowers peacetime costs", "The Fiscal Logic of Offshore Balancing", "Skyler Adams", "2022", "Grand Strategy Ledger", "https://example.org/offshore-balancing-1", "Offshore balancing reduces the need for large permanent deployments abroad. That lowers peacetime operating costs and preserves resources for rare major contingencies."),
        ("Forward presence creates tripwire escalation", "Tripwires and Automatic Escalation", "Dakota Price", "2024", "Escalation Review", "https://example.org/tripwire-escalation-1", "When forces are stationed directly on the front line, a local attack can immediately create pressure for wider retaliation. That tripwire effect makes crises harder to contain."),
        ("Intervention multiplies commitment pressures", "Commitment Expansion after Intervention", "Rowan Bell", "2025", "Policy Commitments Quarterly", "https://example.org/commitment-pressures-1", "Initial interventions rarely remain limited because political leaders face pressure to defend sunk costs, protect credibility, and reassure partners. Those pressures multiply commitments over time."),
        ("Security guarantees encourage risky ally behavior", "Moral Hazard in Alliance Politics", "Emerson Cole", "2023", "Alliance Politics Journal", "https://example.org/moral-hazard-1", "Security guarantees can encourage risky ally behavior because protected states expect outside support. That moral hazard raises the chance of crises and unwanted involvement."),
        ("Arming for primacy provokes counterbalancing", "Primacy and Rival Alignment", "Finley Ward", "2024", "Strategic Competition Review", "https://example.org/counterbalancing-1", "Efforts to preserve military primacy can convince rivals that they must coordinate against the dominant state. The result is stronger counterbalancing and sharper strategic competition."),
        ("Restraint preserves munitions and maintenance capacity", "Readiness Stocks under Restraint", "Harley Brooks", "2025", "Logistics and Readiness", "https://example.org/munitions-maintenance-1", "A restrained strategy avoids consuming munitions, spare parts, and maintenance capacity on peripheral missions. That preserves stocks and repair bandwidth for more serious contingencies."),
        ("Extended commitments widen escalation pathways", "Commitment Scope and Escalation", "Indigo Ross", "2024", "Crisis Pathways", "https://example.org/escalation-pathways-1", "As security commitments spread across more regions and contingencies, the number of escalation pathways grows. Wider commitments therefore make great-power crises harder to manage."),
    ]


def _default_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for repeat in range(2):
        for tag in _research_tags():
            cases.append(
                {
                    "name": f"research-r{repeat + 1}:{tag}",
                    "payload": {
                        "draft_tag": tag,
                        "semantic_search_enabled": True,
                    },
                }
            )
    for batch_name, batch in (("b1", _explicit_batch_one()), ("b2", _explicit_batch_two())):
        for repeat in range(4):
            for tag, title, author, year, publication, url, article in batch:
                cases.append(
                    {
                        "name": f"explicit-{batch_name}-r{repeat + 1}:{tag}",
                        "payload": {
                            "draft_tag": tag,
                            "semantic_search_enabled": True,
                            "source_title": title,
                            "source_author": author,
                            "source_date": year,
                            "source_publication": publication,
                            "source_url": f"{url}?run={repeat + 1}",
                            "article_text": article,
                        },
                    }
                )
    return cases


def _delivery_success(parsed: dict[str, Any], status: int) -> bool:
    cards = parsed.get("cards") or []
    first = cards[0] if cards else {}
    return (
        status == 200
        and parsed.get("ok") is True
        and bool(cards)
        and bool(first.get("formatted_card") or first.get("card_text") or first.get("body"))
    )


def _quality_success(parsed: dict[str, Any]) -> bool:
    meta = parsed.get("meta") if isinstance(parsed, dict) else {}
    if not isinstance(meta, dict):
        return False
    quality = meta.get("quality")
    if isinstance(quality, dict) and "quality_gate_passed" in quality:
        return bool(quality.get("quality_gate_passed"))
    return not bool(meta.get("fallback_used")) and not bool(meta.get("search_exhausted"))


def _run_suite(parallelism: int, request_timeout: int) -> int:
    import server

    for logger in [server.LOGGER, server.REQUEST_LOGGER, server.RESEARCH_LOGGER, server.PROVIDER_LOGGER, server.ERROR_LOGGER]:
        logger.disabled = True
    server.DebateCardHandler.log_message = lambda self, format, *args: None  # type: ignore[assignment]

    cases = _default_cases()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.DebateCardHandler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    def run_case(case: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/cut",
            data=json.dumps(case["payload"]).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                parsed = json.loads(resp.read().decode("utf-8", errors="replace"))
                meta = parsed.get("meta", {}) if isinstance(parsed, dict) else {}
                quality = meta.get("quality", {}) if isinstance(meta, dict) else {}
                return {
                    "name": case["name"],
                    "status": resp.status,
                    "seconds": round(time.time() - started, 2),
                    "delivery_success": _delivery_success(parsed, resp.status),
                    "quality_success": _quality_success(parsed),
                    "provider": meta.get("provider"),
                    "fallback_used": meta.get("fallback_used"),
                    "search_exhausted": meta.get("search_exhausted"),
                    "quality_tier": quality.get("tier") if isinstance(quality, dict) else "",
                    "quality_failures": quality.get("failures") if isinstance(quality, dict) else [],
                }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body}
            return {
                "name": case["name"],
                "status": exc.code,
                "seconds": round(time.time() - started, 2),
                "delivery_success": False,
                "quality_success": False,
                "error": parsed.get("error") if isinstance(parsed, dict) else body,
            }

    results: list[dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = [pool.submit(run_case, case) for case in cases]
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(json.dumps(result, ensure_ascii=False))
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)

    delivery_successes = sum(1 for item in results if item.get("delivery_success"))
    quality_successes = sum(1 for item in results if item.get("quality_success"))
    fallback_used = sum(1 for item in results if item.get("fallback_used"))
    search_exhausted = sum(1 for item in results if item.get("search_exhausted"))
    provider_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}
    for item in results:
        provider = str(item.get("provider") or "")
        tier = str(item.get("quality_tier") or "")
        if provider:
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
        if tier:
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

    summary = {
        "runs": len(results),
        "delivery_successes": delivery_successes,
        "delivery_success_rate": round(delivery_successes / len(results), 3) if results else 0.0,
        "quality_successes": quality_successes,
        "quality_success_rate": round(quality_successes / len(results), 3) if results else 0.0,
        "provider_counts": provider_counts,
        "quality_tier_counts": tier_counts,
        "fallback_used": fallback_used,
        "search_exhausted": search_exhausted,
    }
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return 0 if delivery_successes == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the default 100-case live backend reliability suite.")
    parser.add_argument("--parallelism", type=int, default=10)
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument("--openai-compat-timeout", type=int, default=None)
    args = parser.parse_args()

    if args.openai_compat_timeout is not None:
        os.environ["OPENAI_COMPAT_TIMEOUT"] = str(args.openai_compat_timeout)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return _run_suite(parallelism=max(1, args.parallelism), request_timeout=max(30, args.request_timeout))


if __name__ == "__main__":
    raise SystemExit(main())
