<template>
  <div class="studio">
    <aside class="rail">
      <a class="brand" href="#/Studio"
        ><span class="brand-mark">R</span
        ><span>RESEARCH STUDIO<small>RD-Agent × Qlib</small></span></a
      >
      <nav class="task-navigation" aria-label="工作任务">
        <button
          :class="{ selected: isResearchContext }"
          :aria-current="isResearchContext ? 'page' : undefined"
          @click="section = 'research'"
        >
          <span class="nav-symbol">◎</span
          ><span>AI 研究<small>提出假设，开发并评估因子或模型</small></span>
        </button>
        <button
          :class="{ selected: section === 'factors' }"
          :aria-current="section === 'factors' ? 'page' : undefined"
          @click="section = 'factors'"
        >
          <span class="nav-symbol">⊞</span
          ><span>因子库<small>查看、选择与管理研究因子</small></span>
          <span class="nav-count">{{ totalFactorAssets }}</span>
        </button>
        <button
          :class="{ selected: section === 'strategy' }"
          :aria-current="section === 'strategy' ? 'page' : undefined"
          @click="section = 'strategy'"
        >
          <span class="nav-symbol">◇</span
          ><span>组合回测<small>用已选因子构建并验证策略</small></span>
          <span class="nav-count">{{ selectedFactors.length }}</span>
        </button>
        <button
          :class="{ selected: section === 'runs' }"
          :aria-current="section === 'runs' ? 'page' : undefined"
          @click="section = 'runs'"
        >
          <span class="nav-symbol">↗</span
          ><span>运行记录<small>统一查看AI研究与组合回测</small></span>
        </button>
      </nav>
      <div class="navigation-note">
        <strong>标准工作流</strong>
        <p>研究产生候选 → 因子库筛选 → 组合回测验证。</p>
        <p>所有成功与失败都保留在运行记录中。</p>
      </div>
      <div class="rail-bottom">
        <i :class="{ online: environment.data_ready }"></i
        >{{ environment.data_ready ? "Qlib 数据已就绪" : "等待 Qlib 数据"
        }}<small
          >{{ environment.start || "—" }} → {{ environment.end || "—" }}</small
        ><a href="#/Playground">原生 Playground ↗</a>
      </div>
    </aside>

    <main class="workspace">
      <header class="workspace-head">
        <div>
          <div class="eyebrow">
            QUANTITATIVE RESEARCH / {{ section.toUpperCase() }}
          </div>
          <h1>{{ sections.find((s) => s.id === section)?.name }}</h1>
        </div>
        <span class="tag">{{
          isResearchContext
            ? (environment.chat_model || "未配置研究模型").replace(
                "deepseek/",
                "",
              )
            : "本地 Qlib"
        }}</span>
      </header>
      <div v-if="error" class="notice error" role="alert">
        {{ error }}<button class="text-button" @click="refresh">重试</button
        ><button class="text-button" @click="error = ''">关闭</button>
      </div>
      <div class="workspace-body">
        <template v-if="isBacktestContext"
          ><div class="task-intro">
            <p>
              用因子生成评分，再用策略把评分转成持仓。以下配置来自你的输入，不是
              AI 研究自动生成的策略。
            </p>
          </div>
          <nav class="backtest-steps" aria-label="组合回测配置步骤">
            <button
              :class="{ selected: section === 'factors' }"
              @click="section = 'factors'"
            >
              <small>01</small
              ><span>因子信号<strong>选什么股票</strong></span></button
            ><span class="step-arrow">→</span
            ><button
              :class="{ selected: section === 'strategy' }"
              @click="section = 'strategy'"
            >
              <small>02</small
              ><span>策略与回测<strong>如何持仓、调仓与验证</strong></span>
            </button>
          </nav></template
        >
        <div v-if="section === 'code'" class="research-toolbar">
          <button @click="section = 'research'">← 返回当前研究</button
          ><span class="hint">{{ traceId || "尚未选择研究实验" }}</span>
        </div>
        <template v-if="section === 'research'">
          <div class="research-toolbar">
            <label
              >当前研究实验<select
                v-model="traceId"
                aria-label="选择研究实验"
                @change="selectTrace"
              >
                <option value="">尚未选择实验</option>
                <option v-for="id in traceIds" :key="id" :value="id">
                  {{ id }}
                </option>
              </select></label
            ><button @click="refresh">刷新记录</button
            ><button
              :disabled="!codeFiles.length"
              @click="
                selectedCode = String(codeFiles.length - 1);
                section = 'code';
              "
            >
              查看研究代码
            </button>
          </div>
          <section class="experiment-shelf">
            <div class="section-heading">
              <h3>研究记录</h3>
              <span>{{ researchReports.length }} 个持久实验</span>
            </div>
            <div v-if="researchReports.length" class="experiment-grid">
              <button
                v-for="report in researchReports"
                :key="report.id"
                :class="{ chosen: report.id === traceId }"
                @click="chooseResearchReport(report.id)"
              >
                <small
                  >因子研究 ·
                  {{
                    report.status === "completed" ? "流程完成" : "执行失败"
                  }}</small
                >
                <strong>{{ report.id.split("/").at(-1) }}</strong>
                <span>打开实验报告 →</span>
              </button>
            </div>
            <p v-else class="hint">
              还没有可恢复的研究报告。启动研究后，假设、代码、评估与反馈会组成一条实验记录。
            </p>
          </section>
          <section class="intro">
            <span class="index">01 / HYPOTHESIS LAB</span>
            <h2>提出假设，用实验回答。</h2>
            <p>
              研究方向与场景约束进入假设生成；代码实验交给 Qlib
              评估，再将成功与失败的反馈带入下一轮。
            </p>
          </section>
          <div class="research-flow" aria-label="研究循环">
            <div
              v-for="(step, i) in [
                '方向与历史',
                'LLM 假设',
                '实验与代码',
                'Qlib 评估',
                '反馈迭代',
              ]"
              :key="step"
            >
              <small>0{{ i + 1 }}</small
              ><strong>{{ step }}</strong>
            </div>
          </div>
          <section v-if="researchReport.id" class="surface research-outcome">
            <div class="outcome-kicker">
              <span
                >REAL RUN /
                {{
                  researchReport.status === "completed"
                    ? "流程完成"
                    : "执行失败"
                }}</span
              >
              <span>{{
                researchReport.resumed_from ? "检查点恢复" : "完整运行"
              }}</span>
            </div>
            <div class="outcome-title">
              <div>
                <h2>研究流程完成，策略尚未通过验证</h2>
                <p>
                  沪深300 · 训练 2023 · 验证 2024 · 测试 2025 ·
                  {{ researchReport.rows?.length || 0 }} 个交易日
                </p>
              </div>
              <span class="verdict">继续研究</span>
            </div>
            <div class="comparison-grid">
              <article>
                <small>扣费年化超额收益</small>
                <strong>{{
                  percent(
                    researchReport.baseline_metrics?.[
                      "1day.excess_return_with_cost.annualized_return"
                    ],
                  )
                }}</strong
                ><span>动量基准</span>
                <b>{{
                  percent(
                    researchReport.metrics?.[
                      "1day.excess_return_with_cost.annualized_return"
                    ],
                  )
                }}</b
                ><span>加入因子</span>
              </article>
              <article>
                <small>IC</small>
                <strong>{{
                  formatMetric(researchReport.baseline_metrics?.IC)
                }}</strong
                ><span>动量基准</span>
                <b>{{ formatMetric(researchReport.metrics?.IC) }}</b
                ><span>加入因子</span>
              </article>
              <article>
                <small>Rank IC</small>
                <strong>{{
                  formatMetric(researchReport.baseline_metrics?.["Rank IC"])
                }}</strong
                ><span>动量基准</span>
                <b>{{ formatMetric(researchReport.metrics?.["Rank IC"]) }}</b
                ><span>加入因子</span>
              </article>
            </div>
            <EquityChart :rows="researchReport.rows || []" />
            <p class="outcome-note">
              图中为加入新因子后的绝对扣费净值；表格采用相对沪深300的超额收益口径。流程成功不代表策略可以上线。
            </p>
            <div class="factor-strip">
              <button
                v-for="(factor, i) in researchReport.factors || []"
                :key="factor.name"
                @click="openReportCode(i)"
              >
                <span>0{{ i + 1 }}</span
                ><strong>{{ factor.name }}</strong
                ><small>查看实际代码 →</small>
              </button>
            </div>
          </section>
          <details class="generation-guide">
            <summary>假设依据与生成机制 <span>框架默认行为</span></summary>
            <div class="evidence-grid">
              <article>
                <small>第一轮</small
                ><strong>研究方向 + 场景约束 + 模型知识</strong>
                <p>
                  没有历史实验时，LLM 根据总体要求和内置提示提出待验证的想法。
                </p>
              </article>
              <article>
                <small>后续轮次</small><strong>历史实验 + 最近一轮反馈</strong>
                <p>解释成功和失败，再选择修正现有假设或探索新方向。</p>
              </article>
            </div>
            <p class="hint">{{ generationHint }}</p>
            <p class="hint">
              联合优化源码默认使用 bandit 选择因子或模型方向，也支持 LLM
              和随机选择。此处说明默认配置；实际研究方向以本轮产物为准。内置研究提示不代表联网检索论文。
            </p>
          </details>
          <section class="surface">
            <div class="section-heading">
              <h3>启动新研究</h3>
              <span class="tag">{{ researchStatus }}</span>
            </div>
            <label
              >研发模式<select v-model="scenario">
                <option
                  v-for="mode in modes"
                  :key="mode.value"
                  :value="mode.value"
                >
                  {{ mode.name }}
                </option>
              </select></label
            ><label
              >研究方向<textarea
                v-model="objective"
                placeholder="例如：研究沪深300中量价动量因子的增量信息，并评估与现有特征组合后的效果。"
              ></textarea>
            </label>
            <div class="form-grid">
              <label
                >迭代轮数<input
                  v-model.number="loops"
                  type="number"
                  min="1"
                  max="30" /></label
              ><label
                >运行时限（小时）<input
                  v-model.number="duration"
                  type="number"
                  min="0.1"
                  max="24"
                  step="0.1"
              /></label>
            </div>
            <p class="hint">
              启动后，在“研究确认”中提交总体方向与基础特征，再由 LLM
              生成假设。这里的要求用于引导研究，实际实验参数以 Agent
              产出的配置为准。右栏仅展示所选研究的评估与日志。
            </p>
            <div class="actions">
              <button
                class="primary"
                :disabled="busy || researchActive"
                @click="startResearch"
              >
                {{ busy ? "正在提交…" : "启动 AI 研究" }}</button
              ><button
                :disabled="!researchActive || busy"
                @click="stopResearch"
              >
                停止研究
              </button>
            </div>
          </section>
          <section v-if="interaction" class="surface interaction">
            <div class="section-heading">
              <h3>研究确认</h3>
              <span class="tag">等待输入</span>
            </div>
            <p class="hint">确认研究方向、假设或评估意见，继续下一步实验。</p>
            <label v-for="field in interactionFields" :key="field.key"
              >{{ field.label
              }}<select
                v-if="field.key === 'decision'"
                :value="String(field.value)"
                @change="
                  updateInteraction(field.key, $event.target.value === 'true')
                "
              >
                <option value="true">接受本轮结果</option>
                <option value="false">继续调整</option></select
              ><textarea
                v-else
                :value="field.value"
                @input="updateInteraction(field.key, $event.target.value)"
              ></textarea></label
            ><button
              v-if="'features' in interaction.content"
              @click="useFactors"
            >
              载入当前组合表达式
            </button>
            <details>
              <summary>高级配置：特征字典与完整确认内容</summary>
              <textarea
                class="json-input"
                v-model="interactionText"
                aria-label="研究确认 JSON"
              ></textarea>
            </details>
            <button class="primary" :disabled="busy" @click="submitInteraction">
              确认并继续
            </button>
          </section>
          <div class="section-heading">
            <h3>实验轮次</h3>
            <span
              >{{ researchRounds.length }} 轮 ·
              {{ acceptedRounds }} 轮接受</span
            >
          </div>
          <div v-if="!researchRounds.length" class="empty">
            <span>◎</span>
            <h3>第一条假设尚未生成</h3>
            <p>
              启动研究并完成初始化确认后，这里会显示 LLM
              实际提出的假设，不预填示例结论。
            </p>
          </div>
          <div v-else class="round-selector" aria-label="研究轮次">
            <button
              v-for="round in researchRounds"
              :key="round.id"
              :class="{ chosen: activeRoundId === round.id }"
              @click="selectRound(round)"
            >
              <small>ROUND {{ round.label }}</small
              ><strong>{{ round.action }}</strong
              ><span>{{ round.status }}</span>
            </button>
          </div>
          <article v-if="activeRound" class="surface hypothesis round-detail">
            <div class="section-heading">
              <span class="tag"
                >ROUND {{ activeRound.label }} · {{ activeRound.action }}</span
              ><span class="decision-badge" :class="activeRound.decision">{{
                activeRound.status
              }}</span>
            </div>
            <h2>
              {{ activeRound.hypothesis.hypothesis || "本轮假设事件尚未到达" }}
            </h2>
            <p class="hypothesis-reason">
              {{
                activeRound.hypothesis.reason ||
                activeRound.hypothesis.concise_reason ||
                "等待提出依据。"
              }}
            </p>
            <div class="evidence-grid">
              <article v-for="item in hypothesisEvidence" :key="item.label">
                <small>{{ item.label }}</small>
                <p>{{ item.value || "本轮未提供" }}</p>
              </article>
            </div>
            <div class="round-stages">
              <div
                v-for="stage in activeRound.stages"
                :key="stage.name"
                :class="{ received: stage.received }"
              >
                <i></i><span>{{ stage.name }}</span
                ><small>{{ stage.received ? "已收到产物" : "等待产物" }}</small>
              </div>
            </div>
            <section class="round-section">
              <div class="section-heading">
                <h3>实验任务与实现</h3>
                <span
                  >{{ activeRound.tasks.length }} 个任务 ·
                  {{ activeRound.files.length }} 份代码产物</span
                >
              </div>
              <p v-if="!activeRound.tasks.length" class="hint">
                假设将被转换为具体因子或模型任务，然后生成代码。
              </p>
              <details v-for="(task, i) in activeRound.tasks" :key="i">
                <summary>
                  {{ task.name || task.factor_name || "实验任务 " + (i + 1) }}
                </summary>
                <pre>{{ stringify(task) }}</pre>
              </details>
              <button
                :disabled="!activeRound.files.length"
                @click="openRoundCode(activeRound)"
              >
                查看本轮代码 →
              </button>
              <details v-for="(event, i) in activeRound.development" :key="i">
                <summary>代码执行与检查反馈 {{ i + 1 }}</summary>
                <pre>{{ stringify(event.content) }}</pre>
              </details>
            </section>
            <section class="round-section">
              <div class="section-heading">
                <h3>Qlib 评估</h3>
                <button
                  :disabled="!activeRound.metrics.length"
                  @click="showRoundMetrics(activeRound)"
                >
                  在右栏查看 →
                </button>
              </div>
              <p class="hint">
                指标沿用 Agent
                原生名称与口径，不与独立组合回测混用。出现评估指标不等于假设已被接受。
              </p>
              <div
                class="round-metrics"
                v-if="Object.keys(roundMetrics).length"
              >
                <article v-for="(value, name) in roundMetrics" :key="name">
                  <small>{{ name }}</small
                  ><strong>{{ formatMetric(value) }}</strong>
                </article>
              </div>
              <p v-else class="hint">本轮评估指标尚未返回。</p>
            </section>
            <section class="round-section">
              <div class="section-heading">
                <h3>评估决定与下一步</h3>
                <span class="decision-badge" :class="activeRound.decision">{{
                  decisionLabel(activeRound.feedback?.decision)
                }}</span>
              </div>
              <p>
                {{
                  activeRound.feedback?.reason ||
                  "反馈尚未生成；当前假设仍待验证。"
                }}
              </p>
              <dl class="feedback-facts">
                <template v-for="item in feedbackEvidence" :key="item.label"
                  ><dt>{{ item.label }}</dt>
                  <dd>{{ item.value || "本轮未提供" }}</dd></template
                >
              </dl>
              <div class="feedback-note">
                接受／拒绝来自 RD-Agent
                反馈。下一轮会参考完整实验历史，可能采纳本轮建议，也可能提出其他方向。
              </div>
            </section>
          </article>
        </template>

        <template v-if="section === 'strategy'">
          <section class="intro">
            <span class="index">STEP 02 / PORTFOLIO</span>
            <h2>设定交易规则，再验证。</h2>
            <p>
              查看当前策略的选股与调仓规则，检查关联因子和实际实现，再运行一次独立回测。
            </p>
          </section>
          <section class="surface">
            <div class="section-heading">
              <h3>截面因子 Top-K 组合策略</h3>
              <span class="tag">QLIB · 当前配置</span>
            </div>
            <p class="hint">
              采用 Qlib 原生
              TopkDropoutStrategy。这是可配置的策略模板，尚未以当前参数验证的表现不作预设。
            </p>
            <dl class="feedback-facts">
              <dt>股票池</dt>
              <dd>{{ config.market }}</dd>
              <dt>信号构建</dt>
              <dd>
                所选因子逐日截面百分位排名，按权重加总，再除以权重绝对值之和。
              </dd>
              <dt>持仓数量</dt>
              <dd>目标 Top {{ config.topk }}；按得分排序选择股票。</dd>
              <dt>调仓规则</dt>
              <dd>
                每日最多替换 {{ config.n_drop }} 只，实际成交受 Qlib
                可交易性与资金约束影响。
              </dd>
              <dt>信号与成交</dt>
              <dd>读取前一交易日信号，当日收盘执行。</dd>
              <dt>交易成本</dt>
              <dd>
                买入 {{ percent(config.open_cost) }} / 卖出
                {{ percent(config.close_cost) }}；单笔最低费用 5 元。
              </dd>
            </dl>
            <div class="actions">
              <button
                class="primary"
                :disabled="busy || backtestActive || !selectedFactors.length"
                @click="startBacktest"
              >
                {{ backtestActive ? "回测运行中…" : "运行策略回测" }}</button
              ><button @click="section = 'factors'">编辑关联因子</button>
            </div>
            <p class="hint">
              参数在右侧修改。每次运行保存因子、权重与回测参数快照，后续修改不会覆盖历史运行。
            </p>
          </section>
          <section class="surface">
            <div class="section-heading">
              <h3>关联因子</h3>
              <span>{{ selectedFactors.length }} 个启用</span>
            </div>
            <p v-if="!selectedFactors.length" class="hint">
              请先到“因子与组合”启用至少一个因子。
            </p>
            <article
              v-for="factor in selectedFactors"
              :key="factor.id"
              class="strategy-factor"
            >
              <strong>{{ factor.name }}</strong
              ><span class="tag">权重 {{ factor.weight }}</span>
              <pre>{{ factor.expression }}</pre>
            </article>
            <h3>当前组合信号</h3>
            <pre>{{ combination }}</pre>
          </section>
          <details class="surface">
            <summary>策略代码 · studio_worker.py</summary>
            <p class="hint">
              这是当前回测执行器的实际代码，包含信号构建、Qlib
              策略调用和结果计算。
            </p>
            <div class="code-panel">
              <pre><code>{{ workerCode }}</code></pre>
            </div>
            <button @click="download('studio_worker.py', workerCode)">
              下载策略实现
            </button>
          </details>
          <section class="surface">
            <div class="section-heading">
              <h3>策略回测记录</h3>
              <button @click="section = 'runs'">查看全部 →</button>
            </div>
            <p class="hint">
              当前支持这一种组合策略模板，下方为它使用不同因子与参数的历史运行。
            </p>
            <p v-if="!jobs.length" class="hint">尚无回测记录。</p>
            <button
              v-for="job in jobs.slice(0, 5)"
              :key="job.id"
              class="run-row"
              :class="{ chosen: job.id === jobId }"
              @click="loadJob(job.id)"
            >
              <span
                ><strong
                  >{{ job.config.market }} · Top {{ job.config.topk }}</strong
                ><small
                  >{{ job.config.start }} → {{ job.config.end }} ·
                  {{ job.config.factors.length }} 个因子</small
                ><small>{{ job.id }}</small></span
              ><span class="tag">{{ statusLabel(job.status) }}</span>
            </button>
          </section>
        </template>

        <template v-if="section === 'factors'">
          <section class="intro">
            <span class="index"
              >FACTOR LIBRARY / {{ selectedFactors.length }} SELECTED</span
            >
            <h2>因子先入库，再进入组合。</h2>
            <p>
              勾选“可组合”的 Qlib 表达式因子。AI 生成的 Python
              因子会作为研究产物入库，完成表达式发布或数据接入后才能用于独立组合回测。
            </p>
          </section>
          <div class="factor-pipeline" aria-label="因子到回测流程">
            <span class="active">1 因子库</span><i>→</i><span>2 选择因子</span
            ><i>→</i><span>3 组合策略</span><i>→</i><span>4 回测结果</span>
          </div>
          <section
            v-if="researchReport.factors?.length"
            class="research-assets"
          >
            <div class="section-heading">
              <h3>当前研究产物</h3>
              <span>{{ researchReport.factors.length }} 个 · 代码已执行</span>
            </div>
            <article
              v-for="(factor, i) in researchReport.factors"
              :key="factor.name"
              class="research-factor-row"
            >
              <div>
                <small>AI RESEARCH ASSET</small
                ><strong>{{ factor.name }}</strong>
                <p>
                  原始Python代码已通过执行检查；表达式版可加入独立组合回测。
                </p>
              </div>
              <span class="asset-state">{{
                factor.expression ? "可组合" : "待发布"
              }}</span>
              <button
                :disabled="!factor.expression || isFactorSelected(factor.name)"
                @click="addResearchFactor(factor)"
              >
                {{ isFactorSelected(factor.name) ? "已加入" : "加入组合" }}
              </button>
              <button @click="openReportCode(i)">查看代码</button>
            </article>
          </section>
          <div class="section-heading">
            <h3>可组合因子</h3>
            <button @click="addFactor">＋ 添加因子</button>
          </div>
          <article
            v-for="(factor, index) in factors"
            :key="factor.id"
            class="surface factor"
          >
            <div class="factor-title">
              <input
                type="checkbox"
                v-model="factor.enabled"
                :aria-label="'启用 ' + factor.name"
              /><input v-model="factor.name" aria-label="因子名称" /><span
                class="tag"
                >{{ factor.source || "自定义" }}</span
              ><span class="select-state" :class="{ on: factor.enabled }">{{
                factor.enabled ? "已加入组合" : "未选择"
              }}</span
              ><button class="text-button" @click="factors.splice(index, 1)">
                移除
              </button>
            </div>
            <label
              >Qlib 表达式<textarea
                class="expression"
                v-model="factor.expression"
                spellcheck="false"
              ></textarea>
            </label>
            <div class="factor-meta">
              <label
                >组合权重
                <input
                  type="number"
                  step="0.1"
                  v-model.number="factor.weight" /></label
              ><span>数值越高，信号越强</span>
            </div>
          </article>
          <section class="surface">
            <div class="section-heading">
              <h3>当前已选 {{ selectedFactors.length }} 个因子</h3>
              <span>下一步配置持仓与交易规则</span>
            </div>
            <pre>{{ combination }}</pre>
            <p class="hint">
              这是可编辑的研究模板，不是已验证因子。仅在所选因子均有数据的行上计算组合；使用前一交易日信号，交易日收盘执行。
            </p>
            <button
              class="primary"
              :disabled="!selectedFactors.length"
              @click="section = 'strategy'"
            >
              用这 {{ selectedFactors.length }} 个因子构建组合 →
            </button>
          </section>
        </template>

        <template v-if="section === 'code'">
          <section class="intro">
            <span class="index">03 / IMPLEMENTATION</span>
            <h2>每个结果，都有代码依据。</h2>
            <p>
              查看所选研究各轮生成的因子、模型代码与实验配置。研究产物沿
              RD-Agent 原生链路评估；目前尚不能自动转为独立组合回测信号。
            </p>
          </section>
          <div class="code-toolbar">
            <select v-model="selectedCode" aria-label="选择代码文件">
              <option value="worker" disabled>选择本次研究生成的代码</option>
              <option
                v-for="(file, i) in codeFiles"
                :key="i"
                :value="String(i)"
              >
                轮次 {{ file.loop }} · {{ file.task }} / {{ file.name }}
              </option></select
            ><button @click="downloadCode">下载代码</button>
          </div>
          <div class="code-panel">
            <div class="code-caption">
              <span>{{ currentCode.name }}</span
              ><span
                >READ ONLY ·
                {{ currentCode.code.split("\n").length }} LINES</span
              >
            </div>
            <pre><code>{{ currentCode.code || '等待代码产物。' }}</code></pre>
          </div>
          <section v-for="(event, i) in configs" :key="i" class="surface">
            <h3>实验配置 · {{ event.loop_id }}</h3>
            <pre>{{ stringify(event.content) }}</pre>
          </section>
        </template>

        <template v-if="section === 'runs'">
          <section class="intro">
            <span class="index">04 / EXPERIMENTS</span>
            <h2>研究与回测，都在一条时间线上。</h2>
            <p>
              每次组合回测保存独立参数快照、运行日志和逐日结果。选择历史记录查看当时配置。
            </p>
          </section>
          <div class="section-heading">
            <h3>AI研究</h3>
            <span>{{ researchReports.length }} 条</span>
          </div>
          <button
            v-for="report in researchReports"
            :key="report.id"
            class="run-row"
            @click="chooseResearchReport(report.id)"
          >
            <span
              ><strong>{{ report.id.split("/").at(-1) }}</strong
              ><small>原生RD-Agent因子研究 · 假设、代码、Qlib评估、反馈</small
              ><small>{{ report.id }}</small></span
            ><span class="tag">{{
              report.status === "completed" ? "流程完成" : "失败"
            }}</span>
          </button>
          <div class="section-heading run-separator">
            <h3>组合回测</h3>
            <span>{{ jobs.length }} 条</span>
          </div>
          <div v-if="!jobs.length" class="empty">
            <span>↗</span>
            <h3>还没有组合回测记录</h3>
            <p>从因子库勾选因子，再进入组合回测。</p>
          </div>
          <button
            v-for="job in jobs"
            :key="job.id"
            class="run-row"
            :class="{ chosen: job.id === jobId }"
            @click="loadJob(job.id)"
          >
            <span
              ><strong
                >{{ job.config.market }} · Top {{ job.config.topk }}</strong
              ><small
                >{{ job.config.start }} → {{ job.config.end }} ·
                {{ job.config.factors.length }} 个因子</small
              ><small>{{ job.id }}</small></span
            ><span class="tag">{{ statusLabel(job.status) }}</span>
          </button>
          <section v-if="result.config" class="surface">
            <h3>选中运行的参数快照</h3>
            <pre>{{ stringify(result.config) }}</pre>
            <button @click="downloadResult">导出结果 JSON</button>
          </section>
        </template>
      </div>
    </main>

    <aside class="results">
      <header class="result-head">
        <div>
          <span class="eyebrow">{{
            isResearchContext
              ? "RESEARCH EVIDENCE"
              : section === "factors"
                ? "FACTOR SELECTION"
                : "BACKTEST RESULTS"
          }}</span>
          <h2>
            {{
              isResearchContext
                ? "研究评估"
                : section === "factors"
                  ? "组合篮子"
                  : "回测结果"
            }}
          </h2>
        </div>
        <span
          class="status-dot"
          :class="{ active: backtestActive || researchActive }"
        ></span>
      </header>
      <div class="result-scroll">
        <div v-if="section === 'factors'" class="signal-next">
          <div class="selection-count">
            <strong>{{ selectedFactors.length }}</strong
            ><span>个因子已加入组合</span>
          </div>
          <div class="selection-drawer">
            <div v-for="factor in selectedFactors" :key="factor.id">
              <span>{{ factor.name }}</span
              ><small>权重 {{ factor.weight }}</small>
            </div>
          </div>
          <h3>
            {{
              selectedFactors.length
                ? "选择完成后配置策略"
                : "先从因子库选择因子"
            }}
          </h3>
          <p class="hint">
            勾选框决定因子是否进入组合，权重决定方向与相对贡献。下一步设置持仓、调仓、成本与回测区间。
          </p>
          <button
            :disabled="!selectedFactors.length"
            @click="section = 'strategy'"
          >
            配置策略与回测 →
          </button>
        </div>
        <details v-if="section === 'strategy'" class="config-block" open>
          <summary>Qlib 回测配置</summary>
          <label
            >本地数据目录<input
              v-model="config.provider_uri"
              placeholder="~/.qlib/qlib_data/cn_data"
          /></label>
          <div class="form-grid">
            <label
              >股票池<select v-model="config.market">
                <option value="csi300">沪深300</option>
                <option value="csi500">中证500</option>
                <option value="all">全部股票</option>
              </select></label
            ><label>基准<input v-model="config.benchmark" /></label
            ><label>开始日期<input type="date" v-model="config.start" /></label
            ><label>结束日期<input type="date" v-model="config.end" /></label
            ><label
              >Top-K 持仓<input
                type="number"
                v-model.number="config.topk"
                min="1" /></label
            ><label
              >每日最多替换<input
                type="number"
                v-model.number="config.n_drop"
                min="0" /></label
            ><label
              >买入费率<input
                type="number"
                step="0.0001"
                v-model.number="config.open_cost" /></label
            ><label
              >卖出费率<input
                type="number"
                step="0.0001"
                v-model.number="config.close_cost"
            /></label>
          </div>
          <label
            >初始资金<input
              type="number"
              min="1000"
              v-model.number="config.account"
          /></label>
          <p class="hint">
            日频 / 收盘成交 / 每笔最低费用 5 元。股票交易规则沿用 Qlib
            中国市场配置。
          </p>
          <button
            class="primary wide"
            :disabled="busy || backtestActive || !selectedFactors.length"
            @click="startBacktest"
          >
            {{ backtestActive ? "Qlib 正在回测…" : "运行当前组合回测" }}
          </button>
        </details>
        <div v-if="section !== 'factors'" class="result-tabs">
          <button
            v-if="!isResearchContext"
            :class="{ selected: resultTab === 'portfolio' }"
            @click="resultTab = 'portfolio'"
          >
            组合回测</button
          ><button
            v-if="isResearchContext"
            :class="{ selected: resultTab === 'agent' }"
            @click="resultTab = 'agent'"
          >
            Agent 评估</button
          ><button
            :class="{ selected: resultTab === 'logs' }"
            @click="resultTab = 'logs'"
          >
            日志
          </button>
        </div>
        <template
          v-if="
            section !== 'factors' &&
            !isResearchContext &&
            resultTab === 'portfolio'
          "
        >
          <div class="section-heading">
            <h3>运行结果</h3>
            <span class="tag">{{ statusLabel(result.status) }}</span>
          </div>
          <p v-if="result.config" class="hint">
            {{ result.config.market }} · {{ result.config.start }} →
            {{ result.config.end }} · {{ jobId.slice(0, 8) }}
          </p>
          <div v-if="result.error" class="notice error">{{ result.error }}</div>
          <template v-if="result.metrics"
            ><div class="metrics">
              <article v-for="metric in metricCards" :key="metric.label">
                <small>{{ metric.label }}</small
                ><strong>{{ metric.value }}</strong>
              </article>
            </div>
            <EquityChart :rows="result.rows || []" />
            <p class="hint">
              扣费复利净值；年化按 252 个交易日；夏普无风险利率取
              0。回撤显示为负值。
            </p>
            <details>
              <summary>逐日明细 · {{ result.rows.length }} 条</summary>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>日期</th>
                      <th>日收益</th>
                      <th>费用率</th>
                      <th>换手率</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in result.rows" :key="row.date">
                      <td>{{ row.date }}</td>
                      <td>{{ percent(row.return) }}</td>
                      <td>{{ percent(row.cost) }}</td>
                      <td>{{ percent(row.turnover) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details></template
          >
          <div v-else class="empty compact">
            <span>⌁</span>
            <h3>{{ backtestActive ? "正在计算真实结果" : "结果尚未生成" }}</h3>
            <p>净值、基准、回撤与逐日明细将在运行完成后显示。</p>
          </div>
        </template>
        <template v-if="isResearchContext && resultTab === 'agent'"
          ><select v-model="metricLoop" aria-label="评估轮次">
            <option value="">选择评估轮次</option>
            <option
              v-for="(event, i) in metricEvents"
              :key="i"
              :value="String(i)"
            >
              轮次 {{ event.loop_id }} · {{ event.timestamp }}
            </option>
          </select>
          <div
            class="agent-metrics"
            v-for="(value, key) in agentMetrics"
            :key="key"
          >
            <span>{{ key }}</span
            ><strong>{{ value }}</strong>
          </div>
          <iframe
            v-if="agentChart"
            title="RD-Agent 原生评估图"
            sandbox="allow-scripts"
            :srcdoc="agentChart"
          ></iframe>
          <div v-if="!metricEvents.length" class="empty compact">
            <h3>等待 Agent 评估</h3>
            <p>沿用原生指标名，保留年化、超额收益及费用口径。</p>
          </div></template
        >
        <template v-if="resultTab === 'logs'"
          ><template v-if="!isResearchContext"
            ><h3>Qlib 执行日志</h3>
            <pre class="logs">{{
              result.log || "暂无 Qlib 日志。"
            }}</pre></template
          ><template v-else
            ><h3>RD-Agent 事件</h3>
            <p v-if="!events.length" class="hint">当前研究尚无日志。</p>
            <div v-for="(event, i) in events" :key="i" class="event">
              <small>{{ event.tag }} · {{ event.loop_id }}</small>
              <details>
                <summary>查看内容</summary>
                <pre>{{ stringify(event.content) }}</pre>
              </details>
            </div></template
          ></template
        >
      </div>
    </aside>
  </div>
</template>

<script setup>
import {
  computed,
  onMounted,
  onBeforeUnmount,
  reactive,
  ref,
  watch,
} from "vue";
import EquityChart from "../components/studio/EquityChart.vue";
import localWorkerSource from "../../../rdagent/log/server/studio_worker.py?raw";
const sections = [
  { id: "research", name: "AI 研究", symbol: "◎" },
  { id: "factors", name: "因子库", symbol: "⊞" },
  { id: "strategy", name: "组合回测", symbol: "◇" },
  { id: "code", name: "研究代码与配置", symbol: "⌘" },
  { id: "runs", name: "运行记录", symbol: "↗" },
];
const modes = [
  {
    name: "因子研发",
    desc: "假设 → 因子实现 → 评估",
    value: "Finance Data Building",
  },
  {
    name: "模型研发",
    desc: "模型实现与迭代验证",
    value: "Finance Model Implementation",
  },
  {
    name: "因子 × 模型联合优化",
    desc: "RD-Agent 原生联合研究循环",
    value: "Finance Whole Pipeline",
  },
];
function restore() {
  try {
    return JSON.parse(localStorage.getItem("rd-studio-v2") || "{}");
  } catch {
    return {};
  }
}
const saved = restore();
const activeRoundId = ref("");
const section = ref("research"),
  scenario = ref(saved.scenario || modes[0].value);
const error = ref(""),
  busy = ref(false),
  objective = ref(saved.objective || ""),
  loops = ref(3),
  duration = ref(1);
const environment = ref({}),
  traceId = ref(saved.traceId || ""),
  traceIds = ref([]),
  events = ref([]),
  researchReports = ref([]),
  researchReport = ref({}),
  jobs = ref([]),
  jobId = ref(saved.jobId || ""),
  result = ref({});
const resultTab = ref("agent"),
  metricLoop = ref(""),
  selectedCode = ref("worker"),
  workerCode = ref(localWorkerSource);
const isResearchContext = computed(() =>
  ["research", "code"].includes(section.value),
);
const isBacktestContext = computed(() =>
  ["factors", "strategy"].includes(section.value),
);
watch(isResearchContext, (value) => {
  resultTab.value = value ? "agent" : "portfolio";
});
const researchStatus = ref("尚未启动"),
  researchActive = ref(false),
  interactionText = ref("");
const acknowledged = ref(saved.acknowledged || []);
const factors = ref(
  saved.factors || [
    {
      id: "momentum",
      name: "20日动量",
      expression: "$close / Ref($close, 20) - 1",
      weight: 1,
      enabled: true,
      source: "表达式模板",
    },
    {
      id: "volume",
      name: "相对成交量",
      expression: "$volume / Mean($volume, 20)",
      weight: 0.5,
      enabled: true,
      source: "表达式模板",
    },
    {
      id: "volatility",
      name: "20日波动率",
      expression: "Std($close / Ref($close, 1) - 1, 20)",
      weight: -0.5,
      enabled: false,
      source: "表达式模板",
    },
  ],
);
const config = reactive(
  saved.config || {
    provider_uri: "~/.qlib/qlib_data/cn_data",
    market: "csi300",
    benchmark: "SH000300",
    start: "2017-01-01",
    end: "2020-08-01",
    topk: 10,
    n_drop: 2,
    account: 1000000,
    open_cost: 0.0005,
    close_cost: 0.0015,
  },
);
let timer,
  disposed = false;
const stringify = (value) =>
  typeof value === "string" ? value : JSON.stringify(value, null, 2);
const percent = (value) =>
  typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(2)}%`
    : "—";
const statusLabel = (status) =>
  ({
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
  })[status] || "未运行";
const selectedFactors = computed(() => factors.value.filter((f) => f.enabled));
const totalFactorAssets = computed(
  () =>
    new Set([
      ...factors.value.map((factor) => factor.name),
      ...(researchReport.value.factors || []).map((factor) => factor.name),
    ]).size,
);
const combination = computed(
  () =>
    selectedFactors.value
      .map((f) => `${f.weight} × CSRank(${f.expression})`)
      .join(" + ") + "\n/ Σ |weight|",
);
const backtestActive = computed(() =>
  ["queued", "running"].includes(result.value.status),
);
const hypotheses = computed(() =>
  events.value.filter((e) => e.tag === "research.hypothesis"),
);
const configs = computed(() =>
  events.value.filter((e) => e.tag === "feedback.config"),
);
const metricEvents = computed(() =>
  events.value.filter((e) => e.tag === "feedback.metric"),
);
const agentMetrics = computed(() => {
  if (metricLoop.value === "") return {};
  try {
    const value = metricEvents.value[Number(metricLoop.value)]?.content.result;
    return typeof value === "string" ? JSON.parse(value) : value || {};
  } catch {
    return {};
  }
});
const agentChart = computed(() => {
  if (metricLoop.value === "") return "";
  const loop = metricEvents.value[Number(metricLoop.value)]?.loop_id;
  return (
    events.value.find(
      (e) => e.tag === "feedback.return_chart" && e.loop_id === loop,
    )?.content.chart_html || ""
  );
});
const codeFiles = computed(() => [
  ...events.value
    .filter((e) => e.tag === "evolving.codes")
    .flatMap((e) =>
      (Array.isArray(e.content) ? e.content : []).flatMap((task) =>
        Object.entries(task.workspace || {}).map(([name, code]) => ({
          name,
          code: stringify(code),
          task: task.target_task_name,
          loop: e.loop_id,
        })),
      ),
    ),
  ...(researchReport.value.factors || []).map((factor) => ({
    name: "factor.py",
    code: factor.code,
    task: factor.name,
    loop: "结果",
  })),
]);
const currentCode = computed(() =>
  selectedCode.value === "worker"
    ? { name: "研究代码", code: "" }
    : codeFiles.value[Number(selectedCode.value)] || { name: "", code: "" },
);
const interactionKey = (e) =>
  `${traceId.value}:${e.timestamp}:${JSON.stringify(e.content)}`;
const interaction = computed(() => {
  if (!researchActive.value) return null;
  return events.value.find(
    (e) =>
      e.tag === "user_interaction.request" &&
      !acknowledged.value.includes(interactionKey(e)),
  );
});
watch(
  () => (interaction.value ? interactionKey(interaction.value) : ""),
  (key) => {
    const value = interaction.value;
    if (key && value)
      interactionText.value = JSON.stringify(
        "user_instruction" in value.content
          ? {
              ...value.content,
              user_instruction:
                objective.value || value.content.user_instruction,
            }
          : value.content,
        null,
        2,
      );
  },
);
const interactionFields = computed(() => {
  try {
    const data = JSON.parse(interactionText.value);
    return Object.entries({
      user_instruction: "研究方向",
      hypothesis: "研究假设",
      reason: "依据与反馈",
      decision: "评估决定",
    })
      .filter(([key]) => key in data)
      .map(([key, label]) => ({ key, label, value: data[key] }));
  } catch {
    return [];
  }
});
function updateInteraction(key, value) {
  try {
    const data = JSON.parse(interactionText.value);
    data[key] = value;
    interactionText.value = JSON.stringify(data, null, 2);
  } catch {
    error.value = "请先修正高级配置中的 JSON 格式。";
  }
}
const metricCards = computed(() => {
  const m = result.value.metrics || {};
  return [
    { label: "总收益 · 扣费", value: percent(m.total_return) },
    { label: "复利年化", value: percent(m.annualized_return) },
    {
      label: "夏普",
      value: typeof m.sharpe === "number" ? m.sharpe.toFixed(2) : "—",
    },
    { label: "最大回撤", value: percent(m.max_drawdown) },
    { label: "基准收益", value: percent(m.benchmark_return) },
    { label: "交易日数", value: m.days ?? "—" },
  ];
});
function decisionLabel(value) {
  return value === true || String(value).toLowerCase() === "true"
    ? "接受"
    : value === false || String(value).toLowerCase() === "false"
      ? "拒绝"
      : "待评估";
}
const generationHint = computed(() =>
  scenario.value === "Finance Data Building"
    ? "因子研发默认在前 15 轮优先尝试简单、快速和不同角度的因子，之后引导探索更高 IC 的方向。轮数指历史实验数。"
    : scenario.value === "Finance Model Implementation"
      ? "模型研发结合历史表现提出架构或参数假设，也允许保留模型结构、只调整训练参数。"
      : "联合优化交替选择因子或模型研究方向；因子方向的内置探索提示以历史实验数 6 轮为分界，不是每轮同时优化两者。",
);
const researchRounds = computed(() => {
  const groups = new Map();
  for (const event of events.value) {
    if (event.loop_id === undefined || event.loop_id === null) continue;
    const id = String(event.loop_id);
    if (!groups.has(id)) groups.set(id, { id, label: id, events: [] });
    groups.get(id).events.push(event);
  }
  return [...groups.values()].map((round) => {
    const tagged = (tag) => round.events.filter((e) => e.tag === tag);
    const hypothesis = tagged("research.hypothesis").at(-1)?.content || {};
    const feedback = tagged("feedback.hypothesis_feedback").at(-1)?.content;
    const metrics = tagged("feedback.metric");
    const files = codeFiles.value.filter(
      (file) => String(file.loop) === round.id,
    );
    const development = tagged("evolving.feedbacks");
    const verdict = decisionLabel(feedback?.decision);
    const action =
      hypothesis.action === "factor"
        ? "因子研发"
        : hypothesis.action === "model"
          ? "模型研发"
          : traceId.value.startsWith("Finance Data Building/")
            ? "因子研发"
            : traceId.value.startsWith("Finance Model Implementation/")
              ? "模型研发"
              : "方向未提供";
    return {
      ...round,
      hypothesis,
      feedback,
      metrics,
      files,
      development,
      action,
      tasks: tagged("research.tasks").flatMap((e) =>
        Array.isArray(e.content) ? e.content : [e.content],
      ),
      decision:
        verdict === "接受"
          ? "accepted"
          : verdict === "拒绝"
            ? "rejected"
            : "pending",
      status: feedback
        ? verdict
        : metrics.length
          ? "评估已返回"
          : files.length
            ? "代码已生成"
            : "假设待验证",
      stages: [
        { name: "研究假设", received: !!tagged("research.hypothesis").length },
        { name: "实验代码", received: !!files.length },
        { name: "评估指标", received: !!metrics.length },
        { name: "决策反馈", received: !!feedback },
      ],
    };
  });
});
const activeRound = computed(
  () =>
    researchRounds.value.find((round) => round.id === activeRoundId.value) ||
    researchRounds.value.at(-1),
);
const acceptedRounds = computed(
  () =>
    researchRounds.value.filter((round) => round.decision === "accepted")
      .length,
);
const hypothesisEvidence = computed(() => {
  const h = activeRound.value?.hypothesis || {};
  return [
    { label: "观察", value: h.concise_observation },
    { label: "知识依据", value: h.concise_knowledge },
    { label: "推导理由", value: h.concise_justification },
    { label: "理由摘要", value: h.concise_reason },
  ];
});
const feedbackEvidence = computed(() => {
  const f = activeRound.value?.feedback || {};
  return [
    { label: "实验观察", value: f.observations },
    { label: "假设评价", value: f.hypothesis_evaluation },
    { label: "下一轮建议", value: f.new_hypothesis },
    { label: "异常说明", value: f.exception },
  ];
});
const roundMetrics = computed(() => {
  try {
    const value = activeRound.value?.metrics.at(-1)?.content.result;
    return typeof value === "string" ? JSON.parse(value) : value || {};
  } catch {
    return {};
  }
});
const formatMetric = (value) =>
  typeof value === "number"
    ? Number.isFinite(value)
      ? Number(value.toPrecision(5)).toString()
      : "—"
    : stringify(value);
function showRoundMetrics(round) {
  const event = round.metrics.at(-1);
  metricLoop.value = event ? String(metricEvents.value.indexOf(event)) : "";
  resultTab.value = "agent";
}
function selectRound(round) {
  activeRoundId.value = round.id;
  showRoundMetrics(round);
}
function openRoundCode(round) {
  const file = round.files.at(-1);
  if (!file) return;
  selectedCode.value = String(codeFiles.value.indexOf(file));
  section.value = "code";
}
function openReportCode(index) {
  const offset =
    codeFiles.value.length - (researchReport.value.factors || []).length;
  selectedCode.value = String(offset + index);
  section.value = "code";
}
async function chooseResearchReport(id) {
  traceId.value = id;
  section.value = "research";
  await selectTrace();
}
watch(traceId, () => {
  activeRoundId.value = "";
});
watch(activeRound, (round) => {
  const event = round?.metrics.at(-1);
  metricLoop.value = event ? String(metricEvents.value.indexOf(event)) : "";
});
async function api(path, body) {
  const response = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers:
            body instanceof FormData
              ? {}
              : { "Content-Type": "application/json" },
          body: body instanceof FormData ? body : JSON.stringify(body),
        },
  );
  if ([502, 503, 504].includes(response.status))
    throw new Error("本地后端服务未连接。服务启动后，请点击重试。");
  const text = await response.text();
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(
      "服务未返回 JSON，请确认 RD-Agent 服务及 Vite 代理已启动。",
    );
  }
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}
async function action(fn) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await fn();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function addFactor() {
  factors.value.push({
    id: crypto.randomUUID(),
    name: "新因子",
    expression: "",
    weight: 1,
    enabled: true,
  });
}
function addResearchFactor(factor) {
  const id = `research:${factor.name}`;
  const existing = factors.value.find((item) => item.id === id);
  if (existing) {
    existing.enabled = true;
    return;
  }
  factors.value.push({
    id,
    name: factor.name,
    expression: factor.expression,
    weight: 1,
    enabled: true,
    source: "AI研究表达式版",
  });
}
function isFactorSelected(name) {
  return factors.value.some((factor) => factor.name === name && factor.enabled);
}
async function refresh() {
  error.value = "";
  const responses = await Promise.allSettled([
    api("/studio/environment"),
    api("/studio/backtests"),
    api("/traces"),
    api("/studio/strategy"),
    api("/studio/research-reports"),
  ]);
  responses.forEach((r, i) => {
    if (r.status === "rejected") {
      error.value = r.reason.message;
      return;
    }
    if (i === 0) environment.value = r.value;
    if (i === 1) jobs.value = r.value;
    if (i === 2)
      traceIds.value = Array.isArray(r.value) ? r.value : r.value.ids || [];
    if (i === 3) workerCode.value = r.value.code;
    if (i === 4) {
      researchReports.value = r.value;
      traceIds.value = [
        ...new Set([...traceIds.value, ...r.value.map((report) => report.id)]),
      ];
    }
  });
}
async function startResearch() {
  await action(async () => {
    if (
      !Number.isInteger(loops.value) ||
      loops.value < 1 ||
      loops.value > 30 ||
      !Number.isFinite(duration.value) ||
      duration.value < 0.1 ||
      duration.value > 24
    )
      throw new Error("研究轮数应为 1–30，运行时限应为 0.1–24 小时。");
    const data = new FormData();
    data.append("scenario", scenario.value);
    data.append("loops", String(loops.value));
    data.append("all_duration", String(duration.value));
    const output = await api("/upload", data);
    if (!output.id) throw new Error("研究任务未返回 ID");
    traceId.value = output.id;
    events.value = [];
    researchActive.value = true;
    researchStatus.value = "运行中";
    traceIds.value = [...new Set([output.id, ...traceIds.value])];
    resultTab.value = "agent";
    await pollResearch();
  });
}
async function selectTrace() {
  events.value = [];
  researchReport.value = {};
  metricLoop.value = "";
  researchActive.value = false;
  await action(pollResearch);
}
async function pollResearch() {
  const id = traceId.value;
  if (!id) return;
  const report = researchReports.value.find((item) => item.id === id);
  const [data, persisted] = await Promise.all([
    api("/trace", { id, snapshot: true }),
    report ? api(`/studio/research-reports/${id}`) : Promise.resolve({}),
  ]);
  if (id !== traceId.value || disposed) return;
  if (!Array.isArray(data)) throw new Error("无效的研究事件响应");
  events.value = data;
  researchReport.value = persisted;
  const end = [...data].reverse().find((e) => e.tag.toLowerCase() === "end");
  researchActive.value = report ? false : !end;
  researchStatus.value = report
    ? persisted.execution_success
      ? "流程完成"
      : "执行失败"
    : end
      ? Number(end.content.end_code) === 0
        ? "已完成"
        : Number(end.content.end_code) === -1
          ? "已停止"
          : "执行失败"
      : "运行中";
  if (metricLoop.value === "" && metricEvents.value.length)
    metricLoop.value = String(metricEvents.value.length - 1);
}
async function stopResearch() {
  await action(async () => {
    await api("/control", { id: traceId.value, action: "stop" });
    await pollResearch();
  });
}
function useFactors() {
  const data = JSON.parse(interactionText.value);
  data.features = Object.fromEntries(
    selectedFactors.value.map((f) => [f.name, f.expression]),
  );
  interactionText.value = JSON.stringify(data, null, 2);
}
async function submitInteraction() {
  await action(async () => {
    const current = interaction.value;
    let payload = JSON.parse(interactionText.value);
    if (!payload || typeof payload !== "object" || Array.isArray(payload))
      throw new Error("确认内容必须是 JSON 对象");
    if ("features" in current.content && payload.features)
      payload = payload.features;
    await api("/user_interaction/submit", { id: traceId.value, payload });
    acknowledged.value.push(interactionKey(current));
  });
}
async function startBacktest() {
  await action(async () => {
    const data = {
      ...config,
      factors: selectedFactors.value.map((f) => ({
        name: f.name,
        expression: f.expression,
        weight: Number(f.weight),
      })),
    };
    const output = await api("/studio/backtests", data);
    jobId.value = output.id;
    result.value = { status: "queued", config: data };
    resultTab.value = "portfolio";
    await refresh();
  });
}
async function loadJob(id) {
  await action(async () => {
    const data = await api(`/studio/backtests/${id}`);
    jobId.value = id;
    result.value = data;
    if (!isResearchContext.value) resultTab.value = "portfolio";
  });
}
async function tick() {
  if (disposed) return;
  try {
    if (traceId.value && researchActive.value) await pollResearch();
    if (jobId.value && backtestActive.value) {
      const id = jobId.value;
      const data = await api(`/studio/backtests/${id}`);
      if (id === jobId.value) result.value = data;
      if (!backtestActive.value) await refresh();
    }
  } catch (e) {
    error.value = e.message;
  } finally {
    if (!disposed) timer = setTimeout(tick, 3000);
  }
}
function download(name, content) {
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/plain;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function downloadCode() {
  download(currentCode.value.name, currentCode.value.code);
}
function downloadResult() {
  download(
    `backtest-${jobId.value}.json`,
    JSON.stringify(result.value, null, 2),
  );
}
watch(
  [factors, config, scenario, objective, traceId, jobId, acknowledged],
  () => {
    try {
      localStorage.setItem(
        "rd-studio-v2",
        JSON.stringify({
          factors: factors.value,
          config,
          scenario: scenario.value,
          objective: objective.value,
          traceId: traceId.value,
          jobId: jobId.value,
          acknowledged: acknowledged.value,
        }),
      );
    } catch {
      error.value = "浏览器本地存储不可用，配置无法在刷新后保留。";
    }
  },
  { deep: true },
);
onMounted(async () => {
  await refresh();
  if (traceId.value) await action(pollResearch);
  if (jobId.value) await loadJob(jobId.value);
  if (!disposed) tick();
});
onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(timer);
});
</script>

<style scoped>
.studio .task-navigation {
  margin-top: 30px;
  gap: 8px;
}
.studio .task-navigation button {
  align-items: flex-start;
  padding: 12px 10px;
}
.task-navigation button > span:nth-child(2) {
  min-width: 0;
}
.task-navigation small {
  display: block;
  font-size: 10px;
  line-height: 1.6;
  margin-top: 5px;
  opacity: 0.65;
  font-weight: 400;
}
.navigation-note {
  border-top: 1px solid var(--line);
  padding: 20px 8px;
  margin-top: 26px;
  color: var(--muted);
  font-size: 11px;
}
.navigation-note strong {
  font-weight: 500;
  color: #65705e;
}
.navigation-note p {
  margin: 8px 0;
  line-height: 1.8;
}
.task-intro p {
  font-size: 12px;
  line-height: 1.8;
  color: var(--muted);
  margin: 0 0 16px;
}
.studio .backtest-steps {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 28px;
}
.backtest-steps button {
  flex: 1;
  display: flex;
  gap: 12px;
  text-align: left;
  align-items: center !important;
  border: 1px solid var(--line) !important;
  padding: 14px !important;
}
.backtest-steps small {
  font-family: Georgia, serif;
  font-size: 20px;
  opacity: 0.55;
}
.backtest-steps strong {
  display: block;
  font-size: 10px;
  font-weight: 400;
  opacity: 0.6;
}
.studio .backtest-steps button.selected {
  background: #edf4e9;
  color: #1f583f;
  border-color: #afc2a3 !important;
}
.step-arrow {
  color: var(--muted);
}
.research-toolbar {
  display: flex;
  gap: 8px;
  align-items: end;
  flex-wrap: wrap;
  margin-bottom: 25px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}
.studio .research-toolbar label {
  flex: 1;
  min-width: 160px;
  margin: 0;
}
.research-toolbar button {
  font-size: 11px;
  white-space: nowrap;
}
.signal-next {
  padding: 22px 0 10px;
}
.signal-next h3 {
  margin: 0;
}
@media (max-width: 620px) {
  .studio .rail .task-navigation {
    grid-template-columns: 1fr;
    margin-top: 16px;
  }
  .studio .task-navigation button {
    padding: 10px;
  }
  .navigation-note {
    display: none;
  }
  .backtest-steps button {
    padding: 10px !important;
    gap: 7px;
    font-size: 12px;
  }
  .backtest-steps small {
    font-size: 16px;
  }
  .research-toolbar {
    align-items: center;
  }
  .research-toolbar label {
    flex-basis: 100%;
  }
}

.strategy-factor {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid var(--line);
  padding: 12px 0;
  margin-bottom: 12px;
}
.strategy-factor strong {
  font-size: 12px;
  font-weight: 500;
}
.strategy-factor pre {
  flex-basis: 100%;
  margin: 0 !important;
  color: var(--muted);
}

.menu-group {
  margin-top: 28px;
}
.menu-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  padding: 0 8px;
}
.menu-heading > span {
  font-size: 8px;
  letter-spacing: 1px;
  color: var(--muted);
  font-weight: 400;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 2px 5px;
}
.menu-description {
  font-size: 10px;
  color: var(--muted);
  line-height: 1.7;
  margin: 6px 8px 12px;
}
.experiment-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 18px 8px 5px;
}
.studio .experiment-heading label {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
}
.history-description {
  margin-top: 8px;
}
.backtest-menu {
  padding-top: 22px;
  border-top: 1px solid var(--line);
  margin-top: 20px;
}
.menu-boundary {
  font-size: 10px;
  line-height: 1.8;
  color: var(--muted);
  padding: 12px 9px;
  margin-top: 16px;
  background: #f6f8f2;
  border-radius: 7px;
}
@media (max-width: 620px) {
  .menu-group {
    margin-top: 18px;
  }
  .backtest-menu {
    margin-top: 16px;
    padding-top: 16px;
  }
  .studio .menu-group nav {
    margin-top: 6px;
  }
  .menu-description {
    margin-bottom: 6px;
  }
  .menu-boundary {
    margin-bottom: 0;
  }
  .experiment-heading {
    margin-top: 12px;
  }
  .studio .menu-group select {
    display: block;
  }
}

.research-flow {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 16px;
}
.research-flow > div {
  padding: 12px 9px;
  border-right: 1px solid var(--line);
  background: #f8faf5;
}
.research-flow > div:last-child {
  border: 0;
}
.research-flow small {
  display: block;
  color: var(--green);
  font-size: 9px;
  letter-spacing: 1px;
}
.research-flow strong {
  font-size: 11px;
  font-weight: 500;
}
.experiment-shelf {
  margin: 4px 0 22px;
}
.experiment-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}
.experiment-grid button {
  display: grid;
  gap: 4px;
  padding: 13px 14px;
  text-align: left;
  border-radius: 7px;
}
.experiment-grid button.chosen {
  border-color: #7d9d78;
  background: #f1f6ed;
  box-shadow: inset 3px 0 #376b52;
}
.experiment-grid small {
  color: var(--muted);
  font-size: 9px;
}
.experiment-grid strong {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
}
.experiment-grid span {
  color: var(--green);
  font-size: 10px;
}
.factor-pipeline {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: -5px 0 24px;
  padding: 11px 14px;
  background: #f2f5ee;
  border-radius: 7px;
  color: var(--muted);
  font-size: 10px;
}
.factor-pipeline .active {
  color: white;
  background: var(--green);
  padding: 4px 8px;
  border-radius: 4px;
}
.factor-pipeline i {
  font-style: normal;
  color: #abb2a4;
}
.research-assets {
  margin-bottom: 26px;
}
.research-factor-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto auto;
  align-items: center;
  gap: 12px;
  padding: 15px 0;
  border-bottom: 1px solid var(--line);
}
.research-factor-row small {
  display: block;
  color: #8c674d;
  font-size: 8px;
  letter-spacing: 1px;
}
.research-factor-row strong {
  display: block;
  margin-top: 2px;
  font-size: 13px;
}
.research-factor-row p {
  margin: 3px 0 0;
  color: var(--muted);
  font-size: 10px;
}
.asset-state {
  padding: 3px 6px;
  background: #faf1e8;
  color: #9a6038;
  border-radius: 3px;
  font-size: 9px;
}
.select-state {
  margin-left: auto;
  color: var(--muted);
  font-size: 9px;
}
.select-state.on {
  color: var(--green);
}
.run-separator {
  margin-top: 30px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}
.selection-count {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 22px 0 10px;
}
.selection-count strong {
  font:
    42px/1 Georgia,
    serif;
  color: var(--green);
}
.selection-count span {
  color: var(--muted);
  font-size: 11px;
}
.selection-drawer {
  margin-bottom: 22px;
  border-top: 1px solid var(--line);
}
.selection-drawer div {
  display: flex;
  justify-content: space-between;
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
  font-size: 11px;
}
.selection-drawer small {
  color: var(--muted);
}
.research-outcome {
  position: relative;
  overflow: hidden;
  padding: 0;
  border-color: #cfd9c8;
  box-shadow: 0 18px 45px rgba(48, 65, 47, 0.08);
}
.research-outcome::before {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 4px;
  background: linear-gradient(90deg, #27664f 0 62%, #c07c48 62% 100%);
}
.outcome-kicker,
.outcome-title,
.comparison-grid,
.outcome-note,
.factor-strip {
  margin-left: 22px;
  margin-right: 22px;
}
.outcome-kicker {
  display: flex;
  justify-content: space-between;
  padding-top: 21px;
  color: var(--green);
  font-size: 9px;
  letter-spacing: 1.25px;
}
.outcome-title {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 18px;
  padding: 8px 0 18px;
}
.outcome-title h2 {
  margin: 0 0 5px;
  font-family: Georgia, "Songti SC", serif;
  font-size: 25px !important;
  font-weight: 500;
}
.outcome-title p,
.outcome-note {
  margin: 0;
  color: var(--muted);
  font-size: 11px;
}
.verdict {
  flex: none;
  padding: 6px 10px;
  border: 1px solid #d7b89e;
  border-radius: 99px;
  background: #fff7ef;
  color: #9b582f;
  font-size: 10px;
}
.comparison-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border: 1px solid var(--line);
  border-radius: 9px;
  overflow: hidden;
}
.comparison-grid article {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 3px 10px;
  padding: 13px;
  border-right: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}
.comparison-grid article:last-child {
  border-right: 0;
}
.comparison-grid small {
  grid-column: 1 / -1;
  color: var(--muted);
  font-size: 9px;
}
.comparison-grid strong,
.comparison-grid b {
  font-size: 17px;
  font-weight: 500;
}
.comparison-grid b {
  color: var(--green);
}
.comparison-grid span {
  align-self: center;
  color: var(--muted);
  font-size: 9px;
}
.research-outcome .equity-chart {
  margin-top: 16px;
  height: 310px;
}
.outcome-note {
  padding: 0 0 16px;
}
.factor-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  padding-bottom: 22px;
}
.factor-strip button {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px 8px;
  text-align: left;
  padding: 11px;
}
.factor-strip button span {
  grid-row: 1 / 3;
  color: #9aa593;
  font:
    18px Georgia,
    serif;
}
.factor-strip button strong {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
}
.factor-strip button small {
  color: var(--muted);
  font-size: 9px;
}
@media (max-width: 620px) {
  .experiment-grid {
    grid-template-columns: 1fr;
  }
  .factor-pipeline {
    overflow-x: auto;
    white-space: nowrap;
  }
  .research-factor-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .research-factor-row button {
    grid-column: 1 / -1;
  }
  .comparison-grid,
  .factor-strip {
    grid-template-columns: 1fr;
  }
  .comparison-grid article {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .outcome-title {
    display: block;
  }
  .verdict {
    display: inline-block;
    margin-top: 10px;
  }
}
.generation-guide {
  border-bottom: 1px solid var(--line);
  margin-bottom: 22px;
  padding-bottom: 8px;
}
.generation-guide summary {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.generation-guide summary span {
  font-size: 10px;
  color: var(--muted);
  font-weight: 400;
}
.evidence-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin: 16px 0;
}
.evidence-grid article {
  background: #f7f9f4;
  border: 1px solid #e8ece2;
  border-radius: 8px;
  padding: 13px;
}
.evidence-grid small {
  display: block;
  color: var(--green);
  font-size: 10px;
  margin-bottom: 5px;
}
.evidence-grid strong {
  font-size: 12px;
  font-weight: 500;
}
.evidence-grid p {
  font-size: 12px;
  color: #68715f;
  margin: 6px 0 0;
  white-space: pre-wrap;
}
.round-selector {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 0 0 14px;
}
.round-selector button {
  flex: 0 0 125px;
  text-align: left;
  display: grid;
  gap: 3px;
}
.round-selector button.chosen {
  border-color: #86a580;
  background: #edf4e9;
}
.round-selector small {
  font-size: 9px;
  letter-spacing: 1px;
  color: var(--muted);
}
.round-selector strong {
  font-size: 12px;
  font-weight: 500;
}
.round-selector span {
  font-size: 10px;
  color: var(--muted);
}
.decision-badge {
  font-size: 10px !important;
  padding: 3px 7px;
  border-radius: 4px;
  background: #f1f2ee;
  color: #6f7668 !important;
}
.decision-badge.accepted {
  background: #e7f2e7;
  color: #316743 !important;
}
.decision-badge.rejected {
  background: #faf0e9;
  color: #9e6540 !important;
}
.round-detail h2 {
  font-size: 18px !important;
}
.hypothesis-reason {
  color: #68715f;
  font-size: 13px;
}
.round-stages {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  padding: 16px 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  gap: 8px;
}
.round-stages i {
  display: inline-block;
  background: #c9cec3;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 5px;
}
.round-stages .received i {
  background: var(--green);
}
.round-stages span {
  font-size: 11px;
}
.round-stages small {
  display: block;
  font-size: 9px;
  color: var(--muted);
  margin-top: 4px;
}
.round-section {
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
.round-section:last-child {
  border: 0;
  padding-bottom: 0;
}
.round-section p {
  white-space: pre-wrap;
  font-size: 12px;
}
.round-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.round-metrics article {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 10px;
  min-width: 0;
}
.round-metrics small {
  font-size: 9px;
  overflow-wrap: anywhere;
  color: var(--muted);
  display: block;
}
.round-metrics strong {
  font-size: 17px;
  font-weight: 500;
  display: block;
  margin-top: 6px;
}
.feedback-facts {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 10px;
  font-size: 12px;
  margin: 16px 0;
}
.feedback-facts dt {
  color: var(--muted);
}
.feedback-facts dd {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.feedback-note {
  font-size: 11px;
  background: #f6f8f1;
  border-left: 2px solid #9daf8a;
  padding: 12px;
  color: #68715f;
}
@media (max-width: 620px) {
  .research-flow {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .evidence-grid {
    grid-template-columns: 1fr;
  }
  .round-stages {
    grid-template-columns: 1fr 1fr;
  }
  .round-metrics {
    grid-template-columns: 1fr;
  }
}

.studio {
  --ink: #242923;
  --muted: #7b8078;
  --line: #e1e5dd;
  --green: #17674e;
  --paper: #fff;
  display: grid;
  grid-template-columns: 230px minmax(400px, 1fr) minmax(370px, 440px);
  flex: 1;
  min-height: 0;
  width: 100%;
  background: #f3f4f0;
  color: var(--ink);
  font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 13px;
  line-height: 1.6;
  gap: 10px;
  padding: 10px;
  box-sizing: border-box;
  overflow: hidden;
}
.studio * {
  box-sizing: border-box;
}
.rail,
.workspace,
.results {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--paper);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.rail {
  display: flex;
  flex-direction: column;
  padding: 22px 14px;
  overflow-y: auto;
}
.brand {
  display: flex;
  gap: 10px;
  align-items: center;
  color: var(--ink);
  font-weight: 700;
  font-size: 12px;
  letter-spacing: 0.6px;
  text-decoration: none;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  background: #232a24;
  color: white;
  border-radius: 10px;
  font-family: Georgia, serif;
  font-size: 26px;
}
.brand small {
  display: block;
  font-size: 11px;
  color: var(--muted);
  font-weight: 400;
  letter-spacing: 0;
}
.rail-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--muted);
  font-size: 11px;
  margin: 30px 8px 10px;
  letter-spacing: 1px;
}
.rail-label span {
  font-size: 9px;
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0 4px;
}
.studio button,
.studio input,
.studio textarea,
.studio select {
  font: inherit;
}
.studio button {
  cursor: pointer;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 12px;
  background: white;
  color: var(--ink);
  transition: background 0.15s;
}
.studio button:hover {
  background: #edf2e9;
}
.studio button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.studio button:focus-visible,
.studio input:focus-visible,
.studio textarea:focus-visible,
.studio select:focus-visible {
  outline: 2px solid var(--green);
  outline-offset: 2px;
}
.studio nav {
  display: grid;
  gap: 6px;
}
.studio nav button {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 0;
  text-align: left;
  padding: 11px 10px;
}
.studio nav button.selected {
  background: #252b26;
  color: white;
}
.nav-symbol {
  font-size: 19px;
  width: 22px;
}
.nav-count {
  margin-left: auto;
  font-size: 11px;
  opacity: 0.6;
}
.studio .mode {
  text-align: left;
  border: 0;
  padding: 10px;
  margin-bottom: 3px;
  background: #fafbf8;
}
.mode small {
  display: block;
  font-size: 11px;
  color: var(--muted);
}
.studio .mode.chosen {
  box-shadow: inset 3px 0 var(--green);
  background: #eff4ed;
}
.rail-bottom {
  margin-top: auto;
  padding: 30px 8px 0;
  font-size: 12px;
}
.rail-bottom small {
  display: block;
  margin: 6px 0 16px;
  color: var(--muted);
}
.rail-bottom a {
  color: var(--muted);
}
.rail-bottom i,
.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #b4b9af;
  margin-right: 7px;
}
.rail-bottom i.online,
.status-dot.active {
  background: #318364;
}
.workspace,
.results {
  display: flex;
  flex-direction: column;
}
.workspace-head,
.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22px 26px;
  border-bottom: 1px solid var(--line);
  gap: 10px;
}
.eyebrow {
  font-size: 9px;
  letter-spacing: 1.5px;
  color: var(--muted);
  font-weight: 600;
}
.studio h1 {
  font-size: 23px;
  letter-spacing: -0.5px;
  margin: 4px 0 0;
  font-weight: 600;
}
.studio h2 {
  font-size: 22px;
  line-height: 1.45;
  margin: 12px 0;
}
.studio h3 {
  font-size: 14px;
  margin: 0 0 8px;
  font-weight: 600;
}
.workspace-body {
  padding: 28px;
  overflow: auto;
  flex: 1;
  min-height: 0;
}
.intro {
  padding: 0 0 25px;
}
.index {
  font-size: 10px;
  letter-spacing: 1.5px;
  color: var(--green);
}
.intro p {
  color: var(--muted);
  max-width: 600px;
  margin: 10px 0 0;
  font-size: 13px;
}
.tag {
  font-size: 10px;
  padding: 3px 8px;
  border: 1px solid var(--line);
  border-radius: 5px;
  white-space: nowrap;
  color: #68715f;
  background: #fafbf8;
}
.workflow {
  display: flex;
  margin: 0 0 24px;
  border: 1px solid var(--line);
  border-radius: 9px;
  overflow: hidden;
}
.workflow span {
  flex: 1;
  font-size: 11px;
  text-align: center;
  padding: 12px 3px;
  background: linear-gradient(120deg, #f6f8f2, #fff);
  border-right: 1px solid var(--line);
}
.surface {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 18px;
}
.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin: 12px 0;
}
.section-heading h3 {
  margin: 0;
}
.section-heading > span {
  font-size: 10px;
  color: var(--muted);
}
.studio label {
  display: block;
  font-size: 11px;
  color: #697160;
  margin: 10px 0;
}
.studio input:not([type="checkbox"]),
.studio select,
.studio textarea {
  display: block;
  width: 100%;
  border: 1px solid var(--line);
  background: #fcfdfb;
  border-radius: 7px;
  padding: 9px 10px;
  color: var(--ink);
  margin-top: 5px;
  min-width: 0;
}
.studio textarea {
  resize: vertical;
  min-height: 88px;
}
.studio input[type="checkbox"] {
  accent-color: var(--green);
  width: 16px;
  height: 16px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}
.hint {
  font-size: 11px;
  color: var(--muted);
  margin: 12px 0;
  line-height: 1.8;
}
.actions {
  display: flex;
  gap: 10px;
  margin-top: 18px;
}
.studio .primary {
  background: #252d26;
  border-color: #252d26;
  color: white;
}
.studio .primary:hover {
  background: #175b43;
}
.studio .text-button {
  border: 0;
  padding: 2px;
  background: transparent;
  font-size: 11px;
  color: var(--muted);
}
.empty {
  text-align: center;
  padding: 45px 18px;
  border: 1px dashed var(--line);
  border-radius: 12px;
  color: var(--muted);
  background: radial-gradient(ellipse at top, #f5f7f0, transparent);
}
.empty > span {
  font-size: 30px;
  color: #a2ad98;
  display: block;
  margin-bottom: 16px;
}
.empty h3 {
  color: #626c5a;
}
.empty p {
  font-size: 12px;
}
.hypothesis p {
  white-space: pre-wrap;
}
.studio pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font:
    11px/1.9 "SFMono-Regular",
    Consolas,
    monospace;
  max-width: 100%;
  margin: 12px 0;
}
.studio summary {
  cursor: pointer;
  font-size: 12px;
  padding: 12px 0;
  font-weight: 600;
}
.interaction {
  border-color: #a5b99b;
  background: #f8faf5;
}
.studio .json-input {
  font:
    12px/1.8 "SFMono-Regular",
    Consolas,
    monospace;
  min-height: 180px;
}
.factor-title {
  display: flex;
  gap: 9px;
  align-items: center;
}
.factor-title input:not([type="checkbox"]) {
  margin: 0;
  border: 0;
  font-weight: 600;
  background: transparent;
  padding: 2px;
}
.expression {
  font-family: "SFMono-Regular", Consolas, monospace !important;
  min-height: 60px !important;
}
.factor-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.factor-meta label {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
}
.factor-meta input {
  max-width: 80px;
}
.factor-meta span {
  font-size: 10px;
  color: var(--muted);
}
.code-toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.code-toolbar select {
  margin: 0;
  flex: 1;
}
.code-panel {
  border-radius: 12px;
  background: #202923;
  color: #dfe8dc;
  overflow: hidden;
}
.code-caption {
  display: flex;
  justify-content: space-between;
  padding: 13px 16px;
  border-bottom: 1px solid #3a443d;
  font-size: 10px;
  color: #adb9a8;
}
.code-panel pre {
  padding: 12px 20px;
  max-height: 680px;
  overflow: auto;
  white-space: pre;
  font-size: 12px;
}
.run-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  width: 100%;
  text-align: left;
  margin-bottom: 10px;
  padding: 16px !important;
}
.run-row small {
  display: block;
  color: var(--muted);
  font-size: 10px;
  margin-top: 5px;
}
.run-row.chosen {
  border-color: #93ad87;
  background: #f6f9f2;
}
.result-head {
  padding: 22px 20px;
}
.result-head h2 {
  font-size: 18px;
  margin: 5px 0 0;
}
.result-scroll {
  padding: 0 20px 20px;
  overflow: auto;
  flex: 1;
  min-height: 0;
}
.config-block {
  padding: 6px 0 20px;
}
.wide {
  width: 100%;
}
.result-tabs {
  display: flex;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 12px 0;
  gap: 5px;
  position: sticky;
  top: 0;
  background: white;
  z-index: 1;
}
.result-tabs button {
  flex: 1;
  border: 0;
  font-size: 12px;
  padding: 7px 3px;
}
.result-tabs button.selected {
  background: #edf3e9;
  color: var(--green);
}
.metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 18px 0;
}
.metrics article {
  border: 1px solid var(--line);
  padding: 12px;
  border-radius: 9px;
}
.metrics small {
  color: var(--muted);
  font-size: 10px;
  display: block;
}
.metrics strong {
  display: block;
  font-size: 22px;
  font-weight: 500;
  letter-spacing: -0.5px;
  margin-top: 5px;
  font-variant-numeric: tabular-nums;
}
.compact {
  margin-top: 18px;
  padding: 34px 16px;
}
.table-scroll {
  overflow: auto;
  max-height: 350px;
}
.studio table {
  width: 100%;
  border-collapse: collapse;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}
.studio th,
.studio td {
  text-align: right;
  border-bottom: 1px solid var(--line);
  padding: 9px 4px;
  white-space: nowrap;
}
.studio th:first-child,
.studio td:first-child {
  text-align: left;
}
.notice {
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.notice.error {
  background: #fff3ef;
  color: #9d4130;
  border-bottom: 1px solid #edc9bc;
}
.agent-metrics {
  display: flex;
  gap: 10px;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
  font-size: 11px;
  overflow-wrap: anywhere;
}
.agent-metrics span {
  min-width: 0;
}
.results iframe {
  width: 100%;
  height: 400px;
  border: 0;
  margin-top: 16px;
}
.logs {
  max-height: 380px;
  overflow: auto;
  color: #6c7564;
  background: #f8f9f6;
  padding: 12px;
}
.event {
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.event small {
  color: var(--green);
}
@media (min-width: 1600px) {
  .studio {
    grid-template-columns: 250px minmax(500px, 1fr) 500px;
  }
  .workspace-body {
    padding: 36px 42px;
  }
}
@media (max-width: 1150px) {
  .studio {
    grid-template-columns: 190px minmax(330px, 1fr) 340px;
    gap: 6px;
    padding: 6px;
  }
  .workspace-body {
    padding: 20px;
  }
  .workspace-head {
    padding: 20px;
  }
  .rail {
    padding: 20px 10px;
  }
  .brand {
    font-size: 10px;
  }
  .result-scroll {
    padding: 0 14px 14px;
  }
}
@media (max-width: 950px) {
  .studio {
    grid-template-columns: 180px minmax(0, 1fr);
    overflow: auto;
  }
  .rail {
    grid-row: 1/3;
  }
  .workspace {
    min-height: 650px;
    overflow: visible;
  }
  .workspace-body {
    overflow: visible;
  }
  .results {
    grid-column: 2;
    min-height: 650px;
  }
  .result-scroll {
    overflow: visible;
  }
  .workspace-head > .tag {
    display: none;
  }
}
@media (max-width: 620px) {
  .studio {
    display: block;
    overflow: auto;
    padding: 8px;
  }
  .rail {
    margin-bottom: 8px;
    padding: 14px;
  }
  .rail nav {
    display: grid;
    grid-template-columns: 1fr 1fr;
    margin-top: 12px;
  }
  .rail .mode,
  .rail .rail-label,
  .rail .rail-bottom,
  .rail > select,
  .rail > .hint {
    display: none;
  }
  .workspace,
  .results {
    margin-bottom: 8px;
    min-height: 0;
  }
  .workspace-body {
    padding: 18px;
  }
  .workspace-head {
    padding: 18px;
  }
  .intro h2 {
    font-size: 21px;
  }
  .factor-title {
    flex-wrap: wrap;
  }
  .factor-title input:not([type="checkbox"]) {
    width: 65%;
  }
  .code-toolbar {
    flex-wrap: wrap;
  }
  .result-scroll {
    padding: 0 18px 18px;
  }
  .results iframe {
    height: 300px;
  }
}
@media (prefers-reduced-motion: no-preference) {
  .intro {
    animation: appear 0.35s ease-out;
  }
  @keyframes appear {
    from {
      opacity: 0;
      transform: translateY(5px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
}
</style>
