# Per-request forensics V3: analysis (generated; do not edit)

Rows: 450, observed 450, not observed {'transport': 0, 'unavailable': 0}, estimated spend $24.46.

## beam

| arm | obs | right | no_answer | timeout | tok median | tok mean | tokens / right | rounds med | grep id | lookup id |
|---|---|---|---|---|---|---|---|---|---|---|
| P | 30 | 6 | 0 | 0 | 14,189.50 | 16,511 | 82,554 | 4.50 | 0 | 0 |
| S | 30 | 7 | 0 | 0 | 14,167.50 | 17,171 | 73,589 | 4 | 0 | 0 |
| T | 30 | 30 | 0 | 0 | 2,987.50 | 3,566 | 3,566 | 2 | 0 | 30 |
| Tt | 30 | 25 | 0 | 0 | 14,104 | 15,847 | 19,016 | 4 | 26 | 30 |
| Th | 30 | 30 | 0 | 0 | 3,111.50 | 4,592 | 4,592 | 2 | 0 | 30 |

| contrast | pairs | right a→b | TPC a→b | ratio | correct sign p | tokens sign p | rounds med a→b | rounds sign p | ΔF1 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| S→Tt (printed id) | 30 | 7→25 | 73,589→19,016 | 0.26 | 7.63e-06 | 0.585 | 4→4 | 0.307 | 0.53 | supported |
| Tt→T (lookup) | 30 | 25→30 | 19,016→3,566 | 0.19 | 0.0625 | 1.86e-09 | 4→2 | 1.86e-09 | 0.11 | supported |
| T→Th (tell it) | 30 | 30→30 | 3,566→4,592 | 1.29 | 1 | 8.68e-07 | 2→2 | 0.625 | 0 | not shown |
| S→T (printed id + lookup) | 30 | 7→30 | 73,589→3,566 | 0.05 | 2.38e-07 | 0.0428 | 4→2 | 9.54e-07 | 0.65 | supported |
| P→S (service.name) | 30 | 6→7 | 82,554→73,589 | 0.89 | 1 | 0.00522 | 4.50→4 | 0.388 | 0.03 | not shown |

## deepseek-v4-pro:0813

| arm | obs | right | no_answer | timeout | tok median | tok mean | tokens / right | rounds med | grep id | lookup id |
|---|---|---|---|---|---|---|---|---|---|---|
| P | 30 | 2 | 20 | 0 | 261,035 | 218,367 | 3,275,500 | 14 | 0 | 0 |
| S | 30 | 13 | 11 | 0 | 209,574.50 | 185,845 | 428,872 | 11 | 0 | 0 |
| T | 30 | 28 | 2 | 0 | 7,061.50 | 25,960 | 27,814 | 3 | 10 | 30 |
| Tt | 30 | 29 | 0 | 1 | 38,568.50 | 54,543 | 56,424 | 7 | 30 | 30 |
| Th | 30 | 30 | 0 | 0 | 5,378 | 4,851 | 4,851 | 2 | 2 | 30 |

| contrast | pairs | right a→b | TPC a→b | ratio | correct sign p | tokens sign p | rounds med a→b | rounds sign p | ΔF1 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| S→Tt (printed id) | 30 | 13→29 | 428,872→56,424 | 0.13 | 0.000145 | 0.00131 | 11→7 | 0.00408 | 0.42 | supported |
| Tt→T (lookup) | 30 | 29→28 | 56,424→27,814 | 0.49 | 1 | 4.17e-07 | 7→3 | 1.62e-06 | -0.03 | supported |
| T→Th (tell it) | 30 | 28→30 | 27,814→4,851 | 0.17 | 0.5 | 0.0872 | 3→2 | 0.000221 | 0.07 | supported (fewer rounds) |
| S→T (printed id + lookup) | 30 | 13→28 | 428,872→27,814 | 0.06 | 0.000729 | 1.53e-05 | 11→3 | 8.68e-07 | 0.38 | supported |
| P→S (service.name) | 30 | 2→13 | 3,275,500→428,872 | 0.13 | 0.000977 | 0.344 | 14→11 | 8.8e-05 | 0.32 | supported |

## minimax-m3.1-flash

| arm | obs | right | no_answer | timeout | tok median | tok mean | tokens / right | rounds med | grep id | lookup id |
|---|---|---|---|---|---|---|---|---|---|---|
| P | 30 | 10 | 16 | 0 | 252,873 | 216,690 | 650,071 | 10 | 0 | 0 |
| S | 30 | 14 | 11 | 0 | 250,356.50 | 201,983 | 432,821 | 9 | 0 | 0 |
| T | 30 | 30 | 0 | 0 | 14,238.50 | 14,111 | 14,111 | 4 | 19 | 30 |
| Tt | 30 | 30 | 0 | 0 | 23,822 | 34,102 | 34,102 | 6 | 30 | 30 |
| Th | 30 | 30 | 0 | 0 | 5,826 | 7,244 | 7,244 | 2 | 9 | 30 |

| contrast | pairs | right a→b | TPC a→b | ratio | correct sign p | tokens sign p | rounds med a→b | rounds sign p | ΔF1 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| S→Tt (printed id) | 30 | 14→30 | 432,821→34,102 | 0.08 | 3.05e-05 | 0.00443 | 9→6 | 0.00232 | 0.45 | supported |
| Tt→T (lookup) | 30 | 30→30 | 34,102→14,111 | 0.41 | 1 | 5.77e-08 | 6→4 | 3.73e-09 | 0.00 | supported |
| T→Th (tell it) | 30 | 30→30 | 14,111→7,244 | 0.51 | 1 | 0.0161 | 4→2 | 0.00154 | 0 | supported (fewer rounds) |
| S→T (printed id + lookup) | 30 | 14→30 | 432,821→14,111 | 0.03 | 3.05e-05 | 3.81e-06 | 9→4 | 3.73e-09 | 0.45 | supported |
| P→S (service.name) | 30 | 10→14 | 650,071→432,821 | 0.67 | 0.289 | 0.267 | 10→9 | 0.572 | 0.14 | not shown |

## Fresh controls vs V2 (not decision-bearing)

| model arm | right V2→V3 | TPC V2→V3 | tok median V2→V3 |
|---|---|---|---|
| beam P | 5→6 | 101,477→82,554 | 14,823.50→14,189.50 |
| beam S | 6→7 | 78,153→73,589 | 12,180.50→14,167.50 |
| beam T | 30→30 | 3,553→3,566 | 3,012.50→2,987.50 |
| minimax-m3.1-flash P | 0→10 | –→650,071 | 284,384→252,873 |
| minimax-m3.1-flash S | 0→14 | –→432,821 | 270,813.50→250,356.50 |
| minimax-m3.1-flash T | 28→30 | 124,815→14,111 | 96,423→14,238.50 |
