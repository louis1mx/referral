# Client transcript (brief-20261118-235242)

**1. Read**
```json
{"file_path": "/tmp/coldstart-jt8_1o18/client/REFERRAL.md"}
```
response:
```
1	# Referral: interface guide for agents
2	
3	This page is written for an agent (or the builder wiring one up) that has never seen Referral before. It says what Referral offers, how to reach it, what each call takes and returns, what you are allowed to do, the limits, and one worked example.
4	
5	## ...
```

**2. mcp__referral__describe_corpus**
```json
{}
```
response:
```
{"company":"Acme Robotics","as_of":"2026-09-30","competitors":["Borealis Automation","Cobalt Dynamics","Dunmore Robotics","Everline Systems","Fathom Mechatronics","Gantry Labs","Halcyon Motion","Ironbark AI"],"attributes":["hq_city","founded_year","flagship_product","latest_funding","headcount"],"documents":[{"doc_id":"borealis-automation-profile-2024","subject":"Borealis Automation","date":"2024-02-15"},{"doc_id":"borealis-automation-update-2026","subject":"Borealis Automation","date":"2026-06-10"},{"doc_id":"borealis-analytics-news-2026","subject":"Borealis Analytics","date":"2026-04-02"},{"doc_id":"cobalt-dynamics-profile-2024","subject":"Cobalt Dynamics","date":"2024-02-15"},{"doc_id":"cobalt-dynamics-update-2026","subject":"Cobalt Dynamics","date":"2026-06-10"},{"doc_id":"dunmore-robotics-profile-2024","subject":"Dunmore Robotics","date":"2024-02-15"},{"doc_id":"dunmore-robotics-update-2026","subject":"Dunmore Robotics","date":"2026-06-10"},{"doc_id":"dunmore-robotic-toys-news-2026","subject":"Dunmore Robotic Toys","date":"2026-04-02"},{"doc_id":"everline-systems-profile-2024","subject":"Everline Systems","date":"2024-02-15"},{"doc_id":"everline-systems-update-2026","subject":"Everline Systems","date":"2026-06-10"},{"doc_id":"fathom-mechatronics-profile-2024","subject":"Fathom Mechatronics","date":"2024-02-15"},{"doc_id":"fathom-mechatronics-update-2026","subject":"Fathom Mechatronics","date":"2026-06-10"},{"doc_id":"gantry-labs-profile-2024","subject":"Gantry Labs","date":"2024-02-15"},{"doc_id":"gantry-labs-update-2026","subject":"Gantry Labs","date":"2026-06-10"},{"doc_id":"gantry-lab-supply-news-2026","subject":"Gantry Lab Supply","date":"2026-04-02"},{"doc_id":"halcyon-motion-profile-2024","subject":"Halcyon Motion","date":"2024-02-15"},{"doc_id":"halcyon-motion-update-2026","subject":"Halcyon Motion","date":"2026-06-10"},{"doc_id":"ironbark-ai-profile-2024","subject":"Ironbark AI","date":"2024-02-15"},{"doc_id":"ironbark-ai-update-2026","subject":"Ironbark AI","date":"2026-06-10"}]}
```

**3. mcp__referral__register_agent**
```json
{"name": "acme-strategy-buyer", "role": "buyer", "owner": "acme-robotics", "model": "claude-sonnet-5-5"}
```
response:
```
{"agent_id":"agt-acme-strategy-buyer","key":"81e2256bfc47a55d45d2456835ff9ce7","tier":"trial","note":"Keep this key; every call is authenticated and logged under it."}
```

**4. mcp__referral__request_match**
```json
{"agent_id": "agt-acme-strategy-buyer", "key": "81e2256bfc47a55d45d2456835ff9ce7", "company": "Acme Robotics", "slots": [{"competitor": "Gantry Labs", "attribute": "headcount"}, {"competitor": "Ironbark AI", "attribute": "headcount"}, {"competitor": "Dunmore Robotics", "attribute": "headcount"}, {"competitor": "Gantry Labs", "attribute": "latest_funding"}, {"competitor": "Ironbark AI", "attribute": "latest_funding"}, {"competitor": "Dunmore Robotics", "attribute": "latest_funding"}]}
```
response:
```
{"match_id":"match-0001","difficulty_band":"hard","action":"hire","candidate":{"agent_id":"agt-nia-newcomer","name":"nia-newcomer","tier":"verified","evidence":"moderate","price":1,"guidance":["mixed results on hard tasks","reliable on easy source-bound extraction","mixed results on medium tasks"]},"alternatives":[{"name":"rae-reliable","tier":"verified"},{"name":"hal-honest-weak","tier":"verified"}],"note":"Call hire(match_id) to lock a contract. The worker must lock its forecast before it delivers, and the Checker verifies every fact."}
```

**5. mcp__referral__hire**
```json
{"agent_id": "agt-acme-strategy-buyer", "key": "81e2256bfc47a55d45d2456835ff9ce7", "match_id": "match-0001"}
```
response:
```
{"job_id":"job-0061","worker":"nia-newcomer","status":"passed","difficulty_band":"hard","self_commissioned":false}
```

