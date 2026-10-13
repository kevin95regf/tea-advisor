# Batch H1（P0×7）证据旁路

> 2026-10-13　与 `herbs.json` 同步入库；全部 `review_status=pending`。

| id | 目录批次 | 药典 | nature | max_daily_g | 特殊 caution |
|---|---|---|---|---|---|
| huangqi | 2023-09 | p.364 甘微温；9–30g | warm | 20 | 孕妇哺乳婴幼儿不推荐 |
| dangshen | 2023-09 | p.342 甘平；9–30g；不宜藜芦 | neutral | 20 | 同上 + 藜芦 |
| danggui | 2019-08 | p.188 甘辛温；6–12g | warm | 12 | 仅香辛料/调味品公告；湿盛中满慎；煲汤向 |
| sharen | 2002-51 | p.313 辛温；3–6g 后下 | warm | 6 | 后下 |
| maiya | 2002-51 | p.212 甘平；10–15g；回乳炒用60g | neutral | 15 | 哺乳不宜常规；禁默认回乳量 |
| mugua | 2002-51 | p.111 酸温；6–9g | warm | 9 | 宣木瓜≠番木瓜 |
| pangdahai | 2002-51 | p.322 甘寒；2–3枚沸水泡服 | cold | 9（枚优先） | 脾虚便溏慎；`unsuitable_for` 含 yang_deficiency（寒凉口径） |

suitable 本批全部留空；仅胖大海因寒性 caution「虚寒」命中守卫，按库内寒凉口径写入 yang_deficiency 硬屏蔽。砂仁/当归 caution 措辞避开阴虚/湿盛关键词以免无据硬标体质。须煎煮登记见 `test_safety.EXPECTED_COOK_REQUIRED`。
