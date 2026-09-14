<template>
  <div ref="host" class="equity-chart" role="img" aria-label="策略扣费净值、基准净值与回撤图"></div>
</template>
<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue';
import * as echarts from 'echarts';
const props = defineProps({ rows: { type: Array, default: () => [] } });
const host = ref(null);
let chart, observer;
function render() {
  if (!chart) return;
  chart.setOption({
    color: ['#14765a', '#989da5', '#c26052'],
    tooltip: { trigger: 'axis' }, legend: { top: 4, data: ['策略净值（扣费）', '基准净值', '回撤'] },
    grid: [{ left: 54, right: 18, top: 44, height: '49%' }, { left: 54, right: 18, top: '72%', height: '17%' }],
    xAxis: [{ type: 'category', data: props.rows.map(r => r.date), axisLabel: { show: false } },
      { type: 'category', gridIndex: 1, data: props.rows.map(r => r.date) }],
    yAxis: [{ type: 'value', scale: true, splitLine: { lineStyle: { color: '#edf0ec' } } },
      { type: 'value', gridIndex: 1, axisLabel: { formatter: '{value}%' } }],
    series: [
      { name: '策略净值（扣费）', type: 'line', symbol: 'none', data: props.rows.map(r => r.equity) },
      { name: '基准净值', type: 'line', symbol: 'none', lineStyle: { type: 'dashed' }, data: props.rows.map(r => r.benchmark) },
      { name: '回撤', type: 'line', symbol: 'none', xAxisIndex: 1, yAxisIndex: 1, areaStyle: { opacity: .12 }, data: props.rows.map(r => r.drawdown == null ? null : +(r.drawdown * 100).toFixed(3)) },
    ],
  }, true);
}
onMounted(() => { chart = echarts.init(host.value); observer = new ResizeObserver(() => chart.resize()); observer.observe(host.value); render(); });
watch(() => props.rows, render);
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose(); });
</script>
<style scoped>.equity-chart { height: 350px; width: 100%; }</style>