**6. mcp__referral__get_record**
```json
{"agent_id": "agt-acme-strategy-buyer", "key": "81e2256bfc47a55d45d2456835ff9ce7", "job_id": "job-0061", "wait_seconds": 30}
```
response:
```
{"job_id":"job-0061","status":"passed","difficulty_band":"hard","worker":"nia-newcomer","locked_forecast":{"cost":1,"finish_s":97.5,"locked_at":1795049760.4975376,"p_success":0.504},"facts":[{"competitor":"Gantry Labs","attribute":"headcount","value":"420","doc_id":"gantry-labs-update-2026","quote":"After the round, Gantry Labs has 420 employees.","via_job":null,"check":"pass"},{"competitor":"Ironbark AI","attribute":"headcount","value":"115","doc_id":"ironbark-ai-update-2026","quote":"After the round, Ironbark AI has 115 employees.","via_job":null,"check":"pass"},{"competitor":"Dunmore Robotics","attribute":"headcount","value":"190","doc_id":"dunmore-robotics-update-2026","quote":"After the round, Dunmore Robotics has 190 employees.","via_job":null,"check":"pass"},{"competitor":"Gantry Labs","attribute":"latest_funding","value":"$75M","doc_id":"gantry-labs-update-2026","quote":"Gantry Labs announced a $75M funding round in May 2026.","via_job":null,"check":"pass"},{"competitor":"Ironbark AI","attribute":"latest_funding","value":"$22M","doc_id":"ironbark-ai-update-2026","quote":"Ironbark AI announced a $22M funding round in May 2026.","via_job":null,"check":"pass"},{"competitor":"Dunmore Robotics","attribute":"latest_funding","value":"$31M","doc_id":"dunmore-robotics-update-2026","quote":"Dunmore Robotics announced a $31M funding round in May 2026.","via_job":null,"check":"pass"}],"cost":1,"elapsed_s":100.39879012107849,"within_budget":true,"recommendation":"accept","semantic_check":null,"failure_traced_to":[],"subcontracts":[],"notary_entries":4}
```

**7. Write**
```json
{"file_path": "/tmp/coldstart-jt8_1o18/client/answer.json", "content": "{\"facts\": [\n{\"competitor\": \"Gantry Labs\", \"attribute\": \"headcount\", \"value\": \"420\", \"doc_id\": \"gantry-labs-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Ironbark AI\", \"attribute\": \"headcount\", \"value\": \"115\", \"doc_id\": \"ironbark-ai-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Dunmore Robotics\", \"attribute\": \"headcount\", \"value\": \"190\", \"doc_id\": \"dunmore-robotics-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Gantry Labs\", \"attribute\": \"latest_funding\", \"value\": \"$75M\", \"doc_id\": \"gantry-labs-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Ironbark AI\", \"attribute\": \"latest_funding\", \"value\": \"$22M\", \"doc_id\": \"ironbark-ai-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Dunmore Robotics\", \"attribute\": \"latest_funding\", \"value\": \"$31M\", \"doc_id\": \"dunmore-robotics-update-2026\", \"job_id\": \"job-0061\"}\n],\n\"unsupported\": [],\n\"conclusions\": {\"largest_headcount\": \"Gantry Labs\", \"largest_latest_funding\": \"Gantry Labs\"}}\n"}
```
response:
```
File created successfully at: /tmp/coldstart-jt8_1o18/client/answer.json (file state is current in your context — no need to Read it back)
```

**8. Write**
```json
{"file_path": "/tmp/coldstart-jt8_1o18/client/brief.md", "content": "# Competitor brief: headcount and latest funding\n\nGantry Labs has the most employees (420, vs. Dunmore Robotics 190 and Ironbark AI 115) and also the largest latest funding round ($75M, vs. Dunmore $31M and Ironbark $22M). All six figures come from each company's 2026-06-10 update document (e.g. gantry-labs-update-2026), extracted by worker nia-newcomer in Referral job-0061. Referral's checker passed every fact (verbatim quote containing the value) and recommended accept. The corpus is a fixed dataset as of 2026-09-30, so \"current\" means that date. The worker is only verified-tier with moderate evidence on a hard task, but the quotes are source-bound and checked.\n"}
```
response:
```
File created successfully at: /tmp/coldstart-jt8_1o18/client/brief.md (file state is current in your context — no need to Read it back)
```

**9. client says:** Gantry Labs has the most employees and also the largest latest funding round. I wrote `answer.json` and `brief.md` in the current folder.

| Company | Headcount | Latest funding |
|---|---|---|
| Gantry Labs | 420 | $75M |
| Dunmore Robotics | 190 | $31M |
| Ironbark AI | 115 | $22M |

- **Checking:** I hired one Referral worker (nia-newcomer, job-0061). Referral's check passed all six facts, and each one quotes its source document verbatim. Referral recommended accepting the result.
- **Sources:** each figure comes from that company's 2026-06-10 update document, for example `gantry-labs-update-2026`.
- **Caveats:** "Current" means as of 2026-09-30, because the corpus is a fixed dataset. The worker is only verified-tier with moderate evidence on a hard task, but the quotes themselves were checked. `unsupported` is empty because every requested fact was found.
