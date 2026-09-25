# GitHub 上的假设与策略：一次调研（2026-09-25）

三路并行调研：A 股策略仓库（约 60 组关键词、20 个仓库）、有经济机制的异象及其论文/实现（18 项）、用 LLM 生成假设的开源项目（12 个）。目的不是抄策略，是找**有具名行为人**的假设，以及别人怎么组织假设生成。

## 一、A 股开源仓库里有什么

GitHub 上的 A 股仓库绝大多数是执行框架（QMT / PTrade / 掘金对接）或技术指标集，写出「谁被迫交易」的极少。有内容的集中在两处：聚宽社区策略汇编（matrixhawk 收录 1,098 只，2020–2025）和可转债工具。

宣称的收益普遍不含成本或样本极短（「龙虎榜挖掘年化 1400%」滑点设 0；「13 周 alpha +15.7%」）。少数诚实的自报：youzi 情绪策略 2019H1 −4.9% vs 基准 +27%；XiyiRao 自证纯价格动量验证集全负、幸存者偏差把 +1.2% 变成 +36.5%。

去重后的假设按机制分组：

| 机制 | 假设 | 我们的状态 |
|---|---|---|
| 强制流 | 指数定期调整的被动买入 | **已通过**，策略 930a609a |
| 强制流 | 限售解禁 | 规则 post_unlock_20d 已有（解禁后正漂移） |
| 强制流 | 转债发行：股权登记日前抢配售权、登记日后卸货 | 未测，数据可得（cb_issue） |
| 强制流 | 强赎公告后转债持有人被迫转股卖出 | 只能做空正股；cb_call 接口不可用 |
| 强制流 | 季末基金重仓股拉抬 | 未测，2017 年后有监管处罚，效应可能已消失 |
| 制度 | 国九条分红不达标 → ST | 样本太小 |
| 知情者 | 董监高本人增持 | **已通过**，两条策略在跟踪 |
| 知情者 | 大股东增持 | 已测，不通过（涨后增持） |
| 知情者 | 回购 | 事件通过、真实成交不成立 |
| 知情者 | 北向十大活跃股 | 2024-08 起日度数据停披露 |
| 知情者 | 龙虎榜机构席位、券商金股、分析师评级 | 龙虎榜名字在我们的关注度检验里是跑输的；金股、评级数据不可得 |
| 注意力 | 业绩预告反应不足 | 已测，不通过（公告前已反应完） |
| 注意力 / 制度 | 首板次日低开（T+1 锁仓的打板者被迫止损） | 事件由价格定义，边界情形，不作主假设 |
| 跨市场 | AH 折价收敛 | 需要港股价格 |
| 纯技术 | 小市值轮动、ETF 动量、双均线、双低转债、ML 多因子 | 已知失效，不再列 |

## 二、异象文献给出的、我们还没碰的

| 异象 | 机制与行为人 | 文献 | A 股数据 | 长多可交易 |
|---|---|---|---|---|
| 除息日红利税 | 持股不满一年的短线持有者为避差别化红利税在除息前卖出；除息前 CAR 正、后负（张俊生 2008；Elton–Gruber 1970） | 有 | Tushare `dividend`（REST 可用） | 可：除息前持有、除息前卖出 |
| 股权质押平仓压力后的反转 | 质权人强平，跌破平仓线后的被迫卖出结束即反转（Li–Qian–Wang–Zhu 2019；BIS 2018） | 有，2018 | `pledge_stat` / `pledge_detail`（REST 可用） | 可，但平仓线要自己估，噪声最大 |
| 季末重仓股拉抬 | 基金经理为排名在季末尾盘拉抬重仓股，次日反转（Ouyang–Cao 2020，样本止于 2016） | 有 | `fund_portfolio`（季报前十大，REST 可用） | 可：季末前一日买、季末收盘卖；先验证 2017 后是否还在 |
| 基金赎回抛售（Coval–Stafford） | 遭大额赎回的基金必须卖 | 仅交叉上市研究 | 需要季度全持仓，A 股季报只有前十大 | 数据不够 |
| 杠杆爆仓（Bian et al. 2018） | 触及杠杆上限的融资账户被迫卖，40 日内反转 | 账户级 | 我们用融资余额代理测过（H-D），不通过 | — |
| 国家队 | 政府为稳市必须买 | 有 | 季频前十大股东，不可预知 | 不可预知 |
| 期权到期 / GEX | 做市商对冲 | 美股 | A 股无个股期权 | 不可 |

Li–Liu–Liu–Wei（2023, MS）对 469 个 A 股异象的结论值得记住：用主板断点加市值加权后 83% 不显著。我们所有检验都是全 A 等权，微盘股的贡献要单独看。

## 三、LLM 假设生成项目怎么做

RD-Agent、QuantaAlpha、AlphaSchema、AlphaDiverse、Hubble、AlphaAgent、AlphaSpire、AlphaPROBE、atlas-gic、TradingAgents、FinRobot、llm-alpha-mining。**没有一个附带机制导向的假设库。**

