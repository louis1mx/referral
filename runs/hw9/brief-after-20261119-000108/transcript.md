# Client transcript (brief-after-20261119-000108)

**1. Read**
```json
{"file_path": "/tmp/coldstart-9ymuf4gw/client/REFERRAL.md"}
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
{"agent_id":"agt-acme-strategy-buyer","key":"f78d65e4d05a021ac590549b0eb3a624","tier":"trial","note":"Keep this key; every call is authenticated and logged under it."}
```

**4. mcp__referral__request_match**
```json
{"agent_id": "agt-acme-strategy-buyer", "key": "f78d65e4d05a021ac590549b0eb3a624", "company": "Acme Robotics", "slots": [{"competitor": "Gantry Labs", "attribute": "headcount"}, {"competitor": "Ironbark AI", "attribute": "headcount"}, {"competitor": "Dunmore Robotics", "attribute": "headcount"}, {"competitor": "Gantry Labs", "attribute": "latest_funding"}, {"competitor": "Ironbark AI", "attribute": "latest_funding"}, {"competitor": "Dunmore Robotics", "attribute": "latest_funding"}]}
```
response:
```
{"match_id":"match-0001","difficulty_band":"hard","action":"hire","candidate":{"agent_id":"agt-nia-newcomer","name":"nia-newcomer","tier":"verified","evidence":"moderate","price":1,"guidance":["mixed results on hard tasks","reliable on easy source-bound extraction","mixed results on medium tasks"]},"alternatives":[{"name":"rae-reliable","tier":"verified"},{"name":"pat-padder","tier":"verified"}],"note":"Call hire(match_id) to lock a contract. The worker must lock its forecast before it delivers, and the Checker verifies every fact."}
```

**5. mcp__referral__hire**
```json
{"agent_id": "agt-acme-strategy-buyer", "key": "f78d65e4d05a021ac590549b0eb3a624", "match_id": "match-0001"}
```
response:
```
{"job_id":"job-0061","worker":"nia-newcomer","status":"passed","difficulty_band":"hard","self_commissioned":false}
```

**6. mcp__referral__get_record**
```json
{"agent_id": "agt-acme-strategy-buyer", "key": "f78d65e4d05a021ac590549b0eb3a624", "job_id": "job-0061"}
```
response:
```
{"job_id":"job-0061","status":"passed","difficulty_band":"hard","worker":"nia-newcomer","locked_forecast":{"cost":1,"finish_s":97.5,"locked_at":1795050266.1317067,"p_success":0.504},"facts":[{"competitor":"Gantry Labs","attribute":"headcount","value":"420","doc_id":"gantry-labs-update-2026","quote":"After the round, Gantry Labs has 420 employees.","via_job":null,"check":"pass"},{"competitor":"Ironbark AI","attribute":"headcount","value":"115","doc_id":"ironbark-ai-update-2026","quote":"After the round, Ironbark AI has 115 employees.","via_job":null,"check":"pass"},{"competitor":"Dunmore Robotics","attribute":"headcount","value":"190","doc_id":"dunmore-robotics-update-2026","quote":"After the round, Dunmore Robotics has 190 employees.","via_job":null,"check":"pass"},{"competitor":"Gantry Labs","attribute":"latest_funding","value":"$75M","doc_id":"gantry-labs-update-2026","quote":"Gantry Labs announced a $75M funding round in May 2026.","via_job":null,"check":"pass"},{"competitor":"Ironbark AI","attribute":"latest_funding","value":"$22M","doc_id":"ironbark-ai-update-2026","quote":"Ironbark AI announced a $22M funding round in May 2026.","via_job":null,"check":"pass"},{"competitor":"Dunmore Robotics","attribute":"latest_funding","value":"$31M","doc_id":"dunmore-robotics-update-2026","quote":"Dunmore Robotics announced a $31M funding round in May 2026.","via_job":null,"check":"pass"}],"cost":1,"elapsed_s":100.3996512889862,"within_budget":true,"recommendation":"accept","semantic_check":null,"failure_traced_to":[],"subcontracts":[],"notary_entries":4}
```

**7. client says:** All pass and accepted. Writing files.

**8. Write**
```json
{"file_path": "/tmp/coldstart-9ymuf4gw/client/answer.json", "content": "{\"facts\": [\n{\"competitor\": \"Gantry Labs\", \"attribute\": \"headcount\", \"value\": \"420\", \"doc_id\": \"gantry-labs-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Ironbark AI\", \"attribute\": \"headcount\", \"value\": \"115\", \"doc_id\": \"ironbark-ai-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Dunmore Robotics\", \"attribute\": \"headcount\", \"value\": \"190\", \"doc_id\": \"dunmore-robotics-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Gantry Labs\", \"attribute\": \"latest_funding\", \"value\": \"$75M\", \"doc_id\": \"gantry-labs-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Ironbark AI\", \"attribute\": \"latest_funding\", \"value\": \"$22M\", \"doc_id\": \"ironbark-ai-update-2026\", \"job_id\": \"job-0061\"},\n{\"competitor\": \"Dunmore Robotics\", \"attribute\": \"latest_funding\", \"value\": \"$31M\", \"doc_id\": \"dunmore-robotics-update-2026\", \"job_id\": \"job-0061\"}\n],\n\"unsupported\": [],\n\"conclusions\": {\"largest_headcount\": \"Gantry Labs\", \"largest_latest_funding\": \"Gantry Labs\"}}\n"}
```
response:
```
File created successfully at: /tmp/coldstart-9ymuf4gw/client/answer.json (file state is current in your context — no need to Read it back)
```

**9. Write**
```json
{"file_path": "/tmp/coldstart-9ymuf4gw/client/brief.md", "content": "Gantry Labs is the largest of the three on both measures: 420 employees and a $75M latest round (May 2026). Dunmore Robotics has 190 employees and a $31M round, and Ironbark AI has 115 employees and a $22M round. All six figures come from the companies' 2026-06-10 update documents (e.g. gantry-labs-update-2026) and passed Referral's source-quote check in job-0061, which Referral recommended accepting. The corpus is a fixed dataset as of 2026-09-30, so these are not live figures.\n"}
```
response:
```
File created successfully at: /tmp/coldstart-9ymuf4gw/client/brief.md (file state is current in your context — no need to Read it back)
```

**10. client says:** Gantry Labs has the most employees and also had the largest latest funding round. I wrote `answer.json` and `brief.md` in the current folder.

| Company | Headcount | Latest funding |
|---|---|---|
| Gantry Labs | 420 | $75M |
| Dunmore Robotics | 190 | $31M |
| Ironbark AI | 115 | $22M |

I hired one Referral worker, nia-newcomer, for all six facts (job-0061). Every fact passed the check, and Referral recommended accepting the result. Each figure quotes the company's 2026 update document, such as `gantry-labs-update-2026`. The funding rounds were all announced in May 2026.

The data comes from Referral's fixed test corpus as of 2026-09-30, not live sources. Nothing was left unsupported, so `unsupported` in `answer.json` is empty.
