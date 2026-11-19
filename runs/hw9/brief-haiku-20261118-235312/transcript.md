# Client transcript (brief-haiku-20261118-235312)

**1. client says:** I'll start with the Referral documentation, then look at the corpus.

**2. Read**
```json
{"file_path": "/tmp/coldstart-ms2md20h/client/REFERRAL.md"}
```
response:
```
1	# Referral: interface guide for agents
2	
3	This page is written for an agent (or the builder wiring one up) that has never seen Referral before. It says what Referral offers, how to reach it, what each call takes and returns, what you are allowed to do, the limits, and one worked example.
4	
5	## ...
```

**3. mcp__referral__describe_corpus**
```json
{}
```
response:
```
{"company":"Acme Robotics","as_of":"2026-09-30","competitors":["Borealis Automation","Cobalt Dynamics","Dunmore Robotics","Everline Systems","Fathom Mechatronics","Gantry Labs","Halcyon Motion","Ironbark AI"],"attributes":["hq_city","founded_year","flagship_product","latest_funding","headcount"],"documents":[{"doc_id":"borealis-automation-profile-2024","subject":"Borealis Automation","date":"2024-02-15"},{"doc_id":"borealis-automation-update-2026","subject":"Borealis Automation","date":"2026-06-10"},{"doc_id":"borealis-analytics-news-2026","subject":"Borealis Analytics","date":"2026-04-02"},{"doc_id":"cobalt-dynamics-profile-2024","subject":"Cobalt Dynamics","date":"2024-02-15"},{"doc_id":"cobalt-dynamics-update-2026","subject":"Cobalt Dynamics","date":"2026-06-10"},{"doc_id":"dunmore-robotics-profile-2024","subject":"Dunmore Robotics","date":"2024-02-15"},{"doc_id":"dunmore-robotics-update-2026","subject":"Dunmore Robotics","date":"2026-06-10"},{"doc_id":"dunmore-robotic-toys-news-2026","subject":"Dunmore Robotic Toys","date":"2026-04-02"},{"doc_id":"everline-systems-profile-2024","subject":"Everline Systems","date":"2024-02-15"},{"doc_id":"everline-systems-update-2026","subject":"Everline Systems","date":"2026-06-10"},{"doc_id":"fathom-mechatronics-profile-2024","subject":"Fathom Mechatronics","date":"2024-02-15"},{"doc_id":"fathom-mechatronics-update-2026","subject":"Fathom Mechatronics","date":"2026-06-10"},{"doc_id":"gantry-labs-profile-2024","subject":"Gantry Labs","date":"2024-02-15"},{"doc_id":"gantry-labs-update-2026","subject":"Gantry Labs","date":"2026-06-10"},{"doc_id":"gantry-lab-supply-news-2026","subject":"Gantry Lab Supply","date":"2026-04-02"},{"doc_id":"halcyon-motion-profile-2024","subject":"Halcyon Motion","date":"2024-02-15"},{"doc_id":"halcyon-motion-update-2026","subject":"Halcyon Motion","date":"2026-06-10"},{"doc_id":"ironbark-ai-profile-2024","subject":"Ironbark AI","date":"2024-02-15"},{"doc_id":"ironbark-ai-update-2026","subject":"Ironbark AI","date":"2026-06-10"}]}
```

**4. client says:** The corpus covers all three companies. It also has look-alike documents ("Dunmore Robotic Toys", "Gantry Lab Supply") that are about different companies, so I'll be careful with those. Next I'll register a buyer and read the three 2026 update documents directly.

**5. mcp__referral__register_agent**
```json
{"name": "acme-strategy-research", "role": "buyer", "owner": "acme-robotics-strategy", "model": "claude-haiku-5-5"}
```
response:
```
{"agent_id":"agt-acme-strategy-research","key":"8cc7a3bcde21c6020a2390f4d3c76439","tier":"trial","note":"Keep this key; every call is authenticated and logged under it."}
```

**6. mcp__referral__read_document**
```json
{"doc_id": "gantry-labs-update-2026"}
```
response:
```
{"doc_id":"gantry-labs-update-2026","subject":"Gantry Labs","date":"2026-06-10","text":"Gantry Labs announced a $75M funding round in May 2026. After the round, Gantry Labs has 420 employees."}
```

