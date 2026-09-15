<template>
  <section class="surface" v-if="instruments.length">
    <div class="section-heading">
      <h3>持仓与标的收益</h3>
      <span>{{ holdings?.positions.length ?? 0 }} 只在手 · 共 {{ instruments.length }} 只交易过</span>
    </div>
    <div class="cards">
      <div><small>持仓市值</small><strong>{{ money(marketValue) }}</strong></div>
      <div><small>现金</small><strong>{{ money(holdings?.cash) }}</strong></div>
      <div><small>手续费合计</small><strong>{{ money(totalCost) }}</strong></div>
    </div>
    <input v-model="instrumentQuery" placeholder="搜索合约代码" aria-label="搜索标的" style="margin: 4px 0 8px; width: 100%" />
    <div class="table-scroll">
      <table>
        <thead><tr><th>标的</th><th class="num">成交笔数</th><th class="num">在手市值</th><th class="num">手续费</th><th class="num">最终收益</th></tr></thead>
        <tbody>
          <tr v-for="row in visibleInstruments" :key="row.instrument">
            <td><code>{{ row.instrument }}</code> <span v-if="row.held" class="tag ok">持有</span></td>
            <td class="num">{{ row.trades }}</td>
            <td class="num">{{ row.holding_value ? money(row.holding_value) : "—" }}</td>
            <td class="num">{{ money(row.cost) }}</td>
            <td class="num" :class="row.pnl >= 0 ? 'pos' : 'neg'">{{ money(row.pnl) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="filteredInstruments.length > instrumentLimit" class="hint" style="text-align: center; margin: 8px 0 0">
      <button class="text-button" @click="instrumentLimit += 20">展开更多（还有 {{ filteredInstruments.length - instrumentLimit }} 只）</button>
    </p>
  </section>

  <section class="surface" v-if="trades.length">
    <div class="section-heading">
      <h3>交易时间线</h3>
      <span>共 {{ filteredTrades.length }} 笔 · 第 {{ page }} / {{ pageCount }} 页</span>
    </div>
    <input v-model="tradeQuery" placeholder="搜索合约代码或日期" aria-label="搜索成交" style="margin: 4px 0 8px; width: 100%" />
    <div class="table-scroll">
      <table>
        <thead><tr><th>时间</th><th>标的</th><th>方向</th><th class="num">价格</th><th class="num">数量</th><th class="num">金额</th><th class="num">手续费</th></tr></thead>
        <tbody>
          <tr v-for="(t, i) in pagedTrades" :key="`${t.date}-${t.instrument}-${i}`">
            <td>{{ t.date }}</td>
            <td><code>{{ t.instrument }}</code></td>
            <td :class="t.direction === 'buy' ? 'pos' : 'neg'">{{ t.direction === "buy" ? "买入" : "卖出" }}</td>
            <td class="num">{{ t.price.toFixed(3) }}</td>
            <td class="num">{{ Math.round(t.amount).toLocaleString() }}</td>
            <td class="num">{{ money(t.value) }}</td>
            <td class="num">{{ money(t.cost) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="actions" style="justify-content: center">
      <button :disabled="page <= 1" @click="page--">上一页</button>
      <span class="hint">{{ page }} / {{ pageCount }}</span>
      <button :disabled="page >= pageCount" @click="page++">下一页</button>
    </div>
    <p class="hint" style="margin: 8px 0 0">价格为 Qlib 复权价，与交易所原始报价不同。</p>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Holding, InstrumentSummary, Trade } from "../../api/studio";

const props = defineProps<{
  trades: Trade[];
  instruments: InstrumentSummary[];
  holdings?: { positions: Holding[]; cash: number | null; total: number | null };
}>();
const PAGE = 20;
const instrumentQuery = ref("");
const tradeQuery = ref("");
const instrumentLimit = ref(20);
const page = ref(1);

const money = (v?: number | null) =>
  typeof v === "number" && Number.isFinite(v) ? "¥" + v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
const marketValue = computed(() => props.holdings?.positions.reduce((s, p) => s + p.value, 0) ?? null);
const totalCost = computed(() => props.trades.reduce((s, t) => s + t.cost, 0));

const filteredInstruments = computed(() => {
  const q = instrumentQuery.value.trim().toUpperCase();
  return q ? props.instruments.filter((r) => r.instrument.toUpperCase().includes(q)) : props.instruments;
});
const visibleInstruments = computed(() => filteredInstruments.value.slice(0, instrumentLimit.value));
const filteredTrades = computed(() => {
  const q = tradeQuery.value.trim().toUpperCase();
  return q ? props.trades.filter((t) => t.instrument.toUpperCase().includes(q) || t.date.includes(q)) : props.trades;
});
const pageCount = computed(() => Math.max(1, Math.ceil(filteredTrades.value.length / PAGE)));
const pagedTrades = computed(() => filteredTrades.value.slice((page.value - 1) * PAGE, page.value * PAGE));
watch([tradeQuery, () => props.trades], () => { page.value = 1; });
watch([instrumentQuery, () => props.instruments], () => { instrumentLimit.value = 20; });
</script>