- RD-Agent 的数据模板只有 `$open $close $high $low $volume $factor`，假设 prompt 唯一的方向提示是 "Try the easiest and fastest factors to experiment with from various perspectives first"，15 轮后换成 "try factors that can achieve high IC"。反馈 prompt 写死 "Any small improvement should be considered for inclusion as SOTA"。「20 日成交额变异系数」就是这套设定的自然产物。
- QuantaAlpha 的兜底方向全是量价（"mean reversion opposite to momentum"、"liquidity features in market microstructure"、"volatility regime switching"）。AlphaDiverse 的 38 个「经济机制」分六类，全部可由 OHLCV 算出。AlphaSchema 的 54 个 event family 是 K 线语义（vwap、breakout、oscillator）。Hubble 六个 family 同样。
- 触及机制的只有三处，都很薄：AlphaAgent 给了 PIT 的 `$funda_days_since_disclose`（披露日历）并要求候选跨信息维度；AlphaSpire 的字段库有 analyst / news；atlas-gic 的反身性规则写了 "Fund drawdown >10% → forced selling cascade"，但它是自由文本荐股。
- 没有任何仓库以可测试假设的形式编码：指数纳入与被动流、两融 / 解禁 / 质押、涨跌停与 T+1 约束、大宗 / 龙虎榜 / 北向、供应链滞后传导、分析师覆盖、财报预告制度、ETF 申赎。

可以搬的是**格式和纪律**，不是内容：

1. 假设的结构字段（AlphaDiverse）：event、economic explanation、horizon、condition、expected direction、relation to existing factors。要求每轮先声明机制 family 再写公式。
2. 强制换维度而非换窗口（AlphaAgent）："每轮先归因上一轮结果，再设计下一代；避免仅改窗口长度的同质批次"、"连续 2 轮无改善时，强制引入未用过的信息源或算子族"。
3. 负向检索（Hubble）：把 SOTA 库里数量最多的前 3 个 family 作为回避清单注入，每 family 最多 2 个候选。
4. 假设登记簿（llm-alpha-mining）：`candidate_id, spec_hash, semantic_hash, campaign_round, lineage_depth, proposal_kind, parent_ids`，语义哈希排除方向（同一信号翻个号仍算重复）。
5. 门禁：删掉 "any small improvement"，换成 train / val 同号、月度 IC 正占比 > 0.7、截面自相关 > 0.6、与库内因子截面相关低于阈值；多重检验阈值随累计试验次数抬升（Bonferroni-dynamic），开跑前锁定。
6. 数据面：以上 prompt 改动在只有 6 列量价的数据模板上无效。要把成分股变更、融资余额、解禁日、披露日历、PIT 基本面喂给 LLM，它才有可能提出机制假设。

## 四、下一批预注册候选（按机制强度 × 数据可得 × 长多可交易排序）

1. **转债发行抢权**：事件 = 转债发行公告日 A，股权登记日 R。预期正股 [A+1, R] 正超额，[R+1, R+3] 负超额，幅度与百元含权正相关。行为人：想拿配售权的投资者。数据 `cb_issue`（ann_date、shd_ration_record_date、shd_ration_ratio）+ `cb_basic` + 价格。年样本 100–150。窗口只有 2–3 天，成本 0.2% 对结果影响大，要在预注册里写死。
2. **除息前红利税抢权**：事件 = 除息日，条件股息率 ≥ 阈值。预期除息前 [−20, −1] 正、[0, +5] 负。行为人：短线持有者避税卖出、长线持有者接盘。数据 `dividend`。年样本数千。
3. **季末重仓股拉抬**：事件 = 每季最后交易日，标的 = 小规模主动基金前十大重仓且集中度高的股票。预期季末日正、次日负。数据 `fund_portfolio`（季频、滞后，只能用上一季报）。先用 2017–2025 验证效应是否还在。
4. **股权质押平仓压力反转**：事件 = 质押比例 ≥ 50% 且价格跌破估算平仓线。预期 [+5, +40] 正。数据 `pledge_stat` / `pledge_detail`。噪声最大，排最后。

每一条按既有规则：先写定事件、窗口、通过标准（月度 t ≥ 2、两半同正），提交后再取数，只跑一次主检验。

## 来源

调研涉及的仓库与论文链接见三份子报告（转录于本文各表）；主要仓库：microsoft/RD-Agent、QuantaAlpha/QuantaAlpha、JingyangYi/AlphaSchema、RndmVariableQ/AlphaAgent、Argithun/AlphaSpire、chrisworsey55/atlas-gic、matrixhawk/Trading_Strategies_Analysis、moria/ashare-quant-kb、Stephen-Rong/ai-investment-analyzer、OpenSourceAP/CrossSection、bkelly-lab/jkp-data、gen-li/Replicate_PEAD。