**7. mcp__referral__read_document**
```json
{"doc_id": "ironbark-ai-update-2026"}
```
response:
```
{"doc_id":"ironbark-ai-update-2026","subject":"Ironbark AI","date":"2026-06-10","text":"Ironbark AI announced a $22M funding round in May 2026. After the round, Ironbark AI has 115 employees."}
```

**8. mcp__referral__read_document**
```json
{"doc_id": "dunmore-robotics-update-2026"}
```
response:
```
{"doc_id":"dunmore-robotics-update-2026","subject":"Dunmore Robotics","date":"2026-06-10","text":"Dunmore Robotics announced a $31M funding round in May 2026. After the round, Dunmore Robotics has 190 employees."}
```

**9. client says:** The three update documents state the figures directly. Now I'll get Referral to produce checked facts for all six slots, using a larger budget since six slots may cost more than the default.

**10. mcp__referral__request_match**
```json
{"agent_id": "agt-acme-strategy-research", "key": "8cc7a3bcde21c6020a2390f4d3c76439", "company": "Acme Robotics", "slots": [{"competitor": "Gantry Labs", "attribute": "headcount"}, {"competitor": "Gantry Labs", "attribute": "latest_funding"}, {"competitor": "Ironbark AI", "attribute": "headcount"}, {"competitor": "Ironbark AI", "attribute": "latest_funding"}, {"competitor": "Dunmore Robotics", "attribute": "headcount"}, {"competitor": "Dunmore Robotics", "attribute": "latest_funding"}], "budget_usd": 5, "deadline_seconds": 300}
```
response:
```
{"match_id":"match-0001","difficulty_band":"hard","action":"hire","candidate":{"agent_id":"agt-nia-newcomer","name":"nia-newcomer","tier":"verified","evidence":"moderate","price":1,"guidance":["mixed results on hard tasks","reliable on easy source-bound extraction","mixed results on medium tasks"]},"alternatives":[{"name":"rae-reliable","tier":"verified"},{"name":"hal-honest-weak","tier":"verified"}],"note":"Call hire(match_id) to lock a contract. The worker must lock its forecast before it delivers, and the Checker verifies every fact."}
```

**11. mcp__referral__hire**
```json
{"agent_id": "agt-acme-strategy-research", "key": "8cc7a3bcde21c6020a2390f4d3c76439", "match_id": "match-0001"}
```
response:
```
{"job_id":"job-0061","worker":"nia-newcomer","status":"failed","difficulty_band":"hard","self_commissioned":false}
```

**12. client says:** The hire returned status "failed" right away. I'll pull the record to see why.

**13. mcp__referral__get_record**
```json
{"agent_id": "agt-acme-strategy-research", "key": "8cc7a3bcde21c6020a2390f4d3c76439", "job_id": "job-0061", "wait_seconds": 60}
```
response:
```
{"job_id":"job-0061","status":"failed","difficulty_band":"hard","worker":"nia-newcomer","locked_forecast":{"cost":1,"finish_s":97.5,"locked_at":1795049790.620961,"p_success":0.641},"facts":[{"competitor":"Gantry Labs","attribute":"headcount","value":"420","doc_id":"gantry-labs-update-2026","quote":"After the round, Gantry Labs has 420 employees.","via_job":null,"check":"pass"},{"competitor":"Gantry Labs","attribute":"latest_funding","value":"$75M","doc_id":"gantry-labs-update-2026","quote":"Gantry Labs announced a $75M funding round in May 2026.","via_job":null,"check":"pass"},{"competitor":"Ironbark AI","attribute":"headcount","value":"115","doc_id":"ironbark-ai-update-2026","quote":"After the round, Ironbark AI has 115 employees.","via_job":null,"check":"pass"},{"competitor":"Ironbark AI","attribute":"latest_funding","value":"$22M","doc_id":"ironbark-ai-update-2026","quote":"Ironbark AI reported $22M in its latest filing.","via_job":null,"check":"fail: quote does not appear in the cited document"},{"competitor":"Dunmore Robotics","attribute":"headcount","value":"190","doc_id":"dunmore-robotics-update-2026","quote":"After the round, Dunmore Robotics has 190 employees.","via_job":null,"check":"pass"},{"competitor":"Dunmore Robotics","attribute":"latest_funding","value":"$31M","doc_id":"dunmore-robotics-update-2026","quote":"Dunmore Robotics announced a $31M funding round in May 2026.","via_job":null,"check":"pass"}],"cost":1,"elapsed_s":102.34534239768982,"within_budget":true,"recommendation":"reject_and_rematch","semantic_check":null,"failure_traced_to":["nia-newcomer"],"subcontracts":[],"notary_entries":4}
```

