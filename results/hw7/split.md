# HW7 split and seeds (committed before any run, 2026-11-04)

Competitors of Acme Robotics in the fictional corpus, split into a tuning group and a fresh group.
Nothing is tuned on the fresh group.

| Group | Competitors | Look-alike firms |
|---|---|---|
| Tuning (5) | Borealis Automation, Cobalt Dynamics, Everline Systems, Fathom Mechatronics, Ironbark AI | Borealis Automation |
| Fresh (3) | Dunmore Robotics, Gantry Labs, Halcyon Motion | Dunmore Robotics, Gantry Labs |

The fresh group holds two look-alike firms so hard tasks do not repeat the same two slots.

Seeds (tasks are drawn with `Corpus.make_task(rng, band, competitors=...)`, `rng = random.Random(f"hw7-<step>|<seed>")`; warm-up uses `hw7-warmup|7001`):

| Step | Competitors | Seed | Tasks |
|---|---|---|---|
| Warm-up | tuning | 7001 | 6 (2 per band), the same for every worker |
| Pilot | tuning | 7000 | 2 (easy, hard) |
| Main run | fresh | 7002 | 12 (4 per band) |
| Limit test | tuning | 7003 | 6 (2 per band) |
| Retest | fresh | 7004 | 6 (2 per band) |

Simulated personas use seed 865 plus the repeat number. Settings live in `src/referral/hw7.py`.
