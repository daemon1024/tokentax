## Accounting (every row, deduplicated; first observation wins)

| model | arm | answered | no_answer | timeout | transport | unavailable |
|---|---|---|---|---|---|---|
| beam | P | 30 | 0 | 0 | 0 | 0 |
| beam | S | 30 | 0 | 0 | 0 | 0 |
| beam | T | 30 | 0 | 0 | 0 | 0 |
| beam | TI | 30 | 0 | 0 | 0 | 0 |
| minimax-m3.1-flash | P | 0 | 26 | 4 | 0 | 0 |
| minimax-m3.1-flash | S | 0 | 24 | 6 | 0 | 0 |
| minimax-m3.1-flash | T | 28 | 1 | 1 | 0 | 0 |
| minimax-m3.1-flash | TI | 24 | 5 | 1 | 0 | 0 |

complete quadruples: 60 over 2 model(s), 30 seed(s)

## All models (complete quadruples)

| arm | cells | correct | mean F1 | failures (no_answer/timeout) | median tok (answered) | mean tok (answered) | mean tok (all observed) | tokens/correct | mean rounds |
|---|---|---|---|---|---|---|---|---|---|
| P | 60 | 5 | 0.153 | 30 | 14,824 | 16,913 | 141,944 | 1,703,330 | 7.2 |
| S | 60 | 6 | 0.157 | 30 | 12,180 | 15,631 | 136,286 | 1,362,862 | 7.0 |
| T | 60 | 58 | 0.965 | 2 | 5,342 | 57,565 | 60,024 | 62,094 | 4.5 |
| TI | 60 | 54 | 0.900 | 6 | 9,291 | 59,819 | 76,398 | 84,887 | 5.1 |

### beam

| arm | cells | correct | mean F1 | failures (no_answer/timeout) | median tok (answered) | mean tok (answered) | mean tok (all observed) | tokens/correct | mean rounds |
|---|---|---|---|---|---|---|---|---|---|
| P | 30 | 5 | 0.306 | 0 | 14,824 | 16,913 | 16,913 | 101,477 | 4.3 |
| S | 30 | 6 | 0.314 | 0 | 12,180 | 15,631 | 15,631 | 78,153 | 4.0 |
| T | 30 | 30 | 1.000 | 0 | 3,012 | 3,553 | 3,553 | 3,553 | 2.1 |
| TI | 30 | 30 | 1.000 | 0 | 2,941 | 4,540 | 4,540 | 4,540 | 2.2 |

### minimax-m3.1-flash

| arm | cells | correct | mean F1 | failures (no_answer/timeout) | median tok (answered) | mean tok (answered) | mean tok (all observed) | tokens/correct | mean rounds |
|---|---|---|---|---|---|---|---|---|---|
| P | 30 | 0 | 0.000 | 30 | — | — | 266,976 | — | 10.2 |
| S | 30 | 0 | 0.000 | 30 | — | — | 256,942 | — | 10.1 |
| T | 30 | 28 | 0.931 | 2 | 96,423 | 115,434 | 116,494 | 124,815 | 6.9 |
| TI | 30 | 24 | 0.799 | 6 | 122,618 | 128,918 | 148,257 | 185,321 | 8.0 |

## Contrasts (b vs a)

- S -> T: TPC ratio 0.045466991955915345, 95% CI [0.016228974216286395, 0.08413667185616976] (undefined draws 5); mean dF1 0.8085083333333334 (sign {'n': 30, 'pos': 30, 'neg': 0, 'ties': 0, 'p': 1.862645149230957e-09}); median ln tok ratio (answered pairs) -1.400218339882874 (sign {'n': 30, 'pos': 6, 'neg': 24, 'ties': 0, 'p': 0.001430906355381012})
- S -> TI: TPC ratio 0.05809057485775703, 95% CI [0.021040232170129274, 0.10779007980812969] (undefined draws 5); mean dF1 0.7428366666666667 (sign {'n': 30, 'pos': 30, 'neg': 0, 'ties': 0, 'p': 1.862645149230957e-09}); median ln tok ratio (answered pairs) -1.236214317148262 (sign {'n': 30, 'pos': 8, 'neg': 22, 'ties': 0, 'p': 0.016124801710247993})
- T -> TI: TPC ratio 1.3773139526221068, 95% CI [1.0940170431489404, 1.7549509845277584] (undefined draws 0); mean dF1 -0.06567166666666667 (sign {'n': 7, 'pos': 2, 'neg': 5, 'ties': 23, 'p': 0.453125}); median ln tok ratio (answered pairs) -0.032265482583543115 (sign {'n': 30, 'pos': 13, 'neg': 17, 'ties': 0, 'p': 0.584664711728692})
- P -> S: TPC ratio 0.7701545643691912, 95% CI [0.26321958935835915, 1.9977606233644698] (undefined draws 24); mean dF1 0.003801666666666668 (sign {'n': 10, 'pos': 6, 'neg': 4, 'ties': 20, 'p': 0.75390625}); median ln tok ratio (answered pairs) 0.06086746854727936 (sign {'n': 30, 'pos': 17, 'neg': 13, 'ties': 0, 'p': 0.584664711728692})
- P -> T: TPC ratio 0.0350166113829855, 95% CI [0.011515389931651658, 0.06888331242158093] (undefined draws 19); mean dF1 0.81231 (sign {'n': 30, 'pos': 30, 'neg': 0, 'ties': 0, 'p': 1.862645149230957e-09}); median ln tok ratio (answered pairs) -1.6427021884063393 (sign {'n': 30, 'pos': 8, 'neg': 22, 'ties': 0, 'p': 0.016124801710247993})
- P -> TI: TPC ratio 0.044738721373531756, 95% CI [0.014071520675507002, 0.08835867268979018] (undefined draws 19); mean dF1 0.7466383333333333 (sign {'n': 30, 'pos': 30, 'neg': 0, 'ties': 0, 'p': 1.862645149230957e-09}); median ln tok ratio (answered pairs) -1.461200906145212 (sign {'n': 30, 'pos': 7, 'neg': 23, 'ties': 0, 'p': 0.005222879350185394})

H1 (T vs S): PAYS; fired = []

H2 (TI vs S): PAYS; fired = []

H3 (TI cheaper than T): NOT SHOWN; ratio 1.3773139526221068, tok sign p 0.584664711728692, mean dF1 -0.06567166666666667, replicate noise |ln| 0.20773764282272605