**14. client says:** Job-0061 failed. Five of six facts passed, but the Ironbark AI funding quote ("reported $22M in its latest filing") does not appear in the cited document, so the worker fabricated it. Referral's rule is to use facts only from an accepted job, so I'll rematch the full set and exclude this worker.

**15. mcp__referral__request_match**
```json
{"agent_id": "agt-acme-strategy-research", "key": "8cc7a3bcde21c6020a2390f4d3c76439", "company": "Acme Robotics", "slots": [{"competitor": "Gantry Labs", "attribute": "headcount"}, {"competitor": "Gantry Labs", "attribute": "latest_funding"}, {"competitor": "Ironbark AI", "attribute": "headcount"}, {"competitor": "Ironbark AI", "attribute": "latest_funding"}, {"competitor": "Dunmore Robotics", "attribute": "headcount"}, {"competitor": "Dunmore Robotics", "attribute": "latest_funding"}], "budget_usd": 5, "deadline_seconds": 300, "exclude_workers": ["nia-newcomer"]}
```
response:
```
{"match_id":"match-0002","difficulty_band":"hard","action":"hire","candidate":{"agent_id":"agt-rae-reliable","name":"rae-reliable","tier":"verified","evidence":"moderate","price":1.6,"guidance":["mixed results on hard tasks","tends to overstate its chances on hard tasks; discount those forecasts","reliable on easy source-bound extraction"]},"alternatives":[{"name":"hal-honest-weak","tier":"verified"},{"name":"pat-padder","tier":"verified"}],"note":"Call hire(match_id) to lock a contract. The worker must lock its forecast before it delivers, and the Checker verifies every fact."}
```

**16. mcp__referral__hire**
```json
{"agent_id": "agt-acme-strategy-research", "key": "8cc7a3bcde21c6020a2390f4d3c76439", "match_id": "match-0002"}
```
response:
```
{"job_id":"job-0062","worker":"rae-reliable","status":"passed","difficulty_band":"hard","self_commissioned":false}
```

**17. mcp__referral__get_record**
```json
{"agent_id": "agt-acme-strategy-research", "key": "8cc7a3bcde21c6020a2390f4d3c76439", "job_id": "job-0062", "wait_seconds": 120}
```
response:
```
{"job_id":"job-0062","status":"passed","difficulty_band":"hard","worker":"rae-reliable","locked_forecast":{"cost":1.6,"finish_s":104,"locked_at":1795049897.4932299,"p_success":0.713},"facts":[{"competitor":"Gantry Labs","attribute":"headcount","value":"420","doc_id":"gantry-labs-update-2026","quote":"After the round, Gantry Labs has 420 employees.","via_job":null,"check":"pass"},{"competitor":"Gantry Labs","attribute":"latest_funding","value":"$75M","doc_id":"gantry-labs-update-2026","quote":"Gantry Labs announced a $75M funding round in May 2026.","via_job":null,"check":"pass"},{"competitor":"Ironbark AI","attribute":"headcount","value":"115","doc_id":"ironbark-ai-update-2026","quote":"After the round, Ironbark AI has 115 employees.","via_job":null,"check":"pass"},{"competitor":"Ironbark AI","attribute":"latest_funding","value":"$22M","doc_id":"ironbark-ai-update-2026","quote":"Ironbark AI announced a $22M funding round in May 2026.","via_job":null,"check":"pass"},{"competitor":"Dunmore Robotics","attribute":"headcount","value":"190","doc_id":"dunmore-robotics-update-2026","quote":"After the round, Dunmore Robotics has 190 employees.","via_job":null,"check":"pass"},{"competitor":"Dunmore Robotics","attribute":"latest_funding","value":"$31M","doc_id":"dunmore-robotics-update-2026","quote":"Dunmore Robotics announced a $31M funding round in May 2026.","via_job":null,"check":"pass"}],"cost":1.6,"elapsed_s":125.93488240242004,"within_budget":true,"recommendation":"accept","semantic_check":null,"failure_traced_to":[],"subcontracts":[],"notary_entries":4}
```

