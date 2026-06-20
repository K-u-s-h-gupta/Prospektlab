import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = r"D:\PROSPEKTLAB\.finagent\content_automation\insights\earnings-generate-a-publication-grade-research-analysis-of-britannia-industries-3qfy25-r-v2\article.json"
data = json.load(open(p, encoding="utf-8"))

print("TITLE:", data.get("title"))
print("PUBLISH STATUS:", data.get("publish_status"))
print("CONFIDENCE:", data.get("confidence_score"))
art = data.get("article", {})
print()
print("DESCRIPTION:", (art.get("description") or "")[:400])
print()
print("HERO SUMMARY:", (art.get("hero_summary") or "")[:400])
print()
print("=== SECTIONS ===")
for i, s in enumerate(art.get("sections", [])):
    heading = s.get("heading", "")
    paras = s.get("paragraphs", [])
    bullets = s.get("bullets", [])
    print(f"-- Section {i+1}: {heading} --")
    for j, para in enumerate(paras[:2]):
        print(f"  P{j+1}: {para[:400]}")
    if bullets:
        print(f"  Bullets: {len(bullets)}")
        for b in bullets[:3]:
            print(f"    * {b[:200]}")
    print()

print(f"Word count: {data.get('word_count', 0)}")
print(f"Sources used: {len(data.get('sources_used') or [])}")
pg = data.get("publish_gate", {})
print(f"Publish gate status: {pg.get('status')}")
print(f"Publish gate score: {pg.get('score')}")
print(f"Review reason: {pg.get('review_reason') or data.get('review_reason')}")
print()
print("Metrics:", len(art.get("metrics") or []))
print("Tables:", len(art.get("tables") or []))
print("Visuals:", len(art.get("visuals") or []))