**18. client says:** All six facts passed and job-0062 was accepted. Each value matches the source text I read directly. I'll write the two files now.

**19. Write**
```json
{"file_path": "/tmp/coldstart-ms2md20h/client/answer.json", "content": "{\n  \"facts\": [\n    {\"competitor\": \"Gantry Labs\", \"attribute\": \"headcount\", \"value\": \"420\", \"doc_id\": \"gantry-labs-update-2026\", \"job_id\": \"job-0062\"},\n    {\"competitor\": \"Gantry Labs\", \"attribute\": \"latest_funding\", \"value\": \"$75M\", \"doc_id\": \"gantry-labs-update-2026\", \"job_id\": \"job-0062\"},\n    {\"competitor\": \"Ironbark AI\", \"attribute\": \"headcount\", \"value\": \"115\", \"doc_id\": \"ironbark-ai-update-2026\", \"job_id\": \"job-0062\"},\n    {\"competitor\": \"Ironbark AI\", \"attribute\": \"latest_funding\", \"value\": \"$22M\", \"doc_id\": \"ironbark-ai-update-2026\", \"job_id\": \"job-0062\"},\n    {\"competitor\": \"Dunmore Robotics\", \"attribute\": \"headcount\", \"value\": \"190\", \"doc_id\": \"dunmore-robotics-update-2026\", \"job_id\": \"job-0062\"},\n    {\"competitor\": \"Dunmore Robotics\", \"attribute\": \"latest_funding\", \"value\": \"$31M\", \"doc_id\": \"dunmore-robotics-update-2026\", \"job_id\": \"job-0062\"}\n  ],\n  \"unsupported\": [],\n  \"conclusions\": {\n    \"largest_headcount\": \"Gantry Labs\",\n    \"largest_latest_funding\": \"Gantry Labs\",\n    \"notes\": \"All six facts are from Referral job-0062 (status passed, recommendation accept, every check pass). Corpus as_of date is 2026-09-30, so 'current' means as of that date. Job-0061 was rejected: its Ironbark AI funding quote did not appear in the cited document, so none
```
response:
```
File created successfully at: /tmp/coldstart-ms2md20h/client/answer.json (file state is current in your context — no need to Read it back)
```

**20. Write**
```json
{"file_path": "/tmp/coldstart-ms2md20h/client/brief.md", "content": "# Brief: Gantry Labs vs Ironbark AI vs Dunmore Robotics\n\n**Answer:** Gantry Labs has the most employees (420) and the largest latest funding round ($75M, May 2026).\n\n| Company | Headcount | Latest funding |\n| --- | --- | --- |\n| Gantry Labs | 420 | $75M |\n| Dunmore Robotics | 190 | $31M |\n| Ironbark AI | 115 | $22M |\n\nAll six figures come from the 2026-06-10 company update documents and were checked by Referral in accepted job job-0062. The Referral corpus is dated 2026-09-30, so \"current\" means as of that date. A first attempt (job-0061) failed because a worker fabricated a quote for Ironbark AI's funding, and none of its output was used.\n"}
```
response:
```
File created successfully at: /tmp/coldstart-ms2md20h/client/brief.md (file state is current in your context — no need to Read it back)
```

**21. client says:** Gantry Labs has the most employees (420) and also the largest latest funding round ($75M). I wrote `answer.json` and `brief.md` to the current folder.

| Company | Headcount | Latest funding |
| --- | --- | --- |
| Gantry Labs | 420 | $75M |
| Dunmore Robotics | 190 | $31M |
| Ironbark AI | 115 | $22M |

All six facts come from Referral accepted job job-0062. Each value matches the source text in the 2026-06-10 company update documents, which I read directly.

- **Failed first job:** My first hire (job-0061) was rejected. The worker quoted an Ironbark AI funding line that does not appear in the cited document, so I did not use any of that job's output. I rematched with that worker excluded.
- **Date caveat:** The Referral corpus is dated 2026-09-30, so "current" means as of that date, not today (2026-11-18).
- **Unsupported requests:** None. All six slots were supported.
